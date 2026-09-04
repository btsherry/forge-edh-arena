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
        # BL-10: pre-backend records may lack keys — defaults, never KeyError
        g = lambda k, d=0: last_cum.get(k, d)  # noqa: E731
        print(f"  cumulative: {g('calls')} calls, "
              f"in={g('input_tokens')} out={g('output_tokens')} "
              f"cache_read={g('cache_read_input_tokens')} "
              f"≈${g('cost_usd', 0.0):.2f} API-equivalent (subscription-covered)")
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            grand[k] += g(k)
        grand["cost"] += g("cost_usd", 0.0)
        grand["calls"] += g("calls")
    else:  # pre-telemetry records: fall back to per-decision usage sums
        print(f"  summed usage (excl. session init): in={per['input_tokens']} "
              f"out={per['output_tokens']} cache_read={per['cache_read_input_tokens']}")
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            grand[k] += per[k]

if grand:
    print(f"\nTABLE TOTAL: in={grand['input_tokens']} out={grand['output_tokens']} "
          f"cache_read={grand['cache_read_input_tokens']}"
          + (f" ≈${grand['cost']:.2f} API-equivalent" if grand.get("cost") else ""))
