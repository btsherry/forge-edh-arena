#!/bin/sh
# Advisor supervisor (BL-26, 2026-09-04): the seat-0 AI Advisor brain in the
# same restart-loop shape as run_table.sh's seats — the loop owns
# logs/pids/advisor-loop.pid (written by arena-play.sh), the current child owns
# logs/pids/advisor.pid (rewritten here on every restart), 2 s damper. The
# advisor is one-way (it only reads the seat-0 shadow feed), so a restart can
# never stall the game; before this it ran once under nohup and one I/O error
# ended it silently while the engine kept filling its inbox.
#
# Usage: run_advisor.sh --deck <slug> [--model M] [--effort E] [--base DIR]
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$DIR/logs/pids"
while true; do
  python3 "$DIR/advisor_runner.py" "$@" &
  child=$!
  echo "$child" > "$DIR/logs/pids/advisor.pid"
  wait "$child"; rc=$?
  echo "[advisor] runner exited ($rc) — restarting in 2s" >&2
  sleep 2
done
