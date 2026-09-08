"""The three low-risk steps (Ben, 2026-09-07 late):
1. PersistentClaude — one stream-json process per session (opt-in via
   ARENA_BRAIN_TRANSPORT=persistent); a timeout kills it and the brain falls
   back to the per-call --resume spawn; a different effort takes the spawn path.
2. Low effort for REACT windows holding only OTHER players' abilities with
   nothing aimed at the seat.
3. The runner publishes its yields (mailbox/seat-N/yield.json) for the engine
   mirror; the usage snapshot carries context size and rotations.
Run: python3 -m unittest discover -s tests"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seatd.brain as brain_mod  # noqa: E402
from seatd.brain import PersistentClaude, SeatBrain  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "engine"


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
            # a different effort for one call -> spawn path (per-process flag) AND the
            # live process is stopped: it holds the transcript in memory and would
            # not see the turn the spawn appends on disk (Gemini pass 2)
            b._call("low one", 10.0, resume=True, effort="low")
            self.assertEqual(len(spawned), 1, "effort mismatch goes through the spawn path")
            self.assertIn("--resume", spawned[0])
            self.assertIsNone(b._persistent, "the stale in-memory process is stopped before the spawn turn")
            # process failure -> fallback counted, spawn used
            P.call = lambda self, prompt, timeout_s: None
            b._call("again", 10.0, resume=True)
            self.assertEqual(b.persistent_fallbacks, 1); self.assertEqual(len(spawned), 2)
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


def react(**kw):
    r = json.loads((FIX / "react.json").read_text())
    st = r["state"]
    st["seat"] = 2; st["stack"] = list(kw.get("stack", ("Staff of Domination",)))
    kinds = kw.get("kinds", ("ability",)); owners = kw.get("owners", (0,))
    st["stackKinds"] = list(kinds) if kinds is not None else None
    st["stackOwners"] = list(owners) if owners is not None else None
    st["stackTargets"] = kw.get("targets", [[] for _ in st["stack"]])
    return r


class LowEffortRuleTests(unittest.TestCase):
    def test_other_players_abilities_only_and_unthreatened(self):
        tmp = Path(tempfile.mkdtemp(prefix="eff-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        self.assertTrue(r._unthreatened_ability_react(react()))
        self.assertTrue(r._unthreatened_ability_react(react(stack=("A", "B"), kinds=("trigger", "ability"), owners=(0, 3))))
        self.assertFalse(r._unthreatened_ability_react(react(kinds=("spell",))), "a spell is a full question")
        self.assertFalse(r._unthreatened_ability_react(react(owners=(2,))), "our own item: the own-trigger rule owns that")
        self.assertFalse(r._unthreatened_ability_react(react(targets=[["seat 2"]])), "aimed at us")
        self.assertFalse(r._unthreatened_ability_react(react(stack=(), kinds=(), owners=())), "empty stack")
        self.assertFalse(r._unthreatened_ability_react(react(kinds=None)), "missing metadata fails open")
        oracle = react()
        oracle["state"]["stackOracle"] = ["When Thassa's Oracle enters, look at the top X cards … you win the game."]
        self.assertFalse(r._unthreatened_ability_react(oracle), "a game-deciding ability is a full-effort question")
        os.environ["ARENA_REACT_LOW_EFFORT"] = "off"
        try:
            self.assertFalse(r._unthreatened_ability_react(react()))
        finally:
            os.environ.pop("ARENA_REACT_LOW_EFFORT", None)


class YieldPublishAndVisibilityTests(unittest.TestCase):
    def test_yields_are_published_for_the_engine_mirror(self):
        tmp = Path(tempfile.mkdtemp(prefix="pub-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        req = react()
        req["turn"] = 23
        req["state"]["life"] = 21; req["state"]["manaPool"] = 0; req["state"]["untappedManaSourceCount"] = 0
        req["options"] = [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "The One Ring  {T} — draw"}]
        r._note_yield(req, {"chosenId": 0})
        f = Path(tmp) / "seat-2" / "yield.json"
        self.assertTrue(f.exists(), "yield.json written next to the seat's inbox")
        body = json.loads(f.read_text())
        self.assertEqual(body["seat"], 2)
        item = body["items"][0]
        self.assertEqual((item["turn"], item["name"], item["owner"], item["kind"]), (23, "Staff of Domination", 0, "ability"))
        self.assertEqual(item["options"], ["The One Ring"])
        self.assertEqual((item["life"], item["pool"], item["untapped"]), (21, 0, 0))

    def test_usage_snapshot_carries_context_and_rotations(self):
        tmp = Path(tempfile.mkdtemp(prefix="vis-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        r.brain.last_prompt_tokens = 123_456; r.brain.rotations = 2
        req = react(); req["seq"] = 1; req["turn"] = 1
        r._record(req, {"chosenId": 0}, "memo", why="t")
        rec = json.loads((tmp / "logs" / "seat-2.jsonl").read_text().splitlines()[-1])
        self.assertEqual(rec["cum"]["last_prompt_tokens"], 123_456)
        self.assertEqual(rec["cum"]["rotations"], 2)


if __name__ == "__main__":
    unittest.main()


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
