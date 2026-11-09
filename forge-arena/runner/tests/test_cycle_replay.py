"""Cycle replay (backlog item 3): the brain declares repeat_cycle: N on a decision identical to an earlier
one this turn; the runner replays the recorded cycle for matching windows with zero model calls and breaks
out on any novelty. Round 31 (Ben, 2026-09-14): `until` beside repeat_cycle, a LOOP OFFER when the tape
repeats, a parked loop that re-arms. BL-08: cycle rebinding on (label, type, cost); BL-20: a loop containing
one punted decision never arms. The historical harness: game 47, seat 1 (Urza), turn 20 — 138 decisions
replayed through the real runner against what the live brain answered. Offline: fake mailbox + fake brain.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import runner as runner_mod  # noqa: E402
from tests.support import fake_seat_runner as make_runner  # noqa: E402


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


def confirm_req(seq, turn=5):
    return {"seq": seq, "turn": turn, "phase": "MAIN1",
            "decisionType": "CONFIRM", "prompt": "cast the copy?",
            "state": {"stack": ["Isochron Scepter"], "manaPool": 0, "life": 40,
                      "opponents": [{"life": 40}, {"life": 40}, {"life": 40}],
                      "confirmMode": "TRIGGER", "yesCost": "none"},
            "options": [{"id": 0, "label": "No"}, {"id": 1, "label": "Yes"}]}


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


def opt(i, label, typ="Ability", cost=None):
    return {"id": i, "label": label, "type": typ, "cost": cost}


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
        self.drive(r, req(4, "REACT", ["X"], stack=["Dramatic Reversal", "Swan Song"]))
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
        self.drive(A(10, 100))
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


class CycleRebindIdentity(unittest.TestCase):
    """BL-08: two abilities on one card, only one costed, must not cross-bind."""

    def test_prefix_match_requires_same_type_and_cost(self):
        rec = {"options": [opt(0, "Pass (do nothing)", "PASS"),
                           opt(1, "Foo  {2} — costed: draw a card", cost="{2}"),
                           opt(2, "Foo  — free: untap Foo")]}
        shape = runner_mod.SeatRunner._cycle_shape(rec, {"chosenId": 2})
        self.assertEqual(shape, ("label", ("Foo  — free: untap Foo", "Ability", None)))
        # next window: ids swapped AND the descriptions drifted (exact match fails)
        nxt = {"options": [opt(0, "Pass (do nothing)", "PASS"),
                           opt(7, "Foo  — free: untap Foo (again)"),
                           opt(8, "Foo  {2} — costed: draw a card (again)", cost="{2}")]}
        self.assertEqual(runner_mod.SeatRunner._cycle_rebind(shape, nxt), {"chosenId": 7})
        # the costed sibling alone must never satisfy a free shape
        only_costed = {"options": [opt(0, "Pass (do nothing)", "PASS"),
                                   opt(9, "Foo  {2} — costed (again)", cost="{2}")]}
        self.assertIsNone(runner_mod.SeatRunner._cycle_rebind(shape, only_costed))

    def test_exact_identity_still_wins_over_prefix(self):
        rec = {"options": [opt(1, "Bar  {1} — a", cost="{1}"), opt(2, "Bar  {1} — b", cost="{1}")]}
        shape = runner_mod.SeatRunner._cycle_shape(rec, {"chosenId": 2})
        nxt = {"options": [opt(4, "Bar  {1} — a", cost="{1}"), opt(5, "Bar  {1} — b", cost="{1}")]}
        self.assertEqual(runner_mod.SeatRunner._cycle_rebind(shape, nxt), {"chosenId": 5})
        # two same-prefix candidates, neither exact: ambiguous -> no replay
        amb = {"options": [opt(4, "Bar  {1} — x", cost="{1}"), opt(5, "Bar  {1} — y", cost="{1}")]}
        self.assertIsNone(runner_mod.SeatRunner._cycle_rebind(shape, amb))

    def test_the_same_play_offered_twice_rebinds_to_the_first(self):
        """Game 60: Sensei's Top castable off the library through Mystic Forge AND Future Sight — two options
        with one label, type and cost. The model picked either and the loop went on; the replay called it
        ambiguous and woke the model every pass (2026-09-18)."""
        rec = {"options": [opt(0, "Pass (do nothing)", "PASS"), opt(16, "Sensei's Divining Top  {1} — Sensei's Divining Top", cost="{1}"),
                           opt(17, "Sensei's Divining Top  {1} — Sensei's Divining Top", cost="{1}")]}
        shape = runner_mod.SeatRunner._cycle_shape(rec, {"chosenId": 17})
        nxt = {"options": [opt(0, "Pass (do nothing)", "PASS"), opt(18, "Sensei's Divining Top  {1} — Sensei's Divining Top", cost="{1}"),
                           opt(19, "Sensei's Divining Top  {1} — Sensei's Divining Top", cost="{1}")]}
        self.assertEqual(runner_mod.SeatRunner._cycle_rebind(shape, nxt), {"chosenId": 18}, "identical twins: the first is the same play")
        # a costed twin next to a free one is NOT identical: BL-08 still holds
        mixed = {"options": [opt(0, "Pass (do nothing)", "PASS"), opt(18, "Sensei's Divining Top  {1} — Sensei's Divining Top", cost="{1}"),
                             opt(19, "Sensei's Divining Top  — Sensei's Divining Top")]}
        self.assertEqual(runner_mod.SeatRunner._cycle_rebind(shape, mixed), {"chosenId": 18})


class PuntsNeverReplay(unittest.TestCase):
    """BL-20: a loop containing one punted decision never arms."""

    def test_internal_error_clears_the_tape(self):
        r = make_runner()
        r.brain.script = [{"chosenId": 1}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        self.assertEqual(len(r._hist), 1)
        r.brain.decide = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        r.handle(confirm_req(2))
        self.assertEqual(r._hist, [], "an internal error leaves no tape to arm across")
        self.assertEqual(r.mb.responses[-1][1], {"chosenId": 1})  # free own trigger: yes

    def test_punt_inside_the_candidate_cycle_refuses_to_arm(self):
        r = make_runner()
        r.brain.script = [
            {"chosenId": 1},                      # seq1 activate (model)
            None,                                 # seq2 confirm: model failure -> punt
            {"chosenId": 0},                      # seq3 react pass
            {"chosenId": 1, "repeat_cycle": 3},   # seq4 activate again + declare
        ]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        r.handle(confirm_req(2))
        self.assertIn("punt", " ".join(r.log_lines).lower())
        r.handle(req(3, "REACT", ["Counterspell  {U}{U} — counter"], stack=["Dramatic Reversal"]))
        r.handle(req(4, "CAST_SPELL", [SCEPTER], pool=2))
        self.assertIsNone(r.cycle, "a cycle containing a punt must not arm")
        self.assertTrue(any("non-replayable" in ln for ln in r.log_lines), r.log_lines[-3:])

    def test_clean_cycle_still_arms(self):
        r = make_runner()
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1}, {"chosenId": 0},
                          {"chosenId": 1, "repeat_cycle": 3}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        r.handle(confirm_req(2))
        r.handle(req(3, "REACT", ["Counterspell  {U}{U} — counter"], stack=["Dramatic Reversal"]))
        r.handle(req(4, "CAST_SPELL", [SCEPTER], pool=2))
        self.assertIsNotNone(r.cycle)


TAPE = Path(__file__).resolve().parent / "fixtures" / "game47-seat1-turn20.jsonl"


SEAT = 1


def load_tape():
    return [json.loads(l) for l in TAPE.read_text().splitlines() if l.strip()]


def reconstruct_options(tape):
    """The live runner logs option lists only for brain-answered windows; a window it replayed
    itself (source cycle/memo/yield) is given the options of the most recent brain-answered
    window of the same type and stack — which is what a replayed window IS (the cycle engine
    only replays into an identical window)."""
    last = {}
    out = {}
    for row in tape:
        key = (row["type"], tuple(sorted((row.get("board") or {}).get("stack") or [])))
        if row.get("options"):
            last[key] = row["options"]
            out[row["seq"]] = row["options"]
        else:
            out[row["seq"]] = last.get(key) or ["Pass (do nothing)", "(recorded window)"]
    return out


OPTIONS = None


def request_of(row: dict) -> dict:
    global OPTIONS
    if OPTIONS is None:
        OPTIONS = reconstruct_options(load_tape())
    labels = OPTIONS.get(row["seq"]) or ["Pass (do nothing)", "(recorded window)"]

    def cost_of(lab):                                   # "Mana Vault  {1} — Mana Vault" -> "{1}"; a real request carries cost/type fields
        parts = lab.split("  ", 1)
        return parts[1].split(" — ")[0].strip() if len(parts) > 1 else None
    options = [{"id": i, "label": lab, "cost": cost_of(lab)} for i, lab in enumerate(labels)]
    ans = row.get("answer") or {}
    cid = ans.get("chosenId")
    if isinstance(cid, int) and cid not in {o["id"] for o in options}:
        # entity/card ids are object ids, not indices, and a window the live runner replayed itself may have had
        # one option more than the brain-answered window its list was borrowed from: keep the recorded choice legal
        options.append({"id": cid, "label": f"(recorded option {cid})", "cost": None})
    b = row.get("board") or {}
    lives = {int(k): v for k, v in (b.get("lives") or {}).items()}
    stack = list(b.get("stack") or [])
    state = {"stack": stack, "stackOwners": [SEAT] * len(stack), "manaPool": b.get("pool") or 0,
             "life": lives.get(SEAT, 40), "opponents": [{"seat": s, "life": l} for s, l in lives.items() if s != SEAT],
             "untappedManaSourceCount": b.get("untappedSrc") or 0}
    if isinstance(ans.get("chosen"), list):
        state["min"] = state["max"] = len(ans["chosen"])
    return {"seq": row["seq"], "turn": row["turn"], "phase": row.get("phase"), "decisionType": row["type"],
            "prompt": "recorded", "state": state, "options": options, "min": state.get("min"), "max": state.get("max")}


class TapeBrain:
    """Answers each window with what the real brain answered; may accept an offer."""
    effort = "high"
    model = "opus"

    def __init__(self, tape, accept: bool):
        self.by_seq = {r["seq"]: r for r in tape}
        self.accept = accept
        self.calls = 0
        self.offers = 0
        self.accepted = 0
        self.prompts = []

    def decide(self, prompt, timeout_s=None, effort=None, deadline=None):
        self.calls += 1
        self.prompts.append(prompt)
        seq = int(prompt.split("seq=")[1].split()[0])
        out = dict((self.by_seq[seq].get("answer") or {"chosenId": 0}))
        if "LOOP OFFER" in prompt:
            self.offers += 1
            if self.accept:
                self.accepted += 1
                out["repeat_cycle"] = 8
                # the target the real brain would name: its own reason for this window says what the loop is for
                why = (self.by_seq[seq].get("why") or "").lower()
                if "life" in why or "reservoir" in why:
                    out["until"] = {"life": ">=180"}
        out["why"] = self.by_seq[seq].get("why") or "recorded"
        return out, {"latency_s": 0.01, "usage": None, "cache_read": 1, "raw": json.dumps(out)}

    def reset(self):
        pass


def run_tape(policy_accept: bool):
    tape = load_tape()
    r = make_runner()
    r.seat = SEAT
    r.brain = TapeBrain(tape, policy_accept)
    r.rotate_hard = 0
    r.rotate_at = 0
    sources = {}
    mism = []
    for row in tape:
        req = request_of(row)
        before = len(r.mb.responses)
        r.handle(req)
        seq, answer = r.mb.responses[-1]
        assert len(r.mb.responses) == before + 1
        src = "model" if r.brain.calls > sources.get("_calls", 0) else "runner"
        sources["_calls"] = r.brain.calls
        sources[src] = sources.get(src, 0) + 1
        rec = row.get("answer") or {}
        if src == "runner" and row.get("source") == "model" and answer != rec:
            mism.append((seq, row["type"], answer, rec, (row.get("why") or "")[:60]))
    return r, sources, mism


class Game47Turn20(unittest.TestCase):
    def test_fixture_is_the_real_turn(self):
        tape = load_tape()
        self.assertEqual(len(tape), 138)
        self.assertEqual({s: sum(1 for t in tape if t["source"] == s) for s in ("model", "cycle", "memo", "yield")}, {"model": 67, "cycle": 63, "memo": 7, "yield": 1})

    def test_offers_accepted_with_a_stop_condition_cut_the_brain_calls_and_replay_what_the_brain_chose(self):
        r_dec, src_dec, _ = run_tape(policy_accept=False)
        r_acc, src_acc, mism = run_tape(policy_accept=True)
        calls_dec, calls_acc = r_dec.brain.calls, r_acc.brain.calls
        log = "\n".join(l for l in r_acc.log_lines if "CYCLE" in l or "LOOP" in l)
        msg = (f"\nDECLINE: brain calls {calls_dec} (runner {src_dec.get('runner', 0)}) | offers seen {r_dec.brain.offers}"
               f"\nACCEPT : brain calls {calls_acc} (runner {src_acc.get('runner', 0)}) | offers {r_acc.brain.offers}, accepted {r_acc.brain.accepted}"
               f"\nreplayed answers that differ from the recorded brain answer: {len(mism)} -> {mism[:6]}\n{log}")
        print(msg)
        self.assertGreaterEqual(r_acc.brain.offers, 1, "the tape shows a repeating loop: at least one offer" + msg)
        self.assertLess(calls_acc, calls_dec, "accepting the offers must save brain calls" + msg)
        self.assertTrue(any("CYCLE armed" in l for l in r_acc.log_lines), msg)
        self.assertGreaterEqual(calls_dec - calls_acc, 20, "the offer in the 20:39 mana loop replays the rounds the live brain declared by hand" + msg)
        # every replayed answer must be what the brain actually chose in that window: a divergence here is a real bug
        self.assertEqual(mism, [], msg)

    def test_the_hand_played_reservoir_rounds_were_not_a_clean_repetition(self):
        """The honest negative: after Ben's Ambush the brain resumed the loop by hand for six rounds but
        interleaved extra value actions (floating Vault's mana, tapping Sol Ring before its bounce) every other
        round, so no two consecutive rounds were identical even loosely until the loop's last round — neither
        the offer nor a declaration could have replayed them. What would have: a target declared on the FIRST
        cycle, which parks on the interruption and re-arms when one clean round recurs (tested in
        test_cycle_replay); the tape shows one such round (seq 224-233) before the target was met."""
        r, src, mism = run_tape(policy_accept=True)
        offers_after_ambush = [l for l in r.log_lines if "LOOP OFFER" in l]
        self.assertEqual(len(offers_after_ambush), 1, "one offer, in the 20:39 mana loop; none in the hand-played stretch")
