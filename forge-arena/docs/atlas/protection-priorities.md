# protection-priorities

**Schema tag:** `arena.protection-priorities/1`
**Filename:** `protection-priorities.json` (in `<deck>/dossier/`)
**Generator:** deterministic prep (`ProtectionFinder` via `ComboPrep`)
**Consumer:** **runtime** `EngineFacade.loadProtection` → `ComboPilot.ProtectionSpec`
**Status:** live

## What it is

The deck's **reactive protection covers** — the instant-speed cards that save your
board/permanents from removal (Teferi's Protection, Heroic Intervention, Flawless
Maneuver…). The pilot holds these up as covers, ranked by cost, and fires the
cheapest sufficient one when a threat lands. A deck may hold none (the file is
optional and inert when absent).

## Who generates it, and when

**Deterministic prep**: `ProtectionFinder` scans the deck for protection effects
and records their scope + cost. No model.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.protection-priorities/1"` |
| `deck_hash` | ✓ | cache/provenance key |
| `covers[]` | ✓ | `{card, scope, mana_value}` per protective card |
| `covers[].scope` | ✓ | `ProtectionFinder.Scope` enum: `CREATURES` / `ALL_PERMANENTS` / … (default `ALL_PERMANENTS`) |
| `covers[].mana_value` | ✓ | cost, for cheapest-sufficient selection |

## Canonical example

`decks/giada-font-of-hope/dossier/protection-priorities.json`:

```json
{
  "schema": "arena.protection-priorities/1",
  "deck_hash": "9a169eea...",
  "covers": [
    { "card": "Grand Crescendo", "scope": "CREATURES", "mana_value": 2 },
    { "card": "Flawless Maneuver", "scope": "CREATURES", "mana_value": 3 },
    { "card": "Akroma's Will", "scope": "CREATURES", "mana_value": 4 },
    { "card": "Flare of Fortitude", "scope": "ALL_PERMANENTS", "mana_value": 4 }
  ]
}
```

## Consumer & invariants

**Runtime:** `EngineFacade.loadProtection` (`EngineFacade.java:330-348`) reads the
`covers[]` array into `ComboPilot.ProtectionSpec(card, Scope.valueOf(scope),
mana_value)`. Missing/unreadable file → no covers (never fatal — a deck may hold
none, exactly like an empty pairing set). Invariants: `scope` must be a valid
`ProtectionFinder.Scope` enum name (an unknown value would throw
`valueOf`); every `card` in the deck.

## Related

- Enum: `ProtectionFinder.Scope`; loader: `EngineFacade.loadProtection`
- Sibling reactive artifact: [paired-plays](paired-plays.md) (wipe + shield)
- Consumer of the same protection cards: [pairing-program](pairing-program.md)
