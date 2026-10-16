"""Five-lens round two, Maintainer M1 + BL-59 (2026-10-16).

M1: the CLI's `total_cost_usd` is a running LEDGER, not a turn's cost — the
archives summed it on every result and were up to 70x over. A persistent
process's results rise from the ledger the `--resume` restored (the total the
last cleanly-exited one-shot saved into the transcript), so the per-call figure
is the delta from a seeded base; a `--resume` one-shot reports saved + call.
Measured on CLI 2.1.300 (2026-10-16) and reviewed by two Opus agents.

BL-59: the transport reports the CONCRETE model id; records and the Elo
ladder key on it, the launch alias rides along.

Run: python3 -m unittest discover -s tests"""
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd import brain as brain_mod  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402


class _FakeProc:
    """Enough of a Popen for PersistentClaude: a writable stdin, an stdout at
    EOF (the reader thread exits at once), alive until killed."""

    def __init__(self):
        self.stdin = self
        self.stdout = self
        self.written = []
        self.dead = False

    def write(self, s):
        self.written.append(s)

    def flush(self):
        pass

    def readline(self):
        return ""

    def poll(self):
        return 1 if self.dead else None

    def kill(self):
        self.dead = True

    def wait(self, timeout=None):
        return 1

    def close(self):
        pass


INIT = {"type": "system", "subtype": "init", "model": "claude-opus-5-5",
        "claude_code_version": "2.1.300", "cwd": "/x"}


def result(total, out=4, model="claude-opus-5-5", error=False):
    return {"type": "result", "subtype": "error" if error else "success", "is_error": error,
            "result": "{}", "session_id": "sess-1", "num_turns": 1,
            "usage": {"input_tokens": 2, "output_tokens": out,
                      "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0},
            "total_cost_usd": total,
            "modelUsage": {model: {"inputTokens": 2, "outputTokens": out, "costUSD": total,
                                   "canonicalModel": model}}}


def persistent_with(events, base=0.0, log=None):
    p = brain_mod.PersistentClaude(["claude", "-p", "-"], "sess-1", ".", log or (lambda *a: None))
    p.cost_base = base
    p.cost_seen = base               # what start() does
    p.proc = _FakeProc()
    p._q = queue.Queue()
    for ev in events:
        p._q.put(json.dumps(ev) + "\n")
    return p


class CostDelta(unittest.TestCase):

    def test_each_result_carries_the_turns_delta_not_the_running_total(self):
        p = persistent_with([INIT, result(0.5), result(1.2), result(1.2)])
        e1, e2, e3 = (p.call("a", 5), p.call("b", 5), p.call("c", 5))
        self.assertEqual((e1["cost_usd_call"], e2["cost_usd_call"], e3["cost_usd_call"]), (0.5, 0.7, 0.0))
        self.assertEqual(e3["total_cost_usd"], 1.2, "the CLI's own figure is reported untouched")
        self.assertEqual((p.model_id, p.cli_version), ("claude-opus-5-5", "2.1.300"))

    def test_a_resumed_process_starts_at_the_ledger_the_transcript_saved(self):
        # the init one-shot cost 0.4618 and saved it; the process's first result is 0.4618 + the turn
        p = persistent_with([result(0.4618 + 0.1015), result(0.4618 + 0.1015 + 0.3)], base=0.4618)
        self.assertAlmostEqual(p.call("a", 5)["cost_usd_call"], 0.1015, places=6)
        self.assertAlmostEqual(p.call("b", 5)["cost_usd_call"], 0.3, places=6)

    def test_start_reseeds_from_the_base_not_from_the_dead_processes_total(self):
        p = persistent_with([result(0.9)], base=0.4)
        p.call("a", 5)
        self.assertAlmostEqual(p.cost_seen, 0.9)
        # the same object restarts its process (call() does this on a dead proc): the new
        # process restores the SAVED ledger again, not the killed process's running total
        p._spawn = lambda: _FakeProc()
        self.assertTrue(p.start())
        self.assertAlmostEqual(p.cost_seen, 0.4)
        p.kill()

    def test_an_error_result_leaves_the_ledger_alone(self):
        p = persistent_with([result(0.3), result(0.0, error=True), result(0.5)])
        self.assertAlmostEqual(p.call("a", 5)["cost_usd_call"], 0.3)
        err = p.call("b", 5)
        self.assertNotIn("cost_usd_call", err)
        self.assertAlmostEqual(p.call("c", 5)["cost_usd_call"], 0.2, msg="the error turn's cost lands in the next real result")

    def test_a_ledger_below_the_seed_counts_the_raw_figure_and_says_so_once(self):
        lines = []
        p = persistent_with([result(0.3), result(0.35)], base=2.0, log=lines.append)
        self.assertAlmostEqual(p.call("a", 5)["cost_usd_call"], 0.3)
        self.assertAlmostEqual(p.call("b", 5)["cost_usd_call"], 0.05)
        self.assertEqual(sum("below the seeded" in l for l in lines), 1)

    def test_a_result_without_a_cost_is_passed_through(self):
        ev = dict(result(0.1))
        del ev["total_cost_usd"]
        p = persistent_with([ev])
        self.assertNotIn("cost_usd_call", p.call("x", 5))


def bare_brain(model="opus"):
    b = brain_mod.SeatBrain.__new__(brain_mod.SeatBrain)
    b.seat = 1
    b.model = model
    b.model_id = None
    b.cli_version = None
    b._cli_saved_cost = 0.0
    b.last_prompt_tokens = 0
    b.totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cost_usd": 0.0}
    b.backend = None
    b._parked_backend = None
    b.session_id = None
    b.log = lambda *a: None
    return b


class BrainAccumulate(unittest.TestCase):

    def test_prefers_the_per_call_figure_over_the_running_total(self):
        b = bare_brain()
        env = result(1.2)
        env["cost_usd_call"] = 0.7          # what PersistentClaude.call / the spawn path add
        b._accumulate(env)
        b._accumulate({"usage": {}, "total_cost_usd": 0.3})   # a backend envelope: total IS the request
        self.assertAlmostEqual(b.totals["cost_usd"], 1.0)
        self.assertEqual(b.totals["calls"], 2)

    def test_model_id_comes_from_model_usage_and_the_alias_stays(self):
        b = bare_brain("opus")
        b._accumulate(result(0.1))
        self.assertEqual(b.model_id, "claude-opus-5-5")
        self.assertEqual(b.resolved_model, "claude-opus-5-5")
        self.assertEqual(b.model, "opus", "the launch alias is kept for the banner and the control file")

    def test_the_persistent_processs_own_model_wins_over_a_cumulative_model_usage(self):
        b = bare_brain("sonnet")
        env = result(0.2)                                     # modelUsage still names the old opus
        env["model_id_hint"] = "claude-sonnet-5"              # the process's init event after a re-dial
        b._accumulate(env)
        self.assertEqual(b.model_id, "claude-sonnet-5")

    def test_model_usage_prefers_the_alias_family_then_the_most_output(self):
        b = bare_brain("sonnet")
        env = result(0.2)
        env["modelUsage"] = {"claude-opus-5-5": {"outputTokens": 9000, "canonicalModel": "claude-opus-5-5"},
                             "claude-sonnet-5": {"outputTokens": 40}}
        b._accumulate(env)
        self.assertEqual(b.model_id, "claude-sonnet-5", "a restored ledger keeps the old model's bulk")
        b2 = bare_brain("opus")
        b2._accumulate(env)
        self.assertEqual(b2.model_id, "claude-opus-5-5")

    def test_unresolved_brain_reports_its_alias(self):
        b = bare_brain("opus")
        self.assertEqual(b.resolved_model, "opus")
        b._accumulate({"usage": {}, "total_cost_usd": 0.0})
        self.assertIsNone(b.model_id)

    def test_a_model_redial_forgets_the_resolved_id(self):
        b = bare_brain("opus")
        b._accumulate(result(0.1))
        b.set_model("sonnet")
        self.assertIsNone(b.model_id)
        self.assertEqual(b.resolved_model, "sonnet")


# ---------------------------------------------------------------------------
# End to end: the real SeatBrain and the real PersistentClaude against a fake
# CLI that keeps the ledger the way CLI 2.1.300 does. Both reviewers asked for
# this: the unit tests fill cost_usd_call in by hand; this one proves the brain
# and the process hand it over, across a fallback, a restart, a rotation and a
# note, and that the sum equals the sum of the calls that answered.
# ---------------------------------------------------------------------------
class _Ledger:
    """The transcript's saved total and the scripted cost of each call, in order."""

    def __init__(self, costs):
        self.costs = list(costs)
        self.saved = 0.0
        self.sessions = 0
        self.answered = []

    def take(self):
        c = self.costs.pop(0)
        self.answered.append(c)
        return c


class _FakeCliProc:
    """A persistent `claude` process: restores the saved ledger on --resume,
    never saves (we kill it). A prompt containing DIE closes its output."""

    def __init__(self, ledger, resumed, session=None):
        self.ledger = ledger
        self.session = session
        self.running = ledger.saved if resumed else 0.0
        self._out = queue.Queue()
        self._dead = False
        self.stdin = self
        self.stdout = self
        self._out.put(json.dumps(INIT) + "\n")

    def write(self, s):
        msg = json.loads(s)
        text = msg["message"]["content"]
        if "DIE" in text:
            self._dead = True
            self._out.put("")            # EOF: the CLI went away
            return
        self.running += self.ledger.take()
        ev = result(self.running)
        if self.session:
            ev["session_id"] = self.session          # a resumed process reports the session it holds
        self._out.put(json.dumps(ev) + "\n")

    def flush(self):
        pass

    def readline(self):
        return self._out.get()

    def poll(self):
        return 1 if self._dead else None

    def kill(self):
        if not self._dead:
            self._dead = True
            self._out.put("")

    def wait(self, timeout=None):
        return 1

    def close(self):
        pass


class EndToEnd(unittest.TestCase):

    def setUp(self):
        self.ledger = _Ledger([0.4618, 0.1015, 0.3, 0.07, 0.2, 0.5, 0.1, 0.02])
        ledger = self.ledger

        def fake_run(cmd, input=None, timeout=None, cwd=None, on_child=None):
            resumed = "--resume" in cmd
            total = (ledger.saved if resumed else 0.0) + ledger.take()
            ledger.saved = total                      # a one-shot saves on its clean exit
            if not resumed:
                ledger.sessions += 1
            env = result(total)
            env["session_id"] = f"sess-{ledger.sessions}"
            return subprocess.CompletedProcess(cmd, 0, json.dumps(env), "")

        def fake_spawn(pc):
            resumed = "--resume" in pc.cmd
            session = pc.cmd[pc.cmd.index("--resume") + 1] if resumed else None
            return _FakeCliProc(ledger, resumed=resumed, session=session)

        self._orig = (brain_mod._run, brain_mod.PersistentClaude._spawn)
        brain_mod._run = fake_run
        brain_mod.PersistentClaude._spawn = fake_spawn
        tmp = Path(tempfile.mkdtemp(prefix="cost-e2e-"))
        self.r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"), timeout_s=30.0)
        self.brain = self.r.brain
        self.brain.persistent_enabled = True          # the suite pins ARENA_BRAIN_TRANSPORT=spawn at import
        self.brain.model = "opus"

    def tearDown(self):
        self.brain.stop_persistent()
        brain_mod._run, brain_mod.PersistentClaude._spawn = self._orig

    def _ask(self, text):
        answer, meta = self.brain.decide(text, deadline=time.time() + 120)
        return answer, meta

    def test_dollars_equal_the_calls_that_answered_across_every_transport_event(self):
        b = self.brain
        self.assertTrue(b.ensure_session(timeout_s=30))           # init one-shot: 0.4618, saved
        self.assertEqual(b.session_id, "sess-1")
        self._ask("d1")                                            # process 1 resumes at 0.4618: +0.1015
        self._ask("d2")                                            # +0.3
        self.assertEqual(b.persistent_calls, 2)
        self._ask("DIE then answer")                               # the process closes; fallback spawn --resume: 0.4618+0.07 saved
        self.assertEqual(b.persistent_fallbacks, 1)
        self._ask("d3")                                            # process 2 resumes at 0.5318: +0.2
        self.assertTrue(b.rotate("the record", timeout_s=30))      # one-shot, fresh session: 0.5 saved
        self.assertEqual(b.session_id, "sess-2")
        self._ask("d4")                                            # process 3 resumes at 0.5: +0.1
        self.assertTrue(b.note("hand-off"))                        # +0.02
        self.assertEqual(self.ledger.costs, [], "every scripted call answered")
        self.assertAlmostEqual(b.totals["cost_usd"], round(sum(self.ledger.answered), 6), places=6)
        self.assertAlmostEqual(b.totals["cost_usd"], 1.7533, places=4)
        self.assertEqual(b.totals["calls"], 8)
        self.assertEqual(b.resolved_model, "claude-opus-5-5")
        self.assertEqual(b.cli_version, "2.1.300")
        # and the seat's record carries the id, the alias, and the basis marker
        req = {"gameId": "g1", "seq": 9, "turn": 3, "phase": "MAIN1", "decisionType": "CAST_SPELL",
               "options": [{"id": 0, "label": "pass"}], "state": {}}
        self.r._record(req, {"chosenId": 0}, "model", meta={"latency_s": 1.0, "usage": {}})
        rec = json.loads(Path(self.r._jsonl_path).read_text().splitlines()[-1])
        self.assertEqual((rec["model"], rec["model_alias"]), ("claude-opus-5-5", "opus"))
        self.assertEqual((rec["cum"]["model_id"], rec["cum"]["cost_basis"]), ("claude-opus-5-5", "per-call"))
        self.assertAlmostEqual(rec["cum"]["cost_usd"], 1.7533, places=4)


if __name__ == "__main__":
    unittest.main()
