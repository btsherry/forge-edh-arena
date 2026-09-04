"""Round-two cleanup (2026-09-04), runner side: BL-08 cycle rebinding on
(label, type, cost); BL-20 punts are never replayable cycle steps; BL-28 a
vanished request file punts at once instead of granting a fresh window;
BL-09 transport events carry the game id.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import runner as runner_mod  # noqa: E402
from tests.test_cycle_replay import make_runner, req, confirm_req, SCEPTER  # noqa: E402


def opt(i, label, typ="Ability", cost=None):
    return {"id": i, "label": label, "type": typ, "cost": cost}


def mk():
    """The shared fake runner plus the log paths a punt's bookkeeping needs."""
    r = make_runner()
    tmp = Path(tempfile.mkdtemp(prefix="r2-"))
    r._jsonl_path = tmp / "seat-3.jsonl"
    r._game_log = tmp / "game.jsonl"
    return r


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


class PuntsNeverReplay(unittest.TestCase):
    """BL-20: a loop containing one punted decision never arms."""

    def test_internal_error_clears_the_tape(self):
        r = mk()
        r.brain.script = [{"chosenId": 1}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        self.assertEqual(len(r._hist), 1)
        r.brain.decide = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        r.handle(confirm_req(2))
        self.assertEqual(r._hist, [], "an internal error leaves no tape to arm across")
        self.assertEqual(r.mb.responses[-1][1], {"chosenId": 1})  # free own trigger: yes

    def test_punt_inside_the_candidate_cycle_refuses_to_arm(self):
        r = mk()
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
        r = mk()
        r.brain.script = [{"chosenId": 1}, {"chosenId": 1}, {"chosenId": 0},
                          {"chosenId": 1, "repeat_cycle": 3}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        r.handle(confirm_req(2))
        r.handle(req(3, "REACT", ["Counterspell  {U}{U} — counter"], stack=["Dramatic Reversal"]))
        r.handle(req(4, "CAST_SPELL", [SCEPTER], pool=2))
        self.assertIsNotNone(r.cycle)


class VanishedRequestPunts(unittest.TestCase):
    """BL-28: a real inbox whose request file is gone -> punt, zero model calls."""

    def test_missing_request_file_on_a_real_inbox_punts_without_a_call(self):
        r = mk()
        tmp = Path(tempfile.mkdtemp(prefix="vanish-"))
        r.mb.inbox = tmp                      # exists, holds no req-1.json
        r.brain.script = [{"chosenId": 1}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        self.assertEqual(r.brain.calls, 0, "no model call for a vanished request")
        self.assertEqual(r.mb.responses[-1][1], {"chosenId": 0})
        self.assertTrue(any("vanished" in ln for ln in r.log_lines), r.log_lines)

    def test_fake_inbox_without_a_directory_keeps_a_full_window(self):
        r = mk()                              # inbox = /nonexistent (not a dir)
        r.brain.script = [{"chosenId": 1}]
        r.handle(req(1, "CAST_SPELL", [SCEPTER]))
        self.assertEqual(r.brain.calls, 1)


class TransportEventsCarryGameId(unittest.TestCase):
    def test_event_line_has_game_id(self):
        r = mk()
        tmp = r._jsonl_path.parent
        r._transport_event("punt", "1756950000123-4242")
        r._transport_event("wedge")
        lines = [json.loads(x) for x in (tmp / "transport-events.jsonl").read_text().splitlines()]
        self.assertEqual(lines[0]["gameId"], "1756950000123-4242")
        self.assertEqual(lines[0]["kind"], "punt")
        self.assertIsNone(lines[1]["gameId"])


if __name__ == "__main__":
    unittest.main()


class SingleLegalDefender(unittest.TestCase):
    """BL-23: a missing defender is filled in when exactly one is legal (the
    engine's chooseDefender rule); with several legal it is still rejected."""

    def _req(self, defenders):
        return {"decisionType": "DECLARE_ATTACKERS", "prompt": "x",
                "state": {"defenders": [{"id": d, "label": f"seat {d}", "type": "PLAYER"}
                                        for d in defenders]},
                "options": [{"id": 0, "label": "no attack"}, {"id": 302, "label": "Bear"}]}

    def test_one_legal_defender_is_filled_in(self):
        from seatd import rules
        out = rules.validate(self._req([2]), {"attackers": [{"attacker": 302}]})
        self.assertEqual(out, {"attackers": [{"attacker": 302, "defender": 2}]})

    def test_several_legal_defenders_still_require_it(self):
        from seatd import rules
        self.assertIsNone(rules.validate(self._req([1, 2]), {"attackers": [{"attacker": 302}]}))
        # explicit stays explicit
        out = rules.validate(self._req([1, 2]), {"attackers": [{"attacker": 302, "defender": 1}]})
        self.assertEqual(out, {"attackers": [{"attacker": 302, "defender": 1}]})


class TriggerOrderMemo(unittest.TestCase):
    """BL-02 follow-up (review 2026-09-04): the same set of trigger groups is
    ordered once per game; identical later windows replay the model's order
    with no call (Purphoros + Impact Tremors would otherwise ask every ETB)."""

    def _win(self, seq, labels):
        return {"seq": seq, "turn": 4, "phase": "MAIN1", "decisionType": "CHOOSE_MODE",
                "prompt": "ORDER", "state": {"min": len(labels), "max": len(labels),
                                             "allowRepeat": False, "purpose": "TRIGGER_ORDER"},
                "options": [{"id": i, "label": lab, "cost": None, "type": "TRIGGER"}
                            for i, lab in enumerate(labels)]}

    def test_same_groups_replay_in_the_models_order_with_new_indices(self):
        r = mk()
        r.brain.script = [{"chosen": [1, 0]}]          # Tremors first, then Purphoros
        r.handle(self._win(1, ["Purphoros — 2 damage", "Impact Tremors — 1 damage"]))
        self.assertEqual(r.mb.responses[-1][1], {"chosen": [1, 0]})
        # next creature: the engine offers the groups in the other order
        r.handle(self._win(2, ["Impact Tremors — 1 damage", "Purphoros — 2 damage"]))
        self.assertEqual(r.brain.calls, 1, "no second model call")
        self.assertEqual(r.mb.responses[-1][1], {"chosen": [0, 1]}, "Tremors still resolves first")
        self.assertTrue(any("[memo]" in ln for ln in r.log_lines))

    def test_a_new_group_is_a_new_question(self):
        r = mk()
        r.brain.script = [{"chosen": [1, 0]}, {"chosen": [2, 0, 1]}]
        r.handle(self._win(1, ["A — x", "B — y"]))
        r.handle(self._win(2, ["A — x", "B — y", "C — z"]))
        self.assertEqual(r.brain.calls, 2)

    def test_punt_is_never_memoized(self):
        r = mk()
        r.brain.script = [None, {"chosen": [1, 0]}]
        r.handle(self._win(1, ["A — x", "B — y"]))          # punt -> {"chosen": []} hand-back
        self.assertEqual(r.mb.responses[-1][1], {"chosen": []})
        r.handle(self._win(2, ["A — x", "B — y"]))
        self.assertEqual(r.brain.calls, 2, "the punt was not remembered as an order")


class PurposeWindowPunts(unittest.TestCase):
    """BL-02/03 windows: a punt hands the pick back to the engine's stock
    logic via the documented empty list; a model may say the same."""

    def test_safe_default_and_validate(self):
        from seatd import rules
        order = {"decisionType": "CHOOSE_MODE", "prompt": "x",
                 "state": {"min": 2, "max": 2, "purpose": "TRIGGER_ORDER"},
                 "options": [{"id": 0, "label": "a"}, {"id": 1, "label": "b"}]}
        color = {"decisionType": "CHOOSE_MODE", "prompt": "x",
                 "state": {"min": 1, "max": 1, "purpose": "COLOR"},
                 "options": [{"id": 0, "label": "white"}, {"id": 1, "label": "green"}]}
        plain = {"decisionType": "CHOOSE_MODE", "prompt": "x", "state": {"min": 1, "max": 1},
                 "options": [{"id": 0, "label": "a"}, {"id": 1, "label": "b"}]}
        self.assertEqual(rules.safe_default(order), {"chosen": []})
        self.assertEqual(rules.safe_default(color), {"chosen": []})
        self.assertEqual(rules.safe_default(plain), {"chosen": [0]}, "ordinary modes keep the first-min rule")
        self.assertEqual(rules.validate(order, {"chosen": []}), {"chosen": []})
        self.assertEqual(rules.validate(color, {"chosen": []}), {"chosen": []})
        self.assertIsNone(rules.validate(plain, {"chosen": []}), "an empty list is not legal for a real mode choice")
        self.assertEqual(rules.validate(order, {"chosen": [1, 0]}), {"chosen": [1, 0]})
        self.assertIsNone(rules.validate(order, {"chosen": [1]}), "a partial order is not a permutation")
