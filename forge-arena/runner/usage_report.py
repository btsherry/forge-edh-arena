#!/usr/bin/env python3
"""Per-seat token-burn report from the decisions JSONLs. Works mid-game.

Usage: python3 forge-arena/runner/usage_report.py [logs-dir]
"""
import json
import sys
from collections import Counter
from pathlib import Path

logs = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "logs"

grand = Counter()
for jl in sorted(logs.glob("seat-*.jsonl")):
    seat = jl.stem
    per, sources, lat = Counter(), Counter(), []
    last_cum = None
    for line in jl.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        sources[rec.get("source", "?")] += 1
        if rec.get("latency_s"):
            lat.append(rec["latency_s"])
        u = rec.get("usage") or {}
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            per[k] += u.get(k) or 0
        if rec.get("cum"):
            last_cum = rec["cum"]
    n = sum(sources.values())
    avg = sum(lat) / len(lat) if lat else 0
    print(f"{seat}: {n} decisions "
          f"({', '.join(f'{k}={v}' for k, v in sorted(sources.items()))}) "
          f"avg model latency {avg:.1f}s")
    if last_cum:
        print(f"  cumulative: {last_cum['calls']} calls, "
              f"in={last_cum['input_tokens']} out={last_cum['output_tokens']} "
              f"cache_read={last_cum['cache_read_input_tokens']} "
              f"≈${last_cum['cost_usd']:.2f} API-equivalent (subscription-covered)")
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            grand[k] += last_cum[k]
        grand["cost"] += last_cum["cost_usd"]
        grand["calls"] += last_cum["calls"]
    else:  # pre-telemetry records: fall back to per-decision usage sums
        print(f"  summed usage (excl. session init): in={per['input_tokens']} "
              f"out={per['output_tokens']} cache_read={per['cache_read_input_tokens']}")
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            grand[k] += per[k]

if grand:
    print(f"\nTABLE TOTAL: in={grand['input_tokens']} out={grand['output_tokens']} "
          f"cache_read={grand['cache_read_input_tokens']}"
          + (f" ≈${grand['cost']:.2f} API-equivalent" if grand.get("cost") else ""))
