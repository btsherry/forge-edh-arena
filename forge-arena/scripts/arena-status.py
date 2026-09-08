#!/usr/bin/env python3
"""On-demand dashboard for the interactive GuiPilotMatch mailbox.

Reads the pending decision request(s) and prints a ground-truth table snapshot:
whose decision is pending, the turn/phase, and every seat's life + board (public
info) from the acting seat's serialized state. Use this instead of trusting a
brain's prose summary — it reflects what the engine actually sent.

Usage: python3 forge-arena/scripts/arena-status.py [mailbox-dir]
"""
import json, glob, sys, os

BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mailbox")


def _seat_labels():
    """Live seat labels from the observer snapshot (2026-08-24: the old
    hardcoded default-roster map mislabeled any non-default table). AI seats
    are named mailbox-seat<N>-<Deck>; anything else is the human/advisor
    seat. Missing snapshot -> generic seat N."""
    import re
    labels = {}
    try:
        snap = json.load(open(os.path.join(BASE, "observer-state.json")))
        for seat in snap.get("seats", []):
            n, name = seat.get("seat"), seat.get("name") or ""
            m = re.match(r"mailbox-seat\d+-(.+)", name)
            labels[n] = m.group(1) if m else f"{name} (YOU/human)"
    except (OSError, ValueError):
        pass
    return labels


_LABELS = _seat_labels()


def _label(seat):
    return _LABELS.get(seat, f"seat {seat}")


def print_seatd_narrative(tail_n=6):
    """Recent brain decisions + logged decision logic from the shared
    game.jsonl (written by the seatd runners; full view: runner/status.py)."""
    game = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "runner", "logs", "game.jsonl")
    if not os.path.exists(game):
        return
    try:
        lines = open(game).read().splitlines()[-tail_n:]
    except OSError:
        return
    print()
    print(f"== RECENT SEAT DECISIONS (game.jsonl; runner/status.py for full) ==")
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        # FAIRNESS: decision logic ("why") is sealed during live play — it can
        # reveal hidden holdings/plans to the human opponent. Post-game review:
        # runner/status.py or game.jsonl directly.
        print(f"  [t{r.get('turn')} {r.get('phase','')} seat {r.get('seat')} "
              f"{r.get('type')}] {json.dumps(r.get('answer'))}")

def print_seat_efficiency():
    """2026-09-07: per-seat efficiency for the CURRENT game — how many
    decisions the runner answered itself (memo/repeat/yield/affordability/
    autopass) vs the model, the model's context size and rotations (from the
    seat's usage snapshot), and the executive / engine-mirror state."""
    import collections
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs = os.path.join(root, "runner", "logs")
    game = os.path.join(logs, "game.jsonl")
    if not os.path.exists(game):
        return
    rows = []
    try:
        for line in open(game):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        return
    if not rows:
        return
    gid = rows[-1].get("gameId")
    rows = [r for r in rows if r.get("gameId") == gid]
    print()
    print("== SEAT EFFICIENCY (this game) ==")
    for seat in sorted({r.get("seat") for r in rows}):
        mine = [r for r in rows if r.get("seat") == seat]
        src = collections.Counter(r.get("source") for r in mine)
        model = src.get("model", 0)
        fast = sum(v for k, v in src.items() if k not in ("model", "punt"))
        line = (f"  seat {seat} [{_label(seat)}]  decisions {len(mine)}  model {model}  "
                f"runner-answered {fast} ({', '.join(f'{k} {v}' for k, v in sorted(src.items()) if k not in ('model', 'punt'))})  "
                f"punts {src.get('punt', 0)}")
        try:
            u = json.load(open(os.path.join(logs, f"seat-{seat}.usage.json")))
            line += (f"\n        ctx {u.get('last_prompt_tokens', 0) // 1000}k  rotations {u.get('rotations', 0)}  "
                     f"cache_read {u.get('cache_read_input_tokens', 0) // 1000}k  calls {u.get('calls', 0)}"
                     + (f"  persistent {u.get('persistent_calls')}/{u.get('persistent_fallbacks')}fb"
                        if 'persistent_calls' in u else ""))
        except (OSError, ValueError):
            pass
        print(line)
    exe = os.path.join(logs, "control", "executive.json")
    try:
        on = json.load(open(exe)).get("on", False)
        print(f"  advisor executive: {'ON — the advisor plays seat 0' if on else 'off'}")
    except (OSError, ValueError):
        print("  advisor executive: off")
    mirror = os.path.join(logs, "engine-events.jsonl")
    if os.path.exists(mirror):
        try:
            ev = [json.loads(l) for l in open(mirror) if l.strip()]
            ev = [e for e in ev if e.get("gameId") == gid]
            kinds = collections.Counter(e.get("kind") for e in ev)
            if kinds:
                print("  engine events: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
        except (OSError, ValueError):
            pass


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
          f"active seat {active} [{_label(active)}]{over}{win}")
    print()
    for s in d.get("seats", []):
        seat = s.get("seat")
        tag = "  <-- active turn" if seat == active else ""
        poison = f"  poison {s['poison']}" if s.get("poison") else ""
        print(f"  seat {seat} [{_label(seat)}]  life {s.get('life')}  "
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
        print_seatd_narrative()
        print_seat_efficiency()
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
    print(f"  seat {seat} [{_label(seat)}]: {d.get('decisionType')} | "
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
      f"active decision: seat {me} [{_label(me)}]) ==")
for s in sorted(k for k in seats if k is not None):
    i = seats[s]
    tag = "  <-- deciding now" if s == me else ""
    hand = f"hand {i['hand']}" if i["own"] else f"hand {i['hand']} (hidden)"
    print(f"  seat {s} [{_label(s)}]  life {i['life']}  {hand}{tag}")
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

print_seatd_narrative()
