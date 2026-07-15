#!/bin/bash
# Launch an arena batch: batch.sh <batch-config.json>
# JVM flags (plan W6): orchestrator is light; each worker gets -Xmx2g
# (override per config "worker_heap"). Workers are separate JVMs — one game
# at a time per JVM keeps MyRandom seeding deterministic.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONFIG="${1:?usage: batch.sh <batch-config.json>}"
export JAVA_HOME="${JAVA_HOME:-/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"

CP_FILE="$REPO_ROOT/forge-arena/target/classpath.txt"
if [ ! -f "$CP_FILE" ] || [ "$REPO_ROOT/forge-arena/pom.xml" -nt "$CP_FILE" ]; then
  echo "resolving classpath..."
  (cd "$REPO_ROOT" && mvn -pl forge-arena -q dependency:build-classpath \
      -Dmdep.outputFile="$CP_FILE" -Dcheckstyle.skip=true)
fi
CP="$REPO_ROOT/forge-arena/target/classes:$(cat "$CP_FILE")"

cd "$REPO_ROOT"
exec "$JAVA_HOME/bin/java" -Xmx512m -cp "$CP" forge.arena.harness.BatchMain "$CONFIG"
