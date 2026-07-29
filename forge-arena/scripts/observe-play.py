#!/usr/bin/env python3
"""Observe play across a batch run dir: find game states where a seat could
plausibly have converted to a win SOONER than it did, and aggregate the
turn-by-turn decision patterns behind them.

Usage: observe-play.py <run-dir-with-events/> [--verbose]

Heuristic classes (each conservative — flags candidates for human review,
never claims a proof; the engine alone decides what was actually lethal):

  ALPHA_HELD_BACK   a seat's board_power >= a living opponent's life while
                    that opponent had no untapped-creature proxy (creatures
                    == 0), sustained for 2+ of the seat's own turns before
                    the game ended — unblockable-on-paper lethal not taken.
  ENTRY_LATENCY     combo_ready at turn R but line_entered at R+2 or later
                    (patience is 0 — the gap is affordability/defer loops).
  READY_NEVER_ENTERED  combo_ready fired, no entry for that combo all game.
  CONVERSION_TAIL   program_complete at turn T, game still running at T+3
                    (the storm landed, the kill machinery lagged).
  DRILL_CHURN       outlet_drill events on one turn with own_life frozen
                    for 20+ consecutive events (the PayLife-refusal class).
  DOMINANT_TIMEOUT  timeout/draw games where one seat ended with 2x the
                    total living opposition's board power and above-start
                    life — a board that should have closed and didn't.

Output: per-game findings plus an aggregate summary.
"""
import json
import sys
import collections
import glob
import os


def load_events(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def analyze_game(path, verbose=False):
    ev = load_events(path)
    findings = []
    result = next((e for e in ev if e["t"] == "game_end"), None)
    end_turn = result.get("turn") if result else None
    winner = result.get("winner_seat", result.get("winner")) if result else None
    rtype = str(result.get("result", result.get("type", "?"))) if result else "?"

    # --- per-turn state table ---
    states = {e["turn"]: e["seats"] for e in ev if e["t"] == "turn_state"}
    turns = sorted(states)

    # ALPHA_HELD_BACK: board lethal vs an empty-board opponent, sustained
    held = collections.defaultdict(list)  # seat -> turns where predicate held
    for t in turns:
        for s in states[t]:
            if s.get("lost"):
                continue
            for o in states[t]:
                if o["seat"] == s["seat"] or o.get("lost"):
                    continue
                if (s.get("board_power", 0) >= o.get("life", 99)
                        and o.get("creatures", 9) == 0
                        and s.get("board_power", 0) > 0):
                    held[s["seat"]].append(t)
                    break
    for seat, ts in held.items():
        # sustained: 2+ turns in the window before the end, and the seat
        # did not win the game on the first turn it held lethal
        if len(ts) >= 2 and (winner != seat or (end_turn and end_turn - ts[0] >= 3)):
            findings.append(("ALPHA_HELD_BACK", seat,
                             f"board-lethal vs empty-board opponent from t{ts[0]} "
                             f"held {len(ts)} turns; game ended t{end_turn} "
                             f"({'won' if winner == seat else 'did NOT win'})"))

    # combo timeline per seat, with ignore-reason attribution
    ready = collections.defaultdict(dict)   # seat -> combo -> first ready turn
    entered = collections.defaultdict(dict)
    ignored = collections.defaultdict(collections.Counter)  # (seat,combo) -> reasons
    for e in ev:
        if e["t"] == "combo_ready":
            ready[e["seat"]].setdefault(e.get("combo"), e["turn"])
        if e["t"] == "line_entered":
            entered[e["seat"]].setdefault(e.get("combo"), e["turn"])
        if e["t"] == "combo_ignored":
            ignored[(e["seat"], e.get("combo"))][e.get("reason")] += 1
    for seat, combos in ready.items():
        for combo, r in combos.items():
            en = entered[seat].get(combo)
            why = dict(ignored.get((seat, combo), {}))
            if en is None:
                # a combo that became ready in the game's last 3 turns is
                # end-state noise (the winner's storm turn lights everything
                # up), not a missed line
                if end_turn is not None and end_turn - r <= 3:
                    continue
                findings.append(("READY_NEVER_ENTERED", seat,
                                 f"{combo} ready t{r}, never entered "
                                 f"(game ended t{end_turn}) ignored={why}"))
            elif en - r >= 2:
                findings.append(("ENTRY_LATENCY", seat,
                                 f"{combo} ready t{r}, entered t{en} (+{en - r})"
                                 f" ignored={why}"))

    # CONVERSION_TAIL: program completed, game dragged on
    for e in ev:
        if e["t"] == "program_complete" and end_turn is not None:
            gap = end_turn - e["turn"]
            if gap >= 3 or (winner != e.get("seat")):
                findings.append(("CONVERSION_TAIL", e.get("seat"),
                                 f"{e.get('combo')} complete t{e['turn']}, game "
                                 f"ended t{end_turn} (+{gap}), "
                                 f"{'won' if winner == e.get('seat') else 'did NOT win'}"))

    # DRILL_CHURN: life-frozen drill windows. Program loop iterations carry
    # a 'kind' field (mana_pair / copy_iteration / cast_bounce) and their
    # life legitimately holds still — only the LEGACY drill's steps (no
    # kind; the PayLife-refusal class) count as churn.
    churn = collections.Counter()
    prev = {}
    for e in ev:
        if e["t"] != "outlet_drill" or e.get("kind") is not None:
            continue
        key = (e.get("seat"), e.get("turn"), e.get("outlet"))
        life = e.get("own_life")
        if prev.get(key) == life:
            churn[key] += 1
        prev[key] = life
    for (seat, turn, outlet), n in churn.items():
        if n >= 20:
            findings.append(("DRILL_CHURN", seat,
                             f"{outlet} t{turn}: {n} consecutive life-frozen "
                             f"activation windows"))

    # DOMINANT_TIMEOUT
    if rtype.lower().find("timeout") >= 0 or rtype.lower().find("draw") >= 0:
        if turns:
            last = states[turns[-1]]
            for s in last:
                if s.get("lost"):
                    continue
                opp_power = sum(o.get("board_power", 0) for o in last
                                if o["seat"] != s["seat"] and not o.get("lost"))
                if (s.get("board_power", 0) >= 2 * max(1, opp_power)
                        and s.get("life", 0) > 40):
                    findings.append(("DOMINANT_TIMEOUT", s["seat"],
                                     f"ended t{end_turn} with power "
                                     f"{s.get('board_power')} vs table {opp_power}, "
                                     f"life {s.get('life')} — board never closed"))

    return {
        "game": os.path.basename(path),
        "result": rtype,
        "winner": winner,
        "end_turn": end_turn,
        "findings": findings,
    }


def main():
    run_dir = sys.argv[1]
    verbose = "--verbose" in sys.argv
    files = sorted(glob.glob(os.path.join(run_dir, "events", "*.jsonl")))
    if not files:
        sys.exit(f"no events under {run_dir}")
    agg = collections.Counter()
    per_seat = collections.Counter()
    print(f"observing {len(files)} games in {run_dir}\n")
    for path in files:
        g = analyze_game(path, verbose)
        for kind, seat, msg in g["findings"]:
            agg[kind] += 1
            per_seat[(kind, seat)] += 1
        if g["findings"]:
            print(f"[{g['game']}] {g['result']} winner={g['winner']} t{g['end_turn']}")
            for kind, seat, msg in g["findings"]:
                print(f"    {kind:<20} seat {seat}: {msg}")
    print("\n=== aggregate ===")
    for kind, n in agg.most_common():
        seats = {s: c for (k, s), c in per_seat.items() if k == kind}
        print(f"{kind:<20} {n:>3} findings  by seat: {dict(sorted(seats.items()))}")


if __name__ == "__main__":
    main()
