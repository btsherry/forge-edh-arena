# deck-cards

**Schema tag:** `arena.deck-cards/1`
**Filename:** `deck-cards.json` (in `<deck>/dossier/`)
**Generator:** T0 deterministic prep (`IngestMain`)
**Consumer:** prep-time only — `PayoffRules`, `TutorWeights`, `DeckLint`, `GoldfishCompile`, `SpellbookClient`, `PrepAutopsy`
**Status:** live

## What it is

The **T0 card facts** for the 99+commander: the resolved, deduped list of every
card with its oracle text, type line, mana cost, color identity, zone, and
quantity. It is the deterministic ground-truth extraction the rest of prep reads
instead of re-parsing the decklist — and, alongside the raw Forge scripts, the
package a discovery subagent is handed. It is a **prep-time** artifact: the runtime
pilot never reads it.

## Who generates it, and when

**Deterministic prep**, at ingest (`IngestMain`), by resolving each decklist line
to card data. No model. `unresolved[]` collects any decklist line that failed to
resolve (empty on a clean deck). Reproducible from the decklist + card DB.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.deck-cards/1"` |
| `deck_id` | ✓ | dossier id |
| `cards[]` | ✓ | one entry per distinct card: `{name, qty, zone, mana_cost, type_line, color_identity, oracle_text}` |
| `cards[].zone` | ✓ | `commander` / `main` (where the card starts) |
| `unresolved[]` | ✓ | decklist lines that did not resolve (empty = clean) |

## Canonical example

`decks/purphoros-god-of-the-forge/dossier/deck-cards.json` (80 cards):

```json
{
  "schema": "arena.deck-cards/1",
  "deck_id": "purphoros-god-of-the-forge",
  "cards": [
    {
      "name": "Purphoros, God of the Forge",
      "qty": 1, "zone": "commander",
      "mana_cost": "{3}{R}",
      "type_line": "Legendary Enchantment Creature - God",
      "color_identity": "R",
      "oracle_text": "Indestructible\nAs long as your devotion to red is less than five, Purphoros isn't a creature.\nWhenever another creature you control enters, Purphoros deals 2 damage to each opponent.\n{2}{R}: ..."
    }
  ],
  "unresolved": []
}
```

## Consumer & invariants

Read at prep time by the classes above (payoff detection, tutor weighting, lint,
goldfish compile). Invariants: `cards[].name` must match the card DB `Name:` line
exactly (the join key everything else uses); `qty` sums to 100 for a legal
Commander deck; `unresolved[]` non-empty is a prep failure to surface, never
ship silently.

## Related

- Sibling T0 provenance: `deck-meta.yaml`, `card-scripts-index.json` (not yet paged)
- Downstream: `combos.json`, `route-coverage.json`, `tutor-priorities.json`
- The raw scripts that pair with this (T0 ground truth): `forge-gui/res/cardsfolder/**`
