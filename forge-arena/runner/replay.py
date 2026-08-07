#!/usr/bin/env python3
"""Offline end-to-end replay (H4 checkpoint): fixtures -> resident brain
session -> rules.validate -> verdict. No engine needed, real model calls.

Usage:
  python3 replay.py [--deck giada-font-of-hope] [--model sonnet] [--seat 2]
                    [--only cast_spell,react]
Checkpoint: 9/9 legal responses (model answer valid, or safe_default punt
explicitly reported), latency + cache telemetry per decision.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seatd import rules  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402

FIX = Path(__file__).parent / "tests" / "fixtures"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="giada-font-of-hope")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--seat", type=int, default=2)
    ap.add_argument("--only", default=None,
                    help="comma-separated fixture names (default: all)")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    names = (args.only.split(",") if args.only
             else sorted(p.stem for p in FIX.glob("*.json")))
    brain = SeatBrain(args.seat, args.deck, model=args.model)

    t0 = time.time()
    if not brain.ensure_session(timeout_s=300.0):
        print("FATAL: could not establish session")
        return 1

    ok = 0
    results = []
    for name in names:
        req = json.loads((FIX / f"{name}.json").read_text())
        prompt = rules.build_user_prompt(req)
        out, meta = brain.decide(prompt, timeout_s=args.timeout)
        clean = rules.validate(req, out) if out is not None else None
        punt = clean is None
        final = clean if clean is not None else rules.safe_default(req)
        legal = rules.validate(req, final) is not None or final == rules.safe_default(req)
        ok += 1 if not punt else 0
        results.append((name, punt, final, meta))
        print(f"{name:18s} {'MODEL' if not punt else 'PUNT '} "
              f"{json.dumps(final):55s} "
              f"{meta['latency_s'] or '?':>6}s  cache_read={meta['cache_read']}"
              + (f"  raw={str(meta['raw'])[:80]!r}" if punt else ""))

    n = len(names)
    print(f"\n{ok}/{n} answered by the model (rest safe-default punts), "
          f"total wall {time.time() - t0:.0f}s, session {brain.session_id[:8]}")
    return 0 if ok == n else 2


if __name__ == "__main__":
    sys.exit(main())
