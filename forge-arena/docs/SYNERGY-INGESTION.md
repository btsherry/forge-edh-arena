# Synergy-ingestion pipeline — the repeatable discovery process

**How to run whole-deck synergy discovery on ANY deck** and emit **compilable**
records the compile step turns into runner programs. This doc is the CONTRACT +
run procedure; the exact agent instructions live in
[`CANARY-BRIEF-GOLD.md`](CANARY-BRIEF-GOLD.md) (both agents receive that brief).

Validated on Selvala (whole-deck): **200 compilable records, 0 hallucinations**
(the FABLE canary alone found 41 rules-cited synergies across 10 anchors; Gemini,
fair, found 10). **FABLE >> Gemini** — the edge is *tool access* (reads every
script on demand, curls EDHREC/Scryfall, cross-checks the dossier for novelty), not
model tier. Gemini is the independent cross-check.

## The run procedure (repeatable, per deck)

1. **Prep the dossier** (deterministic): `scripts/prep.sh <list> --id <deck-slug>`
   → `decks/<deck-slug>/dossier/` with `deck-cards.json`, `card-scripts-index.json`,
   `combos.json`, etc.
2. **FABLE discovery** (primary, tool-using): run the workflow
   `scripts/selvala-wholedeck-ingestion-wf_87514c03-1a9.js` (a Claude Code
   Workflow-tool script) with `args = { deck: "<deck-slug>", anchors: [...] }`
   (anchors = every non-basic card from `deck-cards.json`). It shards the anchors →
   Phase I wide → richest-anchor Phase II deep → adversarial verify → caps at 200.
   Agents read this doc + `CANARY-BRIEF-GOLD.md` + the dossier themselves.
3. **Gemini cross-check** (independent, token-free on Claude):
   `python3 scripts/gemini_wholedeck.py <deck-slug>` — embeds the brief + primer +
   rules + decklist + all non-basic Forge scripts, Search grounding on, writes
   `decks/<deck-slug>/dossier/discovered-synergies-gemini.json`.
4. **Merge** FABLE + Gemini (dedup by anchor+sorted-partners, keep higher
   `compile_rank`) → `decks/<deck-slug>/dossier/discovered-synergies-wholedeck.json`.
5. **Compile** each record into a runner program — see the `arena-dev` skill and
   [`runner-cat.md`](runner-cat.md); gate with schema → `ProgramGate` → seed-paired A/B.

## Data resource files (per deck — substitute the deck slug)
- Deck strategy primer: `forge-arena/docs/primers/<deck-slug>-deckcheck.md`
- Card oracle text (all 99): `forge-arena/decks/<deck-slug>/dossier/deck-cards.json`
- **Card-scripts index** (name → absolute `.txt` path; the fast path): `forge-arena/decks/<deck-slug>/dossier/card-scripts-index.json`
- Forge card scripts root: `forge-gui/res/cardsfolder/<first-letter>/<snake_case_name>.txt`
- Rules digest: `forge-arena/docs/research/mtg-rules-digest-conversion.md`
- Novelty cross-check (existing combos/synergies): `forge-arena/decks/<deck-slug>/dossier/{combos.json, advisory-combos.json, discovered-synergies.json, discovered-combos.json, program-backlog.json}`
- External helpers (inference only, never a hard filter): `https://json.edhrec.com/pages/cards/<slug>.json` (co-occurrence, staple-dominated); `https://api.scryfall.com/cards/search?q=otag:... / oracle:...`

## The shared brief (what both agents receive)

[`CANARY-BRIEF-GOLD.md`](CANARY-BRIEF-GOLD.md) — the deck-agnostic gold brief:
how-to-think (rules-lawyer, script-is-ground-truth, find chains, reject false
positives), the Forge-DSL primer, the execution model + runner shapes, the
test-harness format, the **compilable output schema**, and the scope/caps. The
harness fills the deck name, the `<deck-slug>` in paths, the anchor list, and the
run cap (whole-deck ≤200 / canary ≤50). Keep it byte-in-sync with what the agents
actually receive.

## FABLE invocation (the primary harness)
`scripts/selvala-wholedeck-ingestion-*.js` via the Workflow tool. Agents are
`Agent(subagent_type="general-purpose", model="fable")`, one per anchor shard.
Each prompt = the method + the INPUTS block (the resource paths above) + its
anchors; the agent reads `SYNERGY-INGESTION.md` + `CANARY-BRIEF-GOLD.md` and the
scripts via the **card-scripts index** (never glob), cross-checks novelty against
the dossier, uses EDHREC/Scryfall via `curl`, and holds the **zero-hallucination
bar** (every partner card must exist in `deck-cards.json`).

## Gemini invocation (independent cross-check)
`scripts/gemini_wholedeck.py <deck-slug>`. Endpoint
`https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-latest:generateContent`;
key read at runtime from `hello/gemini-hello` (a Google `AIza…` key — never
print/commit it; override the path with `GEMINI_KEY_FILE`). Enable **Google Search
grounding** (`"tools":[{"google_search":{}}]`); `maxOutputTokens` ≥ 60000 (a
thinking model — a small budget truncates before the JSON). Gemini can't read our
files, so the script **embeds** inline: the brief, the strategy primer, the rules
digest, the full decklist, and **all non-basic Forge scripts** (via the index).

## Compile + validate (turning records into game logic)
Each record's compilable fields map to a program JSON for its `program_class`
(existing runners in [`runner-cat.md`](runner-cat.md); `win_plan` and
`shape_is_new:true` = a new/extended runner to build+test). Then run the record's
`engine_test` as an actual gate — keep only what fires. Rank the compile queue by
`compile_rank`. The compile side is the **`arena-dev`** skill.
