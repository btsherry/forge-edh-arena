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

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


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
                 log=print):
        self.seat = int(seat)
        self.deck = deck
        self.model = model
        self.effort = effort  # pinned — never inherit the user's saved default
        self.log = log
        self.session_id: str | None = None
        self.calls = 0
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
            (here / "seat-brief.md").read_text(),
            # The project's real rules corpus (CR-cited), not a summary of a
            # summary: the game-pilot digest + the win-execution digest.
            (docs / "research" / "mtg-rules-summary.md").read_text(),
            (docs / "research" / "mtg-rules-digest-conversion.md").read_text(),
            f"\n## You are SEAT {self.seat}, playing the deck: {deck}\n",
            "## DECK DOSSIER (full oracle text — never summarized)\n",
            dossier_p.read_text(),  # fat context is REQUIRED (field note 1)
        ]
        if primer_p.exists():
            parts += ["\n## STRATEGY PRIMER\n", primer_p.read_text()]
        parts.append("\nReply exactly: READY")
        self._init_message = "\n".join(parts)

    # ---- transport -----------------------------------------------------------

    def _call(self, prompt: str, timeout_s: float, resume: bool) -> dict | None:
        """One headless call. Returns the parsed --output-format json envelope
        (NOT the answer), or None on failure/timeout."""
        cmd = ["claude", "-p", "-", "--output-format", "json",
               "--model", self.model, "--effort", self.effort,
               "--disallowedTools", "*"]
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
            self.log(f"[seat {self.seat}] claude exit {proc.returncode}: "
                     f"{proc.stderr.strip()[:200]}")
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
        """Load the dossier into a fresh session (once per game)."""
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
        self.totals = {k: (0.0 if k == "cost_usd" else 0) for k in self.totals}

    # ---- decisions ----------------------------------------------------------------

    def decide(self, prompt: str, timeout_s: float) -> tuple[dict | None, dict]:
        """Send one decision prompt; return (answer dict or None, meta)."""
        meta = {"latency_s": None, "usage": None, "cache_read": None, "raw": None}
        if not self.ensure_session():
            return None, meta
        t0 = time.time()
        env = self._call(prompt, timeout_s, resume=True)
        meta["latency_s"] = round(time.time() - t0, 2)
        if env is None:
            return None, meta
        self.calls += 1
        self._accumulate(env)
        usage = env.get("usage") or {}
        meta["usage"] = {k: usage.get(k) for k in
                         ("input_tokens", "output_tokens",
                          "cache_read_input_tokens", "cache_creation_input_tokens")}
        meta["cache_read"] = usage.get("cache_read_input_tokens")
        meta["raw"] = env.get("result")
        if self.calls > 1 and not meta["cache_read"]:
            self.log(f"[seat {self.seat}] WARN cache MISS on resumed session")
        # `claude -p --resume` may rotate session ids; always chase the latest.
        if env.get("session_id"):
            self.session_id = env["session_id"]
        return extract_json(env.get("result", "")), meta
