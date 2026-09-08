#!/usr/bin/env python3
"""arena-public-state.py — everything PUBLIC about the live game, in one dump.

Reads the engine's observer snapshot (mailbox/observer-state.json, rewritten
on every game event) and prints a compact, complete view of the public game
state: turn / phase / active seat, and for every seat life, poison, hand and
library COUNTS (never contents), eliminated, the battlefield with P/T,
tapped, summoning-sick, counters, attachments, imprinted and exiled-with
cards, then graveyard, exile and command zone contents, and the stack with
owners and targets. Nothing here is hidden information (CR 400.2, 406.3) —
the human sees all of it in the GUI; this is the same view for a program.

Used by the AI Advisor as its one allowed tool (2026-09-07, Ben): the
advisor's per-decision request carries the board but not the graveyards,
exile or what sits under an Isochron Scepter; a question like "what did
Urza imprint?" is answered by running this.

Usage:
  arena-public-state.py                 # text, all seats
  arena-public-state.py --seat 1        # one seat's zones in full
  arena-public-state.py --json          # the raw snapshot
  arena-public-state.py --snapshot PATH # a saved snapshot instead of the live one
Exit 2 when no game is live (no snapshot).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ARENA = os.path.dirname(HERE)
DEFAULT_SNAPSHOT = os.path.join(ARENA, "mailbox", "observer-state.json")


def card_line(c: dict) -> str:
    bits = [str(c.get("name", "?"))]
    if "power" in c:
        bits.append(f"{c.get('power')}/{c.get('toughness')}")
    flags = []
    if c.get("tapped"):
        flags.append("tapped")
    if c.get("sick"):
        flags.append("sick")
    if flags:
        bits.append("(" + ", ".join(flags) + ")")
    if c.get("counters"):
        bits.append("counters " + ", ".join(f"{k} x{v}" for k, v in c["counters"].items()))
    if c.get("auras"):
        bits.append("attached: " + ", ".join(c["auras"]))
    if c.get("imprinted"):
        bits.append("imprinted: " + ", ".join(c["imprinted"]))
    if c.get("exiledWith"):
        bits.append("exiled with it: " + ", ".join(c["exiledWith"]))
    return " ".join(bits)


def render(snap: dict, only_seat: int | None = None) -> str:
    out = []
    age = ""
    ts = snap.get("timestamp")
    if isinstance(ts, (int, float)):
        age = f" (snapshot {max(0, time.time() - ts / 1000):.0f}s old)"
    out.append(f"TURN {snap.get('turn')} — {snap.get('phase') or '?'} — active seat {snap.get('activeSeat')}"
               f"{' — GAME OVER, winner ' + str(snap.get('winner')) if snap.get('gameOver') else ''}{age}")
    stack = snap.get("stackDetail") or snap.get("stack") or []
    if stack:
        out.append(f"STACK ({len(stack)} items, top last):")
        for item in stack:
            if isinstance(item, dict):
                tgt = f" -> {', '.join(map(str, item['targets']))}" if item.get("targets") else ""
                out.append(f"  {item.get('kind', '')} {item.get('name')} [seat {item.get('owner')}]{tgt}".replace("  ", " "))
            else:
                out.append(f"  {item}")
    else:
        out.append("STACK: empty")
    for s in snap.get("seats", []):
        if only_seat is not None and s.get("seat") != only_seat:
            continue
        head = (f"SEAT {s.get('seat')} {s.get('name')}: life {s.get('life')}"
                + (f", poison {s.get('poison')}" if s.get("poison") else "")
                + f", hand {s.get('handSize')}, library {s.get('librarySize')}"
                + (", ELIMINATED" if s.get("eliminated") else ""))
        if s.get("playerCounters"):
            head += ", counters " + ", ".join(f"{k} x{v}" for k, v in s["playerCounters"].items())
        out.append(head)
        if s.get("commandZone"):
            out.append("  command zone: " + ", ".join(s["commandZone"]))
        bf = s.get("battlefield") or []
        out.append(f"  battlefield ({len(bf)}):" if bf else "  battlefield: empty")
        for c in bf:
            out.append("    " + card_line(c))
        for zone, label in (("graveyard", "graveyard"), ("exile", "exile")):
            cards = s.get(zone)
            if cards is None:
                continue
            out.append(f"  {label} ({len(cards)}): " + (", ".join(cards) if cards else "empty"))
    if not any("graveyard" in s for s in snap.get("seats", [])):
        out.append("(graveyards, exile and command zones are not in this snapshot version — the engine publishes them from v3.5)")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--seat", type=int)
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    a = ap.parse_args()
    try:
        with open(a.snapshot, encoding="utf-8") as f:
            snap = json.load(f)
    except FileNotFoundError:
        print("no live game: the observer snapshot is missing (start a table with arena-play.sh)", file=sys.stderr)
        return 2
    except ValueError:
        time.sleep(0.2)  # a torn read mid-write; the engine writes atomically, so retry once
        with open(a.snapshot, encoding="utf-8") as f:
            snap = json.load(f)
    if a.json:
        print(json.dumps(snap, indent=1))
    else:
        print(render(snap, a.seat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
