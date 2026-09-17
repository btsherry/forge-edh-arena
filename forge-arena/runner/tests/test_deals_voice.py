"""Table deals, the VOICE side (plan docs/reviews/2026-09-16-table-deals-plan.md §11 — the contract).
The voice runner owns the deal ledger: the live `_deals` map ((a, b) -> {kind, until_turn, struck,
offer_id}, both ways, checkpointed), the append-only logs/deals.jsonl, and the notes that tell a seat's
brain what was agreed (mailbox/seat-<n>/notes/<ts_ms>-deal-struck|broken|lapsed.json). Sources of a deal:
a seat brain's DEAL record in game.jsonl (accept / refuse / counter), the player's acceptance of a counter
(logs/control/deal/<ts>-accept.json), and the seats' own voice truce (deal -> promise). Breaks: an attack
across a truce/alliance, a stack item targeting the other party across a no-target/alliance. The lines:
deal-with-you / no-deal-with-you / counter-offer (anchored, source brain), deal-over, you-broke-it,
i-broke-it; Joshua's joshua-deal-yes/no/counter when the Executive answers for seat 0.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402
from voice import atoms as A  # noqa: E402
from voice import scheduler as sch  # noqa: E402
from voice import table_lines  # noqa: E402
from test_barks_runtime import silent_wav  # noqa: E402
from test_table_lines import _TableCase, REAL_VOICES, LIBS  # noqa: E402

DEAL_IDS = tuple(table_lines.DEALS)
JOSHUA_IDS = ("joshua-deal-yes", "joshua-deal-no", "joshua-deal-counter")


class _DealCase(_TableCase):
    """The table case (0 Giada the human, 1 Urza/harry, 2 Purphoros/bill, 3 Selvala voiceless) with the six deal
    ids in the fake table sub-libraries (the real manifests carry them once the integrator renders), a primed
    ring, and the dice always passing (rng.random = 0)."""

    def setUp(self):
        super().setUp()
        for lib in ("harry", "bill"):
            d = vr.VOICES_DIR / lib / "table"
            m = json.loads((d / "manifest.json").read_text())
            for pid in DEAL_IDS:
                m["phrases"][pid] = {"text": ["x"]}
                (d / f"{pid}.wav").write_bytes(silent_wav())
            (d / "manifest.json").write_text(json.dumps(m))
        self.r.table_ids, self.r.card_ids = self.r._load_sub_ids()
        self.r.rng.seed(7)
        self.ring = [{"seq": 1, "kind": "cast", "turn": 2, "seat": 1, "spell": "x", "cmc": 1}]
        self._snap(3, 1, events=self.ring)                         # the first read primes the ring: never replay
        self.r.queue.clear()

    # ---- helpers
    def _game(self, rec: dict) -> None:
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(json.dumps({"ts": time.time(), "deck": "x", "phase": "MAIN1", "seq": 9, **rec}) + "\n")
        self.r.scan_game_log()

    def _deal_record(self, seat, accept, *, counter=None, terms=None, with_=0, turn=3, offer_id="o1", ts=None) -> None:
        deal = {"offer_id": offer_id, "accept": accept, "with": with_}
        if terms is not None:
            deal["terms"] = terms
        if counter is not None:
            deal["counter"] = counter
        rec = {"seat": seat, "turn": turn, "type": "DEAL", "deal": deal}
        if ts is not None:
            rec["ts"] = ts
        self._game(rec)

    def _ledger(self, event=None) -> list[dict]:
        f = self.logs / "deals.jsonl"
        out = [json.loads(l) for l in (f.read_text().splitlines() if f.exists() else [])]
        return [r for r in out if event is None or r["event"] == event]

    def _notes(self, seat) -> list[dict]:
        d = self.mailbox / f"seat-{seat}" / "notes"
        if not d.exists():
            return []
        out = []
        for f in sorted(d.iterdir()):
            body = json.loads(f.read_text())
            stem, _, kind = f.name[:-5].partition("-")
            self.assertTrue(stem.isdigit(), f"{f.name}: <ts_ms>-<kind>.json")
            self.assertEqual(kind, body["kind"], f"{f.name}: the file is named for its kind")
            out.append(body)
        return out

    def _note(self, seat, kind) -> dict:
        """The last note of `kind` for a seat (two kinds written in one millisecond sort by name, not time)."""
        found = [n for n in self._notes(seat) if n["kind"] == kind]
        self.assertTrue(found, f"seat {seat}: no {kind} note")
        return found[-1]

    def _queue(self):
        return [(q["stock"], q["library"], q["seat"]) for q in self.r.queue]

    def _seat_lines(self):
        return [(q["stock"], q["library"], q["seat"]) for q in self.r.queue if q["kind"] == "bark"]       # without Joshua's "your move" on the human's turn

    def _attack(self, seat, defenders, turn, power=2):
        self.ring.append({"seq": len(self.ring) + 1, "kind": "attack", "turn": turn, "seat": seat, "attackers": 1, "power": power, "defenders": list(defenders)})
        self._snap(turn, seat, events=self.ring)


class ADealFromTheSeat(_DealCase):
    """A seat brain's DEAL record: struck / refused / counter — the ledger, the notes, the seat's line."""

    def test_accepting_the_players_offer_strikes_the_deal_notes_the_seat_and_says_deal_with_you(self):
        self._deal_record(1, True, terms={"kind": "truce", "rounds": 1})
        struck = {"kind": "truce", "until_turn": 7, "struck": 3, "offer_id": "o1"}          # turn 3 + one round of four living seats
        self.assertEqual(self.r._deals, {(1, 0): struck, (0, 1): struck}, "both directions, the contract's dict")
        led = self._ledger()
        self.assertEqual(len(led), 1)
        rec = led[0]
        self.assertEqual({k: rec[k] for k in ("turn", "event", "between", "by", "deal", "offer_id", "seq")},
                         {"turn": 3, "event": "struck", "between": [1, 0], "by": 1, "deal": {"kind": "truce", "rounds": 1, "until_turn": 7}, "offer_id": "o1", "seq": 1})
        self.assertIsInstance(rec["ts"], float)
        self.assertEqual(self._notes(1), [{"kind": "deal-struck", "between": [1, 0], "deal": {"kind": "truce", "rounds": 1, "until_turn": 7}, "offer_id": "o1", "turn": 3}])
        self.assertFalse((self.mailbox / "seat-0" / "notes").exists(), "the human has no runner: no note to seat 0 while the Executive is off")
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["seat"], x["source"], x["prio"], x["ctx"]["targets"]) for x in q],
                         [("deal-with-you", "harry/table", 1, "brain", sch.ANCHORED_PRIO, [0])], "the seat's answer, anchored, addressed to the player")
        self.assertEqual(self._records("noted", "deal")[-1]["why"], "deal struck: 1<->0 by 1")

    def test_executive_on_the_seat_zero_runner_is_a_party_and_gets_the_note(self):
        (self.logs / "control").mkdir(exist_ok=True)
        (self.logs / "control" / "executive.json").write_text(json.dumps({"on": True}))
        self._deal_record(1, True, terms={"kind": "alliance", "until_turn": 9})
        self.assertEqual(self.r._deals[(0, 1)], {"kind": "alliance", "until_turn": 9, "struck": 3, "offer_id": "o1"}, "until_turn given: taken as is")
        self.assertEqual([n["kind"] for n in self._notes(0)], ["deal-struck"])
        self.assertEqual([n["kind"] for n in self._notes(1)], ["deal-struck"])
        self.assertEqual(self._ledger("struck")[0]["deal"], {"kind": "alliance", "until_turn": 9}, "no rounds when the offer named a turn")

    def test_a_refusal_is_recorded_and_said_and_strikes_nothing(self):
        self._deal_record(2, False, terms={"kind": "no-target", "rounds": 2})
        self.assertEqual(self.r._deals, {})
        self.assertEqual([(r["event"], r["between"], r["by"], r["deal"], r["offer_id"]) for r in self._ledger()],
                         [("refused", [2, 0], 2, {"kind": "no-target", "rounds": 2}, "o1")])
        self.assertEqual(self._notes(2), [], "nothing to tell the brain: it refused")
        self.assertEqual(self._queue(), [("no-deal-with-you", "bill/table", 2)])

    def test_a_counter_is_remembered_said_and_struck_when_the_player_accepts_it(self):
        self._deal_record(1, False, terms={"kind": "truce", "rounds": 1}, counter={"kind": "no-target", "rounds": 2})
        self.assertEqual(self.r._deals, {})
        self.assertEqual(self.r._deal_counters, {"o1": {"between": [1, 0], "deal": {"kind": "no-target", "rounds": 2}, "turn": 3}})
        self.assertEqual([(r["event"], r["by"], r["deal"]) for r in self._ledger()], [("counter", 1, {"kind": "no-target", "rounds": 2})])
        self.assertEqual(self._queue(), [("counter-offer", "harry/table", 1)])
        self.r.queue.clear()
        # the player: "@urza accept" — the advisor writes the control file; the voice runner consumes it
        d = self.logs / "control" / "deal"
        d.mkdir(parents=True)
        f = d / "1700000000123-accept.json"
        f.write_text(json.dumps({"offer_id": "o1"}))
        self.r.scan_deal_control()
        self.assertFalse(f.exists(), "consumed")
        self.assertEqual(self.r._deal_counters, {})
        self.assertEqual(self.r._deals[(1, 0)], {"kind": "no-target", "until_turn": 11, "struck": 3, "offer_id": "o1"}, "two rounds of four seats from turn 3")
        rec = self._ledger("struck")[0]
        self.assertEqual((rec["by"], rec["between"], rec["deal"], rec["source"]), (0, [1, 0], {"kind": "no-target", "rounds": 2, "until_turn": 11}, "player"))
        self.assertEqual([n["kind"] for n in self._notes(1)], ["deal-struck"])
        self.assertEqual(self._queue(), [("deal-with-you", "harry/table", 1)], "the seat confirms the pact aloud")

    def test_an_accept_for_an_unknown_offer_is_noted_and_dropped(self):
        d = self.logs / "control" / "deal"
        d.mkdir(parents=True)
        (d / "1-accept.json").write_text(json.dumps({"offer_id": "nope"}))
        (d / "2-accept.json").write_text("{not json")
        old = time.time() - 10
        os.utime(d / "2-accept.json", (old, old))
        (d / "3-accept.json").write_text("{torn")                     # fresh: mid-write, waits
        self.r.scan_deal_control()
        self.assertEqual(sorted(f.name for f in d.iterdir()), ["3-accept.json"])
        whys = [r["why"] for r in self._records("noted", "deal")]
        self.assertIn("accept for an unknown or expired offer: nope", whys)
        self.assertTrue(any(w.startswith("unreadable accept file 2-accept.json") for w in whys), whys)
        self.assertEqual(self.r._deals, {})

    def test_a_counter_nobody_accepted_expires_at_the_turn_roll(self):
        self._deal_record(1, False, counter={"kind": "truce", "rounds": 1})
        self.r.queue.clear()
        self._snap(4, 2, events=self.ring)
        self.assertEqual(self.r._deal_counters, {})
        self.assertEqual([(r["event"], r["between"], r["offer_id"]) for r in self._ledger("expired")], [("expired", [1, 0], "o1")])

    def test_a_record_without_terms_is_a_one_round_truce_and_a_stale_one_is_recorded_but_not_voiced(self):
        self._deal_record(2, True, ts=time.time() - 60)
        self.assertEqual(self.r._deals[(2, 0)], {"kind": "truce", "until_turn": 7, "struck": 3, "offer_id": "o1"}, "no terms: rounds 1 truce")
        self.assertEqual(len(self._ledger("struck")), 1)
        self.assertEqual(self._queue(), [], "read late: the fact stands, the line is history")
        self.assertTrue(any(r["why"].startswith("stale deal answer") for r in self._records("skipped", "bark")))

    def test_the_seats_say_twin_and_the_deal_record_speak_once_whichever_comes_first(self):
        self._deal_record(1, True, terms={"kind": "truce", "rounds": 1})
        self._game({"seat": 1, "turn": 3, "type": "CAST_SPELL", "source": "model", "answer": {"choice": 0}, "say": "take-the-deal"})
        self.assertEqual(self._seat_lines(), [("deal-with-you", "harry/table", 1)], "the DEAL record spoke; the say twin stays quiet")
        self.assertEqual(self._records("skipped", "bark")[-1]["why"], "the DEAL answer already spoke (deal-with-you)")
        self.r.queue.clear()
        self._snap(4, 2, events=self.ring); self.r.queue.clear()
        self._game({"seat": 2, "turn": 4, "type": "CAST_SPELL", "source": "model", "answer": {"choice": 0}, "say": "no-deal"})
        self._deal_record(2, False, turn=4, offer_id="o2")
        self.assertEqual(self._seat_lines(), [("no-deal", "bill/table", 2)], "the say came first and spoke; the DEAL record's line stays quiet")
        self.assertEqual(self._records("skipped", "bark")[-1]["why"], "the seat's say already spoke for this answer")
        self.assertEqual([r["event"] for r in self._ledger()], ["struck", "refused"], "the ledger records both regardless")

    def test_a_deal_record_is_read_with_the_barks_off(self):
        self.r.barks_mode = "off"
        self._deal_record(1, True)
        self.assertIn((1, 0), self.r._deals)
        self.assertEqual([n["kind"] for n in self._notes(1)], ["deal-struck"])
        self.assertEqual(self._queue(), [])

    def test_executive_answers_are_joshuas_lines(self):
        (self.logs / "control").mkdir(exist_ok=True)
        (self.logs / "control" / "executive.json").write_text(json.dumps({"on": True}))
        self._deal_record(0, True, with_=1, terms={"kind": "truce", "rounds": 1}, offer_id="a")
        self.assertEqual(self.r._deals[(0, 1)]["offer_id"], "a")
        self.assertEqual([n["kind"] for n in self._notes(1)], ["deal-struck"]); self.assertEqual([n["kind"] for n in self._notes(0)], ["deal-struck"])
        self._deal_record(0, False, with_=2, offer_id="b")
        self._deal_record(0, False, with_=2, offer_id="c", counter={"kind": "alliance", "rounds": 1})
        self.assertEqual([(q["kind"], q["stock"], q["library"], q["seat"]) for q in self.r.queue],
                         [("quip", "joshua-deal-yes", "", None), ("quip", "joshua-deal-no", "", None), ("quip", "joshua-deal-counter", "", None)][-1:],
                         "Joshua's stock lines, one pending quip at a time (newest wins) — like his other quips")
        self.assertEqual([r["stock"] for r in self._records("queued", "quip")], list(JOSHUA_IDS))
        self.assertEqual([r["event"] for r in self._ledger()], ["struck", "refused", "counter"])


class ADealBrokenOrLapsed(_DealCase):
    """Break detection and the lapse: the ring's attack, the stack's targets, the turn roll."""

    def test_an_attack_across_a_truce_is_broken_noted_to_the_wronged_party_and_called_out(self):
        self.r.strike_deal(1, 2, "truce", 3, by=1, rounds=1)
        self.r.queue.clear()
        self._attack(1, [2], 5)
        self.assertEqual(self._queue(), [("you-promised", "bill/table", 2), ("i-broke-it", "harry/table", 1)], "the objection, then the breaker owns it")
        broke = [q for q in self.r.queue if q["stock"] == "i-broke-it"][0]
        self.assertTrue(broke["follow"], "behind the objection, never evicting it")
        self.assertEqual(self.r._deals, {})
        rec = self._ledger("broken")[0]
        self.assertEqual((rec["between"], rec["by"], rec["how"], rec["deal"], rec["turn"]), ([1, 2], 1, "attack", {"kind": "truce", "until_turn": 7}, 5))
        self.assertEqual([n for n in self._notes(2) if n["kind"] == "deal-broken"], [{"kind": "deal-broken", "between": [1, 2], "by": 1, "how": "attack", "turn": 5}])
        self.assertEqual([n["kind"] for n in self._notes(1)], ["deal-struck"], "the breaker chose: no note")

    def test_an_attack_across_a_no_target_pact_breaks_nothing_and_a_hit_on_a_voiceless_party_is_still_recorded(self):
        self.r.strike_deal(1, 2, "no-target", 3, by=1)
        self.r.queue.clear()
        self._attack(1, [2], 5)
        self.assertIn((1, 2), self.r._deals, "a no-target pact allows combat")
        self.assertNotIn("you-promised", [s for s, _, _ in self._queue()])
        self.r.queue.clear()
        self.r.strike_deal(1, 3, "alliance", 5, by=3)
        self.r.queue.clear()
        self._attack(1, [3], 6)
        self.assertNotIn((1, 3), self.r._deals)
        self.assertEqual(self._ledger("broken")[-1]["between"], [1, 3])
        self.assertEqual(sorted(n["kind"] for n in self._notes(3)), ["deal-broken", "deal-struck"], "Selvala has no voice but has a brain")
        self.assertEqual(self._queue(), [("i-broke-it", "harry/table", 1)], "nobody voiced to object: the breaker's own line stands alone")

    def test_the_human_breaking_a_deal_earns_you_broke_it(self):
        self.r.strike_deal(1, 0, "truce", 3, by=1)
        self.r.queue.clear()
        self._attack(0, [1], 4, power=9)
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["seat"], x["source"], x["prio"], x["ctx"]["aggressor"], x["ctx"]["human_cause"]) for x in q],
                         [("you-broke-it", "harry/table", 1, "event", sch.ANCHORED_PRIO, 0, True)], "anchored, certain; no brace/why-me beside it")
        rec = self._ledger("broken")[0]
        self.assertEqual((rec["between"], rec["by"], rec["how"]), ([0, 1], 0, "attack"))
        self.assertEqual(sorted(n["kind"] for n in self._notes(1)), ["deal-broken", "deal-struck"])
        self.assertFalse((self.mailbox / "seat-0" / "notes").exists())

    def test_a_spell_targeting_the_other_party_breaks_a_no_target_pact_but_not_a_truce(self):
        seats = [self._seat(0), self._seat(1), self._seat(2, creatures=(("Bear", False),)), self._seat(3)]
        self.r.strike_deal(1, 2, "no-target", 3, by=2)
        self.r.queue.clear()
        self._snap(4, 1, seats=seats, stack=[{"kind": "spell", "name": "Bolt", "owner": 1, "targets": ["seat 2"]}])
        self.assertEqual(self._queue(), [("you-promised", "bill/table", 2), ("i-broke-it", "harry/table", 1)], "the objection stands; no hold-on evicts it")
        self.assertEqual(self._ledger("broken")[0]["how"], "target")
        self.assertEqual(self._note(2, "deal-broken"), {"kind": "deal-broken", "between": [1, 2], "by": 1, "how": "target", "turn": 4})
        self.r.queue.clear()
        # a permanent's name resolves to its controller; a truce is not broken by targeting (hold-on fires as before)
        self.r.strike_deal(1, 2, "truce", 4, by=1)
        self.r.queue.clear()
        self._snap(4, 1, seats=seats, stack=[{"kind": "spell", "name": "Murder", "owner": 1, "targets": ["Bear"]}])
        self.assertIn((1, 2), self.r._deals)
        self.assertEqual(self._queue(), [("hold-on", "bill/table", 2)])
        self.r.queue.clear()
        self.r._deals.clear()
        self.r.strike_deal(1, 2, "alliance", 4, by=1)
        self.r.queue.clear()
        self._snap(4, 1, seats=seats, stack=[{"kind": "ability", "name": "Ping", "owner": 1, "targets": ["Bear"]}])
        self.assertNotIn((1, 2), self.r._deals, "an alliance is both: targeting a permanent breaks it")
        self.r.queue.clear()
        # a spell on the stack is not a permanent: countering across a no-target pact is legal
        self.r.strike_deal(1, 2, "no-target", 4, by=1)
        self.r.queue.clear()
        self._snap(4, 2, seats=seats, stack=[{"kind": "spell", "name": "Negate", "owner": 1, "targets": ["Bear (on the stack)"]}])
        self.assertIn((1, 2), self.r._deals)

    def test_the_human_targeting_across_a_no_target_pact_earns_you_broke_it(self):
        self.r.strike_deal(2, 0, "no-target", 3, by=2)
        self.r.queue.clear()
        self._snap(4, 0, stack=[{"kind": "spell", "name": "Bolt", "owner": 0, "targets": ["seat 2"]}])
        self.assertEqual(self._seat_lines(), [("you-broke-it", "bill/table", 2)], "the objection, and no hold-on beside it")
        self.assertEqual((self._ledger("broken")[0]["by"], self._ledger("broken")[0]["how"]), (0, "target"))

    def test_a_deal_lapses_at_the_roll_past_until_turn_with_notes_to_both_and_deal_over(self):
        self.r.strike_deal(1, 2, "truce", 3, by=1)                 # until turn 7 inclusive
        self.r.queue.clear()
        self._snap(7, 3, events=self.ring)
        self.assertIn((1, 2), self.r._deals, "turn 7 is still inside the deal")
        self.assertEqual(self._ledger("lapsed"), [])
        self._snap(8, 0, events=self.ring)
        self.assertEqual(self.r._deals, {})
        rec = self._ledger("lapsed")[0]
        self.assertEqual((rec["between"], rec["by"], rec["deal"], rec["turn"]), ([1, 2], None, {"kind": "truce", "until_turn": 7}, 8))
        for s in (1, 2):
            self.assertEqual(self._note(s, "deal-lapsed"), {"kind": "deal-lapsed", "between": [1, 2], "turn": 8})
        q = [x for x in self.r.queue if x["stock"] == "deal-over"]
        self.assertEqual(len(q), 1)
        self.assertIn((q[0]["seat"], q[0]["ctx"]["targets"]), [(1, [2]), (2, [1])], "one party remarks on it, to the other")
        self.assertEqual(q[0]["library"], f"{'harry' if q[0]['seat'] == 1 else 'bill'}/table")

    def test_a_lapse_with_the_human_gives_the_human_no_note_and_the_seat_the_line(self):
        self.r.strike_deal(1, 0, "truce", 3, by=1)
        self.r.queue.clear()
        self._snap(8, 0, events=self.ring)
        self.assertEqual(sorted(n["kind"] for n in self._notes(1)), ["deal-lapsed", "deal-struck"])
        self.assertFalse((self.mailbox / "seat-0" / "notes").exists())
        self.assertEqual(self._seat_lines(), [("deal-over", "harry/table", 1)])


class SeatToSeatAndTheChains(_DealCase):
    """The old voice truce rides the new ledger; the chain rows; the backchannel classes."""

    def test_a_seat_to_seat_voice_truce_is_struck_in_the_ledger_and_tells_both_brains(self):
        self.r.rng.random = lambda: 0.01
        self._spoken(1, "deal", ctx={"targets": [2]})
        q = [x for x in self.r.queue if x["kind"] == "bark"][0]
        self.assertIn(q["stock"], ("promise", "take-the-deal"))
        self.r.queue.clear()
        self._spoken(2, q["stock"], ctx=q["ctx"], chain=q["chain"])
        struck = {"kind": "truce", "until_turn": 7, "struck": 3, "offer_id": None}
        self.assertEqual(self.r._deals, {(1, 2): struck, (2, 1): struck})
        rec = self._ledger("struck")[0]
        self.assertEqual((rec["between"], rec["by"], rec["deal"], rec["offer_id"], rec["source"]), ([1, 2], 2, {"kind": "truce", "rounds": 1, "until_turn": 7}, None, "voice"))
        for s in (1, 2):
            self.assertEqual(self._notes(s), [{"kind": "deal-struck", "between": [1, 2], "deal": {"kind": "truce", "rounds": 1, "until_turn": 7}, "offer_id": None, "turn": 3}])
        self.assertEqual(self._notes(0), [])

    def test_deal_with_you_invites_a_bystander_taunt_at_point_three_five_and_is_no_question(self):
        self.r.rng.random = lambda: 0.34
        self._spoken(1, "deal-with-you", ctx={"targets": [0]})
        self.assertEqual(self._queue(), [("taunt", "bill", 2)], "the bystander jabs at the seat that dealt")
        self.r.queue.clear()
        self.r._roll_turn(4)
        self.r.rng.random = lambda: 0.36
        self._spoken(1, "deal-with-you", ctx={"targets": [0]})
        self.assertEqual(self._queue(), [])
        self.assertEqual(self._records("skipped", "bark")[-1]["why"], "dice (chain hop 1, p=0.35)", "CHAIN_P_OVERRIDE, not the certain answer a question gets")
        self.assertFalse(sch.is_question("deal-with-you")); self.assertFalse(sch.is_question("deal-over")); self.assertTrue(sch.is_question("deal-urza")); self.assertTrue(sch.is_question("deal"))

    def test_you_broke_it_invites_a_laugh_and_deal_over_invites_nothing(self):
        self.r.rng.random = lambda: 0.0
        self._spoken(1, "you-broke-it", ctx={"targets": [], "aggressor": 0, "human_cause": True})
        self.assertEqual(self._queue(), [("laugh", "bill", 2)])
        self.r.queue.clear()
        self._spoken(1, "deal-over", ctx={"targets": [2]})
        self.assertEqual(self._queue(), [], "the 'deal-' family must not answer 'our truce is done' with 'deal, for one turn'")
        rows = json.loads((REAL_VOICES / "chains.json").read_text())["invites"]
        self.assertEqual(rows["deal-with-you"], [{"role": "bystander", "reply": "taunt"}])
        self.assertEqual(rows["you-broke-it"], [{"role": "bystander", "reply": "laugh"}])
        self.assertEqual(rows["deal-over"], [])

    def test_the_backchannel_classes(self):
        for pid in ("deal-with-you", "no-deal-with-you", "counter-offer"):
            self.assertEqual(A.atom_class(pid), "proposal", pid)
        for pid in ("you-broke-it", "i-broke-it"):
            self.assertEqual(A.atom_class(pid), "jab", pid)


class TheCheckpoint(_DealCase):
    """The new `_deals` shape round-trips; an old checkpoint's ints upgrade."""

    def test_deals_and_counters_round_trip_and_the_old_shape_upgrades(self):
        self.r.strike_deal(1, 0, "no-target", 3, by=1, rounds=2, offer_id="o1")
        self.r._deal_counters["o2"] = {"between": [2, 0], "deal": {"kind": "truce", "rounds": 1}, "turn": 3}
        self.r.queue.clear()
        self.assertTrue(self.r.save_state(force=True))
        st = json.loads((self.logs / vr.STATE_FILE).read_text())
        deal = {"kind": "no-target", "until_turn": 11, "struck": 3, "offer_id": "o1"}
        self.assertEqual(st["deals"], [[0, 1, deal], [1, 0, deal]])
        self.assertEqual(st["deal_counters"], {"o2": {"between": [2, 0], "deal": {"kind": "truce", "rounds": 1}, "turn": 3}})
        self.assertEqual(st["deal_seq"], 1)
        # a second runner adopts it
        st["deals"].append([1, 2, 5]); st["deals"].append([2, 1, 5])                    # an OLD checkpoint's shape: the struck turn
        st["deals"].append([2, 3, "junk"])
        (self.logs / vr.STATE_FILE).write_text(json.dumps(st))
        r2 = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock, tuning=self.tuning)
        self.assertIsNotNone(r2._pending_state)
        r2.scan_observer()
        self.assertEqual(r2._deals[(1, 0)], deal); self.assertEqual(r2._deals[(0, 1)], deal)
        self.assertEqual(r2._deals[(1, 2)], {"kind": "truce", "until_turn": 5 + sch.DEAL_TURNS, "struck": 5, "offer_id": None}, "upgraded: a truce for DEAL_TURNS")
        self.assertNotIn((2, 3), r2._deals)
        self.assertEqual(r2._deal_counters, {"o2": {"between": [2, 0], "deal": {"kind": "truce", "rounds": 1}, "turn": 3}})
        self.assertEqual(r2._deal_seq, 1)
        self.assertEqual(sch.normalize_deal(4), {"kind": "truce", "until_turn": 12, "struck": 4, "offer_id": None})
        self.assertIsNone(sch.normalize_deal("x")); self.assertIsNone(sch.normalize_deal(None))
        self.assertEqual(sch.deal_terms({"kind": "bogus", "rounds": 9}), {"kind": "truce", "rounds": 3}, "unknown kind -> truce; rounds clamped")
        self.assertEqual(sch.deal_terms({"kind": "alliance", "until_turn": "12", "rounds": 2}), {"kind": "alliance", "until_turn": 12}, "exactly one duration")
        self.assertEqual(sch.deal_terms(None), {"kind": "truce", "rounds": 1})


class TheWordings(unittest.TestCase):
    """The DEALS group of table_lines.py: six ids x three voices x four wordings, the rules, the ids the runner expects."""

    def test_six_ids_three_voices_four_wordings_addressed_to_player_one(self):
        self.assertEqual(set(DEAL_IDS), set(sch.DEAL_LINES))
        self.assertEqual(set(sch.DEAL_ANSWER_LINE.values()), {"deal-with-you", "no-deal-with-you", "counter-offer"})
        self.assertEqual(tuple(sch.JOSHUA_DEAL_LINE[k] for k in ("accept", "refuse", "counter")), JOSHUA_IDS)
        for lib in LIBS:
            ph = table_lines.build_manifest(lib)["phrases"]
            for pid in DEAL_IDS:
                p = ph[pid]
                self.assertEqual((p["category"], p["source"], len(p["text"])), ("deal", "table-deal-2026-09-16", 4), f"{lib}/{pid}")
                self.assertTrue(p["when"])
                self.assertEqual(len(set(p["text"])), 4)
                for t in p["text"]:
                    self.assertRegex(t, r"^\[[a-z ]+\] \S", f"{lib}/{pid}: {t!r}")
                    self.assertLessEqual(len(t.split("]", 1)[1].split()), 10, f"{lib}/{pid}: {t!r}")
                    if pid in table_lines.DEALS_ADDRESSED:
                        self.assertIn("Player One", t, f"{lib}/{pid}: spoken to the player")
                    self.assertNotIn("{", t, "fixed lines: no fills")
            self.assertEqual(sum(1 for p in ph.values() if p["category"] == "deal"), 6)


class ASeatsOwnOffer(_DealCase):
    """Ben, 2026-09-16: a seat's DEAL record with "propose" — the `offer` ledger record, the deal line spoken to the
    party (state, terminal), an offer to the player remembered until the advisor's accept/refuse file."""

    def _propose(self, seat, to, terms, oid, turn=3):
        self._game({"seat": seat, "turn": turn, "type": "DEAL", "deal": {"offer_id": oid, "propose": True, "with": to, "terms": terms}})

    def test_seat_to_seat_the_offer_is_spoken_and_the_answer_strikes_it(self):
        self.r.rng.random = lambda: 0.99                              # the generic wording, not the named take
        terms = {"kind": "truce", "rounds": 2}
        self._propose(1, 2, terms, "p1")
        self.assertEqual([(x["event"], x["between"], x["by"], x["deal"], x["offer_id"]) for x in self._ledger()], [("offer", [1, 2], 1, terms, "p1")])
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["seat"], x["source"], x["ctx"]["targets"], x["ctx"].get("terminal")) for x in q],
                         [("deal", "harry", 1, "brain", [2], True)], "the seat asks the party, never rolled; the voice chain's small-talk truce does not answer it")
        self.assertEqual(self.r._deal_counters, {}, "a seat answers a seat: nothing waits on the player")
        self.r.queue.clear()
        self._game({"seat": 1, "turn": 3, "say": "deal", "source": "model", "answer": {"chosenId": 0}})
        self.assertEqual([x for x in self.r.queue if x["kind"] == "bark"], [], "the say beside the proposal stays quiet")
        self.assertIn("the DEAL answer already spoke (deal)", [x["why"] for x in self._records("skipped", "bark")])
        self._deal_record(2, True, terms=terms, with_=1, offer_id="p1")
        self.assertEqual(self.r._deals[(1, 2)]["kind"], "truce")
        self.assertEqual([n["kind"] for n in self._notes(1)], ["deal-struck"]); self.assertEqual([n["kind"] for n in self._notes(2)], ["deal-struck"])
        self.assertEqual(self._seat_lines(), [("deal-with-you", "bill/table", 2)])

    def test_a_seats_refusal_is_told_to_the_proposer(self):
        self.r.rng.random = lambda: 0.99
        terms = {"kind": "truce", "rounds": 1}
        self._propose(3, 1, terms, "p5")                              # Selvala (voiceless) asks Urza
        self._deal_record(1, False, terms=terms, with_=3, offer_id="p5")
        self.assertEqual(self._notes(3), [{"kind": "deal-refused", "between": [1, 3], "by": 1, "deal": terms, "offer_id": "p5", "turn": 3}],
                         "game 53: Purphoros never learned Giada said no")
        self.assertEqual(self._notes(1), [], "the refuser has nothing to learn")
        self.assertEqual(self._seat_lines(), [("no-deal-with-you", "harry/table", 1)])

    def test_an_offer_to_the_player_waits_for_the_typed_answer(self):
        self.r.rng.random = lambda: 0.99
        terms = {"kind": "alliance", "until_turn": 9}
        self._propose(2, 0, terms, "p2")
        self.assertEqual(self.r._deal_counters, {"p2": {"between": [2, 0], "deal": terms, "turn": 4, "proposal": True}}, "a turn longer than a counter: the player is not at a window")
        self.assertEqual(self._seat_lines(), [("deal", "bill", 2)])
        self.r.queue.clear()
        d = self.logs / "control" / "deal"; d.mkdir(parents=True)
        (d / "1700000000123-refuse.json").write_text(json.dumps({"offer_id": "p2"}))
        self.r.scan_deal_control()
        self.assertEqual(self.r._deal_counters, {}); self.assertEqual(self.r._deals, {})
        self.assertEqual([(x["event"], x["between"], x["by"]) for x in self._ledger()][-1], ("refused", [2, 0], 0))
        self.assertEqual(self._notes(2)[-1], {"kind": "deal-refused", "between": [2, 0], "by": 0, "deal": terms, "offer_id": "p2", "turn": 3})
        self.assertEqual(self._seat_lines(), [], "a refusal is not answered aloud")
        self._propose(2, 0, {"kind": "truce", "rounds": 1}, "p3")
        self.r.queue.clear()
        (d / "1700000000456-accept.json").write_text(json.dumps({"offer_id": "p3"}))
        self.r.scan_deal_control()
        self.assertEqual(self.r._deals[(0, 2)]["kind"], "truce")
        self.assertEqual(self._ledger("struck")[-1]["by"], 0)
        self.assertEqual(self._seat_lines(), [("deal-with-you", "bill/table", 2)])
        self.assertEqual(sorted(p.name for p in d.iterdir()), [], "both files consumed")

    def test_the_executive_answering_the_offer_leaves_nothing_for_the_player_to_type(self):
        self.r.rng.random = lambda: 0.99
        terms = {"kind": "truce", "rounds": 1}
        self._propose(1, 0, terms, "p4")
        self.assertIn("p4", self.r._deal_counters)
        self._deal_record(0, True, terms=terms, with_=1, offer_id="p4")
        self.assertEqual(self.r._deals[(0, 1)]["kind"], "truce")
        self.assertNotIn("p4", self.r._deal_counters)
        self.r.lapse_deals(5)
        self.assertEqual(self._ledger("expired"), [], "nothing expires: it was answered")


class AnAllAiTable(_DealCase):
    """ALL_SEATS=1 (run_table.sh): there is no human seat — seat 0's runner gets every note like the others, and a
    deal record that names nobody is skipped, not a crash."""

    def test_seat_zero_gets_the_notes_and_nobody_is_the_player(self):
        self.r.human_seat = None
        self.r.rng.random = lambda: 0.99
        self._deal_record(1, True, terms={"kind": "truce", "rounds": 1}, with_=0, offer_id="a1")
        self.assertEqual(self.r._deals[(1, 0)]["kind"], "truce")
        self.assertEqual([n["kind"] for n in self._notes(0)], ["deal-struck"], "seat 0 is a brain here: it is told")
        self.assertEqual([n["kind"] for n in self._notes(1)], ["deal-struck"])
        self._game({"seat": 2, "turn": 3, "type": "DEAL", "deal": {"offer_id": "a2", "accept": True}})   # no `with`, no human to default to
        self.assertTrue(any("naming no other party" in x["why"] for x in self._records("skipped", "deal")))
        self.assertFalse(self.r.human_turn(), "no seat is the human's: the table is never 'quieter on your turn'")


class ADealLineWaitsOutTheGuard(_DealCase):
    def test_a_deal_line_is_held_not_dropped_by_the_seat_guard(self):
        self.r.rng.random = lambda: 0.99
        self.r._bark_spoken_at[1] = self.clock.t - 2.0                     # Urza spoke two seconds ago
        self.r._seat_last_class()[1] = self.r._guard_class("anchored")
        self.assertFalse(self.r.maybe_bark(1, "kill-that", turn=3, source="event", p=1.0, ctx={"targets": [2]}), "an ordinary anchored line: guarded")
        self.assertTrue(self.r.maybe_bark(1, sch.DEAL_PROPOSE_LINE, turn=3, source="brain", p=1.0, ctx={"targets": [2], "terminal": True}),
                        "game 55: 'Deal, Selvala?' died to the guard while the offer stood")
        item = [q for q in self.r.queue if q["kind"] == "bark"][-1]
        self.assertGreaterEqual(item["gap"], self.r.barks_cooldown - 2.0 - 0.01, "held for the rest of the guard, not dropped")
        self.assertIn("deal line held", [x["why"] for x in self._records("noted", "bark")][-1])


class JoshuaHeard(_DealCase):
    """Game 58 (Ben: "not hearing much from Joshua"): advice within the grace of the player's answer still plays;
    Joshua takes a 30 % share of the colour on the AI seats' turns; the share is spoken, not rolled again."""

    def test_advice_answered_moments_ago_still_plays_and_old_advice_does_not(self):
        r = self.r
        r.queue.clear()
        r.enqueue("advice", text="Hold the counterspell.", seq=41, ttl=25.0)
        r.answered.add(41); r.answered_at[41] = self.clock.t + 6.0                    # the player answers six seconds after the line arrives
        self.clock.t += 10                                                            # past the table's gap; the answer is 4 s old
        item = r.next_item()
        self.assertIsNotNone(item); self.assertEqual(item["kind"], "advice")
        self.assertTrue(any("spoken late" in x["why"] for x in self._records("noted", "advice")))
        r.queue.clear()
        r.enqueue("advice", text="Too late now.", seq=42, ttl=25.0)
        r.answered.add(42); r.answered_at[42] = self.clock.t - 10.0                   # answered ten seconds before the line arrived
        self.clock.t += 10                                                            # twenty seconds on: history
        self.assertIsNone(r.next_item())
        self.assertTrue(any(x["why"].startswith("already answered (20s ago") for x in self._records("dropped", "advice")))
        state = r._recency_state()
        self.assertIn("41", state["answered_at"], "the answer times travel in the checkpoint")

    def test_joshua_takes_his_share_of_the_colour_on_an_ai_turn(self):
        r = self.r; r.queue.clear()
        rec = {"kind": "color", "text": "Urza spent the turn on artifacts. Watch the Scepter.", "owner": 1, "seq": 7}
        r.rng.random = lambda: 0.5                                                 # above the 0.3 share: the seat keeps it
        r._voice_color(rec)
        self.assertEqual([q for q in r.queue if q["kind"] == "color"], [])
        self.assertTrue(any("the seat speaks" in x["why"] for x in self._records("skipped", "color")))
        r.rng.random = lambda: 0.2                                                 # inside the share: Joshua speaks, no second roll
        r._voice_color(rec)
        colour = [q for q in r.queue if q["kind"] == "color"]
        self.assertEqual(len(colour), 1); self.assertEqual(colour[0]["text"], "Urza spent the turn on artifacts.")
        self.assertTrue(any("Joshua takes the colour" in x["why"] for x in self._records("noted", "color")))
        self.assertEqual(r.color_joshua_share, 0.3); self.assertEqual(r.advice_grace, 8.0)
