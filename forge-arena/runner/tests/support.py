"""Shared doubles for the runner suite (consolidation, 2026-11-07).

One copy each of the fakes nine files used to carry: the fake monotonic clock, a
silent WAV, a CompletedProcess stand-in for `seatd.brain._run`, the advisor-side
fake brain, and the seat-side scripted brain, mailbox and engine-free runner.
Builders that shape a REQUEST stay beside the tests that read them.
"""
import io
import json
import tempfile
import wave
from pathlib import Path

from seatd import runner as runner_mod
from seatd.runner import SeatRunner


class Clock:
    """A fake monotonic clock: `clock()` reads `clock.t`; a test moves it by hand."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def silent_wav(seconds: float = 0.2, rate: int = 22050) -> bytes:
    """A mono 16-bit WAV of silence in the runner's format (22.05 kHz unless told otherwise)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class Proc:
    """What `seatd.brain._run` returns: a CompletedProcess with stdout, returncode and stderr."""

    def __init__(self, stdout, returncode: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def envelope(session: str, result: str = '{"chosenId": 0}') -> str:
    """A `claude -p --output-format json` envelope, as the CLI prints it."""
    return json.dumps({"session_id": session, "result": result,
                       "usage": {"input_tokens": 1, "output_tokens": 1,
                                 "cache_read_input_tokens": 100,
                                 "cache_creation_input_tokens": 0},
                       "total_cost_usd": 0.0, "is_error": False})


def seat_runner(seat: int = 2, deck: str = "giada-font-of-hope", prefix: str = "seat-", **kw) -> SeatRunner:
    """A real SeatRunner (its dossier from decks/, its brain unstarted) in a fresh temp mailbox."""
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    return SeatRunner(seat, deck, str(tmp), log_dir=str(tmp / "logs"), **kw)


# ---- the advisor side ----------------------------------------------------------------

class AdvisorFakeBrain:
    """The advisor runner's brain, scripted: one fixed `reply`, every prompt kept.
    `advisor_brain(reply)` makes a subclass with its own reply for `ar.SeatBrain = ...`."""
    REPLY = "advice text"
    last_prompt_tokens = 0
    backend = None
    wedges = 0
    calls = 0

    def __init__(self, *a, **kw):
        self.deck, self.model, self.effort = "giada-font-of-hope", "opus", "low"
        self.session_id = "sess-1"
        self.totals = {"calls": 0}
        self.reply = self.REPLY
        self.decisions = []                 # every prompt, in order (`prompts` is the same list)
        self.prompts = self.decisions
        self.last_prompt = None
        self.resets = 0
        self.notes = []
        self.rotated = 0

    def reset(self):
        self.resets += 1

    def ensure_session(self, *a, **kw):
        return True

    def note(self, text, timeout_s=60.0):
        self.notes.append(text)
        return True

    def rotate(self, text, timeout_s=120.0):
        self.rotated += 1
        return True

    def decide(self, prompt, timeout=None, **kw):
        self.decisions.append(prompt)
        self.last_prompt = prompt
        return {}, {"raw": self.reply, "latency_s": 0.1}


def advisor_brain(reply: str):
    return type("FakeBrain", (AdvisorFakeBrain,), {"REPLY": reply})


# ---- the seat side -------------------------------------------------------------------

class FakeMailbox:
    """A seat mailbox with no engine behind it: answers are kept, never consumed."""
    game_reset = False

    def __init__(self, seat_dir: Path | None = None):
        self.responses = []
        self.inbox = Path("/nonexistent")     # no req file: the runner keeps its window
        self.dir = seat_dir                   # notes/ lives under the mailbox dir when given

    def respond(self, req, answer):
        self.responses.append((req.get("seq"), answer))
        return True

    def read_observer(self):
        return None


class ScriptBrain:
    """A seat brain that hands out scripted answers in order (then passes), keeping every prompt."""
    effort = "low"
    model = "opus"

    def __init__(self, script=()):
        self.script = list(script)
        self.calls = 0
        self.prompts = []
        self.last_prompt = None

    def decide(self, prompt, timeout_s=None, effort=None, deadline=None):
        self.calls += 1
        self.prompts.append(prompt)
        self.last_prompt = prompt
        out = self.script.pop(0) if self.script else {"chosenId": 0}
        return out, {"latency_s": 0.01, "usage": None, "cache_read": 1, "raw": json.dumps(out)}

    def reset(self):
        pass


def fake_seat_runner(seat: int = 3, deck: str = "urza-lord-high-artificer") -> SeatRunner:
    """A SeatRunner around FakeMailbox + ScriptBrain with no engine, model or dossier: the loop
    state, a captured `_say` (`r.log_lines`), a captured `_record` (`r.records`), and the log
    paths a punt's bookkeeping needs. `r.brain.script = [...]` scripts the answers."""
    tmp = Path(tempfile.mkdtemp(prefix="fake-seat-"))
    r = runner_mod.SeatRunner.__new__(runner_mod.SeatRunner)
    r.seat, r.deck = seat, deck
    r.mb = FakeMailbox(tmp / f"seat-{seat}")
    r.brain = ScriptBrain()
    r.timeout_s = 90.0
    r.speculative = r.react_hold = False
    r.autopass = ()
    r.plan = r.hold = r.turn_intent = r.combos = None
    r.react_seen, r.order_memo = set(), {}
    r.cycle, r._hist, r._last_turn = None, [], None
    r._init_loop_state()      # D4: __init__ owns the loop state; a __new__ runner sets it here
    r._deviation = None
    r.log_lines = []
    r._say = r.log_lines.append
    r.records = []
    r._record = lambda req, answer, source, meta=None, **k: r.records.append((req.get("seq"), answer, source, k))
    r._seen_seq = set()
    (tmp / "logs").mkdir()
    r._game_log = tmp / "logs" / "game.jsonl"
    r._jsonl_path = tmp / "logs" / f"seat-{seat}.jsonl"
    return r
