"""Layer two + the executive take-over (Ben, 2026-09-07).
- record.render: machine-built game record from the runner's own logs;
  deterministic, bounded, fair (no other seat's reasons).
- SeatBrain.rotate: fresh session = same dossier + record, old session dropped;
  last_prompt_tokens tracks what the model re-read.
- SeatRunner: rotation only past the cap and only at a turn boundary; an
  injected brain is used as-is.
- AdvisorRunner: the executive toggle file starts a seat-0 runner on the
  ADVISOR'S OWN brain, answers its mailbox, and stops on off.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import advisor_runner as ar  # noqa: E402
import seatd.brain as brain_mod  # noqa: E402
from seatd import record  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "engine"


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

    def test_budget_folds_old_turns(self):
        d = Path(tempfile.mkdtemp(prefix="rec-"))
        rows = []
        for t in range(1, 40):
            rows.append({"seat": 2, "gameId": "g1", "turn": t, "seq": t, "type": "CAST_SPELL", "source": "model",
                         "answer": {"chosenId": 1}, "why": "reason " * 20,
                         "board": {"lives": {"0": 40 - t, "1": 40, "2": 40, "3": 40}, "stack": ["Card %d" % t]}})
        (d / "game.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        text = record.render(d / "game.jsonl", None, 2, max_chars=3000)
        self.assertLessEqual(len(text), 3000)
        self.assertIn("Turn 39\n", text, "the newest turns stay in full")
        self.assertIn("Turn 1 — life", text, "old turns fold to one line")

    def test_empty_logs_render_nothing(self):
        d = Path(tempfile.mkdtemp(prefix="rec-"))
        self.assertEqual(record.render(d / "missing.jsonl", None, 1), "")


class FakeEnv:
    @staticmethod
    def env(session="s-new", read=0, create=0, inp=2):
        return {"session_id": session, "result": "READY",
                "usage": {"input_tokens": inp, "output_tokens": 5, "cache_read_input_tokens": read,
                          "cache_creation_input_tokens": create}}


class BrainRotationTests(unittest.TestCase):
    def test_last_prompt_tokens_and_rotate_swap_the_session(self):
        b = SeatBrain(2, "giada-font-of-hope", model="opus", effort="low", log=lambda *_: None)
        b.session_id = "s-old"
        b._accumulate(FakeEnv.env(read=300_000, create=4_000))
        self.assertEqual(b.last_prompt_tokens, 304_002)
        seen = {}

        def fake_call(prompt, timeout_s, resume, effort=None):
            seen["prompt"], seen["resume"] = prompt, resume
            return FakeEnv.env(session="s-new", read=0, create=60_000)
        b._call = fake_call
        self.assertTrue(b.rotate("## GAME SO FAR\nTurn 1"))
        self.assertFalse(seen["resume"], "a rotation is a FRESH session")
        self.assertIn("## GAME SO FAR", seen["prompt"])
        self.assertTrue(seen["prompt"].rstrip().endswith("Reply exactly: READY"))
        self.assertIn("DECK COMBOS", seen["prompt"]) if "DECK COMBOS" in b._init_message else None
        self.assertLess(seen["prompt"].count("Reply exactly: READY"), 2, "the READY line moves to the end, not duplicated")
        self.assertEqual(b.session_id, "s-new")
        self.assertEqual(b.rotations, 1)
        self.assertEqual(b.last_prompt_tokens, 60_002)

    def test_failed_rotation_keeps_the_old_session(self):
        b = SeatBrain(2, "giada-font-of-hope", model="opus", effort="low", log=lambda *_: None)
        b.session_id = "s-old"
        b._call = lambda *a, **k: None
        self.assertFalse(b.rotate("x"))
        self.assertEqual(b.session_id, "s-old")
        b.session_id = None
        self.assertFalse(b.rotate("x"), "no session yet: nothing to rotate")


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
        self.assertFalse(adv._executive_wanted())
        self.assertFalse(adv._executive_tick()); self.assertIsNone(adv._exec)
        (logs / "control").mkdir(parents=True, exist_ok=True)
        (logs / "control" / "executive.json").write_text('{"on": true}')
        # a pending seat-0 request in the mailbox
        req = json.loads((FIX / "react.json").read_text())
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


if __name__ == "__main__":
    unittest.main()
