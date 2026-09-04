#!/bin/sh
# Launch the 3 autonomous AI seats (seats 1-3) against the standard table:
#   seat 1 Purphoros / seat 2 Giada / seat 3 Urza  (human plays seat 0 in the GUI)
# Each seat runs in a while-true restart loop — that plus the engine's
# timeout->stock fallback is the whole supervision story. (Backend-model seats
# get a crash-loop damper on top: 5 exits in 10 minutes stops the seat rather
# than re-billing a full init every 2s — plan F-02.)
#
# Usage:  forge-arena/runner/run_table.sh [mailbox-base]
# Env:    ARENA_MAILBOX_TIMEOUT (must match the engine's; default 90)
#         SEAT_MODEL (default opus)   SEAT_EFFORT (default medium; pinned per seat)
#         ARENA_SEAT_MODELS  up to 4 comma-separated per-seat model strings,
#           entry i binds to seat i (positional, like ARENA_SEAT_DECKS); empty
#           entries fall back to SEAT_MODEL. Bare names run the Claude CLI;
#           or/<vendor>/<model> runs OpenRouter (needs OPENROUTER_API_KEY,
#           API-BILLED); oai/<model> runs an OpenAI-compatible endpoint at
#           ARENA_OAI_BASE_URL (ARENA_OAI_API_KEY optional — keyless local
#           endpoints are legal). See ~/Claude/openrouter-backends-plan.md.
# Secrets rule: no key ever appears on any command line (argv is ps-visible);
# authenticated HTTP from shell must be a python3 -c reading os.environ.
# Watch:  tail -f forge-arena/runner/logs/seat-*.log
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
AROOT=$(cd "$DIR/.." && pwd)          # forge-arena/
# --preflight: verify every AI seat ships its context files AND that any
# backend-model config is deterministically sane (keys present, seat-0 rule,
# saved-probe context fit), then exit 0/1. arena-play.sh calls this as a
# synchronous launch gate BEFORE teardown — failures here cost nothing.
PREFLIGHT_ONLY=0
if [ "${1:-}" = "--preflight" ]; then PREFLIGHT_ONLY=1; shift; fi
BASE="${1:-$DIR/../mailbox}"
MODEL="${SEAT_MODEL:-opus}"
EFFORT="${SEAT_EFFORT:-medium}"
export ARENA_MAILBOX_TIMEOUT="${ARENA_MAILBOX_TIMEOUT:-90}"
# SEAT_SPECULATIVE=1 enables executable turn plans; SEAT_REACT_HOLD=1 enables
# the same-turn reactive hold posture. Both default off.
SPEC_FLAG=""
[ "${SEAT_SPECULATIVE:-0}" = "1" ] && SPEC_FLAG="--speculative"
HOLD_FLAG=""
[ "${SEAT_REACT_HOLD:-0}" = "1" ] && HOLD_FLAG="--react-hold"

# Per-seat models (plan F-27): POSIX IFS=',' splitting preserves interior
# empty fields; only a trailing empty drops, so pad to 4 after the split.
M0="$MODEL"; M1="$MODEL"; M2="$MODEL"; M3="$MODEL"
if [ -n "${ARENA_SEAT_MODELS:-}" ]; then
  OLDIFS=$IFS; IFS=','
  # shellcheck disable=SC2086  # intentional comma split
  set -- $ARENA_SEAT_MODELS
  IFS=$OLDIFS
  [ -n "${1:-}" ] && M0="$1"
  [ -n "${2:-}" ] && M1="$2"
  [ -n "${3:-}" ] && M2="$3"
  [ -n "${4:-}" ] && M3="$4"
fi

is_backend() { case "$1" in or/*|oai/*) return 0 ;; *) return 1 ;; esac; }

seat() { # seat_no deck model
  if is_backend "$3"; then damped=1; else damped=0; fi
  fails=0; win_start=$(date +%s)
  mkdir -p "$DIR/logs/pids"
  while true; do
    python3 "$DIR/seat_runner.py" --seat "$1" --deck "$2" \
      --model "$3" --effort "$EFFORT" --base "$BASE" $SPEC_FLAG $HOLD_FLAG &
    child=$!
    echo "$child" > "$DIR/logs/pids/seat-$1.pid"   # item 13e: arena-stop kills by PID
    wait "$child"; rc=$?
    echo "[seat $1] runner exited ($rc) — restarting in 2s" >&2
    if [ "$damped" = 1 ]; then
      now=$(date +%s)
      if [ $((now - win_start)) -gt 600 ]; then fails=0; win_start=$now; fi
      fails=$((fails + 1))
      if [ "$fails" -ge 5 ]; then
        echo "[seat $1] CRASH-LOOP DAMPER: 5 exits in 10 minutes on backend model $3 — stopping this seat so a bug cannot re-bill the init payload every 2s. Fix the cause and relaunch." >&2
        return 1
      fi
    fi
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
    # Static .dck sanity (2026-09-01): two decks reached a live launch
    # unloadable; catch the cheap-to-see defects (sections, 100 cards, DFC
    # naming) at every launch. The authoritative loader probe runs at ingest.
    err=$(python3 - "$AROOT/decks/$d.dck" "$AROOT/../forge-gui/res/cardsfolder" <<'PYCHK'
import sys
try:
    lines = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
except OSError:
    print("dck file missing"); sys.exit(0)
if "[Commander]" not in lines or "[metadata]" not in lines:
    print("not a sectioned Commander .dck (raw export?)"); sys.exit(0)
ci = lines.index("[Commander]")
if ci + 1 >= len(lines) or lines[ci + 1].startswith("["):
    print("empty [Commander] section"); sys.exit(0)
n = 0
for l in lines:
    parts = l.split(None, 1)
    if parts and parts[0].isdigit():
        n += int(parts[0])
if n != 100:
    print(f"{n} cards, expected 100"); sys.exit(0)
# DFC naming (2026-08-31, game 18): Forge names transform / modal-DFC /
# adventure / disturb cards by their FRONT face; only true split cards keep
# "A // B". A wrong form isn't a load error — CardPool inserts an UNSUPPORTED
# placeholder, the count stays 100, and the match silently drops the card
# (Sythis played 95). Resolve each "A // B" line against the card scripts.
import os, glob, re
folder = sys.argv[2] if len(sys.argv) > 2 else ""
def slug(name):
    name = name.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_")
if os.path.isdir(folder):
    for l in lines:
        parts = l.split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        name = parts[1].split("|")[0].strip()
        if " // " not in name:
            continue
        a, b = [x.strip() for x in name.split(" // ", 1)]
        hits = glob.glob(os.path.join(folder, "*", slug(a) + "_" + slug(b) + ".txt"))
        if not hits:
            print(f"no card script for '{name}'"); sys.exit(0)
        if "AlternateMode:Split" not in open(hits[0], encoding="utf-8", errors="replace").read():
            print(f"'{name}' is a double-faced card: write its FRONT face '{a}' "
                  f"(only split cards keep 'A // B'); the match would DROP it"); sys.exit(0)
# Launch manifest (plan item 7, 2026-09-03): ingestion verified every card
# against Forge ONCE and recorded the .dck's SHA-256 + a card-DB stamp. Here
# we compare hashes in milliseconds — no JVM at launch, ever. Missing manifest
# = never verified; changed .dck = verified deck is not the one on disk.
import hashlib, json
slugdir = os.path.dirname(sys.argv[1]); slug = os.path.splitext(os.path.basename(sys.argv[1]))[0]
mpath = os.path.join(slugdir, slug, "dossier", "manifest.json")
if not os.path.exists(mpath):
    print("no launch manifest — run arena-add-deck.py (or --manifest-only) so the deck is "
          "verified against Forge once"); sys.exit(0)
try:
    m = json.load(open(mpath))
except (OSError, ValueError) as e:
    print(f"unreadable launch manifest ({e}) — re-run arena-add-deck.py"); sys.exit(0)
sha = hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()
if m.get("dck_sha256") != sha:
    print("deck changed since ingest (sha mismatch) — re-run arena-add-deck.py so the "
          "new list is verified"); sys.exit(0)
if os.path.isdir(folder) and m.get("db_stamp"):
    n_cards = sum(1 for _r, _d, fs in os.walk(folder) for f in fs if f.endswith(".txt"))
    eds = os.path.join(os.path.dirname(folder), "editions")
    try:
        n_eds = sum(1 for f in os.listdir(eds) if f.endswith(".txt"))
    except OSError:
        n_eds = 0
    if m["db_stamp"] != f"{n_cards}:{n_eds}":
        print(f"WARN card database changed since ingest ({m['db_stamp']} -> {n_cards}:{n_eds}); "
              f"re-ingest when convenient", file=sys.stderr)
PYCHK
)
    [ -z "$err" ] || miss="$miss\n  [$d]  BAD .dck            ($err)"
  done
  if [ -n "$miss" ]; then
    printf '%b\n' "[run_table] PREFLIGHT FAILED — required files missing:$miss" >&2
    printf '%s\n' "[run_table] fix: scripts/arena-add-deck.py <deck.dck>  (writes deck text + combos + primer), then relaunch." >&2
    return 1
  fi
  printf '%s\n' "[run_table] preflight OK — AI decks: $AI_DECKS"
  return 0
}

# Deterministic backend-config checks (plan F-03/F-27): these run in the
# synchronous --preflight gate so a bad config fails on the terminal BEFORE
# the previous game is torn down. No network here — key PRESENCE only; key
# validity is the runtime 401 latch's job.
preflight_models() {
  bad=""
  for pair in "0:$M0" "1:$M1" "2:$M2" "3:$M3"; do
    n=${pair%%:*}; m=${pair#*:}
    case "$m" in
      or/*)  [ -n "${OPENROUTER_API_KEY:-}" ] || bad="$bad\n  [seat $n] '$m' needs OPENROUTER_API_KEY (unset) — OpenRouter seats are API-BILLED" ;;
      oai/*) [ -n "${ARENA_OAI_BASE_URL:-}" ] || bad="$bad\n  [seat $n] '$m' needs ARENA_OAI_BASE_URL (unset)" ;;
    esac
  done
  if is_backend "$M0" && [ "${ALL_SEATS:-0}" != "1" ]; then
    bad="$bad\n  [seat 0] backend model '$M0' — seat 0 is the human/advisor seat unless ALL_SEATS=1"
  fi
  if [ -n "$bad" ]; then
    printf '%b\n' "[run_table] MODEL PREFLIGHT FAILED:$bad" >&2
    return 1
  fi
  # Best-effort context fit against a previously saved /models probe: fail
  # only on a PROVEN misfit (dossier estimate > known context_length).
  if [ -f "$DIR/logs/cache/or-models.json" ]; then
    ARENA_PF_MODELS="$M1,$M2,$M3" ARENA_PF_M0="$M0" ARENA_PF_ALL="${ALL_SEATS:-0}" \
    ARENA_PF_DECKS="$D0 $D1 $D2 $D3" ARENA_PF_ROOT="$AROOT" \
    python3 - <<'PY' || return 1
import json, os, sys
root = os.environ["ARENA_PF_ROOT"]
decks = os.environ["ARENA_PF_DECKS"].split()
models = os.environ["ARENA_PF_MODELS"].split(",")
if os.environ["ARENA_PF_ALL"] == "1":
    models = [os.environ["ARENA_PF_M0"]] + models
    seats = [0, 1, 2, 3]
else:
    seats = [1, 2, 3]
try:
    rows = {r.get("id"): r for r in json.load(
        open(os.path.join(root, "runner/logs/cache/or-models.json")))["data"]}
except Exception:
    sys.exit(0)
def est(seat):
    n = 0
    for rel in ("runner/seatd/seat-brief.md",
                "docs/research/mtg-rules-summary.md",
                "docs/research/mtg-rules-digest-conversion.md",
                f"decks/{decks[seat]}/dossier/deck-cards.json",
                f"decks/{decks[seat]}/dossier/combos.json",
                f"docs/primers/{decks[seat]}-deckcheck.md"):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            n += os.path.getsize(p)
    return int(n / 4 * 1.25)
bad = []
for seat, m in zip(seats, models):
    if not m.startswith("or/"):
        continue
    mid = m[3:]
    row = rows.get(mid) or rows.get(mid.partition(":")[0])
    if not row:
        continue  # unknown id: warn-and-continue posture (plan F-30)
    ctx = row.get("context_length")
    if isinstance(ctx, int) and ctx > 0:
        need = est(seat)
        if need > ctx:
            bad.append(f"  [seat {seat}] {m}: init estimate ~{need} tokens "
                       f"exceeds the model's {ctx}-token context")
if bad:
    print("[run_table] CONTEXT PREFLIGHT FAILED:\n" + "\n".join(bad),
          file=sys.stderr)
    sys.exit(1)
PY
  fi
  return 0
}

if [ "$PREFLIGHT_ONLY" = "1" ]; then
  preflight_decks && preflight_models
  exit $?
fi
preflight_decks || exit 1
preflight_models || exit 1

# Keyless /models probe (plan F-31): public endpoint, 5s cap, once per launch,
# warn-and-continue — a hung OpenRouter must never stall Claude seats. The
# saved payload supplies context_length / max_completion_tokens to backends.py
# and to the next launch's context preflight.
case "$M0 $M1 $M2 $M3" in
  *or/*)
    mkdir -p "$DIR/logs/cache"   # item 13f: control/ is cleared by arena-stop; cache/ survives
    python3 - "$DIR/logs/cache/or-models.json" <<'PY' || \
      echo "[run_table] /models probe failed (continuing — runtime latch is the backstop)" >&2
import json, os, sys, urllib.request
out = sys.argv[1]
try:
    with urllib.request.urlopen(
            "https://openrouter.ai/api/v1/models", timeout=5) as r:
        data = r.read(1 << 24)
    json.loads(data)  # sanity
    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)
    print("[run_table] /models probe OK — metadata saved")
except Exception as e:
    print(f"[run_table] /models probe: {type(e).__name__}", file=sys.stderr)
    sys.exit(1)
PY
    ;;
esac

# Item 13e: on INT/TERM kill OUR seat runners (by PID file) and OUR loop
# subshells — never `kill 0`, which signalled the launching shell's whole
# process group.
trap 'for f in "$DIR"/logs/pids/seat-*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done; kill $(jobs -p) 2>/dev/null; exit 143' INT TERM
if [ "${ALL_SEATS:-0}" = "1" ]; then
  seat 0 "$D0" "$M0" &   # all-AI mode: 4th brain takes seat 0
fi
seat 1 "$D1" "$M1" &
seat 2 "$D2" "$M2" &
seat 3 "$D3" "$M3" &
echo "seatd table up (seats 1-3, model=$M1/$M2/$M3, timeout=${ARENA_MAILBOX_TIMEOUT}s)"
echo "logs: tail -f $DIR/logs/seat-*.log"
wait
