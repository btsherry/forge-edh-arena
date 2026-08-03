#!/usr/bin/env python3
"""Whole-deck synergy discovery via Gemini (gemini-pro-latest), as a CROSS-CHECK
to the FABLE workflow. Shards the 85 non-basic anchors into batches so each
call's JSON output stays under the token cap; embeds the shared brief + primer +
rules digest + full decklist + ALL non-basic Forge scripts in every call (Gemini
can't read our files). Google Search grounding ON. Never prints the API key.
Aggregates every batch's records to one JSON file. Discovery only — no compile."""
import json, re, os, glob, urllib.request, time

ROOT = "/Users/toor/Claude"
FA = ROOT + "/personal/forge-edh-arena"
DOSSIER = FA + "/forge-arena/decks/selvala-heart-of-the-wilds/dossier"
CARDS = FA + "/forge-gui/res/cardsfolder"
SCRATCH = "/private/tmp/claude-501/-Users-toor-Claude/472653bf-a5b3-4295-8ed3-bc916e689d2e/scratchpad"
OUT = SCRATCH + "/gemini-wholedeck-records.json"
LOG = SCRATCH + "/gemini-wholedeck.log"
BATCH = 22            # anchors per call -> ~4 calls; keeps output under the cap

def log(m):
    with open(LOG, "a") as f:
        f.write(m + "\n")

raw = open(ROOT + "/hello/gemini-hello").read()
m = re.search(r"AIza[0-9A-Za-z_\-]{35}", raw)
key = m.group(0) if m else raw.strip().splitlines()[-1].strip()
del raw

brief = open(SCRATCH + "/canary-brief.md").read()
# widen the canary scope line to whole-deck
brief = brief.replace("canary: 10 anchors, ≤50 pairings", "whole deck, ≤200 pairings")

deck = json.load(open(DOSSIER + "/deck-cards.json"))
basics = {"Forest", "Island", "Swamp", "Mountain", "Plains", "Wastes"}
anchors = sorted({c["name"] for c in deck["cards"] if c["name"] not in basics})

try:
    primer = open(FA + "/forge-arena/docs/primers/selvala-heart-of-the-wilds-deckcheck.md").read()
except Exception:
    primer = "(primer unavailable)"
try:
    rules = open(FA + "/forge-arena/docs/research/mtg-rules-digest-conversion.md").read()
except Exception:
    rules = "(rules digest unavailable)"

def line(c):
    return f"- {c['name']} | {c.get('type_line','')} | {c.get('mana_cost','')} | {(c.get('oracle_text') or '').replace(chr(10),' / ')}"
decklist = "\n".join(line(c) for c in deck["cards"])

def slug(name):
    s = name.lower().replace("'", "").replace(",", "").replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return "_".join(s.split())
scripts, found, miss = [], 0, 0
for c in deck["cards"]:
    n = c["name"]
    if n in basics:
        continue
    sg = slug(n); letter = sg[0]
    cands = glob.glob(f"{CARDS}/{letter}/{sg}.txt") or glob.glob(f"{CARDS}/{letter}/{sg}*.txt")
    if cands:
        try:
            scripts.append(f"### {n}\n" + open(cands[0]).read().strip()); found += 1
        except Exception:
            miss += 1
    else:
        miss += 1
scripts_blob = "\n\n".join(scripts)
log(f"embedded scripts={found}/{found+miss}  anchors={len(anchors)}")

def batches(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

all_records = []
for bi, batch in enumerate(batches(anchors, BATCH)):
    prompt = (brief
        + "\n\n===== YOUR ANCHOR CARDS FOR THIS BATCH ====="
        + "\n(anchor ONLY on these; partners may be ANY non-basic deck card)\n"
        + "\n".join(f"{i+1}. {a}" for i, a in enumerate(batch))
        + "\n\n(You have Google Search available — inference helper only, never a hard filter. "
          "Every partner card MUST be a real card in the decklist below. Mark novelty best-effort.)"
        + "\n\n===== DECK STRATEGY PRIMER =====\n" + primer
        + "\n\n===== RULES DIGEST (reference) =====\n" + rules
        + "\n\n===== FULL DECKLIST (name | type | cost | oracle) =====\n" + decklist
        + "\n\n===== FORGE CARD SCRIPTS (mechanical ground truth) =====\n" + scripts_blob)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 60000},
    }).encode()
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-latest:generateContent?key=" + key
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=600)
        data = json.loads(resp.read())
        cand = data["candidates"][0]
        text = "\n".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        # extract the JSON array from the response
        mm = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
        recs = []
        if mm:
            try:
                recs = json.loads(mm.group(0))
            except Exception as e:
                log(f"batch {bi}: json parse fail: {e}")
        all_records.extend(recs if isinstance(recs, list) else [])
        log(f"batch {bi}: finish={cand.get('finishReason')} chars={len(text)} records={len(recs)}")
    except urllib.error.HTTPError as e:
        log(f"batch {bi}: HTTP {e.code} {e.read().decode()[:300].replace(key,'<KEY>')}")
    except Exception as e:
        log(f"batch {bi}: ERROR {str(e).replace(key,'<KEY>')}")
    time.sleep(2)

json.dump({"source": "gemini-pro-latest whole-deck cross-check", "anchors": len(anchors),
           "records": all_records}, open(OUT, "w"), indent=1)
log(f"DONE total_records={len(all_records)} -> {OUT}")
print("GEMINI_WHOLEDECK_DONE records=%d -> %s" % (len(all_records), OUT))
