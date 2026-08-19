#!/bin/sh
# build-light-package.sh — assemble forge-light-llm, the portable Project 2
# package: observable 4-player agentic play (all-AI or human + 3 mailbox
# seats), deck ingestion via arena-add-deck.py, and the per-decision
# observability logs. Nothing from the headless stats harness (Project 1)
# ships: no batch/canary/prep scripts, no atlas/runner-cat docs, no per-deck
# program JSONs or fixtures. Compiled classes ship WHOLESALE (Ben 2026-08-12:
# the exclusion is about workflow surface, not classes inert on a classpath).
#
# This script IS the package manifest — edit here, never hand-curate the tree.
#
# Usage:  forge-arena/packaging/build-light-package.sh [dest] [--force]
#         dest default: <repo>/../forge-light-llm ; --force replaces an
#         existing dest (refused otherwise so a reviewed tree isn't clobbered).
#
# Prereqs: a green `mvn -o -pl forge-arena -am package` (fat jar + classes +
# classpath.txt all fresh — the arena pom runs the full 292-test gate even
# with -DskipTests, so a successful package build IS the green gate).
set -eu

DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$DIR/../.." && pwd)

DEST="$REPO/../forge-light-llm"; FORCE=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    *) DEST="$a" ;;
  esac
done

# The eight decks that ship.
SLUGS="giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds
urza-lord-high-artificer swords-plunder swords-plunder-gc
y-shtola-night-s-blessed sythis-harvests-hand"

FATJAR=$(ls "$REPO"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar 2>/dev/null | head -n1)
CP_TXT="$REPO/forge-arena/target/classpath.txt"
CLASSES="$REPO/forge-arena/target/classes"

# ---- preflight: refuse to package stale or missing build artifacts ----------
[ -n "$FATJAR" ] || { echo "ERROR: fat jar missing — run the arena build first." >&2; exit 1; }
[ -f "$CP_TXT" ]  || { echo "ERROR: $CP_TXT missing — run the arena build first." >&2; exit 1; }
[ -f "$CLASSES/forge/arena/interactive/GuiPilotMatch.class" ] || {
  echo "ERROR: GuiPilotMatch.class missing under $CLASSES." >&2; exit 1; }
KEEP=""
if [ -e "$DEST" ]; then
  [ "$FORCE" = 1 ] || { echo "ERROR: $DEST exists — pass --force to replace it." >&2; exit 1; }
  # Ratings are per-installation state (plan F-25): a rebuild must never
  # destroy a tree's accumulated ELO ladders/history. Stash and restore.
  if ls "$DEST"/forge-arena/runner/ratings.json "$DEST"/forge-arena/runner/ratings-history.jsonl >/dev/null 2>&1; then
    KEEP=$(mktemp -d)
    cp "$DEST"/forge-arena/runner/ratings.json "$DEST"/forge-arena/runner/ratings-history.jsonl "$KEEP/" 2>/dev/null
    echo "[preserve] existing ELO ratings stashed across the rebuild"
  fi
  rm -rf "$DEST"
fi
mkdir -p "$DEST"

echo "[1/9] lib/ — every jar from classpath.txt (order within lib/* is JVM-"
echo "      unspecified; the fat jar precedes lib/* in -cp so its classes win"
echo "      duplicates exactly as in the source tree)"
mkdir -p "$DEST/lib"
tr ':' '\n' < "$CP_TXT" | while IFS= read -r jar; do
  [ -f "$jar" ] || { echo "ERROR: classpath entry missing: $jar" >&2; exit 1; }
  cp "$jar" "$DEST/lib/"
done

echo "[2/9] engine — fat jar + desktop pom (the launcher greps its JVM args)"
mkdir -p "$DEST/forge-gui-desktop/target"
cp "$FATJAR" "$DEST/forge-gui-desktop/target/"
cp "$REPO/forge-gui-desktop/pom.xml" "$DEST/forge-gui-desktop/"

echo "[3/9] arena classes — wholesale (classpath.txt itself does NOT ship;"
echo "      run-pilot-match.sh takes the lib/* branch when lib/ exists)"
mkdir -p "$DEST/forge-arena/target"
rsync -a "$CLASSES/" "$DEST/forge-arena/target/classes/"

echo "[4/9] forge-gui/res — pruned: adventure (separate app), music (optional"
echo "      audio), non-English card names. Everything else ships: the desktop"
echo "      home screen eagerly class-inits every submenu (quest/puzzle/draft),"
echo "      and FModel.initialize reads deckgendecks — pruning those crashed"
echo "      startup (ExceptionInInitializerError via VSubmenuQuestStart)."
mkdir -p "$DEST/forge-gui"
rsync -a \
  --exclude '/adventure/' --exclude '/music/' \
  --exclude '/languages/cardnames-*.txt' \
  "$REPO/forge-gui/res/" "$DEST/forge-gui/res/"

echo "[5/9] decks — the arena-add-deck write set only (deck text, combos,"
echo "      ingest cache); program JSONs/fixtures/reports are Project 1"
for s in $SLUGS; do
  src="$REPO/forge-arena/decks/$s"
  for f in "$REPO/forge-arena/decks/$s.dck" "$src/dossier/deck-cards.json" \
           "$src/dossier/combos.json" \
           "$REPO/forge-arena/docs/primers/$s-deckcheck.md"; do
    [ -f "$f" ] || { echo "ERROR: [$s] missing $f" >&2; exit 1; }
  done
  mkdir -p "$DEST/forge-arena/decks/$s/dossier"
  cp "$REPO/forge-arena/decks/$s.dck" "$DEST/forge-arena/decks/"
  cp "$src/dossier/deck-cards.json" "$src/dossier/combos.json" \
     "$DEST/forge-arena/decks/$s/dossier/"
  [ -d "$src/dossier/.cache" ] && rsync -a "$src/dossier/.cache/" \
     "$DEST/forge-arena/decks/$s/dossier/.cache/"
done

echo "[6/9] docs — primers for the shipped decks + the two rules digests the"
echo "      brains load verbatim (the sole research/ exception)"
mkdir -p "$DEST/forge-arena/docs/primers" "$DEST/forge-arena/docs/research"
for s in $SLUGS; do
  cp "$REPO/forge-arena/docs/primers/$s-deckcheck.md" "$DEST/forge-arena/docs/primers/"
done
cp "$REPO/forge-arena/docs/research/mtg-rules-summary.md" \
   "$REPO/forge-arena/docs/research/mtg-rules-digest-conversion.md" \
   "$DEST/forge-arena/docs/research/"

echo "[7/9] runner — the seatd tree (no tests, no pycache, empty logs/)"
rsync -a --exclude '__pycache__/' --exclude '/tests/' --exclude '/logs/' \
  --exclude '/ratings.json' --exclude '/ratings-history.jsonl' \
  --exclude '/ratings.lock' --exclude '/results/' \
  "$REPO/forge-arena/runner/" "$DEST/forge-arena/runner/"
mkdir -p "$DEST/forge-arena/runner/logs" "$DEST/forge-arena/runner/results" \
  "$DEST/forge-arena/mailbox"
if [ -n "$KEEP" ]; then
  cp "$KEEP"/ratings.json "$KEEP"/ratings-history.jsonl \
     "$DEST/forge-arena/runner/" 2>/dev/null
  rm -rf "$KEEP"
  echo "[preserve] ELO ratings restored into the rebuilt tree"
fi

echo "[8/9] scripts — play/stop/launch/ingest/observe (batch, canary, prep,"
echo "      smoke, discovery harnesses, react-autopass stay home)"
mkdir -p "$DEST/forge-arena/scripts"
for f in arena-play.sh arena-stop.sh run-pilot-match.sh run-gui.sh \
         arena-add-deck.py arena-status.py arena-digest.py react-autopass.py; do
  cp "$REPO/forge-arena/scripts/$f" "$DEST/forge-arena/scripts/"
done

echo "[9/9] top level — README (from packaging/), LICENSE, provenance stamp"
[ -f "$DIR/README.md" ] && cp "$DIR/README.md" "$DEST/README.md" \
  || echo "  WARN: $DIR/README.md not written yet — package has no README"
[ -f "$DIR/PATCH-NOTES.md" ] && cp "$DIR/PATCH-NOTES.md" "$DEST/PATCH-NOTES.md"
cp "$REPO/LICENSE" "$DEST/LICENSE"
{ echo "forge-light-llm — built $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "source: $(git -C "$REPO" rev-parse --short HEAD) ($(git -C "$REPO" branch --show-current))"
} > "$DEST/VERSION"

echo; echo "done: $DEST"
du -sh "$DEST" | awk '{print "  size: " $1}'
find "$DEST" -type f | wc -l | awk '{print "  files: " $1}'