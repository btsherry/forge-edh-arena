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
