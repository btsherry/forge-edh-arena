#!/usr/bin/env python3
"""On-demand dashboard for the interactive GuiPilotMatch mailbox.

Reads the pending decision request(s) and prints a ground-truth table snapshot:
whose decision is pending, the turn/phase, and every seat's life + board (public
info) from the acting seat's serialized state. Use this instead of trusting a
brain's prose summary — it reflects what the engine actually sent.

Usage: python3 forge-arena/scripts/arena-status.py [mailbox-dir]
"""
import json, glob, sys, os

BASE = sys.argv[1] if len(sys.argv) > 1 else \
    "/Users/toor/Claude/personal/forge-edh-arena/forge-arena/mailbox"
DECKS = {0: "Selvala (YOU/human)", 1: "Purphoros", 2: "Giada", 3: "Urza"}

def print_observer_snapshot(path):
    """Print a dashboard from the continuously-updated public observer snapshot.

    This is written by ObserverSnapshot.java on every game event, so it stays
    fresh even during the HUMAN's turn (when no mailbox request is pending).
    It is PUBLIC info only: per-seat life/poison/board + hand COUNT (never
    contents, for anyone) and the public stack.
    """
    try:
        d = json.load(open(path))
    except Exception as e:
        print(f"No pending decision, and observer snapshot unreadable: {e}")
        return
    active = d.get("activeSeat")
    over = " [GAME OVER]" if d.get("gameOver") else ""
    win = f"  winner: {d['winner']}" if d.get("winner") else ""
    print("== TABLE  (from observer snapshot) ==")
    print(f"  turn {d.get('turn')}  |  {d.get('phase','')}  |  "
          f"active seat {active} [{DECKS.get(active,'?')}]{over}{win}")
    print()
    for s in d.get("seats", []):
        seat = s.get("seat")
        tag = "  <-- active turn" if seat == active else ""
        poison = f"  poison {s['poison']}" if s.get("poison") else ""
        print(f"  seat {seat} [{DECKS.get(seat,'?')}]  life {s.get('life')}  "
              f"hand {s.get('handSize')} (count)  lib {s.get('librarySize')}"
              f"{poison}{tag}")
        board = s.get("battlefield", [])
        if board:
            for c in board:
                pt = ""
                if "power" in c:
                    sick = " sick" if c.get("sick") else ""
                    pt = f" {c['power']}/{c['toughness']}{sick}"
                flags = " (tapped)" if c.get("tapped") else ""
                extra = ""
                if c.get("counters"):
                    extra += f" counters={c['counters']}"
                if c.get("auras"):
                    extra += f" auras={c['auras']}"
                print(f"       - {c.get('name')}{pt}{flags}{extra}")
        else:
            print("       board: (empty)")
    stack = d.get("stack", [])
    print()
    print(f"== STACK ==  {stack if stack else '(empty)'}")


reqs = sorted(glob.glob(os.path.join(BASE, "seat-*", "inbox", "req-*.json")))
if not reqs:
    obs = os.path.join(BASE, "observer-state.json")
    if os.path.exists(obs):
        print("No pending decision in the mailbox (likely the human's turn).")
        print()
        print_observer_snapshot(obs)
        sys.exit(0)
    print("No pending decision in the mailbox.")
    print("=> It's the human's turn (act in the GUI), or the game is between windows.")
    print("   (No observer-state.json yet — start an interactive mailbox match to populate it.)")
    sys.exit(0)

# Summarize every pending decision; keep the first as the state source.
print("== PENDING DECISIONS ==")
state_src = None
for f in reqs:
    try:
        d = json.load(open(f))
    except Exception:
        continue
    seat = d.get("seat")
    print(f"  seat {seat} [{DECKS.get(seat,'?')}]: {d.get('decisionType')} | "
          f"turn {d.get('turn')} | {d.get('phase','')} | seq {d.get('seq')}")
    if state_src is None:
        state_src = d
print()

st = state_src.get("state", {})
me = state_src.get("seat")

# Assemble each seat's public view (acting seat has full own info; others public).
seats = {me: {"life": st.get("life"), "board": st.get("battlefield"),
              "hand": st.get("handSize"), "own": True}}
for o in st.get("opponents", []):
    seats[o.get("seat")] = {"life": o.get("life"), "board": o.get("battlefield"),
                            "hand": "?", "cpow": o.get("creaturePower"), "own": False}

print(f"== TABLE  (turn {state_src.get('turn')}, {state_src.get('phase','')}, "
      f"active decision: seat {me} [{DECKS.get(me,'?')}]) ==")
for s in sorted(k for k in seats if k is not None):
    i = seats[s]
    tag = "  <-- deciding now" if s == me else ""
    hand = f"hand {i['hand']}" if i["own"] else f"hand {i['hand']} (hidden)"
    print(f"  seat {s} [{DECKS.get(s,'?')}]  life {i['life']}  {hand}{tag}")
    print(f"       board: {i['board']}")
    if i["own"]:
        for z in ("command", "graveyard", "exile"):
            v = st.get(z)
            if v:
                print(f"       {z}: {v}")
print()

print(f"== OPTIONS for seat {me} ({state_src.get('decisionType')}) ==")
for o in state_src.get("options", []):
    print(f"  [{o.get('id')}] {o.get('label','')}")
