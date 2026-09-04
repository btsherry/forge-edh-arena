"""The no-harm proof (plan v5 §9, F-26): with no backend configured, the
Claude CLI invocation is byte-identical to the pinned known-good argv, the
session lifecycle is untouched, and no backend key ever leaks into the
schemas. Deliberately offline: subprocess.run is monkeypatched — NO argv
logging was added to brain.py, because the guard must never modify the
surface it proves unchanged. Run: python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd import brain as brain_mod  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402

DECK = "selvala-heart-of-the-wilds"

GOLDEN_INIT_ARGV = ["claude", "-p", "-", "--output-format", "json",
                    "--model", "opus", "--effort", "low",
                    "--disallowedTools", "*",
                    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                    "--setting-sources", ""]   # BL-24: no hooks/plugins/settings
GOLDEN_DECIDE_ARGV = GOLDEN_INIT_ARGV + ["--resume", "sess-golden-1"]
GOLDEN_TOTALS_KEYS = {"calls", "input_tokens", "output_tokens",
                      "cache_read_input_tokens",
                      "cache_creation_input_tokens", "cost_usd"}


class Proc:
    returncode = 0
    stderr = ""

    def __init__(self, stdout):
        self.stdout = stdout


def envelope(session="sess-golden-1", result="READY"):
    return json.dumps({"session_id": session, "result": result,
                       "usage": {"input_tokens": 90000, "output_tokens": 5,
                                 "cache_read_input_tokens": 0,
                                 "cache_creation_input_tokens": 90000},
                       "total_cost_usd": 0.42, "is_error": False})


class GoldenClaudeTests(unittest.TestCase):
    def setUp(self):
        self.argvs = []
        self._orig = brain_mod._run

        def fake_run(cmd, **kw):
            self.argvs.append(list(cmd))
            return Proc(envelope())

        brain_mod._run = fake_run
        self.addCleanup(lambda: setattr(brain_mod, "_run", self._orig))

    def test_argv_byte_identical_and_lifecycle(self):
        b = SeatBrain(1, DECK, model="opus", effort="low", log=lambda *a: None)
        self.assertIsNone(b.backend)                    # bare name -> claude
        self.assertTrue(b.ensure_session())
        self.assertEqual(self.argvs[0], GOLDEN_INIT_ARGV)
        ans, meta = b.decide('{"prompt": "x"}', timeout_s=72.0)
        self.assertEqual(self.argvs[1], GOLDEN_DECIDE_ARGV)
        self.assertEqual(set(meta.keys()),
                         {"latency_s", "usage", "cache_read", "raw"})
        self.assertEqual(set(meta["usage"].keys()),
                         {"input_tokens", "output_tokens",
                          "cache_read_input_tokens",
                          "cache_creation_input_tokens"})

    def test_totals_schema_has_no_backend_keys(self):
        b = SeatBrain(1, DECK, model="opus", log=lambda *a: None)
        b.ensure_session()
        b.decide("x", timeout_s=72.0)
        self.assertEqual(set(b.totals.keys()), GOLDEN_TOTALS_KEYS)
        b.reset()
        self.assertEqual(set(b.totals.keys()), GOLDEN_TOTALS_KEYS)

    def test_detour_preserves_claude_session(self):
        """Gemini r3-1: claude -> backend -> claude resumes the ORIGINAL
        session with no re-init and never --resumes a synthetic id."""
        b = SeatBrain(1, DECK, model="opus", log=lambda *a: None)
        b.ensure_session()
        self.assertEqual(b.session_id, "sess-golden-1")
        b.set_model("or/google/gemini-2.5-pro")
        self.assertIsNotNone(b.backend)
        self.assertEqual(b.session_id, "sess-golden-1")  # untouched by detour
        b.set_model("opus")
        self.assertIsNone(b.backend)
        n_calls = len(self.argvs)
        self.assertTrue(b.ensure_session())              # no re-init needed
        self.assertEqual(len(self.argvs), n_calls)
        b.decide("y", timeout_s=72.0)
        self.assertEqual(self.argvs[-1][-2:], ["--resume", "sess-golden-1"])

    def test_same_class_redial_keeps_transcript(self):
        b = SeatBrain(1, DECK, model="or/google/gemini-2.5-pro",
                      log=lambda *a: None)
        self.assertIsNotNone(b.backend)
        b.backend.messages = [{"role": "system", "content": "init"}]
        b.backend.ready = True
        old_backend = b.backend
        b.set_model("or/openai/gpt-5.2")
        self.assertIs(b.backend, old_backend)            # or/->or/: same inst
        self.assertEqual(b.backend.model_id, "openai/gpt-5.2")

    def test_cost_totals_survive_transport_swaps(self):
        b = SeatBrain(1, DECK, model="or/google/gemini-2.5-pro",
                      log=lambda *a: None)
        b.totals["cost_usd"] = 3.75
        b.set_model("opus")
        b.set_model("or/google/gemini-2.5-pro")
        self.assertEqual(b.totals["cost_usd"], 3.75)     # F-06: rail survives

    def test_auth_latch_persists_across_reset_model_latch_clears(self):
        b = SeatBrain(1, DECK, model="or/google/gemini-2.5-pro",
                      log=lambda *a: None)
        b.backend_latches["auth"]["https://openrouter.ai/api/v1"] = "401"
        b.backend_latches["model"]["google/gemini-2.5-pro"] = "init 400"
        b.reset()
        self.assertTrue(b.backend_latches["auth"])       # bad key doesn't heal
        self.assertFalse(b.backend_latches["model"])     # per-game latch


if __name__ == "__main__":
    unittest.main()
