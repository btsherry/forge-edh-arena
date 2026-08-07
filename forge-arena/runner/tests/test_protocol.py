"""Transport-layer tests (H1 checkpoint). Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.protocol import SeatMailbox  # noqa: E402


def write_req(inbox: Path, seq: int, payload=None, age_s: float = 0.0):
    inbox.mkdir(parents=True, exist_ok=True)
    p = inbox / f"req-{seq}.json"
    body = {"seq": seq, "seat": 2, "turn": 1, "phase": "MAIN1",
            "decisionType": "CAST_SPELL", "prompt": "x", "state": {},
            "options": [{"id": 0, "label": "Pass (do nothing)"}]}
    if payload is not None:
        body = payload
    p.write_text(json.dumps(body))
    if age_s:
        past = time.time() - age_s
        os.utime(p, (past, past))
    return p


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.mb = SeatMailbox(2, self.base, timeout_s=90.0)

    def tearDown(self):
        self.tmp.cleanup()

    # -- discovery ----------------------------------------------------------

    def test_pending_returns_oldest_fresh_req(self):
        write_req(self.mb.inbox, 4)
        write_req(self.mb.inbox, 3)
        req = self.mb.pending_request()
        self.assertEqual(req["seq"], 3)

    def test_tmp_staging_files_ignored(self):
        (self.mb.inbox).mkdir(parents=True)
        (self.mb.inbox / "req-9.json.tmp").write_text("{}")
        self.assertIsNone(self.mb.pending_request())

    def test_stale_orphan_req_ignored(self):
        write_req(self.mb.inbox, 1, age_s=120.0)  # older than timeout: dead engine
        self.assertIsNone(self.mb.pending_request())

    def test_partial_write_is_transient_not_fatal(self):
        self.mb.inbox.mkdir(parents=True)
        (self.mb.inbox / "req-2.json").write_text('{"seq": 2, "trunc')
        self.assertIsNone(self.mb.pending_request())  # no crash, retry next tick

    # -- responding -----------------------------------------------------------

    def test_respond_atomic_write_and_consumption(self):
        req_path = write_req(self.mb.inbox, 1)
        req = self.mb.pending_request()

        # simulate the engine: consume resp then req shortly after it appears
        import threading

        def engine():
            final = self.mb.outbox / "resp-1.json"
            for _ in range(100):
                if final.exists():
                    json.loads(final.read_text())  # engine parses it
                    final.unlink()
                    req_path.unlink()
                    return
                time.sleep(0.01)

        t = threading.Thread(target=engine)
        t.start()
        ok = self.mb.respond(req, {"chosenId": 0})
        t.join()
        self.assertTrue(ok)
        self.assertFalse(any(self.mb.outbox.glob("*.tmp")))  # never leaves staging

    def test_respond_refuses_when_req_vanished(self):
        req_path = write_req(self.mb.inbox, 1)
        req = self.mb.pending_request()
        req_path.unlink()  # engine timed out first
        self.assertFalse(self.mb.respond(req, {"chosenId": 0}))
        self.assertFalse((self.mb.outbox / "resp-1.json").exists())

    def test_late_resp_garbage_collected(self):
        req_path = write_req(self.mb.inbox, 1)
        req = self.mb.pending_request()

        import threading

        def engine_gives_up():
            time.sleep(0.1)
            req_path.unlink()  # engine deletes req, never touches resp

        t = threading.Thread(target=engine_gives_up)
        t.start()
        ok = self.mb.respond(req, {"chosenId": 0}, consume_wait_s=0.5)
        t.join()
        self.assertFalse(ok)
        self.assertFalse((self.mb.outbox / "resp-1.json").exists())  # GC'd

    # -- races and restarts ----------------------------------------------------

    def test_answered_seq_not_returned_during_delete_race(self):
        req_path = write_req(self.mb.inbox, 1)
        req = self.mb.pending_request()
        self.mb.respond(req, {"chosenId": 0}, consume_wait_s=0.0)
        # engine deleted resp but req-1 still lingers for a poll cycle
        (self.mb.outbox / "resp-1.json").unlink()
        self.assertTrue(req_path.exists())
        self.assertIsNone(self.mb.pending_request())  # not answered twice

    def test_seq_regression_signals_new_game(self):
        write_req(self.mb.inbox, 5)
        req = self.mb.pending_request()
        self.mb.respond(req, {"chosenId": 0}, consume_wait_s=0.0)
        (self.mb.inbox / "req-5.json").unlink()
        (self.mb.outbox / "resp-5.json").unlink()
        self.assertFalse(self.mb.game_reset)

        write_req(self.mb.inbox, 1)  # engine restarted: seq starts over
        req = self.mb.pending_request()
        self.assertIsNotNone(req)
        self.assertEqual(req["seq"], 1)
        self.assertTrue(self.mb.game_reset)

    def test_startup_outbox_sweep(self):
        self.mb.outbox.mkdir(parents=True)
        (self.mb.outbox / "resp-7.json").write_text("{}")
        (self.mb.outbox / "resp-3.json.tmp").write_text("{")
        self.assertEqual(self.mb.sweep_outbox(), 2)
        self.assertEqual(list(self.mb.outbox.iterdir()), [])

    # -- fairness ---------------------------------------------------------------

    def test_paths_confined_to_own_seat(self):
        for p in (self.mb.inbox, self.mb.outbox):
            self.assertIn(f"seat-{self.mb.seat}", str(p))
        # the only path outside the seat dir is the public observer snapshot
        self.assertEqual(self.mb.observer_path.name, "observer-state.json")


if __name__ == "__main__":
    unittest.main()
