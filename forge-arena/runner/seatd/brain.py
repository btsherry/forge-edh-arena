"""The model transport: one resident headless-`claude` session per seat.

Subscription mandate (docs/AGENT-SDK-SEATS.md): the model runs on the user's
own `claude` login via documented headless mode — no API key, no API billing.

Pattern (verified live 2026-08-07):
- init: send rules card + seat brief + FULL dossier + primer as the first
  message of a fresh session; capture `session_id` from --output-format json.
- per decision: `claude -p - --resume <session_id> ...` with the decision
  prompt on stdin; the session carries the dossier (cache-hit on resume —
  `usage.cache_read_input_tokens` observed > 0 across resumes).
- tools are disabled (--disallowedTools '*'); the model is text-in/text-out.
  Exception: an `allowed_tools` allowlist (the advisor's public-state dump).
  The runner does ALL file I/O — the model can never touch a mailbox path.

Every call returns (parsed_json_or_None, meta). Callers validate via rules.py
and fall back to rules.safe_default() — never trust, never retry past the
deadline.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import backends

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


WEDGE_FAILS = 3          # consecutive failed calls ...
WEDGE_SECONDS = 60.0     # ... spanning at least this long => wedged
WEDGE_HARD_FAILS = 6     # or this many in a row regardless of time
REJOIN_NOTE = ("[SESSION NOTE] Your previous session for this game was lost "
               "(transport failure) and this is a FRESH session mid-game. You "
               "have no memory of earlier turns: trust the board/state in each "
               "decision as authoritative, re-derive your plan from what is on "
               "the battlefield, in your hand and on the stack, and re-state a "
               "turn_plan when you next have priority.]\n\n")


def extract_json(text: str) -> dict | None:
    """Best-effort extraction of the answer object from model text."""
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.strip()
    try:
        out = json.loads(t)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        pass
    m = _FENCE_RE.search(t)  # the brief forbids fences, but belt-and-suspenders
    if m:
        try:
            out = json.loads(m.group(1))
            return out if isinstance(out, dict) else None
        except json.JSONDecodeError:
            pass
    # BL-27: walk every "{" with raw_decode until an object parses. The old
    # first-"{"-to-last-"}" slice broke on mana symbols in prose ("{G}{2}{W}
    # ... {"chosenId": 3}") and turned a usable answer into a punt.
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch != "{":
            continue
        try:
            out, _ = dec.raw_decode(t, i)
        except json.JSONDecodeError:
            continue
        if isinstance(out, dict):
            return out
    return None


def _run(cmd, *, input, timeout, cwd, on_child=None):
    """subprocess.run's contract (CompletedProcess or TimeoutExpired) with a
    TRACKED child (BL-28): `on_child(proc)` is called when the child starts
    and `on_child(None)` when it is gone, so the seat's signal handler can
    kill an in-flight CLI call instead of orphaning it at teardown. Tests
    monkeypatch this function, never subprocess itself."""
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, cwd=cwd)
    if on_child is not None:
        on_child(child)
    try:
        out, err = child.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        # kill, then wait() — never communicate(): a grandchild that inherited
        # the pipes would keep communicate() blocked with no timeout (CPython's
        # subprocess.run does exactly this on POSIX for the same reason)
        child.kill()
        child.wait()
        raise
    finally:
        if on_child is not None:
            on_child(None)
    return subprocess.CompletedProcess(cmd, child.returncode, out, err)


class PersistentClaude:
    """One long-lived `claude -p --input-format stream-json --output-format
    stream-json` process holding ONE session (Ben's step 1, 2026-09-07). Each
    decision is one user message in; we read events until the `result` line
    and return it shaped like the `--output-format json` envelope (result,
    session_id, usage, is_error, total_cost_usd). Same session, same reads,
    no per-call process spawn. Probe 2026-09-07: turn 2 in one process 1.0 s
    vs 2.5 s cold; cache is ephemeral_1h.

    Reading: a daemon thread drains stdout line by line into a queue (a
    buffered text pipe must never be mixed with select()); call() consumes
    the queue with a deadline. A timeout kills the process (never a hung
    read); any failure marks it dead and the brain falls back to the per-call
    --resume spawn on the SAME session id, so the transcript is never lost.
    Model/effort are per-process flags, so a call at a different effort goes
    through the spawn path instead."""

    def __init__(self, cmd_base: list[str], session_id: str | None, cwd: str, log,
                 stderr_path: str | None = None):
        self.cmd = list(cmd_base) + (["--resume", session_id] if session_id else [])
        self.cmd += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        self.cwd = cwd
        self.log = log
        self.stderr_path = stderr_path   # Gemini pass 2 (P1): an undrained stderr pipe would block the CLI
        self.proc = None
        self.turns = 0
        self._q = None
        self._reader = None
        self._err = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self):
        err = subprocess.DEVNULL
        if self.stderr_path:
            try:
                Path(self.stderr_path).parent.mkdir(parents=True, exist_ok=True)
                self._err = open(self.stderr_path, "ab")   # append: kept for post-game inspection
                err = self._err
            except OSError:
                err = subprocess.DEVNULL
        return subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=err, text=True, cwd=self.cwd)

    def start(self) -> bool:
        import queue
        import threading
        try:
            self.proc = self._spawn()
        except OSError as e:
            self.log(f"persistent claude launch failed: {e}")
            self.proc = None
            return False
        self._q = queue.Queue()
        proc, q = self.proc, self._q

        def drain():
            try:
                for line in iter(proc.stdout.readline, ""):
                    q.put(line)
            except (OSError, ValueError):
                pass
            q.put(None)   # EOF marker

        self._reader = threading.Thread(target=drain, name="claude-stream-reader", daemon=True)
        self._reader.start()
        return True

    def kill(self) -> None:
        p = self.proc
        self.proc = None
        if p is None:
            return
        try:
            p.kill()
            p.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for stream in (getattr(p, "stdin", None), getattr(p, "stdout", None), self._err):
            close = getattr(stream, "close", None)
            try:
                if close is not None:
                    close()
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass
        self._err = None

    def call(self, prompt: str, timeout_s: float) -> dict | None:
        """One turn. None on any failure (the process is then dead)."""
        import queue
        if not self.alive() and not self.start():
            return None
        msg = json.dumps({"type": "user", "message": {"role": "user", "content": prompt}})
        try:
            self.proc.stdin.write(msg + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as e:
            self.log(f"persistent claude write failed: {e}")
            self.kill()
            return None
        deadline = time.time() + timeout_s
        while True:
            left = deadline - time.time()
            if left <= 0:
                self.log(f"persistent claude call timed out ({timeout_s:.0f}s) — process killed")
                self.kill()
                return None
            try:
                line = self._q.get(timeout=min(left, 1.0))
            except queue.Empty:
                # a process that exited closes its stdout: the reader posts the
                # EOF marker (None) below — never abort on poll() alone, the
                # final result line may still be in flight (Gemini pass 2, P2)
                continue
            if line is None:
                self.log("persistent claude closed its output")
                self.kill()
                return None
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("type") == "result":
                self.turns += 1
                return ev


class SeatBrain:
    """One resident model session for one seat."""

    def __init__(self, seat: int, deck: str, model: str = "sonnet",
                 effort: str = "low", repo_root: str | Path | None = None,
                 log=print, brief: str = "seat-brief.md",
                 extra_parts: list[str] | None = None,
                 allowed_tools: list[str] | None = None):
        self.seat = int(seat)
        # Tools are disabled for every brain ("--disallowedTools *"); the
        # ADVISOR alone may be handed an allowlist (2026-09-07, Ben): the
        # public-state dump script. Seats never get one — their state is the
        # request, and a tool would be a second, unaudited channel.
        self.allowed_tools = list(allowed_tools) if allowed_tools else None
        self.deck = deck
        self.model = model
        self.effort = effort  # pinned — never inherit the user's saved default
        self.log = log
        # session_id is CLAUDE session state only. Backend transports keep
        # their own transcript on self.backend, and backend envelopes never
        # carry a session_id, so a backend detour can neither poison nor
        # discard a live Claude session (plan F-01 / Gemini r3-1).
        self.session_id: str | None = None
        self.backend = backends.make(model, seat=self.seat, log=log)
        self._parked_backend = None  # held across a detour for a warm return
        # Backend failure latches, runner-lifetime by design (plan F-09):
        # auth-class keyed by base URL (never cleared mid-session — the env
        # is frozen at spawn, so a re-dial can't fix a bad key); model-class
        # keyed by model id (cleared per game in reset()).
        self.backend_latches: dict = {"auth": {}, "model": {}}
        self.calls = 0
        # Wedged-session recovery (game 7, 2026-08-17): Giada's resident
        # session went dark for 11 min (timeouts, then upstream 500s on that
        # one conversation) and Urza's mid-combo; the runner just re-resumed
        # the wedged session forever, punting to safe defaults. After
        # WEDGE_FAILS consecutive failures spanning >= WEDGE_SECONDS (fast
        # exit-1 bursts alone don't count — a 15s blip should not cost the
        # game memory), or WEDGE_HARD_FAILS regardless of time, drop --resume
        # and re-init a fresh session with the dossier at the next decision.
        self._fail_streak = 0
        self._fail_streak_t0: float | None = None
        self._rejoin_pending = False
        self.wedges = 0  # lifetime count; the runner mirrors these into
                         # transport-events.jsonl for the ratings void check
        self._child = None  # the in-flight CLI process, for kill_child (BL-28)
        # Cumulative burn since instantiation (includes the dossier init call).
        self.totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                       "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0, "cost_usd": 0.0}
        # Session rotation (Ben, 2026-09-07): the prompt size of the LAST call
        # (input + cache read + cache creation = the whole transcript the
        # model re-read). The runner rotates the session when it passes a cap.
        self.last_prompt_tokens = 0
        self.rotations = 0
        # Step 1: ARENA_BRAIN_TRANSPORT=persistent (DEFAULT since 2026-09-08,
        # Ben, after games 26-27: 285 calls, 4 fallbacks, 0 stalls of its own)
        # keeps one CLI process per session; "spawn" is the per-call --resume.
        self.persistent_enabled = os.environ.get("ARENA_BRAIN_TRANSPORT", "persistent").lower() == "persistent"
        self._persistent: PersistentClaude | None = None
        self._persistent_key: tuple | None = None   # (model, effort) the process was started with
        self.persistent_calls = 0
        self.persistent_fallbacks = 0
        root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
        self.root = root  # session storage is cwd-scoped: keep every call here
        here = Path(__file__).parent
        docs = root / "forge-arena" / "docs"
        dossier_p = root / "forge-arena" / "decks" / deck / "dossier" / "deck-cards.json"
        primer_p = docs / "primers" / f"{deck}-deckcheck.md"
        parts = [
            (here / brief).read_text(),
            # The project's real rules corpus (CR-cited), not a summary of a
            # summary: the game-pilot digest + the win-execution digest.
            (docs / "research" / "mtg-rules-summary.md").read_text(),
            (docs / "research" / "mtg-rules-digest-conversion.md").read_text(),
            f"\n## You are SEAT {self.seat}, playing the deck: {deck}\n",
            "## DECK DOSSIER (full oracle text — never summarized)\n",
            dossier_p.read_text(),  # fat context is REQUIRED (field note 1)
        ]
        # Ship-pattern combo knowledge: the CommanderSpellbook included-combos
        # distillation ONLY (pieces, zone requirements, prerequisites, steps,
        # produces). Project-internal artifacts (combo-program-*.json,
        # advisory-combos.json) are deliberately NOT ingested — the shipped
        # arena-add-deck pipeline won't have them.
        combos_p = dossier_p.parent / "combos.json"
        if combos_p.exists():
            parts += ["\n## DECK COMBOS (CommanderSpellbook — real combos in "
                      "THIS 100; know them, assemble them, execute them)\n",
                      combos_p.read_text()]
        if primer_p.exists():
            parts += ["\n## STRATEGY PRIMER\n", primer_p.read_text()]
        # Caller-supplied context (e.g. the ADVISOR reads every deck at the
        # table — an observer teaches better knowing the pod; seat brains
        # never get this, their fairness contract keeps opponents' lists dark).
        if extra_parts:
            parts += extra_parts
        parts.append("\nReply exactly: READY")
        self._init_message = "\n".join(parts)

    # ---- transport -----------------------------------------------------------

    def set_model(self, model: str) -> None:
        """Apply a (possibly transport-changing) model re-dial. Per-transport
        session state: the Claude session_id and any backend transcript are
        BOTH preserved across a switch — a detour is a detour, not a divorce.
        Cost totals and latches are never touched here (plan §4)."""
        old_kind, _ = backends.parse_model(self.model)
        new_kind, new_id = backends.parse_model(model)
        self.model = model
        if new_kind == old_kind:
            if self.backend is not None and new_id != self.backend.model_id:
                self.backend.model_id = new_id   # or/->or/: transcript kept,
                self.backend._meta = None        # per-call id updated
            return
        if self.backend is not None:
            self._parked_backend = self.backend
        if new_kind == "claude":
            self.backend = None
            self.log(f"[seat {self.seat}] transport -> claude cli "
                     f"(claude session {'resumes' if self.session_id else 'cold'})")
            return
        parked = self._parked_backend
        if (parked is not None and parked.kind == new_kind
                and parked.model_id == new_id):
            self.backend, self._parked_backend = parked, None
            self.log(f"[seat {self.seat}] transport -> {new_kind} "
                     f"(transcript resumed, no re-init)")
        else:
            self.backend = backends.make(model, seat=self.seat, log=self.log)
            self.log(f"[seat {self.seat}] transport -> {new_kind} "
                     f"(cold start — init payload re-sends at next decision)")

    def _call(self, prompt: str, timeout_s: float, resume: bool,
              effort: str | None = None) -> dict | None:
        """One headless call. Returns the parsed --output-format json envelope
        (NOT the answer), or None on failure/timeout. `effort` overrides the
        seat effort for THIS call only (resourceless-window routing)."""
        eff = effort or self.effort
        if self.backend is not None:
            return self.backend.call(prompt, timeout_s, self, effort=eff)
        # --strict-mcp-config + empty --mcp-config: the seat has every tool
        # disallowed, yet by default the CLI still connects the user's whole
        # MCP roster (9 servers on Ben's box) on every spawn — measured at
        # ~3.3s of the ~6s per-call floor (2026-08-17 pace study). Skipping
        # it changes nothing the model can see or do; --disallowedTools "*"
        # already made those servers inert.
        # --setting-sources "" (BL-24): no user/project settings, hooks or
        # plugins load into a brain call — model and effort are passed
        # explicitly, so nothing from those files is needed. (CLAUDE.md
        # auto-discovery is NOT affected by this flag; see the README note.)
        cmd = ["claude", "-p", "-", "--output-format", "json",
               "--model", self.model, "--effort", eff]
        if self.allowed_tools:
            # print mode denies every tool not on the allowlist without asking
            for pattern in self.allowed_tools:
                cmd += ["--allowedTools", pattern]
        else:
            cmd += ["--disallowedTools", "*"]   # golden argv (test_golden_claude): order is fixed
        cmd += ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", ""]
        if resume and self.session_id and self.persistent_enabled:
            t_p = time.time()
            env_p = self._persistent_call(cmd, prompt, timeout_s, eff)
            if env_p is not None:
                return None if env_p.get("__error__") else env_p
            # fell through: the process is dead or unsuitable -> per-call spawn
            # below, with ONLY the time that remains of this window. Game 26
            # (2026-09-08): a persistent timeout followed by a full-length spawn
            # wait cost 144 s per window and lost it twice; after a timeout
            # nothing remains, so the seat punts at once instead.
            timeout_s = timeout_s - (time.time() - t_p)
            if timeout_s < self.MIN_CALL_S:
                self.log(f"[seat {self.seat}] persistent call used the window "
                         f"({timeout_s:.0f}s left) — no spawn retry")
                return None
        if resume and self.session_id:
            cmd += ["--resume", self.session_id]
        try:
            proc = _run(cmd, input=prompt, timeout=timeout_s, cwd=str(self.root),
                        on_child=self._track_child)
        except subprocess.TimeoutExpired:
            self.log(f"[seat {self.seat}] model call timed out ({timeout_s:.0f}s)")
            return None
        except OSError as e:
            self.log(f"[seat {self.seat}] claude launch failed: {e}")
            return None
        if proc.returncode != 0:
            # the error text is usually in the STDOUT envelope (API Error:
            # 500 ...), stderr is often empty — log both (game 7)
            self.log(f"[seat {self.seat}] claude exit {proc.returncode}: "
                     f"stderr={proc.stderr.strip()[:160]!r} "
                     f"stdout={proc.stdout.strip()[:200]!r}")
            return None
        try:
            env = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.log(f"[seat {self.seat}] unparseable envelope: "
                     f"{proc.stdout[:200]!r}")
            return None
        if env.get("is_error"):
            self.log(f"[seat {self.seat}] model error envelope: "
                     f"{str(env.get('result'))[:200]}")
            return None
        return env

    def _track_child(self, proc) -> None:
        self._child = proc

    def _persistent_call(self, cmd_base: list[str], prompt: str, timeout_s: float,
                         eff: str) -> dict | None:
        """Step 1 transport. Starts (or restarts) the long-lived process for
        (model, effort); a different effort than the running process was
        started with means THIS call takes the spawn path (per-process flag).
        Any failure counts a fallback and returns None."""
        key = (self.model, eff)
        p = self._persistent
        if p is not None and p.alive() and self._persistent_key != key:
            # effort/model differs for this one call: spawn path. The live
            # process holds the transcript IN MEMORY, so a turn appended on
            # disk by the spawn would be invisible to it — stop it; the next
            # persistent call restarts from disk with --resume (Gemini pass 2, P1).
            self.stop_persistent()
            return None
        if p is None or not p.alive():
            err_path = str(self.root / "forge-arena" / "runner" / "logs" / f"claude-persistent-seat-{self.seat}.err")
            p = PersistentClaude(cmd_base, self.session_id, str(self.root), self.log, stderr_path=err_path)
            if not p.start():
                self.persistent_fallbacks += 1
                return None
            self._persistent, self._persistent_key = p, key
            self.log(f"[seat {self.seat}] persistent claude process up for session "
                     f"{self.session_id[:8]} ({self.model}/{eff})")
        self._child = p.proc
        env = p.call(prompt, timeout_s)
        self._child = None
        if env is None:
            self.persistent_fallbacks += 1
            self._persistent = None
            return None
        if env.get("is_error"):
            self.log(f"[seat {self.seat}] model error envelope (persistent): "
                     f"{str(env.get('result'))[:200]}")
            return {"__error__": True}   # handled by _call: a model error, not a transport fallback
        if env.get("session_id") and env["session_id"] != self.session_id:
            self.log(f"[seat {self.seat}] persistent process reported session "
                     f"{env['session_id'][:8]} (had {self.session_id[:8]}) — adopting it")
            self.session_id = env["session_id"]
        self.persistent_calls += 1
        return env

    def stop_persistent(self) -> None:
        p = getattr(self, "_persistent", None)   # brains built without __init__ (tests)
        if p is not None:
            p.kill()
        self._persistent = None

    def kill_child(self) -> None:
        """Kill the in-flight CLI call, if any (BL-28: called from the seat's
        SIGTERM/SIGINT handler so teardown never orphans a model call)."""
        self.stop_persistent()
        c = self._child
        if c is not None:
            try:
                c.kill()
            except OSError:
                pass

    def _accumulate(self, env: dict) -> None:
        u = env.get("usage") or {}
        self.totals["calls"] += 1
        try:
            self.last_prompt_tokens = sum(int(u.get(k) or 0) for k in (
                "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        except (TypeError, ValueError):
            pass
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                  "cache_creation_input_tokens"):
            v = u.get(k)
            if isinstance(v, (int, float)):
                self.totals[k] += int(v)
        c = env.get("total_cost_usd")
        if isinstance(c, (int, float)):
            self.totals["cost_usd"] = round(self.totals["cost_usd"] + c, 6)

    # ---- lifecycle -------------------------------------------------------------

    def ensure_session(self, timeout_s: float = 300.0) -> bool:
        """Load the dossier into a fresh session (once per game, per transport:
        Claude iff no session_id, backend iff its transcript is empty)."""
        if self.backend is not None:
            if self.backend.ready:
                return True
            t0 = time.time()
            env = self.backend.init(self._init_message, timeout_s, brain=self)
            if env is None:
                return False
            self.calls += 1
            self._accumulate(env)
            self.log(f"[seat {self.seat}] backend session up ({self.model}) in "
                     f"{time.time() - t0:.1f}s — {self.deck} dossier loaded "
                     f"as system context")
            return True
        if self.session_id:
            return True
        t0 = time.time()
        env = self._call(self._init_message, timeout_s, resume=False)
        if env is None or not env.get("session_id"):
            return False
        self.session_id = env["session_id"]
        self.calls += 1
        self._accumulate(env)  # the dossier load is the biggest single burn
        self.log(f"[seat {self.seat}] session up ({self.model}) in "
                 f"{time.time() - t0:.1f}s — {self.deck} dossier loaded, "
                 f"session {self.session_id[:8]}")
        return True

    def rotate(self, record_text: str, timeout_s: float = 120.0) -> bool:
        """Start a FRESH session for the same game: the same dossier, verbatim,
        plus the machine-built game record (seatd/record.py), then READY. The
        old session is simply abandoned. Claude CLI transport only — a backend
        keeps its own transcript. Returns True when the new session is up; on
        failure the old session stays in use."""
        if self.backend is not None or not self.session_id:
            return False
        ready = "\nReply exactly: READY"
        base = self._init_message
        if base.endswith(ready):
            base = base[: -len(ready)]
        prompt = base + "\n\n" + record_text.rstrip() + "\n" + ready
        t0 = time.time()
        env = self._call(prompt, timeout_s, resume=False)
        if env is None or not env.get("session_id"):
            self.log(f"[seat {self.seat}] session rotation FAILED — keeping the old session")
            return False
        old = self.session_id
        self.stop_persistent()          # the process holds the OLD session
        self.session_id = env["session_id"]
        self.calls += 1
        self.rotations += 1
        before = self.last_prompt_tokens
        self._accumulate(env)
        self.log(f"[seat {self.seat}] session rotated #{self.rotations} in {time.time() - t0:.1f}s: "
                 f"{before // 1000}k -> {self.last_prompt_tokens // 1000}k tokens "
                 f"({old[:8]} -> {self.session_id[:8]}); record {len(record_text)} chars")
        return True

    def note(self, text: str, timeout_s: float = 60.0) -> bool:
        """One plain message into the live session (no decision): used for the
        executive hand-off. Returns True when the model answered."""
        if not self.ensure_session(timeout_s=timeout_s):
            return False
        if self.backend is not None:
            return False
        env = self._call(text, timeout_s, resume=True)
        if env is None:
            return False
        self.calls += 1
        self._accumulate(env)
        return True

    def reset(self) -> None:
        self.stop_persistent()
        self._reset_inner()

    def _reset_inner(self) -> None:
        """New game (seq regression): drop the session; next decide() reloads.
        Totals restart too — each game's readout counts its own burn."""
        self.session_id = None
        self.calls = 0
        self._fail_streak = 0
        self._fail_streak_t0 = None
        self._rejoin_pending = False
        self.totals = {k: (0.0 if k == "cost_usd" else 0) for k in self.totals}
        # Per-game backend state: model-class latches (incl. cost/call caps)
        # clear; auth-class latches persist — a bad key does not heal between
        # games (plan F-06/F-09). Transcripts drop so init re-sends.
        self.backend_latches["model"].clear()
        for b in (self.backend, self._parked_backend):
            if b is not None:
                b.reset_for_new_game()

    def _note_failure(self) -> None:
        """Consecutive-failure accounting; wedge => fresh session next call."""
        now = time.time()
        if self._fail_streak == 0:
            self._fail_streak_t0 = now
        self._fail_streak += 1
        span = now - (self._fail_streak_t0 or now)
        wedged = (self._fail_streak >= WEDGE_HARD_FAILS
                  or (self._fail_streak >= WEDGE_FAILS and span >= WEDGE_SECONDS))
        if not wedged:
            return
        if self.backend is not None:
            # backend transports have their own latches/caps (plan F-06/F-09);
            # only the Claude resident session gets the drop-and-reinit cure
            return
        if self.session_id is None:
            return
        old = self.session_id
        self.log(f"[seat {self.seat}] SESSION WEDGED — {self._fail_streak} consecutive "
                 f"failures over {span:.0f}s on session {old[:8]}; dropping --resume, "
                 f"a fresh session (dossier reload, no game memory) starts at the "
                 f"next decision")
        self.session_id = None          # ensure_session() re-inits lazily
        self._rejoin_pending = True     # first prompt tells the brain it rejoined
        self.wedges += 1
        self._fail_streak = 0
        self._fail_streak_t0 = None

    # ---- decisions ----------------------------------------------------------------

    # Below this many seconds of window a model call cannot land in time;
    # the runner's own floor (handle()) uses the same number.
    MIN_CALL_S = 5.0

    def decide(self, prompt: str, timeout_s: float | None = None,
               effort: str | None = None,
               deadline: float | None = None) -> tuple[dict | None, dict]:
        """Send one decision prompt; return (answer dict or None, meta).

        Interactive plan item 2: the budget is ONE clock. `deadline` is the
        absolute time the answer must land by (the runner passes the engine's
        deadline); `timeout_s` is the legacy duration form. Init and the
        decision call each get what REMAINS of that deadline — never the
        whole budget twice, never a fixed cap. A lazy re-init that eats the
        window yields an on-time safe default (logged), not a dark seat.
        """
        meta = {"latency_s": None, "usage": None, "cache_read": None, "raw": None}
        if deadline is None:
            deadline = time.time() + (timeout_s if timeout_s is not None else 240.0)
        remaining = deadline - time.time()
        if remaining < self.MIN_CALL_S:
            self.log(f"[seat {self.seat}] {remaining:.0f}s left of the window "
                     f"-> no model call")
            return None, meta
        had_session = bool(self.session_id) or self.backend is not None
        t_init = time.time()
        if not self.ensure_session(timeout_s=max(remaining - self.MIN_CALL_S,
                                                 self.MIN_CALL_S)):
            return None, meta
        remaining = deadline - time.time()
        if remaining < self.MIN_CALL_S:
            self.log(f"[seat {self.seat}] init took {time.time() - t_init:.0f}s, "
                     f"{remaining:.0f}s left of the window -> safe default "
                     f"(session is warm for the next decision)")
            return None, meta
        if not had_session:
            self.log(f"[seat {self.seat}] init took {time.time() - t_init:.0f}s, "
                     f"{remaining:.0f}s left for the decision")
        if self._rejoin_pending:
            prompt = REJOIN_NOTE + prompt
            self._rejoin_pending = False
        t0 = time.time()
        env = self._call(prompt, remaining, resume=True, effort=effort)
        meta["latency_s"] = round(time.time() - t0, 2)
        if env is None:
            self._note_failure()
            return None, meta
        self._fail_streak = 0
        self._fail_streak_t0 = None
        self.calls += 1
        self._accumulate(env)
        usage = env.get("usage") or {}
        meta["usage"] = {k: usage.get(k) for k in
                         ("input_tokens", "output_tokens",
                          "cache_read_input_tokens", "cache_creation_input_tokens")}
        meta["cache_read"] = usage.get("cache_read_input_tokens")
        meta["raw"] = env.get("result")
        if self.backend is None and self.calls > 1 and not meta["cache_read"]:
            self.log(f"[seat {self.seat}] WARN cache MISS on resumed session")
        # `claude -p --resume` may rotate session ids; always chase the latest.
        if env.get("session_id"):
            self.session_id = env["session_id"]
        return extract_json(env.get("result", "")), meta
