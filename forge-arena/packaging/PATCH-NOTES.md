# forge-light-llm — Patch Notes

## v3.3.1 — 2026-08-31

Fix release: a two-model adversarial review of v3.3's new decision surfaces
found ten defects; all are fixed and every fix is proven end-to-end.

- **Optional costs work properly now**: Buyback/Kicker appear as separate
  "[+ cost]" options in the seat's cast list (affordability-checked; the
  base spell is always offered). v3.3 could hide the base spell and opened
  redundant prompts.
- **Multikicker actually kicks**: Everflowing-Chalice-class spells enter
  with the number of kicks the seat chooses (v3.3's fix was on a code path
  the AI never reached).
- **Library ordering is no longer inverted**: Sensei's Top / Scroll Rack
  put-backs land in exactly the order the seat states.
- **No more phantom payment prompts**: cost-payment questions only appear
  while a cast is actually happening, never during the AI's own planning.
- **Safer timeouts**: a timed-out brain now bids LOW on Wheel-of-
  Misfortune-class effects (it used to bid the maximum and take the
  damage); X-spells still default to the affordable maximum.
- Protective abilities are never auto-passed while divided-damage spells
  (Arc Trail class) point at your board; a seat's own spells no longer
  count as threats against itself.

## v3.3 — 2026-08-28

### The seats now own nearly every decision

The largest play-quality release since the interactive seam shipped. A
dual-model audit of the engine/AI boundary found every remaining place a
stock heuristic silently decided FOR the seat — all of them are now the
seat's own choice, with the same fail-safe as always (an invalid or late
answer falls back to stock, never worse than before):

- **Sacrifices** — edicts and "each player sacrifices" effects, AND which
  card pays a sacrifice cost (Viscera-Seer-class outlets, additional-cost
  spells). The seat feeds the token, not the win condition.
- **Pitch costs** — which blue card Force of Will exiles, which card a
  discard/return/put-to-library cost eats.
- **Cleanup & mulligans** — discarding to hand size at end of turn and
  choosing which cards go under the library on a London mulligan.
- **Library control** — scry, surveil, reorder-on-library effects
  (Sensei's Top / Scroll Rack class), and clash top-or-bottom calls.
- **Casts with options** — Buyback/Kicker-class optional costs, non-X
  announced values (Multikicker), "choose a number" effects (Wheel of
  Misfortune class), and may-cast offers (Isochron Scepter copies) with the
  seat aiming the copy's targets.
- **Redirects** — Deflecting-Swat-class retargeting actually retargets
  (stock AI literally could not do this and the spell fizzled silently).
- **Table politics** — votes, Fact-or-Fiction pile splits, protection
  color choices (Mother of Runes picks the RIGHT color from the stack),
  and creature-or-player choices.

### Brains see more of the table

Every stack item now announces its **chosen targets** (public information —
"Beast Within, targeting Purphoros") and carries a compact **oracle-text
line**, so reactive decisions run on ground truth instead of model recall.
The reactive fastpaths were rekeyed on phase, combat state, and targets, so
a held Fog or Flawless Maneuver can no longer be auto-passed after an
earlier quiet window that merely looked identical — and protective
abilities (Mother of Runes / Giver of Runes) are never fast-passed while
removal is pointed at your board.

### Advisor discipline

The seat-0 Advisor now verifies a target's effective keywords before
recommending removal — no more "hold Beast Within for the indestructible
god" advice.

### Fixed

- **Y'shtola's deck file** shipped in a raw export format that the game
  refused to load (the deck had never actually hit a table); rebuilt as a
  legal 100-card Commander deck. If your v3.2 install won't seat Y'shtola,
  this is why.
- Ability option labels no longer render as "Exile ." / "Untap ." before
  targets are chosen — they show the card's rules text.
- `arena-status.py` shows the live table's real deck names instead of a
  default roster.

### Under the hood

Faster test/gate tooling for contributors (project-classified suite,
documented gate policy and revert flags — see `BUILDING.md`), a shared test
harness, and regression tests for every surface above (355+ Java/Python
tests, all green).

## v3.2 — 2026-08-19

### New: DeckCheck primers without copy/paste

`arena-add-deck.py` can now pull a deck's strategy analysis straight from
DeckCheck.co. Give it your DeckCheck deck URL or id —
`arena-add-deck.py my-deck.dck --deckcheck <url-or-id>` — and it fetches the
structured analysis (analysis prose, bracket, and CRISPI ratings) from
DeckCheck's public endpoint and renders it as the primer, no manual paste. The
existing paste and local-fable options are unchanged.

### New: eighth bundled deck — Sythis, Harvest's Hand

Selesnya (GW) enchantress built through the new DeckCheck import pipeline:
full dossier, combo list, and DeckCheck primer. The AI table roster and
`ARENA_SEAT_DECKS` accept it like any bundled deck.

### New: ninth bundled deck — Liberator, Urza's Battlethopter

A colorless cEDH build, also onboarded through the DeckCheck import pipeline
(full dossier, combo list, and DeckCheck primer) — the first colorless deck in
the bundle. Sits at any seat via the roster or `ARENA_SEAT_DECKS`.

### New: primer generation controls

- `--primer-out PATH` — write the primer to a path you choose instead of
  `docs/primers/<slug>-deckcheck.md`.
- `--primer-timeout SECS` (default 2700) — bound the local fable/max primer run.
- `--no-primer-rules` — skip embedding the MTG rules digests in the local fable
  prompt for a faster generation, at some cost to loop-precision.

### Improved: local primers reason from the rules corpus

Option B (local `claude` fable/max generation) now feeds the model the two MTG
rules digests alongside the deck's combos and oracle text, so generated primers
state loop and timing lines more rules-accurately.

### Fixed: double-faced card ingest

Double-faced / modal (MDFC) card names — e.g. `Bala Ged Recovery // Bala Ged
Sanctuary` — now resolve during ingest (Scryfall is queried by the front face),
so those cards land in the dossier with full oracle text instead of the
unresolved list.

### New: color-matched seat avatars

Each seat now gets a built-in Forge avatar matched to its deck's colors — tallied
from the deck's mana-pip composition, so a mono-red deck always shows a red head,
a three-color deck leans toward its heaviest color, and so on. Heads are picked
with per-color variety (different each launch) and are distinct across the four
seats. New decks get a themed avatar for free; anything unexpected falls back to
Forge's default avatar, and it never touches gameplay.

### Changed: leaner, more human Advisor cadence

The Advisor now speaks at a humanly-random handful of moments per turn (roughly
one to three) instead of at nearly every window — spread across the phases and
still fully board-aware — plus the always-on end-of-turn recap, and it always
weighs in on mulligans. Fewer, better-timed interruptions and a lighter token
footprint; the turn recap covers anything a given turn's picks skipped.

## v3.1 — 2026-08-17

### Faster: loops fast-forward, MCP-free decisions stay

- **Declared-loop replay.** A seat executing a repetitive loop (Scepter
  mana, storm counts, token pings) can declare `repeat_cycle: N` after one
  full iteration; the runner replays the whole cycle's answers N times at
  zero model calls and wakes the brain the instant ANYTHING differs — a new
  stack object, a changed option list, a player leaving. A loop iteration
  that cost ~60–80 seconds of deliberation now costs milliseconds after the
  first pass. Life totals and the growing pool are expected loop movement
  and never break the replay; novelty always does.
- **Free own-trigger confirms think light** ("cast the Scepter copy?" class)
  — routed to low effort with full authority, same policy as own-trigger
  reaction windows.
- (Carried from v3, the biggest single win: every decision stopped paying
  ~2–3s of MCP tool-roster initialization for a process with all tools
  disabled — median decision time fell from ~8s to ~5s. v3.1 keeps that and
  removes the next tail: the loop.)

### Fixed: counterspells actually counter

Two distinct defects made seat-cast counters resolve as no-ops:

- Seats targeted the stack-zone CARD instead of the spell on the stack —
  a "countered" spell resolved anyway ("found nothing" fizzles, Winter Orb
  surviving two counters in one game). Spell targeting now aims at the
  stack entry itself, the same object the rules operate on.
- A targeted spell cast by a seat could reach resolution with its targets
  stripped after an interleaved trigger. Cast-time diagnostics now verify
  the stack entry carries the seat's chosen targets, and the full collision
  (counter + tax trigger + cast trigger, all on one stack) is covered by
  regression tests.

### New: your own triggers are yours

- **Optional "you may [pay X to]…" triggers reach the seat** as a confirm
  with the trigger text, the cost, and the chosen targets — Rings of
  Brighthearth copies, may-draws, may-bounces. (Stock AI silently declined
  the seat's own Rings copies: a live "infinite mana" combo netted zero for
  three full turns.)
- **Targeting triggers are aimed by the seat** — Tidespout Tyrant no longer
  bounces its controller's own 17/17 because a heuristic liked the look of
  it.

### New: the symmetry break

If a seat controls a permanent whose restriction reads "as long as ~ is
untapped" and affects all players (Winter Orb, Static Orb, Storage Matrix),
windows on the turn right before the seat's own now offer **[SYMMETRY
BREAK]**: tap the piece through any outlet whose cost can tap it (Urza,
Clock of Omens, its own tap ability) with the piece pre-selected as the
payment. The seat's untap step escapes the lock; the piece untaps during
that same step and keeps restricting everyone else. Detected from card
mechanics, not card names — future cards with the same shape work
automatically. All seats see `state.symmetryPieces` and whose untap is next.

### New: more decisions belong to the brain

- Discard selection (rummage, forced discards where you choose).
- Split/adventure/MDFC face and side picks.
- "Reduce this cost by up to N" numbers.
- Generic "choose N cards" effect choices.

### New: transport resilience and honest ratings

- A seat whose resident session goes dark (timeouts, upstream 500s) now
  drops the wedged session after a sustained failure streak and rejoins the
  game on a fresh one — with a note telling the brain to re-derive its plan
  from the live board. A brief blip never costs the session.
- Emergency defaults are shape-aware: a punt no longer answers "no" to the
  seat's own free copy-cast mid-combo.
- Games degraded by transport failure are **voided for ratings**: the
  history keeps the record (with the reason), the ladders never move on a
  contaminated result. `ARENA_RATE_VOIDED=1` overrides.

### Improved: seat brief tuned from live evidence

Assembly-cost counting when one combo piece away; re-cost the payoff after
its mana source resolves; impulse/play-from-exile before the land drop;
re-check your hand for an answer to the permanent you keep planning around;
symmetry-piece timing; per-deck mana-discipline notes (Urza's colourless-
heavy base).

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
