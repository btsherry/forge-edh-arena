#!/bin/sh
# Voice supervisor (2026-09-07): the advisor's spoken voice (voice_runner.py)
# in the same restart-loop shape as run_advisor.sh — the loop owns
# logs/pids/voice-loop.pid (written by arena-play.sh), the current child owns
# logs/pids/voice.pid (rewritten here on every restart), 2 s damper. The voice
# runner is one-way (it reads the advisor's stream and the observer snapshot),
# so a restart can never stall the game. Stock phrases need nothing; live
# lines need ELEVENLABS_API_KEY in the environment.
#
# Usage: run_voice.sh [--logs DIR] [--mailbox DIR]
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$DIR/logs/pids"
while true; do
  python3 "$DIR/voice_runner.py" "$@" &
  child=$!
  echo "$child" > "$DIR/logs/pids/voice.pid"
  wait "$child"; rc=$?
  echo "[voice] runner exited ($rc) — restarting in 2s" >&2
  sleep 2
done
