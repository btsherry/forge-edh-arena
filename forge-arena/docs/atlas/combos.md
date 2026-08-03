# combos

**Schema tag:** `arena.combos/1`
**Filename:** `combos.json` (in `<deck>/dossier/`)
**Generator:** T0/T1 deterministic prep (`SpellbookClient` fetch → `ComboPrep`)
**Consumer:** **runtime** `ComboDef.loadWithDiscovered` → `ComboTracker`; prep `DeckCoverage`, `TutorWeights`
**Status:** live

## What it is

The **Commander Spellbook attested combos** present in the deck — the bounded,
authoritative work list that a deck's ingestion must account for (completeness bar,
working-plan §4). Each entry is a Spellbook combo whose pieces are all in the 99,
with its numeric id, the exact card list + zone requirements, the prose steps, the
features it `produces`, and a `popularity` figure (a tutor-weight signal). At
runtime the pilot's `ComboTracker` watches for these to assemble.

## Who generates it, and when

**Deterministic prep**: `SpellbookClient` fetches the raw Spellbook variants
(`spellbook-raw.json`), `ComboPrep` filters to combos fully contained in the deck
and normalizes them here. No model. Combos whose pieces are only *almost* in the
deck go to [advisory-combos](advisory-combos.md) instead.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.combos/1"` |
| `deck_id`, `deck_hash`, `spellbook_snapshot` | ✓ | provenance (hash pins the deck; snapshot pins the Spellbook date) |
| `combos[]` | ✓ | one per attested combo |
| `combos[].id` | ✓ | Spellbook id (numeric, e.g. `513-5034--46`) — the tracker/program key |
| `combos[].cards[]` | ✓ | `{name, zone_req}` per piece (`zone_req` ∈ battlefield/hand/…) |
| `combos[].template_requirements[]` | ○ | generic slots (`{name, scryfall_query, zone_req, quantity}`) — an "any card that…" piece |
| `combos[].steps` | ✓ | the prose line (human/authoring reference) |
| `combos[].popularity` | ○ | Spellbook popularity → tutor-weight signal |
| `combos[].bracket_tag`, `produces[]` | ○ | power bracket; the features the combo yields |

## Canonical example

`decks/urza-lord-high-artificer/dossier/combos.json` (23 combos), first entry:

```json
{
  "id": "513-5034--46",
  "url": "https://commanderspellbook.com/combo/513-5034--46/",
  "cards": [
    { "name": "Hullbreaker Horror", "zone_req": "battlefield" },
    { "name": "Sol Ring", "zone_req": "battlefield" }
  ],
  "template_requirements": [
    { "name": "Permanent that can be cast using {C}", "scryfall_query": "mv<=1 (mana={0} or mana={1} or mana={C}) is:permanent", "zone_req": "hand", "quantity": 1 }
  ],
  "steps": "Activate Sol Ring by tapping it, adding {C}{C}. Cast the permanent ... Hullbreaker Horror triggers, returning Sol Ring ...",
  "popularity": 1234,
  "produces": ["Infinite mana", "..."]
}
```

## Consumer & invariants

**Runtime:** `ComboDef.loadWithDiscovered(dossierDir)` (`EngineFacade.java:250`)
loads `combos.json` **plus** [discovered-combos](discovered-combos.md) into one
`ComboTracker` — the tracker treats both identically. A combo's `id` is the key a
[combo-program](combo-program.md) must match (the three-way id invariant).
**Prep:** `DeckCoverage` maps combos → win routes; `TutorWeights` reads
`popularity` + piece counts for weighting.

Invariants: every `cards[].name` in the deck (else it belongs in advisory);
`id` unique and stable (it is the program/tracker key); `template_requirements`
slots are filled at runtime from the deck, not pre-bound.

## Related

- Runtime tracker twin: [discovered-combos](discovered-combos.md)
- Almost-in-deck sibling: [advisory-combos](advisory-combos.md)
- Compiled from these: [combo-program](combo-program.md)
- Raw input: `spellbook-raw.json` (not yet paged)
