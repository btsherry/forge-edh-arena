#!/bin/bash
# Gate 4 canary (plan §3): a small full-fidelity batch of the EXACT pod
# configuration, auto-checked before any large run. Defaults: 20 games.
# Env: CANARY_GAMES (20), CANARY_WORKERS (4), CANARY_TURNS (30),
#      CANARY_DECKS (space-separated .dck paths; default the 4 baseline decks).
# Checks: crash rate 0; timeout rate < 10%; every seat cast its commander in
# >= 90% of games; every event line parses with game_start/game_end framing.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export JAVA_HOME="${JAVA_HOME:-/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
GAMES="${CANARY_GAMES:-20}"; WORKERS="${CANARY_WORKERS:-4}"; TURNS="${CANARY_TURNS:-30}"
DECKS="${CANARY_DECKS:-$REPO_ROOT/forge-arena/decks/giada-font-of-hope.dck $REPO_ROOT/forge-arena/decks/purphoros-god-of-the-forge.dck $REPO_ROOT/forge-arena/decks/selvala-heart-of-the-wilds.dck $REPO_ROOT/forge-arena/decks/urza-lord-high-artificer.dck}"

RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/arena-canary.XXXXXX")"
SEATS=""
for d in $DECKS; do SEATS="$SEATS{\"deck\": \"$d\"},"; done
cat > "$RUN_DIR/config.json" <<EOF
{
  "run_id": "canary", "seed_base": 42, "games": $GAMES, "workers": $WORKERS,
  "out_dir": "$RUN_DIR/run", "assets_dir": "$REPO_ROOT/forge-gui",
  "limits": {"turns": $TURNS, "wall_clock_sec": 600, "priority_passes_per_turn": 2000},
  "seats": [${SEATS%,}]
}
EOF
bash "$REPO_ROOT/forge-arena/scripts/batch.sh" "$RUN_DIR/config.json"

BATCH_DIR=$(ls -d "$RUN_DIR/run"/*/ | head -1)
python3 - "$BATCH_DIR" $DECKS <<'EOF'
import json, sys, glob, os, re
batch = sys.argv[1]; decks = sys.argv[2:]
# commander names from each .dck's [Commander] section
commanders = []
for d in decks:
    section, cmdr = "", None
    for line in open(d):
        s = line.strip()
        if s.startswith("["): section = s.lower(); continue
        m = re.match(r"\d+\s+(.+)", s)
        if section == "[commander]" and m: cmdr = m.group(1); break
    commanders.append(cmdr)
deck_ids = [os.path.basename(d)[:-4] for d in decks]

records = [json.loads(l) for l in open(os.path.join(batch, "game-records.jsonl")) if l.strip()]
games = len(records)
crashes = sum(1 for r in records if r["result"] == "crash")
timeouts = sum(1 for r in records if r["result"] == "timeout_draw")
cmdr_cast = {d: 0 for d in deck_ids}
for ev_file in glob.glob(os.path.join(batch, "events", "*.jsonl")):
    lines = [json.loads(l) for l in open(ev_file) if l.strip()]
    assert lines[0]["t"] == "game_start" and lines[-1]["t"] == "game_end", ev_file
    seats = lines[0]["seats"]
    for idx, deck in enumerate(seats):
        cmdr = commanders[deck_ids.index(deck)]
        if any(l.get("t") == "spell_cast" and l.get("seat") == idx
               and (" cast " + cmdr) in l.get("desc", "") for l in lines):
            cmdr_cast[deck] += 1
fails = []
if crashes: fails.append(f"crash rate {crashes}/{games} (must be 0)")
if timeouts / max(games,1) >= 0.10 and games >= 10:
    fails.append(f"timeout rate {timeouts}/{games} >= 10%")
if games >= 10:  # thresholds are meaningless at validation-sized n; real canaries run 20
    for deck, n in cmdr_cast.items():
        if n / games < 0.90:
            fails.append(f"{deck} cast commander in only {n}/{games} games (<90%)")
else:
    print(f"(n={games} < 10: rate thresholds skipped — run CANARY_GAMES=20 for the real gate)")
print(f"canary: {games} games, crashes={crashes}, timeouts={timeouts}, commander_cast={cmdr_cast}")
if fails:
    print("CANARY FAIL:"); [print("  " + f) for f in fails]; sys.exit(1)
print("CANARY PASS")
EOF
