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
