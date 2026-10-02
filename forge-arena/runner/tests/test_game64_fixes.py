"""Game 64 (2026-10-02, all-AI watch game) — the runner-side fixes.

BL-62  the same-turn pass memo forgets its passes when a stack object with a NEW name appears: a window
       that looks like one already passed may sit on the far side of a resolution (Giada's Kabira Takedown,
       Collective Resistance above it, then the same stack again — memo-passed, Takedown fizzled).
BL-61  a punt on a TARGETS window carries "punt": true, so the engine aims with its stock logic instead of
       taking the first options (possibly the seat's own permanents) or nothing at all.
BL-63  the seats' small-talk truce is struck after the NEXT snapshot, never between the last two seats and
       never across an attack already declared this turn; the filler pool no longer says "deal"; the spoken
       duration is state (no dice) and outlives the wait behind its accept line.
Run: python3 -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import rules  # noqa: E402
from voice import scheduler as sch  # noqa: E402
from test_memo_only_from_model import META, react, runner  # noqa: E402
from test_deals_voice import _DealCase  # noqa: E402


def window(seq, stack, turn=9):
    r = react(seq, turn)
    r["state"]["stack"] = list(stack)
    r["state"]["stackOwners"] = [1] * len(stack)
    r["state"]["stackKinds"] = ["spell"] * len(stack)
    return r


class MemoSeesANewSpell(unittest.TestCase):
    def setUp(self):
        self.r = runner()
        self.calls = []
        self.r.brain.decide = lambda prompt, **kw: (self.calls.append(1) or {"chosenId": 0, "why": "wait"}, dict(META))

    def test_the_window_after_a_new_spell_resolved_goes_to_the_model(self):
        r = self.r
        r.handle(window(1, ["Kabira Takedown"]))
        r.handle(window(2, ["Collective Resistance", "Kabira Takedown"]))
        self.assertEqual(len(self.calls), 2, "a new spell above mine: the model is asked")
        r.handle(window(3, ["Kabira Takedown"]))
        self.assertEqual(len(self.calls), 3, "game 64 t21: the stack looks like window 1, but Resistance resolved in between")
        r.handle(window(4, ["Kabira Takedown"]))
        self.assertEqual(len(self.calls), 3, "the same window again, nothing new since: the memo replays the pass")

    def test_names_already_seen_keep_the_memo(self):
        r = self.r
        for seq, stack in ((1, ["Grinning Ignus"]), (2, ["Purphoros, God of the Forge", "Grinning Ignus"]), (3, ["Grinning Ignus"])):
            r.handle(window(seq, stack))
        self.assertEqual(len(self.calls), 3, "each stack shape once")
        for seq, stack in ((4, ["Purphoros, God of the Forge", "Grinning Ignus"]), (5, ["Grinning Ignus"]),
                           (6, ["Purphoros, God of the Forge", "Grinning Ignus"]), (7, ["Grinning Ignus"])):
            r.handle(window(seq, stack))
        self.assertEqual(len(self.calls), 3, "a loop repeats names the seat has seen: every later lap is memoised (BL-52 keeps its saving)")

    def test_a_yield_is_forgotten_with_the_memo(self):
        """Review 2026-10-02: my trigger on the stack (passed -> yielded), a new spell above it (passed), then the
        trigger alone again: it was auto-yielded with no model call."""
        r = self.r
        def trig(seq, stack, kinds):
            w = window(seq, stack)
            w["state"]["stackKinds"] = list(kinds)
            w["state"]["stackOwners"] = [r.seat] * len(stack)
            return w
        r.handle(trig(1, ["Ravenous Chupacabra"], ["trigger"]))
        r.handle(trig(2, ["Collective Resistance", "Ravenous Chupacabra"], ["spell", "trigger"]))
        r.handle(trig(3, ["Ravenous Chupacabra"], ["trigger"]))
        self.assertEqual(len(self.calls), 3, "the window after the new spell resolved reaches the model, not the yield")

    def test_the_turn_boundary_clears_the_names(self):
        r = self.r
        r.handle(window(1, ["Kabira Takedown"]))
        self.assertEqual(r._stack_names_seen, {"Kabira Takedown"})
        r.handle(window(2, ["Swords to Plowshares"], turn=10))
        self.assertEqual(r._stack_names_seen, {"Swords to Plowshares"})


class TargetWindowPunt(unittest.TestCase):
    def _req(self, purpose, lo):
        return {"decisionType": "CHOOSE_ENTITIES", "seq": 1, "turn": 5,
                "state": {"min": lo, "max": 2, **({"purpose": purpose} if purpose else {})},
                "options": [{"id": 1, "label": "Sol Ring [Urza-S0]"}, {"id": 2, "label": "Grim Monolith [Urza-S0]"}, {"id": 3, "label": "Mox Amber [Urza-S0]"}]}

    def test_a_punt_on_a_target_window_is_marked_and_still_valid(self):
        for lo in (0, 1, 2):
            req = self._req("TARGETS", lo)
            out = rules.safe_default(req)
            self.assertEqual(out, {"chosen": [1, 2][:lo], "punt": True})
            self.assertIsNotNone(rules.validate(req, out), "the invariant: a safe default validates")

    def test_other_multi_pick_windows_punt_as_before(self):
        self.assertEqual(rules.safe_default(self._req(None, 1)), {"chosen": [1]})
        self.assertEqual(rules.safe_default(self._req("SACRIFICE", 0)), {"chosen": []})

    def test_the_seat_may_choose_no_targets_when_the_minimum_is_zero(self):
        req = self._req("TARGETS", 0)
        self.assertEqual(rules.validate(req, {"chosen": []}), {"chosen": []})
        self.assertEqual(rules.validate(req, {"chosen": [3, 1]}), {"chosen": [3, 1]}, "the order is kept: the split follows it")
        self.assertIsNone(rules.validate(req, {"chosen": [1, 1]}))
        self.assertIsNone(rules.validate(req, {"chosen": [1, 2, 3]}), "over state.max")

    def test_the_punt_marker_reaches_the_engine(self):
        """handle() sends rules.safe_default as it is: the engine must see "punt": true."""
        r = runner()
        r.brain.decide = lambda prompt, **kw: (None, dict(META))          # timeout / wedge
        sent = []
        r.mb.respond = lambda req, payload, **kw: sent.append(payload) or True
        req = self._req("TARGETS", 1)
        req.update({"phase": "MAIN1", "prompt": "Choose the TARGETS for Electrolyze", "timeoutSec": 90})
        r.handle(req)
        self.assertEqual(sent, [{"chosen": [1], "punt": True}])

    def test_a_declinable_window_accepts_an_empty_pick_or_the_real_range(self):
        req = self._req("TARGETS", 2)
        req["state"]["declinable"] = True
        self.assertEqual(rules.validate(req, {"chosen": []}), {"chosen": []}, "[] declines the seat's own optional trigger")
        self.assertIsNone(rules.validate(req, {"chosen": [1]}), "one pick is under the real minimum of two")
        self.assertEqual(rules.validate(req, {"chosen": [1, 2]}), {"chosen": [1, 2]})


class SmallTalkTruce(_DealCase):
    """setUp leaves turn 3, seat 1 active, MAIN1: the opener (seat 1) has not declared its attack."""

    def _exchange(self):
        """Seat 1 says "deal" to seat 2 and seat 2's chain reply is spoken; nothing is struck yet."""
        self.r.rng.random = lambda: 0.01
        self._spoken(1, "deal", ctx={"targets": [2]})
        q = [x for x in self.r.queue if x["kind"] == "bark"][0]
        self.r.queue.clear()
        self._spoken(2, q["stock"], ctx=q["ctx"], chain=q["chain"])
        self.assertEqual(self.r._deals, {})

    def _why(self):
        return [r["why"] for r in self._records("noted", "deal") if "not struck" in r.get("why", "")]

    def _past_attacks(self, turn=3, active=1):
        self._snap(turn, active, events=self.ring, phase="MAIN2")

    def test_it_waits_for_the_active_party_to_declare_its_attack_and_is_struck_when_none_came(self):
        self._exchange()
        self.assertIsNone(self.r.settle_smalltalk_truce(), "seat 1's DECLARE_ATTACKERS may be open or in flight: not yet")
        self.assertIsNotNone(self.r.__dict__.get("_smalltalk_truce"), "held, not dropped")
        self.assertEqual((self.r._deals, self._why()), ({}, []))
        self._past_attacks()
        self.assertIsNotNone(self.r.settle_smalltalk_truce())
        self.assertEqual(sorted(self.r._deals), [(1, 2), (2, 1)])
        rec = self._ledger("struck")[0]
        self.assertEqual((rec["by"], rec["source"], rec["deal"]), (2, "voice", {"kind": "truce", "rounds": 1, "until_turn": 7}))
        self.assertIsNone(self.r.__dict__.get("_smalltalk_truce"))

    def test_on_a_third_seats_turn_it_is_struck_at_once(self):
        self._snap(3, 3, events=self.ring)
        self.r.queue.clear()
        self._exchange()
        self.assertIsNotNone(self.r.settle_smalltalk_truce(), "neither party can attack this turn: nothing to wait for")

    def test_an_attack_declared_while_the_reply_played_voids_it_and_nobody_is_a_traitor(self):
        self._snap(3, 2, events=self.ring)             # seat 2's turn
        self.r.queue.clear()
        self._exchange()
        self._attack(2, [1], 3)                        # game 64 t36: the ring event is read after the reply
        self.assertIsNone(self.r.settle_smalltalk_truce())
        self.assertEqual((self.r._deals, self._ledger("struck"), self._ledger("broken")), ({}, [], []))
        self.assertEqual((self._notes(1), self._notes(2)), ([], []), "neither brain is told of a deal that never was")
        self.assertEqual(self._why(), ["small-talk truce 1<->2 not struck: one of them attacked the other since it was said"])
        self.assertIsNone(self.r.__dict__.get("_smalltalk_truce"))

    def test_an_attack_before_the_words_does_not_void_a_truce_spoken_after_combat(self):
        """Gemini review: seat 2 hit seat 1 in combat, THEN they made peace in the second main phase."""
        self._attack(2, [1], 3)
        self._snap(3, 2, events=self.ring, phase="MAIN2")
        self.r.queue.clear()
        self._exchange()
        self.assertIsNotNone(self.r.settle_smalltalk_truce(), "the attack came before the words: the truce stands from here")
        self.assertEqual((sorted(self.r._deals), self._ledger("broken")), ([(1, 2), (2, 1)], []))

    def test_an_attack_on_a_third_seat_does_not_void_it(self):
        self._snap(3, 2, events=self.ring)
        self.r.queue.clear()
        self._exchange()
        self._attack(2, [3], 3)                        # still COMBAT-less MAIN1 in the test snapshot: held
        self.assertIsNone(self.r.settle_smalltalk_truce())
        self._snap(3, 2, events=self.ring, phase="COMBAT_DECLARE_BLOCKERS")
        self.assertIsNotNone(self.r.settle_smalltalk_truce(), "seat 2 attacked seat 3, not its new partner")
        self.assertEqual(sorted(self.r._deals), [(1, 2), (2, 1)])

    def test_the_last_two_seats_strike_nothing(self):
        seats = [dict(self._seat(i), eliminated=(i in (0, 3))) for i in range(4)]
        self._snap(3, 1, seats=seats, events=self.ring)
        self.r.queue.clear()
        self._exchange()
        self.assertIsNone(self.r.settle_smalltalk_truce())
        self.assertEqual((self.r._deals, self._ledger("struck")), ({}, []))
        self.assertEqual(self._why(), ["small-talk truce 1<->2 not struck: only 2 seats live"])

    def test_one_turn_roll_carries_it_and_a_second_drops_it(self):
        self._exchange()
        self._snap(4, 3, events=self.ring)             # seat 1 passed the turn without combat; seat 3 is neither party
        deal = self.r.settle_smalltalk_truce()
        self.assertIsNotNone(deal, "the words were heard a moment ago: struck on the new turn")
        self.assertEqual(self._ledger("struck")[0]["deal"]["until_turn"], 8, "one round from turn 4, four seats")

    def test_two_turn_rolls_drop_it(self):
        self._exchange()
        self._snap(5, 0, events=self.ring)
        self.assertIsNone(self.r.settle_smalltalk_truce())
        self.assertEqual(self._why(), ["small-talk truce 1<->2 not struck: it went stale (said on turn 3, now turn 5)"])

    def test_a_standing_deal_is_not_overwritten_by_small_talk(self):
        self.r.strike_deal(1, 2, "alliance", 3, by=1, rounds=3)
        self.r.queue.clear()
        self.r._smalltalk_truce = {"a": 1, "b": 2, "turn": 3, "at": self.r.clock(), "seq": 1}
        self._past_attacks()
        self.assertIsNone(self.r.settle_smalltalk_truce())
        self.assertEqual(self.r.deal_between(1, 2)["kind"], "alliance")
        self.assertEqual(len(self._ledger("struck")), 1)
        self.assertEqual(self._why(), ["small-talk truce 1<->2 not struck: a deal already stands between them"])

    def test_the_duration_is_spoken_whatever_the_dice_say_and_waits_for_its_accept_line(self):
        self._exchange()
        self._past_attacks()
        self.r.queue.clear()
        self.r.rng.random = lambda: 0.99            # game 64: "One round." was diced away at p = 0.15, twice
        self.assertIsNotNone(self.r.settle_smalltalk_truce())
        q = [x for x in self.r.queue if x["stock"] == "terms-rounds-1"]
        self.assertEqual(len(q), 1)
        self.assertEqual((q[0]["seat"], q[0]["gap"]), (2, 0.3))
        self.assertAlmostEqual(q[0]["expires"] - self.r.clock(), sch.TERMS_TTL_S, places=3)

    def test_a_truce_struck_long_after_the_reply_says_no_duration(self):
        self._exchange()
        self.clock.t += sch.SMALLTALK_TERMS_WITHIN_S + 1
        self._past_attacks()
        self.r.queue.clear()
        self.assertIsNotNone(self.r.settle_smalltalk_truce())
        self.assertEqual([x for x in self.r.queue if str(x["stock"]).startswith("terms-")], [], "no stray 'One round.' minutes after the reply")

    def test_a_queued_duration_dies_with_its_deal(self):
        self._exchange()
        self._past_attacks()
        self.r.queue.clear()
        self.r.settle_smalltalk_truce()
        self.assertEqual([x["stock"] for x in self.r.queue if str(x["stock"]).startswith("terms-")], ["terms-rounds-1"])
        self.r.break_deal(1, 2, "attack", 4)
        self.assertEqual([x for x in self.r.queue if str(x["stock"]).startswith("terms-")], [], "broken before it was said: never said")
        self.assertTrue([r for r in self._records("dropped", "bark") if r.get("why") == "the deal it described was broken"])

    def test_the_daemon_step_settles_after_reading_the_snapshot_muted_or_not(self):
        """step() order: the snapshot (and its ring) first, then the settlement — in both branches."""
        self._snap(3, 2, events=self.ring)             # seat 2's turn
        self.r.queue.clear()
        self._exchange()
        self.ring.append({"seq": len(self.ring) + 1, "kind": "attack", "turn": 3, "seat": 2, "attackers": 1, "power": 2, "defenders": [1]})
        (self.mailbox / "observer-state.json").write_text(__import__("json").dumps(
            {"turn": 3, "phase": "COMBAT_DECLARE_BLOCKERS", "activeSeat": 2, "gameOver": False,
             "seats": [self._seat(i) for i in range(4)], "events": self.ring, "stackDetail": []}))
        self.r.step()                                   # the attack sits unread in the file until this step
        self.assertEqual((self.r._deals, self._ledger("struck"), self._ledger("broken")), ({}, [], []))
        self.assertEqual(self._why(), ["small-talk truce 1<->2 not struck: one of them attacked the other since it was said"])
        # ...and a muted table still strikes one that is due
        self._snap(4, 3, events=self.ring)
        self.r.queue.clear()
        self.r._smalltalk_truce = {"a": 1, "b": 2, "turn": 4, "at": self.r.clock(), "seq": len(self.ring)}
        self.r.enabled = lambda: False
        self.r.step()
        self.assertEqual(sorted(self.r._deals), [(1, 2), (2, 1)], "the muted branch settles too (this runner owns the ledger)")

    def test_nothing_pending_is_a_no_op(self):
        self.assertIsNone(self.r.settle_smalltalk_truce())
        self.assertEqual(self._records("noted", "deal"), [])

    def test_the_filler_pool_opens_no_deal(self):
        seats = [{"seat": i, "life": 40, "handSize": 3, "battlefield": []} for i in range(4)]
        for living in ([1, 2], [0, 1, 2, 3]):
            cands = self.r.patter_candidates({"turn": 9, "activeSeat": 1, "seats": seats}, living)
            self.assertFalse([c for c in cands if c[1] == "deal" or str(c[1]).startswith("deal-")])
        self.assertNotIn("deal", sch.ANCHORED_PATTER)


class DealConflictLabels(unittest.TestCase):
    """Review 2026-10-02: `_deal_conflict` crashed (int(None)) on the label the engine writes for a seat's
    permanent — "<card> [<commander>-S<n>]" fills the regex's SECOND group — whenever a cycle replay checked a
    target window under a no-target deal; handle() caught it and punted."""

    def test_an_engine_label_names_the_seat_without_raising(self):
        from test_deals_seat import make_runner
        r = make_runner(seat=3)
        r._deals_in_force = {2: {"kind": "no-target", "until_turn": 9}}
        req = {"decisionType": "CHOOSE_ENTITY", "turn": 5, "state": {"opponents": []},
               "options": [{"id": 1, "label": "Sol Ring [Urza, Lord High Artificer-S2]"}, {"id": 2, "label": "Island [Giada, Font of Hope-S1]"}]}
        self.assertTrue(str(r._deal_conflict(req, {"chosenId": 1})).startswith("target "))
        self.assertIsNone(r._deal_conflict(req, {"chosenId": 2}))
        req["decisionType"] = "CHOOSE_ENTITIES"
        self.assertTrue(str(r._deal_conflict(req, {"chosen": [2, 1]})).startswith("target "), "the new TARGETS answer shape too")


if __name__ == "__main__":
    unittest.main()
