#!/usr/bin/env python3
"""Phase 11 execution-fidelity scorer (PR-epsilon).

Scores a batch run directory on the thing Phase 11 exists for: did compiled
programs ENTER, SUSTAIN, and CONVERT — and when they stopped, why. Wins are
counted from the ENGINE result only (the pre-gamma spike measured that a
lethal final iteration ends the game before program_complete can be emitted,
so completion events undercount conversions).

Per deck, across the run:
  - entered:     games in which a governor_plan fired (the program planned)
  - iterations:  verified loop iterations (outlet_drill), total / per-entered-game
  - plans:       governor need/cap/planned as recorded
  - aborts:      program_abort reasons, histogrammed (the build backlog's
                 runtime twin — every reason here is a bug class or a
                 legitimate interruption)
  - suppressed:  legacy drills refused on program pieces (drill_suppressed)
  - converted:   games WON (engine result) by a seat that had entered its
                 program that game
  - prereqs:     loop_prereq grants performed and verified

Seating ROTATES per game; every seat index resolves through that record's
own `seats` array. Usage: program-fidelity.py <run-dir>
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(run_dir: Path) -> None:
    records = [json.loads(line)
               for line in (run_dir / "game-records.jsonl").open()]
    decks = sorted({name for r in records for name in r["seats"]})
    entered = Counter()
    iterations = Counter()
    iter_per_game = defaultdict(list)
    plans = defaultdict(list)
    aborts = defaultdict(Counter)
    suppressed = Counter()
    prereqs = Counter()
    converted = Counter()
    wins = Counter()
    decided = 0

    for rec in records:
        seats = rec["seats"]
        events = []
        log = run_dir / rec["event_log"]
        if log.exists():
            events = [json.loads(line) for line in log.open()]
        entered_this_game = set()
        game_iters = Counter()
        for e in events:
            deck = seats[e["seat"]] if e.get("seat") is not None else None
            t = e.get("t")
            if t == "governor_plan":
                entered_this_game.add(deck)
                plans[deck].append({k: e.get(k) for k in ("need", "cap", "planned",
                                                          "tranche")})
            elif t == "outlet_drill":
                iterations[deck] += 1
                game_iters[deck] += 1
            elif t == "program_abort":
                aborts[deck][str(e.get("reason", "?")).split(":")[0]] += 1
            elif t == "drill_suppressed":
                suppressed[deck] += 1
            elif t == "loop_prereq":
                prereqs[deck] += 1
        for deck in entered_this_game:
            entered[deck] += 1
            iter_per_game[deck].append(game_iters[deck])
        if rec["result"] == "win":
            decided += 1
            winner = seats[rec["winner_seat"]]
            wins[winner] += 1
            if winner in entered_this_game:
                converted[winner] += 1

    games = len(records)
    print(f"run: {run_dir}  games={games} decided={decided}")
    for deck in decks:
        print(f"\n{deck}")
        print(f"  wins            {wins[deck]}/{games}")
        print(f"  program entered {entered[deck]} games")
        if entered[deck]:
            per = iter_per_game[deck]
            print(f"  iterations      total={iterations[deck]} "
                  f"per-entered-game={sorted(per, reverse=True)}")
            print(f"  converted       {converted[deck]} engine wins with program entered")
            print(f"  prereq grants   {prereqs[deck]}")
            recent = plans[deck][:3]
            print(f"  governor plans  {len(plans[deck])} (first: {recent})")
        if aborts[deck]:
            print(f"  aborts          {dict(aborts[deck])}")
        if suppressed[deck]:
            print(f"  drill_suppressed {suppressed[deck]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
