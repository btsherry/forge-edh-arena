# forge-light-llm — Patch Notes

## v3 — unreleased

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
  can even switch a seat Claude ↔ backend mid-game and back; its Claude
  session survives the detour.
- **Cost rails on by default** — $5/seat/game spend cap (`ARENA_MAX_SEAT_
  COST_USD`) plus a 250-attempt call cap that works even where providers
  report no cost; caps, latches, and failures all degrade a seat to safe
  defaults without ever stalling the game.
- **Config errors fail at launch, on your terminal** — missing key, a model
  whose context can't fit the deck dossier — before anything is torn down.
- The README's "Other models on the backend" section covers the details,
  including the honest cost arithmetic to read before picking a $15/M model.

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
