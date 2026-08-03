# discovered-combos

**Schema tag:** `arena.discovered-combos/1`
**Filename:** `discovered-combos.json` (in `<deck>/dossier/`)
**Generator:** hand-authored / research subagent (domain knowledge channel)
**Consumer:** **runtime** `ComboDef.loadWithDiscovered` → `ComboTracker` (identical to `combos.json`); prep `TutorWeights`
**Status:** live

## What it is

Curated combos that **Spellbook omits** — paper lines with an open payoff slot (the
named pair alone produces no lethal feature, so the Spellbook API skips them), plus
any combo a capable model finds directly from card-text review. It is the durable
output channel for domain/model discovery, kept **separate on purpose** from the
prep-generated `combos.json` so the two provenances never blur. The tracker
consumes it exactly like a Spellbook combo; ids are `syn-`/`ben-` prefixed.

## Who generates it, and when

**Hand-authored** from Ben's domain knowledge, or **subagent-discovered** from
card-text review — never prep-generated. Each entry names the pieces the tracker
keys on; a matching [combo-program](combo-program.md) supplies the line (the
program's runner enforces any open payoff slot, e.g. `outlet_on_board`).

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.discovered-combos/1"` |
| `source` | ✓ | provenance prose (e.g. "Ben domain knowledge — paper lines Spellbook omits") |
| `combos[]` | ✓ | `{id, cards[{name}], note}` |
| `combos[].id` | ✓ | `syn-`/`ben-` id — the tracker/program key |
| `combos[].cards[]` | ✓ | `{name}` per named piece (the tracker readiness set) |
| `combos[].note` | ○ | the role breakdown / how the program enforces the payoff |
| `design_rationale` | ○ | why this file is kept separate from `combos.json` |

## Canonical example

`decks/purphoros-god-of-the-forge/dossier/discovered-combos.json`:

```json
{
  "schema": "arena.discovered-combos/1",
  "source": "Ben domain knowledge — paper lines Spellbook omits (open payoff slot)",
  "combos": [
    {
      "id": "ben-ignus-birgi",
      "cards": [ { "name": "Grinning Ignus" }, { "name": "Birgi, God of Storytelling" } ],
      "note": "3-role combo: engine (Ignus) + refund (Birgi per-cast mana) + payoff (any creature-ETB damage, e.g. Purphoros). The runner enforces the payoff via outlet_on_board; the ComboDef lists the two named pieces so the tracker marks it ready when both are present."
    }
  ],
  "design_rationale": "Ben 2026-07-30: kept SEPARATE from combos.json on purpose. Spellbook omits multi-card combos with an open payoff slot ... the tracker consumes it exactly like a Spellbook combo (ComboDef.loadWithDiscovered)."
}
```

## Consumer & invariants

**Runtime:** merged with `combos.json` by `ComboDef.loadWithDiscovered`
(`EngineFacade.java:250`) — the `ComboTracker` cannot tell the two apart. A
`discovered-combo` id is a legal [combo-program](combo-program.md) key. Invariants:
`id` prefixed `syn-`/`ben-` and unique; every `cards[].name` in the deck; a combo
with an open payoff slot **must** ship a program (its runner enforces the payoff),
because the bare pair produces no win on its own.

## Related

- Runtime twin: [combos](combos.md)
- Compiled from these: [combo-program](combo-program.md)
- Bulk discovery corpus (different shape): [discovered-synergies-wholedeck](discovered-synergies-wholedeck.md)
