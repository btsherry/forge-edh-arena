# forge-light-llm — Patch Notes

## v3 — 2026-08-17

### New: bring your own models

Any AI seat can now run **any OpenRouter model** or **any OpenAI-compatible
endpoint** (Ollama, LM Studio, vLLM) instead of Claude — per seat, mixed
tables welcome:

```sh
ARENA_SEAT_MODELS=",or/google/gemini-2.5-pro,,oai/llama3.1" \
  forge-arena/scripts/arena-play.sh --all-ai
```

- **Opt-in and isolated** — with no backend model configured, nothing
  changes: Claude seats run exactly as before on your `claude` login.
- **Per-seat model strings** — `or/<vendor>/<model>` (OpenRouter, uses
  `OPENROUTER_API_KEY`, API-billed) or `oai/<model>` (your
  `ARENA_OAI_BASE_URL`; keyless local endpoints work). Backend models join
  the AI panel's steppers and re-dial mid-game like everything else — you
  can switch a seat Claude ↔ backend mid-game and back; its Claude session
  survives the detour.
- **Cost rails on by default** — $5/seat/game spend cap
  (`ARENA_MAX_SEAT_COST_USD`) plus a 250-attempt call cap that works even
  where providers report no cost; caps, latches, and failures all degrade a
  seat to safe defaults without ever stalling the game.
- **Config errors fail at launch, on your terminal** — missing key, a model
  whose context can't fit the deck dossier — before anything is torn down.
- The README's "Other models on the backend" section covers the details,
  including the honest cost arithmetic to read before picking a $15/M model.

### New: local ELO ladders

Every finished game rates three local ladders — pilot (models, `human`,
and `human+advisor` are all pilots), deck, and pilot×deck — scored as six
pairwise 1v1s by finish order with tie groups for simultaneous eliminations.
Ratings update at teardown, display per seat in the AI panel, persist across
package rebuilds, and accumulate a plottable per-game history. Which model
actually pilots your deck best is now a number.

### New: the deviation log

Every seat now records, in plain words, each moment its plan met reality:

```
[seat 2] DEVIATION t3 MAIN1: wanted "Cast Giada off Ancient Tomb" — blocked by:
  Ancient Tomb produces only colorless; no white source in play
```

Deviations land in the seat logs and as a structured `deviation` field on
each decision record, alongside the turn's stated intent — a play-quality
review is now a grep, and the day's brief tuning came straight out of it.

### New: Advisor pause button

A button at the bottom of the Advisor tab pauses/resumes the coach mid-game
(paused = no advice, no model calls, no teardown); the AI panel's seat-0 row
reflects the state.

### Faster: every decision, and the dead windows

- **~2–3 seconds off every single AI decision.** Each brain call had been
  paying to connect the host's entire MCP tool roster before answering,
  for a process with all tools disabled. Median decision time fell from
  ~8s to ~5s across the table; time spent actually thinking rose from
  58% to ~88% of the clock. Nothing the brains see or decide changed.
- **Dead windows think light, never skip.** Reaction windows where a seat
  has zero mana and zero untapped sources, and windows where every stack
  item is the seat's own trigger, are answered at low effort — the brain
  keeps full authority (a combat trick in response to your own trigger is
  still yours to cast); it just doesn't deliberate over "let my trigger
  resolve." A cascade of identical own triggers (token pings, untap loops)
  now fast-passes after the first pass instead of re-asking on every step.
- Seat runners and the advisor poll faster; the AI panel hides stepper
  buttons that would do nothing.

### Improved: what the brains can see and choose

- **Modal spells honor the chosen mode.** Tutors and other non-targeted
  modes of Charm-style spells now resolve as the seat chose them (Green
  Sun's Zenith, Archdruid's Charm, Transmute Artifact all find their card).
- **Every "pay X or else" is the brain's call**: taxes on your spells
  (Esper Sentinel, Rhystic Study, counter-unless), pay-the-difference
  tutors, "sacrifice unless" upkeeps. Multi-card searches (Cultivate-class)
  and yes/no confirms reach the seat as well.
- **Free alternative costs are offered as their own option** — Fierce
  Guardianship, Deflecting Swat and the rest of the free-if-commander
  family show up at `{0}`, labeled, beside the paid version.
- **Commander tax is shown on the label** (`[effective cost: {1}{G}{G} +
  {4} = 7 mana]`), a seat can see its own command zone and cast counts, and
  an unaffordable cast is refused locally instead of attempted.
- **Seat brief tuned from live evidence**: mana colour and pip counting,
  conditional and restricted mana sources (Mox Amber, Workshop),
  commander tax, unbounded-loop conversion (loop to a table kill, order
  enablers → bodies → finisher, spend every tutor), and survival math that
  counts the opponent's damage doublers.

### Fixed (v2)

- A commander cast short of its tax could be lost from every zone for the
  rest of the game (an upstream engine failure path). Failed payments now
  return the card to where it came from, and seats no longer attempt casts
  they cannot pay for.
- Modal-spell modes chosen by a seat could be silently discarded at cast
  time, resolving the spell as a no-op ("found nothing"). Resolved.

## v2 — 2026-08-13

### New: The AI Advisor

```sh
forge-arena/scripts/arena-play.sh --human your-deck.dck --advisor
```

A dedicated coaching brain for the human seat, in its own **Advisor tab**
(lower-left dock, beside Prompt):

- **Advice before you act** — every meaningful decision (priority windows,
  attacks, blocks, mulligans, targets, X values) is mirrored to the advisor
  as the prompt opens; its short read appears while you're still deciding.
- **Knows the whole table** — the advisor reads every deck at the table
  (full oracle text and combo lists) at startup: matchup-aware mulligan
  advice, threat forecasting by name, and no card-fact guessing.
- **Color commentary** — a few sentences per completed turn covering the
  table's public plays, with personality.
- **A deliberate cadence** — 3–5 advice moments per turn (your first main
  and combat guaranteed, the rest sampled), so each appearance carries
  weight. Danger overrides the budget: an opponent's spell on the stack
  always gets a read.
- **Coach's memory** — it tracks your actual choices, calls back to plays
  that paid off, and owns its own misses in a sentence.
- **Strictly read-only** — the advisor's feed has no return channel; it can
  never act for you or stall the game. Advice arriving late is advice
  skipped, never a pause.
- Every exchange is recorded to `runner/logs/advisor-0.jsonl` — advice,
  your choice, and the divergence — alongside the existing game dataset.

Requires the piloted deck to be ingested (`arena-add-deck.py`) and the
`claude` CLI logged in. Model/effort re-dialable mid-game from the AI
panel's seat-0 row.

### New: Smart Autopass

Priority stops with nothing meaningful to do pass themselves (default
`casts` mode; `ARENA_AUTOPASS=strict|off` to change). The guarantees are
stakes-based, not heuristic:

- Your own **main phases are never auto-passed**, by any layer.
- Neither are **combat declare steps**, stops with an **opponent's spell on
  the stack**, any stop while you have **mana floating**, or the rest of
  the turn after an **equipment enters** with its equip cost payable.
- Every skipped stop leaves a `⏭` receipt in the Advisor tab, so the quiet
  is fully auditable.

### New: Table quality of life

- **Any-color mana picks auto-answer** with your commander's color when
  your commander is mono-colored (the Gemstone Caverns / City of Brass
  dialog class). Multicolor commanders keep the choice.
- **Zero-latency no-op reactions** — the `react-autopass` daemon now
  launches automatically with every game, answering provably-dead reaction
  windows in milliseconds before any AI burns a thought on them.

### Improved: what the AI seats can see

- **Double-faced cards are whole**: bundled deck data now carries both
  faces (a modal land back is a land), and in-hand cards serialize both
  faces' types — mulligan judgment across all seats improves accordingly.
- **Effective keywords in every board state**: indestructible, hexproof,
  ward, protection, and the evergreen combat set — including granted
  effects — are stated facts at decision time for every seat, not
  recall tests.

### Improved: deck ingestion

- Card-name resolution now survives Secret Lair flavor names and
  punctuation differences (hyphens, apostrophes) between your list and the
  canonical card name.
- Generated primers (`--primer b`) now actually perform their live
  EDHREC/web research, and are constrained to rules-accurate execution
  lines with no meta-commentary in the output.
- All console output prints package-relative paths.

### Fixed (v1)

- Bundled decks' card data was missing the back faces of double-faced
  cards, which skewed AI mulligan and land counts. Rebuilt with complete
  data.
- One bundled Purphoros card ("Spider-Punk") failed to resolve due to a
  name mismatch and played without full card knowledge. Resolved.

---

## v1 — 2026-08-12

Initial release: four-seat Commander arena with Claude-piloted opponents
(all-AI or human + 3), pilot-tuned match layout, live AI panel (per-seat
model/effort dials and token telemetry), deck ingestion from bare `.dck`
(Scryfall + Commander Spellbook + implementability lint + primer),
`ARENA_SEAT_DECKS` table roster control, seven bundled decks, and the
per-decision observability dataset (`game.jsonl`).
