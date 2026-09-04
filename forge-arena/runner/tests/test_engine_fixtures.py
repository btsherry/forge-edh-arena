"""Interactive plan item 15 (2026-09-03): the other half of the wire contract.
`ProtocolContractTest` (Java) drives the real controller, validates every
request against schemas/arena.mailbox-request.1.schema.json and writes one
ENGINE-EMITTED request per decision type to fixtures/engine/. Here every one
of those goes through the runner's own punt and validator: the safe default
the runner would send must be a legal answer for what the engine actually
asked, and every engine decision type must be one the runner knows.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import rules  # noqa: E402

ENGINE = Path(__file__).parent / "fixtures" / "engine"


class EngineFixtures(unittest.TestCase):
    def setUp(self):
        self.files = sorted(ENGINE.glob("*.json")) if ENGINE.is_dir() else []
        if not self.files:
            self.skipTest("no engine fixtures — run the Java suite (ProtocolContractTest writes them)")

    def test_safe_default_is_legal_for_every_engine_request(self):
        for f in self.files:
            req = json.loads(f.read_text())
            with self.subTest(fixture=f.stem):
                d = rules.safe_default(req)
                self.assertIsNotNone(rules.validate(req, d),
                                     f"safe_default not legal for the engine's {f.stem}: {d}")

    def test_engine_types_are_known_to_the_runner(self):
        for f in self.files:
            req = json.loads(f.read_text())
            with self.subTest(fixture=f.stem):
                self.assertIn(req["decisionType"], rules.ANSWER_CONTRACT,
                              "the engine emits a decision type the runner does not know")

    def test_engine_requests_carry_identity_and_budget(self):
        for f in self.files:
            req = json.loads(f.read_text())
            with self.subTest(fixture=f.stem):
                self.assertRegex(req["gameId"], r"^\d+-\d+$")
                self.assertGreater(req["timeoutSec"], 0)
                self.assertIn("manaSources", req["state"])
                self.assertIn("manaAvailableNow", req["state"])


if __name__ == "__main__":
    unittest.main()
