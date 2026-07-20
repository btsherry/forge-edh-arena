#!/usr/bin/env python3
"""Phase 7 fidelity ledger (PR-58).

Answers the question that decides whether the prediction cutover is
justified: when the engine says "attacking now kills someone", is it right,
and does the existing predicate agree?

Reads a batch run directory and reports, per deck:
  - how often a prediction ran at all (the read-model gate is meant to make
    this rare)
  - how often it predicted a kill
  - whether the seat actually won that turn or the next (did the predicted
    kill happen?)
  - how often the OLD path declined to attack on a turn the engine says was
    lethal — the whole case for switching, in one number
  - what the predictions cost in wall clock

Usage: fidelity.py <run-dir>
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_records(run_dir: Path):
    """Yield (record, events) per game across every worker shard."""
    for path in sorted(run_dir.rglob("*.jsonl")):
        if path.name == "batches.jsonl":
            continue
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and "events" in rec:
                yield rec, rec.get("events", [])


def main(run_dir: Path):
    per_deck = defaultdict(lambda: {
        "predictions": 0, "predicted_kill": 0, "timed_out": 0,
        "elapsed_ms": 0, "kill_and_won_soon": 0, "kill_but_no_win": 0,
        "forced_attack_same_turn": 0, "lethal_missed_by_old_path": 0,
    })
    games = 0

    for rec, events in load_records(run_dir):
        games += 1
        # seating ROTATES per game — always use this record's own seats
        seats = rec.get("seats") or []
        winner_seat = rec.get("winner_seat", -1)
        win_turn = rec.get("turns")

        # what the OLD path did, per (seat, turn)
        forced = set()
        for e in events:
            if e.get("t") == "line_step" and e.get("fields", {}).get("stage") in (
                    "FORCED_ATTACK", "LETHAL_ALPHA"):
                forced.add((e.get("seat"), e.get("turn")))

        for e in events:
            if e.get("t") != "alpha_prediction":
                continue
            f = e.get("fields", {})
            seat = e.get("seat")
            turn = e.get("turn")
            deck = seats[seat] if isinstance(seat, int) and seat < len(seats) else f"seat{seat}"
            d = per_deck[deck]
            d["predictions"] += 1
            d["elapsed_ms"] += f.get("elapsed_ms", 0) or 0
            if f.get("timed_out"):
                d["timed_out"] += 1
                continue
            if not f.get("predicted_kill"):
                continue
            d["predicted_kill"] += 1

            # Did the predicted kill actually land? The seat winning on this
            # turn or the next is the observable proxy for "yes".
            won_soon = (seat == winner_seat and isinstance(win_turn, int)
                        and isinstance(turn, int) and 0 <= win_turn - turn <= 1)
            if won_soon:
                d["kill_and_won_soon"] += 1
            else:
                d["kill_but_no_win"] += 1

            if (seat, turn) in forced:
                d["forced_attack_same_turn"] += 1
            else:
                # engine says lethal, old path did not steer an attack: this
                # is the population the cutover would newly convert
                d["lethal_missed_by_old_path"] += 1

    print(f"=== PR-58 fidelity ledger: {games} games from {run_dir} ===\n")
    if not per_deck:
        print("no alpha_prediction events found — the read-model gate never opened")
        return
    for deck, d in sorted(per_deck.items()):
        n = d["predictions"]
        avg = (d["elapsed_ms"] / n) if n else 0
        print(f"{deck}")
        print(f"  predictions run        {n}  (avg {avg:.0f} ms, {d['timed_out']} timed out)")
        print(f"  predicted a kill       {d['predicted_kill']}")
        print(f"    -> seat won by t+1   {d['kill_and_won_soon']}")
        print(f"    -> no win followed   {d['kill_but_no_win']}   <- copy lying, or the pilot did not take it")
        print(f"  old path also attacked {d['forced_attack_same_turn']}")
        print(f"  OLD PATH MISSED IT     {d['lethal_missed_by_old_path']}   <- the case for cutting over")
        print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(Path(sys.argv[1]))
