#!/usr/bin/env python3
"""Phase 7 fidelity ledger (PR-58).

Answers the one question the prediction cutover rests on: when the engine
says "attacking right now kills someone", is it right, and did the OLD path
attack anyway?

Reads a batch run directory (the one holding game-records.jsonl) and reports
per deck:
  - how often a prediction ran at all (the read-model gate should make this
    rare — a high count means the gate is too loose)
  - how often it predicted a kill
  - whether a win actually followed within a turn (did the predicted kill
    happen, or is the copy lying?)
  - how often the engine called it lethal on a turn the old path did NOT
    steer an attack — the entire case for cutting over, in one number
  - what predictions cost in wall clock

Seating ROTATES per game, so every seat index is resolved through that
record's own `seats` array. Events are flat objects in a per-game file named
by the record's `event_log`.

Usage: fidelity.py <run-dir>
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def games(run_dir: Path):
    """Yield (record, [events]) for every game in the run."""
    records = run_dir / "game-records.jsonl"
    if not records.exists():
        sys.exit(f"no game-records.jsonl in {run_dir}")
    for line in records.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        events = []
        log = rec.get("event_log")
        if log and (run_dir / log).exists():
            for raw in (run_dir / log).read_text(errors="replace").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        yield rec, events


def main(run_dir: Path):
    per_deck = defaultdict(lambda: defaultdict(int))
    total = 0

    for rec, events in games(run_dir):
        total += 1
        seats = rec.get("seats") or []
        winner = rec.get("winner_seat", -1)
        win_turn = rec.get("turns")

        # what the OLD path actually did, per (seat, turn)
        attacked = {
            (e.get("seat"), e.get("turn"))
            for e in events
            if e.get("t") == "line_step"
            and e.get("stage") in ("FORCED_ATTACK", "LETHAL_ALPHA")
        }

        for e in events:
            if e.get("t") != "alpha_prediction":
                continue
            seat, turn = e.get("seat"), e.get("turn")
            deck = seats[seat] if isinstance(seat, int) and seat < len(seats) else f"seat{seat}"
            d = per_deck[deck]
            d["runs"] += 1
            d["ms"] += e.get("elapsed_ms") or 0
            if e.get("timed_out"):
                d["timed_out"] += 1
                continue
            if not e.get("predicted_kill"):
                d["predicted_no_kill"] += 1
                continue
            d["predicted_kill"] += 1
            won_soon = (
                seat == winner
                and isinstance(win_turn, int)
                and isinstance(turn, int)
                and 0 <= win_turn - turn <= 1
            )
            d["kill_then_won" if won_soon else "kill_no_win"] += 1
            d["old_path_agreed" if (seat, turn) in attacked else "OLD_PATH_MISSED"] += 1

    print(f"=== PR-58 fidelity ledger — {total} games from {run_dir.name} ===\n")
    if not per_deck:
        print("no alpha_prediction events: the read-model gate never opened.")
        print("(power >= weakest opponent life never held on an own combat)")
        return

    for deck, d in sorted(per_deck.items()):
        n = d["runs"]
        print(f"{deck}")
        print(f"  predictions run         {n}   avg {d['ms'] / n:.0f} ms"
              f"   ({d['timed_out']} timed out)")
        print(f"  predicted a kill        {d['predicted_kill']}"
              f"   (no kill: {d['predicted_no_kill']})")
        print(f"    won within a turn     {d['kill_then_won']}")
        print(f"    no win followed       {d['kill_no_win']}"
              f"   <- copy lying, or pilot never took the attack")
        print(f"  old path also attacked  {d['old_path_agreed']}")
        print(f"  OLD PATH MISSED IT      {d['OLD_PATH_MISSED']}"
              f"   <- the case for cutting over")
        print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(Path(sys.argv[1]))
