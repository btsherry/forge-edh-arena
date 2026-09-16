"""Table deals, seat side (docs/reviews/2026-09-16-table-deals-plan.md §5, §6, §11): the seat
runner reads notes files into RUNNER NOTE sentences (consumed once, three per prompt), offers
the "deal" answer key only while an offer is pending, validates and records the answer as its
own game.jsonl DEAL record, lapses an unanswered offer at the turn change, and hands any
attack/target window that could break a deal in force to the model — never to a fastpath or
a replayed cycle. Offline: fake mailbox + fake brain. Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import rules  # noqa: E402
from seatd import runner as runner_mod  # noqa: E402


class FakeMailbox:
    game_reset = False

    def __init__(self, seat_dir: Path):
        self.responses = []
        self.inbox = Path("/nonexistent")     # no req file: the runner keeps its window (tests)
        self.dir = seat_dir                   # notes/ lives under the mailbox dir

    def respond(self, req, answer):
        self.responses.append((req.get("seq"), answer))
        return True

    def read_observer(self):
        return None


class FakeBrain:
    effort = "low"
    model = "opus"

    def __init__(self):
        self.script, self.calls, self.prompts = [], 0, []

    def decide(self, prompt, timeout_s=None, effort=None, deadline=None):
        self.calls += 1
        self.prompts.append(prompt)
        self.last_prompt = prompt
        out = self.script.pop(0) if self.script else {"chosenId": 0}
        return out, {"latency_s": 0.01, "usage": None, "raw": json.dumps(out)}

    def reset(self):
        pass


def make_runner(seat=3):
    tmp = Path(tempfile.mkdtemp(prefix="deals-"))
    r = runner_mod.SeatRunner.__new__(runner_mod.SeatRunner)
    r.seat, r.deck = seat, "urza-lord-high-artificer"
    r.mb = FakeMailbox(tmp / f"seat-{seat}")
    r.brain = FakeBrain()
    r.timeout_s = 90.0
    r.speculative = r.react_hold = False
    r.autopass = ()
    r.plan = r.hold = r.turn_intent = r.combos = None
    r.react_seen, r.order_memo = set(), {}
    r.cycle, r._hist, r._last_turn = None, [], None
    r._init_loop_state()
    r._deviation = None
    r.log_lines = []
    r._say = r.log_lines.append
    r.records = []
    r._record = lambda req, answer, source, meta=None, **k: r.records.append((req.get("seq"), answer, source, k))
    (tmp / "logs").mkdir()
    r._game_log = tmp / "logs" / "game.jsonl"
    r._jsonl_path = tmp / "logs" / f"seat-{seat}.jsonl"      # a punt's transport event needs it
    return r


OPPONENTS = [{"seat": 0, "life": 35, "battlefield": [{"id": 78, "name": "Managorger Hydra"}]},
             {"seat": 1, "life": 38, "battlefield": [{"id": 161, "name": "Inti, Seneschal of the Sun"}]},
             {"seat": 2, "life": 40, "battlefield": []}]


def _base(seq, dtype, turn, phase="MAIN1"):
    return {"seq": seq, "turn": turn, "phase": phase, "decisionType": dtype, "gameId": "g1", "prompt": "t",
            "state": {"seat": 3, "stack": [], "manaPool": 0, "life": 40, "untappedManaSourceCount": 3,
                      "opponents": [dict(o) for o in OPPONENTS]}}


def cast(seq, turn=5):
    r = _base(seq, "CAST_SPELL", turn)
    r["options"] = [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "Sol Ring  {1} — mana rock"}]
    return r


def react(seq, turn=5):
    r = _base(seq, "REACT", turn)
    r["state"]["stack"] = ["Rhystic Study"]
    r["options"] = [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "Counterspell  {U}{U} — counter target spell"}]
    return r


def attack(seq, turn=5, defenders=(0, 1, 2)):
    names = {0: "Selvala", 1: "Purphoros", 2: "Giada"}
    r = _base(seq, "DECLARE_ATTACKERS", turn, "COMBAT_DECLARE_ATTACKERS")
    r["options"] = [{"id": 0, "label": "Pass (do nothing)"}, {"id": 302, "label": "Urza 1/4", "type": "ATTACKER"}]
    r["state"]["defenders"] = [{"id": d, "label": f"{names[d]} player (seat {d}), life 40", "type": "PLAYER"} for d in defenders]
    return r


def target(seq, turn=5):
    r = _base(seq, "CHOOSE_ENTITY", turn)
    r["state"].update({"min": 1, "max": 1})
    r["options"] = [{"id": 0, "label": "Choose none", "type": "NONE"},
                    {"id": 78, "label": "Managorger Hydra 4/4", "type": "CARD"},
                    {"id": 161, "label": "Inti, Seneschal of the Sun 2/2", "type": "CARD"}]
    return r


def note(r, kind, ts, **body):
    d = r._notes_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{ts}-{kind}.json").write_text(json.dumps({"kind": kind, **body}))


def offer(r, ts=1000, oid="1000-0-3", **deal):
    note(r, "deal-offer", ts, **{"from": 0, "to": 3, "deal": deal or {"kind": "truce", "rounds": 1},
                                 "offer_id": oid, "text": "peace for a turn?", "turn": 5})
    return oid


def struck(r, ts=1001, kind="truce", until_turn=6, other=0, oid="1000-0-3"):
    note(r, "deal-struck", ts, between=[other, 3], deal={"kind": kind, "rounds": 1, "until_turn": until_turn}, offer_id=oid, turn=5)


def deal_rows(r):
    if not r._game_log.exists():
        return []
    return [json.loads(l) for l in r._game_log.read_text().splitlines() if '"DEAL"' in l]


def notes_left(r):
    d = r._notes_dir()
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


class NotesReader(unittest.TestCase):
    def test_notes_are_rendered_in_order_capped_at_three_and_consumed_once(self):
        r = make_runner()
        offer(r, 1000)
        note(r, "deal-struck", 1001, between=[0, 3], deal={"kind": "alliance", "rounds": 2, "until_turn": 9}, offer_id="1000-0-3", turn=5)
        note(r, "deal-broken", 1002, between=[0, 3], by=0, how="attack", turn=8)
        note(r, "deal-lapsed", 1003, between=[3, 1], turn=9)
        r.handle(cast(1))
        p = r.brain.last_prompt
        self.assertIn('RUNNER NOTE: Player One (seat 0) offers a TRUCE for 1 of your turns: neither of you attacks the other. '
                      'They said: "peace for a turn?". Answer with "deal": {"offer_id": "1000-0-3", "accept": true} or "accept": false '
                      '(you may counter once), and a "say" (take-the-deal / no-deal / counter-offer). Decide as this deck would: '
                      'a truce with the threat is a mistake; one with the weakest seat buys tempo.', p)
        self.assertIn("RUNNER NOTE: you have an ALLIANCE with Player One (seat 0) until the end of turn 9: do not attack or target them. "
                      "Breaking it is a choice the table will remember.", p)
        self.assertIn("RUNNER NOTE: Player One (seat 0) broke your alliance (attacked you turn 8). You owe them nothing.", p)
        self.assertNotIn("has ended", p, "the fourth note waits for the next prompt")
        self.assertEqual(notes_left(r), ["1003-deal-lapsed.json"], "three consumed, the rest wait on disk")
        self.assertEqual(r._deals(), {}, "struck then broken: nothing in force")
        r.handle(cast(2))
        self.assertIn("RUNNER NOTE: your truce with seat 1 has ended.", r.brain.last_prompt)
        self.assertEqual(notes_left(r), [])
        r.handle(cast(3))
        self.assertNotIn("RUNNER NOTE", r.brain.last_prompt, "consumed once")

    def test_malformed_and_unknown_notes_are_deleted_with_a_log_line(self):
        r = make_runner()
        d = r._notes_dir(); d.mkdir(parents=True)
        (d / "900-deal-offer.json").write_text("{not json")
        (d / "901-deal-struck.json").write_text(json.dumps({"kind": "deal-struck", "between": [3, 3]}))
        (d / "902-deal-bribe.json").write_text(json.dumps({"kind": "deal-bribe", "gold": 4}))
        (d / "903-deal-offer.json").write_text(json.dumps({"kind": "deal-offer", "from": 0, "deal": {"kind": "truce", "rounds": 1}}))
        struck(r, 904)
        r.handle(cast(1))
        log = "\n".join(r.log_lines)
        self.assertIn("note 900-deal-offer.json dropped: malformed", log)
        self.assertIn("note 901-deal-struck.json dropped: malformed (no other party)", log)
        self.assertIn("note 902-deal-bribe.json dropped: unknown kind 'deal-bribe'", log)
        self.assertIn("note 903-deal-offer.json dropped: malformed (offer without offer_id)", log)
        self.assertEqual(notes_left(r), [])
        self.assertIn("RUNNER NOTE: you have a TRUCE with Player One (seat 0) until the end of turn 6: do not attack them.", r.brain.last_prompt)
        self.assertEqual(r._deals()[0]["kind"], "truce")
        self.assertEqual(r._pending(), {})

    def test_a_break_this_seat_caused_is_not_narrated_but_ends_the_deal(self):
        r = make_runner()
        struck(r, 1001, kind="no-target")
        note(r, "deal-broken", 1002, between=[0, 3], by=3, how="target", turn=5)
        r.handle(cast(1))
        self.assertNotIn("broke", r.brain.last_prompt)
        self.assertEqual(r._deals(), {})
        self.assertEqual(notes_left(r), [])
        note(r, "deal-broken", 1003, between=[0, 3], by=0, how="target", turn=6)
        r.handle(cast(2))
        self.assertIn("RUNNER NOTE: Player One (seat 0) broke your truce (targeted you turn 6). You owe them nothing.", r.brain.last_prompt)

    def test_a_seat_partner_is_named_by_commander_when_the_request_knows_it(self):
        r = make_runner()
        struck(r, 1001, other=1)
        rq = cast(1); rq["state"]["opponents"][1]["commander"] = "Purphoros, God of the Forge"
        r.handle(rq)
        self.assertIn("you have a TRUCE with Purphoros, God of the Forge until", r.brain.last_prompt)


class DealKey(unittest.TestCase):
    def test_the_key_is_offered_only_while_an_offer_is_pending_and_accept_is_recorded(self):
        r = make_runner()
        r.handle(cast(1))
        self.assertNotIn("DEAL PENDING", r.brain.last_prompt)
        oid = offer(r)
        r.brain.script = [{"chosenId": 1, "why": "tempo", "say": "take-the-deal",
                           "deal": {"offer_id": oid, "accept": True}}]
        r.handle(cast(2))
        self.assertIn(f'\nDEAL PENDING {oid}: add "deal": {{"offer_id": "{oid}", "accept": true|false}}; to counter once add '
                      '"counter": {"kind": "truce|no-target|alliance", "rounds": 1-3} or {..., "until_turn": N}; '
                      'plus "say": take-the-deal / no-deal / counter-offer.', r.brain.last_prompt)
        self.assertEqual(r.mb.responses[-1], (2, {"chosenId": 1}), "the engine sees the contract fields only")
        rows = deal_rows(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual({k: rows[0][k] for k in ("type", "seat", "turn", "gameId", "deal")},
                         {"type": "DEAL", "seat": 3, "turn": 5, "gameId": "g1", "deal": {"offer_id": oid, "accept": True, "terms": {"kind": "truce", "rounds": 1}, "with": 0}},
                         "the answer carries the offer's terms and the other party (game 50: without them the ledger struck the wrong deal)")
        self.assertIn("ts", rows[0])
        seq, answer, source, k = r.records[-1]
        self.assertEqual((source, k.get("say"), k.get("deal")), ("model", "take-the-deal", {"offer_id": oid, "accept": True, "terms": {"kind": "truce", "rounds": 1}, "with": 0}))
        self.assertEqual(r._pending(), {})
        r.handle(cast(3))
        self.assertNotIn("DEAL PENDING", r.brain.last_prompt, "answered: the key is gone")

    def test_refuse_and_a_valid_counter_are_recorded(self):
        r = make_runner()
        oid = offer(r)
        r.brain.script = [{"chosenId": 1, "deal": {"offer_id": oid, "accept": False}}]
        r.handle(cast(1))
        self.assertEqual(deal_rows(r)[-1]["deal"], {"offer_id": oid, "accept": False, "terms": {"kind": "truce", "rounds": 1}, "with": 0})
        oid2 = offer(r, 1010, "1010-0-3")
        r.brain.script = [{"chosenId": 1, "say": "counter-offer",
                           "deal": {"offer_id": oid2, "accept": False, "counter": {"kind": "no-target", "rounds": 2}}}]
        r.handle(cast(2))
        self.assertEqual(deal_rows(r)[-1]["deal"], {"offer_id": oid2, "accept": False, "counter": {"kind": "no-target", "rounds": 2}, "terms": {"kind": "truce", "rounds": 1}, "with": 0})
        self.assertEqual(r.records[-1][3].get("say"), "counter-offer")
        oid3 = offer(r, 1020, "1020-0-3")
        r.brain.script = [{"chosenId": 1, "deal": {"offer_id": oid3, "accept": False, "counter": {"kind": "alliance", "until_turn": 9}}}]
        r.handle(cast(3))
        self.assertEqual(deal_rows(r)[-1]["deal"]["counter"], {"kind": "alliance", "until_turn": 9})

    def test_a_counter_to_a_counter_is_a_refusal(self):
        r = make_runner(seat=0)     # Executive holding seat 0 receives a seat's counter
        note(r, "deal-counter", 1000, **{"from": 2, "to": 0, "deal": {"kind": "truce", "rounds": 2}, "offer_id": "990-0-2",
                                          "counter": True, "text": "", "turn": 5})
        r.brain.script = [{"chosenId": 1, "deal": {"offer_id": "990-0-2", "accept": False, "counter": {"kind": "truce", "rounds": 1}}}]
        r.handle(cast(1))
        self.assertIn("RUNNER NOTE: seat 2 counters your offer: a TRUCE for 2 of your turns: neither of you attacks the other. "
                      'Answer with "deal": {"offer_id": "990-0-2", "accept": true} or "accept": false (a counter to a counter is a refusal).',
                      r.brain.prompts[0])
        self.assertIn('DEAL PENDING 990-0-2: add "deal": {"offer_id": "990-0-2", "accept": true|false} (a counter now is a refusal).',
                      r.brain.prompts[0], "seat 0 gets the key without a say clause")
        self.assertEqual(deal_rows(r)[-1]["deal"], {"offer_id": "990-0-2", "accept": False, "terms": {"kind": "truce", "rounds": 2}, "with": 2})
        self.assertTrue(any("a counter to a counter is a refusal" in l for l in r.log_lines))

    def test_invalid_deals_are_dropped_and_the_offer_stays_pending(self):
        r = make_runner()
        oid = offer(r)
        bad = [({"offer_id": oid, "accept": False, "counter": {"kind": "truce", "rounds": 4}}, "counter rounds must be 1..3"),
               ({"offer_id": oid, "accept": False, "counter": {"kind": "truce", "until_turn": 3}}, "counter until_turn must be after turn 5"),
               ({"offer_id": oid, "accept": False, "counter": {"kind": "truce", "rounds": 1, "until_turn": 8}}, "counter needs exactly one of rounds / until_turn"),
               ({"offer_id": oid, "accept": False, "counter": {"kind": "bribe", "rounds": 1}}, "counter kind 'bribe'"),
               ({"offer_id": "nope", "accept": True}, "offer_id 'nope' is not pending"),
               ({"offer_id": oid, "accept": "yes"}, "accept must be true or false"),
               ("accept", "not an object")]
        for i, (raw, why) in enumerate(bad, start=1):
            r.brain.script = [{"chosenId": 1, "deal": raw}]
            r.handle(cast(i))
            self.assertTrue(any("dropped: " + why in l for l in r.log_lines), (raw, r.log_lines[-3:]))
            self.assertEqual(deal_rows(r), [], raw)
            self.assertIn(oid, r._pending(), "still pending: the brain may answer at its next window")
            self.assertNotIn("deal", r.records[-1][3] and {k: v for k, v in r.records[-1][3].items() if v is not None})
        self.assertEqual(r.mb.responses[-1][1], {"chosenId": 1}, "the engine answer is untouched by a bad deal key")

    def test_a_deal_on_a_punted_answer_is_not_recorded(self):
        r = make_runner()
        oid = offer(r)
        r.brain.script = [{"chosenId": 99, "deal": {"offer_id": oid, "accept": True}}]
        r.handle(cast(1))
        self.assertEqual(r.records[-1][2], "punt")
        self.assertEqual(deal_rows(r), [])
        self.assertIn(oid, r._pending())

    def test_an_offer_lapses_at_the_turn_change_with_a_record(self):
        r = make_runner()
        oid = offer(r)
        r.handle(cast(1, turn=5))
        self.assertIn("DEAL PENDING", r.brain.last_prompt)
        r.handle(cast(2, turn=6))
        self.assertNotIn("DEAL PENDING", r.brain.last_prompt)
        self.assertEqual(r._pending(), {})
        self.assertEqual(deal_rows(r)[-1]["deal"], {"offer_id": oid, "accept": None, "why": "no answer"})
        self.assertEqual(deal_rows(r)[-1]["turn"], 6)
        self.assertTrue(any(f"deal offer {oid} lapsed: no answer" in l for l in r.log_lines))

    def test_validate_strips_the_key_and_the_prompt_line_is_short(self):
        self.assertEqual(rules.validate(cast(1), {"chosenId": 1, "deal": {"offer_id": "x", "accept": True}}), {"chosenId": 1})
        line = rules.deal_offer_line("1000-0-3")
        self.assertNotIn("\n", line)
        self.assertLessEqual(len(line.split()), 40, "≤ 60 tokens")
        self.assertIn("counter-offer", rules.SAY_MENU)
        r = make_runner(); offer(r); r.handle(cast(1))
        sentence = [l for l in r.brain.last_prompt.splitlines() if l.startswith("RUNNER NOTE: Player One")][0]
        self.assertLessEqual(len(sentence.split()), 90, "≤ 120 tokens per §5")


class FastpathHandoff(unittest.TestCase):
    def test_an_attack_window_under_a_truce_is_the_models_not_a_fastpaths(self):
        r = make_runner()
        struck(r, 1001)                                    # truce with seat 0 until turn 6
        r._fastpath = lambda req: ({"attackers": []}, "memo") if req["decisionType"] == "DECLARE_ATTACKERS" else None   # a hypothetical attack fastpath
        r.brain.script = [{"attackers": [{"attacker": 302, "defender": 0}], "why": "betrayal, on purpose"},
                          {"chosenId": 0}, {"attackers": []}]
        r.handle(attack(1))
        self.assertEqual(r.brain.calls, 1)
        self.assertIn("RUNNER NOTE: your truce with Player One (seat 0) is in force — attacking them breaks it", r.brain.last_prompt)
        self.assertEqual(r.mb.responses[-1][1], {"attackers": [{"attacker": 302, "defender": 0}]}, "a model answer is never overridden")
        self.assertTrue(any("held for the model: your truce with Player One" in l for l in r.log_lines))
        r.handle(attack(2, defenders=(1, 2)))
        self.assertEqual((r.brain.calls, r.records[-1][2]), (1, "memo"), "no partner offered: the fastpath may answer")
        r.handle(cast(3, turn=6)); r.handle(attack(4, turn=6))
        self.assertEqual(r.brain.calls, 3, "the deal is in force until the voice runner says it lapsed")

    def test_a_target_window_under_no_target_or_alliance_is_held_for_the_model(self):
        r = make_runner()
        struck(r, 1001, kind="no-target")
        r._fastpath = lambda req: ({"chosenId": 78}, "memo")
        r.handle(target(1))
        self.assertEqual(r.brain.calls, 1)
        self.assertIn("RUNNER NOTE: your no-target deal with Player One (seat 0) is in force — targeting them or their permanents breaks it",
                      r.brain.last_prompt)
        rq = target(2); rq["options"] = rq["options"][:1] + rq["options"][2:]      # only seat 1's creature offered
        r.handle(rq)
        self.assertEqual((r.brain.calls, r.records[-1][2]), (1, "memo"))
        r2 = make_runner(); struck(r2, 1001, kind="alliance"); r2._fastpath = lambda req: ({"chosenId": 78}, "memo")
        r2.handle(target(1))
        self.assertIn("your alliance with Player One (seat 0) is in force — attacking or targeting them breaks it", r2.brain.last_prompt)
        r3 = make_runner(); struck(r3, 1001, kind="truce"); r3._fastpath = lambda req: ({"chosenId": 78}, "memo")
        r3.handle(target(1))
        self.assertEqual(r3.records[-1][2], "memo", "a truce is about combat: targeting stays fast")

    def test_an_armed_cycle_whose_step_would_target_the_partner_breaks_out(self):
        def armed(r):
            rq = target(1)
            sig = r._cycle_signature(rq)
            shape = r._cycle_shape(rq, {"chosenId": 78})
            r._last_turn = 5
            r.cycle = {"steps": [(sig, "CHOOSE_ENTITY", shape)], "ptr": 0, "rounds": 3, "total": 3, "until": None,
                       "until_text": "", "last_vals": None, "flat": 0, "done": 0, "loose": False}
        r = make_runner(); armed(r)
        r.handle(target(1))
        self.assertEqual((r.brain.calls, r.mb.responses[-1][1], r.records[-1][2]), (0, {"chosenId": 78}, "cycle"), "control: replays")
        r = make_runner(); struck(r, 1001, kind="alliance"); armed(r)
        r.handle(target(1))
        self.assertIsNone(r.cycle)
        self.assertTrue(any("CYCLE broken: the next step would target Player One (seat 0) across a deal in force" in l for l in r.log_lines))
        self.assertEqual(r.brain.calls, 1)
        self.assertIn("your alliance with Player One (seat 0) is in force", r.brain.last_prompt)
        self.assertEqual(r.records[-1][2], "model")

    def test_a_pending_offer_holds_every_window_for_the_model_until_answered(self):
        r = make_runner()
        r.handle(cast(0))                                  # the turn boundary clears the memo: set the turn first
        r.react_seen.add(r._react_signature(react(1)))
        r.handle(react(1))
        self.assertEqual(r.records[-1][2], "memo")
        offer(r)
        r.handle(react(2))
        self.assertEqual((r.records[-1][2], r.brain.calls), ("model", 2), "the offer reaches the brain instead of lapsing unseen")
        self.assertIn("DEAL PENDING", r.brain.last_prompt)
        r.react_seen.add(r._react_signature(react(3)))
        r.handle(react(3))
        self.assertEqual(r.records[-1][2], "model", "still pending: every window is the model's (release plan step 1a; game 50's four-minute answer)")
        oid = next(iter(r._pending()))
        r.brain.script = [{"chosenId": 0, "deal": {"offer_id": oid, "accept": False}, "say": "no-deal"}]
        r.handle(react(4))
        self.assertEqual(r._pending(), {}, "answered")
        r.react_seen.add(r._react_signature(react(5)))
        r.handle(react(5))
        self.assertEqual(r.records[-1][2], "memo", "answered: the memo is back")

    def test_a_new_game_forgets_deals(self):
        r = make_runner()
        struck(r, 1001); offer(r, 1002)
        r.handle(cast(1))
        self.assertTrue(r._deals() and r._pending())
        r.mb.game_reset = True; r.mb.prev_game_id = "g0"; r.mb.game_id = "g2"; r.mb.swept_on_reset = 0
        r._usage_readout = lambda label: None
        r._publish_yields = lambda: None
        r.handle(cast(2))
        self.assertEqual((r._deals(), r._pending()), ({}, {}))


if __name__ == "__main__":
    unittest.main()


class TermsAndNames(unittest.TestCase):
    def test_an_alliance_of_two_travels_with_the_answer(self):
        r = make_runner()
        oid = offer(r, kind="alliance", rounds=2)
        r.brain.script = [{"chosenId": 1, "deal": {"offer_id": oid, "accept": True}}]
        r.handle(cast(1))
        d = deal_rows(r)[-1]["deal"]
        self.assertEqual((d["terms"], d["with"]), ({"kind": "alliance", "rounds": 2}, 0), "game 50: the ledger must strike what was offered")

    def test_a_party_is_named_from_the_launch_roster_when_the_request_does_not(self):
        import os
        r = make_runner()
        old = {k: os.environ.get(k) for k in ("ARENA_HUMAN_DECK", "ARENA_SEAT_DECKS")}
        os.environ["ARENA_HUMAN_DECK"] = "selvala-heart-of-the-wilds"
        os.environ["ARENA_SEAT_DECKS"] = "urza-lord-high-artificer giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds"
        try:
            name = r._party_name(3, {"state": {"opponents": [{"seat": 3, "life": 40}]}})
        finally:
            for k, v in old.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
        self.assertIn("Purphoros", name); self.assertIn("(seat 3)", name)
        self.assertEqual(r._party_name(0), "Player One (seat 0)")
