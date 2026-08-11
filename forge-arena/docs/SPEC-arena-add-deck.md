# SPEC — `arena-add-deck`: bare `.dck` → playable arena seat

**Goal.** A recipient of the distributed package drops a Forge `.dck` file in a
folder, runs one command, and gets a fully playable AI (or human) seat: full
per-card oracle text, the deck's real combos, an engine-implementability check,
and a strategy primer — with **no hand-authoring**. This is the distribution
blocker: without it, only the four bundled decks work.

Status: SPEC (not built). Companion to the packaging plan (see chat 2026-08-10).

---

## Inputs / outputs

**Input:** a Forge `.dck` file. Format (already used by the bundled decks):
```
[metadata]
Name=Selvala, Heart of the Wilds
[Commander]
1 Selvala, Heart of the Wilds
[Main]
1 Arbor Elf
5 Forest
...
```

**Output tree** (mirrors the bundled decks exactly, so the runner needs zero
new wiring):
```
forge-arena/decks/<slug>.dck                     # copied/normalized
forge-arena/decks/<slug>/dossier/deck-cards.json # full oracle text, per card
forge-arena/decks/<slug>/dossier/combos.json     # CommanderSpellbook included combos
forge-arena/docs/primers/<slug>-deckcheck.md      # strategy primer (step 5)
```
`<slug>` = kebab-cased deck name (sanitize; collision → append short hash).

**Consumers (unchanged):** `brain.py` init loads `deck-cards.json` + `combos.json`
+ the `<slug>-deckcheck.md` primer; `run_table.sh` / `arena-play.sh` reference the
deck by slug. So `arena-add-deck` only has to *produce these files correctly*.

---

## Pipeline

### 1. Parse the `.dck`
- Extract commander (`[Commander]` block) + main list (name, count) + deck name.
- Normalize card names (strip set tags, trailing whitespace; keep DFC full names).
- Derive `<slug>`. Refuse if the file isn't a Commander deck (no commander, or
  not ~100 cards) with a clear message.

### 2. Fetch full card text — Scryfall
- `POST /cards/collection` (batches of ≤75 identifiers, `{"name": "..."}`).
- Pull `oracle_text`, `mana_cost`, `type_line`, `power`, `toughness`,
  `color_identity`, `layout`, and `card_faces[]` for DFC/split/adventure.
- **Fat context is mandatory** (field note 1): store the *complete* oracle text,
  never a summary. `deck-cards.json` schema matches the bundled dossiers.
- Handle: not-found names (collect and report — usually a typo or an un-scryfallable
  token), DFC (concatenate/label both faces), reprints (irrelevant — text is text).
- Respect rate limits (~100ms between calls); cache raw responses under
  `dossier/.cache/scryfall/` so re-runs are instant and offline.

### 3. Fetch combos — CommanderSpellbook
- `find-my-combos` endpoint: POST the decklist, receive combos whose pieces are
  **all present in the deck** (the *included* set — NOT the "1-card-away"
  potential list; that was the ship-pattern decision, 2026-08-10).
- Keep per-combo: `cards[]` (name + zone_req), `mana_needed`, `prerequisites`,
  `steps`, `produces`, `bracket_tag`, `popularity`. Schema matches the bundled
  `combos.json` (`arena.combos/1`).
- Cache under `dossier/.cache/commanderspellbook/`.
- CommanderSpellbook is fine to use (open API); **DeckCheck is not scraped** —
  see step 5 and the licensing note.

### 4. Implementability lint (fail-loud, don't fail mid-game)
- Cross-check every card name against Forge's card database (the ~33k scripted
  cards the engine ships). A card Forge can't script will misbehave or no-op
  in-engine — better to surface it at ingest than to discover it as a "vanished"
  card three turns in (cf. the whole card-loss bug family this project just fixed).
- Output: a `lint` report — `unsupported: [...]`, `note: [...]` (e.g. cards whose
  implementation is partial/known-quirky). Default **warn + list**, let the user
  decide to proceed; `--strict` turns unsupported into a hard fail.
- Cheap bonus checks: color-identity subset of the commander, singleton (non-basic),
  ~100 cards. These catch a malformed `.dck` before a game does.

### 5. Strategy primer (the hard, high-value step)
The primer *is* the pilot's strategic brain — `brain.py` feeds it to the seat
verbatim, so its quality directly drives play quality. The nuance the primer must
capture is genuinely hard: **committed subthemes, sacrifice loops, overlapping
keyword packages, tap/untap engines, synergy webs (not just named combos)** — the
stuff that only becomes obvious after an experienced pilot runs the deck through
many games. DeckCheck.co is unusually good at exactly this. So step 5 does not try
to out-clever it; it **recommends DeckCheck first** and offers a local fallback.

`arena-add-deck` prints, at step 5:

> **Strategy primer for `<slug>`.** The pilot plays far better with a good one.
> DeckCheck.co produces the best commander-specific analysis we've seen — it
> surfaces subthemes, sac loops, keyword overlaps, and synergy lines that are hard
> to see otherwise. Two options:
>
> **(A) Paste a DeckCheck review (recommended).** Open https://deckcheck.co, run
> this deck, copy the review, and save it to:
> `forge-arena/docs/primers/<slug>-deckcheck.md`
> Press ENTER when done, or `s` to skip.
>
> **(B) Generate one locally with the top model.** We'll run the **fable** model
> at **max effort** to synthesize a primer from your `deck-cards.json`,
> `combos.json`, and live EDHREC / web research on the commander. Slower and not
> quite DeckCheck-grade on subthemes, but fully local + free. Type `b` to use it.

- **Path A** — the tool waits for the file, then validates it's non-empty and
  looks like prose (not an error page). Done.
- **Path B — fable / max effort.** Invoke the resident-transport CLI
  (`claude -p --model fable --effort max`, subscription auth — never the API) with
  a primer-generation prompt that is handed:
  - the full `deck-cards.json` (every card's oracle text),
  - `combos.json` (the real combos + steps),
  - and instructions to **do live EDHREC + web research on the commander** to
    catch committed subthemes, and to reason about: archetype(s) the deck has
    chosen; every combo's execution line; synergy packages beyond named combos
    (sac loops, untap engines, overlapping keywords, counters-matter, storm,
    landfall, etc.); mulligan heuristics; threat assessment; primary + backup win
    lines; and the *sequencing* those subthemes imply.
  - Output written to `<slug>-deckcheck.md` (same filename regardless of path, so
    `brain.py` needs no branching).
- Either way the primer is optional-to-good: if skipped, the seat still plays off
  the dossier + combos, just less sharply. Encourage A, allow B, permit skip.

> Why this split and not "always generate": in this project's own bake-off the
> pipeline-generated primer beat a DeckCheck-sourced one *for the seat-brain
> audience* on the combo-execution axis, but DeckCheck was better at the diffuse
> subtheme read. Offering both, DeckCheck-first, gets the best of each and (see
> the email / licensing note) is the arrangement we want with DeckCheck anyway.

### 6. Register + smoke-test
- Place all files; add `<slug>` to the deck registry the launchers read (make
  `DECKS[]` config-driven, not source-hardcoded — a tracked tier-2 item).
- Optional `--verify`: load the deck in headless Forge to confirm it assembles a
  legal 100-card Commander deck (catches lint gaps the name-check missed).

---

## CLI shape
```
arena add-deck path/to/mydeck.dck [--slug NAME] [--strict] [--primer a|b|skip]
                                  [--no-cache] [--verify]
```
- Interactive by default at step 5; `--primer` makes it scriptable for batch adds.
- Idempotent: re-running refreshes the dossier/combos from cache (or `--no-cache`
  to re-fetch), and leaves an existing primer untouched unless asked.

## Dependencies / failure modes
- **Internet** at ingest for steps 2–3 (and 5B research) — one-time per deck; cached
  after. Steps 1/4/6 are offline.
- Clear, non-stack-trace errors for: bad `.dck`, Scryfall miss list, CSB down,
  unsupported cards (lint), no primer chosen.
- All network responses cached so a flaky connection doesn't force a full redo.

## Licensing / relationships
- **CommanderSpellbook**: open API, fine to call. **Scryfall**: fine (respect rate
  limits + caching per their guidelines). **DeckCheck.co**: we do **not** scrape —
  step 5A is the *user* pasting their own review, and we want a real arrangement
  (free-tier API) with the owner (see the outreach email). This both respects their
  ToS and funnels users to their service.
- The whole package is GPL-3.0 / WotC Fan Content (non-commercial). `arena-add-deck`
  fetches public card data the user is entitled to; it ships no card data itself
  beyond what Forge already bundles.

## Build order (when green-lit)
1. Steps 1–2 (parse + Scryfall dossier) — the core, unblocks everything.
2. Step 3 (CSB combos) — reuse the find-my-combos calls already proven this project.
3. Step 4 (lint) — cheap, high-value safety.
4. Step 5 (primer A/B) — the UX + the fable-max prompt.
5. Step 6 (register/verify) + the `arena` wrapper.
