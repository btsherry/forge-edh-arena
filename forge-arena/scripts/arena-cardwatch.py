#!/usr/bin/env python3
"""Card-conservation watcher for a live arena game (2026-08-31, game 18).

Ben's ask: "watch for disappearing cards, or abilities and effects that
don't land or resolve properly." The seam's historic failure mode is a card
silently leaving every zone (a MailboxController gate defect, never a
missing script — see memory/card-vanish-is-seam-not-script). Nothing in the
engine logs that; the only place the full zone picture exists is the seat
decision request the engine writes to the mailbox — hand/library sizes plus
battlefield, graveyard, exile, command and the stack. Those files are
transient (consumed when the seat answers), so this polls them fast and
keeps a per-seat running total of NON-TOKEN cards across all zones (own
stack items included). It prints one line per seat at first sight and one
line on every change — a DROP with no matching visible move is the signal.

Reading the numbers: a seat's steady total is 100 (99 + commander) plus 1
for the "Commander Effect" pseudo-card the command zone lists, minus
anything the feed can't see (face-down exile such as Necropotence's, cards
under an opponent's control). Snapshots taken mid-resolution can double
count a card in transit (zone moves create new Card instances) — a GAIN
followed by an equal DROP within one resolution is that, not a vanish.
Baselines below 101 at game start mean the LOADER dropped cards (Sythis
opened at 97 = 95 cards + commander + effect: four modal-DFC lines written
"A // B").

Usage:  python3 scripts/arena-cardwatch.py [mailbox-dir]   (default: ./mailbox)
Exits when observer-state.json reports gameOver. Feed it to a line-buffered
monitor, or just tail it in a terminal.
"""
import glob
import json
import os
import sys
import time

BASE = sys.argv[1] if len(sys.argv) > 1 else "mailbox"


def nontoken(entries):
    n = 0
    for e in entries or []:
        name = e.get("name") if isinstance(e, dict) else str(e)
        if not str(name).endswith(" Token"):
            n += 1
    return n


def total(state):
    seat = state.get("seat")
    parts = {
        "hand": int(state.get("handSize") or 0),
        "lib": int(state.get("librarySize") or 0),
        "bf": nontoken(state.get("battlefield")),
        "gy": nontoken(state.get("graveyard")),
        "ex": nontoken(state.get("exile")),
        "cmd": nontoken(state.get("command")),
        "stack": sum(1 for o in (state.get("stackOwners") or []) if o == seat),
    }
    return sum(parts.values()), parts


def main():
    base, last = {}, {}
    print(f"[cards] watching {BASE} (nontoken cards per seat across zones)", flush=True)
    while True:
        for f in glob.glob(os.path.join(BASE, "seat-*", "inbox", "req-*.json")):
            try:
                req = json.load(open(f, encoding="utf-8"))
            except (OSError, ValueError):
                continue  # half-written or already consumed
            s = req.get("state") or {}
            if "librarySize" not in s:
                continue
            seat = s.get("seat")
            t, parts = total(s)
            if seat not in base:
                base[seat] = last[seat] = t
                print(f"[cards] seat {seat} baseline {t} at turn {s.get('turn')} {parts}", flush=True)
            elif t != last[seat]:
                tag = "DROP" if t < last[seat] else "GAIN"
                print(f"[cards] seat {seat} {tag} {last[seat]}->{t} (baseline {base[seat]}) "
                      f"turn {s.get('turn')} {s.get('phase')} {parts} stack={s.get('stack')}",
                      flush=True)
                last[seat] = t
        obs = os.path.join(BASE, "observer-state.json")
        if os.path.exists(obs):
            try:
                if json.load(open(obs, encoding="utf-8")).get("gameOver"):
                    print("[cards] gameOver observed — exiting", flush=True)
                    return
            except (OSError, ValueError):
                pass
        time.sleep(0.3)


if __name__ == "__main__":
    main()
