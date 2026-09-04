#!/usr/bin/env python3
"""Local ELO ladders for the arena (plan ~/Claude/openrouter-backends-plan.md §13).

Consumes game-result spool files written by the engine's GameResultSpool
(runner/results/game-<startMillis>-<pid>.json), updates three ladders —
by pilot (model / human / human+advisor), by deck slug, and by pilot×deck —
and appends a per-game record to ratings-history.jsonl for over-time plots.

Invoked from arena-stop.sh BEFORE the log archive (and therefore also by the
next arena-play.sh launch, which calls arena-stop). Idempotent: consumed
spools rename to *.rated; integrity-failed spools rename to *.skipped with a
loud line (correctness > coverage — a mis-attributed game must never rate).

Scoring (settled spec, do not re-litigate):
- A 4-player game is six pairwise 1v1s. Placement comes as TIE GROUPS from
  the spool (all players eliminated in one game-over batch share a group).
  Across groups: 1/0 by group order. Within a group: 0.5/0.5.
- All expected scores are computed from the PRE-game snapshot; each side uses
  its OWN K (40 until 10 games, then 20); per-player deltas are summed and
  applied once per ladder. Replays are order-independent by construction.
- Self-pairs (both seats resolve to one rated player — the DEFAULT table has
  one model in three seats) are skipped; games_played += 1 per player per
  game regardless of seat count.
- AI seat attribution: the model with the most source=="model" records for
  that seat in game.jsonl within the game's time window; tie -> earliest;
  zero -> deck ladder only. Deck cross-check: any in-window record whose
  deck differs from the spool slug skips the whole game.

Stdlib only. The whole read-modify-write runs under an exclusive flock.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

RUNNER = Path(__file__).resolve().parent
START_ELO = 1000.0
WINDOW_SLACK_S = 30.0


def k_factor(games: int) -> float:
    return 40.0 if games < 10 else 20.0


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def pair_scores(groups: list[list[int]]) -> list[tuple[int, int, float]]:
    """(seatA, seatB, scoreA) for every unordered pair across the groups."""
    out = []
    for gi, ga in enumerate(groups):
        for ai, a in enumerate(ga):
            for b in ga[ai + 1:]:
                out.append((a, b, 0.5))
            for gb in groups[gi + 1:]:
                for b in gb:
                    out.append((a, b, 1.0))
    return out


def ladder_update(table: dict, seat_key: dict, pairs) -> dict:
    """Snapshot-based pairwise update of one ladder (mutates table).
    seat_key: seat -> rated-player key (None = unrated on this ladder)."""
    keys = {k for k in seat_key.values() if k}
    snap = {k: dict(table.get(k) or {"elo": START_ELO, "games": 0})
            for k in keys}
    delta = {k: 0.0 for k in keys}
    for a, b, sa in pairs:
        ka, kb = seat_key.get(a), seat_key.get(b)
        if not ka or not kb or ka == kb:
            continue
        ea = expected(snap[ka]["elo"], snap[kb]["elo"])
        delta[ka] += k_factor(snap[ka]["games"]) * (sa - ea)
        delta[kb] += k_factor(snap[kb]["games"]) * ((1.0 - sa) - (1.0 - ea))
    changes = {}
    for k in keys:
        before = snap[k]["elo"]
        table[k] = {"elo": round(before + delta[k], 2),
                    "games": snap[k]["games"] + 1}
        changes[k] = {"before": before, "after": table[k]["elo"]}
    return changes


def slice_game_log(game_log: Path, t0: float, t1: float) -> list[dict]:
    """Records in [t0, t1] across the shared log. Item 13h: the runners write
    one game-<gameId>.jsonl per game and keep game.jsonl as a symlink to the
    current one, so read every regular game*.jsonl beside it (the symlink
    itself is skipped — it duplicates one of them)."""
    files = []
    if game_log.parent.is_dir():
        for p in sorted(game_log.parent.glob("game*.jsonl")):
            if p.is_symlink():
                continue
            files.append(p)
    elif game_log.exists():
        files.append(game_log)
    out = []
    for p in files:
        try:
            lines = p.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ts = r.get("ts")
            if isinstance(ts, (int, float)) and t0 <= ts <= t1:
                out.append(r)
    return out


def attribute(spool: dict, window_recs: list[dict], log=print):
    """Per-seat pilot resolution. Returns (seat->pilot|None, seat->counts,
    error string or None). AI seats attribute by model-decision majority and
    cross-check the deck slug; human seats attribute by control field."""
    pilots, counts = {}, {}
    by_seat: dict = {}
    for r in window_recs:
        by_seat.setdefault(r.get("seat"), []).append(r)
    for s in spool["seats"]:
        seat, slug, control = s["seat"], s["slug"], s["control"]
        if control in ("human", "human+advisor"):
            pilots[seat] = control
            counts[seat] = {}
            continue
        recs = by_seat.get(seat, [])
        wrong = [r for r in recs if r.get("deck") and slug
                 and r.get("deck") != slug]
        if wrong:
            return None, None, (f"seat {seat}: runner records say deck="
                                f"{wrong[0].get('deck')!r} but result says "
                                f"{slug!r} — roster drift, game NOT rated")
        model_recs = [r for r in recs if r.get("source") == "model"
                      and isinstance(r.get("model"), str)]
        c = Counter(r["model"] for r in model_recs)
        counts[seat] = dict(c)
        if not c:
            pilots[seat] = None  # deck ladder only (plan F-22)
            continue
        top = max(c.values())
        leaders = [m for m, n in c.items() if n == top]
        if len(leaders) == 1:
            pilots[seat] = leaders[0]
        else:  # tie -> earliest model-sourced record among leaders
            first = min((r for r in model_recs if r["model"] in leaders),
                        key=lambda r: r.get("ts") or 0)
            pilots[seat] = first["model"]
    return pilots, counts, None


VOID_PUNT_THRESHOLD = 8   # punts on ONE seat inside the window => transport-contaminated


def load_transport_events(game_log: Path) -> list[dict]:
    """logs/transport-events.jsonl beside game.jsonl (seat runners append
    {ts, seat, kind: punt|wedge}); absent file = no events."""
    p = game_log.parent / "transport-events.jsonl"
    out = []
    try:
        with p.open() as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        out.append(rec)
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def void_reason(spool: dict, events: list[dict]) -> str | None:
    """A game is VOID for rating when transport failure degraded a seat
    inside its window: any session wedge, or >= VOID_PUNT_THRESHOLD punts on
    a single seat. ARENA_RATE_VOIDED=1 overrides (rates anyway)."""
    if os.environ.get("ARENA_RATE_VOIDED") == "1":
        return None
    t0 = spool["startMillis"] / 1000.0 - WINDOW_SLACK_S
    t1 = spool["endMillis"] / 1000.0 + WINDOW_SLACK_S
    # BL-09: a stamped spool attributes events by game id exactly; events
    # from an unstamped runner (no gameId) still fall under the time window.
    gid = spool.get("gameId")
    if isinstance(gid, str) and gid:
        events = [e for e in events if e.get("gameId") in (None, gid)]
    punts: dict = {}
    for e in events:
        ts = e.get("ts")
        if not isinstance(ts, (int, float)) or not (t0 <= ts <= t1):
            continue
        if e.get("kind") == "wedge":
            return f"seat {e.get('seat')} session wedged mid-game"
        if e.get("kind") == "punt":
            n = punts.get(e.get("seat"), 0) + 1
            punts[e.get("seat")] = n
            if n >= VOID_PUNT_THRESHOLD:
                return (f"seat {e.get('seat')} punted {n}+ decisions "
                        f"(transport degradation)")
    return None


REQUIRED_SPOOL_KEYS = ("startMillis", "endMillis", "seats", "placementGroups")


def spool_problem(spool) -> str | None:
    """BL-26: the shape process_spool indexes without checking. A problem
    string means the spool is marked .skipped instead of raising."""
    if not isinstance(spool, dict):
        return "not an object"
    for k in REQUIRED_SPOOL_KEYS:
        if k not in spool:
            return f"missing {k}"
    if not isinstance(spool["startMillis"], (int, float)) \
            or not isinstance(spool["endMillis"], (int, float)):
        return "startMillis/endMillis not numeric"
    if not isinstance(spool["seats"], list) or not all(
            isinstance(x, dict) and "seat" in x and "control" in x and "slug" in x
            for x in spool["seats"]):
        return "seats rows need seat/control/slug"
    if not isinstance(spool["placementGroups"], list):
        return "placementGroups not a list"
    return None


def _rename_quiet(p: Path, suffix: str, log=print) -> bool:
    """BL-26: a spool another sweeper already moved is its win, not a crash."""
    try:
        p.rename(p.with_name(p.name + suffix))
        return True
    except OSError as e:
        log(f"[ratings] note: could not mark {p.name}{suffix} ({e}) — "
            f"another sweeper moved it")
        return False


def process_spool(spool: dict, tables: dict, game_log: Path, log=print,
                  events: list[dict] | None = None):
    """Rate one game. Returns the history record, or None if skipped."""
    seats = {s["seat"]: s for s in spool.get("seats", [])}
    groups = spool.get("placementGroups") or []
    placed = [x for g in groups for x in g]
    if sorted(placed) != sorted(seats) or len(seats) < 2:
        log(f"[ratings] SKIP: placement groups {groups} do not cover the "
            f"seats {sorted(seats)} exactly")
        return None
    t0 = spool["startMillis"] / 1000.0 - WINDOW_SLACK_S
    t1 = spool["endMillis"] / 1000.0 + WINDOW_SLACK_S
    pilots, counts, err = attribute(spool, slice_game_log(game_log, t0, t1),
                                    log=log)
    if err:
        log(f"[ratings] SKIP: {err}")
        return None
    reason = void_reason(spool, events if events is not None
                         else load_transport_events(game_log))
    if reason:
        log(f"[ratings] VOID (recorded, not rated): {reason}")
        slug_v = {n: (s["slug"] or None) for n, s in seats.items()}
        return {"ts": round(time.time(), 3),
                "start": spool["startMillis"], "end": spool["endMillis"],
                "turns": spool.get("turnsPlayed"),
                "advisor": spool.get("advisor", False),
                "voided": True, "voidReason": reason,
                "seats": [{"seat": n, "pilot": pilots[n], "slug": slug_v[n],
                           "control": seats[n]["control"],
                           "modelDecisions": counts.get(n) or {}}
                          for n in sorted(seats)],
                "placementGroups": groups, "changes": {}}
    pairs = pair_scores(groups)
    slug_of = {n: (s["slug"] or None) for n, s in seats.items()}
    combo_of = {n: (f"{pilots[n]}|{slug_of[n]}"
                    if pilots[n] and slug_of[n] else None) for n in seats}
    changes = {
        "models": ladder_update(tables["models"], pilots, pairs),
        "decks": ladder_update(tables["decks"], slug_of, pairs),
        "combos": ladder_update(tables["combos"], combo_of, pairs),
    }
    return {"ts": round(time.time(), 3),
            "start": spool["startMillis"], "end": spool["endMillis"],
            "turns": spool.get("turnsPlayed"),
            "advisor": spool.get("advisor", False),
            "seats": [{"seat": n, "pilot": pilots[n], "slug": slug_of[n],
                       "control": seats[n]["control"],
                       "modelDecisions": counts.get(n) or {}}
                      for n in sorted(seats)],
            "placementGroups": groups, "changes": changes}


def write_digests(tables: dict, record: dict, elo_dir: Path) -> None:
    """Flat per-seat digests for the AI panel's regex-only reader (F-32)."""
    elo_dir.mkdir(parents=True, exist_ok=True)
    for s in record["seats"]:
        pilot, slug = s["pilot"], s["slug"]
        m = tables["models"].get(pilot) if pilot else None
        d = tables["decks"].get(slug) if slug else None
        md = tables["combos"].get(f"{pilot}|{slug}") if pilot and slug else None
        body = {"m": m["elo"] if m else 0, "d": d["elo"] if d else 0,
                "md": md["elo"] if md else 0,
                "n": m["games"] if m else 0,
                "pilot": pilot or s["control"]}
        p = elo_dir / f"seat-{s['seat']}.json"
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(body))
        tmp.replace(p)


def sweep(results_dir: Path, ratings_path: Path, history_path: Path,
          game_log: Path, elo_dir: Path, log=print) -> int:
    # BL-26: the listing happens UNDER the lock (below) — a sweep that listed
    # first could rename a spool a concurrent sweeper had already moved.
    if not results_dir.is_dir():
        return 0
    lock_path = ratings_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lf = lock_path.open("w")
    deadline = time.time() + 5.0
    while True:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= deadline:
                log("[ratings] lock busy after 5s — leaving spools for the "
                    "next sweep (nothing lost)")
                return 0
            time.sleep(0.2)
    try:
        spools = sorted(results_dir.glob("game-*.json"))
        spools = [p for p in spools if not p.name.endswith((".rated", ".skipped"))]
        if not spools:
            return 0
        try:
            tables = json.loads(ratings_path.read_text())
            assert isinstance(tables, dict)
        except (OSError, ValueError, AssertionError):
            tables = {"version": 1, "models": {}, "decks": {}, "combos": {}}
        for k in ("models", "decks", "combos"):
            tables.setdefault(k, {})
        rated = 0
        last_record = None
        events = load_transport_events(game_log)
        for p in spools:
            try:
                spool = json.loads(p.read_text())
            except (OSError, ValueError) as e:
                log(f"[ratings] SKIP {p.name}: unreadable ({e})")
                _rename_quiet(p, ".skipped", log)
                continue
            problem = spool_problem(spool)
            if problem:
                log(f"[ratings] SKIP {p.name}: malformed spool ({problem})")
                _rename_quiet(p, ".skipped", log)
                continue
            rec = process_spool(spool, tables, game_log, log=log,
                                events=events)
            if rec is None:
                _rename_quiet(p, ".skipped", log)
                continue
            rec["spool"] = p.name
            with history_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            if rec.get("voided"):
                # the record survives for review; the ladders never move
                _rename_quiet(p, ".voided", log)
                continue
            # Item 13c: persist the ladders BEFORE marking the spool rated —
            # a crash between the two used to leave history saying "rated"
            # while ratings.json never moved, with the spool unprocessable.
            tmp = ratings_path.with_name(ratings_path.name + ".tmp")
            tmp.write_text(json.dumps(tables, indent=1, sort_keys=True))
            tmp.replace(ratings_path)
            _rename_quiet(p, ".rated", log)
            last_record = rec
            rated += 1
            top = max(rec["changes"]["models"].items(),
                      key=lambda kv: kv[1]["after"], default=None)
            log(f"[ratings] rated {p.name}: "
                + ", ".join(f"{k} {v['before']:.0f}->{v['after']:.0f}"
                            for k, v in rec["changes"]["models"].items()))
        if rated and last_record:
            write_digests(tables, last_record, elo_dir)
        return rated
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runner-dir", default=str(RUNNER),
                    help="runner/ root (results/, logs/, ratings.json live here)")
    a = ap.parse_args()
    root = Path(a.runner_dir)
    n = sweep(results_dir=root / "results",
              ratings_path=root / "ratings.json",
              history_path=root / "ratings-history.jsonl",
              game_log=root / "logs" / "game.jsonl",
              elo_dir=root / "logs" / "elo")
    print(f"[ratings] sweep complete — {n} game(s) rated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
