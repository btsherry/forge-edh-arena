"""The advisor runner (advisor_runner.py) apart from the deals: the lifecycle (feed numbers, a gameId change
resets and re-arms the governor, a resume consumes the backlog quietly); the Ask field; the carried context's
bound; the table roster rule; the r<round>-t<turn> labels and the stat-first snapshot read; the auto-pass
receipts collapsing to one line per turn; the Executive take-over (the toggle file starts a seat-0 runner on the
ADVISOR'S OWN brain, never rotates while executive); the [quip:] and [bark:] vocabularies and the quip guide
switching on the voice state file; the one tool, arena-public-state.py, allowlisted for the advisor alone.
Run: python3 -m unittest discover -s tests"""
import functools
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import advisor_runner as ar  # noqa: E402
import voice_runner as vr  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402
from tests.support import advisor_brain  # noqa: E402

FIX_ENGINE = Path(__file__).parent / "fixtures" / "engine"
AskBrain = advisor_brain("Hold it — the flyers are the real threat.")
LifecycleBrain = advisor_brain("advice text")
QuipBrain = advisor_brain("Hold the Boots until Urza taps out. [quip:calculating]")
BarkBrain = advisor_brain("Purphoros swung fourteen into Urza. [bark:1:that-hurt]")
ContextBrain = advisor_brain("advice")


VOICES = {1: {"library": "harry", "voice": "Harry", "temperament": "fiery young warrior"},
          2: {"library": "bill", "voice": "Bill", "temperament": "elder professor"},
          3: {"library": "lily", "voice": "Lily", "temperament": "warm and wise"}}


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "arena-public-state.py"


SNAP = {
    "kind": "observer-snapshot", "timestamp": 1788800000000, "turn": 12, "activeSeat": 1, "phase": "MAIN1", "gameOver": False,
    "seats": [
        {"seat": 0, "name": "Human", "eliminated": False, "life": 31, "poison": 0, "handSize": 4, "librarySize": 80,
         "battlefield": [{"id": 1, "name": "Selvala, Heart of the Wilds", "power": 2, "toughness": 4, "sick": False, "types": "Legendary Creature", "tapped": True,
                          "counters": {"P1P1": 2}, "auras": ["Swiftfoot Boots"]}],
         "graveyard": ["Beast Within"], "exile": [], "commandZone": []},
        {"seat": 1, "name": "mailbox-seat1-Urza", "eliminated": False, "life": 40, "poison": 0, "handSize": 3, "librarySize": 88,
         "battlefield": [{"id": 9, "name": "Isochron Scepter", "types": "Artifact", "tapped": False, "imprinted": ["Pact of Negation"]}],
         "graveyard": [], "exile": ["Pact of Negation"], "commandZone": ["Urza, Lord High Artificer"]},
    ],
    "stack": ["Purphoros, God of the Forge"],
    "stackDetail": [{"kind": "trigger", "name": "Purphoros, God of the Forge", "owner": 3, "targets": ["seat 0"]}],
}


class AdvisorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = LifecycleBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0,
                                  log_dir=base / "logs")
        self.r.inbox.mkdir(parents=True)
        self.r.RANDOM_ADMIT_P = 1.0   # deterministic admission for these tests

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def _write(self, kind, n, body):
        body = dict(body)
        body.setdefault("seq", n)
        (self.r.inbox / f"{kind}-{n}.json").write_text(json.dumps(body))

    def _req(self, n, turn, gid="g1"):
        self._write("req", n, {"gameId": gid, "turn": turn, "phase": "MAIN1",
                               "decisionType": "PRIORITY", "prompt": "act or pass",
                               "state": {}, "options": []})

    def test_interleaved_numbers_in_one_game_do_not_reset(self):
        self._req(7, 3)
        self._write("digest", 9, {"gameId": "g1", "turn": 2, "digest": ["a", "b"]})
        self.r._process(self.r._scan())
        self._write("chosen", 7, {"gameId": "g1", "decisionType": "PRIORITY", "chosen": "pass"})
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 0, "7 after 9 is ordinary interleaving, not a new game")
        self.assertEqual(self.r.game_id, "g1")

    def test_game_id_change_resets_and_rearms_the_governor(self):
        self._req(40, 25)
        self.r._process(self.r._scan())
        self.assertEqual(self.r.gov_turn, 25)
        self._req(1, 1, gid="g2")
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 1)
        self.assertEqual(self.r.game_id, "g2")
        self.assertEqual(self.r.gov_turn, 1, "the governor re-armed for the new game's turn 1")
        self.assertEqual(len(self.r.brain.decisions), 2, "turn 1 of game 2 was advised")

    def test_resume_consumes_backlog_quietly(self):
        self._write("note", 3, {"gameId": "g1", "turn": 4, "phase": "MAIN1", "note": "(auto-passed)"})
        self._write("chosen", 2, {"gameId": "g1", "decisionType": "PRIORITY", "chosen": "pass"})
        self._write("digest", 4, {"gameId": "g1", "turn": 4, "digest": ["x"]})
        self._req(5, 5)
        n = self.r._process(self.r._scan(), quiet=True)
        self.assertEqual(n, 4)
        self.assertEqual(self.r.brain.decisions, [], "no advice on a stale backlog")
        stream = self.r._stream.read_text() if self.r._stream.exists() else ""
        self.assertNotIn("(auto-passed)", stream, "stale notes are not streamed on resume")
        self.assertTrue(any("the human chose" in c for c in self.r.pending_context))
        self.assertTrue(any("turn 4 public log" in c for c in self.r.pending_context))
        kinds = [json.loads(l)["kind"] for l in self.r._jsonl.read_text().splitlines()]
        self.assertIn("skipped_backlog", kinds)
        self.assertEqual(list(self.r.inbox.iterdir()), [], "backlog consumed")

    def test_unstamped_feed_keeps_seq_heuristic_on_monotonic_kinds_only(self):
        self._write("req", 9, {"turn": 3, "phase": "MAIN1", "decisionType": "PRIORITY",
                               "prompt": "x", "state": {}, "options": []})
        self.r._process(self.r._scan())
        self._write("chosen", 7, {"decisionType": "PRIORITY", "chosen": "pass"})
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 0, "a chosen file never signals a new game")
        self._write("req", 1, {"turn": 1, "phase": "MAIN1", "decisionType": "PRIORITY",
                               "prompt": "x", "state": {}, "options": []})
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 1, "an unstamped req regression still does")


class AdvisorAskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = AskBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0,
                                  log_dir=base / "logs")
        self.r.inbox.mkdir(parents=True)
        self.asks = base / "logs" / "control" / "ask"
        self.asks.mkdir(parents=True)

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def _ask(self, name, body):
        p = self.asks / name
        p.write_text(body if isinstance(body, str) else json.dumps(body))
        return p

    def _stream(self):
        return self.r._stream.read_text() if self.r._stream.exists() else ""

    def _records(self, kind):
        if not self.r._jsonl.exists():
            return []
        out = []
        for line in self.r._jsonl.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("kind") == kind:
                out.append(rec)
        return out

    def _asked(self, prompt):
        return prompt.split("ASKS: ")[1].split("\n")[0]

    def test_question_is_answered_streamed_recorded_and_consumed(self):
        (self.r.inbox / "req-3.json").write_text(json.dumps(
            {"gameId": "g1", "seq": 3, "turn": 12, "phase": "MAIN1", "decisionType": "PRIORITY",
             "prompt": "act", "state": {}, "options": []}))
        self.r._process(self.r._scan(), quiet=True)   # sets the turn label without advising
        p = self._ask("ask-1700000000000-001.json", {"ask": "Should I attack with everything?", "ts": 1})
        self.assertEqual(self.r._handle_asks(), 1)
        self.assertFalse(p.exists(), "the file is deleted on pickup — that is the panel's 'sent' signal")
        self.assertEqual(len(self.r.brain.decisions), 1)
        self.assertIn("THE HUMAN AT YOUR SEAT ASKS: Should I attack with everything?",
                      self.r.brain.decisions[0])
        s = self._stream()
        self.assertIn("[r3-t12 · you] Should I attack with everything?", s)
        self.assertIn("[r3-t12 · advisor] Hold it — the flyers are the real threat.", s)
        rec = self._records("ask")
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["text"], "Should I attack with everything?")
        self.assertEqual(rec[0]["answer"], self.r.brain.reply)
        self.assertEqual(rec[0]["turn"], 12)

    def test_pending_context_folds_into_the_question_once(self):
        self.r._push_context("- the human chose \"pass\" for PRIORITY (seq 3)")
        self._ask("ask-1700000000000-001.json", {"ask": "why did that matter?"})
        self.r._handle_asks()
        self.assertIn("SINCE LAST TIME:", self.r.brain.decisions[0])
        self.assertEqual(self.r.pending_context, [], "context is consumed by the call that used it")

    def test_questions_answer_in_numeric_send_order(self):
        # sorted by (millis, serial) as integers, never lexically
        self._ask("ask-1700000000001-002.json", {"ask": "second"})
        self._ask("ask-1700000000000-010.json", {"ask": "first"})
        self._ask("ask-1700000000001-003.json", {"ask": "third"})
        self.assertEqual(self.r._handle_asks(), 3)
        self.assertEqual([self._asked(d) for d in self.r.brain.decisions],
                         ["first", "second", "third"])

    def test_malformed_or_empty_questions_are_dropped_not_re_read(self):
        self._ask("ask-1700000000000-001.json", "{not json")       # torn/partial write
        self._ask("ask-1700000000000-002.json", {"ask": "   "})     # blank
        self._ask("ask-1700000000000-003.json", {"nope": 1})        # wrong key
        self._ask("ask-1700000000000-004.json", {"ask": 42})        # wrong type
        self.assertEqual(self.r._handle_asks(), 0)
        self.assertEqual(self.r.brain.decisions, [])
        # the unparseable one is left for the next poll (it may still be being
        # written); the parseable-but-useless ones are consumed and recorded
        self.assertEqual(sorted(p.name for p in self.asks.iterdir()),
                         ["ask-1700000000000-001.json"])
        self.assertEqual(len(self._records("ask_rejected")), 3)

    def test_long_question_is_capped_and_whitespace_collapsed(self):
        self._ask("ask-1700000000000-001.json", {"ask": "a  b\n\nc " + "x" * 900})
        self.r._handle_asks()
        asked = self._asked(self.r.brain.decisions[0])
        self.assertTrue(asked.startswith("a b c xxx"))
        self.assertEqual(len(asked), ar.ASK_MAX_CHARS)

    def test_empty_reply_is_said_not_swallowed(self):
        self.r.brain.reply = ""
        self._ask("ask-1700000000000-001.json", {"ask": "hello?"})
        self.r._handle_asks()
        self.assertIn("[t? · advisor] (no answer", self._stream())

    def test_missing_ask_dir_is_quiet(self):
        shutil.rmtree(self.asks)
        self.assertEqual(self.r._handle_asks(), 0)

    def test_asks_run_before_the_pause_gate_in_the_main_loop(self):
        # Structural pin: run() consults the asks before it reads the pause
        # toggle, so a paused advisor still answers a typed question.
        src = inspect.getsource(ar.AdvisorRunner.run)
        self.assertLess(src.index("self._handle_asks()"), src.index("self._toggle_enabled()"))


class AdvisorContextBound(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = ContextBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0,
                                  log_dir=base / "logs")

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def test_bound_drops_oldest_and_says_so(self):
        for i in range(ar.CONTEXT_MAX_LINES + 10):
            self.r._push_context(f"- line {i}")
        self.assertEqual(len(self.r.pending_context), ar.CONTEXT_MAX_LINES)
        self.assertEqual(self.r.pending_context[0], "- line 10")
        self.assertEqual(self.r._context_dropped, 10)
        self.r._advise({"seq": 1, "turn": 3, "phase": "MAIN1", "decisionType": "CAST_SPELL",
                        "prompt": "p", "state": {}, "options": []})
        prompt = self.r.brain.decisions[-1]
        self.assertIn("10 earlier line(s) dropped", prompt)
        self.assertIn("- line 49", prompt)
        self.assertNotIn("- line 9\n", prompt)
        self.assertEqual(self.r.pending_context, [])
        self.assertEqual(self.r._context_dropped, 0)

    def test_guarded_writes_survive_a_missing_log_dir(self):
        self.r._stream = Path(self.tmp.name) / "gone" / "advisor-0.log"
        self.r._jsonl = Path(self.tmp.name) / "gone" / "advisor-0.jsonl"
        self.r._stream_write("x")          # must not raise
        self.r._record("note", {"a": 1})


class TableRosterRule(unittest.TestCase):
    ROSTER = ar.DEFAULT_TABLE.split()

    def test_default_order_is_urza_giada_purphoros_selvala(self):
        self.assertEqual(self.ROSTER, ["urza-lord-high-artificer", "giada-font-of-hope",
                                       "purphoros-god-of-the-forge", "selvala-heart-of-the-wilds"])

    def test_human_on_selvala_faces_the_first_three(self):
        self.assertEqual(ar.table_opponents("selvala-heart-of-the-wilds", self.ROSTER),
                         ["urza-lord-high-artificer", "giada-font-of-hope",
                          "purphoros-god-of-the-forge"])

    def test_human_on_a_non_roster_deck_faces_the_first_three(self):
        self.assertEqual(ar.table_opponents("sheoldreds-sacrifice", self.ROSTER),
                         self.ROSTER[:3])

    def test_human_on_a_roster_deck_removes_only_that_deck(self):
        self.assertEqual(ar.table_opponents("giada-font-of-hope", self.ROSTER),
                         ["urza-lord-high-artificer", "purphoros-god-of-the-forge",
                          "selvala-heart-of-the-wilds"])


class RoundTurnLabels(unittest.TestCase):
    """Ben, 2026-09-08 (game 32): panel lines read r<round>-t<turn>."""
    def test_rounds_follow_the_table_not_a_formula(self):
        import advisor_runner as ar
        tmp = Path(tempfile.mkdtemp(prefix="clk-"))
        st = tmp / "observer-state.json"
        clk = ar.TurnClock(st)
        self.assertEqual(clk.label(1), "r1-t1", "no snapshot: four turns a round")
        self.assertEqual(clk.label(5), "r2-t5"); self.assertEqual(clk.label(13), "r4-t13")
        # game 33's order: seat 1 started; the human is seat 0
        clk = ar.TurnClock(st)
        order = {1: 1, 2: 2, 3: 3, 4: 0, 5: 1, 6: 2, 7: 3, 8: 0, 9: 1}
        labels = {}
        for t, active in order.items():
            st.write_text(json.dumps({"turn": t, "activeSeat": active}))
            clk.observe()                      # the poll loop sees the snapshot first
            labels[t] = clk.label(t)
        self.assertEqual(labels[4], "r1-t4"); self.assertEqual(labels[5], "r2-t5", "seat 1 again: round 2 starts at t5")
        self.assertEqual(labels[8], "r2-t8"); self.assertEqual(labels[9], "r3-t9")
        # the snapshot lags a line: label() reads it on demand
        st.write_text(json.dumps({"turn": 10, "activeSeat": 2}))
        self.assertEqual(clk.label(10), "r3-t10")
        # seat 3 eliminated: round 3 is 9 (s1), 10 (s2), 11 (s0); seat 1 again at 12 opens round 4 — three turns a round now
        for t, active in {11: 0, 12: 1, 13: 2}.items():
            st.write_text(json.dumps({"turn": t, "activeSeat": active})); clk.observe()
        self.assertEqual(clk.label(11), "r3-t11", "earlier turns keep their round")
        self.assertEqual(clk.label(12), "r4-t12"); self.assertEqual(clk.label(13), "r4-t13")
        self.assertEqual(clk.label("?"), "t?")
        # a line for a turn the snapshot has not shown yet: same round as the latest known
        self.assertEqual(clk.label(14), "r4-t14")

    def test_snapshot_is_parsed_only_when_it_changes(self):
        """Plan §3 (2026-09-14): stat first; the JSON is read only on a new mtime/size."""
        import advisor_runner as ar
        self.assertEqual(ar.POLL_S, 1.0)
        tmp = Path(tempfile.mkdtemp(prefix="sig-"))
        st = tmp / "observer-state.json"
        clk = ar.TurnClock(st)
        clk.observe(); self.assertEqual(clk.last, {}, "no file: nothing")
        st.write_text(json.dumps({"turn": 7, "activeSeat": 1})); clk.observe()
        self.assertEqual(clk.last["activeSeat"], 1)
        before = st.stat()
        st.write_text(json.dumps({"turn": 7, "activeSeat": 2}))      # same size ...
        os.utime(st, ns=(before.st_atime_ns, before.st_mtime_ns))     # ... same mtime: unchanged to a stat
        clk.observe()
        self.assertEqual(clk.last["activeSeat"], 1, "same mtime and size: not re-parsed")
        os.utime(st, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
        clk.observe()
        self.assertEqual(clk.last["activeSeat"], 2, "a moved mtime: parsed")
        st.write_text("{partial")
        clk.observe()
        self.assertEqual(clk.last["activeSeat"], 2, "a torn write keeps the last snapshot ...")
        st.write_text(json.dumps({"turn": 8, "activeSeat": 3})); clk.observe()
        self.assertEqual(clk.last["turn"], 8, "... and the next change is still seen")

    def test_stream_lines_carry_the_label(self):
        import advisor_runner as ar
        tmp = Path(tempfile.mkdtemp(prefix="lbl-"))

        class FakeBrain:
            deck = "selvala-heart-of-the-wilds"; model = "opus"; effort = "low"; session_id = "s1"
            last_prompt_tokens = 0; totals = {"calls": 0}; backend = None; wedges = 0; calls = 0
            def ensure_session(self, *a, **k): return True
            def reset(self): pass
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = (lambda *a, **k: FakeBrain()), (lambda *a, **k: [])
        try:
            adv = ar.AdvisorRunner("selvala-heart-of-the-wilds", tmp, "opus", "low", 30.0, log_dir=tmp / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        out = []
        adv._stream_write = out.append
        (tmp / "observer-state.json").write_text(json.dumps({"turn": 6, "activeSeat": 1}))
        env = os.environ.get("ARENA_AUTOPASS_RECEIPTS")
        os.environ.pop("ARENA_AUTOPASS_RECEIPTS", None)   # the default: summary
        try:
            adv._show_note({"turn": 6, "note": "(auto-passed — nothing available)"})
            self.assertEqual(out, [], "summary by default: held until the turn moves on")
            adv._show_note({"turn": 7, "note": "(prompt kept — castable: Khalni Ambush)"})
        finally:
            if env is not None:
                os.environ["ARENA_AUTOPASS_RECEIPTS"] = env
        self.assertTrue(out[0].startswith("[r2-t6] ⏭ auto-passed 1 stop"), out)
        self.assertTrue(out[1].startswith("[r2-t7] ⏭ (prompt kept"), out)


class ReceiptSummaryTests(unittest.TestCase):
    """Ben, 2026-09-08: auto-pass receipts collapse to one line per turn in the panel."""
    def _adv(self):
        tmp = Path(tempfile.mkdtemp(prefix="rcpt-"))

        class FakeBrain:
            deck = "selvala-heart-of-the-wilds"; model = "opus"; effort = "low"; session_id = "s1"
            last_prompt_tokens = 0; totals = {"calls": 0}; backend = None; wedges = 0; calls = 0
            def ensure_session(self, *a, **k): return True
            def reset(self): pass
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = (lambda *a, **k: FakeBrain()), (lambda *a, **k: [])
        try:
            adv = ar.AdvisorRunner("selvala-heart-of-the-wilds", tmp, "opus", "low", 30.0, log_dir=tmp / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        out = []
        adv._stream_write = out.append
        import os as _os
        _os.environ["ARENA_AUTOPASS_RECEIPTS"] = "summary"   # explicit (the default since game 32)
        self.addCleanup(lambda: _os.environ.pop("ARENA_AUTOPASS_RECEIPTS", None))
        return adv, out

    def test_one_line_per_turn_with_counts(self):
        adv, out = self._adv()
        for _ in range(3):
            adv._show_note({"turn": 8, "note": "(auto-passed — nothing available)"})
        adv._show_note({"turn": 8, "note": "(auto-passed — only utility activations available: Arbor Elf)"})
        self.assertEqual(out, [], "nothing shown until the turn moves on")
        adv._show_note({"turn": 9, "note": "(auto-passed — nothing available)"})
        self.assertEqual(len(out), 1)
        self.assertIn("[r2-t8] ⏭ auto-passed 4 stops (nothing available ×3, only utility activations available: Arbor Elf)", out[0])

    def test_kept_prompts_show_at_once_and_flush_first(self):
        adv, out = self._adv()
        adv._show_note({"turn": 8, "note": "(auto-passed — nothing available)"})
        adv._show_note({"turn": 8, "note": "(prompt kept — castable: Khalni Ambush)"})
        self.assertEqual(len(out), 1); self.assertIn("prompt kept", out[0])
        adv._show_note({"turn": 9, "note": "(auto-passed — nothing available)"})
        self.assertIn("[r2-t8] ⏭ auto-passed 1 stop (nothing available)", out[1])

    def test_modes_all_and_off(self):
        adv, out = self._adv()
        import os as _os
        _os.environ["ARENA_AUTOPASS_RECEIPTS"] = "all"
        try:
            adv._show_note({"turn": 1, "note": "(auto-passed — nothing available)"})
            self.assertEqual(len(out), 1)
            _os.environ["ARENA_AUTOPASS_RECEIPTS"] = "off"
            adv._show_note({"turn": 1, "note": "(auto-passed — nothing available)"})
            self.assertEqual(len(out), 1)
        finally:
            _os.environ.pop("ARENA_AUTOPASS_RECEIPTS", None)


class ExecutiveTests(unittest.TestCase):
    def test_toggle_file_starts_and_stops_a_seat0_runner_on_the_advisor_brain(self):
        tmp = Path(tempfile.mkdtemp(prefix="exec-"))
        logs = tmp / "logs"
        notes = []

        class FakeBrain:
            deck = "selvala-heart-of-the-wilds"; model = "opus"; effort = "low"; session_id = "s1"
            last_prompt_tokens = 0; totals = {"calls": 0}; backend = None; wedges = 0; calls = 0

            def ensure_session(self, *a, **k): return True
            def reset(self): pass
            def note(self, text, timeout_s=60.0): notes.append(text); return True
            def decide(self, prompt, timeout_s=None, effort=None, deadline=None):
                return {"chosenId": 0}, {"latency_s": 0.1, "usage": None, "cache_read": None, "raw": "{}"}
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = (lambda *a, **k: FakeBrain()), (lambda *a, **k: [])
        try:
            adv = ar.AdvisorRunner("selvala-heart-of-the-wilds", tmp, "opus", "low", 30.0, log_dir=logs)
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        orig_seat = ar.SeatRunner

        class QuickSeat(ar.SeatRunner):           # no engine consumes the exec runner's answers: do not wait the 2 s
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.mb.respond = functools.partial(self.mb.respond, consume_wait_s=0.0)
        ar.SeatRunner = QuickSeat
        self.addCleanup(setattr, ar, "SeatRunner", orig_seat)
        self.assertFalse(adv._executive_wanted())
        self.assertFalse(adv._executive_tick()); self.assertIsNone(adv._exec)
        (logs / "control").mkdir(parents=True, exist_ok=True)
        (logs / "control" / "executive.json").write_text('{"on": true}')
        # a pending seat-0 request in the mailbox
        req = json.loads((FIX_ENGINE / "react.json").read_text())
        req["seat"] = 0; req["seq"] = 1; req["gameId"] = "g1"
        inbox = tmp / "seat-0" / "inbox"; inbox.mkdir(parents=True)
        (inbox / "req-1.json").write_text(json.dumps(req))
        handled = adv._executive_tick()
        self.assertIsNotNone(adv._exec)
        self.assertIsInstance(adv._exec.brain, FakeBrain, "the ADVISOR's brain plays the seat")
        self.assertTrue(any("EXECUTIVE MODE" in n for n in notes), "the hand-off note went to the session")
        self.assertTrue(handled or adv._executive_tick(), "the pending seat-0 request is answered")
        outbox = tmp / "seat-0" / "outbox"
        self.assertTrue(outbox.exists() and any(outbox.iterdir()), "an answer landed in the seat-0 outbox")
        (logs / "control" / "executive.json").write_text('{"on": false}')
        adv._executive_tick()
        self.assertIsNone(adv._exec)
        self.assertTrue(any("ENDED" in n for n in notes))


class AdvisorExecutiveGuards(unittest.TestCase):
    def test_advisor_never_rotates_while_executive_and_tracks_the_seat_game_id(self):   # findings R3, R8
        tmp = Path(tempfile.mkdtemp(prefix="exec-"))

        class FakeBrain:
            deck = "selvala-heart-of-the-wilds"; model = "opus"; effort = "low"; session_id = "s1"
            last_prompt_tokens = 10_000_000; totals = {"calls": 0}; backend = None; wedges = 0; calls = 0
            rotated = 0

            def ensure_session(self, *a, **k): return True
            def reset(self): pass
            def note(self, text, timeout_s=60.0): return True
            def rotate(self, text, timeout_s=120.0): self.rotated += 1; return True
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = (lambda *a, **k: FakeBrain()), (lambda *a, **k: [])
        try:
            adv = ar.AdvisorRunner("selvala-heart-of-the-wilds", tmp, "opus", "low", 30.0, log_dir=tmp / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        (tmp / "logs" / "control").mkdir(parents=True, exist_ok=True)
        (tmp / "logs" / "control" / "executive.json").write_text('{"on": true}')
        adv._executive_tick()
        self.assertIsNotNone(adv._exec)
        adv._exec._game_id = "g-77"
        adv._executive_tick()
        self.assertEqual(adv.game_id, "g-77")
        self.assertFalse(adv._maybe_rotate(), "the seat runner owns rotation while executive")
        self.assertEqual(adv.brain.rotated, 0)
        (tmp / "logs" / "control" / "executive.json").write_text('{"on": false}')
        adv._executive_tick()
        self.assertIsNone(adv._exec)


class QuipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = QuipBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0, log_dir=base / "logs")
        self.r.inbox.mkdir(parents=True)
        self.r.RANDOM_ADMIT_P = 1.0

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def _records(self, kind):
        return [json.loads(l) for l in self.r._jsonl.read_text().splitlines() if json.loads(l).get("kind") == kind]

    def test_split_quip_strips_known_tags_and_drops_unknown_ones(self):
        self.assertEqual(ar.split_quip("Good line. [quip:ouch]"), ("Good line.", "ouch"))
        self.assertEqual(ar.split_quip("Good line. [quip:not-a-thing]"), ("Good line.", None))
        self.assertEqual(ar.split_quip("No tag here."), ("No tag here.", None))
        self.assertEqual(ar.split_quip("Mid [quip:hello] sentence."), ("Mid sentence.", "hello"))
        logs = []
        self.assertEqual(ar.split_quip("Nice line. [quip:nice-swingg]", log=logs.append), ("Nice line.", None))
        self.assertTrue(logs and "nice-swingg" in logs[0], "an unknown id is logged and dropped (review 2026-09-07, R10)")

    def test_advice_prompt_offers_the_vocabulary_and_the_tag_becomes_a_quip_record(self):
        (self.r.inbox / "req-3.json").write_text(json.dumps(
            {"gameId": "g1", "seq": 3, "turn": 5, "phase": "MAIN1", "decisionType": "PRIORITY",
             "prompt": "act", "state": {}, "options": []}))
        self.r._process(self.r._scan())
        self.assertIn("[quip:calculating]", self.r.brain.last_prompt)
        self.assertIn("at most once per game", self.r.brain.last_prompt)
        adv = self._records("advice")
        self.assertEqual(adv[0]["text"], "Hold the Boots until Urza taps out.", "the tag never reaches the panel")
        self.assertNotIn("[quip", self.r._stream.read_text())
        q = self._records("quip")
        self.assertEqual((q[0]["id"], q[0]["turn"], q[0]["with"], q[0]["seq"]), ("calculating", 5, "advice", 3))

    def test_commentary_carries_quips_too(self):
        self.r.brain.reply = "Purphoros just dealt twelve. [quip:ouch]"
        (self.r.inbox / "digest-9.json").write_text(json.dumps({"gameId": "g1", "seq": 9, "turn": 6, "digest": ["a", "b"]}))
        self.r._process(self.r._scan())
        self.assertEqual(self._records("color")[0]["text"], "Purphoros just dealt twelve.")
        self.assertEqual(self._records("quip")[0]["with"], "color")

    def test_a_window_where_an_opponent_targets_you_is_always_advised(self):
        """Game 43: Jwari Disruption on Sheltering Ancient fell to the dice; nobody said 'Earthcraft now'."""
        snap = {"turn": 14, "activeSeat": 0, "seats": [{"seat": 0, "battlefield": [{"name": "Earthcraft"}, {"name": "Forest"}]}],
                "stackDetail": [{"kind": "spell", "name": "Jwari Disruption", "owner": 1, "targets": ["Sheltering Ancient (on the stack)"]},
                                {"kind": "spell", "name": "Sheltering Ancient", "owner": 0}]}
        self.assertEqual(ar.danger_targets(snap), ["Jwari Disruption targets Sheltering Ancient (on the stack)"])
        snap2 = {"seats": [{"seat": 0, "battlefield": [{"name": "Earthcraft"}]}],
                 "stackDetail": [{"name": "Beast Within", "owner": 2, "targets": ["Earthcraft"]}, {"name": "Lightning Bolt", "owner": 3, "targets": ["seat 0"]},
                                 {"name": "Counterspell", "owner": 1, "targets": ["Rhystic Study (on the stack)"]}]}
        self.assertEqual(ar.danger_targets(snap2), ["Beast Within targets Earthcraft", "Lightning Bolt targets you"], "an opponent countering another opponent is not your danger")
        self.assertEqual(ar.danger_targets({"stackDetail": [{"name": "Sol Ring", "owner": 1}]}), [])
        self.assertEqual(ar.danger_targets({}), []); self.assertEqual(ar.danger_targets(None), [])
        # through the governor: dice at zero, budget spent — still admitted
        self.r.RANDOM_ADMIT_P = 0.0
        self.r._clock.last = snap
        ok, why = self.r._admit({"decisionType": "PRIORITY", "turn": 14, "seq": 40})
        self.assertTrue(ok); self.assertTrue(why.startswith("danger: Jwari Disruption targets"), why)
        self.r._clock.last = {"stackDetail": []}
        ok, why = self.r._admit({"decisionType": "PRIORITY", "turn": 14, "seq": 41})
        self.assertEqual((ok, why), (False, "budget"), "no danger: the dice rule as before")

    def test_the_humans_choice_is_recorded_for_the_voice_runner(self):
        (self.r.inbox / "chosen-3.json").write_text(json.dumps({"gameId": "g1", "seq": 3, "decisionType": "PRIORITY", "chosen": "pass"}))
        self.r._process(self.r._scan())
        self.assertEqual(self._records("chosen")[0]["seq"], 3)


class QuipGuide(unittest.TestCase):
    """Ben, 2026-09-08: stock quips are boosted ONLY while live lines are down — the advisor reads the voice state file."""

    def test_advisor_switches_guidance_on_the_state_file(self):
        import advisor_runner as ar
        tmp = Path(tempfile.mkdtemp(prefix="qg-"))
        f = tmp / "state.json"; logs = []
        text, live = ar.quip_guide(f, log=logs.append, prev=None)
        self.assertEqual((text, live), (ar.QUIP_GUIDE_SPARSE, True), "no file: sparse")
        f.write_text(json.dumps({"live": False, "reason": "no ELEVENLABS_API_KEY", "enabled": True}))
        text, live = ar.quip_guide(f, log=logs.append, prev=True)
        self.assertEqual((text, live), (ar.QUIP_GUIDE_DENSE, False))
        self.assertIn("one line in two", text); self.assertIn("stock phrases", text)
        self.assertEqual(len(logs), 1); self.assertIn("no ELEVENLABS_API_KEY", logs[0])
        text, live = ar.quip_guide(f, log=logs.append, prev=False)
        self.assertEqual(len(logs), 1, "same state: no second log line")
        f.write_text(json.dumps({"live": True, "reason": "ok"}))
        text, live = ar.quip_guide(f, log=logs.append, prev=False)
        self.assertEqual((text, len(logs)), (ar.QUIP_GUIDE_SPARSE, 2))
        f.write_text("{not json")
        self.assertEqual(ar.quip_guide(f)[0], ar.QUIP_GUIDE_SPARSE, "unreadable: sparse")
        self.assertIn("at most every other turn", ar.QUIP_GUIDE_SPARSE)


class BarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._env = dict(os.environ)
        os.environ.pop("ARENA_BARKS", None)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections, vr.load_seat_libraries)
        ar.SeatBrain = BarkBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        vr.load_seat_libraries = lambda *a, **kw: dict(VOICES)
        self.r = self._runner()

    def _runner(self):
        base = Path(self.tmp.name) / f"r{len(os.listdir(self.tmp.name))}"
        r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0, log_dir=base / "logs")
        r.inbox.mkdir(parents=True)
        r.RANDOM_ADMIT_P = 1.0
        return r

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections, vr.load_seat_libraries = self._orig
        os.environ.clear(); os.environ.update(self._env)
        self.tmp.cleanup()

    def _records(self, kind):
        return [json.loads(l) for l in self.r._jsonl.read_text().splitlines() if json.loads(l).get("kind") == kind]

    # ---- pure helpers
    def test_vocabulary_matches_the_seat_libraries(self):
        """The ids the advisor may emit are exactly the ids every voice library renders."""
        root = Path(__file__).resolve().parents[1] / "voice" / "stock" / "voices"
        for lib in ("harry", "bill", "lily"):
            m = json.loads((root / lib / "manifest.json").read_text())
            barks = tuple(pid for pid, ph in m["phrases"].items() if ph.get("category") in ("bark", "reaction"))
            self.assertEqual(barks, ar.BARKS, lib)
            others = [pid for pid, ph in m["phrases"].items() if ph.get("category") in ("reply", "patter")]
            self.assertEqual(len(others), 34, f"{lib}: replies and patter are the runner's vocabulary, never the advisor's")
        self.assertEqual(len(ar.BARKS), 32)

    def test_split_bark_strips_known_tags_and_drops_bad_ones(self):
        self.assertEqual(ar.split_bark("Big turn. [bark:2:big-swing]"), ("Big turn.", (2, "big-swing")))
        self.assertEqual(ar.split_bark("Big turn. [bark: 3 : my-turn ]"), ("Big turn.", (3, "my-turn")))
        self.assertEqual(ar.split_bark("Mid [bark:1:taunt] sentence."), ("Mid sentence.", (1, "taunt")))
        self.assertEqual(ar.split_bark("No tag."), ("No tag.", None))
        dropped = []
        self.assertEqual(ar.split_bark("x [bark:1:not-a-thing]", log=dropped.append), ("x", None))
        self.assertEqual(ar.split_bark("x [bark:0:taunt]", log=dropped.append), ("x", None), "never the human seat")
        self.assertEqual(ar.split_bark("x [bark:4:taunt]", log=dropped.append), ("x", None))
        self.assertEqual(len(dropped), 3)
        self.assertIn("unknown id", dropped[0]); self.assertIn("seat must be 1-3", dropped[1])

    def test_guide_names_decks_and_moments_never_the_voices(self):
        decks = {1: "urza-lord-high-artificer", 2: "giada-font-of-hope", 3: "purphoros-god-of-the-forge"}
        g = ar.bark_guide(VOICES, "some", decks)                      # an advice window: optional, sparse
        for frag in ("optional, sparse", "seat 1 (urza-lord-high-artificer): fiery young warrior", "seat 3 (purphoros-god-of-the-forge): warm and wise",
                     "that-hurt when it takes a big hit", "my-turn when it", "Never seat 0", "A quip and a bark never share",
                     "always call a player by their COMMANDER"):
            self.assertIn(frag, g)
        for name in ("Harry", "Bill", "Lily"):
            self.assertNotIn(name, g, "game 38: Joshua called a player 'Bill' — the voice names never reach the model")
        self.assertEqual(ar.bark_guide(VOICES, "off"), "")
        self.assertEqual(ar.bark_guide({}, "some"), "", "no voice libraries, no offer")

    def test_recap_guide_is_shaped_by_whose_turn_it_was(self):
        decks = {1: "urza-lord-high-artificer", 2: "giada-font-of-hope", 3: "purphoros-god-of-the-forge"}
        own = ar.bark_guide(VOICES, "some", decks, owner=2)
        self.assertIn("this recap is seat 2's own turn (giada-font-of-hope)", own)
        self.assertIn("End with exactly ONE tag for seat 2", own)
        self.assertIn("slow-turn if nothing happened", own)
        self.assertNotIn("optional", own.split("Tag form")[0], "the seat's own turn: a tag is expected, not optional")
        human = ar.bark_guide(VOICES, "some", decks, owner=0)
        self.assertIn("this recap is the human's turn", human)
        self.assertIn("(optional)", human); self.assertIn("otherwise no tag", human)
        self.assertEqual(ar.bark_guide(VOICES, "some", decks, owner=None), ar.bark_guide(VOICES, "some", decks))
        self.assertIn("optional, sparse", ar.bark_guide(VOICES, "some", decks, owner=7), "an owner without a voice: the generic offer")

    # ---- through the runner
    def test_colour_reply_bark_becomes_a_record_and_leaves_the_panel_text(self):
        self.r._clock.active_of[6] = 3                                   # the clock saw seat 3 take turn 6
        (self.r.inbox / "digest-9.json").write_text(json.dumps({"gameId": "g1", "seq": 9, "turn": 6, "digest": ["a", "b"]}))
        self.r._process(self.r._scan())
        self.assertIn("this recap is seat 3's own turn", self.r.brain.last_prompt)
        self.assertIn("seat 2 (", self.r.brain.last_prompt); self.assertNotIn("Bill", self.r.brain.last_prompt)
        self.assertEqual(self._records("color")[0]["text"], "Purphoros swung fourteen into Urza.")
        self.assertEqual(self._records("color")[0]["owner"], 3, "the voice runner reads the owner off the colour record")
        self.assertNotIn("[bark", self.r._stream.read_text())
        b = self._records("bark")
        self.assertEqual((b[0]["seat"], b[0]["id"], b[0]["turn"], b[0]["with"], b[0]["seq"]), (1, "that-hurt", 6, "color", 9))

    def test_advice_reply_may_carry_a_bark_and_quip_and_bark_are_both_kept(self):
        self.r.brain.reply = "Block with the angel. [quip:calculating] [bark:3:big-swing]"
        (self.r.inbox / "req-3.json").write_text(json.dumps(
            {"gameId": "g1", "seq": 3, "turn": 5, "phase": "COMBAT_DECLARE_BLOCKERS", "decisionType": "DECLARE_BLOCKERS",
             "prompt": "act", "state": {}, "options": []}))
        self.r._process(self.r._scan())
        self.assertIn("SEAT BARK", self.r.brain.last_prompt)
        self.assertEqual(self._records("advice")[0]["text"], "Block with the angel.")
        self.assertEqual(self._records("quip")[0]["id"], "calculating")
        b = self._records("bark")[0]
        self.assertEqual((b["seat"], b["id"], b["with"]), (3, "big-swing", "advice"))

    def test_barks_off_removes_the_offer_and_ignores_tags(self):
        os.environ["ARENA_BARKS"] = "off"
        self.r = self._runner()
        (self.r.inbox / "digest-9.json").write_text(json.dumps({"gameId": "g1", "seq": 9, "turn": 6, "digest": ["a"]}))
        self.r._process(self.r._scan())
        self.assertNotIn("SEAT BARK", self.r.brain.last_prompt)
        # a tag the model emits anyway is still stripped from the panel; the record is harmless (the voice runner ignores it when off)
        self.assertEqual(self._records("color")[0]["text"], "Purphoros swung fourteen into Urza.")


class PublicStateToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.snap = Path(self.tmp.name) / "observer-state.json"
        self.snap.write_text(json.dumps(SNAP))

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(self.snap), *args],
                              capture_output=True, text=True, timeout=30)

    def test_renders_every_public_zone(self):
        p = self._run()
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout
        for needle in ("TURN 12 — MAIN1 — active seat 1", "STACK (1 items", "trigger Purphoros, God of the Forge [seat 3] -> seat 0",
                       "SEAT 0 Human: life 31, hand 4, library 80", "Selvala, Heart of the Wilds 2/4 (tapped)", "counters P1P1 x2",
                       "attached: Swiftfoot Boots", "graveyard (1): Beast Within", "imprinted: Pact of Negation",
                       "command zone: Urza, Lord High Artificer", "exile (1): Pact of Negation"):
            self.assertIn(needle, out, needle)
        self.assertNotIn("hand:", out.lower().replace("hand 4", ""), "hand contents never appear")

    def test_seat_filter_and_json(self):
        p = self._run("--seat", "1")
        self.assertIn("SEAT 1", p.stdout); self.assertNotIn("SEAT 0", p.stdout)
        j = self._run("--json")
        self.assertEqual(json.loads(j.stdout)["turn"], 12)

    def test_no_live_game_exits_2(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(Path(self.tmp.name) / "missing.json")],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2); self.assertIn("no live game", p.stderr)

    def test_old_snapshot_without_zones_says_so(self):
        old = dict(SNAP); old["seats"] = [{k: v for k, v in s.items() if k not in ("graveyard", "exile", "commandZone")} for s in SNAP["seats"]]
        self.snap.write_text(json.dumps(old))
        self.assertIn("not in this snapshot version", self._run().stdout)

    def test_brain_argv_allowlists_the_tool_for_the_advisor_only(self):
        seat = SeatBrain(1, "urza-lord-high-artificer", model="opus", effort="low", log=lambda *_: None)
        adv = SeatBrain(0, "selvala-heart-of-the-wilds", model="opus", effort="low", log=lambda *_: None,
                        brief="advisor-brief.md", allowed_tools=[ar.PUBLIC_STATE_TOOL])
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            raise OSError("not really launching")
        import seatd.brain as brain_mod
        orig = brain_mod._run
        brain_mod._run = fake_run
        try:
            seat._call("x", 5.0, resume=False)
            seat_cmd = captured["cmd"]
            adv._call("x", 5.0, resume=False)
            adv_cmd = captured["cmd"]
        finally:
            brain_mod._run = orig
        self.assertIn("--disallowedTools", seat_cmd); self.assertNotIn("--allowedTools", seat_cmd)
        self.assertNotIn("--disallowedTools", adv_cmd)
        self.assertEqual(adv_cmd[adv_cmd.index("--allowedTools") + 1], "Bash(python3 forge-arena/scripts/arena-public-state.py:*)")
        for keep in ("--setting-sources", "--strict-mcp-config"):
            self.assertIn(keep, adv_cmd)

    def test_advisor_constructs_its_brain_with_the_tool(self):
        seen = {}

        class FakeBrain:
            def __init__(self, *a, **kw):
                seen.update(kw); self.deck = a[1]; self.model = "opus"; self.effort = "low"; self.totals = {"calls": 0}
            def ensure_session(self, *a, **kw): return True
            def reset(self): pass
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = FakeBrain, (lambda *a, **kw: [])
        try:
            ar.AdvisorRunner("selvala-heart-of-the-wilds", Path(self.tmp.name), "opus", "low", 30.0, log_dir=Path(self.tmp.name) / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        self.assertEqual(seen.get("allowed_tools"), [ar.PUBLIC_STATE_TOOL])
        self.assertIn("arena-public-state.py", (Path(__file__).resolve().parents[1] / "seatd" / "advisor-brief.md").read_text())
