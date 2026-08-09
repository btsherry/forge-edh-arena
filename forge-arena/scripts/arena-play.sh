#!/bin/sh
# One-shot launch: teardown -> clean slate -> seat runners -> spectator/human GUI
# -> wait until the match is live -> print ONE status line. Folds the whole
# ~5-round-trip launch dance into a single orchestrator call with no loss of
# function (it just calls arena-stop.sh, run_table.sh, run-pilot-match.sh).
#
# Usage:
#   arena-play.sh --all-ai [--timeout N] [--model M] [--effort E]
#   arena-play.sh --human [deck.dck] [--timeout N] [--model M] [--effort E]
# Defaults: model=opus effort=medium timeout=90; human deck=selvala-heart-of-the-wilds.dck
#
# Notes:
#  - max/xhigh effort needs --timeout 300 or the seat punts past the 90s deadline.
#  - runs runners + GUI in the background (nohup); this script returns once the
#    match is live (observer-state.json appears) or after a ~150s guard.
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$DIR/.." && pwd)
LOGS="$ROOT/runner/logs"

MODE=""; HUMAN_DECK="selvala-heart-of-the-wilds.dck"
MODEL="opus"; EFFORT="medium"; TIMEOUT="90"
while [ $# -gt 0 ]; do
  case "$1" in
    --all-ai) MODE="all-ai"; shift ;;
    --human)  MODE="human"; shift
              case "${1:-}" in *.dck) HUMAN_DECK="$1"; shift ;; esac ;;
    --model)  MODEL="$2"; shift 2 ;;
    --effort) EFFORT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$MODE" ] || { echo "specify --all-ai or --human [deck]" >&2; exit 2; }

# 1) clean slate (reuses arena-stop for teardown+archive+clear)
"$DIR/arena-stop.sh" >/dev/null 2>&1

# 2) seat runners (all four for all-ai; seats 1-3 for human)
ALL=""
[ "$MODE" = "all-ai" ] && ALL="ALL_SEATS=1"
env $ALL SEAT_MODEL="$MODEL" SEAT_EFFORT="$EFFORT" ARENA_MAILBOX_TIMEOUT="$TIMEOUT" \
  nohup "$ROOT/runner/run_table.sh" >"$LOGS/run_table.out" 2>&1 &
sleep 3

# 3) GUI (spectator for all-ai, human seat 0 otherwise)
if [ "$MODE" = "all-ai" ]; then GUI_ARG="--all-ai"; else GUI_ARG="$HUMAN_DECK"; fi
ARENA_MAILBOX_TIMEOUT="$TIMEOUT" \
  nohup "$DIR/run-pilot-match.sh" "$GUI_ARG" >"$LOGS/gui.out" 2>&1 &

# 4) wait until the match is actually live
i=0
while [ ! -f "$ROOT/mailbox/observer-state.json" ] && [ $i -lt 50 ]; do
  sleep 3; i=$((i+1))
done

# 5) one status line
if [ -f "$ROOT/mailbox/observer-state.json" ]; then
  seats=$(python3 "$ROOT/runner/arena-ctl.py" status 2>/dev/null | grep -c "model=")
  echo "arena live [$MODE]: $seats AI seats @ $MODEL/$EFFORT, timeout=${TIMEOUT}s"$([ "$MODE" = human ] && echo ", human=$HUMAN_DECK")
else
  echo "arena launch: runners up but match not live after ~150s — check $LOGS/gui.out"
  exit 1
fi
