#!/usr/bin/env python3
"""seatd entry point — pilots one Forge arena seat over the file mailbox.

Modes:
  --echo   Transport-proof mode (H1): answers EVERY window with the legal pass /
           safe default, zero model calls. Run this against a live game to prove
           atomic writes, consumption, and seq handling before any brain exists.
  (default brain mode lands in H3-H4: headless `claude -p` per-seat session.)

Usage:
  python3 seat_runner.py --seat 2 [--base ../mailbox] [--echo]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seatd.protocol import SeatMailbox  # noqa: E402
from seatd.rules import safe_default  # noqa: E402

POLL_S = 0.5

# Echo mode answers every window with the always-legal safe default.
echo_default = safe_default


def run_echo(mb: SeatMailbox) -> None:
    print(f"[seat {mb.seat}] echo-runner up — base={mb.inbox.parent.parent}, "
          f"timeout={mb.timeout_s}s", flush=True)
    swept = mb.sweep_outbox()
    if swept:
        print(f"[seat {mb.seat}] swept {swept} stale outbox file(s)", flush=True)
    while True:
        req = mb.pending_request()
        if req is None:
            time.sleep(POLL_S)
            continue
        if mb.game_reset:
            print(f"[seat {mb.seat}] seq regression -> new game, memory wiped",
                  flush=True)
            mb.game_reset = False
        ans = echo_default(req)
        ok = mb.respond(req, ans)
        print(f"[seat {mb.seat}] seq={req['seq']} {req.get('decisionType')} "
              f"turn={req.get('turn')} {req.get('phase', '')} -> "
              f"{json.dumps(ans)} {'consumed' if ok else 'WINDOW LOST'}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seat", type=int, required=True)
    ap.add_argument("--deck", help="deck folder name (required for brain mode)")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="medium",
                    help="pinned reasoning effort for the seat session")
    ap.add_argument("--base", default=str(Path(__file__).resolve().parent.parent / "mailbox"))
    ap.add_argument("--timeout", type=float,
                    default=float(os.environ.get("ARENA_MAILBOX_TIMEOUT", "90")))
    ap.add_argument("--autopass", default="Giver of Runes,Mother of Runes,Academy Ruins",
                    help="comma-separated ability-name prefixes auto-passed in REACT")
    ap.add_argument("--speculative", action="store_true",
                    help="execute brain-authored CAST plans locally under the "
                         "four-part guard (fewer round-trips on uncontested turns)")
    ap.add_argument("--react-hold", action="store_true",
                    help="honor brain-armed same-turn REACT hold posture "
                         "(auto-pass reacts on already-seen stack objects)")
    ap.add_argument("--echo", action="store_true",
                    help="answer every window with the legal safe default (no model)")
    args = ap.parse_args()

    if args.echo:
        run_echo(SeatMailbox(args.seat, args.base, timeout_s=args.timeout))
        return
    if not args.deck:
        print("--deck is required for brain mode (or use --echo)", file=sys.stderr)
        sys.exit(2)
    from seatd.runner import SeatRunner
    autopass = tuple(s.strip() for s in args.autopass.split(",") if s.strip())
    SeatRunner(args.seat, args.deck, args.base, model=args.model,
               effort=args.effort, timeout_s=args.timeout,
               autopass=autopass, speculative=args.speculative,
               react_hold=args.react_hold).run()


if __name__ == "__main__":
    main()
