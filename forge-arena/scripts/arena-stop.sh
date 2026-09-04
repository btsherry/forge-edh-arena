#!/bin/sh
# One-shot teardown: kill GUI + all seat runners, archive this session's logs
# (per-seat logs, game.jsonl and the per-game game-<id>.jsonl files — BL-21:
# the whole log set of a session moves to archive/ together), clear the
# mailbox + control files. Prints a single summary line. Zero-fidelity-loss
# consolidation of the multi-step teardown so the orchestrator spends one
# round trip, not five.
#
# Usage: forge-arena/scripts/arena-stop.sh
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$DIR/.." && pwd)          # forge-arena/
LOGS="$ROOT/runner/logs"

# Item 13e: kill by PID file (written by arena-play.sh / run_table.sh), so a
# stop touches only THIS table's processes. The command-line patterns are the
# fallback for a table launched before PID files existed.
PIDS="$LOGS/pids"
# BL-27 hardening: a PID file may be stale (a runner restarted, the number
# reused by an unrelated process). Only signal a PID whose command line
# belongs to THIS checkout.
ours() { ps -p "$1" -o command= 2>/dev/null | grep -qF -- "$ROOT"; }
if [ -d "$PIDS" ] && ls "$PIDS"/*.pid >/dev/null 2>&1; then
  for f in "$PIDS"/*.pid; do p=$(cat "$f" 2>/dev/null); [ -n "$p" ] && ours "$p" && kill "$p" 2>/dev/null; done
  sleep 1
  for f in "$PIDS"/*.pid; do p=$(cat "$f" 2>/dev/null); [ -n "$p" ] && ours "$p" && kill -9 "$p" 2>/dev/null; rm -f "$f"; done
  left=$(pgrep -f "seat_runner.py --seat|advisor_runner.py|GuiPilotMatch" | wc -l | tr -d ' ')
  [ "$left" -gt 0 ] && echo "note: $left arena process(es) not covered by a PID file are still running (another table, or a hand launch) — left alone" >&2
else
  # BL-27: the fallback patterns are anchored on this checkout's path so a
  # stop here never reaches another checkout's table.
  pkill -f "$ROOT/.*GuiPilotMatch" 2>/dev/null
  pkill -f "$ROOT/runner/run_table.sh" 2>/dev/null
  pkill -f "$ROOT/runner/run_advisor.sh" 2>/dev/null
  pkill -f "$ROOT/runner/seat_runner.py" 2>/dev/null
  pkill -f "$ROOT/runner/advisor_runner.py" 2>/dev/null
  sleep 1
fi

# ELO sweep BEFORE the archive: the applier attributes pilots from game.jsonl
# (never archived) and needs unconsumed spool files in runner/results/. Rated
# and skipped spools then ride into the archive; unrated ones stay for the
# next sweep. Never blocks teardown.
python3 "$ROOT/runner/ratings.py" >>"$LOGS/ratings.out" 2>&1 || true

archived=0
# BL-21: archive whenever ANY of the session's log files exists (the old test
# needed seat logs AND gui.out together, so a stop after a partial launch, or
# one that only had game logs left, archived nothing).
have_logs=0
for f in "$LOGS"/seat-*.log "$LOGS"/gui.out "$LOGS"/game.jsonl "$LOGS"/game-*.jsonl; do
  [ -e "$f" ] || [ -L "$f" ] && { have_logs=1; break; }
done
if [ "$have_logs" = 1 ]; then
  A="$LOGS/archive/$(date +%Y%m%d-%H%M%S)-stop"
  mkdir -p "$A"
  # gui.out/run_table.out ride along so the next launch's `>` redirects never
  # clobber a past game's record — every game's full log set survives intact.
  mv "$LOGS"/seat-*.log "$LOGS"/seat-*.jsonl "$LOGS"/seat-*.usage.json \
     "$LOGS"/advisor-0.log "$LOGS"/advisor-0.jsonl "$LOGS"/advisor_runner.out \
     "$LOGS"/gui.out "$LOGS"/run_table.out \
     "$LOGS"/game.jsonl "$LOGS"/game-*.jsonl \
     "$LOGS"/ratings.out "$LOGS"/transport-events.jsonl \
     "$ROOT"/runner/results/*.rated \
     "$ROOT"/runner/results/*.skipped "$ROOT"/runner/results/*.voided "$A/" 2>/dev/null
  archived=$(ls "$A" 2>/dev/null | wc -l | tr -d ' ')
fi
rm -rf "$ROOT"/mailbox/seat-* "$ROOT"/mailbox/observer-state.json "$ROOT"/mailbox/launch-status.json "$LOGS"/control/* 2>/dev/null

runners=$(pgrep -f "seat_runner.py --seat" | wc -l | tr -d ' ')
gui=$(pgrep -f GuiPilotMatch >/dev/null && echo up || echo down)
# BL-21: the session's game.jsonl (and its per-game files) are in the archive
# now; report what went there.
decisions=0; games=0
if [ -n "${A:-}" ] && [ -f "$A/game.jsonl" ]; then
  decisions=$(wc -l < "$A/game.jsonl" | tr -d ' ')
  games=$(ls "$A"/game-*.jsonl 2>/dev/null | grep -v legacy | wc -l | tr -d ' ')
fi
echo "arena stopped: runners=$runners gui=$gui | archived $archived log files | $decisions decisions across $games game(s) (archived)"

# Watchers armed by a driving agent session (digest monitors, log tails) are
# deliberately NOT killed — they re-attach across games by design. Surface
# them so the operator/agent reads it in the teardown output and decides.
obs=$(pgrep -f "^python3? .*arena-digest\.py|^tail -F .*runner/logs" | wc -l | tr -d ' ')
[ "$obs" -gt 0 ] && echo "note: $obs observer process(es) still watching the logs — yours to stop (or keep for the next game)"
exit 0
