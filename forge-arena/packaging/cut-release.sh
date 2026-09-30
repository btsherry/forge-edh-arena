#!/bin/sh
# cut-release.sh — build, check and tar a forge-light-llm release from the COMMITTED tree (2026-09-30; the
# steps every cut since v3.3 ran by hand or from a scratchpad script that was lost twice between sessions).
#
#   1. refuse a dirty tree — the package's VERSION stamp names HEAD, and HEAD must be the release commit
#   2. build-light-package.sh --force            (needs a green `mvn -o -pl forge-arena -am package` beforehand)
#   3. the packaging checks: VERSION stamp = HEAD, exactly one fat jar, no home paths, no key-shaped strings,
#      ten decks, the four voice libraries, every manifest phrase has its baked take (check-voice-takes.py),
#      preflight OK from the package root
#   4. tar from the parent directory (COPYFILE_DISABLE=1: no macOS resource forks), then bytes / entries / sha256
#
# Usage:  forge-arena/packaging/cut-release.sh YYYYMMDD[b]
#   e.g.  forge-arena/packaging/cut-release.sh 20260930      -> ~/Claude/personal/forge-light-llm-20260930.tar.gz
# Then ship it:  forge-arena/packaging/ship-release-s3.py <tarball> forge-light-llm-YYYYMMDD.tar.gz [--latest]
# (ship-release.sh for a tarball under 300 MiB). Dev-only; not part of the package.
set -eu
STAMP=${1:?release date, e.g. 20260930 (a b-suffix for a same-day re-cut)}
DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$DIR/../.." && pwd)
DEST="$REPO/../forge-light-llm"
TAR="$REPO/../forge-light-llm-$STAMP.tar.gz"
HEAD_SHA=$(git -C "$REPO" rev-parse --short HEAD)
if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
  echo "cut: the tree is dirty — commit the release docs first; the VERSION stamp names HEAD" >&2; exit 1
fi
echo "== [1/4] release commit $HEAD_SHA ($(git -C "$REPO" branch --show-current))"
echo "== [2/4] build"
"$DIR/build-light-package.sh" --force | tail -3
echo "== [3/4] checks"
echo "VERSION: $(tr '\n' ' ' < "$DEST/VERSION")"
grep -q "$HEAD_SHA" "$DEST/VERSION" || { echo "cut: VERSION stamp is not HEAD" >&2; exit 1; }
jars=$(find "$DEST" -name '*jar-with-dependencies*.jar' | wc -l | tr -d ' ')
echo "fat jars: $jars $(find "$DEST" -name '*jar-with-dependencies*.jar' -exec basename {} \;)"
[ "$jars" = "1" ] || { echo "cut: expected one fat jar" >&2; exit 1; }
strays=$(grep -rIl "/Users/" "$DEST" 2>/dev/null | wc -l | tr -d ' ')
echo "home-path strays: $strays"
[ "$strays" = "0" ] || { grep -rIl "/Users/" "$DEST" | head -5 >&2; echo "cut: home paths in the package" >&2; exit 1; }
keys=$(grep -rIE "sk_[A-Za-z0-9]{24,}|ELEVENLABS_API_KEY=[A-Za-z0-9]{8}|AIza[0-9A-Za-z_-]{30}" "$DEST" 2>/dev/null | wc -l | tr -d ' ')
echo "key-shaped strings: $keys"
[ "$keys" = "0" ] || { echo "cut: key-shaped strings in the package" >&2; exit 1; }
decks=$(ls -d "$DEST"/forge-arena/decks/*/ | wc -l | tr -d ' ')
echo "decks: $decks"
[ "$decks" = "10" ] || { echo "cut: expected the ten shipped decks" >&2; exit 1; }
echo "voice libraries: $(ls "$DEST/forge-arena/runner/voice/stock/voices" | tr '\n' ' ')"
for v in harry bill lily joshua; do [ -d "$DEST/forge-arena/runner/voice/stock/voices/$v" ] || { echo "cut: voice library $v missing" >&2; exit 1; }; done
python3 "$DIR/check-voice-takes.py" "$DEST"
(cd "$DEST" && forge-arena/runner/run_table.sh --preflight 2>&1 | tail -1)
echo "== [4/4] tar"
rm -f "$TAR"
(cd "$(dirname "$DEST")" && COPYFILE_DISABLE=1 tar czf "$TAR" "$(basename "$DEST")")
echo "tarball: $TAR"
echo "bytes: $(stat -f %z "$TAR")  entries: $(tar tzf "$TAR" | wc -l | tr -d ' ')  unpacked: $(du -sm "$DEST" | cut -f1) MB"
echo "sha256: $(shasum -a 256 "$TAR" | cut -d' ' -f1)"
echo "== cut done: ship with packaging/ship-release-s3.py $TAR forge-light-llm-$STAMP.tar.gz --latest"
