#!/bin/bash
# CI smoke gate (plan §11): build + unit tests + small canary batch.
# Env overrides: SMOKE_GAMES (default 8), SMOKE_WORKERS (2), SMOKE_TURNS (10).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export JAVA_HOME="${JAVA_HOME:-/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
GAMES="${SMOKE_GAMES:-8}"; WORKERS="${SMOKE_WORKERS:-2}"; TURNS="${SMOKE_TURNS:-10}"

echo "== build + unit tests =="
(cd "$REPO_ROOT" && mvn -pl forge-arena -am install -DskipTests -Dcheckstyle.skip=true -q)
# (forge-arena's surefire pins skipTests=false, so its own tests ran above)

echo "== canary batch: $GAMES games / $WORKERS workers / turn cap $TURNS =="
RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/arena-smoke.XXXXXX")"
CONFIG="$RUN_DIR/config.json"
cat > "$CONFIG" <<EOF
{
  "run_id": "smoke",
  "seed_base": 42,
  "games": $GAMES,
  "workers": $WORKERS,
  "out_dir": "$RUN_DIR/run",
  "assets_dir": "$REPO_ROOT/forge-gui",
  "limits": {"turns": $TURNS, "wall_clock_sec": 300, "priority_passes_per_turn": 2000},
  "seats": [
    {"deck": "$REPO_ROOT/forge-arena/decks/giada-font-of-hope.dck"},
    {"deck": "$REPO_ROOT/forge-arena/decks/purphoros-god-of-the-forge.dck"},
    {"deck": "$REPO_ROOT/forge-arena/decks/selvala-heart-of-the-wilds.dck"},
    {"deck": "$REPO_ROOT/forge-arena/decks/urza-lord-high-artificer.dck"}
  ]
}
EOF
bash "$REPO_ROOT/forge-arena/scripts/batch.sh" "$CONFIG"

echo "== canary checks =="
BATCH_DIR=$(ls -d "$RUN_DIR/run"/*/ 2>/dev/null | head -1)
[ -n "$BATCH_DIR" ] || { echo "FAIL: no batch dir under $RUN_DIR/run"; exit 1; }
RECORDS="${BATCH_DIR}game-records.jsonl"
COUNT=$(wc -l < "$RECORDS" | tr -d ' ')
CRASHES=$(grep -c '"result":"crash"' "$RECORDS" || true)
[ "$COUNT" -eq "$GAMES" ] || { echo "FAIL: $COUNT/$GAMES records"; exit 1; }
[ "$CRASHES" -eq 0 ] || { echo "FAIL: $CRASHES crash records"; exit 1; }
[ -s "${BATCH_DIR}run.log" ] || { echo "FAIL: empty run.log"; exit 1; }
[ -s "$RUN_DIR/run/batches.jsonl" ] || { echo "FAIL: no batch ledger"; exit 1; }
echo "SMOKE PASS: $COUNT games, 0 crashes  ($BATCH_DIR)"
