#!/usr/bin/env python3
"""Zero-latency auto-pass for no-op REACT windows (stopgap for the engine-side gate).

Watches every seat's inbox. A pending REACT whose non-pass options are ALL on the
no-op allowlist (free protection taps / mana-neutral recursion that never answers
a stack object) is answered instantly with {"chosenId": 0} — atomically, same as
a brain would. Anything else is left for the orchestrator/brains.

This is the `react_autopass` fastpath from docs/AGENT-SDK-SEATS.md, shipped early
as a standalone daemon. The durable fix is the engine-side filter
(INTERACTIVE-ARENA.md field note 12); retire this script when that lands.

Usage: python3 forge-arena/scripts/react-autopass.py [mailbox-dir]
"""
import json, os, sys, time, glob

BASE = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/toor/Claude/personal/forge-edh-arena/forge-arena/mailbox"

# Abilities that are never a meaningful response on their own. Matched by
# prefix against the option label (labels look like "Giver of Runes  {T} — ...").
NOOP_PREFIXES = ("Giver of Runes", "Academy Ruins")

POLL_S = 0.2

def is_noop_react(req):
    if req.get("decisionType") != "REACT":
        return False
    non_pass = [o for o in req.get("options", []) if o.get("id") != 0]
    if not non_pass:
        return True  # pass is the only option anyway
    return all(
        any(str(o.get("label", "")).startswith(p) for p in NOOP_PREFIXES)
        for o in non_pass
    )

def main():
    print(f"react-autopass watching {BASE} (allowlist: {', '.join(NOOP_PREFIXES)})",
          flush=True)
    while True:
        for req_path in glob.glob(os.path.join(BASE, "seat-*", "inbox", "req-*.json")):
            try:
                with open(req_path) as f:
                    req = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue  # partial write — engine writes atomically, retry next tick
            if not is_noop_react(req):
                continue
            seat_dir = os.path.dirname(os.path.dirname(req_path))
            seq = req.get("seq")
            final = os.path.join(seat_dir, "outbox", f"resp-{seq}.json")
            tmp = final + ".tmp"
            try:
                with open(tmp, "w") as f:
                    f.write('{"chosenId": 0}')
                os.replace(tmp, final)
                print(f"AUTOPASS seat={req.get('seat')} seq={seq} "
                      f"stack={req.get('state', {}).get('stack')}", flush=True)
            except OSError:
                pass
        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
