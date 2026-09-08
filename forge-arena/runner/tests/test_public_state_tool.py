"""The advisor's one tool (2026-09-07): arena-public-state.py renders the
observer snapshot; the advisor's brain gets exactly that command allowlisted
while every seat brain keeps every tool disallowed.
Run: python3 -m unittest discover -s tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import advisor_runner as ar  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "arena-public-state.py"

SNAP = {
    "kind": "observer-snapshot", "timestamp": 1788800000000, "turn": 12, "activeSeat": 1, "phase": "MAIN1", "gameOver": False,
    "seats": [
        {"seat": 0, "name": "Human", "eliminated": False, "life": 31, "poison": 0, "handSize": 4, "librarySize": 80,
         "battlefield": [{"id": 1, "name": "Selvala, Heart of the Wilds", "power": 2, "toughness": 4, "sick": False, "types": "Legendary Creature", "tapped": True,
                          "counters": {"P1P1": 2}, "auras": ["Swiftfoot Boots"]}],
         "graveyard": ["Beast Within"], "exile": [], "commandZone": []},
        {"seat": 1, "name": "mailbox-seat1-Urza", "eliminated": False, "life": 40, "poison": 0, "handSize": 3, "librarySize": 88,
         "battlefield": [{"id": 9, "name": "Isochron Scepter", "types": "Artifact", "tapped": False, "imprinted": ["Pact of Negation"]}],
         "graveyard": [], "exile": ["Pact of Negation"], "commandZone": ["Urza, Lord High Artificer"]},
    ],
    "stack": ["Purphoros, God of the Forge"],
    "stackDetail": [{"kind": "trigger", "name": "Purphoros, God of the Forge", "owner": 3, "targets": ["seat 0"]}],
}


class PublicStateToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.snap = Path(self.tmp.name) / "observer-state.json"
        self.snap.write_text(json.dumps(SNAP))

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(self.snap), *args],
                              capture_output=True, text=True, timeout=30)

    def test_renders_every_public_zone(self):
        p = self._run()
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout
        for needle in ("TURN 12 — MAIN1 — active seat 1", "STACK (1 items", "trigger Purphoros, God of the Forge [seat 3] -> seat 0",
                       "SEAT 0 Human: life 31, hand 4, library 80", "Selvala, Heart of the Wilds 2/4 (tapped)", "counters P1P1 x2",
                       "attached: Swiftfoot Boots", "graveyard (1): Beast Within", "imprinted: Pact of Negation",
                       "command zone: Urza, Lord High Artificer", "exile (1): Pact of Negation"):
            self.assertIn(needle, out, needle)
        self.assertNotIn("hand:", out.lower().replace("hand 4", ""), "hand contents never appear")

    def test_seat_filter_and_json(self):
        p = self._run("--seat", "1")
        self.assertIn("SEAT 1", p.stdout); self.assertNotIn("SEAT 0", p.stdout)
        j = self._run("--json")
        self.assertEqual(json.loads(j.stdout)["turn"], 12)

    def test_no_live_game_exits_2(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--snapshot", str(Path(self.tmp.name) / "missing.json")],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2); self.assertIn("no live game", p.stderr)

    def test_old_snapshot_without_zones_says_so(self):
        old = dict(SNAP); old["seats"] = [{k: v for k, v in s.items() if k not in ("graveyard", "exile", "commandZone")} for s in SNAP["seats"]]
        self.snap.write_text(json.dumps(old))
        self.assertIn("not in this snapshot version", self._run().stdout)

    def test_brain_argv_allowlists_the_tool_for_the_advisor_only(self):
        seat = SeatBrain(1, "urza-lord-high-artificer", model="opus", effort="low", log=lambda *_: None)
        adv = SeatBrain(0, "selvala-heart-of-the-wilds", model="opus", effort="low", log=lambda *_: None,
                        brief="advisor-brief.md", allowed_tools=[ar.PUBLIC_STATE_TOOL])
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            raise OSError("not really launching")
        import seatd.brain as brain_mod
        orig = brain_mod._run
        brain_mod._run = fake_run
        try:
            seat._call("x", 5.0, resume=False)
            seat_cmd = captured["cmd"]
            adv._call("x", 5.0, resume=False)
            adv_cmd = captured["cmd"]
        finally:
            brain_mod._run = orig
        self.assertIn("--disallowedTools", seat_cmd); self.assertNotIn("--allowedTools", seat_cmd)
        self.assertNotIn("--disallowedTools", adv_cmd)
        self.assertEqual(adv_cmd[adv_cmd.index("--allowedTools") + 1], "Bash(python3 forge-arena/scripts/arena-public-state.py:*)")
        for keep in ("--setting-sources", "--strict-mcp-config"):
            self.assertIn(keep, adv_cmd)

    def test_advisor_constructs_its_brain_with_the_tool(self):
        seen = {}

        class FakeBrain:
            def __init__(self, *a, **kw):
                seen.update(kw); self.deck = a[1]; self.model = "opus"; self.effort = "low"; self.totals = {"calls": 0}
            def ensure_session(self, *a, **kw): return True
            def reset(self): pass
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = FakeBrain, (lambda *a, **kw: [])
        try:
            ar.AdvisorRunner("selvala-heart-of-the-wilds", Path(self.tmp.name), "opus", "low", 30.0, log_dir=Path(self.tmp.name) / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        self.assertEqual(seen.get("allowed_tools"), [ar.PUBLIC_STATE_TOOL])
        self.assertIn("arena-public-state.py", (Path(__file__).resolve().parents[1] / "seatd" / "advisor-brief.md").read_text())


if __name__ == "__main__":
    unittest.main()
