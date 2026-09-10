#!/bin/sh
# ship-release.sh — upload a built forge-light-llm tarball to the public
# Cloudflare R2 bucket and verify it. Two objects per release (Ben's naming
# rule since v3): the DATED object is the version, forge-light-llm-latest.tar.gz
# is the alias that is overwritten. Both are downloaded back and compared by
# sha256 before this script reports success.
#
# Usage:  forge-arena/packaging/ship-release.sh <tarball> <dated-key>
#   e.g.  forge-arena/packaging/ship-release.sh ~/Claude/personal/forge-light-llm-20260909.tar.gz forge-light-llm-20260909.tar.gz
#   --no-latest   upload the dated object only (a re-cut you do not want as -latest yet)
#
# Credentials: ~/Claude/hello/cloudflare-hello — line 1 the account id, line 2 an
# API token with R2 write on the bucket. Read into shell variables only; never
# echoed, never on a logged command line, never committed. This script prints
# sizes, hashes and HTTP codes, nothing else.
set -eu
TAR=${1:?tarball path}; KEY=${2:?dated object key, e.g. forge-light-llm-YYYYMMDD.tar.gz}
LATEST=1; [ "${3:-}" = "--no-latest" ] && LATEST=0
BUCKET=forge-light-llm-dist
PUB=https://pub-6a4e610a9fd04c94b51eb95344c3013f.r2.dev
CRED="$HOME/Claude/hello/cloudflare-hello"
[ -s "$TAR" ] || { echo "ship: tarball missing: $TAR" >&2; exit 1; }
[ -s "$CRED" ] || { echo "ship: credentials file missing" >&2; exit 1; }
case "$KEY" in forge-light-llm-*.tar.gz) ;; *) echo "ship: key must look like forge-light-llm-YYYYMMDD.tar.gz" >&2; exit 1 ;; esac
ACCT=$(sed -n 1p "$CRED" | tr -d '\r\n'); TOKEN=$(sed -n 2p "$CRED" | tr -d '\r\n')
[ -n "$ACCT" ] && [ -n "$TOKEN" ] || { echo "ship: credentials file must hold account id (line 1) and token (line 2)" >&2; exit 1; }
LOCAL_SHA=$(shasum -a 256 "$TAR" | cut -d' ' -f1); SIZE=$(stat -f %z "$TAR")
echo "ship: $TAR — $SIZE bytes, sha256 $LOCAL_SHA"
# refuse to overwrite an existing DATED object: dated = version, immutable
if curl -sI -o /dev/null -w '%{http_code}' "$PUB/$KEY" | grep -q '^200$'; then
  echo "ship: $KEY already exists in the bucket — dated objects are never overwritten (use a b-suffixed key for a same-day re-cut)" >&2; exit 1
fi
KEYS="$KEY"; [ "$LATEST" = 1 ] && KEYS="$KEY forge-light-llm-latest.tar.gz"
for K in $KEYS; do
  RESP=$(mktemp)
  code=$(curl -s -o "$RESP" -w '%{http_code}' -X PUT \
    "https://api.cloudflare.com/client/v4/accounts/$ACCT/r2/buckets/$BUCKET/objects/$K" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/gzip" --data-binary "@$TAR")
  echo "ship: PUT $K -> http $code"
  rm -f "$RESP"
  [ "$code" = "200" ] || { echo "ship: upload failed for $K" >&2; exit 1; }
done
for K in $KEYS; do
  TMP=$(mktemp); curl -s -o "$TMP" "$PUB/$K"
  RSHA=$(shasum -a 256 "$TMP" | cut -d' ' -f1); RSIZE=$(stat -f %z "$TMP"); rm -f "$TMP"
  if [ "$RSHA" = "$LOCAL_SHA" ]; then echo "ship: verify $K -> byte-exact ($RSIZE bytes)"
  else echo "ship: verify $K -> MISMATCH remote sha256 $RSHA ($RSIZE bytes)" >&2; exit 1; fi
done
echo "ship: done — $PUB/$KEY$([ "$LATEST" = 1 ] && echo " and $PUB/forge-light-llm-latest.tar.gz")"
