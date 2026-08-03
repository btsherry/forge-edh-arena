# paired-plays

**Schema tag:** `arena.paired-plays/1`
**Filename:** `paired-plays.json` (in `<deck>/dossier/`)
**Generator:** deterministic prep (`ComboPrep` / `ProtectionFinder`)
**Consumer:** **runtime** `ExecutorBindings.withPairedPlays` (via `EngineFacade`)
**Status:** live

## What it is

The deck's **wipe + shield candidate pairs** — every combination of a mass-removal
spell with a reactive protection card that would survive it, enumerated with the
combined mana cost. It is the deterministic candidate set that the hand-authored
[pairing-program](pairing-program.md)s are compiled *from* (a pairing program
references its `paired-plays` entry by id), and that the executor bindings load so
the pilot knows which pairs exist.

## Who generates it, and when

**Deterministic prep**: the cross product of the deck's wipes × protection covers,
filtered to pairs where the shield covers the wipe's scope on your side, each with
`combined_mana_value`. No model. Ordered by combined cost.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.paired-plays/1"` |
| `deck_hash` | ✓ | provenance/cache key |
| `pairs[]` | ✓ | `{id, trigger_card, protection_card, wipe_scope, combined_mana_value}` |
| `pairs[].id` | ✓ | `pp-<wipe>-<shield>` — the key a [pairing-program](pairing-program.md) references |
| `pairs[].trigger_card` | ✓ | the wipe |
| `pairs[].protection_card` | ✓ | the shield |
| `pairs[].wipe_scope` | ✓ | `CREATURES` / `LANDS` / `NONLAND_PERMANENTS` / `ALL_PERMANENTS` |
| `pairs[].combined_mana_value` | ✓ | wipe + shield cost (fire-affordability) |

## Canonical example

`decks/giada-font-of-hope/dossier/paired-plays.json` (36 pairs), sample:

```json
{
  "schema": "arena.paired-plays/1",
  "deck_hash": "9a169eea...",
  "pairs": [
    { "id": "pp-doomskar-teferi-s-protection", "trigger_card": "Doomskar", "protection_card": "Teferi's Protection", "wipe_scope": "CREATURES", "combined_mana_value": 8 },
    { "id": "pp-armageddon-teferi-s-protection", "trigger_card": "Armageddon", "protection_card": "Teferi's Protection", "wipe_scope": "LANDS", "combined_mana_value": 7 }
  ]
}
```

## Consumer & invariants

**Runtime:** `ExecutorBindings.load(...).withPairedPlays(dossier/paired-plays.json)`
(`EngineFacade.java:253`) merges these into the executor bindings; the pilot fires
a pair once per pair per game. Not every listed pair has a compiled
[pairing-program](pairing-program.md) — the JSON program adds the explicit
respond-on-stack sequence and audit; the raw pair is the candidate. Invariants:
`id` unique and matching the pairing-program filename key when one is compiled;
both cards in the deck; `wipe_scope` from the fixed vocabulary.

## Related

- Compiled into: [pairing-program](pairing-program.md)
- Shares protection cards with: [protection-priorities](protection-priorities.md)
- Bindings loader: `ExecutorBindings.withPairedPlays`
