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

## CORRECTION (Ben, 2026-07-30) — trample is BROADLY available; research was wrong
Ben challenged "Rhonas is the only trample source." Verified from scripts:
- 8 BUILT-IN tramplers: Defiler of Vigor, Frenzied Baloth, Goldvein Hydra, Managorger Hydra, Ojer Kaslem, Phyrexian Dreadnought, Sheltering Ancient, Surrak and Goreclaw.
- 3 GRANT trample to your team: Craterhoof Behemoth (KW$ Trample to all your creatures + X/+X), Garruk Wildspeaker (ult), Rhonas.
Outlet-tree corrections: (1) Craterhoof from hand IS a trample overrun (upgrade its ranking — it was wrongly gated as no-trample). (2) Finale->Craterhoof IS trample (Finale's OWN pump grants none, but the fetched Craterhoof grants the whole board trample + X/+X). (3) The "wide board / Selvala-huge needs Rhonas" caveat is largely dissolved — trample is available from 8 natives + 3 grants; only making SELVALA HERSELF (commander, no native trample) connect still needs a grant, of which there are now three, not one.

## PHASE 2b — SYNERGY CENSUS (re-run, Opus + Gemini, plain-text/no-schema — both succeeded)
The failed coverage angle re-run with improved instructions. Opus read EVERY card script; Gemini corroborated (12.9k). ~40 synergies across 6 families (A ramp-burst/land-tricks, B value engines, C cheat-into-play/tutor-routing, D protection, E combat/overrun, F recursion).

### Trample, fully corrected (Ben + Opus + scripts)
Standing team-trample: **Surrak and Goreclaw** (S:Mode$ Continuous | Affected$ Creature.Other+YouCtrl | AddKeyword$ Trample — "other creatures you control have trample" + ETB +1/+1 & haste). One-shot team grants: Craterhoof (+trample +X/+X), Garruk ult. Repeatable per-target: Rhonas. Plus 8 native tramplers. => the "needs Rhonas" caveat is fully dead; Surrak converts a Genesis-Wave/Finale mass-dump into an immediate lethal (standing trample + hastes every ETB).

### Ranked shortlist — synergies worth a compiled program (stock AI provably wrong/absent)
1. Genesis Wave force-cast past NeedsToPlayVar (>=6 untapped LANDS; Selvala mana is creature-based) — highest value.
2. Combo-half tutor ROUTING: Genesis Hydra (Permanent.nonLand->battlefield) & Inventors' Fair (Artifact->hand, metalcraft) are the ONLY finders of Staff/Umbral — no creature tutor (GSZ/Finale/Nature's Rhythm/Invasion) can reach an artifact.
3. Selvala strict-max draw sequencing (cast ascending; ties draw nothing) + Sabertooth/Kogla blink-replay of the biggest body.
4. Restricted-mana awareness: Castle Garenbrig 6 (creature-only, cannot pay Staff/Umbral), Delighted Halfling (legendary-only), Gemstone Caverns.
5. Finale->Craterhoof best-value fetch + X>=10 (Craterhoof supplies the trample, corrected).
6. Omnath green-mana retention (AI:RemoveDeck:All; pool persists across phases).
7. Land-untap-target selection: untap Cradle/Nykthos (highest yield), not a Forest; Deserted Temple/Magus/Garruk-+1/Saryth as burst enablers.
8. Surrak standing trample + Concordant Crossroads haste — convert a mass-dump to same-turn lethal.
9. Smuggler's Surprise Spree (flash 2 creatures into play / protect / dig).
10. Lightning Greaves (SHROUD) blocks your own Umbral equip -> use Swiftfoot Boots (hexproof) on the Umbral target.
11. Greater Good/Life's Legacy/Momentous Fall sac-target discipline (sac biggest expendable, preserve Selvala + pieces).
12. Dosan green-light detection (hold the all-in turn until Dosan / uncounterability stack online).

### Corrections to prior research (from the script reads)
- **Earthcraft is NOT infinite mana in this 99** (untaps BASICS only, no free creature-untap/token loop) — the primer's infinite claim is FALSE; it's finite creature->mana ramp.
- **Archdruid's Charm tutor mode puts creatures to HAND** (lands to battlefield tapped), does NOT cheat creatures into play.
- **Zilortha (Invasion of Ikoria back)**: non-Human team assigns combat damage AS UNBLOCKED — stronger than trample, a distinct combat payoff.
- Inventors' Fair / Genesis Hydra are the deck's ONLY Staff/Umbral tutors (first-class tutor-routing fact).
Full census in scratchpad (Opus report) — the coverage layer for the pilot beyond the 7 combos + their sinks.

## PHASE 3 — PLANNING (Fable, 2026-07-30) — the build spec, grounded in the code

### The structural fact that defines the whole arc
The existing `mana_loop` tap_untap path (ManaLoopRunner lines ~322-370, Urza's Basalt/Grim + Power-Artifact combos) assumes **producer == untapper**: one `engineCard = body[0].card` is tapped for mana AND untapped by `body[1].cost`, with a CONSTANT `expected_net_per_pair` (Urza = +1). Selvala breaks BOTH assumptions:
- **producer != untapper.** Selvala (body[0]) taps for X; a SEPARATE card untaps her — Staff of Domination in two steps ({3}{T} untap Selvala, then {1} untap Staff itself = {4} total), or Umbral Mantle in one ({3}, untap+`+2/+2`).
- **X is VARIABLE**, not a constant net. Selvala's `AB$ Mana | Amount$ X`, X = greatest creature power. Staff line: X constant per loop (power fixed) -> net = X-4. Umbral line: each untap pumps Selvala +2/+2 -> X RAMPS +2/cycle -> net = X-3 growing.
These two breaks ARE extensions A and B. Neither is Selvala-specific in the code — `yield_model` + producer/untapper split are general capabilities (they also serve Fanatic, Weaver, Satyr+Cradle rows). No deck-specific logic.

### Extension A — variable-yield, producer!=untapper tap_untap (ManaLoopRunner)
Generalize the tap_untap loop:
- `loop.producer` = body[0] (Selvala): activate her mana ability; yield X from `yield_model`.
- `loop.untap_sequence` = body[1..] : the ORDERED abilities that untap the producer (Staff = 2 steps, Umbral = 1). Resolve each on `body[i].card` (NOT reused engineCard — the current bug for this shape), targeting the producer where the ability targets.
- `loop.yield_model` in {POWER_CONSTANT, POWER_RAMPING, ENCHANTMENT_COUNT, CREATURE_COUNT, CONSTANT}: computes expected X from LIVE board each cycle. Per-cycle expected net = X(model,live) - sum(untap step generic costs).
- MEASURED per-cycle delta check already exists (pool grew >= expected net AND producer untapped) — feed it the COMPUTED net, not a constant.
- **RAMPING divergence proof (Umbral):** do NOT gate on entry-net>=1 (Umbral opens at -2, then 0, +2, +4...). Prove MONOTONIC DIVERGENCE: X strictly increases (+2/cycle from the Mantle pump) => exists cycle k past which net>0 and the pool diverges. Governor primes the small deficit (~{2}{G}) then rides the ramp; cap by ITERATION_CAP as backstop.
- **Reject non-diverging net<=0 (the E=3 Weaver regression):** ENCHANTMENT_COUNT E=3 -> net 0 forever -> abort at entry `zero_yield: E=3 net 0`. This is the canonical guard the dossier's "E>=4 not 3" bug demands.
- Precondition: producer not summoning-sick (Selvala can't tap the turn she lands).
- **Guard so Urza stays byte-identical:** the new path activates ONLY when `yield_model` is present; absent -> the existing constant-net path runs unchanged. Seed-paired Urza regression check before/after.

### Extension B — cast_x_spell / outlet-selection sink
Once pool >= target, pick the LETHAL outlet by the Phase-2 decision tree instead of the Aetherflux storm sink:
- **DEFAULT Genesis Wave X=all, FORCE-CAST bypassing NeedsToPlayVar** (the AI's >=6-untapped-LANDS gate; Selvala mana is creature-based so stock silently refuses). This is the #1-value seam and the main new mechanism — hosted on the existing obligation/force seam (orderAndPlaySimultaneousSa machinery from the Heliod fix).
- X = pool - reserve; per-spell X thresholds (Genesis Wave >= deck size; Finale >= 10; Goldvein >= life).
- Best-value fetch: Finale -> Craterhoof (trample-correct now). Trample/haste/board gating from the CORRECTED census (Surrak standing team-trample anthem + hastes ETBs; Craterhoof one-shot grant).
- **Golden path 527-2645 uses Staff's BUILT-IN sink** ({5}{T}: draw a card, repeat to draw the deck) -> then a real in-hand outlet. No cast_x_spell/force-cast needed for the FIRST gate — sequences the risk.

### Proving order (Ben's) — risk sequenced low->high
1. **527-2645 Selvala+Staff (GOLDEN PATH)** — POWER_CONSTANT, producer!=untapper 2-step untap, Staff built-in draw sink. Flat math, self-contained, NO force-cast. First gate.
2. **527-2816 Selvala+Umbral (RAMPING)** — POWER_RAMPING divergence path + first cast_x_spell outlet (Genesis Wave force-cast). Second gate.
3. **1355-2816 Weaver+Umbral (THRESHOLD REGRESSION)** — ENCHANTMENT_COUNT, proves the E>=4 zero-yield reject. Third gate.
Then SWEEP the remaining 4 tap_untap rows (Fanatic CONSTANT, Weaver+Staff, Satyr+Cradle x2) — clones of A/B, no new mechanism.

### Explicitly NOT in this pass
Sabertooth blink family (HELD). Setup/dig storm layer (separate concern, later). The 68 unverified discovered-synergies (research already surfaced the 12 that matter).

### Phase 4 deliverables (code — awaiting check-in)
1. ManaLoopRunner: producer!=untapper generalization + `yield_model` + monotonic-divergence entry guard + zero-yield reject. Guarded so Urza is unchanged.
2. Outlet-selection sink (small OutletSelector) with Genesis Wave force-cast on the obligation seam.
3. Three combo-program JSONs (527-2645, 527-2816, 1355-2816) to the extended schema; discovered nothing new — all three are Spellbook combos already in combos.json.
4. Gate fixtures per combo; seed-paired Urza regression check.

### Technical risks flagged for the check-in
- **R1 (shared-runner regression):** generalizing ManaLoopRunner touches Urza's passing combos. Mitigation: yield_model-gated new path + seed-paired Urza before/after. Recommend GENERALIZE (keeps one runner, capability is general) over forking a SelvalaManaLoopRunner.
- **R2 (force-cast seam):** Genesis Wave force-cast past NeedsToPlayVar is the one genuinely new mechanism. Mitigation: golden path (gate 1) needs none; prove the runner on Staff's built-in sink FIRST, add force-cast only for gate 2. If the obligation seam can't host a clean force-cast, fall back to Staff-built-in + Finale-from-hand outlets and treat force-cast as its own spike.
