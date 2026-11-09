"""SeatBrain and its transports (seatd/brain.py): PersistentClaude — one stream-json process per session,
a timeout kills it and the brain falls back to the per-call --resume spawn with only the REMAINING window
(game 26); the decision budget is ONE clock shared by init and the call (plan item 2); wedged-session
recovery (game 7) after consecutive failures spanning long enough, fast bursts kept; two back-to-back stalls
rotate the session at once (B3 / W-18); rotation itself (a fresh session carrying the record; a failed one
keeps the old); BL-27 extract_json survives mana symbols in prose; BL-28 the CLI child is tracked, killable,
and killed by the seat's signal handler. Run: python3 -m unittest discover -s tests"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seatd.brain as brain_mod  # noqa: E402
from seatd.brain import PersistentClaude, SeatBrain  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402
import seat_runner  # noqa: E402
from tests.support import Proc, envelope  # noqa: E402


DECK = "selvala-heart-of-the-wilds"


class FakeProc:
    """Stands in for subprocess.Popen: replies to each user line with events
    ending in a result; optionally never answers (timeout path). readline()
    BLOCKS until a line exists or the process is killed (like a real pipe)."""
    def __init__(self, session="s1", silent=False):
        import threading
        self._cv = threading.Condition()
        self._out = []
        self._silent = silent
        self._session = session
        self._rc = None
        self.written = []
        proc = self

        class _In:
            def write(self, s):
                proc.written.append(s)
                proc.feed(s)
                return len(s)

            def flush(self):
                pass

        class _Out:
            def readline(self):
                with proc._cv:
                    while not proc._out and proc._rc is None:
                        proc._cv.wait(timeout=0.05)
                    return proc._out.pop(0) if proc._out else ""
        self.stdin = _In()
        self.stdout = _Out()

    def poll(self):
        return self._rc

    def kill(self):
        with self._cv:
            self._rc = -9
            self._cv.notify_all()

    def wait(self, timeout=None):
        return self._rc

    def feed(self, prompt):
        if self._silent:
            return
        with self._cv:
            self._out.append(json.dumps({"type": "assistant", "message": {}}) + "\n")
            self._out.append(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "OK",
                                         "session_id": self._session,
                                         "usage": {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 100,
                                                   "cache_creation_input_tokens": 5}}) + "\n")
            self._cv.notify_all()


class PersistentClaudeTests(unittest.TestCase):
    def _persistent(self, silent=False):
        seen = {}
        p = PersistentClaude(["claude", "-p"], "s1", "/tmp", (lambda m: seen.setdefault("logs", []).append(m)))
        p._spawn = lambda: seen.setdefault("proc", FakeProc(silent=silent))
        return p, seen

    def test_call_returns_the_result_envelope_and_reuses_the_process(self):
        p, seen = self._persistent()
        env = p.call("Q1", 5.0)
        self.assertEqual(env["result"], "OK"); self.assertEqual(env["session_id"], "s1")
        env2 = p.call("Q2", 5.0)
        self.assertIsNotNone(env2); self.assertEqual(p.turns, 2)
        self.assertEqual(len(seen["proc"].written), 2, "both turns went to the SAME process")
        self.assertIn('"type": "user"', seen["proc"].written[0])
        self.assertIn("--input-format", p.cmd); self.assertIn("--resume", p.cmd)

    def test_timeout_kills_the_process_and_returns_none(self):
        p, seen = self._persistent(silent=True)
        self.assertIsNone(p.call("Q", 0.2))
        self.assertFalse(p.alive()); self.assertEqual(seen["proc"]._rc, -9)
        self.assertTrue(any("timed out" in l for l in seen["logs"]))


class BrainTransportTests(unittest.TestCase):
    def _brain(self, persistent=True):
        prev = os.environ.get("ARENA_BRAIN_TRANSPORT")
        os.environ["ARENA_BRAIN_TRANSPORT"] = "persistent" if persistent else "spawn"
        try:
            b = SeatBrain(2, "giada-font-of-hope", model="opus", effort="medium", log=lambda *_: None)
        finally:
            # restore, never pop: other test modules pinned "spawn" at import (tests/__init__)
            if prev is None:
                os.environ.pop("ARENA_BRAIN_TRANSPORT", None)
            else:
                os.environ["ARENA_BRAIN_TRANSPORT"] = prev
        b.session_id = "s-live"
        return b

    def test_persistent_path_is_used_and_falls_back_on_failure(self):
        b = self._brain()
        calls = []

        class P:
            def __init__(self, cmd, sid, cwd, log, **kw): calls.append(("new", sid)); self.ok = True
            def alive(self): return self.ok
            def start(self): return True
            def call(self, prompt, timeout_s):
                calls.append(("call", prompt))
                return {"result": "{}", "session_id": "s-live", "usage": {"input_tokens": 1, "output_tokens": 1,
                        "cache_read_input_tokens": 10, "cache_creation_input_tokens": 0}}
            def kill(self): self.ok = False
            proc = None
        orig_cls, orig_run = brain_mod.PersistentClaude, brain_mod._run
        brain_mod.PersistentClaude = P
        spawned = []
        brain_mod._run = lambda cmd, **kw: spawned.append(cmd) or (_ for _ in ()).throw(OSError("no spawn expected"))
        try:
            env = b._call("hello", 10.0, resume=True)
            self.assertIsNotNone(env); self.assertEqual(b.persistent_calls, 1); self.assertEqual(spawned, [])
            # a different EFFORT keeps the live process (keyed on model only, Ben
            # 2026-09-08): the call is answered at the process's effort and counted
            b._call("low one", 10.0, resume=True, effort="low")
            self.assertEqual(spawned, [], "no spawn for an effort flip")
            self.assertEqual(b.effort_pinned, 1); self.assertEqual(b.persistent_calls, 2)
            self.assertIsNotNone(b._persistent, "the process stays up across effort flips")
            # a different MODEL stops it (transcript is in memory) and starts a fresh one
            b.model = "sonnet"
            b._call("other model", 10.0, resume=True)
            self.assertEqual(len(calls), 5, "a new process for the new model")   # new, call, call(pinned), new, call
            # process failure -> fallback counted, spawn used
            P.call = lambda self, prompt, timeout_s: None
            b._call("again", 10.0, resume=True)
            self.assertEqual(b.persistent_fallbacks, 1); self.assertEqual(len(spawned), 1, "the failure is the only spawn")
        finally:
            brain_mod.PersistentClaude, brain_mod._run = orig_cls, orig_run

    def test_process_starts_at_the_base_effort_and_a_control_change_restarts_it(self):
        """Game 43 (2026-09-10): seats restarted inside a low-effort reaction window and
        then played every decision at low while the AI panel said high."""
        b = self._brain()
        started = []

        class P:
            def __init__(self, cmd, sid, cwd, log, **kw): started.append(list(cmd)); self.ok = True
            def alive(self): return self.ok
            def start(self): return True
            def call(self, prompt, timeout_s):
                return {"result": "{}", "session_id": "s-live", "usage": {"input_tokens": 1, "output_tokens": 1,
                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
            def kill(self): self.ok = False
            proc = None
        orig_cls, orig_run = brain_mod.PersistentClaude, brain_mod._run
        brain_mod.PersistentClaude = P
        brain_mod._run = lambda cmd, **kw: (_ for _ in ()).throw(OSError("no spawn expected"))
        try:
            b._call("react", 10.0, resume=True, effort="low")           # the FIRST call asks low…
            self.assertEqual(started[0][started[0].index("--effort") + 1], "medium", "…but the process starts at the seat's base effort")
            self.assertEqual(b._persistent_key, ("opus", "medium"))
            self.assertEqual(b.last_effort_used, "medium", "and the record says what was really used")
            self.assertEqual(b.effort_pinned, 1)
            # the AI panel's effort button: the runner restarts the process at the new effort
            b.effort = "high"; b.stop_persistent()
            b._call("main", 10.0, resume=True)
            self.assertEqual(len(started), 2); self.assertEqual(started[1][started[1].index("--effort") + 1], "high")
            self.assertEqual(b.last_effort_used, "high")
        finally:
            brain_mod.PersistentClaude, brain_mod._run = orig_cls, orig_run

    def test_spawn_mode_never_touches_the_persistent_class(self):
        b = self._brain(persistent=False)   # ARENA_BRAIN_TRANSPORT=spawn (persistent is the default now)
        touched = []
        orig_cls, orig_run = brain_mod.PersistentClaude, brain_mod._run
        brain_mod.PersistentClaude = lambda *a, **k: touched.append(1)
        brain_mod._run = lambda cmd, **kw: (_ for _ in ()).throw(OSError("stop"))
        try:
            b._call("x", 5.0, resume=True)
            self.assertEqual(touched, [])
        finally:
            brain_mod.PersistentClaude, brain_mod._run = orig_cls, orig_run


class FallbackBudgetTests(unittest.TestCase):
    """Game 26: after a persistent-process timeout the spawn fallback must get
    only the REMAINING window, i.e. nothing — punt at once, never wait twice."""
    def _brain(self):
        prev = os.environ.get("ARENA_BRAIN_TRANSPORT")
        os.environ["ARENA_BRAIN_TRANSPORT"] = "persistent"
        try:
            b = SeatBrain(2, "giada-font-of-hope", model="opus", effort="medium", log=lambda *_: None)
        finally:
            if prev is None:
                os.environ.pop("ARENA_BRAIN_TRANSPORT", None)
            else:
                os.environ["ARENA_BRAIN_TRANSPORT"] = prev
        b.session_id = "s-live"
        return b

    def test_timeout_leaves_no_time_so_no_spawn(self):
        b = self._brain()
        import time as _t

        class SlowP:
            def __init__(self, *a, **k): self.ok = True
            def alive(self): return self.ok
            def start(self): return True
            def call(self, prompt, timeout_s):
                _t.sleep(min(timeout_s, 0.3)); self.ok = False; return None   # "timed out", process killed
            def kill(self): self.ok = False
            proc = None
        spawned = []
        orig, orig_run = brain_mod.PersistentClaude, brain_mod._run
        brain_mod.PersistentClaude = SlowP
        brain_mod._run = lambda cmd, **kw: spawned.append(cmd) or (_ for _ in ()).throw(OSError("no spawn expected"))
        try:
            self.assertIsNone(b._call("q", 0.3, resume=True))
            self.assertEqual(spawned, [], "the window is spent: punt, do not wait a second time")
            self.assertEqual(b.persistent_fallbacks, 1)
        finally:
            brain_mod.PersistentClaude, brain_mod._run = orig, orig_run

    def test_quick_failure_still_spawns_with_the_remaining_time(self):
        b = self._brain()

        class DeadP:
            def __init__(self, *a, **k): pass
            def alive(self): return False
            def start(self): return False     # launch failed at once
            def kill(self): pass
            proc = None
        seen = {}

        def fake_run(cmd, **kw):
            seen["timeout"] = kw.get("timeout"); raise OSError("stop here")
        orig, orig_run = brain_mod.PersistentClaude, brain_mod._run
        brain_mod.PersistentClaude = DeadP
        brain_mod._run = fake_run
        try:
            b._call("q", 30.0, resume=True)
            self.assertIsNotNone(seen.get("timeout"))
            self.assertGreater(seen["timeout"], 29.0, "a quick failure leaves the whole window for the spawn")
        finally:
            brain_mod.PersistentClaude, brain_mod._run = orig, orig_run


class BudgetDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.calls = []            # (timeout passed to subprocess, was_init)
        self.init_takes = [0.0]    # simulated wall time the init call burns
        self.now = [1000.0]
        orig_run, orig_time = brain_mod._run, brain_mod.time.time

        def fake_run(cmd, **kw):
            is_init = "--resume" not in cmd
            self.calls.append((kw.get("timeout"), is_init))
            if is_init:
                self.now[0] += self.init_takes[0]
            else:
                self.now[0] += 1.0
            return Proc(envelope("sess-A"))

        brain_mod._run = fake_run
        brain_mod.time.time = lambda: self.now[0]
        self.addCleanup(lambda: setattr(brain_mod, "_run", orig_run))
        self.addCleanup(lambda: setattr(brain_mod.time, "time", orig_time))

    def _brain(self):
        return SeatBrain(1, DECK, model="opus", effort="low", log=lambda *a: None)

    def test_init_and_call_share_one_deadline(self):
        b = self._brain()
        self.init_takes[0] = 50.0
        deadline = self.now[0] + 72.0
        ans, _ = b.decide("q", deadline=deadline)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertEqual(len(self.calls), 2, "init then decision")
        init_to, dec_to = self.calls[0][0], self.calls[1][0]
        self.assertLessEqual(init_to, 72.0 - 5.0 + 1e-6,
                             "init may use the window minus the call floor")
        self.assertLessEqual(dec_to, 72.0 - 50.0 + 1e-6,
                             "the decision call gets only what is LEFT after init")
        self.assertLessEqual(self.now[0], deadline + 1e-6,
                             "the answer landed before the engine's deadline")

    def test_init_that_eats_the_window_punts_on_time(self):
        b = self._brain()
        self.init_takes[0] = 70.0
        deadline = self.now[0] + 72.0
        ans, _ = b.decide("q", deadline=deadline)
        self.assertIsNone(ans, "under the call floor -> safe default, no model call")
        self.assertEqual(len(self.calls), 1, "no decision call was attempted")
        self.assertTrue(b.session_id, "the session stays warm for the next decision")

    def test_warm_session_gets_the_whole_remaining_window(self):
        b = self._brain()
        b.session_id = "sess-A"          # already initialised
        deadline = self.now[0] + 72.0
        ans, _ = b.decide("q", deadline=deadline)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertEqual(len(self.calls), 1)
        self.assertAlmostEqual(self.calls[0][0], 72.0, places=6)

    def test_legacy_duration_form_still_works(self):
        b = self._brain()
        b.session_id = "sess-A"
        ans, _ = b.decide("q", timeout_s=30.0)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertAlmostEqual(self.calls[0][0], 30.0, places=6)

    def test_no_fixed_cap_on_long_timeout_games(self):
        b = self._brain()
        b.session_id = "sess-A"
        deadline = self.now[0] + 300.0
        b.decide("q", deadline=deadline)
        self.assertAlmostEqual(self.calls[0][0], 300.0, places=6,
                               msg="the old 240s literal is gone; the engine's timeout rules")


class WedgeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []          # (argv, prompt)
        self.script = []         # per-call behaviour: "ok" | "exit1" | "timeout"
        self.now = [1000.0]
        self.sessions = iter(["sess-A", "sess-B", "sess-C"])
        self.cur = ["sess-A"]
        orig_run, orig_time = brain_mod._run, brain_mod.time.time

        def fake_run(cmd, **kw):
            self.calls.append((list(cmd), kw.get("input", "")))
            beh = self.script.pop(0) if self.script else "ok"
            if beh == "exit1":
                return Proc('{"is_error":true,"result":"API Error: 500"}', returncode=1)
            if beh == "timeout":
                raise brain_mod.subprocess.TimeoutExpired(cmd, 72)
            if "--resume" not in cmd:          # fresh init: new session id
                self.cur[0] = next(self.sessions)
            return Proc(envelope(self.cur[0]))

        brain_mod._run = fake_run
        brain_mod.time.time = lambda: self.now[0]
        self.addCleanup(lambda: setattr(brain_mod, "_run", orig_run))
        self.addCleanup(lambda: setattr(brain_mod.time, "time", orig_time))

    def _brain(self):
        return SeatBrain(1, DECK, model="opus", effort="low", log=lambda *a: None)

    def test_fast_burst_keeps_session(self):
        b = self._brain()
        self.assertTrue(b.ensure_session())
        self.assertEqual(b.session_id, "sess-A")
        # three exit-1s within 10 seconds: a blip, not a wedge
        self.script = ["exit1", "exit1", "exit1"]
        for _ in range(3):
            self.now[0] += 3
            ans, _ = b.decide("q", timeout_s=60)
            self.assertIsNone(ans)
        self.assertEqual(b.session_id, "sess-A", "a 9s burst must not drop the session")
        ans, _ = b.decide("q", timeout_s=60)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertEqual(b._fail_streak, 0)

    def test_long_streak_reinits_and_rejoins(self):
        b = self._brain()
        self.assertTrue(b.ensure_session())
        # three failures spanning >= 60s (two 72s timeouts then a 500) => wedged
        self.script = ["timeout", "timeout", "exit1"]
        for _ in range(3):
            self.now[0] += 72
            ans, _ = b.decide("q", timeout_s=90)
            self.assertIsNone(ans)
        self.assertIsNone(b.session_id, "wedge must drop the resumed session")
        self.assertTrue(b._rejoin_pending)
        # next decision: fresh init (no --resume), then the decision with the note
        n = len(self.calls)
        ans, _ = b.decide("DECISION seq=9", timeout_s=90)
        self.assertEqual(ans, {"chosenId": 0})
        init_argv, init_prompt = self.calls[n]
        dec_argv, dec_prompt = self.calls[n + 1]
        self.assertNotIn("--resume", init_argv)
        self.assertIn("--resume", dec_argv)
        self.assertEqual(dec_argv[dec_argv.index("--resume") + 1], "sess-B")
        self.assertTrue(dec_prompt.startswith(brain_mod.REJOIN_NOTE))
        self.assertIn("DECISION seq=9", dec_prompt)
        self.assertFalse(b._rejoin_pending)
        # the note is one-shot
        ans, _ = b.decide("DECISION seq=10", timeout_s=90)
        self.assertFalse(self.calls[-1][1].startswith(brain_mod.REJOIN_NOTE))

    def test_hard_fail_count_wedges_regardless_of_time(self):
        b = self._brain()
        self.assertTrue(b.ensure_session())
        self.script = ["exit1"] * brain_mod.WEDGE_HARD_FAILS
        for _ in range(brain_mod.WEDGE_HARD_FAILS):
            self.now[0] += 1
            b.decide("q", timeout_s=60)
        self.assertIsNone(b.session_id)

    def test_nonzero_exit_logs_stdout(self):
        lines = []
        b = SeatBrain(1, DECK, model="opus", effort="low", log=lines.append)
        self.assertTrue(b.ensure_session())
        self.script = ["exit1"]
        b.decide("q", timeout_s=60)
        self.assertTrue(any("API Error: 500" in l for l in lines),
                        "the stdout envelope text must reach the seat log")


ENVELOPE = {"type": "result", "result": '{"chosenId": 0, "why": "hold"}', "session_id": "s-old",
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 5}}


class FakePersistent:
    """The long-lived transport: every call is a deadline kill until `ok` is set."""
    ok = False
    made = []

    def __init__(self, cmd_base, session_id, cwd, log, stderr_path=None):
        self.cmd = list(cmd_base); self.session_id = session_id; self.log = log
        self.proc = None; self.turns = 0; self.last_timeout = False; self._alive = False
        FakePersistent.made.append(self)

    def alive(self):
        return self._alive

    def start(self):
        self._alive = True
        return True

    def kill(self):
        self._alive = False

    def call(self, prompt, timeout_s):
        self.last_timeout = False
        if FakePersistent.ok:
            self.turns += 1
            return dict(ENVELOPE)
        self.last_timeout = True     # what the real call() does before killing the process
        self.kill()
        return None


def _spawn_times_out(cmd, *, input, timeout, cwd, on_child=None):
    raise subprocess.TimeoutExpired(cmd, timeout)


def _req(seq):
    return {"seq": seq, "turn": 3, "phase": "MAIN1", "decisionType": "CAST_SPELL", "gameId": "g1",
            "options": [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "Sol Ring {1}"}],
            "state": {"stack": [], "manaPool": 0, "untappedManaSourceCount": 3, "life": 40}}


class StallRotation(unittest.TestCase):
    def setUp(self):
        self._orig = (brain_mod.PersistentClaude, brain_mod._run)
        brain_mod.PersistentClaude, brain_mod._run = FakePersistent, _spawn_times_out
        FakePersistent.ok = False; FakePersistent.made = []
        tmp = Path(tempfile.mkdtemp(prefix="stall-"))
        self.r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"), timeout_s=30.0)
        self.r.brain.session_id = "s-old"
        self.r.brain.persistent_enabled = True      # the suite pins ARENA_BRAIN_TRANSPORT=spawn at import
        self.r.mb.respond = lambda req, ans: True
        self.r._fastpath = lambda req: None         # this is about the transport, not the fastpaths
        self.rotations = []
        self.r.brain.rotate = lambda text, timeout_s=120.0: self.rotations.append(text) or True
        self.events = tmp / "logs" / "transport-events.jsonl"

    def tearDown(self):
        brain_mod.PersistentClaude, brain_mod._run = self._orig

    def _rotate_events(self):
        rows = [json.loads(l) for l in self.events.read_text().splitlines()] if self.events.exists() else []
        return [e for e in rows if e.get("kind") == "rotate"]

    def test_second_consecutive_stall_rotates_with_the_reason_recorded(self):
        r = self.r
        r.handle(_req(1))
        self.assertEqual(r.brain.stalls, 1)
        self.assertEqual(self.rotations, [], "one stall: the process restarts on --resume, no rotation")
        self.assertEqual(self._rotate_events(), [])
        r.handle(_req(2))
        self.assertEqual(r.brain.stalls, 2)
        self.assertEqual(len(self.rotations), 1, "the second back-to-back stall rotates")
        ev = self._rotate_events()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["reason"], ev[0]["seat"], ev[0]["gameId"]), ("stall-x2", 2, "g1"))
        self.assertTrue(any("stall-x2" in l for l in r._game_log.parent.joinpath("seat-2.log").read_text().splitlines()))
        # both windows were answered on time with the safe default, as punts
        rows = [json.loads(l) for l in r._game_log.read_text().splitlines()]
        self.assertEqual([x["source"] for x in rows], ["punt", "punt"])
        self.assertEqual(r.brain.wedges, 0, "rotation, not the wedge path: the game record is kept")

    def test_an_answered_call_between_two_stalls_resets_the_count(self):
        r = self.r
        r.handle(_req(1))
        self.assertEqual(r.brain.stalls, 1)
        FakePersistent.ok = True
        r.handle(_req(2))
        self.assertEqual(r.brain.stalls, 0, "an answer in between: the streak restarts")
        FakePersistent.ok = False
        r.handle(_req(3))
        self.assertEqual((r.brain.stalls, self.rotations), (1, []), "one stall again, no rotation")

    def test_a_forced_rotation_ignores_the_token_caps_and_a_capped_one_names_its_reason(self):
        r = self.r
        r.rotate_at, r.rotate_hard = 250_000, 600_000
        r.brain.last_prompt_tokens = 1_000
        self.assertFalse(r._maybe_rotate(), "under the cap")
        self.assertTrue(r._maybe_rotate(hard=True, reason="stall-x2"), "a reason forces it")
        r.brain.last_prompt_tokens = 300_000
        self.assertTrue(r._maybe_rotate())
        self.assertEqual([e["reason"] for e in self._rotate_events()], ["stall-x2", "turn-boundary"])
        r.brain.session_id = None
        self.assertFalse(r._maybe_rotate(hard=True, reason="stall-x2"), "no session: nothing to rotate")


class BrainRotateResetsTheStreaks(unittest.TestCase):
    def test_rotate_clears_stalls_and_the_failure_streak(self):
        tmp = Path(tempfile.mkdtemp(prefix="stall2-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        b = r.brain
        b.session_id = "s-old"; b.stalls = 2; b._fail_streak = 2; b._fail_streak_t0 = 1.0
        b._call = lambda prompt, timeout_s, resume, **k: {"session_id": "s-new", "usage": {"input_tokens": 7}}
        self.assertTrue(b.rotate("RECORD"))
        self.assertEqual((b.session_id, b.stalls, b._fail_streak, b._fail_streak_t0), ("s-new", 0, 0, None))


class FakeEnv:
    @staticmethod
    def env(session="s-new", read=0, create=0, inp=2):
        return {"session_id": session, "result": "READY",
                "usage": {"input_tokens": inp, "output_tokens": 5, "cache_read_input_tokens": read,
                          "cache_creation_input_tokens": create}}


class BrainRotationTests(unittest.TestCase):
    def test_last_prompt_tokens_and_rotate_swap_the_session(self):
        b = SeatBrain(2, "giada-font-of-hope", model="opus", effort="low", log=lambda *_: None)
        b.session_id = "s-old"
        b._accumulate(FakeEnv.env(read=300_000, create=4_000))
        self.assertEqual(b.last_prompt_tokens, 304_002)
        seen = {}

        def fake_call(prompt, timeout_s, resume, effort=None):
            seen["prompt"], seen["resume"] = prompt, resume
            return FakeEnv.env(session="s-new", read=0, create=60_000)
        b._call = fake_call
        self.assertTrue(b.rotate("## GAME SO FAR\nTurn 1"))
        self.assertFalse(seen["resume"], "a rotation is a FRESH session")
        self.assertIn("## GAME SO FAR", seen["prompt"])
        self.assertTrue(seen["prompt"].rstrip().endswith("Reply exactly: READY"))
        self.assertLess(seen["prompt"].count("Reply exactly: READY"), 2, "the READY line moves to the end, not duplicated")
        self.assertEqual(b.session_id, "s-new")
        self.assertEqual(b.rotations, 1)
        self.assertEqual(b.last_prompt_tokens, 60_002)

    def test_failed_rotation_keeps_the_old_session(self):
        b = SeatBrain(2, "giada-font-of-hope", model="opus", effort="low", log=lambda *_: None)
        b.session_id = "s-old"
        b._call = lambda *a, **k: None
        self.assertFalse(b.rotate("x"))
        self.assertEqual(b.session_id, "s-old")
        b.session_id = None
        self.assertFalse(b.rotate("x"), "no session yet: nothing to rotate")


class ExtractJson(unittest.TestCase):
    def test_mana_symbols_before_the_answer(self):
        t = ('I can pay {G}{2}{W} for this and keep {U} floating, so '
             '{"chosenId": 3, "why": "tempo"}')
        self.assertEqual(brain_mod.extract_json(t), {"chosenId": 3, "why": "tempo"})

    def test_brace_noise_after_the_answer(self):
        t = '{"chosen": [1, 2]} — leaving {R} up for Lightning Bolt {R}'
        self.assertEqual(brain_mod.extract_json(t), {"chosen": [1, 2]})

    def test_arrays_and_garbage_are_not_answers(self):
        self.assertIsNone(brain_mod.extract_json("[1, 2, 3]"))
        self.assertIsNone(brain_mod.extract_json("{G} {W} nothing here"))
        self.assertIsNone(brain_mod.extract_json(""))

    def test_plain_and_fenced_still_work(self):
        self.assertEqual(brain_mod.extract_json('{"keep": true}'), {"keep": True})
        self.assertEqual(brain_mod.extract_json('```json\n{"keep": false}\n```'), {"keep": False})


class TrackedChild(unittest.TestCase):
    def test_timeout_kills_the_child_and_raises(self):
        seen = []
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        with self.assertRaises(subprocess.TimeoutExpired):
            brain_mod._run(cmd, input="", timeout=0.3, cwd=None, on_child=seen.append)
        self.assertIsNotNone(seen[0], "child reported on start")
        self.assertIsNone(seen[-1], "child cleared on exit")
        self.assertIsNotNone(seen[0].returncode, "child is dead, not orphaned")

    def test_completed_process_contract(self):
        cmd = [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"]
        proc = brain_mod._run(cmd, input="ok", timeout=10, cwd=None)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "OK")

    def test_kill_child_is_safe_with_and_without_a_child(self):
        class FakeBrain:
            pass
        b = brain_mod.SeatBrain.__new__(brain_mod.SeatBrain)
        b._child = None
        b.kill_child()                      # no child: no-op

        class Child:
            killed = False

            def kill(self):
                self.killed = True
        c = Child()
        b._track_child(c)
        b.kill_child()
        self.assertTrue(c.killed)


class SignalHandler(unittest.TestCase):
    def test_sigterm_kills_child_and_exits(self):
        class B:
            killed = 0

            def kill_child(self):
                self.killed += 1

        class R:
            brain = B()
        r = R()
        old_term, old_int = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
        try:
            seat_runner.install_signal_handlers(r)
            handler = signal.getsignal(signal.SIGTERM)
            with self.assertRaises(SystemExit) as cm:
                handler(signal.SIGTERM, None)
            self.assertEqual(cm.exception.code, 128 + signal.SIGTERM)
            self.assertEqual(r.brain.killed, 1)
        finally:
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)
