"""The seat's table line. §4.4 (2026-09-14): a non-procedural window offers an optional "say" key from a short
menu of table-line ids; the runner validates it, keeps it out of the engine answer and records it beside "why"
for the voice runner. The contextual menu (2026-10-18): voices/say-menu.json is the one source; the runner reads
the window's situations from the request and the observer's event ring, offers the ids that fit, takes a `to`
seat, caps two brain lines a turn, records the target, the card and the offered list; the stance key beside it.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import rules  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402
from test_deals_seat import make_runner, cast, _base  # noqa: E402


VOICES = Path(__file__).resolve().parents[1] / "voice" / "stock" / "voices"


def _cast(seq=1, options=None, **over):
    req = {"seq": seq, "turn": 4, "phase": "MAIN1", "decisionType": "CAST_SPELL", "gameId": "g",
           "options": options if options is not None else [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "Sol Ring {1}"}],
           "state": {"stack": [], "manaPool": 0, "untappedManaSourceCount": 3, "life": 40}}
    req.update(over)
    return req


def observer(turn=5, active=1, seats=None, events=(), stack=()):
    seats = seats or [{"seat": i, "life": 40, "handSize": 4, "eliminated": False} for i in range(4)]
    return {"turn": turn, "phase": "MAIN1", "activeSeat": active, "gameOver": False, "seats": seats,
            "events": list(events), "stackDetail": list(stack)}


def damage(seq, victim, hitter, amount=5, turn=5):
    return {"seq": seq, "kind": "damage", "turn": turn, "seat": victim, "amount": amount, "combat": True, "from": [hitter]}


def menu_runner():
    r = make_runner(seat=3)                      # Urza's deck at seat 3 in the deals fixture
    r.mb.read_observer = lambda: None
    r.brain.effort = "medium"                    # the deals fixture's brain is "low", which would make every window lite
    return r


def offered(r):
    return list(r._say_offered[1])


class SayOffer(unittest.TestCase):
    def test_offered_on_moments_not_on_ceremony(self):
        self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast()))
        self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast(), seat=2))
        self.assertNotIn('"say"', rules.build_user_prompt(_cast(), seat=0), "seat 0 is the advisor playing the human's seat: no table line (Ben)")
        self.assertFalse(rules.say_offer(_cast(), 0)); self.assertTrue(rules.say_offer(_cast(), 3))
        self.assertNotIn('"say"', rules.build_user_prompt(_cast(options=[{"id": 0, "label": "Pass (do nothing)"}])), "a plain pass")
        for dt in ("MULLIGAN", "CHOOSE_NUMBER", "CHOOSE_MODE", "CONFIRM", "PAY_UNLESS", "CHOOSE_CARD"):
            self.assertNotIn('"say"', rules.build_user_prompt(_cast(decisionType=dt)), dt)
        for dt in ("REACT", "CHOOSE_ENTITY", "CHOOSE_ENTITIES"):
            self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast(decisionType=dt)), dt)
            self.assertNotIn('"say"', rules.build_user_prompt(_cast(decisionType=dt, options=[{"id": 3, "label": "only"}])), dt + " forced")
        for dt in ("DECLARE_ATTACKERS", "DECLARE_BLOCKERS"):
            self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast(decisionType=dt, options=[])), dt)

    def test_the_offer_is_one_short_line_of_real_ids(self):
        self.assertNotIn("\n", rules.SAY_OFFER)
        self.assertLess(len(rules.SAY_OFFER.split()), 80, "well under the 150-token budget")
        self.assertEqual(len(set(rules.SAY_MENU)), len(rules.SAY_MENU))
        main, table = VOICES / "harry" / "manifest.json", VOICES / "harry" / "table" / "manifest.json"
        if not (main.exists() and table.exists()):
            self.skipTest("harry's libraries are not checked out")
        have = set()
        for m in (main, table):
            have |= set((json.loads(m.read_text()).get("phrases") or {}).keys())
        self.assertEqual([i for i in rules.SAY_MENU if i not in have], [], "every menu id is a phrase harry can speak")

    def test_validate_strips_the_key(self):
        self.assertEqual(rules.validate(_cast(), {"chosenId": 1, "why": "w", "say": "taunt"}), {"chosenId": 1})


class SayRecorded(unittest.TestCase):
    def _runner(self):
        tmp = Path(tempfile.mkdtemp(prefix="say-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        r.brain.session_id = "s"; r.brain.ensure_session = lambda *a, **k: True
        r._fastpath = lambda req: None
        sent = []
        r.mb.respond = lambda req, ans: sent.append(ans) or True
        return r, sent

    def _decide(self, r, out):
        r.brain.decide = lambda *a, **k: (dict(out), {"latency_s": 0.1, "usage": None, "raw": json.dumps(out)})

    def _rows(self, r):
        return [json.loads(l) for l in r._game_log.read_text().splitlines()]

    def _log(self, r):
        return (r._game_log.parent / "seat-2.log").read_text()

    def test_a_valid_say_is_recorded_beside_why_and_never_sent(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 1, "why": "ramp", "say": "Taunt "})
        r.handle(_cast(1))
        self.assertEqual(sent, [{"chosenId": 1}], "the engine sees the contract fields only")
        row = self._rows(r)[-1]
        self.assertEqual((row["say"], row["why"], row["source"]), ("taunt", "ramp", "model"))
        self.assertNotIn("dropped", self._log(r))

    def test_an_unknown_id_is_dropped_with_a_note(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 1, "why": "ramp", "say": "trash-talk"})
        r.handle(_cast(2))
        self.assertEqual(sent, [{"chosenId": 1}])
        self.assertNotIn("say", self._rows(r)[-1])
        self.assertIn("say 'trash-talk' dropped: not offered on this window", self._log(r))

    def test_a_say_on_a_procedural_window_is_dropped(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 0, "why": "nothing to do", "say": "gg"})
        r.handle(_cast(3, options=[{"id": 0, "label": "Pass (do nothing)"}]))
        self.assertEqual(sent, [{"chosenId": 0}])
        self.assertNotIn("say", self._rows(r)[-1])
        self.assertIn("say 'gg' dropped: procedural window (CAST_SPELL)", self._log(r))

    def test_no_say_key_means_no_say_field_and_a_punt_speaks_nothing(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 1, "why": "ramp"})
        r.handle(_cast(4))
        self.assertNotIn("say", self._rows(r)[-1])
        self._decide(r, {"chosenId": 99, "why": "bad id", "say": "gg"})    # invalid answer -> safe default
        r.handle(_cast(5))
        row = self._rows(r)[-1]
        self.assertEqual(row["source"], "punt"); self.assertNotIn("say", row)


class TheFile(unittest.TestCase):
    def test_every_id_is_a_phrase_all_four_voices_carry_with_a_gloss(self):
        menu = rules.load_say_menu()
        libs = {}
        for lib in ("harry", "bill", "lily", "joshua"):
            have = {}
            for sub in ("", "table", "cards"):
                m = VOICES / lib / sub / "manifest.json" if sub else VOICES / lib / "manifest.json"
                if m.exists():
                    have.update(json.loads(m.read_text()).get("phrases") or {})
            if have:
                libs[lib] = have
        if len(libs) < 3:
            self.skipTest("the voice libraries are not checked out")
        missing = []
        for lib, have in libs.items():
            for i in menu["ids"]:
                if i not in have or not have[i].get("when"):
                    missing.append((lib, i))
        self.assertEqual(missing, [])
        for g in [menu["core"], *menu["situations"].values(), menu["deal"], menu["loop"]]:
            for e in g:
                self.assertTrue(e["gloss"] and e["gloss"] != e["id"], e)
        self.assertEqual(len(menu["core"]), 8)
        self.assertEqual((menu["max_ids"], menu["max_says_per_turn"]), (14, 2))
        self.assertTrue(set(menu["held"]) <= set(menu["ids"]))
        self.assertTrue(set(menu["needs_target"]) <= set(menu["ids"]))
        self.assertEqual(tuple(menu["stances"]), rules.STANCE_TRIGGERS, "every trigger has a list, in the triggers' order")
        stance_ids = {i for ids in menu["stances"].values() for i in ids}
        self.assertEqual([(lib, i) for lib, have in libs.items() for i in sorted(stance_ids) if i not in have], [])

    def test_the_question_ids_mirror_the_voices_set(self):
        from voice import scheduler
        self.assertTrue(set(rules.SAY_QUESTIONS) <= scheduler.QUESTION_LINES)
        self.assertTrue(set(rules.SAY_QUESTIONS) <= set(rules.SAY_MENU))

    def test_the_quiet_line_is_still_one_short_line(self):
        self.assertNotIn("\n", rules.SAY_OFFER)
        self.assertLess(len(rules.SAY_OFFER.split()), 60)
        block = rules.say_menu_block(rules.load_say_menu()["situations"]["hit"] + rules.load_say_menu()["core"], charged=True)
        self.assertIn("Lines that fit now:", block)
        self.assertIn("youre-the-threat→ — name the threat", block)
        self.assertIn('"to": <seat number>', block)


class TheWindow(unittest.TestCase):
    def test_a_quiet_window_offers_the_core_line(self):
        r = menu_runner()
        r.mb.read_observer = lambda: observer(active=3)
        text = r._say_menu(cast(1, turn=5), r.mb.read_observer())
        self.assertNotIn("Lines that fit now", text)
        self.assertEqual(offered(r), [e["id"] for e in rules.load_say_menu()["core"]])

    def test_a_hit_charges_the_window_and_the_second_hit_offers_the_grudge(self):
        r = menu_runner()
        r._say_menu(cast(1, turn=5), observer(events=[damage(1, 3, 1)]))          # the first read primes the cursor
        self.assertNotIn("that-hurt", offered(r), "history is never replayed")
        text = r._say_menu(cast(2, turn=5), observer(events=[damage(1, 3, 1), damage(2, 3, 1)]))
        self.assertIn("Lines that fit now", text)
        ids = offered(r)
        self.assertEqual(ids[0], "that-hurt")
        self.assertNotIn("grudge", ids, "the first hit this game")
        self.assertIn("taunt", ids, "core fills the list")
        self.assertLessEqual(len(ids), 14)
        self.assertTrue(all(e in ids for e in ("youre-the-threat", "attack-them")))
        r._say_menu(cast(3, turn=6), observer(turn=6, events=[damage(2, 3, 1), damage(3, 3, 1)]))
        self.assertIn("grudge", offered(r), "the same seat again")
        r._say_menu(cast(4, turn=6), observer(turn=6, events=[damage(3, 3, 1)]))
        self.assertNotIn("that-hurt", offered(r), "nothing new since the last window: quiet again")

    def test_blocking_attacking_and_the_deal_partner_gate(self):
        r = menu_runner()
        req = _base(1, "DECLARE_BLOCKERS", 5)
        r._say_menu(req, observer())
        ids = offered(r)
        self.assertTrue({"brace", "no-blocks", "take-it", "why-me"} <= set(ids))
        req = _base(2, "DECLARE_ATTACKERS", 5)
        req["state"]["defenders"] = [{"id": 1, "label": "Player One"}, {"id": 2, "label": "Giada, Font of Hope-S1"}]
        r._say_menu(req, observer())
        ids = offered(r)
        self.assertTrue({"big-swing", "poke", "attack-you", "not-sorry"} <= set(ids))
        self.assertNotIn("i-broke-it", ids, "no deal with a defender")
        r._deals_in_force = {0: {"kind": "truce", "until_turn": 9}}
        r._say_menu(req, observer())
        self.assertIn("i-broke-it", offered(r))

    def test_a_threat_on_the_stack_on_a_react_window(self):
        r = menu_runner()
        req = _base(1, "REACT", 5)
        req["options"] = [{"id": 0, "label": "Pass"}, {"id": 1, "label": "Counterspell {U}{U}"}]
        req["state"]["stack"] = ["Craterhoof Behemoth"]
        obs = observer(active=1, events=[{"seq": 1, "kind": "cast", "turn": 5, "seat": 1, "spell": "Craterhoof Behemoth", "commander": False, "cmc": 8}],
                       stack=[{"kind": "spell", "name": "Craterhoof Behemoth", "owner": 1, "targets": []}])
        text = r._say_menu(req, obs)
        ids = offered(r)
        self.assertIn("Lines that fit now", text)
        self.assertTrue({"oh-no", "kill-that", "counter", "in-response", "read-that"} <= set(ids))
        self.assertNotIn("gc-react", ids, "not a game changer of that deck")
        req2 = _base(2, "REACT", 5)
        req2["options"] = [{"id": 0, "label": "Pass"}, {"id": 1, "label": "Counterspell {U}{U}"}]
        req2["state"]["stack"] = ["Sol Ring"]
        r._say_menu(req2, observer(active=1, stack=[{"kind": "spell", "name": "Sol Ring", "owner": 1, "targets": []}]))
        self.assertNotIn("oh-no", offered(r), "a rock is no threat: the quiet line")

    def test_my_cast_offers_the_own_action_lines_that_fit_the_options(self):
        r = menu_runner()
        req = cast(1, turn=5)
        req["options"].append({"id": 2, "label": "Urza, Lord High Artificer {2}{U}{U} — commander"})
        req["options"].append({"id": 3, "label": "Myr Battlesphere {7} — artifact creature"})
        r._say_menu(req, observer(active=3))
        ids = offered(r)
        self.assertTrue({"commander-cast", "cast-big", "removal", "sweep"} <= set(ids))
        self.assertNotIn("game-changer", ids, "no game changer on offer")
        r._say_menu(cast(2, turn=5), observer(active=3))
        self.assertNotIn("commander-cast", offered(r), "a rock alone: no my_cast situation")

    def test_lite_and_fixed(self):
        r = menu_runner()
        r.brain.effort = "low"
        text = r._say_menu(cast(1, turn=5), observer(events=[damage(1, 3, 1)]))
        text = r._say_menu(cast(2, turn=5), observer(events=[damage(1, 3, 1), damage(2, 3, 1)]))
        self.assertNotIn("Lines that fit now", text, "a low-effort window gets the short line")
        self.assertIn("that-hurt", offered(r), "...but the situation's ids are still offered")
        r.say_menu_mode = "fixed"
        self.assertIsNone(r._say_menu(cast(3, turn=5), observer()))
        self.assertEqual(offered(r), [])


class Validation(unittest.TestCase):
    def _offer(self, r, req, obs=None):
        r._say_menu(req, obs or observer(active=3))

    def test_object_form_target_rules_and_the_cap(self):
        r = menu_runner()
        req = cast(1, turn=5)
        self._offer(r, req)
        self.assertEqual(r._say_key(req, {"id": "youre-the-threat", "to": 1}), {"id": "youre-the-threat", "to": 1})
        self.assertEqual(r._say_key(req, {"id": "taunt", "to": 3}), {"id": "taunt", "to": None})        # self: target dropped, line kept
        self.assertIsNone(r._say_key(req, "respect"), "the cap: two a turn")
        req6 = cast(2, turn=6)
        self._offer(r, req6)
        self.assertEqual(r._say_key(req6, {"id": "taunt", "to": 0}), {"id": "taunt", "to": 0}, "the human may be addressed (Ben, decision 1)")
        self.assertEqual(r._say_key(req6, {"id": "kill-that", "to": 9}), {"id": "kill-that", "to": None}, "not a living seat")
        self.assertTrue(any("target 9 dropped" in l for l in r.log_lines))

    def test_a_question_is_never_aimed_at_the_human(self):
        r = menu_runner()
        obs = observer(active=3, seats=[{"seat": 0, "life": 40, "handSize": 8, "eliminated": False}] + [{"seat": i, "life": 40, "handSize": 4, "eliminated": False} for i in (1, 2, 3)])
        req = cast(1, turn=5)
        req["state"]["life"] = 41                                 # the unique life leader: the `leader` situation
        self._offer(r, req, obs)
        self.assertIn("cards-in-hand", offered(r))
        self.assertEqual(r._say_key(req, {"id": "cards-in-hand", "to": 0}), {"id": "cards-in-hand", "to": None})
        self.assertTrue(any("a question the human cannot answer" in l for l in r.log_lines))

    def test_only_what_was_offered_validates(self):
        r = menu_runner()
        req = cast(1, turn=5)
        self._offer(r, req)
        self.assertIsNone(r._say_key(req, "big-swing"), "an attack line on a cast window")
        self.assertTrue(any("not offered on this window" in l for l in r.log_lines))
        self.assertIsNone(r._say_key(req, "dance"))
        r.say_menu_mode = "fixed"
        r._say_offered = (None, {})
        self.assertEqual(r._say_key(cast(2, turn=5), "big-swing"), {"id": "big-swing", "to": None}, "fixed mode: any id the file names")

    def test_deal_and_loop_ids_ride_with_their_own_lines(self):
        r = menu_runner()
        req = cast(1, turn=5)
        r._say_menu(req, observer(active=3), deal_offer=True, loop_offer=True)
        self.assertTrue({"take-the-deal", "no-deal", "counter-offer", "looping"} <= set(offered(r)))
        r._say_menu(cast(2, turn=5), observer(active=3))
        self.assertNotIn("take-the-deal", offered(r))


class TheRecord(unittest.TestCase):
    def test_the_say_fields_land_on_the_record_and_a_lost_window_speaks_nothing(self):
        r = menu_runner()
        r.mb.read_observer = lambda: observer(active=3)
        r.brain.script = [{"chosenId": 1, "why": "ramp", "say": {"id": "taunt", "to": 1}}]
        r.handle(cast(1, turn=5))
        seq, answer, source, k = r.records[-1]
        self.assertEqual((k["say"], k["say_meta"]["say_to"], k["say_meta"]["say_card"]), ("taunt", 1, "Sol Ring"))
        self.assertEqual(k["say_meta"]["say_offered"][:1], ["taunt"])
        r.brain.script = [{"chosenId": 1, "why": "ramp", "say": "respect"}]
        r.mb.respond = lambda req, ans: False                     # WINDOW LOST
        r.handle(cast(2, turn=5))
        self.assertIsNone(r.records[-1][3]["say"], "a line for a decision the engine never took is not spoken")

    def test_a_new_game_resets_the_cursor_and_the_cap(self):
        r = menu_runner()
        r._say_menu(cast(1, turn=5), observer(events=[damage(1, 3, 1)]))
        r._says_turn = (5, 2)
        r.brain.totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cost_usd": 0.0}
        r.brain.backend = None
        r.mb.game_reset = True
        r.mb.prev_game_id = r.mb.game_id = "g"
        r.mb.swept_on_reset = 0
        r.mb.read_observer = lambda: observer(active=3)
        r.handle(cast(2, turn=1))
        self.assertIsNone(r._ring_seq)
        self.assertEqual(r._says_turn, (None, 0))


class Stances(unittest.TestCase):
    """Plan step 4, seat side: the stance key is offered beside the menu, validated per trigger, recorded, and gone
    when ARENA_STANCES is off."""

    def test_the_offer_rides_with_the_menu(self):
        r = menu_runner()
        r.mb.read_observer = lambda: observer(active=3)
        r.handle(cast(1, turn=5))
        self.assertIn('OPTIONAL "stance"', r.brain.prompts[-1])
        self.assertIn("on_hit, on_attacked, on_counter, on_gc", r.brain.prompts[-1])
        r.stances_on = False
        r.handle(cast(2, turn=5))
        self.assertNotIn('"stance"', r.brain.prompts[-1])

    def test_validation_per_trigger_and_the_record(self):
        r = menu_runner()
        req = cast(1, turn=5)
        got = r._stance_key(req, {"on_hit": "grudge", "on_gc": {"id": "kill-that", "to": 1}, "on_counter": "gg",
                                  "on_dance": "taunt", "on_sweep": {"id": "got-swept", "to": 3}})
        self.assertEqual(got, {"on_hit": {"id": "grudge", "to": None}, "on_gc": {"id": "kill-that", "to": 1}, "on_sweep": {"id": "got-swept", "to": None}})
        self.assertTrue(any("on_counter='gg' dropped" in l for l in r.log_lines))
        self.assertTrue(any("'on_dance' dropped" in l for l in r.log_lines))
        self.assertTrue(any("on_sweep: target 3 dropped" in l for l in r.log_lines))
        self.assertIsNone(r._stance_key(req, "grudge"), "not a dict")
        plain = cast(2, turn=5); plain["options"] = [{"id": 0, "label": "Pass (do nothing)"}]
        self.assertIsNone(r._stance_key(plain, {"on_hit": "grudge"}), "a procedural window offers nothing")
        r.mb.read_observer = lambda: observer(active=3)
        r.brain.script = [{"chosenId": 1, "why": "ramp", "stance": {"on_hit": "grudge"}}]
        r.handle(cast(3, turn=5))
        self.assertEqual(r.records[-1][3]["stance"], {"on_hit": {"id": "grudge", "to": None}})
        r.stances_on = False
        r.brain.script = [{"chosenId": 1, "why": "ramp", "stance": {"on_hit": "grudge"}}]
        r.handle(cast(4, turn=5))
        self.assertIsNone(r.records[-1][3]["stance"], "off: the key is ignored")
