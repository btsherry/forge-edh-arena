#!/bin/sh
# One-shot launch: teardown -> clean slate -> seat runners -> spectator/human GUI
# -> wait until the match is live -> print ONE status line. Folds the whole
# ~5-round-trip launch dance into a single orchestrator call with no loss of
# function (it just calls arena-stop.sh, run_table.sh, run-pilot-match.sh).
#
# Usage:
#   arena-play.sh --all-ai [--timeout N] [--model M] [--effort E]
#   arena-play.sh --human [deck.dck] [--timeout N] [--model M] [--effort E] [--no-advisor]
#   ... [--linger N] [--no-autostop]
# Defaults: model=opus effort=medium timeout=90; human deck=selvala-heart-of-the-wilds.dck
# Auto-teardown (2026-09-04, Ben): once the engine reports gameOver (or the GUI
#   JVM is gone) a sleep-loop watcher lingers --linger seconds (default 60 all-AI,
#   120 human — time to read the final board; Ben shortened it from 600 after
#   game 22) and runs arena-stop.sh. --no-autostop
#   leaves the table up until you stop it by hand.
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
LINGER=""; AUTOSTOP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --all-ai) MODE="all-ai"; shift ;;
    --human)  MODE="human"; shift
              case "${1:-}" in *.dck) HUMAN_DECK="$1"; shift ;; esac ;;
    --model|--effort|--timeout)
              [ $# -ge 2 ] || { echo "arena: $1 needs a value" >&2; exit 2; }   # item 13g
              case "$1" in --model) MODEL="$2" ;; --effort) EFFORT="$2" ;; --timeout) TIMEOUT="$2" ;; esac
              shift 2 ;;
    --linger) [ $# -ge 2 ] || { echo "arena: --linger needs a value (seconds)" >&2; exit 2; }
              case "$2" in ''|*[!0-9]*) echo "arena: --linger takes a whole number of seconds (got '$2')" >&2; exit 2 ;; esac
              LINGER="$2"; shift 2 ;;
    --no-autostop) AUTOSTOP=0; shift ;;
    --advisor) ADVISOR=1; shift ;;      # explicit on (the default for --human)
    --no-advisor) ADVISOR=0; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
# BL-27: deck files are slugs by construction; a name with whitespace would
# word-split in three scripts and surface as an unexplained preflight failure.
case "$HUMAN_DECK" in *[[:space:]]*)
  echo "arena: deck file names must not contain whitespace: '$HUMAN_DECK' — rename it to a slug (e.g. my-deck.dck)" >&2; exit 2 ;;
esac
HUMAN_SLUG=$(basename "$HUMAN_DECK" .dck)   # item 13g: a path prefix used to break the slug
# Advisor default: ON for human games (Ben, 2026-08-17), N/A for all-ai.
if [ -z "$ADVISOR" ]; then
  [ "$MODE" = "human" ] && ADVISOR=1 || ADVISOR=0
fi
[ "$ADVISOR" = "1" ] && [ "$MODE" != "human" ] && {
  echo "arena: --advisor only applies to --human games; ignoring." >&2; ADVISOR=0; }
# The advisor brain needs the human deck's dossier + primer (same preflight
# the AI seats get). Missing → the game still launches, just unadvised.
if [ "$ADVISOR" = "1" ]; then
  if ! pf_err=$(PREFLIGHT_DECKS="$HUMAN_SLUG" "$ROOT/runner/run_table.sh" --preflight 2>&1 >/dev/null); then
    # item 13g: say WHAT failed — this used to report every preflight failure
    # (a missing OpenRouter key, a backend model on seat 0) as "not ingested"
    echo "arena: --advisor disabled — preflight for deck '$HUMAN_SLUG' failed:" >&2
    printf '%s\n' "$pf_err" | sed 's/^/    /' >&2
    ADVISOR=0
  fi
fi
[ -n "$MODE" ] || { echo "specify --all-ai or --human [deck]" >&2; exit 2; }
# Linger default: a spectator table has nobody reading the board; a human does.
[ -n "$LINGER" ] || { [ "$MODE" = "human" ] && LINGER=120 || LINGER=60; }

# Item R (Ben, 2026-09-04): run_table.sh seats the AI decks from the roster
# rule (all-AI: roster order; human: the first three roster decks that are not
# the human's). The human's slug is what the rule needs.
ALL="ARENA_HUMAN_DECK=$HUMAN_SLUG"
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
mkdir -p "$LOGS/pids"   # item 13e: every process this launch starts leaves a PID file

# 2) seat runners (all four for all-ai; seats 1-3 for human)
env $ALL SEAT_MODEL="$MODEL" SEAT_EFFORT="$EFFORT" ARENA_MAILBOX_TIMEOUT="$TIMEOUT" \
  nohup "$ROOT/runner/run_table.sh" >"$LOGS/run_table.out" 2>&1 &
echo $! > "$LOGS/pids/run_table.pid"
sleep 3

# 2.5) advisor brain (human mode only): reads the seat-0 shadow feed the GUI
# engine writes; one-way, so it can never stall the game. Backend API keys are
# stripped (plan F-19): only run_table.sh's seat children may hold them —
# env -u is a no-op when the vars are unset, so the Claude path is untouched.
# BL-26: supervised like the seats (runner/run_advisor.sh restart loop); the
# loop writes advisor.pid per restart, this PID is the loop itself.
if [ "$ADVISOR" = "1" ]; then
  nohup env -u OPENROUTER_API_KEY -u ARENA_OAI_API_KEY \
    "$ROOT/runner/run_advisor.sh" --deck "$HUMAN_SLUG" \
    --model "$MODEL" --effort "$EFFORT" >"$LOGS/advisor_runner.out" 2>&1 &
  echo $! > "$LOGS/pids/advisor-loop.pid"
fi

# 3) GUI (spectator for all-ai, human seat 0 otherwise)
if [ "$MODE" = "all-ai" ]; then GUI_ARG="--all-ai"; else GUI_ARG="$HUMAN_DECK"; fi
ARENA_MAILBOX_TIMEOUT="$TIMEOUT" ARENA_ADVISOR="$ADVISOR" \
  ARENA_AUTOPASS="${ARENA_AUTOPASS:-casts}" \
  nohup env -u OPENROUTER_API_KEY -u ARENA_OAI_API_KEY \
  "$DIR/run-pilot-match.sh" "$GUI_ARG" >"$LOGS/gui.out" 2>&1 &
echo $! > "$LOGS/pids/gui.pid"   # run-pilot-match execs java, so this IS the JVM

# 4) wait until the match is actually live — or until the engine refuses the
# launch (item 7: a seat short of 100 real cards writes launch-status.json
# with ok:false and exits; say so at once instead of after the 150 s wait)
i=0
while [ ! -f "$ROOT/mailbox/observer-state.json" ] && [ $i -lt 50 ]; do
  if [ -f "$ROOT/mailbox/launch-status.json" ] && grep -q '"ok": false' "$ROOT/mailbox/launch-status.json"; then
    echo "arena launch REFUSED by the engine:" >&2
    python3 -c 'import json,sys; print("   ", json.load(open(sys.argv[1]))["detail"])' "$ROOT/mailbox/launch-status.json" >&2
    "$DIR/arena-stop.sh" >/dev/null 2>&1
    exit 1
  fi
  sleep 3; i=$((i+1))
done

# 5) one status line
if [ -f "$ROOT/mailbox/observer-state.json" ]; then
  seats=$(python3 "$ROOT/runner/arena-ctl.py" status 2>/dev/null | grep -c "model=")
  echo "arena live [$MODE]: $seats AI seats @ $MODEL/$EFFORT, timeout=${TIMEOUT}s"$([ "$MODE" = human ] && echo ", human=$HUMAN_DECK")
  # 6) auto-teardown once the match has clearly concluded (Ben, 2026-09-04):
  # a plain sleep-loop watcher (no scheduler) waits for the engine's gameOver
  # flag or the GUI JVM to vanish, lingers, then runs arena-stop.sh exactly as
  # a hand stop would. arena-stop kills a waiting watcher by this PID file.
  if [ "$AUTOSTOP" = 1 ]; then
    nohup "$DIR/arena-autostop.sh" "$LINGER" >"$LOGS/autostop.out" 2>&1 &
    echo $! > "$LOGS/pids/autostop.pid"
    echo "  auto-stop: ${LINGER}s after game over (--linger N / --no-autostop)"
  fi
else
  echo "arena launch: runners up but match not live after ~150s — check $LOGS/gui.out"
  exit 1
fi
