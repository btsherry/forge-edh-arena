# Shape census — does the build cycle converge? (2026-07-30)

**The question** (Ben, strategic planning): is the number of program *shapes*
bounded and small, or does it grow linearly with combos? If bounded, the
endgame is a compiler that populates a fixed shape set; if linear, the cycle
never ends. This census classifies every combo and pairing across the four
decks by loop-mechanic shape and by produced-feature (outlet) to answer it.

## Verdict: BOUNDED and CONVERGENT

**78 combo/pairing rows across four decks resolve into 7 shape families.
Six runners we have already built cover 82% (64/78).** The entire
un-built remainder is 14 rows in 3 shapes, dominated by ONE — `cast_recur`
(storm/magecraft), 12 rows. Build that single shape and coverage reaches
**97% (76/78)**; the final 2 are one-offs (`spell_copy`, `lock`).

This is the answer we needed: shapes do **not** grow linearly with combos.
They saturate. New combos overwhelmingly land in shapes we already
interpret, and the last meaningful shape is a single, well-understood one.

## Shape family census

| Shape family | rows | built? | notes |
|---|---:|---|---|
| pairing | 36 | ✅ | wipe+protection; all 4 decks' protection suites |
| mana_loop | 20 | ✅ | tap_untap (15) + float_copy (5); Basalt/Grim/Scepter/Selvala-Staff |
| cast_recur (storm) | 12 | ❌ | **the one shape worth building** — ritual-copy / magecraft storm |
| cast_bounce | 6 | ✅ | Tidespout/Hullbreaker + rock + fodder |
| ping_loop | 2 | ✅ | Heliod/Archangel + Walking Ballista |
| spell_copy | 1 | ❌ | one-off |
| lock / other | 1 | ❌ | one-off (Stasis-class) |

## Outlet (produces-feature) census — also bounded

The conversion side is finite too, which matters as much as the mechanic
side: a bounded set of "I have infinite X" states, each mapping to a small
set of close routines.

| Outlet class | count | conversion routine |
|---|---:|---|
| protected wipe | 36 | (pairing — self-contained, no separate outlet) |
| infinite storm count | 16 | Aetherflux storm-count → PayLife (BUILT) |
| infinite mana (colorless/colored/land/etc.) | ~26 | sink into X-outlet: Urza {5}, Finale, Aetherflux (BUILT/pending) |
| infinite draw / draw-triggers | 18 | draw-to-outlet or deck-out win (needs mapping) |
| infinite ETB / LTB / blink | 15 | ETB payoff (Terror/Purphoros class) (needs mapping) |
| infinite lifegain / magecraft / untap | ~20 | feed a payoff already on board |
| infinite damage / tokens / turns / counters | ~8 | direct or combat close |

The produced-feature vocabulary is ~15 meaningful classes, not hundreds —
Commander Spellbook's taxonomy is finite by construction, exactly as the
ingestion-landscape research reported. Feature → conversion-routine is a
lookup table, not a per-combo design problem.

## Strategic implications

1. **The compiler is the right bet.** With shapes saturating at ~7 and the
   last big one being a single shape, the expensive work (shape discovery)
   is nearly done; the remaining work (shape population) is what a compiler
   automates. Task #58's thin slice is aimed at the correct layer.

2. **`cast_recur` is the highest-value next runner** — 12 rows, all of
   Purphoros's uncompiled backlog plus Selvala magecraft lines, one shape.
   It is the `cast_bounce` payoff again: one runner unlocks a whole family.
   (Purphoros already wins at 25%+ organically, so this is coverage, not a
   win-rate emergency — but it is the last shape standing.)

3. **The un-built tail is 2 genuine one-offs** (`spell_copy`, `lock`).
   These are the honest ship-flagged floor — compile shapes that recur,
   flag the singletons. Exactly Ben's "one step beyond Forge, stop short of
   the exotic" scope.

4. **Coverage ≠ compiled.** 82% of rows are IN a built shape, but only 30
   currently have compiled programs — the other 34 in-shape rows are
   population work (clone/emit), not new runners. That gap is precisely what
   the compiler (task #3) and the cross-deck reuse proof (task #2) exist to
   close cheaply.

## Method / caveats

- Source: `combos.json` + `paired-plays.json` across the four dossiers
  (dataset in scratchpad `shape-census-dataset.json`; classified in
  `shape-census-classified.json`).
- Classification is by loop mechanic from Spellbook steps + produced
  features, cross-checked against `program_class` for the 30 already
  compiled. Two rows were hand-adjudicated (Heliod family → ping_loop;
  Devastating Onslaught → cast_recur).
- Four decks are a biased sample (blue artifacts, mono-white, mono-green,
  mono-red-ish). A broader sample (task #2's fifth deck, and any future
  ingest) will test whether 7 families holds — but the saturation trend and
  the finite Spellbook feature taxonomy both predict it will, with at most a
  few more shapes across the whole format, not per-deck growth.
