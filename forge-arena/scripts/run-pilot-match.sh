#!/bin/sh
# Launch a 4-player Commander game in the DESKTOP GUI where seat 0 is a HUMAN
# and seats 1-3 are file-driven MailboxLobbyPlayer opponents (see
# forge.arena.interactive.GuiPilotMatch).
#
# Like run-gui.sh, this MUST run from forge-gui/ because the desktop GUI resolves
# res/ (skins, card DB) relative to the working directory. GuiPilotMatch does NOT
# read an assets-dir property, so cwd is the only lever — hence the cd below and
# absolute paths for everything else.
#
# Because we launch via -cp (not -jar), the jar-manifest Add-Opens do NOT apply,
# so we pass the desktop JVM args (mandatory + add-opens) explicitly. They are
# extracted from forge-gui-desktop/pom.xml so they can't drift from the build.
#
# Usage:
#   forge-arena/scripts/run-pilot-match.sh [humanDeckFileName] [busDir]
#     arg 0: which deck the human plays (default selvala-heart-of-the-wilds.dck)
#     arg 1: mailbox bus dir override
#
# Env:
#   ARENA_MAILBOX_TIMEOUT  seconds a mailbox seat waits for a brain before
#                          falling back to stock AI (default 300).
#                          Use a SMALL value (e.g. 3) for a no-brains smoke test.
#   ARENA_MAILBOX_DIR      override the mailbox base dir.
#   ARENA_SEAT_DECKS       four deck slugs in seat order — repoints the table
#                          roster (forwarded as -Darena.seat.decks; keep the
#                          same value on run_table.sh so brains match seats).
#   JAVA_HOME              honored if set; else `java` on PATH (needs JDK 17+).
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

GUI_DIR="$REPO_ROOT/forge-gui"
ARENA_CLASSES="$REPO_ROOT/forge-arena/target/classes"
ARENA_CP_TXT="$REPO_ROOT/forge-arena/target/classpath.txt"
DESKTOP_POM="$REPO_ROOT/forge-gui-desktop/pom.xml"
DECKS_DIR="$REPO_ROOT/forge-arena/decks"
MAILBOX_DIR="${ARENA_MAILBOX_DIR:-$REPO_ROOT/forge-arena/mailbox}"
TIMEOUT="${ARENA_MAILBOX_TIMEOUT:-300}"

# Self-contained desktop jar (all forge + deps); survives version bumps.
JAR=$(ls "$REPO_ROOT"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar 2>/dev/null | head -n1)
if [ -z "$JAR" ]; then
  echo "ERROR: no forge-gui-desktop jar-with-dependencies.jar found — build it first." >&2
  exit 1
fi
if [ ! -f "$ARENA_CLASSES/forge/arena/interactive/GuiPilotMatch.class" ]; then
  echo "ERROR: GuiPilotMatch not compiled at $ARENA_CLASSES — compile the interactive package first." >&2
  exit 1
fi
# Classpath tail — dual-mode, one script for both worlds:
#   source tree:   reactor-generated classpath.txt (absolute paths incl. ~/.m2);
#   packaged tree: a flat lib/ of jars at the package root (forge-light-llm).
# lib/ wins when present; the source tree has no lib/, so its behavior is
# unchanged. The wildcard stays quoted so the JVM, not the shell, expands it —
# and the fat jar still precedes it, so fat-jar classes win duplicates as today.
if [ -d "$REPO_ROOT/lib" ]; then
  CP_EXTRA="$REPO_ROOT/lib/*"
elif [ -f "$ARENA_CP_TXT" ]; then
  CP_EXTRA=$(cat "$ARENA_CP_TXT")
else
  echo "ERROR: no classpath source — need $REPO_ROOT/lib/ (packaged tree) or $ARENA_CP_TXT (source tree: run the arena build once; it bundles Jackson + module deps the fat jar lacks)." >&2
  exit 1
fi

# Extract the desktop JVM args from the pom (single-line values, no '<' inside).
MAND=$(grep -o '<mandatory.java.args>[^<]*</mandatory.java.args>' "$DESKTOP_POM" | sed 's/<[^>]*>//g')
OPENS=$(grep -o '<addopen.java.args>[^<]*</addopen.java.args>' "$DESKTOP_POM" | sed 's/<[^>]*>//g')
if [ -z "$MAND" ] || [ -z "$OPENS" ]; then
  echo "ERROR: could not extract JVM args from $DESKTOP_POM" >&2
  exit 1
fi

if [ -n "${JAVA_HOME:-}" ]; then JAVA="$JAVA_HOME/bin/java"; else JAVA="java"; fi

# Table roster pass-through: spaces become commas so the property stays one
# JVM argument (GuiPilotMatch splits on both). Empty when unset — the word
# then vanishes from the (intentionally unquoted) exec arg list.
SEAT_DECKS_ARG=""
[ -n "${ARENA_SEAT_DECKS:-}" ] && \
  SEAT_DECKS_ARG="-Darena.seat.decks=$(printf '%s' "$ARENA_SEAT_DECKS" | tr ' ' ',')"

echo "Forge GUI pilot match"
echo "  run dir      : $GUI_DIR   (res/ lives here)"
echo "  human deck   : ${1:-selvala-heart-of-the-wilds.dck}"
echo "  mailbox dir  : $MAILBOX_DIR   (seat-<id>/inbox|outbox)"
echo "  brain timeout: ${TIMEOUT}s (falls back to stock AI after this)"
echo "  java         : $("$JAVA" -version 2>&1 | head -n1)"
echo

cd "$GUI_DIR"
# shellcheck disable=SC2086  # MAND/OPENS are intentional multi-arg word lists
exec "$JAVA" $MAND $OPENS $SEAT_DECKS_ARG \
  -Darena.decks.dir="$DECKS_DIR" \
  -Darena.mailbox.dir="$MAILBOX_DIR" \
  -Darena.mailbox.timeout.sec="$TIMEOUT" \
  -Darena.runner.logs.dir="$REPO_ROOT/forge-arena/runner/logs" \
  -cp "$ARENA_CLASSES:$JAR:$CP_EXTRA" \
  forge.arena.interactive.GuiPilotMatch "$@"
