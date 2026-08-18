"""Cycle replay (backlog item 3): brain declares repeat_cycle: N on a
decision identical to an earlier one this turn; the runner replays the
recorded cycle for matching windows with zero model calls and breaks out on
any novelty. Offline: fake mailbox + fake brain."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import runner as runner_mod  # noqa: E402


class FakeMailbox:
    game_reset = False

    def __init__(self):
        self.responses = []
        self.inbox = Path("/nonexistent")

    def respond(self, req, answer):
        self.responses.append((req.get("seq"), answer))
        return True

    def read_observer(self):
        return None


class FakeBrain:
    effort = "low"
    model = "opus"

    def __init__(self, script):
        self.script = list(script)   # answers to hand out, in order
        self.calls = 0

    def decide(self, prompt, timeout_s, effort=None):
        self.calls += 1
        out = self.script.pop(0) if self.script else {"chosenId": 0}
        return out, {"latency_s": 0.01, "usage": None, "cache_read": 1, "raw": json.dumps(out)}

    def reset(self):
        pass


def make_runner():
    r = runner_mod.SeatRunner.__new__(runner_mod.SeatRunner)
    r.seat = 3
    r.deck = "urza-lord-high-artificer"
    r.mb = FakeMailbox()
    r.brain = FakeBrain([])
    r.timeout_s = 90.0
    r.speculative = False
    r.react_hold = False
    r.autopass = ()
    r.plan = None
    r.hold = None
    r.turn_intent = None
    r.combos = None
    r.react_seen = set()
    r.cycle = None
    r._hist = []
    r._last_turn = None
    r._deviation = None
    r.log_lines = []
    r._say = r.log_lines.append
    r._record = lambda *a, **k: None
    r._seen_seq = set()
    return r


def req(seq, dtype, opts, stack=(), pool=0, life=40, phase="MAIN1", turn=5,
        extra_state=None):
    state = {"stack": list(stack), "manaPool": pool, "life": life,
             "opponents": [{"life": 40}, {"life": 40}, {"life": 40}],
             "untappedManaSourceCount": 3}
    if extra_state:
        state.update(extra_state)
    options = [{"id": 0, "label": "Pass (do nothing)"}]
    options += [{"id": i + 1, "label": lab} for i, lab in enumerate(opts)]
    return {"seq": seq, "turn": turn, "phase": phase, "decisionType": dtype,
            "prompt": "t", "state": state, "options": options}


SCEPTER = 'Isochron Scepter  {2} — copy imprinted instant'
CONFIRM_OPTS = None  # CONFIRM uses fixed 0/1 options


def confirm_req(seq, turn=5):
    return {"seq": seq, "turn": turn, "phase": "MAIN1",
            "decisionType": "CONFIRM", "prompt": "cast the copy?",
            "state": {"stack": ["Isochron Scepter"], "manaPool": 0, "life": 40,
                      "opponents": [{"life": 40}, {"life": 40}, {"life": 40}],
                      "confirmMode": "TRIGGER", "yesCost": "none"},
            "options": [{"id": 0, "label": "No"}, {"id": 1, "label": "Yes"}]}


class CycleReplayTests(unittest.TestCase):
    def drive(self, r, request):
        r.handle(request)
        return r.mb.responses[-1][1]

    def test_declared_cycle_replays_and_completes(self):
        r = make_runner()
        # iteration 1 (all model): activate scepter -> confirm yes -> react pass
        r.brain.script = [
            {"chosenId": 1},                       # seq1 activate
            {"chosenId": 1},                       # seq2 confirm yes
            {"chosenId": 0},                       # seq3 react pass
            {"chosenId": 1, "repeat_cycle": 3},    # seq4 activate again + declare
        ]
        self.drive(r, req(1, "CAST_SPELL", [SCEPTER]))
        self.drive(r, confirm_req(2))
        self.drive(r, req(3, "REACT", ["Counterspell  {U}{U} — counter"],
                          stack=["Dramatic Reversal"]))
        self.drive(r, req(4, "CAST_SPELL", [SCEPTER], pool=2))  # pool GREW: still same sig
        self.assertIsNotNone(r.cycle, "repeat_cycle: 3 should arm the cycle")
        calls_before = r.brain.calls
        # three more rounds, minus the live anchor: replay confirms/reacts/anchors
        seqs = 5
        answers = []
        for rnd in range(3):
            if rnd > 0:
                answers.append(self.drive(r, req(seqs, "CAST_SPELL", [SCEPTER], pool=4 + rnd)))
                seqs += 1
            answers.append(self.drive(r, confirm_req(seqs))); seqs += 1
            answers.append(self.drive(r, req(seqs, "REACT",
                              ["Counterspell  {U}{U} — counter"],
                              stack=["Dramatic Reversal"], life=42 + rnd))); seqs += 1
        self.assertEqual(r.brain.calls, calls_before,
                         "replayed windows must cost zero model calls")
        self.assertEqual(answers[0], {"chosenId": 1})   # confirm yes replayed
        self.assertEqual(answers[1], {"chosenId": 0})   # react pass replayed
        self.assertIsNone(r.cycle, "cycle must complete after N rounds")

    def test_novelty_breaks_replay(self):
        r = make_runner()
        r.brain.script = [
            {"chosenId": 1},
            {"chosenId": 0},
            {"chosenId": 1, "repeat_cycle": 5},
            {"chosenId": 0},                       # model resumes after break
        ]
        self.drive(r, req(1, "CAST_SPELL", [SCEPTER]))
        self.drive(r, req(2, "REACT", ["X"], stack=["Dramatic Reversal"]))
        self.drive(r, req(3, "CAST_SPELL", [SCEPTER]))
        self.assertIsNotNone(r.cycle)
        # an OPPONENT spell appears on the stack: signature mismatch -> model
        out = self.drive(r, req(4, "REACT", ["X"],
                                stack=["Dramatic Reversal", "Swan Song"]))
        self.assertIsNone(r.cycle, "novelty must break the cycle")
        self.assertEqual(r.brain.calls, 4, "the novel window must go to the model")

    def test_repeat_without_prior_identical_window_is_ignored(self):
        r = make_runner()
        r.brain.script = [{"chosenId": 1, "repeat_cycle": 9}]
        self.drive(r, req(1, "CAST_SPELL", [SCEPTER]))
        self.assertIsNone(r.cycle, "no earlier identical window -> no cycle")

    def test_turn_change_clears_cycle(self):
        r = make_runner()
        r.brain.script = [
            {"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 4}, {"chosenId": 0},
        ]
        self.drive(r, req(1, "CAST_SPELL", [SCEPTER], turn=5))
        self.drive(r, req(2, "CAST_SPELL", [SCEPTER], turn=5))
        self.assertIsNotNone(r.cycle)
        self.drive(r, req(3, "REACT", ["X"], stack=["Y"], turn=6))
        self.assertIsNone(r.cycle, "a cycle never survives the turn boundary")


if __name__ == "__main__":
    unittest.main()
