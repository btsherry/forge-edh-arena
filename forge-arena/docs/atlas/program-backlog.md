# program-backlog

**Schema tag:** `arena.program-backlog/1`
**Filename:** `program-backlog.json` (in `<deck>/dossier/`)
**Generator:** deterministic prep (`ProgramGate` / `PrepMain`)
**Consumer:** `ProgramGate` (reporting); the main agent (compile work list)
**Status:** live

## What it is

The **outstanding compile work** for a deck: every registered combo that has **no
compiled program yet**, plus the goldfish status of the ones that do. It is the
running answer to "is this deck's ingestion done?" — a non-empty `no_program` /
`shape_is_new` set means it is not (completeness bar §4). It closes the loop
between the discovery corpus and the compiled programs: what's left to build.

## Who generates it, and when

**Deterministic prep**: `ProgramGate` walks the registered combos, checks for a
matching [combo-program](combo-program.md), goldfishes those that exist, and records
the rest as `no_program`. No model. `seed` and `sustain_bar` pin the goldfish run.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.program-backlog/1"` |
| `seed` | ✓ | goldfish seed (reproducibility) |
| `sustain_bar` | ✓ | iterations a loop must sustain to count as executable |
| `programs[]` | ✓ | one per registered combo |
| `programs[].combo_id` | ✓ | the combo |
| `programs[].status` | ✓ | `no_program` / (goldfish outcome for compiled ones) |
| `programs[].reason` | ✓ | e.g. "no compiled program — build backlog" |
| `programs[].iterations`, `win` | ✓ | goldfish result (0/false when uncompiled) |

## Canonical example

`decks/purphoros-god-of-the-forge/dossier/program-backlog.json` (6 uncompiled):

```json
{
  "schema": "arena.program-backlog/1",
  "seed": 42,
  "sustain_bar": 5,
  "programs": [
    { "combo_id": "147-1235", "status": "no_program", "reason": "no compiled program — build backlog", "iterations": 0, "win": false },
    { "combo_id": "411-3101", "status": "no_program", "reason": "no compiled program — build backlog", "iterations": 0, "win": false }
  ]
}
```

## Consumer & invariants

`ProgramGate` produces and re-reads it to report the executable/flagged/no_program
split (echoed in [dossier](dossier.md) `status.programs`). The main agent uses it as
the compile work list. Invariants: every `combo_id` is a registered combo
([combos](combos.md)/[discovered-combos](discovered-combos.md)); a `no_program`
entry is a **mandatory** work item (§4), not a permanent state; when a program is
compiled and goldfishes green, its entry flips out of `no_program`. `shape_is_new`
records from the discovery corpus feed straight into this backlog.

## Related

- Gate: `ProgramGate`; rollup in [dossier](dossier.md) `status.programs`
- Fed by: [discovered-synergies-wholedeck](discovered-synergies-wholedeck.md) `shape_is_new_backlog`
- Cleared by compiling: [combo-program](combo-program.md)
