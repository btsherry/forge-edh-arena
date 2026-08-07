#!/usr/bin/env python3
"""seatd health + narrative dashboard. Numbers over vibes.

Usage: python3 forge-arena/runner/status.py [--tail N] [logs-dir]

Reads seat-*.jsonl (per-seat decisions) and game.jsonl (shared, board-stamped
narrative all seats append to). Shows per-seat health rates, table totals, and
the recent play narrative with each brain's logged decision logic.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def pct(part, whole):
    return f"{100.0 * part / whole:.0f}%" if whole else "-"


def p(values, q):
    if not values:
        return None
    vs = sorted(values)
    return vs[min(len(vs) - 1, int(q * len(vs)))]


def main() -> None:
    args = [a for a in sys.argv[1:]]
    tail_n = 12
    if "--tail" in args:
        i = args.index("--tail")
        tail_n = int(args[i + 1])
        del args[i:i + 2]
    logs = Path(args[0]) if args else Path(__file__).parent / "logs"

    print("== SEAT HEALTH ==")
    grand = {"dec": 0, "model": 0, "fast": 0, "punt": 0, "lost": 0,
             "out": 0, "cache": 0, "cost": 0.0}
    for jl in sorted(logs.glob("seat-*.jsonl")):
        recs = []
        for line in jl.read_text().splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not recs:
            continue
        n = len(recs)
        by = {}
        for r in recs:
            by[r.get("source", "?")] = by.get(r.get("source", "?"), 0) + 1
        lat = [r["latency_s"] for r in recs if r.get("latency_s")]
        lost = sum(1 for r in recs if r.get("consumed") is False)
        punts = by.get("punt", 0)
        fast = by.get("autopass", 0) + by.get("memo", 0)
        model = by.get("model", 0)
        # cache-hit rate across model calls that reported usage
        hits = misses = 0
        for r in recs:
            u = r.get("usage") or {}
            if u.get("cache_read_input_tokens") is not None:
                if u["cache_read_input_tokens"] > 0:
                    hits += 1
                else:
                    misses += 1
        cum = recs[-1].get("cum") or {}
        age = time.time() - recs[-1].get("ts", 0)
        print(f"  {jl.stem}: {n} decisions | model {model} ({pct(model, n)}) "
              f"fastpath {fast} ({pct(fast, n)}) punt {punts} lost {lost}")
        print(f"      latency p50 {p(lat, .5)}s p95 {p(lat, .95)}s | "
              f"cache hit {pct(hits, hits + misses)} ({misses} miss) | "
              f"last activity {age:.0f}s ago")
        if cum:
            print(f"      burn: {cum.get('calls')} calls, out {cum.get('output_tokens')}, "
                  f"cache_read {cum.get('cache_read_input_tokens')}, "
                  f"≈${cum.get('cost_usd', 0):.2f} API-equiv (subscription)")
            grand["out"] += cum.get("output_tokens") or 0
            grand["cache"] += cum.get("cache_read_input_tokens") or 0
            grand["cost"] += cum.get("cost_usd") or 0
        grand["dec"] += n
        grand["model"] += model
        grand["fast"] += fast
        grand["punt"] += punts
        grand["lost"] += lost

    if grand["dec"]:
        print(f"\n== TABLE ==  {grand['dec']} decisions | model {grand['model']} "
              f"| fastpath {grand['fast']} | punts {grand['punt']} "
              f"| lost {grand['lost']} | out {grand['out']} tok "
              f"| ≈${grand['cost']:.2f} API-equiv")

    game = logs / "game.jsonl"
    if game.exists():
        lines = game.read_text().splitlines()[-tail_n:]
        print(f"\n== RECENT PLAY (last {len(lines)} of {game.name}) ==")
        for line in lines:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            b = r.get("board") or {}
            lives = "/".join(str(v) for _, v in sorted(
                (b.get("lives") or {}).items()))
            combat = f" ⚔ {len(b['combat'])} atk" if b.get("combat") else ""
            stack = f" stk:{b['stack']}" if b.get("stack") else ""
            why = f' — "{r.get("why")}"' if r.get("why") else ""
            lat = f" ({r['latency_s']}s)" if r.get("latency_s") else ""
            print(f"  [t{r.get('turn')} {r.get('phase','')} seat{r.get('seat')} "
                  f"{r.get('type')}] {json.dumps(r.get('answer'))}"
                  f"{why}{lat}  |  lives {lives}{combat}{stack}")


if __name__ == "__main__":
    main()
