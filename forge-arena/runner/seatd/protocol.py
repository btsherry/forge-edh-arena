"""Mailbox transport for one Forge arena seat.

Implements the file contract from docs/INTERACTIVE-ARENA.md exactly:

    <base>/seat-<id>/inbox/req-<n>.json    engine writes (atomic .tmp+rename)
    <base>/seat-<id>/outbox/resp-<n>.json  we write (atomic .tmp+rename)

Engine behavior this module encodes (from MailboxProtocol.java):
- Engine polls the outbox every 75ms; once a resp parses as JSON it deletes
  BOTH files (resp first, then req) — a malformed-but-parseable resp burns the
  window, so callers must validate BEFORE respond().
- On timeout the engine deletes the req and falls back to stock AI; a resp
  written after that is a stale landmine for the NEXT game (seq resets to 1
  per engine process). Hence: re-check req existence before writing, confirm
  consumption after, and sweep our own outbox at startup.
- Seqs are per-seat and monotonic from 1. A seq at-or-below the last seen one
  (outside the just-answered delete race) means an engine restart: all game
  memory must be wiped (`game_reset` flag).

FAIRNESS (mechanical): paths are constructed ONLY from the seat id given at
construction. The single cross-seat read in the entire codebase is the public
observer snapshot. Nothing here can name another seat's directory.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_REQ_RE = re.compile(r"^req-(\d+)\.json$")

# A req we answered may linger up to ~2 engine polls while the engine deletes
# resp-then-req. Within this window a still-present answered seq is the race;
# beyond it, an identical seq means a NEW GAME reused the number.
_DELETE_RACE_S = 3.0


class SeatMailbox:
    """Transport for exactly one seat. No game logic lives here."""

    def __init__(self, seat: int, base: str | os.PathLike, timeout_s: float = 90.0):
        base = Path(base)
        self.seat = int(seat)
        seat_dir = base / f"seat-{self.seat}"          # sole path root (fairness)
        self.inbox = seat_dir / "inbox"
        self.outbox = seat_dir / "outbox"
        self.observer_path = base / "observer-state.json"  # only legal cross-seat read
        self.timeout_s = float(timeout_s)
        self.last_seq = 0
        self._answered_at: dict[int, float] = {}
        self.game_reset = False  # set when a seq regression is detected; caller clears

    # ---- startup hygiene -------------------------------------------------

    def sweep_outbox(self) -> int:
        """Delete leftover resp files (a stale resp-1 would be mis-consumed as
        the answer to the next game's first request). Returns count removed."""
        n = 0
        if self.outbox.is_dir():
            for p in self.outbox.glob("resp-*.json*"):  # includes orphaned .tmp
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    pass
        return n

    # ---- request discovery -----------------------------------------------

    @staticmethod
    def _seq_of(path: Path) -> int | None:
        m = _REQ_RE.match(path.name)
        return int(m.group(1)) if m else None

    def pending_request(self) -> dict | None:
        """Oldest fresh, unanswered request as a parsed dict, or None.

        - Ignores the engine's *.tmp staging files (never matched) and reqs
          older than the timeout (orphans from a killed engine).
        - Skips seqs answered within the delete-race window.
        - Detects engine restart (seq regression / reused seq beyond the race
          window): wipes seq memory and sets `game_reset`.
        """
        if not self.inbox.is_dir():
            return None
        now = time.time()
        candidates = []
        for p in self.inbox.iterdir():
            seq = self._seq_of(p)
            if seq is None:
                continue
            try:
                age = now - p.stat().st_mtime
            except OSError:
                continue  # vanished between listing and stat
            if age >= self.timeout_s:
                continue  # orphan req: no engine is waiting on this
            candidates.append((seq, p))
        for seq, p in sorted(candidates):
            answered = self._answered_at.get(seq)
            if answered is not None and (now - answered) < _DELETE_RACE_S:
                continue  # engine still mid-delete on this one
            if answered is not None or seq <= self.last_seq:
                # Reused or regressed seq outside the race window: engine restart.
                self._reset_game_memory()
            try:
                req = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                return None  # engine writes atomically — partial read is transient
            if not isinstance(req, dict) or req.get("seq") != seq:
                return None  # malformed or mid-rename; retry next tick
            return req
        return None

    def _reset_game_memory(self) -> None:
        self.last_seq = 0
        self._answered_at.clear()
        self.game_reset = True

    # ---- responding --------------------------------------------------------

    def respond(self, req: dict, payload: dict,
                consume_wait_s: float = 2.0) -> bool:
        """Atomically write the response for `req`. Returns True if written
        (and, best-effort, consumed), False if the window was already lost.

        Callers MUST have validated `payload` (engine deletes both files the
        moment it parses as JSON, before shape validation)."""
        seq = int(req["seq"])
        req_path = self.inbox / f"req-{seq}.json"
        if not req_path.exists():
            return False  # engine timed out / restarted — never write late
        final = self.outbox / f"resp-{seq}.json"
        tmp = self.outbox / f"resp-{seq}.json.tmp"
        self.outbox.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, final)  # atomic: engine can never see a partial file
        self._answered_at[seq] = time.time()
        self.last_seq = max(self.last_seq, seq)

        # Confirm consumption (engine polls at 75ms). If the req vanished but
        # our resp lingers, the engine gave up — GC our own landmine.
        deadline = time.time() + consume_wait_s
        while time.time() < deadline:
            if not final.exists():
                return True
            time.sleep(0.05)
        if not req_path.exists() and final.exists():
            try:
                final.unlink()
            except OSError:
                pass
            return False
        return True  # engine is slow but still coming; resp is valid

    # ---- public observer ----------------------------------------------------

    def read_observer(self) -> dict | None:
        """The PUBLIC table snapshot (life/boards/stack, hand counts only)."""
        try:
            return json.loads(self.observer_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
