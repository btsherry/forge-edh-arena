"""Table deals, advisor side (docs/reviews/2026-09-16-table-deals-plan.md §11): the
player's `@urza peace for a turn?` in the Advisor chat is parsed FIRST in _handle_asks,
relayed as a `deal-offer` note in the seat's mailbox and never answered by the brain;
the seat's `deal` answer (game.jsonl) and the voice runner's ledger (logs/deals.jsonl)
come back as one panel line each; `@urza accept` on a counter writes
logs/control/deal/<ts>-accept.json; Joshua assesses every deal the player strikes or has broken (no dice, Ben game 50).
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import advisor_runner as ar  # noqa: E402
try:
    import voice_runner as vr  # noqa: E402 — optional here: patched so no stock library is read
except Exception:  # noqa: BLE001 — the voice lane may be mid-edit; the advisor imports it lazily and copes
    vr = None

VOICES = {1: {"library": "harry", "voice": "Harry", "temperament": "fiery young warrior"},
          2: {"library": "bill", "voice": "Bill", "temperament": "elder professor"},
          3: {"library": "lily", "voice": "Lily", "temperament": "warm and wise"}}
# the human plays Giada at seat 0; the roster fills Urza (1), Purphoros (2), Selvala (3)
TABLE = {0: "giada-font-of-hope", 1: "urza-lord-high-artificer", 2: "purphoros-god-of-the-forge",
         3: "selvala-heart-of-the-wilds"}


class FakeBrain:
    def __init__(self, *a, **kw):
        self.deck, self.model, self.effort = "giada-font-of-hope", "opus", "low"
        self.session_id = "sess-1"
        self.totals = {"calls": 0}
        self.reply = "Fine for you: Urza has no fliers and you needed the turn."
        self.prompts: list[str] = []

    def reset(self):
        pass

    def ensure_session(self, *a, **kw):
        return True

    def decide(self, prompt, timeout=None, **kw):
        self.prompts.append(prompt)
        self.last_prompt = prompt
        return {}, {"raw": self.reply, "latency_s": 0.1}


class DealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._env = dict(os.environ)
        os.environ.pop("ARENA_BARKS", None)
        os.environ.pop("ARENA_SEAT_DECKS", None)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections, getattr(vr, "load_seat_libraries", None))
        ar.SeatBrain = FakeBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        if vr is not None:
            vr.load_seat_libraries = lambda *a, **kw: dict(VOICES)
        self.base = Path(self.tmp.name) / "mailbox"
        self.r = ar.AdvisorRunner("giada-font-of-hope", self.base, "opus", "low", 30.0, log_dir=self.base / "logs")
        self.r.inbox.mkdir(parents=True)
        self._n = 0
        self.snapshot(7, 1)

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig[:2]
        if vr is not None:
            vr.load_seat_libraries = self._orig[2]
        os.environ.clear(); os.environ.update(self._env)
        self.tmp.cleanup()

    # ---- helpers
    def snapshot(self, turn, active, dead=()):
        seats = [{"seat": s, "name": TABLE[s].split("-")[0].capitalize(), "life": 30 - 3 * s, "handSize": 5,
                  "battlefield": [{"name": "Sol Ring"}] * s, "eliminated": s in dead} for s in range(4)]
        (self.base / "observer-state.json").write_text(json.dumps({"turn": turn, "activeSeat": active, "seats": seats}))
        self.r._clock._sig = None
        self.r._clock.observe()

    def ask(self, text):
        self._n += 1
        self.r._asks.mkdir(parents=True, exist_ok=True)
        (self.r._asks / f"ask-{1000 + self._n}-{self._n}.json").write_text(json.dumps({"ask": text}))
        return self.r._handle_asks()

    def panel(self):
        return self.r._stream.read_text() if self.r._stream.exists() else ""

    def records(self, kind):
        if not self.r._jsonl.exists():
            return []
        return [json.loads(l) for l in self.r._jsonl.read_text().splitlines() if json.loads(l).get("kind") == kind]

    def notes(self, seat):
        d = self.base / f"seat-{seat}" / "notes"
        return sorted(d.iterdir()) if d.exists() else []

    def game_line(self, **rec):
        p = self.r._log_dir / "game.jsonl"
        with p.open("a") as f:
            f.write(json.dumps({"ts": 1.0, "gameId": "g1", **rec}) + "\n")

    def ledger_line(self, **rec):
        with self.r._ledger.open("a") as f:
            f.write(json.dumps({"ts": 1.0, "seq": 1, **rec}) + "\n")

    def offer(self, text="@urza peace for a turn?"):
        self.ask(text)
        return list(self.r._offers)[-1]

    def lbl(self, turn):
        """The clock's label for a turn — rounds follow the table (test_hardening pins that), not a formula."""
        return self.r._clock.label(turn)

    # ---- the grammar
    def test_parse_table(self):
        al, names, handles = ar.deal_table(TABLE)
        self.assertEqual(names, {0: "Giada", 1: "Urza", 2: "Purphoros", 3: "Selvala"})
        self.assertEqual(handles, {0: "giada", 1: "urza", 2: "purphoros", 3: "selvala"})
        table = {
            "@urza peace for a turn?": {"to": 1, "action": "offer", "deal": {"kind": "truce", "rounds": 1}, "words": "peace for a turn?"},
            "deal purphoros alliance 2 rounds": {"to": 2, "action": "offer", "deal": {"kind": "alliance", "rounds": 2}, "words": "alliance 2 rounds"},
            "@giada until turn 12 no target": {"to": 0, "action": "offer", "deal": {"kind": "no-target", "until_turn": 12}, "words": "until turn 12 no target"},
            "@urza accept": {"to": 1, "action": "accept", "words": "accept"},
            "@urza no": {"to": 1, "action": "refuse", "words": "no"},
            "@Urza: yes!": {"to": 1, "action": "accept", "words": "yes!"},
            "@selvala": {"to": 3, "action": "offer", "deal": {"kind": "truce", "rounds": 1}, "words": ""},
            "deal with urza: don't attack me for two turns": {"to": 1, "action": "offer", "deal": {"kind": "truce", "rounds": 2}, "words": "don't attack me for two turns"},
            "@1 ally 5 turns": {"to": 1, "action": "offer", "deal": {"kind": "alliance", "rounds": 3}, "words": "ally 5 turns"},
            "@seat2 truce until the end of turn 10": {"to": 2, "action": "offer", "deal": {"kind": "truce", "until_turn": 10}, "words": "truce until the end of turn 10"},
            "@purphoros both, 3 rounds": {"to": 2, "action": "offer", "deal": {"kind": "alliance", "rounds": 3}, "words": "both, 3 rounds"},
            "@urza no target 3 rounds please": {"to": 1, "action": "offer", "deal": {"kind": "no-target", "rounds": 3}, "words": "no target 3 rounds please"},
            "@joshua is the truce good?": {"to": "advisor", "words": "is the truce good?"},
        }
        for text, want in table.items():
            self.assertEqual(ar.parse_deal(text, al), want, text)
        for text in ("@bogus hi", "deal me in", "what should I do about Urza?", "urza peace?", "deal"):
            self.assertIsNone(ar.parse_deal(text, al), f"{text!r} names no seat: an ordinary ask")
        self.assertEqual(ar.deal_terms_text({"kind": "truce", "rounds": 1}), "truce, 1 turn")
        self.assertEqual(ar.deal_terms_text({"kind": "alliance", "rounds": 2}), "alliance, 2 turns")
        self.assertEqual(ar.deal_terms_text({"kind": "no-target", "until_turn": 12}), "no-target until turn 12")
        self.assertEqual(ar.deal_terms_text({"kind": "truce", "rounds": 1, "until_turn": 9}, "Urza"), "truce until Urza's turn 9 ends")

    def test_unknown_deck_is_named_by_its_slug(self):
        al, names, handles = ar.deal_table({0: "giada-font-of-hope", 1: "brand-new-deck"}, commanders={})
        self.assertEqual((names[1], handles[1], al["brand"], al["brand-new-deck"], al["seat1"]), ("Brand", "brand", 1, 1, 1))

    # ---- the relay
    def test_offer_writes_the_note_and_the_panel_line_and_never_calls_the_brain(self):
        self.ask("@urza peace for a turn?")
        notes = self.notes(1)
        self.assertEqual(len(notes), 1, "one deal-offer note in mailbox/seat-1/notes/")
        self.assertTrue(notes[0].name.endswith("-deal-offer.json"), notes[0].name)
        ts = notes[0].name.split("-")[0]
        self.assertEqual(json.loads(notes[0].read_text()),
                         {"kind": "deal-offer", "from": 0, "to": 1, "deal": {"kind": "truce", "rounds": 1},
                          "offer_id": f"{ts}-0-1", "text": "peace for a turn?", "turn": 7})
        self.assertFalse(list((self.base / "seat-1" / "notes").glob("*.tmp")), "atomic: no tmp left behind")
        self.assertIn('\n[r2-t7 · you → Urza] truce, 1 turn: "peace for a turn?"\n', self.panel())
        self.assertEqual(self.r.brain.prompts, [], "a deal message is relayed, never answered")
        self.assertEqual(self.records("ask"), [])
        off = self.r._offers[f"{ts}-0-1"]
        self.assertEqual((off["seat"], off["who"], off["turn"], off["status"]), (1, "Urza", 7, "open"))
        self.assertEqual(self.records("deal")[0]["event"], "offer")

    def test_until_turn_and_deal_word_forms_write_their_terms(self):
        self.ask("deal purphoros alliance 2 rounds")
        self.ask("@selvala until turn 12 no target")
        self.assertEqual(json.loads(self.notes(2)[0].read_text())["deal"], {"kind": "alliance", "rounds": 2})
        self.assertEqual(json.loads(self.notes(3)[0].read_text())["deal"], {"kind": "no-target", "until_turn": 12})
        self.assertIn("[r2-t7 · you → Purphoros] alliance, 2 turns:", self.panel())
        self.assertIn("[r2-t7 · you → Selvala] no-target until turn 12:", self.panel())

    def test_dead_seat_duplicate_and_self_get_a_panel_line_and_no_note(self):
        self.snapshot(7, 1, dead=(3,))
        self.ask("@selvala truce?")
        self.assertIn("[r2-t7 · table] Selvala is out of the game — no deal", self.panel())
        self.assertEqual(self.notes(3), [])
        self.ask("@giada peace?")
        self.assertIn("[r2-t7 · table] you can't deal with yourself", self.panel())
        self.assertEqual(self.notes(0), [])
        self.ask("@urza peace for a turn?")
        self.ask("@urza two turns then?")
        self.assertEqual(len(self.notes(1)), 1, "the second offer this turn is refused")
        self.assertIn("[r2-t7 · table] you already offered Urza a deal this turn — wait for the answer", self.panel())
        self.ask("@purphoros truce until turn 5")
        self.assertIn("[r2-t7 · table] turn 5 is not ahead of us", self.panel())
        self.assertEqual(self.notes(2), [])
        self.assertEqual(self.r.brain.prompts, [])
        self.assertEqual([r["why"] for r in self.records("deal_rejected")], ["dead", "self", "duplicate", "until_turn_past"])
        # next turn: a fresh offer to Urza goes through
        self.snapshot(8, 2)
        self.ask("@urza peace for a turn?")
        self.assertEqual(len(self.notes(1)), 2)

    def test_executive_on_does_not_stop_the_relay(self):
        self.r._exec = object()      # Executive holds seat 0: the typed offer is still the player's
        self.ask("@urza peace for a turn?")
        self.assertEqual(len(self.notes(1)), 1)
        self.assertIn("[r2-t7 · you → Urza] truce, 1 turn", self.panel())

    def test_unparsable_falls_through_to_an_ask(self):
        self.ask("@bogus hi")
        self.assertEqual(len(self.r.brain.prompts), 1)
        self.assertIn("THE HUMAN AT YOUR SEAT ASKS: @bogus hi", self.r.brain.prompts[0])
        self.assertNotIn("DEALS AT THE TABLE", self.r.brain.prompts[0])
        self.assertIn("[r2-t7 · you] @bogus hi", self.panel())
        self.assertIn("[r2-t7 · advisor] Fine for you", self.panel())
        self.assertEqual(self.r._offers, {})

    # ---- the answers
    def test_deal_records_become_panel_lines(self):
        oid = self.offer()
        self.game_line(seat=1, turn=7, type="DEAL", deal={"offer_id": oid, "accept": True, "with": 0,
                                                          "terms": {"kind": "truce", "rounds": 1, "until_turn": 9}})
        self.r._deal_tick()
        self.assertIn("\n[r2-t7 · Urza] accepts: truce until Urza's turn 9 ends\n", self.panel())
        self.assertEqual((self.r._offers[oid]["status"], self.r._offers[oid]["until_turn"]), ("accepted", 9))
        self.r._deal_tick()
        self.assertEqual(self.panel().count("accepts:"), 1, "read once")
        # refuse
        self.snapshot(8, 2)
        oid2 = self.offer("@purphoros truce?")
        self.game_line(seat=2, turn=8, type="DEAL", deal={"offer_id": oid2, "accept": False, "with": 0})
        self.r._deal_tick()
        self.assertIn(f"\n[{self.lbl(8)} · Purphoros] refuses\n", self.panel())
        self.assertEqual(self.r._offers[oid2]["status"], "refused")
        # counter
        self.snapshot(9, 3)
        oid3 = self.offer("@selvala truce?")
        self.game_line(seat=3, turn=9, type="DEAL", deal={"offer_id": oid3, "accept": False, "with": 0,
                                                          "counter": {"kind": "alliance", "rounds": 2}})
        self.r._deal_tick()
        self.assertIn(f'\n[{self.lbl(9)} · Selvala] counters: alliance, 2 turns — type "@selvala accept" or "@selvala no"\n', self.panel())
        self.assertEqual((self.r._offers[oid3]["status"], self.r._offers[oid3]["counter"]), ("countered", {"kind": "alliance", "rounds": 2}))
        # a seat-to-seat deal record is not the player's business
        self.game_line(seat=1, turn=9, type="DEAL", deal={"offer_id": "x-3-1", "accept": True, "with": 3})
        self.r._deal_tick()
        self.assertNotIn("x-3-1", self.panel()); self.assertEqual(self.panel().count("accepts:"), 1)
        self.assertEqual([l for l in self.panel().splitlines() if l.startswith("[") and len(l) > ar.DEAL_PANEL_MAX], [])

    def test_ledger_struck_lapsed_broken_and_expired(self):
        self.r.brain.reply = "Noted."                        # Joshua assesses every strike and break now (Ben, game 50)
        oid = self.offer()
        self.game_line(seat=1, turn=7, type="DEAL", deal={"offer_id": oid, "accept": True, "with": 0})
        self.r._deal_tick()
        self.assertIn("[r2-t7 · Urza] accepts: truce, 1 turn\n", self.panel(), "no until_turn yet: the terms as offered")
        self.ledger_line(turn=7, event="struck", between=[0, 1], by=1, offer_id=oid, deal={"kind": "truce", "rounds": 1, "until_turn": 9})
        self.r._deal_tick()
        self.assertIn("\n[r2-t7 · table] your truce with Urza is on until turn 9 ends\n", self.panel())
        self.assertEqual((self.r._offers[oid]["status"], self.r._offers[oid]["until_turn"]), ("struck", 9))
        self.ledger_line(turn=9, event="lapsed", between=[1, 0], offer_id=oid, deal={"kind": "truce", "until_turn": 9})
        self.r._deal_tick()
        self.assertIn(f"\n[{self.lbl(9)} · table] your truce with Urza has ended\n", self.panel())
        self.assertEqual(self.r._offers[oid]["status"], "lapsed")
        # broken, both ways; a seat-to-seat break is not shown
        self.ledger_line(turn=8, event="broken", between=[0, 2], by=2, how="attack", offer_id="a-0-2", deal={"kind": "truce"})
        self.ledger_line(turn=8, event="broken", between=[0, 3], by=0, how="target", offer_id="b-0-3", deal={"kind": "alliance"})
        self.ledger_line(turn=8, event="broken", between=[1, 2], by=1, how="attack", offer_id="c-1-2", deal={"kind": "truce"})
        self.r._deal_tick()
        self.assertIn(f"\n[{self.lbl(8)} · table] Purphoros broke your truce (attacked you)\n", self.panel())
        self.assertIn(f"\n[{self.lbl(8)} · table] you broke your alliance with Selvala\n", self.panel())
        self.assertNotIn("c-1-2", self.panel()); self.assertEqual(self.panel().count("broke"), 2)
        # an offer the seat never answered
        self.snapshot(10, 0)
        oid2 = self.offer("@purphoros peace?")
        self.ledger_line(turn=10, event="expired", between=[0, 2], offer_id=oid2)
        self.ledger_line(turn=10, event="refused", between=[0, 2], offer_id=oid2)     # a refusal only the ledger saw
        self.r._deal_tick()
        self.assertIn(f"\n[{self.lbl(10)} · table] Purphoros did not answer\n", self.panel())
        self.assertIn(f"\n[{self.lbl(10)} · Purphoros] refuses\n", self.panel())
        self.assertEqual(self.panel().count("refuses"), 1)
        self.assertTrue(all(q.startswith("TABLE DEAL") for q in self.r.brain.prompts), "only assessments, never an answer to the offer")
        for line in self.panel().splitlines():
            if line.startswith("["):
                self.assertLessEqual(len(line), ar.DEAL_PANEL_MAX, line)

    def test_counter_accept_and_refuse_write_control_files_and_lapse_at_turn_end(self):
        self.ask("@urza accept")
        self.assertIn("[r2-t7 · table] no counter or offer from Urza is pending", self.panel())
        self.assertFalse(self.r._deal_control.exists())
        oid = self.offer()
        self.game_line(seat=1, turn=7, type="DEAL", deal={"offer_id": oid, "accept": False, "with": 0,
                                                          "counter": {"kind": "alliance", "rounds": 2}})
        self.r._deal_tick()
        self.ask("@urza accept")
        files = sorted(self.r._deal_control.iterdir())
        self.assertEqual(len(files), 1); self.assertTrue(files[0].name.endswith("-accept.json"), files[0].name)
        self.assertEqual(json.loads(files[0].read_text()), {"offer_id": oid, "counter": {"kind": "alliance", "rounds": 2}})
        self.assertIn("\n[r2-t7 · you → Urza] accept the counter: alliance, 2 turns\n", self.panel())
        self.assertEqual(self.r._offers[oid]["status"], "counter-accepted")
        self.assertEqual(self.r.brain.prompts, [])
        # refuse
        self.snapshot(8, 2)
        oid2 = self.offer("@purphoros truce?")
        self.game_line(seat=2, turn=8, type="DEAL", deal={"offer_id": oid2, "accept": False, "with": 0,
                                                          "counter": {"kind": "truce", "until_turn": 11}})
        self.r._deal_tick()
        self.ask("@purphoros no")
        files = sorted(self.r._deal_control.iterdir())
        self.assertEqual(len(files), 2); self.assertTrue(files[-1].name.endswith("-refuse.json"), files[-1].name)
        self.assertEqual(json.loads(files[-1].read_text()), {"offer_id": oid2, "counter": {"kind": "truce", "until_turn": 11}})
        self.assertIn(f"\n[{self.lbl(8)} · you → Purphoros] refuse the counter\n", self.panel())
        # a counter left unanswered lapses when the turn moves on
        self.snapshot(9, 3)
        oid3 = self.offer("@selvala truce?")
        self.game_line(seat=3, turn=9, type="DEAL", deal={"offer_id": oid3, "accept": False, "with": 0, "counter": {"kind": "truce", "rounds": 3}})
        self.r._deal_tick()
        self.assertNotIn("lapsed", self.panel())
        self.snapshot(10, 0)
        self.r._deal_tick()
        self.assertIn(f"\n[{self.lbl(10)} · table] Selvala's counter lapsed\n", self.panel())
        self.assertEqual(self.r._offers[oid3]["status"], "counter-lapsed")
        self.ask("@selvala accept")
        self.assertIn(f"[{self.lbl(10)} · table] no counter or offer from Selvala is pending", self.panel())

    def test_executive_answer_for_the_player_prints_as_you(self):
        self.game_line(seat=0, turn=7, type="DEAL", deal={"offer_id": "1-1-0", "accept": True, "with": 1, "terms": {"kind": "truce", "rounds": 1}})
        self.game_line(seat=0, turn=7, type="DEAL", deal={"offer_id": "2-2-0", "accept": False, "with": 2, "terms": {"kind": "alliance", "rounds": 2}})
        self.game_line(seat=0, turn=7, type="DEAL", deal={"offer_id": "3-3-0", "accept": False, "with": 3, "counter": {"kind": "truce", "rounds": 1}})
        self.r._deal_tick()
        self.assertIn("\n[r2-t7 · you (Executive)] accept Urza's truce\n", self.panel())
        self.assertIn("\n[r2-t7 · you (Executive)] refuse Purphoros's alliance\n", self.panel())
        self.assertIn("\n[r2-t7 · you (Executive)] counter Selvala: truce, 1 turn\n", self.panel())
        self.assertEqual([r["event"] for r in self.records("deal")], ["executive-answer"] * 3)

    # ---- Joshua's 30 %
    def test_joshua_assesses_every_struck_or_broken_deal_never_the_offer(self):
        self.assertEqual(ar.DEAL_COLOR_P, 1.0, "Ben (game 50): a deal is state you act on — no dice on the advisor's read")
        oid = self.offer()
        self.assertEqual(self.r.brain.prompts, [], "the offer itself is never answered")
        self.r.deal_rng.random = lambda: 0.99          # the worst roll changes nothing
        self.r.brain.reply = "A fair truce: Urza's board is the smaller threat this turn."
        self.ledger_line(turn=7, event="struck", between=[0, 1], by=1, offer_id=oid, deal={"kind": "truce", "rounds": 1, "until_turn": 9})
        self.r._deal_tick()
        self.assertEqual(len(self.r.brain.prompts), 1, "the strike is assessed, every time")
        self.assertIn("was STRUCK", self.r.brain.prompts[0])
        self.assertEqual(len(self.records("color")), 1)
        self.r.brain.reply = "Cheap peace: Urza has nothing that flies, so watch his mana instead. [quip:calculating] [bark:1:taunt]"
        self.ledger_line(turn=8, event="broken", between=[0, 1], by=1, how="attack", offer_id=oid, deal={"kind": "truce"})
        self.r._deal_tick()
        self.assertTrue(any("was STRUCK" in q for q in self.r.brain.prompts))
        p = next(q for q in self.r.brain.prompts if "BROKEN" in q)
        self.assertIn("TABLE DEAL: your truce with Urza was BROKEN by Urza (attacked)", p)
        self.assertIn("One sentence: was this a good deal for the human, and what to watch", p)
        self.assertIn("BOARD: you: life 30", p); self.assertIn("Urza: life 27", p)
        self.assertIn("Deals at the table: truce, 1 turn with Urza (offered turn 7): broken", p)
        c = self.records("color")
        self.assertGreaterEqual(len(c), 2, "the strike and the break are both assessed")
        self.assertEqual(c[-1]["text"], "Cheap peace: Urza has nothing that flies, so watch his mana instead.")
        self.assertEqual((c[-1]["turn"], c[-1]["owner"]), (8, None))
        self.assertIn("BROKEN", c[-1]["deal"])
        self.assertEqual(self.records("quip")[0]["id"], "calculating")
        self.assertEqual(self.records("bark"), [], "a bark never rides an assessment")
        self.assertIn(f"\n[{self.lbl(8)} · color] Cheap peace:", self.panel())
        self.assertNotIn("[bark", self.panel()); self.assertNotIn("[quip", self.panel())
        # the panel order: the table's fact first, then Joshua's take
        text = self.panel()
        self.assertLess(text.index("Urza broke your truce (attacked you)"), text.index(f"[{self.lbl(8)} · color]"))

    def test_asking_about_a_deal_always_gets_the_facts(self):
        oid = self.offer()
        self.game_line(seat=1, turn=7, type="DEAL", deal={"offer_id": oid, "accept": True, "with": 0, "terms": {"kind": "truce", "rounds": 1, "until_turn": 9}})
        self.r._deal_tick()
        self.r.deal_rng.random = lambda: 0.99
        self.ask("@joshua was that truce smart?")
        self.assertEqual(len(self.r.brain.prompts), 1)
        self.assertIn("DEALS AT THE TABLE (the runner's ledger, ground truth): truce, 1 turn with Urza (offered turn 7): accepted, until turn 9 ends.", self.r.brain.prompts[0])
        self.assertIn("THE HUMAN AT YOUR SEAT ASKS: was that truce smart?", self.r.brain.prompts[0])
        self.ask("should I trust the deal with Urza?")
        self.assertIn("DEALS AT THE TABLE", self.r.brain.prompts[1])
        self.ask("what does Sol Ring do?")
        self.assertNotIn("DEALS AT THE TABLE", self.r.brain.prompts[2])
        self.assertEqual(len(self.records("ask")), 3)

    # ---- the brief and the tail
    def test_brief_relays_and_never_answers(self):
        brief = (Path(__file__).resolve().parents[1] / "seatd" / "advisor-brief.md").read_text()
        self.assertIn("## Table deals", brief)
        self.assertIn("you never answer it", brief)
        self.assertIn("ONE sentence", brief)

    def test_tail_reads_complete_lines_and_restarts_on_a_shrunken_file(self):
        p = self.r._log_dir / "game.jsonl"
        p.write_text('{"a":1}\n{"b":2')
        self.assertEqual(self.r._tail_jsonl(p, "_game_pos"), [{"a": 1}])
        with p.open("a") as f:
            f.write('}\n')
        self.assertEqual(self.r._tail_jsonl(p, "_game_pos"), [{"b": 2}])
        p.write_text('{"c":3}\n')                        # arena-stop archived and a new game began
        self.assertEqual(self.r._tail_jsonl(p, "_game_pos"), [{"c": 3}])
        # a runner started mid-game never re-prints finished deals
        r2 = ar.AdvisorRunner("giada-font-of-hope", self.base, "opus", "low", 30.0, log_dir=self.base / "logs")
        self.assertEqual(r2._game_pos, p.stat().st_size)


if __name__ == "__main__":
    unittest.main()


class SeatOffers(unittest.TestCase):
    """Ben, 2026-09-16: a seat's own offer, from its DEAL record with "propose". Seat to seat: one table line.
    To the player: the panel line with the typed answer, remembered like a counter, Joshua's assessment at once."""
    setUp, tearDown = DealTests.setUp, DealTests.tearDown
    snapshot, ask, panel, records, game_line, ledger_line, lbl = (DealTests.snapshot, DealTests.ask, DealTests.panel, DealTests.records,
                                                                  DealTests.game_line, DealTests.ledger_line, DealTests.lbl)

    def _propose(self, seat, to, terms, oid, turn=7, text=None):
        deal = {"offer_id": oid, "propose": True, "with": to, "terms": terms}
        if text:
            deal["text"] = text
        self.game_line(seat=seat, turn=turn, type="DEAL", deal=deal)
        self.r._deal_tick()

    def test_a_seat_offering_another_seat_is_one_table_line(self):
        self._propose(1, 2, {"kind": "truce", "rounds": 2}, "p-1-2", text="we both lose to Giada")
        self.assertIn('\n[r2-t7 · table] Urza offers Purphoros truce, 2 turns — "we both lose to Giada"\n', self.panel())
        self.assertEqual(self.r._offers, {})
        self.r._deal_tick()
        self.assertEqual(self.panel().count("Urza offers"), 1, "read once")
        self.assertEqual(self.records("deal")[-1]["event"], "seat-offer")

    def test_a_seat_offering_the_player_is_answered_in_the_chat_and_assessed_at_once(self):
        self.r.brain.reply = "Take it: Purphoros cannot race you and Urza is the one to fear."
        self._propose(2, 0, {"kind": "alliance", "until_turn": 10}, "p-2-0", text="Urza is the threat")
        self.assertIn('\n[r2-t7 · Purphoros] offers you alliance until turn 10 — "Urza is the threat" (@purphoros accept/no)\n', self.panel())
        off = self.r._offers["p-2-0"]
        self.assertEqual((off["status"], off["from"], off["counter_turn"], off["deal"]), ("proposed", 2, 8, {"kind": "alliance", "until_turn": 10}))
        self.assertIn("TABLE DEAL: Purphoros OFFERS you alliance until turn 10 (unanswered", self.r.brain.prompts[-1], "Joshua assesses the offer: state, no dice")
        self.assertIn("[r2-t7 · color] Take it:", self.panel())
        self.ask("@purphoros accept")
        files = sorted(self.r._deal_control.iterdir())
        self.assertEqual([f.name.endswith("-accept.json") for f in files], [True])
        self.assertEqual(json.loads(files[0].read_text()), {"offer_id": "p-2-0", "counter": {"kind": "alliance", "until_turn": 10}})
        self.assertIn("\n[r2-t7 · you → Purphoros] accept the offer: alliance until turn 10\n", self.panel())
        self.assertEqual(self.r._offers["p-2-0"]["status"], "offer-accepted")
        self.assertIn("Purphoros's offer of alliance until turn 10 (turn 7): offer-accepted", self.r._deal_facts())
        # the player's refusal of a second offer is echoed as typed, and the ledger's `refused` (by 0) is not repeated
        self._propose(1, 0, {"kind": "truce", "rounds": 1}, "p-1-0")
        self.ask("@urza no")
        self.assertIn("\n[r2-t7 · you → Urza] refuse the offer\n", self.panel())
        self.assertEqual([f.name.endswith("-refuse.json") for f in sorted(self.r._deal_control.iterdir())][-1], True)
        self.ledger_line(turn=7, event="refused", between=[1, 0], by=0, offer_id="p-1-0", deal={"kind": "truce", "rounds": 1})
        self.r._deal_tick()
        self.assertNotIn("Urza] refuses", self.panel())

    def test_an_unanswered_offer_lapses_a_turn_later_and_the_executive_answers_its_own(self):
        self.r.brain.reply = "Noted."
        self._propose(2, 0, {"kind": "truce", "rounds": 1}, "p-2-0")
        self.snapshot(8, 2); self.r._deal_tick()
        self.assertEqual(self.r._offers["p-2-0"]["status"], "proposed", "turn 8: still open")
        self.snapshot(9, 3); self.r._deal_tick()
        self.assertEqual(self.r._offers["p-2-0"]["status"], "offer-lapsed")
        self.assertIn(f"\n[{self.lbl(9)} · table] Purphoros's offer lapsed\n", self.panel())
        self.ledger_line(turn=9, event="expired", between=[2, 0], by=2, offer_id="p-2-0", deal={"kind": "truce", "rounds": 1})
        self.r._deal_tick()
        self.assertNotIn("did not answer", self.panel(), "the lapse was the tick's line")
        self.ask("@purphoros accept")
        self.assertIn("no counter or offer from Purphoros is pending", self.panel())
        self.r._exec_file.parent.mkdir(parents=True, exist_ok=True)
        self.r._exec_file.write_text(json.dumps({"on": True}))
        self._propose(1, 0, {"kind": "truce", "rounds": 1}, "p-1-0", turn=9)
        self.assertIn(f"\n[{self.lbl(9)} · Urza] offers you truce, 1 turn — the Executive answers for you\n", self.panel())
        self.assertNotIn("p-1-0", self.r._offers)
