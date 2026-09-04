#!/usr/bin/env python3
"""deckcheck-import — LOCAL TESTING TOOL (do NOT bundle).

Authenticated DeckCheck round-trip to onboard a deck for local arena testing:
  login -> create draft -> import a Moxfield/Archidekt/ManaBox URL -> persist the
  cards (save-draft) -> set visibility -> run the paid analysis -> poll -> print
  the deckId. Then feed that id to:
    arena-add-deck.py <deck.dck> --slug <slug> --deckcheck <deckId>
  which pulls the primer keylessly (no credits).

SPENDS CREDITS (standard = 1, pro = 5) and uses the login at hello/deckcheck-hello.
Never bundle this — the distributable path is the keyless read (arena-add-deck
mode A). Full protocol notes: docs/research/DECKCHECK-ACCESS.md.

Usage:
  deckcheck-import.py <deck-url> [--tier standard|pro] [--name NAME]
                      [--visibility unlisted|public|private] [--no-analyze]
                      [--dck-out PATH] [--cred PATH]
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://deckcheck.co"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
DEFAULT_CRED = (os.environ.get("DECKCHECK_CRED_FILE")
                or os.path.expanduser("~/Claude/hello/deckcheck-hello"))
TIER_CREDITS = {"standard": 1, "pro": 5}

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))


def call(method, path, data=None, form=False, timeout=90):
    """One authenticated call; cookies persist across calls via the shared jar.
    Returns (status_code, parsed_json_or_text)."""
    url = BASE + path if path.startswith("/") else path
    headers = {"User-Agent": UA, "Accept": "application/json",
               "X-Requested-With": "XMLHttpRequest", "Origin": BASE,
               "Referer": BASE + "/app/builder"}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _opener.open(req, timeout=timeout) as r:
            raw = r.read().decode(errors="replace").strip()
            return r.status, (json.loads(raw) if raw[:1] in ("{", "[") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace").strip()
        return e.code, (json.loads(raw) if raw[:1] in ("{", "[") else raw)


def load_creds(path):
    d = {}
    for line in open(path):
        if ":" in line:
            k, v = line.split(":", 1)
            d[k.strip()] = v.strip()
    if "u" not in d or "p" not in d:
        sys.exit(f"ERROR: {path} must contain 'u:' and 'p:' lines")
    return d["u"], d["p"]


def persist(cards):
    """Import card list -> save-draft's {cardName: entry} dict shape."""
    out = {}
    for c in cards:
        out[c["name"]] = {"printings": [{
            "quantity": c.get("quantity", 1),
            "finish": c.get("finish") or "nonfoil",
            "card_scryfall_id": c.get("scryfall_id"),
            "set_code": c.get("set_code"),
            "collector_number": c.get("collector_number"),
        }]}
    return out


def write_dck(path, name, commanders, cards):
    # Commander lines use the FRONT face of "A // B" names (2026-09-01):
    # Forge names transform/MDFC cards by their front face and the loader
    # resolves no commander otherwise; split-layout commanders don't exist,
    # so the heuristic is safe here. Main entries pass through untouched —
    # arena-add-deck's layout-aware rewrite is the authoritative fix.
    lines = ["[metadata]", "Name=" + (name or "Imported Deck"), "[Commander]"]
    lines += [f"{c.get('quantity',1)} {c['name'].split(' // ')[0].strip()}"
              for c in commanders]
    lines.append("[Main]")
    lines += [f"{c.get('quantity',1)} {c['name']}" for c in cards]
    open(path, "w").write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="Moxfield/Archidekt/ManaBox deck URL")
    ap.add_argument("--tier", choices=["standard", "pro"], default="pro")
    ap.add_argument("--name", help="deck name (default: from the import)")
    ap.add_argument("--visibility", choices=["unlisted", "public", "private"],
                    default="unlisted")
    ap.add_argument("--no-analyze", action="store_true",
                    help="import + save + set visibility, but skip the paid analysis")
    ap.add_argument("--dck-out", help="also write a Forge .dck to this path")
    ap.add_argument("--drop-sideboard", action="store_true",
                    help="do not persist the source deck's sideboard/maybe pile "
                         "(Commander Deck Scan rejects drafts with non-companion "
                         "sideboard cards — HTTP 409)")
    ap.add_argument("--cred", default=DEFAULT_CRED)
    a = ap.parse_args()
    u, p = load_creds(a.cred)

    # 1. login (prime cookies, then form-encoded credentials)
    call("GET", "/login")
    call("POST", "/login", {"username": u, "password": p}, form=True)
    _, cs = call("GET", "/api/credits-status")
    if not isinstance(cs, dict) or "available_credits" not in cs:
        sys.exit("ERROR: login failed (no credits-status returned)")
    credits_before = cs["available_credits"]
    print(f"[auth] logged in — {credits_before} credits "
          f"(access_level {cs.get('access_level')})")
    if not a.no_analyze and credits_before < TIER_CREDITS[a.tier]:
        sys.exit(f"ERROR: need {TIER_CREDITS[a.tier]} credits for {a.tier}, "
                 f"have {credits_before}")

    # 2. create an empty draft
    _, dr = call("POST", "/builder/api/draft-deck",
                 {"name": a.name or "arena-import", "deck_format": "Commander",
                  "folder_id": None})
    did = (dr.get("deck") or {}).get("id") if isinstance(dr, dict) else None
    if not did:
        sys.exit(f"ERROR: draft-deck failed: {dr}")
    print(f"[draft] deckId = {did}")

    # 3. import the URL
    _, imp = call("POST", "/builder/api/import-deck-builder",
                  {"url": a.url, "deckId": did})
    if not isinstance(imp, dict) or "cards" not in imp:
        sys.exit(f"ERROR: import failed: {imp}")
    name = a.name or imp.get("name") or "arena-import"
    commanders = imp.get("commanders", [])
    cmd_names = [c["name"] for c in commanders]
    print(f"[import] '{imp.get('name')}' — {len(imp.get('cards', []))} cards, "
          f"commander={cmd_names}")

    # 4. persist the cards (save-draft)
    payload = {
        "id": did, "name": name, "deck_format": "commander",
        "commander": cmd_names[0] if cmd_names else None,
        "commander2": cmd_names[1] if len(cmd_names) > 1 else None,
        "companion": None,
        "cards": persist(imp.get("cards", [])),
        "sideboard": persist([] if a.drop_sideboard else imp.get("sideboard", [])),
        "considering": {}, "notes": "", "deck_roles": {}, "deck_metadata": {},
    }
    st, sv = call("POST", "/builder/api/save-draft", payload)
    print(f"[save] HTTP {st}: {sv if isinstance(sv, str) else sv.get('message', sv)}")

    # 5. visibility
    st, _ = call("POST", "/builder/api/update-deck-visibility",
                 {"deck_id": did, "visibility": a.visibility})
    print(f"[visibility] {a.visibility}: HTTP {st}")

    # 6. paid analysis (async job -> poll)
    if not a.no_analyze:
        # deckList is the 99-card mainboard only; the commander travels in
        # commanderInput. Including it makes DeckCheck reject "expected 99, got 100".
        deck_list = "\n".join(f"{c.get('quantity',1)} {c['name']}"
                              for c in imp.get("cards", []))
        body = {"commanderInput": cmd_names, "companionInput": "",
                "deckList": deck_list, "draftDeckId": did, "deckStateHash": "",
                "intelligenceLevel": a.tier, "userInput": "", "forceRescan": True}
        st, ev = call("POST", "/api/evaluate-deck", body)
        job = ev.get("job_id") if isinstance(ev, dict) else None
        if not job:
            sys.exit(f"ERROR: evaluate-deck failed (HTTP {st}): {ev}")
        print(f"[analyze] tier={a.tier} job={job} — polling...")
        for _ in range(40):
            time.sleep(6)
            _, js = call("GET", f"/api/job-status/{job}")
            status = js.get("status") if isinstance(js, dict) else "?"
            if status in ("completed", "success", "succeeded", "done", "finished"):
                print(f"[analyze] DONE — bracket {js.get('bracket_level')}, "
                      f"perf {js.get('performance_index')}, "
                      f"tier {js.get('analysis_intelligence_level')}, "
                      f"{len(js.get('full_analysis') or '')} chars")
                break
            if status in ("failed", "error", "errored"):
                sys.exit(f"ERROR: analysis job failed: {js}")
            print(f"  … {status} (queue {js.get('queue_position')})")
        _, cs2 = call("GET", "/api/credits-status")
        after = cs2.get("available_credits")
        print(f"[credits] {credits_before} -> {after} (spent {credits_before - after})")

    # 7. optional .dck emit
    if a.dck_out:
        write_dck(a.dck_out, name, commanders, imp.get("cards", []))
        print(f"[dck] wrote {a.dck_out}")

    print(f"\nDONE. deckId = {did}")
    print(f"Next: python3 forge-arena/scripts/arena-add-deck.py <deck.dck> "
          f"--slug <slug> --deckcheck {did}")


if __name__ == "__main__":
    main()
