#!/bin/sh
# One-shot teardown: kill GUI + all seat runners, archive this game's per-seat
# logs (game.jsonl is preserved and keeps accumulating), clear the mailbox +
# control files. Prints a single summary line. Zero-fidelity-loss consolidation
# of the multi-step teardown so the orchestrator spends one round trip, not five.
#
# Usage: forge-arena/scripts/arena-stop.sh
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$DIR/.." && pwd)          # forge-arena/
LOGS="$ROOT/runner/logs"

pkill -f "GuiPilotMatch" 2>/dev/null
pkill -f "run_table.sh" 2>/dev/null
pkill -f "seat_runner.py --seat" 2>/dev/null
sleep 1

archived=0
if ls "$LOGS"/seat-*.log >/dev/null 2>&1; then
  A="$LOGS/archive/$(date +%Y%m%d-%H%M%S)-stop"
  mkdir -p "$A"
  mv "$LOGS"/seat-*.log "$LOGS"/seat-*.jsonl "$LOGS"/seat-*.usage.json "$A/" 2>/dev/null
  archived=$(ls "$A" 2>/dev/null | wc -l | tr -d ' ')
fi
rm -rf "$ROOT"/mailbox/seat-* "$ROOT"/mailbox/observer-state.json "$LOGS"/control/* 2>/dev/null

runners=$(pgrep -f "seat_runner.py --seat" | wc -l | tr -d ' ')
gui=$(pgrep -f GuiPilotMatch >/dev/null && echo up || echo down)
decisions=0
[ -f "$LOGS/game.jsonl" ] && decisions=$(wc -l < "$LOGS/game.jsonl" | tr -d ' ')
echo "arena stopped: runners=$runners gui=$gui | archived $archived log files | game.jsonl=${decisions:-0} decisions (preserved)"
