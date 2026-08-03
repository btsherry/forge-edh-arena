# fixtures

**Schema tag:** `arena.program-fixture/1`
**Filename:** `fixtures/fixture-<id>.json` (in `<deck>/dossier/fixtures/`)
**Generator:** deterministic prep (`ProgramGate` derive / `ProgramFixtureProbe`)
**Consumer:** `ProgramGate`, `ProgramFixtureProbe` (goldfish)
**Status:** live

## What it is

A **goldfish fixture**: the minimal board/hand/land state that puts a program's
pieces in position so the goldfish harness can play the line headless and assert
its exit event fires. One fixture per program, derived from the program's `pieces`
(honoring each piece's `requires` zone) and funded with enough basic land of the
right color to pay the line's costs. It is the "put the pieces on the table on turn
N" setup that makes Gate 4 deterministic.

## Who generates it, and when

**Deterministic prep**: `ProgramGate` derives a fixture from a
[combo-program](combo-program.md) (`derived_from` records the source), placing each
piece in its `requires` zone and choosing a basic land from the pieces' colors
(e.g. Wastes → Forest). No model.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.program-fixture/1"` |
| `combo_id` | ✓ | the program this fixture is for |
| `derived_from` | ✓ | the source program filename |
| `apply_turn` | ✓ | the turn to inject the state |
| `battlefield[]` | ✓ | cards to place in play (attachments resolved by the harness) |
| `hand[]` | ✓ | cards to place in hand (the `requires:HAND` pieces, e.g. a window body) |
| `lands` | ✓ | `{BasicName: count}` — mana to fund the line |

## Canonical example

`decks/selvala-competitive/dossier/fixtures/fixture-syn-phyrexian-dreadnought-momentous-fall.json`:

```json
{
  "schema": "arena.program-fixture/1",
  "combo_id": "syn-phyrexian-dreadnought-momentous-fall",
  "derived_from": "combo-program-syn-phyrexian-dreadnought-momentous-fall.json",
  "apply_turn": 4,
  "battlefield": [],
  "hand": [ "Phyrexian Dreadnought", "Momentous Fall" ],
  "lands": { "Forest": 10 }
}
```

## Consumer & invariants

`ProgramGate` (and `ProgramFixtureProbe`) inject this state at `apply_turn`, then
run the program and check its own exit event (e.g. `dreadnought_window`,
`engine_cycle`, mana-loop conversion). Invariants: `hand[]` must match the
program's `requires:HAND` pieces (a window body belongs in hand, not battlefield);
`lands` must fund the line's costs in the right colors; `combo_id`/`derived_from`
consistent with the program file. A fixture that under-funds the line produces a
false goldfish failure — the fixture is wrong, not the program.

## Related

- Gate: `ProgramGate` (see working-plan-Aug-3 §11); probe: `ProgramFixtureProbe`
- Derived from: [combo-program](combo-program.md)
- Fixture derivation for pairing/engine programs: task #65
