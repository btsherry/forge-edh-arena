# route-coverage

**Schema tag:** `arena.route-coverage/2`
**Filename:** `route-coverage.json` (in `<deck>/dossier/`)
**Generator:** deterministic prep (win-routes engine via `PrepMain`)
**Consumer:** **runtime** `RoutePlan.load` (payoffs) via `EngineFacade`; prep `TutorWeights`, `PrepAutopsy`
**Status:** live

## What it is

The deck's **win-route analysis**: for each combo, the features it produces mapped
to the abstract win routes they serve (DIRECT_DAMAGE_LOOP, SPREAD_COMBAT,
DECK_ACCESS…), plus the deck's **payoff inventory** (cards grouped by payoff
function), the routes the deck can actually express (supported / unsupported /
missing), and guard notes. It answers "if I have infinite X, how does this deck
turn it into a win?" — the conversion half of the pipeline. The `deck.payoffs`
block is what the runtime pilot reads to seed conversion tutoring.

## Who generates it, and when

**Deterministic prep**: the win-routes engine (`win-routes/6`) maps combo features
→ routes and classifies each route's support from the deck's payoff cards. No
model. `schema` is at **v2**.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.route-coverage/2"` |
| `deck_id`, `deck_hash`, `win_routes_version` | ✓ | provenance / cache keys |
| `combos[]` | ✓ | `{id, features[{name, category, routes[]}], direct_win}` — per-combo feature→route mapping (`category` ∈ RESOURCE/LETHAL/…) |
| `deck.payoffs` | ✓ | `{payoff_function: [cards]}` — the inventory the pilot reads (`mass_pump`, `ping_each_opponent`, `haste_*`, `draw_engine_permanent`, …) |
| `deck.routes[]` | ✓ | `{route, origin, support, from_combos[], enablers[], missing[]}` — support ∈ intrinsic/supported/unsupported |
| `deck.guards[]` | ○ | `{id, severity, detail}` — e.g. ORACLE_WIN not expressible without a Thassa's Oracle |
| `deck.win_paths` | ✓ | count of expressible win paths |
| `unroutable_features[]`, `status` | ✓ | leftovers; `clean` when all features route |

## Canonical example

`decks/purphoros-god-of-the-forge/dossier/route-coverage.json`:

```json
{
  "schema": "arena.route-coverage/2",
  "deck_id": "purphoros-god-of-the-forge",
  "combos": [
    { "id": "1110-6785", "features": [ { "name": "Near-infinite damage", "category": "LETHAL", "routes": ["DIRECT_DAMAGE_LOOP"] } ], "direct_win": true }
  ],
  "deck": {
    "payoffs": {
      "ping_each_opponent": ["Purphoros, God of the Forge", "Agate Instigator", "Chandra, Torch of Defiance"],
      "haste_equip": ["Lightning Greaves"]
    },
    "routes": [
      { "route": "DIRECT_DAMAGE_LOOP", "origin": "direct", "support": "intrinsic", "from_combos": ["1110-6785", "..."], "enablers": ["Purphoros, God of the Forge", "..."] },
      { "route": "ORACLE_WIN", "origin": "conversion", "support": "unsupported", "from_combos": ["1878-3368"], "missing": ["oracle_win"] }
    ],
    "guards": [ { "id": "oracle_guard", "severity": "info", "detail": "DECK_ACCESS present but no Thassa's Oracle class effect — ORACLE_WIN not expressible; self-draw must stop short of the library" } ],
    "win_paths": 2
  },
  "unroutable_features": [], "status": "clean"
}
```

## Consumer & invariants

**Runtime:** `RoutePlan.load(route-coverage.json)` (`EngineFacade.java:255`);
`routePlan.payoffs()` seeds the tutor ranker's conversion targets (the DEPLOY
breadth set), so a proven line tutors toward conversion, not just assembly.
**Prep:** `TutorWeights` uses route payoffs in its derivation; `PrepAutopsy`
audits coverage. Invariants: an `unsupported`/`missing` route must never be tutored
toward as if reachable (the guards enforce this — e.g. don't self-mill into a
library-out with no oracle win); `deck.win_paths` ≥ 1 for a viable deck; every
payoff/enabler card in the deck.

## Related

- Loader: `RoutePlan`; win-routes rules: `docs/WIN-ROUTES.md`
- Seeds: [tutor-priorities](tutor-priorities.md) (payoff weighting)
- Per-combo features from: [combos](combos.md)
