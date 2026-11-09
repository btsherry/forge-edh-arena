"""The seat runner around its decisions: the restart record (a restarted runner carries the game so far;
record.render is deterministic, bounded and fair), session rotation past the token cap and at the hard ceiling,
the engine's timeoutSec as the budget, game identity (a new game clears the per-turn memories), the plain
game.jsonl beside the per-game files, a punt's bookkeeping (a vanished request, the transport event's game
id, the TARGETS punt marker), the trigger-order memo, and an exception inside a decision becoming a recorded
punt rather than a dead runner. Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import record  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402
from test_cycle_replay import make_runner, req, SCEPTER  # noqa: E402
from test_fastpath import react_rev, runner_g  # noqa: E402
from test_react_memo import META, PASS, react_cs as react, runner_p as runner  # noqa: E402


def _runner():
    tmp = Path(tempfile.mkdtemp(prefix="hard-"))
    return SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs")), tmp


def _rows(seat, gid, turns):
    return [{"seat": seat, "gameId": gid, "turn": t, "seq": 10 * t, "type": "CAST_SPELL", "source": "model",
             "answer": {"chosenId": 1}, "why": f"turn {t} reason",
             "board": {"lives": {"0": 40, "2": 40 - t}, "stack": []}} for t in turns]


def write_logs(d: Path):
    g = d / "game.jsonl"
    s2 = d / "seat-2.jsonl"
    rows = [
        {"seat": 1, "gameId": "g1", "turn": 1, "seq": 1, "type": "CAST_SPELL", "source": "model", "answer": {"chosenId": 1},
         "why": "SECRET URZA PLAN do not leak", "board": {"lives": {"0": 40, "1": 40, "2": 40, "3": 40}, "stack": []}},
        {"seat": 2, "gameId": "g1", "turn": 1, "seq": 1, "type": "CAST_SPELL", "source": "model", "answer": {"chosenId": 1},
         "why": "Mox first, then Giada on curve", "board": {"lives": {"0": 40, "1": 40, "2": 40, "3": 40}, "stack": []}},
        {"seat": 2, "gameId": "g1", "turn": 3, "seq": 2, "type": "REACT", "source": "model", "answer": {"chosenId": 0},
         "why": "nothing to do", "board": {"lives": {"0": 38, "1": 40, "2": 40, "3": 40}, "stack": ["Rhystic Study"]}},
        {"seat": 2, "gameId": "g1", "turn": 3, "seq": 3, "type": "DECLARE_ATTACKERS", "source": "model", "answer": {"attackers": [5, 6]},
         "why": "two fliers in", "board": {"lives": {"0": 38, "1": 40, "2": 40, "3": 40}, "stack": []}},
        {"seat": 2, "gameId": "OLD", "turn": 9, "seq": 9, "type": "CAST_SPELL", "source": "model", "answer": {"chosenId": 1},
         "why": "from another game", "board": {"lives": {"0": 1}, "stack": []}},
    ]
    g.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    s2.write_text("\n".join(json.dumps(r) for r in [
        {"seat": 2, "gameId": "g1", "seq": 1, "turn": 1, "type": "CAST_SPELL", "answer": {"chosenId": 1},
         "options": ["Pass (do nothing)", "Chrome Mox  {0} — imprint"], "why": "Mox first, then Giada on curve"},
        {"seat": 2, "gameId": "g1", "seq": 3, "turn": 3, "type": "DECLARE_ATTACKERS", "answer": {"attackers": [5, 6]},
         "options": [], "why": "two fliers in"},
    ]) + "\n")
    return g, s2


class RestartKeepsTheRecord(unittest.TestCase):
    def test_init_prompt_shares_the_dossier_and_appends_the_record(self):
        r, _ = _runner()
        plain = r.brain._init_prompt(None)
        self.assertEqual(plain, r.brain._init_message)
        withrec = r.brain._init_prompt("THE RECORD")
        self.assertTrue(withrec.endswith("\nReply exactly: READY"))
        self.assertEqual(withrec.count("Reply exactly: READY"), 1, "READY is said once, after the record")
        self.assertLess(withrec.index("THE RECORD"), withrec.index("Reply exactly: READY"))
        self.assertTrue(withrec.startswith(plain[: len(plain) - len("\nReply exactly: READY")]))

    def test_restart_record_is_found_only_for_a_live_game(self):
        r, tmp = _runner()
        self.assertIsNone(r._restart_record(), "no game.jsonl: a launch, not a restart")
        r._game_log.parent.mkdir(parents=True, exist_ok=True)
        rows = _rows(0, "g1", [1, 2]) + _rows(2, "g1", [1, 2, 3])
        r._game_log.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
        got = r._restart_record()
        self.assertIsNotNone(got)
        gid, text, n = got
        self.assertEqual((gid, n), ("g1", 3))
        self.assertIn("Turn 3", text)
        self.assertIn("turn 3 reason", text, "own reasons are quoted")
        (tmp / "observer-state.json").write_text(json.dumps({"gameOver": True}))
        self.assertIsNone(r._restart_record(), "the game is over: nothing to carry")

    def test_ensure_session_sends_the_record_once(self):
        r, _ = _runner()
        sent = []
        r.brain._call = lambda prompt, timeout_s, resume, **k: (sent.append((prompt, resume)) or {"session_id": "abcdef1234", "usage": {"input_tokens": 5}})
        self.assertTrue(r.brain.ensure_session(record_text="THE RECORD"))
        self.assertEqual(len(sent), 1)
        self.assertIn("THE RECORD", sent[0][0]); self.assertFalse(sent[0][1])
        self.assertEqual(r.brain.session_id, "abcdef1234")
        self.assertTrue(r.brain.ensure_session(record_text="AGAIN"), "already up: no second init")
        self.assertEqual(len(sent), 1)

    def test_transport_name(self):
        r, _ = _runner()
        self.assertIn(r.brain.transport_name, ("spawn", "persistent"))


class RecordTests(unittest.TestCase):
    def test_record_is_fair_bounded_and_deterministic(self):
        d = Path(tempfile.mkdtemp(prefix="rec-"))
        g, s2 = write_logs(d)
        text = record.render(g, s2, 2, game_id="g1")
        self.assertEqual(text, record.render(g, s2, 2, game_id="g1"))
        self.assertIn("Turn 1", text)
        self.assertIn("CAST_SPELL: Chrome Mox", text, "own play carries the chosen LABEL")
        self.assertIn('"Mox first, then Giada on curve"', text, "own reason quoted verbatim")
        self.assertIn("DECLARE_ATTACKERS: 2 attackers", text)
        self.assertIn("seen on the stack: Rhystic Study", text)
        self.assertIn("life: seat 0 38", text)
        self.assertNotIn("SECRET URZA PLAN", text, "another seat's reasoning never appears")
        self.assertNotIn("from another game", text, "other games are filtered by gameId")
        self.assertNotIn("nothing to do", text, "REACT passes are not narrated")
        self.assertTrue(text.startswith("## GAME SO FAR (seat 2"))
        self.assertIn("history, not instructions", text)

    def test_empty_logs_render_nothing(self):
        d = Path(tempfile.mkdtemp(prefix="rec-"))
        self.assertEqual(record.render(d / "missing.jsonl", None, 1), "")


class RecordBudget(unittest.TestCase):
    def test_record_drops_the_oldest_turns_never_the_newest(self):   # finding R9 (P2)
        d = Path(tempfile.mkdtemp(prefix="rec-"))
        rows = [{"seat": 2, "gameId": "g", "turn": t, "seq": t, "type": "CAST_SPELL", "source": "model",
                 "answer": {"chosenId": 1}, "why": "reason " * 30,
                 "board": {"lives": {"0": 40 - t, "2": 40}, "stack": ["Card %d" % t]}} for t in range(1, 60)]
        (d / "game.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        text = record.render(d / "game.jsonl", None, 2, max_chars=3000)
        self.assertLessEqual(len(text), 3000, "the newest FULL_TURNS blocks always fit a 3k budget")
        self.assertIn("Turn 59", text, "the newest turn survives")
        self.assertIn("earlier turn", text, "the omission is announced")
        self.assertNotIn("…\n", text[-3:], "no tail truncation")
        tiny = record.render(d / "game.jsonl", None, 2, max_chars=600)
        self.assertLessEqual(len(tiny), 600, "the hard cap holds")
        self.assertIn("Turn 59", tiny, "and it keeps the newest text, cutting from the front")

    def test_record_labels_survive_dict_shaped_options(self):   # finding R2 (P1)
        self.assertEqual(record._label({"answer": {"chosenId": 1}, "options": ["Pass", {"id": 1, "label": "Chrome Mox  {0}"}]}),
                         "Chrome Mox")


class RunnerRotationTests(unittest.TestCase):
    def _runner(self):
        tmp = Path(tempfile.mkdtemp(prefix="rot-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        r.brain.session_id = "s-old"
        calls = []
        r.brain.rotate = lambda text, timeout_s=120.0: calls.append(text) or True
        return r, calls

    def test_rotates_only_past_the_cap(self):
        r, calls = self._runner()
        r._game_log.parent.mkdir(parents=True, exist_ok=True)
        r._game_log.write_text(json.dumps({"seat": 2, "turn": 1, "seq": 1, "type": "CAST_SPELL", "source": "model",
                                           "answer": {"chosenId": 1}, "why": "w", "board": {"lives": {"2": 40}, "stack": []}}) + "\n")
        r.rotate_at = 250_000
        r.brain.last_prompt_tokens = 100_000
        self.assertFalse(r._maybe_rotate()); self.assertEqual(calls, [])
        r.brain.last_prompt_tokens = 260_000
        self.assertTrue(r._maybe_rotate()); self.assertEqual(len(calls), 1)
        self.assertIn("## GAME SO FAR (seat 2", calls[0])

    def test_hard_ceiling_rotates_mid_turn(self):
        r, calls = self._runner()
        r._game_log.parent.mkdir(parents=True, exist_ok=True)
        r._game_log.write_text(json.dumps({"seat": 2, "turn": 17, "seq": 1, "type": "CAST_SPELL", "source": "model",
                                           "answer": {"chosenId": 1}, "why": "w", "board": {"lives": {"2": 40}, "stack": []}}) + "\n")
        r.rotate_at, r.rotate_hard = 250_000, 600_000
        r.brain.last_prompt_tokens = 400_000
        self.assertFalse(r._maybe_rotate(hard=True), "above the soft cap but under the hard ceiling: wait for the turn boundary")
        r.brain.last_prompt_tokens = 851_000
        self.assertTrue(r._maybe_rotate(hard=True), "game 28: 851k mid-turn rotates now")
        self.assertEqual(len(calls), 1)

    def test_zero_cap_disables(self):
        r, calls = self._runner()
        r.rotate_at = 0
        r.brain.last_prompt_tokens = 900_000
        self.assertFalse(r._maybe_rotate())

    def test_injected_brain_is_used_as_is(self):
        tmp = Path(tempfile.mkdtemp(prefix="inj-"))
        b = SeatBrain(0, "selvala-heart-of-the-wilds", model="opus", effort="low", log=lambda *_: None, brief="advisor-brief.md")
        r = SeatRunner(0, "selvala-heart-of-the-wilds", str(tmp), log_dir=str(tmp / "logs"), brain=b)
        self.assertIs(r.brain, b)


class EngineTimeoutAdoption(unittest.TestCase):
    """Plan item 12: the engine's timeoutSec on a request is the budget source."""

    def test_runner_adopts_the_engine_timeout(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 0}, dict(META))
        self.assertEqual(r.timeout_s, 90.0)
        req = react(1)
        req["timeoutSec"] = 300
        r.handle(req)
        self.assertEqual(r.timeout_s, 300.0)
        self.assertEqual(r.mb.timeout_s, 300.0)

    def test_unstamped_request_keeps_the_launch_timeout(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 0}, dict(META))
        req = react(1)
        req.pop("timeoutSec", None)
        r.handle(req)
        self.assertEqual(r.timeout_s, 90.0)


class GameReset(unittest.TestCase):
    def test_game_reset_clears_the_per_turn_memories(self):   # finding R7 (P2)
        r = runner_g()
        r._tap_pass = (1, ("x",), 40); r._yielded = {(1, "a", 0, "ability", ()): (40, 0, 0)}
        req = react_rev(stack=(), kinds=(), owners=()); req["seq"] = 1; req["turn"] = 1
        req["decisionType"] = "CAST_SPELL"   # an own-main window: nothing to yield on after the reset
        r.mb.game_reset = True
        r.brain.decide = lambda *a, **k: (PASS, {"latency_s": 0.1, "usage": None, "cache_read": None, "raw": "{}"})
        r.brain.session_id = "s"; r.brain.ensure_session = lambda *a, **k: True
        r.mb.respond = lambda req, ans: True
        r.handle(req)
        self.assertIsNone(r._tap_pass); self.assertEqual(r._yielded, {})


class EmptyDeviationsAreDropped(unittest.TestCase):
    def test_wanted_nothing_is_not_a_deviation(self):
        r, _ = _runner()
        req = {"seq": 5, "turn": 3, "phase": "MAIN1", "decisionType": "CAST_SPELL", "gameId": "g", "options": [{"id": 0, "label": "Pass (do nothing)"}]}
        meta = {"latency_s": 0.1, "usage": None, "raw": "{}"}
        r.brain.decide = lambda *a, **k: ({"chosenId": 0, "deviation": {"wanted": "nothing", "blocked_by": "n/a"}}, meta)
        r.brain.session_id = "s"; r.brain.ensure_session = lambda *a, **k: True
        r.mb.respond = lambda req, ans: True
        r.handle(req)
        self.assertIsNone(r._deviation, "wanted nothing: no deviation recorded")
        r.brain.decide = lambda *a, **k: ({"chosenId": 0, "deviation": {"wanted": "hold Force", "blocked_by": "no blue"}}, meta)
        r.handle(dict(req, seq=6))
        self.assertEqual(r._deviation, {"wanted": "hold Force", "blocked_by": "no blue"})


class RunnerHygiene(unittest.TestCase):
    """Plan item 13: (a) an exception inside a decision never kills the runner
    — it logs, answers the safe default, and records a punt; (h) the shared
    log is one file per game with game.jsonl a symlink to the current one."""

    def test_exception_in_decision_becomes_a_recorded_punt(self):
        r = runner()

        def boom(prompt, **kw):
            raise RuntimeError("model client exploded")
        r.brain.decide = boom
        r.handle(react(1))   # must not raise
        rows = [json.loads(l) for l in r._jsonl_path.read_text().splitlines()]
        self.assertEqual(rows[-1]["source"], "punt")
        self.assertIn("runner exception", rows[-1]["why"])
        self.assertIn("INTERNAL ERROR", r._log_path.read_text())

    def test_game_log_is_plain_and_per_game_files_ride_alongside(self):
        """BL-21 (2026-09-04, replacing item 13h's symlink): game.jsonl is a
        PLAIN append-only file — the human `tail -f` target for the whole
        session — and every record is ALSO appended to game-<gameId>.jsonl,
        the per-game machine record. A symlink left by a 13h runner is removed
        once so the plain file can take its place."""
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 0}, dict(META))
        # a pre-BL-21 runner left game.jsonl as a symlink: it must go
        legacy = r._game_log.with_name("game-legacy-target.jsonl")
        legacy.write_text("")
        r._game_log.symlink_to(legacy.name)
        req = react(1)
        req["gameId"] = "1756950000123-4242"
        r.handle(req)
        per_game = r._game_log.with_name("game-1756950000123-4242.jsonl")
        self.assertFalse(r._game_log.is_symlink(), "game.jsonl is a plain file again")
        self.assertTrue(r._game_log.is_file())
        self.assertTrue(per_game.exists(), "records ALSO go to the per-game file")
        self.assertEqual(len(r._game_log.read_text().splitlines()), 1)
        self.assertEqual(len(per_game.read_text().splitlines()), 1)
        self.assertEqual(json.loads(per_game.read_text())["gameId"], "1756950000123-4242")
        # a second game: game.jsonl keeps accumulating (same inode, tail -f
        # follows), a second per-game file appears, the first stays
        req2 = react(1, turn=1)
        req2["gameId"] = "1756950009999-4242"
        r.handle(req2)
        self.assertEqual(len(r._game_log.read_text().splitlines()), 2)
        self.assertTrue(r._game_log.with_name("game-1756950009999-4242.jsonl").exists())
        self.assertTrue(per_game.exists())
        self.assertEqual(len(per_game.read_text().splitlines()), 1)
        # an unstamped engine (no gameId): only the flat file
        r.handle(react(2, turn=2))
        self.assertEqual(len(r._game_log.read_text().splitlines()), 3)
        self.assertEqual(len(list(r._game_log.parent.glob("game-*.jsonl"))), 3)


class VanishedRequestPunts(unittest.TestCase):
    """BL-28: a real inbox whose request file is gone -> punt, zero model calls."""

    def test_missing_request_file_on_a_real_inbox_punts_without_a_call(self):
        r = make_runner()
        tmp = Path(tempfile.mkdtemp(prefix="vanish-"))
        r.mb.inbox = tmp                      # exists, holds no req-1.json
        r.brain.script = [{"chosenId": 1}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        self.assertEqual(r.brain.calls, 0, "no model call for a vanished request")
        self.assertEqual(r.mb.responses[-1][1], {"chosenId": 0})
        self.assertTrue(any("vanished" in ln for ln in r.log_lines), r.log_lines)

    def test_fake_inbox_without_a_directory_keeps_a_full_window(self):
        r = make_runner()                              # inbox = /nonexistent (not a dir)
        r.brain.script = [{"chosenId": 1}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        self.assertEqual(r.brain.calls, 1)


class TransportEventsCarryGameId(unittest.TestCase):
    def test_event_line_has_game_id(self):
        r = make_runner()
        tmp = r._jsonl_path.parent
        r._transport_event("punt", "1756950000123-4242")
        r._transport_event("wedge")
        lines = [json.loads(x) for x in (tmp / "transport-events.jsonl").read_text().splitlines()]
        self.assertEqual(lines[0]["gameId"], "1756950000123-4242")
        self.assertEqual(lines[0]["kind"], "punt")
        self.assertIsNone(lines[1]["gameId"])


class TargetPuntMarker(unittest.TestCase):
    """BL-61 (game 64): handle() sends rules.safe_default as it is — on a TARGETS window the engine must
    see "punt": true, so its stock logic aims instead of taking the first options."""

    def test_the_punt_marker_reaches_the_engine(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: (None, dict(META))          # timeout / wedge
        sent = []
        r.mb.respond = lambda req, payload, **kw: sent.append(payload) or True
        req = {"decisionType": "CHOOSE_ENTITIES", "seq": 1, "turn": 5, "phase": "MAIN1",
               "prompt": "Choose the TARGETS for Electrolyze", "timeoutSec": 90,
               "state": {"min": 1, "max": 2, "purpose": "TARGETS"},
               "options": [{"id": 1, "label": "Sol Ring [Urza-S0]"}, {"id": 2, "label": "Grim Monolith [Urza-S0]"},
                           {"id": 3, "label": "Mox Amber [Urza-S0]"}]}
        r.handle(req)
        self.assertEqual(sent, [{"chosen": [1], "punt": True}])


class TriggerOrderMemo(unittest.TestCase):
    """BL-02 follow-up (review 2026-09-04): the same set of trigger groups is
    ordered once per TURN; identical later windows that turn replay the
    model's order with no call (Purphoros + Impact Tremors would otherwise ask
    on every creature); the next turn asks again."""

    def test_next_turn_asks_again(self):
        r = make_runner()
        r.brain.script = [{"chosen": [1, 0]}, {"chosen": [0, 1]}]
        w = self._win(1, ["A — x", "B — y"])
        r.handle(w)
        w2 = self._win(2, ["A — x", "B — y"]); w2["turn"] = 5
        r.handle(w2)
        self.assertEqual(r.brain.calls, 2, "a new turn is a new question")
        self.assertEqual(r.mb.responses[-1][1], {"chosen": [0, 1]})

    def _win(self, seq, labels):
        return {"seq": seq, "turn": 4, "phase": "MAIN1", "decisionType": "CHOOSE_MODE",
                "prompt": "ORDER", "state": {"min": len(labels), "max": len(labels),
                                             "allowRepeat": False, "purpose": "TRIGGER_ORDER"},
                "options": [{"id": i, "label": lab, "cost": None, "type": "TRIGGER"}
                            for i, lab in enumerate(labels)]}

    def test_same_groups_replay_in_the_models_order_with_new_indices(self):
        r = make_runner()
        r.brain.script = [{"chosen": [1, 0]}]          # Tremors first, then Purphoros
        r.handle(self._win(1, ["Purphoros — 2 damage", "Impact Tremors — 1 damage"]))
        self.assertEqual(r.mb.responses[-1][1], {"chosen": [1, 0]})
        # next creature: the engine offers the groups in the other order
        r.handle(self._win(2, ["Impact Tremors — 1 damage", "Purphoros — 2 damage"]))
        self.assertEqual(r.brain.calls, 1, "no second model call")
        self.assertEqual(r.mb.responses[-1][1], {"chosen": [0, 1]}, "Tremors still resolves first")
        self.assertTrue(any("[memo]" in ln for ln in r.log_lines))

    def test_a_new_group_is_a_new_question(self):
        r = make_runner()
        r.brain.script = [{"chosen": [1, 0]}, {"chosen": [2, 0, 1]}]
        r.handle(self._win(1, ["A — x", "B — y"]))
        r.handle(self._win(2, ["A — x", "B — y", "C — z"]))
        self.assertEqual(r.brain.calls, 2)

    def test_punt_is_never_memoized(self):
        r = make_runner()
        r.brain.script = [None, {"chosen": [1, 0]}]
        r.handle(self._win(1, ["A — x", "B — y"]))          # punt -> {"chosen": []} hand-back
        self.assertEqual(r.mb.responses[-1][1], {"chosen": []})
        r.handle(self._win(2, ["A — x", "B — y"]))
        self.assertEqual(r.brain.calls, 2, "the punt was not remembered as an order")
