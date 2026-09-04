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
  The runner does ALL file I/O — the model can never touch a mailbox path.

Every call returns (parsed_json_or_None, meta). Callers validate via rules.py
and fall back to rules.safe_default() — never trust, never retry past the
deadline.
"""
from __future__ import annotations

import json
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
    start, end = t.find("{"), t.rfind("}")
    if 0 <= start < end:
        try:
            out = json.loads(t[start:end + 1])
            return out if isinstance(out, dict) else None
        except json.JSONDecodeError:
            pass
    return None


class SeatBrain:
    """One resident model session for one seat."""

    def __init__(self, seat: int, deck: str, model: str = "sonnet",
                 effort: str = "low", repo_root: str | Path | None = None,
                 log=print, brief: str = "seat-brief.md",
                 extra_parts: list[str] | None = None):
        self.seat = int(seat)
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
        # Cumulative burn since instantiation (includes the dossier init call).
        self.totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                       "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0, "cost_usd": 0.0}
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
        cmd = ["claude", "-p", "-", "--output-format", "json",
               "--model", self.model, "--effort", eff,
               "--disallowedTools", "*",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
        if resume and self.session_id:
            cmd += ["--resume", self.session_id]
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                timeout=timeout_s, cwd=str(self.root))
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

    def _accumulate(self, env: dict) -> None:
        u = env.get("usage") or {}
        self.totals["calls"] += 1
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

    def reset(self) -> None:
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
