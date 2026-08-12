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
AROOT=$(cd "$DIR/.." && pwd)          # forge-arena/
# --preflight: only verify every AI seat ships its context files, then exit
# 0 (all present) / 1 (any missing). arena-play.sh calls this as a launch gate.
PREFLIGHT_ONLY=0
if [ "${1:-}" = "--preflight" ]; then PREFLIGHT_ONLY=1; shift; fi
BASE="${1:-$DIR/../mailbox}"
MODEL="${SEAT_MODEL:-sonnet}"
EFFORT="${SEAT_EFFORT:-low}"
export ARENA_MAILBOX_TIMEOUT="${ARENA_MAILBOX_TIMEOUT:-90}"
# SEAT_SPECULATIVE=1 enables executable turn plans; SEAT_REACT_HOLD=1 enables
# the same-turn reactive hold posture. Both default off.
SPEC_FLAG=""
[ "${SEAT_SPECULATIVE:-0}" = "1" ] && SPEC_FLAG="--speculative"
HOLD_FLAG=""
[ "${SEAT_REACT_HOLD:-0}" = "1" ] && HOLD_FLAG="--react-hold"

seat() { # seat_no deck
  while true; do
    python3 "$DIR/seat_runner.py" --seat "$1" --deck "$2" \
      --model "$MODEL" --effort "$EFFORT" --base "$BASE" $SPEC_FLAG $HOLD_FLAG
    echo "[seat $1] runner exited ($?) — restarting in 2s" >&2
    sleep 2
  done
}

# Table roster in seat order (0-3) — override with ARENA_SEAT_DECKS (four deck
# slugs, space-separated). GuiPilotMatch reads the same roster via the
# arena.seat.decks property (run-pilot-match.sh forwards ARENA_SEAT_DECKS), so
# the engine's seats and the brains launched here move together. ALL_SEATS also
# seats seat 0. PREFLIGHT_DECKS lets a caller (or a test) check an explicit set.
TABLE="${ARENA_SEAT_DECKS:-selvala-heart-of-the-wilds purphoros-god-of-the-forge giada-font-of-hope urza-lord-high-artificer}"
# shellcheck disable=SC2086  # intentional word split: TABLE is a slug list
set -- $TABLE
[ $# -eq 4 ] || { echo "[run_table] ARENA_SEAT_DECKS must list exactly 4 deck slugs in seat order (got $#: $TABLE)" >&2; exit 1; }
D0=$1; D1=$2; D2=$3; D3=$4
AI_DECKS="$D1 $D2 $D3"
[ "${ALL_SEATS:-0}" = "1" ] && AI_DECKS="$D0 $AI_DECKS"
AI_DECKS="${PREFLIGHT_DECKS:-$AI_DECKS}"

# Startup preflight: every AI seat needs deck text + combos + a strategy primer
# (brain.py reads all three), plus the two shared rules digests + seat brief it
# also reads unguarded. If any are missing, brain init throws and the seat
# crash-loops mid-game — so refuse to start, list every gap, and point at the fix.
preflight_decks() {
  miss=""
  for f in "docs/research/mtg-rules-summary.md" \
           "docs/research/mtg-rules-digest-conversion.md" \
           "runner/seatd/seat-brief.md"; do
    [ -f "$AROOT/$f" ] || miss="$miss\n  [shared]  MISSING $f"
  done
  for d in $AI_DECKS; do
    [ -f "$AROOT/decks/$d/dossier/deck-cards.json" ] || miss="$miss\n  [$d]  MISSING deck text  (decks/$d/dossier/deck-cards.json)"
    [ -f "$AROOT/decks/$d/dossier/combos.json" ]     || miss="$miss\n  [$d]  MISSING combos     (decks/$d/dossier/combos.json)"
    [ -f "$AROOT/docs/primers/$d-deckcheck.md" ]     || miss="$miss\n  [$d]  MISSING strategy   (docs/primers/$d-deckcheck.md)"
  done
  if [ -n "$miss" ]; then
    printf '%b\n' "[run_table] PREFLIGHT FAILED — required files missing:$miss" >&2
    printf '%s\n' "[run_table] fix: scripts/arena-add-deck.py <deck.dck>  (writes deck text + combos + primer), then relaunch." >&2
    return 1
  fi
  printf '%s\n' "[run_table] preflight OK — AI decks: $AI_DECKS"
  return 0
}

if [ "$PREFLIGHT_ONLY" = "1" ]; then
  preflight_decks
  exit $?
fi
preflight_decks || exit 1

trap 'kill 0' INT TERM
if [ "${ALL_SEATS:-0}" = "1" ]; then
  seat 0 "$D0" &   # all-AI mode: 4th brain takes seat 0
fi
seat 1 "$D1" &
seat 2 "$D2" &
seat 3 "$D3" &
echo "seatd table up (seats 1-3, model=$MODEL, timeout=${ARENA_MAILBOX_TIMEOUT}s)"
echo "logs: tail -f $DIR/logs/seat-*.log"
wait
