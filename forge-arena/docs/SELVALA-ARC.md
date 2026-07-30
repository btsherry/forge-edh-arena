# Selvala mana-loop arc — living plan (started 2026-07-30)

Anchor-then-sweep (Ben-approved). Anchor Umbral Mantle (527-2816) + the two
extensions (variable-yield pair verification, cast_x_spell sink), gate, then
clone the six other tap-untap mana combos. Sabertooth blink family HELD.
No large batch until check-in. Phase summaries at each boundary.

## PHASE 1 — INGESTION (done)

**Deck:** 99-card mono-green stompy-combo (list in the .dck). **Primer:**
selvala-heart-of-the-wilds-deckcheck.md (reingested). **Combos:** 11 in
combos.json. **Pairings:** paired-plays.json EMPTY (she has no wipe+shield
pairs — her "synergies" are ramp→payoff, not the Giada class). 68 unverified
discovered-synergies exist (research will surface the few that matter, not
build all 68).

**The 11 combos are two families:**
- **7 tap-untap mana loops (THE ARC TARGET):** 527-2645 Staff+Selvala,
  527-2816 Mantle+Selvala (ANCHOR — mechanism confirmed PR-A), 2816-5711
  Mantle+Fanatic of Rhonas, 1355-2645 Staff+Sanctum Weaver, 1355-2816
  Mantle+Sanctum Weaver, 2026-2404-2645 Voyaging Satyr+Gaea's Cradle+Staff,
  2026-2404-2816 Satyr+Cradle+Mantle. All produce infinite mana (Staff also
  infinite draw).
- **4 Sabertooth blink loops (HELD):** Temur Sabertooth + Selvala + a
  haste-enabler — bounce-recast, different shape.

## Ben's outlet briefing (2026-07-30) — the hard part, verbatim seed for research

Selvala's outlets are CONDITIONAL and board-dependent (unlike Aetherflux's
always-lethal PayLife or Purphoros's always-lethal ETB). Ben's map:
- **Craterhoof Behemoth** — needs creatures on board (overrun; board-dependent).
- **Finale of Devastation** — can fetch Craterhoof, but with minimal board may
  NOT be lethal (X/X body + fetch; needs a board to overrun).
- **Genesis Wave** — infinite mana → plays out most of the deck on the spot →
  lethal board. The cleanest "infinite mana = win."
- **Selvala goes almost-infinitely-large** (several routes) → kill one player
  at a time via combat/commander damage.
- **Two of the gods** act as outlets for infinite mana → winning board states
  (deck has Nylea Keen-Eyed, Ojer Kaslem Deepest Growth, Rhonas + Omnath the
  mana battery — research to identify which two and how).
- **Sabertooth + Selvala value:** pick up and put down the LARGEST creature to
  re-trigger Selvala's draw-on-strongest-ETB (even non-infinite, a draw engine).
- **Finite-but-large mana** via tap/untap shenanigans on big/enchanted lands
  (Nykthos Shrine to Nyx = devotion; Gaea's Cradle = creatures; a land with
  multiple enchantments) → a storm-like turn: draw a ton, cast a lot, dig to a
  combo. This is the SETUP/dig layer that gets INTO combo position.
"This is going to be hard stuff." — Ben.

## Outlet suite in the 99 (ingestion cross-check)

Genesis Wave, Finale of Devastation, Craterhoof Behemoth, Greater Good
(sac oversized → draw, combo fuel/dig), Staff of Domination (infinite draw →
deck-out/find), Umbral Mantle (Selvala huge → combat), Genesis Hydra /
Goldvein Hydra / Managorger Hydra (X payoffs), Return of the Wildspeaker
(draw X / +3+3), Turntimber Symbiosis (X creatures), Nylea Keen-Eyed /
Ojer Kaslem / Rhonas / Omnath (god/battery outlets). The governor's hard job:
pick the outlet that is ACTUALLY LETHAL given the live board.

## Layered deck model (from primer + Ben)

1. SETUP/ramp: dorks + auras + big lands (Cradle/Nykthos/enchanted) → burst mana → dig.
2. COMBO: the 7 tap-untap infinite-mana loops.
3. OUTLET/CONVERSION: Genesis Wave (cleanest) / Finale→Craterhoof / Selvala-huge / gods — CONDITIONAL, board-dependent.
4. VALUE: Sabertooth + Selvala draw engine (held family).

## Open decisions carried forward
- Sabertooth blink family: HELD (Ben).
- "Synergy pairings": research surfaces the KEY payoffs/synergies from the card
  list, not the 68 unverified pairs (Ben: "let's see what the research comes
  back with using the card list").

## Next: PHASE 2 — research fan-out (Opus + Gemini), seeded with Ben's briefing.

## PHASE 2 — RESEARCH (done; full harvest in scratchpad selvala-research-harvest.json)

Opus workflow (4 angles) + Gemini cross-check, all reading card scripts. 3 of 4
Opus angles + synthesis + Gemini succeeded; the coverage-synergies angle failed
on an over-strict output schema (StructuredOutput retry cap — a brittleness bug
in the workflow instructions, not research quality). Coverage is recoverable
from the primer + card list; the three load-bearing angles (combo-mechanics,
outlet-selection, setup-dig) all landed. Opus and Gemini AGREE on every key point.

### The 7 tap-untap combos, ranked (per-cycle net; threshold; sink)
Two untap shapes: Staff = {3}{T} producer + {1} Staff = 4 generic; Umbral = {3}{Q}, +2/+2 on producer.
1. **527-2816 Selvala+Umbral (ANCHOR)** — POWER, RAMPING (+2/cyc on Selvala); net P-4; primed ~{2}{G}, opens -2,0,+2,+4; also makes Selvala infinitely large (combat wincon). Lowest board req.
2. **527-2645 Selvala+Staff** — POWER, constant-per-loop; net P-5; P>=6; Staff is BUILT-IN sink ({5}{T} draw). GOLDEN PATH for first proof (flat math, self-contained).
3. **2816-5711 Fanatic+Umbral** — CONSTANT 4 (Ferocious gate power>=4); net +1 from iter 1, no priming; commander-independent; green only.
4. **1355-2645 Weaver+Staff** — ENCHANTMENT-COUNT; net E-4; E>=5; single color; Staff sink.
5. **1355-2816 Weaver+Umbral** — ENCHANTMENT-COUNT; net E-3; **E>=4 NOT 3** (BUG: dossier says 3 = break-even net 0). Regression case.
6. **2026-2404-2645 Satyr+Cradle+Staff** — CREATURE-COUNT; net C-4; C>=5; green.
7. **2026-2404-2816 Satyr+Cradle+Umbral** — CREATURE-COUNT; net C-3; C>=4; green.
Proving order: 527-2645 (golden) -> 527-2816 (ramping code path) -> 1355-2816 (threshold regression).

### Outlet-selection decision tree (the hard part)
- **DEFAULT: Genesis Wave X=all** (board-independent) — fire if Craterhoof OR Concordant Crossroads still in LIBRARY and X>=deck size; reveal top X, drop every cmc<=X permanent (Craterhoof ETB pumps, Crossroads hastes) -> manufactures lethal board from empty. **CRITICAL OVERRIDE: force-cast bypassing Genesis Wave's NeedsToPlayVar (>=6 untapped LANDS) AI gate — Selvala mana is creature-based, so stock AI silently refuses the deck's best wincon. #1 program value.**
- Fallback ladder (descending board-independence): Goldvein Hydra X>=40 (native trample/haste, single opp) -> Rhonas pump-loop (the deck's only trample, single opp) -> Finale X>=10 (fetch Craterhoof cmc8, +X/+X+haste but NO trample) -> Craterhoof from hand (board-gated, C>=~5-6) -> Selvala-huge/Omnath combat (no evasion, needs Rhonas-trample or open attack).
- Non-terminal DIGS (never terminal, sequence AFTER choosing sink): Staff {5} draw, Nylea {2}{G} dig, Sabertooth bounce, Greater Good. Once Staff draws the library, Genesis Wave whiffs.
- **The two gods = Rhonas (trample combat) + Nylea (dig). Ojer Kaslem is NOT an outlet** (both researchers agree). Omnath = mana battery (green pool persists across phases; power=banked green).

### The two extensions, specced
**A. Variable-yield pair-verification** — yield models: POWER_CONSTANT (read at entry), POWER_RAMPING (re-eval each cycle, +2/+2 feeds next yield; prove MONOTONIC DIVERGENCE not entry-net>=1 since Umbral opens at -2), ENCHANTMENT_COUNT, CREATURE_COUNT, CONSTANT (Fanatic 4 + power>=4 gate). Per-loop generic untap cost (Staff 4 / Umbral 3), threshold, color-breadth tag, producer topology (Cradle = land<-creature<-untapper), summoning-sickness precondition. Reject net<=0 (E=3 Weaver = canonical zero-yield regression).
**B. cast_x_spell / outlet sink** — X = N-k from pool; per-spell X thresholds (Finale>=10, Genesis Wave>=deck size, Goldvein>=life); multi-part resolution (fetch-then-pump); best-value fetch (Finale->Craterhoof for trample); 4 sink shapes (X-spell, fixed+ETB, repeated activated, combat); color satisfiability; NeedsToPlayVar force-cast; board/haste/deck-out gating; restricted-mana awareness (Castle Garenbrig creature-only cannot pay generic X).

### Coverage synergies worth a program (stock AI provably wrong/absent)
Genesis Wave force-cast (#1); Omnath (AI:RemoveDeck:All, manual green retention); Concordant Crossroads (AI de-prioritizes haste + combo piece); Selvala strict-max draw (ties draw nothing) + Sabertooth blink value; per-source mana restrictions (Garenbrig/Earthcraft/Wirewood/Arbor Elf-Yavimaya); tutor routing by target type (no creature tutor finds the artifact halves — dig via Genesis Hydra/Inventors' Fair); Rhonas = only trample source. (Full list section 4 of synthesis.)

### Setup/dig recognition (two-axis)
Axis A = untap mana engine online? Axis B = untapper artifact present? A&B->execute; A-only->dig for artifact (Genesis Hydra/Inventors' Fair, NOT creature tutors); B-only/neither->tutor a power>=6 strict-max body; no-infinite-but-high-ceiling->storm-dig into Genesis Wave X~=ceiling-3. Median goldfish T5.

## Next: PHASE 3 — planning (Fable): spec the anchor 527-2645/527-2816 + extensions A & B concretely, then check in.
