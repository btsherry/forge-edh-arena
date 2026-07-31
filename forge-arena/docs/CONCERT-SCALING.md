# Concert scaling / interference report — concert60 (2026-07-31)

60-game, 4-deck pod (seed 3033), full concert: 10 Selvala combos + bounce-recursion
family + assemble-and-deploy + reactive protection + outlet ladder + pairings, all
runners live. The question: do the behaviours interfere / logically collapse as they
scale? **Answer: no collapse. The concert composes cleanly, and the win rate moved.**

## Headline
- 60 games: **52 win / 7 timeout / 1 crash**. **Crash rate 1.7%** (historically ~10% —
  the upstream recursion is not amplified by the added behaviours).
- Wins by deck: Purphoros 29, Giada 14, Urza 4, **Selvala 5/60 (8.3%)** — up from the
  pre-deploy baseline **1/30 (3.3%), a ~2.5x lift**. All four pilots function; no deck
  collapsed.

## Interference signals (the point of the run)
| Signal | Result | Read |
|---|---|---|
| **Cannibalization** (combos stealing each other's pieces) | piece_lost/misattached = **0** (was 22/30 pre-deploy) | Eliminated — the assembly gate + deploy stop it. |
| **Crash / collapse** | 1/60 | Stable; the concert does not destabilize the engine. |
| **Assembly** (deploy working) | governor_plan **18** (was 1); **62 deploy-casts + 9 equips** | The deploy phase assembles combos organically at scale. |
| **Conversion** | 3 outlets fired (Genesis Wave 2, Finale 1) + 3 program_completes | Loops convert in real games. |
| **Protection** | piece_protected **2** (Heroic Intervention, Flare of Fortitude) | The reactive save fires correctly in real games (the hard-to-gate behaviour, validated). |

## The two real contention points (refinements, NOT collapse)
1. **Outlet contention — 12 `no_outlet_castable` deferrals.** A combo banks (near-)
   infinite mana but can't cast Genesis Wave (it's undrawn, already cast, or reserved).
   Bounded — the combo defers cleanly and another line often wins — but it is the
   biggest conversion leak: the loop assembles + banks, then can't cash. **Next lever:
   outlet REACHABILITY** (route the loop to Finale/Craterhoof when Genesis Wave is gone;
   tutor the outlet during assembly).
2. **Deploy oscillation — 3 Umbral-sharing combos deployed-but-never-assembled**
   (1355-2816, 2026-2404-2816, 2816-5711). The pilot explores multiple Umbral hosts but
   only one can be attached; the assembly gate correctly blocks the rest, so it's safe,
   but some deploy actions are wasted. **Next lever: pick ONE deploy target and commit**
   (deploy toward the single highest-value assemblable combo, not all sharing a piece).

## Verdict
The scaling worry does not materialize: adding runners, combos, pairings, deploy, and
protection did NOT cause logical collapse or cross-behaviour breakage — cannibalization
dropped to zero and the crash rate fell. The remaining friction is two bounded
contention points (outlet reachability, deploy target selection), both conversion
refinements rather than stability problems.
