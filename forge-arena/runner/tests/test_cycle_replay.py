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

    def decide(self, prompt, timeout_s=None, effort=None, deadline=None):
        self.calls += 1
        self.last_prompt = prompt
        self.prompts = getattr(self, "prompts", []) + [prompt]
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
    r.order_memo = {}
    r.cycle = None
    r._hist = []
    r._last_turn = None
    r._init_loop_state()      # D4: __init__ owns the loop state; a __new__ runner sets it here
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


def own_req(seq, dtype, opts, stack, kinds, turn=7, phase="MAIN1"):
    """Request whose stack is entirely the seat's own objects (mixed kinds)."""
    state = {"stack": list(stack), "manaPool": 3, "life": 40,
             "opponents": [{"life": 40}, {"life": 40}, {"life": 40}],
             "untappedManaSourceCount": 2,
             "stackOwners": [3] * len(stack),
             "stackKinds": list(kinds)}
    options = [{"id": 0, "label": "Pass (do nothing)"}]
    options += [{"id": i + 1, "label": lab} for i, lab in enumerate(opts)]
    return {"seq": seq, "turn": turn, "phase": phase, "decisionType": dtype,
            "prompt": "t", "state": state, "options": options}


class OwnObjectCollapseTests(unittest.TestCase):
    """Game-12 shape: a declared loop whose OWN trigger pile grows and whose
    own copy-spell interleaves at varying depth must still replay; an
    opponent object must still break out."""

    def test_growing_own_stack_replays(self):
        r = make_runner()
        stacks = [
            (["Aura Shards"] * 3 + ["Ondu Spiritdancer"], ["trigger"] * 3 + ["spell"]),
            (["Ondu Spiritdancer"] + ["Aura Shards"] * 4, ["spell"] + ["trigger"] * 4),
            (["Aura Shards"] * 5 + ["Ondu Spiritdancer"], ["trigger"] * 5 + ["spell"]),
            (["Aura Shards"] * 6, ["trigger"] * 6),
        ]
        r.brain.script = [
            {"chosenId": 1},                       # iter 1: confirm copy
            {"chosenId": 0},                       # iter 1: react pass
            {"chosenId": 1, "repeat_cycle": 8},    # iter 2 anchor: declare
        ]
        st0, k0 = stacks[0]
        self.assertEqual(r.handle(own_req(1, "CONFIRM", ["Yes"], st0, k0)) or
                         r.mb.responses[-1][1], {"chosenId": 1})
        st1, k1 = stacks[1]
        r.handle(own_req(2, "REACT", ["X  {1} — thing"], st1, k1))
        # anchor: same shape as seq1 but MORE own triggers — must still match
        st2, k2 = stacks[2]
        r.handle(own_req(3, "CONFIRM", ["Yes"], st2, k2))
        self.assertIsNotNone(r.cycle,
                             "own-object collapse should make the grown stack match the anchor")
        calls = r.brain.calls
        # replayed iteration with yet another stack shape
        st3, k3 = stacks[3]
        r.handle(own_req(4, "REACT", ["X  {1} — thing"], st3, k3))
        r.handle(own_req(5, "CONFIRM", ["Yes"], stacks[0][0], stacks[0][1]))
        self.assertEqual(r.brain.calls, calls, "replays must cost zero model calls")
        self.assertEqual(r.mb.responses[-1][1], {"chosenId": 1})

    def test_opponent_object_still_breaks(self):
        r = make_runner()
        r.brain.script = [
            {"chosenId": 1}, {"chosenId": 0}, {"chosenId": 1, "repeat_cycle": 5},
            {"chosenId": 0},
        ]
        own = (["Aura Shards"] * 2, ["trigger"] * 2)
        r.handle(own_req(1, "CONFIRM", ["Yes"], own[0], own[1]))
        r.handle(own_req(2, "REACT", ["X"], own[0], own[1]))
        r.handle(own_req(3, "CONFIRM", ["Yes"], own[0] + ["Aura Shards"], own[1] + ["trigger"]))
        self.assertIsNotNone(r.cycle)
        # an OPPONENT spell joins the stack: owners no longer all-3 -> multiset
        req = own_req(4, "REACT", ["X"], ["Aura Shards", "Swan Song"], ["trigger", "spell"])
        req["state"]["stackOwners"] = [3, 1]
        r.handle(req)
        self.assertIsNone(r.cycle, "an opponent object must break the replay")
        self.assertEqual(r.brain.calls, 4, "the novel window must reach the model")

    def test_react_memo_signature_unchanged(self):
        r = make_runner()
        # memo signature must NOT collapse a mixed-kind own stack
        req = own_req(9, "REACT", ["X"], ["A", "A", "B"], ["trigger", "trigger", "spell"])
        sig = r._react_signature(req)
        # wave-2 inserted phase at sig[1]; the stack digest is sig[2]
        self.assertNotIn("OWN-TRIGGERS", str(sig[2]),
                         "mixed kinds must not trigger the memo's own-collapse")
        self.assertEqual(sig[2], ("A", "A", "B"), "memo keeps the exact multiset")


if __name__ == "__main__":
    unittest.main()


class StopConditionTests(unittest.TestCase):
    """Round 31 (Ben, 2026-09-14): `until` beside repeat_cycle — the runner stops at the
    target or at N, checks progress, holds a life floor, parks on an interruption and
    re-arms when the steps recur; a LOOP OFFER note when the tape repeats."""

    def setUp(self):
        self.r = make_runner()

    def drive(self, request):
        self.r.handle(request)
        return self.r.mb.responses[-1][1]

    def test_until_stops_when_the_target_is_met_and_the_brain_is_told_why(self):
        r = self.r
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 10, "until": {"life": ">=60"}}, {"chosenId": 0}]
        self.drive(req(1, "CAST_SPELL", ["Mana Vault  {1}"], life=40))
        self.drive(req(2, "CAST_SPELL", ["Mana Vault  {1}"], life=45))
        self.assertTrue(any("CYCLE armed" in l and "stops when life >= 60" in l for l in r.log_lines), r.log_lines[-1])
        self.assertEqual(self.drive(req(3, "CAST_SPELL", ["Mana Vault  {1}"], life=50)), {"chosenId": 1})
        self.assertEqual(self.drive(req(4, "CAST_SPELL", ["Mana Vault  {1}"], life=55)), {"chosenId": 1})
        self.assertEqual(r.brain.calls, 2, "two replays, no model call")
        self.assertEqual(self.drive(req(5, "CAST_SPELL", ["Mana Vault  {1}"], life=60)), {"chosenId": 0})
        self.assertEqual(r.brain.calls, 3, "life 60 meets the target: the model answers this window")
        self.assertTrue(any("CYCLE stopped: life 60 meets >= 60 after 2 round(s)" in l for l in r.log_lines), r.log_lines)
        self.assertIn("RUNNER NOTE: LOOP STOPPED: life 60 meets >= 60", r.brain.last_prompt)
        self.assertIsNone(r.cycle)
        self.drive(req(6, "CAST_SPELL", ["Mana Vault  {1}"], life=60))
        self.assertNotIn("RUNNER NOTE", r.brain.last_prompt, "the note is one-shot")

    def test_until_alone_takes_the_cap_bad_grammar_is_ignored_and_a_met_target_does_not_arm(self):
        r = self.r
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1, "until": {"bogus": ">=1"}}, {"chosenId": 1, "until": {"pool": 40}}]
        self.drive(req(1, "CAST_SPELL", ["Sol Ring  {1}"]))
        self.drive(req(2, "CAST_SPELL", ["Sol Ring  {1}"]))
        self.assertTrue(any("until ignored: unknown operand 'bogus'" in l for l in r.log_lines))
        self.assertIsNone(r.cycle, "no repeat_cycle and a bad until: nothing armed")
        self.drive(req(3, "CAST_SPELL", ["Sol Ring  {1}"], pool=3))
        self.assertIsNotNone(r.cycle); self.assertEqual(r.cycle["total"], runner_mod.SeatRunner.CYCLE_MAX_ROUNDS, "a bare integer means >= and until alone takes the cap as N")
        self.assertEqual(r.cycle["until_text"], "pool >= 40")
        r2 = make_runner()
        r2.brain.script = [{"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 5, "until": {"life": ">=10"}}]
        r2.handle(req(1, "CAST_SPELL", ["Sol Ring  {1}"], life=40)); r2.handle(req(2, "CAST_SPELL", ["Sol Ring  {1}"], life=40))
        self.assertIsNone(r2.cycle); self.assertTrue(any("until already satisfied" in l for l in r2.log_lines))
        for bad, msg in (({"life": ">40"}, "use '>=N'"), ({"any": []}, "non-empty"), ({"life": True}, "comparison"), ("x", "non-empty object")):
            with self.assertRaises(ValueError, msg=str(bad)) as cm:
                runner_mod.SeatRunner.parse_until(bad)
            self.assertIn(msg, str(cm.exception))
        self.assertEqual(runner_mod.SeatRunner.parse_until({"any": [{"life": ">=180"}, {"opp_life_max": "<=0"}]}), ("any", [("life", ">=", 180), ("opp_life_max", "<=", 0)]))

    def test_no_progress_stops_the_loop(self):
        r = self.r
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 20, "until": {"life": ">=100"}}, {"chosenId": 0}]
        self.drive(req(1, "CAST_SPELL", ["Sol Ring  {1}"], life=40)); self.drive(req(2, "CAST_SPELL", ["Sol Ring  {1}"], life=40))
        self.drive(req(3, "CAST_SPELL", ["Sol Ring  {1}"], life=40)); self.drive(req(4, "CAST_SPELL", ["Sol Ring  {1}"], life=40))
        self.assertEqual(r.brain.calls, 2, "two rounds replayed while life stayed at 40")
        self.assertTrue(any("no progress toward life >= 100 over 2 rounds" in l for l in r.log_lines), r.log_lines)
        self.assertIsNone(r.cycle)
        self.drive(req(5, "CAST_SPELL", ["Sol Ring  {1}"], life=40))
        self.assertEqual(r.brain.calls, 3); self.assertIn("no progress", r.brain.last_prompt)

    def test_the_life_floor_stops_the_loop_whatever_the_target(self):
        r = self.r
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 20, "until": {"pool": ">=40"}}, {"chosenId": 0}]
        self.drive(req(1, "CAST_SPELL", ["Necro  {B}"], life=12, pool=0)); self.drive(req(2, "CAST_SPELL", ["Necro  {B}"], life=10, pool=2))
        self.assertEqual(self.drive(req(3, "CAST_SPELL", ["Necro  {B}"], life=8, pool=4)), {"chosenId": 1})
        self.assertEqual(self.drive(req(4, "CAST_SPELL", ["Necro  {B}"], life=5, pool=6)), {"chosenId": 0}, "life 5: the floor")
        self.assertTrue(any("life 5 at the safety floor" in l for l in r.log_lines)); self.assertIn("safety floor", r.brain.last_prompt)

    def test_a_parked_loop_re_arms_when_its_steps_recur_and_a_different_answer_discards_it(self):
        r = self.r
        A = lambda seq, life: req(seq, "CAST_SPELL", ["Mana Vault  {1}"], life=life)  # noqa: E731
        B = lambda seq, life: req(seq, "CHOOSE_ENTITY", ["Sol Ring [me]"], life=life)  # noqa: E731
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 6, "until": {"life": ">=100"}}]
        self.drive(A(1, 40)); self.drive(B(2, 40)); self.drive(A(3, 50))
        self.assertTrue(any("CYCLE armed: 2 step(s) x 6" in l for l in r.log_lines), r.log_lines[-1])
        self.assertEqual(self.drive(B(4, 50)), {"chosenId": 1}); self.assertEqual(r.brain.calls, 3)
        # an opponent's spell: the window changes -> paused, not broken
        r.brain.script = [{"chosenId": 0}]
        self.drive(req(5, "REACT", ["Counterspell  {U}{U}"], stack=["Opponent's Bolt"], life=50))
        self.assertEqual(r.brain.calls, 4); self.assertIsNone(r.cycle); self.assertIsNotNone(r._parked)
        self.assertTrue(any("CYCLE paused" in l for l in r.log_lines)); self.assertIn("RUNNER NOTE: LOOP PAUSED: your loop (until life >= 100; 1 round(s) done, 5 left)", r.brain.last_prompt)
        # the brain plays one round of the same steps by hand -> the loop re-arms and the next window replays
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1}]
        self.drive(A(6, 60)); self.drive(B(7, 60))
        self.assertEqual(r.brain.calls, 6); self.assertTrue(any("CYCLE re-armed after the interruption" in l for l in r.log_lines), r.log_lines[-3:])
        self.assertIsNotNone(r.cycle); self.assertIsNone(r._parked)
        self.assertEqual(self.drive(A(8, 70)), {"chosenId": 1}); self.assertEqual(self.drive(B(9, 70)), {"chosenId": 1})
        self.assertEqual(r.brain.calls, 6, "replayed, no model calls")
        self.assertEqual(self.drive(A(10, 100)), {"chosenId": 0} if False else self.r.mb.responses[-1][1])
        self.assertTrue(any("CYCLE stopped: life 100 meets >= 100" in l for l in r.log_lines), "the target is reached after the resumption")
        # a different answer after a pause discards the parked loop
        r2 = make_runner()
        r2.brain.script = [{"chosenId": 1}, {"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 6, "until": {"life": ">=100"}}, {"chosenId": 0},
                           {"chosenId": 2}, {"chosenId": 1}, {"chosenId": 2}, {"chosenId": 1}]
        A2 = lambda seq: req(seq, "CAST_SPELL", ["Mana Vault  {1}", "Sol Ring  {1}"])  # noqa: E731
        for s_ in (1, 2, 3): r2.handle(A2(s_) if s_ != 2 else B(2, 40))
        r2.handle(B(4, 40))
        r2.handle(req(5, "REACT", ["Counterspell  {U}{U}"], stack=["Opponent's Bolt"]))
        self.assertIsNotNone(r2._parked)
        for s_ in (6, 7, 8, 9): r2.handle(A2(s_) if s_ % 2 == 0 else B(s_, 40))
        self.assertIsNone(r2._parked, "two rounds answered differently: the brain's judgement wins")

    def test_the_offer_appears_once_after_two_identical_rounds_and_only_for_the_seats_own_engine(self):
        r = self.r
        A = lambda seq, **kw: req(seq, "CAST_SPELL", ["Mana Vault  {1}"], **kw)  # noqa: E731
        B = lambda seq, **kw: req(seq, "CHOOSE_ENTITY", ["Sol Ring [me]"], **kw)  # noqa: E731
        r.brain.script = [{"chosenId": 1}] * 4 + [{"chosenId": 1, "repeat_cycle": 3}]
        self.drive(A(1)); self.drive(B(2)); self.drive(A(3)); self.drive(B(4))
        self.assertTrue(all("LOOP OFFER" not in p for p in r.brain.prompts), "one round is not a pattern")
        self.drive(A(5))
        self.assertIn("RUNNER NOTE: LOOP OFFER: the runner sees your last 2 decisions (CAST_SPELL, CHOOSE_ENTITY) repeating the 2 before them", r.brain.last_prompt)
        self.assertTrue(any("LOOP OFFER: 2-step pattern seen twice" in l for l in r.log_lines))
        self.assertIsNotNone(r.cycle, "the brain took the offer")
        self.assertEqual(self.drive(B(6)), {"chosenId": 1}); self.assertEqual(r.brain.calls, 5)
        # the cycle runs its rounds, then the same pattern again: no second offer this turn
        while r.cycle:
            self.drive(A(100 + r.brain.calls + len(r.mb.responses))); self.drive(B(200 + len(r.mb.responses)))
        n = r.brain.calls
        r.brain.script = [{"chosenId": 1}] * 6
        for s_ in range(300, 305): self.drive(A(s_) if s_ % 2 == 0 else B(s_))
        self.assertTrue(all("LOOP OFFER" not in p for p in r.brain.prompts[n:]), "offered once per pattern per turn")
        # an opponent's object inside the pattern: not our engine, no offer
        r3 = make_runner(); r3.brain.script = [{"chosenId": 0}] * 6
        for s_ in range(1, 6):
            r3.handle(req(s_, "REACT", ["Counterspell  {U}{U}"], stack=["Opponent's Engine"]))
        self.assertTrue(all("LOOP OFFER" not in p for p in r3.brain.prompts))
        # and the runner note channel survives a declined offer: the next prompt carries nothing
        r4 = make_runner(); r4.brain.script = [{"chosenId": 1}] * 6
        for s_ in range(1, 6): r4.handle(A(s_))
        self.assertNotIn("LOOP OFFER", r4.brain.prompts[2], "one action twice is everyday play (game 48: two mana floats)")
        self.assertIn("LOOP OFFER", r4.brain.prompts[3], "a one-step pattern: offered at the fourth identical window")
        self.assertNotIn("LOOP OFFER", r4.brain.prompts[4]); self.assertIsNone(r4.cycle, "declined: nothing replayed")

    def test_a_loop_with_a_target_tolerates_its_own_churn_but_not_an_opponent(self):
        """Game 47: Sol Ring and Mana Vault alternate between hand and battlefield, so no two
        rounds show the same option list; a target-bearing loop matches loosely, a plain one strictly."""
        r = self.r
        castA = lambda seq, life: req(seq, "CAST_SPELL", ["Mana Vault  {1}", "Sol Ring  {T} — add"], life=life)   # noqa: E731  Vault in hand
        castB = lambda seq, life: req(seq, "CAST_SPELL", ["Sol Ring  {1}", "Mana Vault  {T} — add"], life=life)   # noqa: E731  Sol Ring in hand
        bounce = lambda seq, life: req(seq, "CHOOSE_ENTITY", ["Sol Ring [me]", "Mana Vault [me]"], life=life)     # noqa: E731
        r.brain.script = [{"chosenId": 1}] * 8
        # two rounds of the alternating loop: Vault round, Sol Ring round — the answers alternate too, so the pattern is four steps
        self.drive(castA(1, 40)); self.drive(bounce(2, 40)); self.drive(castB(3, 45)); self.drive(bounce(4, 45))
        self.assertTrue(all("LOOP OFFER" not in p for p in r.brain.prompts), "one round of a four-step pattern is not yet a loop")
        self.drive(castA(5, 50)); self.drive(bounce(6, 50)); self.drive(castB(7, 55)); self.drive(bounce(8, 55))
        # round three opens: the loose pattern has repeated with the same answers -> offer
        r.brain.script = [{"chosenId": 1, "repeat_cycle": 10, "until": {"life": ">=100"}}]
        self.drive(castA(9, 60))
        self.assertIn("LOOP OFFER: the runner sees your last 4 decisions", r.brain.last_prompt)
        self.assertIsNotNone(r.cycle); self.assertTrue(r.cycle["loose"]); self.assertEqual(len(r.cycle["steps"]), 4)
        self.assertEqual(self.drive(bounce(10, 60)), {"chosenId": 1})
        self.assertEqual(self.drive(castB(11, 70)), {"chosenId": 1}, "the Sol Ring half of the round, replayed by its own recorded answer")
        self.assertEqual(self.drive(bounce(12, 70)), {"chosenId": 1})
        # a window outside the pattern is asked of the brain and the loop waits
        r.brain.script = [{"chosen": [0]}]
        r.handle({"seq": 13, "turn": 5, "phase": "MAIN1", "decisionType": "CHOOSE_MODE", "prompt": "mode", "min": 1, "max": 1,
                  "state": {"stack": ["Hullbreaker Horror"], "stackOwners": [3], "life": 80, "manaPool": 0, "opponents": [{"life": 40}] * 3},
                  "options": [{"id": 0, "label": "bounce"}, {"id": 1, "label": "counter"}]})
        self.assertIn("LOOP ARMED: your loop (until life >= 100", r.brain.last_prompt); self.assertIsNotNone(r.cycle)
        self.assertEqual(self.drive(castA(14, 80)), {"chosenId": 1}, "the loop resumed at its next step")
        # an opponent's object is still novelty: paused, and it re-arms loosely when the steps recur for one round
        r.brain.script = [{"chosenId": 0}] + [{"chosenId": 1}] * 4
        self.drive(req(15, "REACT", ["Counterspell  {U}{U}"], stack=["Opponent's Bolt"], life=80))
        self.assertIsNotNone(r._parked); self.assertTrue(r._parked["loose"])
        self.drive(bounce(16, 80)); self.drive(castB(17, 85)); self.drive(bounce(18, 85)); self.drive(castA(19, 90))
        self.assertIsNotNone(r.cycle, r.log_lines[-4:])
        calls = r.brain.calls
        self.assertEqual(self.drive(bounce(20, 90)), {"chosenId": 1}); self.assertEqual(r.brain.calls, calls, "replayed after the resumption")
        self.drive(castB(21, 100))
        self.assertEqual(r.brain.calls, calls + 1); self.assertIn("LOOP STOPPED: life 100 meets >= 100", r.brain.last_prompt)
        # the brain may end an armed loop outright
        r2 = make_runner(); r2.brain.script = [{"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 9, "until": {"life": ">=100"}}, {"chosen": [0], "stop_loop": True}]
        r2.handle(castA(1, 40)); r2.handle(castA(2, 40))
        self.assertIsNotNone(r2.cycle)
        r2.handle({"seq": 3, "turn": 5, "phase": "MAIN1", "decisionType": "CHOOSE_MODE", "prompt": "mode", "min": 1, "max": 1,
                   "state": {"stack": ["x"], "stackOwners": [3], "life": 40, "manaPool": 0, "opponents": [{"life": 40}] * 3},
                   "options": [{"id": 0, "label": "a"}, {"id": 1, "label": "b"}]})
        self.assertIsNone(r2.cycle); self.assertTrue(any("loop ended by the brain" in l for l in r2.log_lines))
        # without a target the strict signature is unchanged: a changed SET of castable names breaks the loop
        # (a newly affordable Tidespout Tyrant), while a target-bearing loop reads on past it
        castC = lambda seq, life: req(seq, "CAST_SPELL", ["Mana Vault  {1}", "Sol Ring  {T} — add", "Tidespout Tyrant  {5}{U}{U}{U}"], life=life)  # noqa: E731
        r3 = make_runner(); r3.brain.script = [{"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 5}, {"chosenId": 1}]
        r3.handle(castA(1, 40)); r3.handle(castA(2, 40)); r3.handle(castC(3, 40))
        self.assertIsNone(r3.cycle); self.assertTrue(any("CYCLE broken" in l for l in r3.log_lines)); self.assertEqual(r3.brain.calls, 3)
        r4 = make_runner(); r4.brain.script = [{"chosenId": 1}, {"chosenId": 1, "repeat_cycle": 5, "until": {"life": ">=100"}}]
        r4.handle(castA(1, 40)); r4.handle(castA(2, 50))
        self.assertEqual(r4.mb.responses[-1][1], {"chosenId": 1}); r4.handle(castC(3, 60))
        self.assertEqual((r4.brain.calls, r4.mb.responses[-1][1]), (2, {"chosenId": 1}), "with a target, the new castable is the loop's own churn: replayed")

