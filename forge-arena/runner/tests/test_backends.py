"""OpenAI-compatible backend tests (plan v5 §9) against a stdlib http.server
mock: envelope mapping, transcript discipline, wall-clock reads, the error
state machine's latch classes, and the cost/call rails. Run:
python3 -m unittest discover -s tests"""
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd import backends  # noqa: E402

# ---- scripted mock endpoint --------------------------------------------------

SCRIPT: list = []      # each entry: {"status":int,"body":dict|str,"drip":bool}
REQUESTS: list = []    # parsed request bodies, in order


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            REQUESTS.append(json.loads(raw))
        except ValueError:
            REQUESTS.append(raw)
        step = SCRIPT.pop(0) if SCRIPT else {"status": 200, "body": ok_body()}
        body = step["body"]
        payload = (body if isinstance(body, (bytes, str)) else json.dumps(body))
        if isinstance(payload, str):
            payload = payload.encode()
        self.send_response(step.get("status", 200))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if step.get("drip"):
            for i in range(0, len(payload), 16):
                self.wfile.write(payload[i:i + 16])
                self.wfile.flush()
                time.sleep(0.6)
        else:
            self.wfile.write(payload)

    def log_message(self, *a):  # silence
        pass


def ok_body(text='{"chosenId": 0}', cost=0.01, finish="stop"):
    return {"choices": [{"message": {"content": text},
                         "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                      "prompt_tokens_details": {"cached_tokens": 40},
                      "cost": cost}}


class FakeBrain:
    def __init__(self):
        self.totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                       "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0, "cost_usd": 0.0}
        self.backend_latches = {"auth": {}, "model": {}}
        self.lines = []

    def log(self, msg):
        self.lines.append(str(msg))


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        SCRIPT.clear()
        REQUESTS.clear()
        self.brain = FakeBrain()

    def backend(self, kind="or", model="google/gemini-2.5-pro"):
        b = backends.OpenAICompatBackend(kind, model, seat=2,
                                         log=self.brain.log)
        b.base_url = self.url
        b.api_key = "sk-test-KEY-never-logged"
        return b

    def init_ok(self, b):
        SCRIPT.append({"status": 200, "body": ok_body(text="READY")})
        return b.init("SYSTEM INIT PAYLOAD", 30, self.brain)

    # ---- happy path -------------------------------------------------------

    def test_envelope_mapping_and_no_session_id(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 200, "body": ok_body()})
        env = b.call("decide", 30, self.brain, effort="medium")
        self.assertEqual(env["result"], '{"chosenId": 0}')
        self.assertEqual(env["usage"]["input_tokens"], 100)
        self.assertEqual(env["usage"]["output_tokens"], 20)
        self.assertEqual(env["usage"]["cache_read_input_tokens"], 40)
        self.assertEqual(env["total_cost_usd"], 0.01)
        self.assertNotIn("session_id", env)          # F-01: never poison claude
        # transcript: system + one exchange; init probe NOT stored
        self.assertEqual([m["role"] for m in b.messages],
                         ["system", "user", "assistant"])

    def test_request_shape(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 200, "body": ok_body()})
        b.call("decide", 30, self.brain, effort="high")
        req = REQUESTS[-1]
        self.assertIn("max_tokens", req)              # F-14
        self.assertEqual(req["usage"], {"include": True})
        self.assertEqual(req["reasoning"], {"effort": "high"})  # F-36 verbatim
        self.assertEqual(req["messages"][0]["role"], "system")  # F-29

    def test_oai_no_reasoning_no_usage_param(self):
        b = self.backend(kind="oai", model="mistral-7b")
        b.api_key = ""
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 200, "body": ok_body()})
        b.call("decide", 30, self.brain, effort="max")
        req = REQUESTS[-1]
        self.assertNotIn("reasoning", req)
        self.assertNotIn("usage", req)

    # ---- error machine ----------------------------------------------------

    def test_init_4xx_latches_model_and_skips_http(self):
        b = self.backend()
        SCRIPT.append({"status": 400, "body": {"error": {
            "code": 400, "message": "maximum context length exceeded"}}})
        self.assertIsNone(b.init("INIT", 30, self.brain))
        self.assertTrue(self.brain.backend_latches["model"])
        n = len(REQUESTS)
        self.assertIsNone(b.call("decide", 30, self.brain))
        self.assertEqual(len(REQUESTS), n)            # latched: no HTTP fired

    def test_auth_latch_survives_redial_dance(self):
        b = self.backend()
        SCRIPT.append({"status": 401, "body": {"error": {
            "code": 401, "message": "bad key"}}})
        self.assertIsNone(b.init("INIT", 30, self.brain))
        self.assertIn(self.url, self.brain.backend_latches["auth"])
        b2 = self.backend()                            # fresh instance, F-09
        n = len(REQUESTS)
        self.assertIsNone(b2.init("INIT", 30, self.brain))
        self.assertEqual(len(REQUESTS), n)

    def test_moderation_403_no_latch_until_three(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        for i in range(3):
            SCRIPT.append({"status": 403, "body": {"error": {
                "code": 403, "message": "flagged",
                "metadata": {"reasons": ["violence"],
                             "flagged_input": "kill the 2/2"}}}})
            self.assertIsNone(b.call("decide", 30, self.brain))
            if i < 2:
                self.assertFalse(self.brain.backend_latches["model"], i)
        self.assertTrue(self.brain.backend_latches["model"])

    def test_bare_403_is_auth_latch(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 403, "body": {"error": {
            "code": 403, "message": "forbidden"}}})
        self.assertIsNone(b.call("decide", 30, self.brain))
        self.assertIn(self.url, self.brain.backend_latches["auth"])

    def test_402_latches(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 402, "body": {"error": {
            "code": 402, "message": "insufficient credits"}}})
        self.assertIsNone(b.call("decide", 30, self.brain))
        self.assertTrue(self.brain.backend_latches["model"])

    def test_error_inside_http_200(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 200, "body": {"error": {
            "code": 402, "message": "credits ran dry mid-stream"}}})
        self.assertIsNone(b.call("decide", 30, self.brain))   # F-12
        self.assertTrue(self.brain.backend_latches["model"])

    def test_429_then_success_retries_once(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 429, "body": {"error": {
            "code": 429, "message": "slow down"}}})
        SCRIPT.append({"status": 200, "body": ok_body()})
        env = b.call("decide", 60, self.brain)
        self.assertIsNotNone(env)

    def test_5xx_then_success_retries_once(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 502, "body": "bad gateway"})
        SCRIPT.append({"status": 200, "body": ok_body()})
        self.assertIsNotNone(b.call("decide", 60, self.brain))

    def test_reasoning_400_drops_param_and_retries(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 400, "body": {"error": {
            "code": 400, "message": "unknown parameter: reasoning"}}})
        SCRIPT.append({"status": 200, "body": ok_body()})
        self.assertIsNotNone(b.call("decide", 60, self.brain, effort="high"))
        self.assertIn("reasoning", REQUESTS[-2])
        self.assertNotIn("reasoning", REQUESTS[-1])

    def test_context_overflow_shrinks_then_latches(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        for i in range(12):                            # build history
            SCRIPT.append({"status": 200, "body": ok_body()})
            b.call(f"d{i}", 30, self.brain)
        SCRIPT.append({"status": 400, "body": {"error": {
            "code": 400, "message": "this model's maximum context length..."}}})
        SCRIPT.append({"status": 200, "body": ok_body()})
        before = len(b.messages)
        self.assertIsNotNone(b.call("decide", 60, self.brain))  # shrink+recover
        self.assertLess(len(b.messages), before)
        SCRIPT.append({"status": 400, "body": {"error": {
            "code": 400, "message": "maximum context length exceeded"}}})
        SCRIPT.append({"status": 400, "body": {"error": {
            "code": 400, "message": "maximum context length exceeded"}}})
        self.assertIsNone(b.call("decide", 60, self.brain))     # shrink fails
        self.assertTrue(self.brain.backend_latches["model"])

    def test_slow_drip_bounded_by_wall_clock(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 200, "body": ok_body(), "drip": True})
        t0 = time.monotonic()
        self.assertIsNone(b.call("decide", 2, self.brain))      # F-07
        self.assertLess(time.monotonic() - t0, 10)

    # ---- rails --------------------------------------------------------------

    def test_cost_cap_latches_without_http(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        self.brain.totals["cost_usd"] = 5.01
        n = len(REQUESTS)
        self.assertIsNone(b.call("decide", 30, self.brain))
        self.assertEqual(len(REQUESTS), n)
        self.assertTrue(any("__cost_cap__" in v for v in
                            self.brain.backend_latches["model"].values()))

    def test_call_cap_latches(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        self.brain.totals["backend_attempts"] = 250
        self.assertIsNone(b.call("decide", 30, self.brain))
        self.assertTrue(any("__call_cap__" in v for v in
                            self.brain.backend_latches["model"].values()))

    def test_absent_cost_flags_unenforceable(self):
        b = self.backend()
        body = ok_body()
        del body["usage"]["cost"]
        SCRIPT.append({"status": 200, "body": dict(body, **{
            "choices": [{"message": {"content": "READY"},
                         "finish_reason": "stop"}]})})
        self.assertIsNotNone(b.init("INIT", 30, self.brain))
        for i in range(2):
            SCRIPT.append({"status": 200, "body": body})
            b.call(f"d{i}", 30, self.brain)
        self.assertTrue(b.cap_unenforceable)           # F-16: 3 consecutive
        self.assertTrue(any("cap NOT enforceable" in l
                            for l in self.brain.lines))

    def test_transport_failure_counts_unmetered(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        b.base_url = "http://127.0.0.1:9"               # nothing listens here
        self.assertIsNone(b.call("decide", 4, self.brain))
        self.assertGreaterEqual(self.brain.totals.get("unmetered_attempts", 0), 1)
        self.assertGreater(self.brain.totals.get("unmetered_est_tokens", 0), 0)

    # ---- hygiene ------------------------------------------------------------

    def test_key_never_in_logs(self):
        b = self.backend()
        SCRIPT.append({"status": 401, "body": {"error": {
            "code": 401, "message": "bad key"}}})
        b.init("INIT", 30, self.brain)
        for line in self.brain.lines:
            self.assertNotIn("sk-test-KEY", line)

    def test_truncation_logged(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        SCRIPT.append({"status": 200, "body": ok_body(finish="length")})
        b.call("decide", 30, self.brain)
        self.assertTrue(any("TRUNCATED" in l for l in self.brain.lines))

    def test_alternation_after_trim(self):
        b = self.backend()
        self.assertIsNotNone(self.init_ok(b))
        for i in range(30):
            SCRIPT.append({"status": 200, "body": ok_body()})
            b.call(f"d{i}", 30, self.brain)
        roles = [m["role"] for m in b.messages]
        self.assertEqual(roles[0], "system")
        body = roles[1:]
        self.assertTrue(all(r == ("user" if i % 2 == 0 else "assistant")
                            for i, r in enumerate(body)))
        # trim runs pre-send: stored history is at most default-8 exchanges
        # plus the exchange just appended after the successful call.
        self.assertLessEqual(len(body), 18)


class ParseModelTests(unittest.TestCase):
    def test_grammar(self):
        self.assertEqual(backends.parse_model("opus"), ("claude", "opus"))
        self.assertEqual(backends.parse_model("or/google/gemini-2.5-pro"),
                         ("or", "google/gemini-2.5-pro"))
        self.assertEqual(backends.parse_model("or/meta/llama-3:free"),
                         ("or", "meta/llama-3:free"))
        self.assertEqual(backends.parse_model("oai/mistral-7b"),
                         ("oai", "mistral-7b"))
        # unknown prefixed forms stay on the claude path (fail like today)
        self.assertEqual(backends.parse_model("google/gemini")[0], "claude")
        self.assertEqual(backends.parse_model(None)[0], "claude")


if __name__ == "__main__":
    unittest.main()
