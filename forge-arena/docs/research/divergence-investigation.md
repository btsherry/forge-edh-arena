# The residual 10% divergence — investigation, not yet closed

After PR-67 made the RNG per-thread, three identical 10-game runs came back
**9/10 three-way identical** (pre-fix: 15/30 diverged). This documents the
hunt for the last 1-in-10, which is NARROWED but not solved.

## Ruled out, with evidence

| candidate | finding |
|---|---|
| unseeded randomness | zero `new Random()` / `Math.random` / `ThreadLocalRandom` in forge-ai, forge-game, or forge-arena |
| AI time budgets | `AvailableActions`' deadline is called only from `PlayerControllerHuman` (UI). `SpellAbilityPicker`'s `execTime` feeds a debug print and gates nothing; `simulation_ai` is false in our configs |
| identity hash codes | `Card` (via `GameEntity`) and `SpellAbility` both override `hashCode()` with a stable `id`, so hash-collection order is fixed |
| parallel card DB load | `executor.invokeAll(tasks)` returns futures in task order; results collected in that order |
| replacement-effect choice | `AiController.chooseSingleReplacementEffect` ends in `list.get(0)`, and the list comes from `forEachCardInGame`, which walks players and zones in fixed order |
| our own hash iteration | `ComboPilot`/`TutorRanker` iterate `Map<String,String>`; `String.hashCode` is specified and stable |

## What it actually is

Divergent seed `-609009976913779751`. First differing logged event is at
turn 27: a Purphoros trigger dealing **4 damage in run1 and 8 in run3**.

The turn-28 board snapshots are the real evidence:

```
run1  seat0 life 24  seat1 life 31  seat1 board_power 25
run3  seat0 life 16  seat1 life 23  seat1 board_power 20
```

**Everything else is identical** — hand 5, library 86, creatures 1, lands 2,
graveyard 2 for seat 0; hand 2, library 84, creatures 5 for seat 1.

Same cards drawn, same cards played. A 5-point power gap across 5 creatures
is exactly one extra activation of Purphoros's `{2}{R}: creatures you control
get +1/+0` — an ability activation changes neither hand nor library, which is
why the counts match.

**Conclusion: a different NUMBER of ability activations from identical card
state.** That is a decision-count divergence inside Forge's priority loop,
not a state or randomness divergence.

## Where to look next

Ability-priority ordering or priority-window count — `ComputerUtilAbility`
(the `p -= 10` priority sort, whose ties are broken by input order) and
`AiController.getSpellAbilityToPlay`. The input order comes from
`getSpellAbilities(cards, player)`, which is the next thing to audit.

## Why we stopped here

50% -> 10% divergence is the difference between "no A/B is meaningful" and
"A/B is meaningful for effect sizes above roughly 3 wins at n=30". The
outstanding deck-behaviour findings are much larger effects than that:
Selvala at 0/27 with an unmodelled phase-boundary constraint (Omnath's
`S:Mode$ UnspentMana`), and Giada's sweepers possibly never castable at all
(`SP$ DestroyAll` with no `ValidTgts` bound to `targeted_removal`).

Closing the last 10% is worth doing before any A/B that hinges on a 1-2 win
delta. It is not worth doing before fixing decks that win zero games.
