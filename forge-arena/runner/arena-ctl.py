#!/usr/bin/env python3
"""Live per-seat brain control: set model/effort mid-game.

The runners reconcile: changes apply at each seat's next decision boundary
(sessions survive — model/effort are per-call flags). The AI dock tab writes
the same files; this is the terminal path.

Usage:
  arena-ctl.py <seat|all> [--model haiku|sonnet|opus] [--effort low|medium|high]
  arena-ctl.py status            # show current control files

Examples:
  arena-ctl.py 2 --model opus --effort high     # boss-mode Giada
  arena-ctl.py all --effort low                 # calm the whole table
"""
import json
import sys
import time
from pathlib import Path

CONTROL = Path(__file__).parent / "logs" / "control"
SEATS = (0, 1, 2, 3)


def show_status() -> None:
    for n in SEATS:
        p = CONTROL / f"seat-{n}.json"
        if p.exists():
            try:
                d = json.loads(p.read_text())
                age = time.time() - p.stat().st_mtime
                print(f"seat {n}: model={d.get('model')} effort={d.get('effort')} "
                      f"(updated {age:.0f}s ago)")
            except (OSError, json.JSONDecodeError):
                print(f"seat {n}: unreadable control file")
        else:
            print(f"seat {n}: no control file (runner not started)")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "status":
        show_status()
        return 0

    target = args[0]
    seats = list(SEATS) if target == "all" else [int(target)]
    updates = {}
    i = 1
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            updates["model"] = args[i + 1]; i += 2
        elif args[i] == "--effort" and i + 1 < len(args):
            updates["effort"] = args[i + 1]; i += 2
        else:
            print(f"unknown arg: {args[i]}"); return 2
    if not updates:
        print("nothing to set (use --model/--effort)"); return 2

    CONTROL.mkdir(parents=True, exist_ok=True)
    for n in seats:
        p = CONTROL / f"seat-{n}.json"
        current = {}
        if p.exists():
            try:
                current = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                pass
        current.update(updates)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current))
        tmp.replace(p)
        print(f"seat {n} <- {json.dumps(current)}")
    print("(applies at each seat's next decision)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
