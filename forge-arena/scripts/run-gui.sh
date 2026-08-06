#!/bin/sh
# Launch the Forge desktop GUI from the source tree.
#
# The critical fact: the desktop jar resolves `res/` (skins, card data, etc.)
# relative to the CURRENT WORKING DIRECTORY, so it MUST be run from forge-gui/.
# The stock forge.sh cd's into target/ and fails with "can't find skins directory".
# This wrapper cd's to forge-gui/ first, then runs the built jar.
#
# Usage: forge-arena/scripts/run-gui.sh [extra args passed to forge.view.Main]
#   (no args launches the GUI; e.g. `sim ...` would run headless instead)
#
# JAVA_HOME is honored if set; otherwise `java` on PATH is used (needs JDK 17+).
set -eu

# Resolve the repo root from this script's own location (portable regardless of cwd).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

GUI_DIR="$REPO_ROOT/forge-gui"
TARGET_DIR="$REPO_ROOT/forge-gui-desktop/target"

# Auto-detect the assembled jar so this survives version bumps.
JAR=$(ls "$TARGET_DIR"/forge-gui-desktop-*-jar-with-dependencies.jar 2>/dev/null | head -n1)

if [ -z "${JAR:-}" ]; then
  echo "ERROR: no jar-with-dependencies.jar found in $TARGET_DIR" >&2
  echo "       build it first, e.g.: mvn -pl forge-gui-desktop -am -P osx -DskipTests package" >&2
  exit 1
fi

if [ -n "${JAVA_HOME:-}" ]; then
  JAVA="$JAVA_HOME/bin/java"
else
  JAVA="java"
fi

# The --add-opens flags are baked into the jar manifest; only these -D/-Xmx args are needed.
JVM_ARGS="-Xmx4096m -Dio.netty.tryReflectionSetAccessible=true -Dfile.encoding=UTF-8"

echo "Forge GUI launcher"
echo "  repo root : $REPO_ROOT"
echo "  run dir   : $GUI_DIR   (res/ lives here)"
echo "  jar       : $JAR"
echo "  java      : $("$JAVA" -version 2>&1 | head -n1)"
echo

cd "$GUI_DIR"
exec "$JAVA" $JVM_ARGS -jar "$JAR" "$@"
