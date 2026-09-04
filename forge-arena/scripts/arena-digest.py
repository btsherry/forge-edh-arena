#!/usr/bin/env python3
"""Per-turn digest of an all-AI (or human) game — one compact line per turn.

Designed to be wrapped by the Monitor tool so an ambient "how's it going" feed
costs ~1 notification per turn instead of 5-10 per decision. Decision-level
detail is never lost — it's always in game.jsonl (read via status.py). Tails
game.jsonl and, on each turn rollover, emits:

  t14 | life 40/38/40/25 | seat2 CAST_SPELL x4, DECLARE_ATTACKERS | ELIM: seat3

Also emits an immediate line for eliminations and for any punt/invalid, so the
digest doubles as a light problem signal without a second monitor. game.jsonl
is a plain append-only file for the whole session (BL-21), so one digest spans
every game of the session; torn lines are counted and reported, never silent.

Usage: python3 forge-arena/scripts/arena-digest.py [game.jsonl]
"""
import json
import os
import sys
import time
from collections import Counter

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runner", "logs", "game.jsonl")


def fmt_lives(lives):
    if not lives:
        return "?"
    return "/".join(str(lives[k]) for k in sorted(lives, key=lambda x: int(x)))


def flush(turn, acts, last_lives, elim):
    if turn is None or not acts:
        return
    # compact "seatN TYPE xN" summary, ordered by seat
    parts = []
    for seat in sorted(acts):
        tc = acts[seat]
        segs = [f"{t}{'x'+str(n) if n > 1 else ''}" for t, n in tc.most_common()]
        parts.append(f"seat{seat} " + ",".join(segs))
    line = f"t{turn} | life {fmt_lives(last_lives)} | " + " ; ".join(parts)
    if elim:
        line += " | ELIM:" + ",".join("seat" + s for s in sorted(elim))
    print(line, flush=True)


def main():
    # wait for the file, then tail from the end
    while not os.path.exists(PATH):
        time.sleep(1)
    f = open(PATH)
    f.seek(0, 2)
    cur_turn = None
    acts = {}
    last_lives = {}
    prev_lives = None
    elim_this_turn = set()
    torn = 0

    while True:
        line = f.readline()
        if not line:
            time.sleep(0.5)
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            torn += 1  # BL-10: a torn/partial line is counted, not swallowed
            if torn in (1, 10, 100) or torn % 1000 == 0:
                print(f"digest: {torn} unparseable line(s) skipped so far", flush=True)
            continue
        turn = r.get("turn")
        seat = r.get("seat")
        board = r.get("board") or {}
        lives = board.get("lives") or {}

        # turn rollover -> flush the completed turn
        if cur_turn is not None and turn != cur_turn:
            flush(cur_turn, acts, last_lives, elim_this_turn)
            acts = {}
            elim_this_turn = set()
        cur_turn = turn

        acts.setdefault(seat, Counter())[r.get("type")] += 1
        if lives:
            # detect eliminations = a seat that had life last snapshot and is now gone
            if prev_lives:
                for k in prev_lives:
                    if k not in lives:
                        elim_this_turn.add(k)
            prev_lives = lives
            last_lives = lives

        # immediate signal for real problems (no second monitor needed)
        if r.get("source") == "punt":
            print(f"t{turn} | PUNT seat{seat} {r.get('type')}: {r.get('why','')}",
                  flush=True)


if __name__ == "__main__":
    main()
