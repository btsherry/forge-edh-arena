#!/usr/bin/env python3
"""arena-hygiene.py — the teardown hygiene block (Ben, 2026-09-08). Reads one
archived session (or the live runner/logs) and prints, per game: decisions by
who answered them, model share, punts, refusals, deviations, timeouts,
rotations, restarts, wedges, persistent fallbacks, yield-mirror passes, engine
seam markers, voice and advisor counts — and a loud line when anything that
should be zero is not. arena-stop.sh runs it after the archive and saves the
output as hygiene.txt beside the logs.

Usage: arena-hygiene.py <archive-dir | runner/logs>
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys

# The same signals the game watchers key on. Each: (label, regex over seat-*.log
# and run_table.out lines, must-be-zero?)
SEAT_LOG_SIGNALS = [
    # one stalled call writes "call timed out" AND "used the window … no spawn
    # retry": count the first line only (game 31 read 2 for one stall)
    ("timeouts", re.compile(r"call timed out|timed out \("), True),
    ("punts", re.compile(r"\[punt|answering the safe default"), True),
    ("tracebacks", re.compile(r"Traceback|INTERNAL ERROR"), True),
    ("windows lost", re.compile(r"WINDOW LOST"), True),
    ("wedges", re.compile(r"SESSION WEDGED"), True),
    ("refusals", re.compile(r"was refused"), False),
    ("deviations", re.compile(r"DEVIATION"), False),
    ("rotations", re.compile(r"session rotated #"), False),
    ("restarts", re.compile(r"RESTART mid-game"), False),
]
# run_table.out echoes every seat log line (stdout of the seat loops), so it is
# read ONLY for the supervisor's own restart line. C3 (2026-09-14): the voice and
# advisor supervisors write the same line to their own .out — counted too (game 48
# read "restarts 0" with two voice restarts).
RESTART_LINE = re.compile(r"runner exited")
SUPERVISOR_OUTS = ("run_table.out", "voice_runner.out", "advisor_runner.out")


RUNNER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner")
try:
    # C2 (2026-09-14): the SAME rule the runner's eviction class, governor and seat guard use, so the
    # anchored share Ben steers by measures what the scheduler does. `spoke` records carry `source`.
    sys.path.insert(0, RUNNER_DIR)
    from voice.scheduler import ANCHORED_SOURCES, classify_source  # noqa: E402
except Exception:                                                   # a package without the runner beside the script: the same mapping, mirrored
    ANCHORED_SOURCES = ("event", "card", "procedural", "opener", "brain")   # keep in step with voice/scheduler.py (tested)

    def classify_source(source):
        if source == "chain":
            return "chain"
        return "anchored" if source in ANCHORED_SOURCES else "optional"


def anchored(v: dict) -> bool:
    """A spoken seat line tied to something that happened at the table — the shared
    classify_source() (voice/scheduler.py) says which sources those are; the advisor's
    afterthoughts (recap, advice), patter and banter replies are optional."""
    return classify_source(v.get("source")) == "anchored"


# Ben's table-talk targets (round 31): the pace and the anchored share he steers by.
TARGET_LINES_PER_MIN = 8.0
TARGET_ANCHORED = 0.60
LONG_GAP_S = 24.0          # a silence longer than this is what the ear notices
VOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner", "voice", "stock", "voices")


def _p90(sorted_vals):
    """The same p90 arithmetic the model-latency line uses."""
    n = len(sorted_vals)
    return sorted_vals[int(n * 0.9) - 1 if n > 1 else 0]


def voice_pace(voice: list) -> list[str]:
    """Lines for the voice section: pace and anchored share beside the targets, the
    gap distribution between spoken lines (a gap runs from one line's end to the
    next line's start), and the distinct ids spoken against the ids the seated
    libraries hold (their manifests, when found beside this script)."""
    out = []
    spoke = sorted((v for v in voice if v.get("event") == "spoke" and isinstance(v.get("ts"), (int, float))),
                   key=lambda v: v["ts"])
    barks = [v for v in spoke if v.get("kind") == "bark"]
    if len(spoke) >= 2:
        # the pace target counts the SEATS' lines (Ben: 8 seat lines a minute); a silence is a
        # silence whoever broke it, so the gaps run over every line, Joshua's included
        ends = [v["ts"] + (v.get("seconds") if isinstance(v.get("seconds"), (int, float)) else 0) for v in spoke]
        gaps = sorted(max(0.0, spoke[i + 1]["ts"] - ends[i]) for i in range(len(spoke) - 1))
        span_min = max(ends[-1] - spoke[0]["ts"], 1e-9) / 60.0
        long_gaps = [g for g in gaps if g > LONG_GAP_S]
        share = f"{sum(1 for v in barks if anchored(v)) / len(barks):.0%}" if barks else "n/a"
        out.append(f"  voice pace: {len(barks) / span_min:.1f} seat lines/min (target {TARGET_LINES_PER_MIN:.0f}) | "
                   f"anchored {share} (target {TARGET_ANCHORED:.0%}) | "
                   f"gaps median {gaps[len(gaps) // 2]:.1f}s p90 {_p90(gaps):.1f}s max {gaps[-1]:.1f}s | "
                   f"{sum(long_gaps):.0f}s inside {len(long_gaps)} gap(s) over {LONG_GAP_S:.0f}s")
    ids = {v.get("stock") for v in spoke if v.get("stock")}
    if ids:
        line = f"  voice ids: {len(ids)} distinct spoken"
        libs, avail = [], 0
        for lib in sorted({v.get("library") for v in spoke if v.get("library")}):
            try:
                with open(os.path.join(VOICES_DIR, lib, "manifest.json"), encoding="utf-8") as f:
                    avail += len(json.load(f).get("phrases") or {})
                libs.append(lib)
            except (OSError, ValueError, AttributeError):
                continue
        if libs:
            line += f" / {avail} available ({', '.join(libs)})"
        out.append(line)
    return out


GUI_SIGNALS = [("yield-mirror", "yield-mirror"), ("TARGETLOSS", "TARGETLOSS"), ("SA-SWAP", "SA-SWAP"),
               ("java exceptions", "Exception")]


def rows_of(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def lines_of(paths):
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    yield line
        except OSError:
            continue


def report(d: str) -> tuple[str, bool]:
    out = []
    bad = collections.OrderedDict()
    game_rows = rows_of(os.path.join(d, "game.jsonl"))
    by_game = collections.OrderedDict()
    for r in game_rows:
        by_game.setdefault(r.get("gameId") or "unstamped", []).append(r)
    out.append(f"== HYGIENE  {os.path.basename(d.rstrip('/'))}  ({len(game_rows)} decisions, {len(by_game)} game(s)) ==")
    for gid, rows in by_game.items():
        src = collections.Counter(r.get("source") for r in rows)
        model = src.get("model", 0)
        punts = src.get("punt", 0)
        fast = {k: v for k, v in src.items() if k not in ("model", "punt")}
        n = len(rows)
        out.append(f"  game {str(gid)[:8]}: decisions {n} | model {model} ({100 * model // max(n, 1)}%) | "
                   f"runner-answered {sum(fast.values())} ({', '.join(f'{k} {v}' for k, v in sorted(fast.items(), key=lambda kv: -kv[1]))})"
                   f" | punts {punts} | deviations {sum(1 for r in rows if r.get('deviation'))}")
        if punts:
            bad["punts (game log)"] = punts
        lat = [r.get("latency_s") for r in rows if r.get("source") == "model" and isinstance(r.get("latency_s"), (int, float))]
        if lat:
            lat.sort()
            out.append(f"     model latency: median {lat[len(lat) // 2]:.1f}s  p90 {lat[int(len(lat) * 0.9) - 1 if len(lat) > 1 else 0]:.1f}s  max {lat[-1]:.1f}s")
        for seat in sorted({r.get("seat") for r in rows}):
            mine = [r for r in rows if r.get("seat") == seat]
            s = collections.Counter(r.get("source") for r in mine)
            line = f"     seat {seat}: {len(mine)} decisions, model {s.get('model', 0)}, punts {s.get('punt', 0)}"
            try:
                u = json.load(open(os.path.join(d, f"seat-{seat}.usage.json")))
                line += (f" | ctx {u.get('last_prompt_tokens', 0) // 1000}k, rotations {u.get('rotations', 0)}, "
                         f"calls {u.get('calls', 0)}, cache-read {u.get('cache_read_input_tokens', 0) // 1000}k")
                if "persistent_calls" in u:
                    line += f", persistent {u.get('persistent_calls')} / fallbacks {u.get('persistent_fallbacks')}"
                    if u.get("persistent_fallbacks"):
                        bad[f"persistent fallbacks seat {seat}"] = u.get("persistent_fallbacks")
            except (OSError, ValueError):
                pass
            out.append(line)
    seat_logs = sorted(glob.glob(os.path.join(d, "seat-*.log")))
    counts = collections.Counter()
    for line in lines_of(seat_logs):
        for label, rx, _ in SEAT_LOG_SIGNALS:
            if rx.search(line):
                counts[label] += 1
    counts["restarts"] += sum(1 for line in lines_of([os.path.join(d, n) for n in SUPERVISOR_OUTS]) if RESTART_LINE.search(line))
    gui = ""
    try:
        gui = open(os.path.join(d, "gui.out"), encoding="utf-8", errors="replace").read()
    except OSError:
        pass
    gui_counts = {label: gui.count(needle) for label, needle in GUI_SIGNALS} if gui else {}
    ev = collections.Counter(e.get("kind") for e in rows_of(os.path.join(d, "transport-events.jsonl")))
    eng = collections.Counter(e.get("kind") for e in rows_of(os.path.join(d, "engine-events.jsonl")))
    out.append("  runner signals: " + " | ".join(f"{label} {counts.get(label, 0)}" for label, _, _ in SEAT_LOG_SIGNALS))
    if ev:
        out.append("  transport events: " + ", ".join(f"{k} {v}" for k, v in sorted(ev.items())))
    if eng or gui_counts:
        parts = [f"{k} {v}" for k, v in sorted(eng.items())] + [f"{k} {v}" for k, v in gui_counts.items() if k != "yield-mirror" or not eng]
        out.append("  engine: " + ", ".join(parts))
    for label, _, must_zero in SEAT_LOG_SIGNALS:
        if must_zero and counts.get(label):
            bad[label] = counts[label]
    if gui_counts.get("java exceptions"):
        bad["java exceptions (gui.out)"] = gui_counts["java exceptions"]
    voice = rows_of(os.path.join(d, "voice-0.jsonl"))
    if voice:
        vc = collections.Counter(v.get("event") for v in voice)
        bk = collections.Counter(v.get("event") for v in voice if v.get("kind") == "bark")
        spoke_barks = [v for v in voice if v.get("event") == "spoke" and v.get("kind") == "bark"]
        n_anchored = sum(1 for v in spoke_barks if anchored(v))
        duties = [v["duty"] for v in voice if v.get("event") == "spoke" and isinstance(v.get("duty"), (int, float))]
        if spoke_barks:
            # round 31: the mix — Ben's goal is an anchored share past 60 % at about 8 lines/min; the duty is the governor's measure
            srcs = collections.Counter(v.get("source") or "?" for v in spoke_barks)
            out.append(f"  table talk: {len(spoke_barks)} seat lines — anchored {n_anchored / len(spoke_barks):.0%} "
                       f"({', '.join(f'{k} {n}' for k, n in srcs.most_common())})"
                       + (f" | mean duty {sum(duties) / len(duties):.2f}" if duties else ""))
        out.append(f"  voice: spoke {vc.get('spoke', 0)} | skipped {vc.get('skipped', 0)} | dropped {vc.get('dropped', 0)} | "
                   f"render failures {vc.get('render-failed', 0)} | live paused {vc.get('live-paused', 0)}"
                   f" | barks spoke {bk.get('spoke', 0)} / skipped {bk.get('skipped', 0)} / dropped {bk.get('dropped', 0)}")
        out.extend(voice_pace(voice))
        if vc.get("live-paused"):
            bad["voice live paused"] = vc["live-paused"]
    adv = rows_of(os.path.join(d, "advisor-0.jsonl"))
    if adv:
        ac = collections.Counter(a.get("kind") or a.get("event") for a in adv)
        out.append("  advisor: " + ", ".join(f"{k} {v}" for k, v in sorted(ac.items(), key=lambda kv: -kv[1])[:6]))
    if bad:
        out.append("  !! HYGIENE: " + ", ".join(f"{k} {v}" for k, v in bad.items()) + f" — read the logs in {d}")
    else:
        out.append("  OK: no punts, timeouts, fallbacks, tracebacks, lost windows or wedges")
    return "\n".join(out) + "\n", not bad


def main() -> None:
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    text, ok = report(sys.argv[1])
    sys.stdout.write(text)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
