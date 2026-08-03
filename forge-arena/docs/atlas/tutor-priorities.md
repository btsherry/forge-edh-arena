# tutor-priorities

**Schema tag:** `arena.tutor-priorities/1`
**Filename:** `tutor-priorities.json` (in `<deck>/dossier/`)
**Generator:** derived fold (`TutorWeights` via `PrepMain`)
**Consumer:** **runtime** `TutorRanker.loadWeights` (via `EngineFacade`)
**Status:** live

## What it is

The deck's **tutor weighting**: a card → weight map telling the pilot which cards a
search effect (Green Sun's Zenith, Chord of Calling, Worldly Tutor…) should fetch.
Weights are derived, not authored — from combo membership, route payoffs, and
engine-program pieces — with an `explanations` map recording why each card scored.
It is how "assemble toward the win" becomes a concrete fetch choice. Per the caps
(§5), the weighted set is bounded to **30–40 cards**, hub contribution ceilinged
below the combo band.

## Who generates it, and when

**Derived fold** in prep (`TutorWeights`, orchestrated by `PrepMain`): a
deterministic function of `combos.json` popularity/piece-count, `route-coverage`
payoffs, engine-program pieces, and the discovered-synergy hub fold (capped by
`HUB_CAP`). The `derivation` string records the exact formula. Reproducible from
its inputs.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.tutor-priorities/1"` |
| `deck_id`, `deck_hash`, `win_routes_version` | ✓ | provenance / cache keys |
| `derivation` | ✓ | the formula prose (combo-piece / route-payoff / engine-piece / hub contributions, max-combined) |
| `weights` | ✓ | `{card: weight}` — the map `TutorRanker` reads (0–1) |
| `explanations` | ✓ | `{card: why}` — the winning contribution per card |

## Canonical example

`decks/giada-font-of-hope/dossier/tutor-priorities.json`:

```json
{
  "schema": "arena.tutor-priorities/1",
  "deck_id": "giada-font-of-hope",
  "win_routes_version": "win-routes/6",
  "derivation": "combo pieces: (0.5 + 0.45*logNorm(popularity)) * min(1, 2/pieces), commanders x0.2; route payoffs: 0.35 + 0.35*(routes served / expressible routes); engine-program pieces: flat 0.9 ...; card weight = max over contributions",
  "weights": {
    "Heliod, Sun-Crowned": 0.95, "Walking Ballista": 0.95,
    "Land Tax": 0.9, "Scroll Rack": 0.9, "Archangel of Thune": 0.885,
    "Giada, Font of Hope": 0.105
  },
  "explanations": {
    "Heliod, Sun-Crowned": "combo 1274-3693 (popularity 48304, 2 pieces)",
    "Land Tax": "engine program piece: ep-land-tax-scroll-rack",
    "Giada, Font of Hope": "route payoff: COMMANDER_DMG_SEQUENCE (commander: command zone always available, x0.2)"
  }
}
```

## Consumer & invariants

**Runtime:** `TutorRanker.loadWeights(tutor-priorities.json)` (`EngineFacade.java:257`)
builds the ranker the pilot queries on every search effect; the ranker is also
seeded with the deck's payoff cards (route-coverage ∪ binding payoffs). Invariants:
weights in [0,1]; commanders down-weighted (×0.2 — always available from the
command zone); the weighted set respects the 30–40 cap (§5) — a fold that balloons
past it (last night's 85) is a work item to prune, not a valid artifact; every
weighted card is in the deck.

## Related

- Ranker: `TutorRanker`; derivation source: `TutorWeights`
- Inputs: [combos](combos.md), [route-coverage](route-coverage.md), [engine-program](engine-program.md), [discovered-synergies-wholedeck](discovered-synergies-wholedeck.md)
- Cap policy: working-plan-Aug-3 §5
