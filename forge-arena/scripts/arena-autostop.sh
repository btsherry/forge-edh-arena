#!/bin/sh
# Ends a table that has clearly concluded (Ben, 2026-09-04). A plain sleep
# loop, no scheduler: wait until the engine's observer snapshot says gameOver
# (or the GUI JVM is gone — a table with no engine can never finish), linger
# so the final board can be read, then run arena-stop.sh exactly as a hand
# stop would (kill by PID file, rate, archive, clear). Started by arena-play.sh
# once the match is live; arena-stop kills a waiting watcher by its PID file.
#
# Usage: arena-autostop.sh [linger-seconds]      (default 60)
# Exit 0 without stopping anything when the table was already stopped
# (mailbox + pids cleared) — a hand arena-stop always wins.
#
# Test hooks (env, defaults are the live paths):
#   ARENA_AUTOSTOP_STATE         observer snapshot (mailbox/observer-state.json)
#   ARENA_AUTOSTOP_GUI_PID_FILE  the GUI JVM's PID file (runner/logs/pids/gui.pid)
#   ARENA_AUTOSTOP_PID_FILE      this watcher's own PID file (removed before stopping)
#   ARENA_AUTOSTOP_STOP          the stop command (scripts/arena-stop.sh)
#   ARENA_AUTOSTOP_POLL          seconds between checks (5)
#   ARENA_AUTOSTOP_GUI_GONE_LINGER  linger when the GUI vanished before game over (10)
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$DIR/.." && pwd)
LOGS="$ROOT/runner/logs"

LINGER="${1:-60}"
case "$LINGER" in ''|*[!0-9]*) echo "arena-autostop: linger must be a whole number of seconds (got '$LINGER')" >&2; exit 2 ;; esac
STATE="${ARENA_AUTOSTOP_STATE:-$ROOT/mailbox/observer-state.json}"
GUI_PID_FILE="${ARENA_AUTOSTOP_GUI_PID_FILE:-$LOGS/pids/gui.pid}"
OWN_PID_FILE="${ARENA_AUTOSTOP_PID_FILE:-$LOGS/pids/autostop.pid}"
STOP="${ARENA_AUTOSTOP_STOP:-$DIR/arena-stop.sh}"
POLL="${ARENA_AUTOSTOP_POLL:-5}"
GUI_GONE_LINGER="${ARENA_AUTOSTOP_GUI_GONE_LINGER:-10}"

say() { echo "$(date '+%H:%M:%S') arena-autostop: $*"; }

# gameOver is written by ObserverSnapshot on the outcome event (a forced
# write), so a true here is the engine's own word that the match is over.
over() {
  python3 - "$STATE" <<'PY' 2>/dev/null
import json, sys
try:
    sys.exit(0 if json.load(open(sys.argv[1])).get("gameOver") is True else 1)
except Exception:
    sys.exit(1)
PY
}
# The PID file is written by arena-play.sh; run-pilot-match.sh execs java,
# so that PID IS the engine JVM. A recorded PID that no longer exists means
# the window was closed or the JVM died.
gui_gone() {
  p=$(cat "$GUI_PID_FILE" 2>/dev/null)
  [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null
}
# arena-stop removes the snapshot AND every PID file; both gone = stopped.
stopped_already() { [ ! -f "$STATE" ] && [ ! -f "$GUI_PID_FILE" ]; }

while :; do
  if stopped_already; then say "table already stopped — nothing to do"; rm -f "$OWN_PID_FILE"; exit 0; fi
  if over; then why="match over (engine reports gameOver)"; break; fi
  if gui_gone; then why="GUI JVM gone before game over"; LINGER="$GUI_GONE_LINGER"; break; fi
  sleep "$POLL"
done

say "$why — stopping in ${LINGER}s (a hand arena-stop.sh now is fine too)"
sleep "$LINGER"
if stopped_already; then say "stopped by someone else meanwhile — nothing to do"; rm -f "$OWN_PID_FILE"; exit 0; fi
rm -f "$OWN_PID_FILE"   # this process becomes arena-stop; its old PID file must not name it
say "running $STOP"
exec "$STOP"
