#!/bin/sh
# One-shot launch: teardown -> clean slate -> seat runners -> spectator/human GUI
# -> wait until the match is live -> print ONE status line. Folds the whole
# ~5-round-trip launch dance into a single orchestrator call with no loss of
# function (it just calls arena-stop.sh, run_table.sh, run-pilot-match.sh).
#
# Usage:
#   arena-play.sh --all-ai [--timeout N] [--model M] [--effort E]
#   arena-play.sh --human [deck.dck] [--timeout N] [--model M] [--effort E] [--no-advisor]
# Defaults: model=opus effort=medium timeout=90; human deck=selvala-heart-of-the-wilds.dck
# Human games run the seat-0 AI Advisor BY DEFAULT (2026-08-17, Ben) — teaching
#   commentary in the GUI's Advisor tab + autopass (ARENA_AUTOPASS=off|strict|casts,
#   default casts). --no-advisor opts out; a non-ingested human deck auto-disables
#   it (the game still launches, unadvised). --advisor is accepted as a no-op.
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
MODEL="opus"; EFFORT="medium"; TIMEOUT="90"; ADVISOR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --all-ai) MODE="all-ai"; shift ;;
    --human)  MODE="human"; shift
              case "${1:-}" in *.dck) HUMAN_DECK="$1"; shift ;; esac ;;
    --model)  MODEL="$2"; shift 2 ;;
    --effort) EFFORT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --advisor) ADVISOR=1; shift ;;      # explicit on (the default for --human)
    --no-advisor) ADVISOR=0; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
# Advisor default: ON for human games (Ben, 2026-08-17), N/A for all-ai.
if [ -z "$ADVISOR" ]; then
  [ "$MODE" = "human" ] && ADVISOR=1 || ADVISOR=0
fi
[ "$ADVISOR" = "1" ] && [ "$MODE" != "human" ] && {
  echo "arena: --advisor only applies to --human games; ignoring." >&2; ADVISOR=0; }
# The advisor brain needs the human deck's dossier + primer (same preflight
# the AI seats get). Missing → the game still launches, just unadvised.
if [ "$ADVISOR" = "1" ]; then
  HUMAN_SLUG="${HUMAN_DECK%.dck}"
  if ! PREFLIGHT_DECKS="$HUMAN_SLUG" "$ROOT/runner/run_table.sh" --preflight >/dev/null 2>&1; then
    echo "arena: --advisor disabled — deck '$HUMAN_SLUG' is not ingested (run arena-add-deck.py first)." >&2
    ADVISOR=0
  fi
fi
[ -n "$MODE" ] || { echo "specify --all-ai or --human [deck]" >&2; exit 2; }

ALL=""
[ "$MODE" = "all-ai" ] && ALL="ALL_SEATS=1"

# 0) preflight the AI decks BEFORE tearing down any running game: each AI seat must
# ship deck text + combos + a strategy primer, or brain init crash-loops mid-game.
# Synchronous so the warning reaches the terminal and nothing (incl. teardown) runs.
if ! env $ALL "$ROOT/runner/run_table.sh" --preflight; then
  echo "arena: refusing to start — an AI deck is missing required files (see above)." >&2
  exit 1
fi

# 1) clean slate (reuses arena-stop for teardown+archive+clear)
"$DIR/arena-stop.sh" >/dev/null 2>&1

# 2) seat runners (all four for all-ai; seats 1-3 for human)
env $ALL SEAT_MODEL="$MODEL" SEAT_EFFORT="$EFFORT" ARENA_MAILBOX_TIMEOUT="$TIMEOUT" \
  nohup "$ROOT/runner/run_table.sh" >"$LOGS/run_table.out" 2>&1 &
sleep 3

# 2.5) advisor brain (human mode only): reads the seat-0 shadow feed the GUI
# engine writes; one-way, so it can never stall the game. Backend API keys are
# stripped (plan F-19): only run_table.sh's seat children may hold them —
# env -u is a no-op when the vars are unset, so the Claude path is untouched.
if [ "$ADVISOR" = "1" ]; then
  nohup env -u OPENROUTER_API_KEY -u ARENA_OAI_API_KEY \
    python3 "$ROOT/runner/advisor_runner.py" --deck "$HUMAN_SLUG" \
    --model "$MODEL" --effort "$EFFORT" >"$LOGS/advisor_runner.out" 2>&1 &
fi

# (react-autopass daemon RETIRED from the launch 2026-08-17: its allowlist
# fastpath lives in the seat runners now — zero windows absorbed across the
# last three games. scripts/react-autopass.py remains for manual fallback;
# arena-stop still reaps it if launched by hand.)

# 3) GUI (spectator for all-ai, human seat 0 otherwise)
if [ "$MODE" = "all-ai" ]; then GUI_ARG="--all-ai"; else GUI_ARG="$HUMAN_DECK"; fi
ARENA_MAILBOX_TIMEOUT="$TIMEOUT" ARENA_ADVISOR="$ADVISOR" \
  ARENA_AUTOPASS="${ARENA_AUTOPASS:-casts}" \
  nohup env -u OPENROUTER_API_KEY -u ARENA_OAI_API_KEY \
  "$DIR/run-pilot-match.sh" "$GUI_ARG" >"$LOGS/gui.out" 2>&1 &

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
