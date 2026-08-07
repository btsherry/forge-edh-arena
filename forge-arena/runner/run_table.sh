#!/bin/sh
# Launch the 3 autonomous AI seats (seats 1-3) against the standard table:
#   seat 1 Purphoros / seat 2 Giada / seat 3 Urza  (human plays seat 0 in the GUI)
# Each seat runs in a while-true restart loop — that plus the engine's
# timeout->stock fallback is the whole supervision story.
#
# Usage:  forge-arena/runner/run_table.sh [mailbox-base]
# Env:    ARENA_MAILBOX_TIMEOUT (must match the engine's; default 90)
#         SEAT_MODEL (default sonnet)   SEAT_EFFORT (default low; pinned per seat)
# Watch:  tail -f forge-arena/runner/logs/seat-*.log
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
BASE="${1:-$DIR/../mailbox}"
MODEL="${SEAT_MODEL:-sonnet}"
EFFORT="${SEAT_EFFORT:-low}"
export ARENA_MAILBOX_TIMEOUT="${ARENA_MAILBOX_TIMEOUT:-90}"

seat() { # seat_no deck
  while true; do
    python3 "$DIR/seat_runner.py" --seat "$1" --deck "$2" \
      --model "$MODEL" --effort "$EFFORT" --base "$BASE"
    echo "[seat $1] runner exited ($?) — restarting in 2s" >&2
    sleep 2
  done
}

trap 'kill 0' INT TERM
seat 1 purphoros-god-of-the-forge &
seat 2 giada-font-of-hope &
seat 3 urza-lord-high-artificer &
echo "seatd table up (seats 1-3, model=$MODEL, timeout=${ARENA_MAILBOX_TIMEOUT}s)"
echo "logs: tail -f $DIR/logs/seat-*.log"
wait
