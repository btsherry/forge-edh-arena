# Combo accounting — all 42 detected combos across four decks

Two-level audit, because the Power Artifact bug proved a binding can EXIST
and model the wrong mechanic. Level 1: is it bound? Level 2: does the bound
one validate in a game (only the batch shows this).

## Coverage after this pass

| deck | combos | bound | unbound |
|---|---|---|---|
| Purphoros | 6 | 3 | 3 |
| Selvala | 11 | 8 | 3 |
| Urza | 23 | 17 | 6 |
| Giada | 2 | 2 | 0 |
| **total** | **42** | **30** | **12** |

## Bound this pass (mirror a PROVEN working shape)

- `1355-2816` Sanctum Weaver + Umbral Mantle — mirrors Selvala+Mantle (527-2816)
- `1355-2645` Sanctum Weaver + Staff of Domination — mirrors Selvala+Staff

Both are `TapForManaUntapLoop` with a different engine. The archetype
sim-validates on a copy at fire time, so a wrong yield aborts honestly rather
than firing a fiction — the same guard that caught Power Artifact.

## Fixed this pass (bound but WRONG mechanic)

- `4131-5149` / `2585-5149` Power Artifact + Basalt/Grim Monolith — Power
  Artifact was modelled as an untapper; it is a cost REDUCER on the engine's
  self-untap. Re-modelled, goldfish-verified (PR-D1).

## Unbound, and WHY — not faked

These do not mirror a proven shape. Binding them wrong is worse than leaving
them unbound (the pilot enters, aborts, and burns priority windows). Each
needs either a new archetype or a verified new binding shape.

**Copy-a-mana-ability loops** (need a "copy" archetype, not tap/untap):
- `4131-4235` Rings of Brighthearth + Basalt Monolith — Rings copies the
  {3} self-untap for {2}
- `4131-5390` Basalt Monolith + Forensic Gadgeteer — ability-cost reduction
  on the self-untap, like Power Artifact but not yet mirrored
- `3094-4821` Dramatic Reversal + Lithoform Engine

**Storm / spell-copy rituals** (SpellCopyLoop candidates, need verification):
- `1878-3368` Jeska's Will + Reiterate
- `2091-3368` Mana Geyser + Reiterate

**Genuinely novel / multi-piece:**
- `2816-5711` Umbral Mantle + Fanatic of Rhonas (dual-mode mana, ferocious
  gate — the PR-60 highest-yield-ability fix is a prerequisite)
- `2026-2404-2645` / `2026-2404-2816` Voyaging Satyr + Gaea's Cradle + Staff/Mantle
  (untap a LAND that scales with creatures — three-piece, land-based)
- `11-5261--41` Narset's Reversal + Isochron Scepter (imprint + counter loop)
- `2364-2495-3094` Lithoform Engine + Tezzeret + Mana Vault
- `3363-4331` Drafna + The One Ring
- `1110-6785` Devastating Onslaught + Terror of the Peaks

## Discipline note

Every binding here was checked against the card SCRIPT, not oracle prose or
memory. The two I bound mirror a shape that already wins games; the twelve I
left are honestly flagged rather than bound wrong to inflate a coverage
number. Coverage is only real if the bound combo VALIDATES — the batch is
the arbiter, not this table.
