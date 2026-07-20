# Phase 10 results — PR-A/B/C, first trustworthy deck-behaviour measurement

Deterministic harness, 30 games, same seeds as the rebaseline.

| deck | rebaseline | phase 10 | note |
|---|---|---|---|
| Selvala | 0/27 | **1/30** | off zero; x_spell_cast fired (PR-A mechanism confirmed) |
| Purphoros | 8/27 | 9/30 | within noise, direction right |
| Urza | 0/27 | **0/30** | unchanged — see below |
| Giada | 9/27 | 12/30 | up, within-but-toward the noise band |

Three decks moved the right way, none regressed, one mechanism-confirmed new
win. Modest and real. Not "done".

## The honest caveats

- **n=30 with a 10% divergence floor.** A +3 (Giada) and +1 (Purphoros) are
  consistent with improvement, not proof of it. Only Selvala's move is
  mechanism-confirmed rather than count-inferred.
- **Crash rate 4/30 (~13%)** — consistent with the ~10-11% measured all
  along; the new code neither caused nor cured it.

## Urza: I had the diagnosis wrong, and the funnel corrected it

I was about to build the `free_cast_grant` -> Aetherflux execution path,
believing Urza failed at CONVERSION. The funnel says otherwise:

```
combo fires        : 1   (in 30 games)
conversion kinds   : {DIG_ACTIVATE: 1}
ignored reasons    : {mana_reserved: 22, no_viable_route: 7}
```

**Urza fires his engine once in thirty games.** He is not failing to convert
infinite mana into a win — he is failing to ASSEMBLE the loop that makes the
mana. PR-B fixed his mana ACCOUNTING (Workshop mana no longer miscounted
toward {5}), which was a real correctness bug, but correct accounting on a
combo that never assembles changes no games.

Building the Aetherflux payoff now would be the PR-65 mistake again: a
conversion path for an engine that is off. The real Urza work is upstream —
why his combos do not assemble. His pieces are Isochron Scepter (imprint,
`AI:RemoveDeck`) and cast-bounce loops needing specific fragile parts, and
`no_viable_route: 7` says several detected combos still map to no executor.

**Next Urza step is a coverage/assembly diagnosis, NOT a payoff build.**
Deferred deliberately rather than acted on wrong.

## What actually shipped

PR-A (Selvala x_spell_outlet + phase discipline), PR-B (Urza restricted-mana
accounting + ability-cost-reduction split), PR-C (amplifier-aware lethality,
multipliers-first). All deck-agnostic, all in our layer, 234/234 tests green.

Deferred from the plan: PR-D (prune Emeria's Call class), PR-E (graceful
abort on engine rejection), and Giada's sweepers (she is the best deck; MLD
heuristics are a proxy trap).
