# engine-program

**Schema tag:** `arena.engine-program/1`
**Filename:** `engine-program-<id>.json` (in `<deck>/dossier/`)
**Generator:** hand-authored (main agent, Compile step)
**Consumer:** `EngineFacade` scan → `ComboPilot.setEnginePrograms` → `EngineProgramRunner`
**Status:** live

## What it is

A hand-authored plan for a **background card-advantage engine** — a two-piece
value cycle the pilot runs a bit each turn, forever, with **no exit state**. Unlike
a combo-program it never "completes" or "converts": it just wants both pieces on
the battlefield and then activates one gated cycle per turn. The archetypal case is
Land Tax + Scroll Rack, where the stock AI literally never plays the engine (Scroll
Rack carries `AI:RemoveDeck:All`; Land Tax's condition sits dead), so the whole
value is pilot-delivered. The class exists precisely for **finite-but-repeating
plays that boost card quality** — a desirable engine, not an infinite loop
(working-plan §4).

## Who generates it, and when

**Hand-authored by the main agent** in the **Compile** step, with the two scripts
in context. `compiled_from` records the `script_hashes` and an
`oracle_cross_check` that must explain *why stock fails to run the engine* (that
gap is the whole reason the program exists) plus the `load_bearing_interaction`
(here: Rack is worthless without a shuffle; Land Tax's fetch IS the shuffle). A
`feasibility` doc pointer is included when one was written.

## Schema

| Field | Req | Read by | Meaning |
|---|---|---|---|
| `schema` | ✓ | (validator) | literal `"arena.engine-program/1"` |
| `engine_id` | ✓ | keying | **must equal the filename id** (`ep-...`) |
| `name` | ✓ | logs | human label |
| `compiled_from` | ✓ | provenance | `script_hashes`, `oracle_cross_check` (must state the stock-failure gap), `load_bearing_interaction`, optional `feasibility` |
| `pieces[]` | ✓ | runner | `{card, role:"engine", cost, note}`; the `note` carries cast-timing intent (e.g. "cast EARLY") |
| `setup[]` | ✓ | `EngineProgramRunner` | `{action:"cast", card, frequency, priority}` — which pieces to cast and when |
| `cycle` | ✓ | `EngineProgramRunner` | the per-turn activation (see below) |
| `verify` | ○ | measurement | invariants to check + the `engine_cycle` event emitted per activation |
| `on_interruption` | ✓ | runner | `idle_and_retry` — an engine has no exit state; a missing piece just waits |
| `self_consumption` | ○ | runner/humans | resource drain, if any (here `none`) |
| `success_metric` | ○ | humans | what a batch should move (entry rate + basics swapped) |
| `schema_notes` | ○ | humans | class description + discovery pattern |

### `cycle` (the per-turn action)

| Field | Meaning |
|---|---|
| `frequency` | `per_turn` |
| `gates[]` | ordered prose gates that must ALL hold to activate (both pieces out; the load-bearing live-condition, e.g. "an opponent controls more lands"; resource availability; untapped + mana) |
| `action` | `{activate, cost}` — the ability to fire |
| `exile_policy` / `put_back_order` / *(class-specific)* | how the cycle chooses what to move; v1 is deliberately conservative (basics only) |

## Canonical example

`decks/giada-font-of-hope/dossier/engine-program-ep-land-tax-scroll-rack.json`:

```json
{
  "schema": "arena.engine-program/1",
  "engine_id": "ep-land-tax-scroll-rack",
  "name": "Land Tax + Scroll Rack",
  "compiled_from": {
    "script_hashes": { "land_tax": "a8d0e98d2aecaa7c", "scroll_rack": "113c4d933544458e" },
    "oracle_cross_check": "... Scroll Rack carries AI:RemoveDeck:All — stock never plays it; measured 60 games: zero casts. The engine is 100% pilot-delivered.",
    "load_bearing_interaction": "Rack without a shuffle is worthless. Land Tax's fetch IS the shuffle. The cycle gate requires the Tax condition LIVE (an opponent has more lands) at activation."
  },
  "pieces": [
    { "card": "Land Tax", "role": "engine", "cost": "{W}", "note": "cast EARLY" },
    { "card": "Scroll Rack", "role": "engine", "cost": "{2}", "note": "cast by the pilot (stock never will)" }
  ],
  "setup": [
    { "action": "cast", "card": "Land Tax", "frequency": "once", "priority": "early" },
    { "action": "cast", "card": "Scroll Rack", "frequency": "once", "priority": "early" }
  ],
  "cycle": {
    "frequency": "per_turn",
    "gates": [ "both pieces on the battlefield", "shuffle_available: an opponent controls MORE lands than we do", "excess_basics: at least one basic beyond the land drop", "rack untapped and {1} available" ],
    "action": { "activate": "Scroll Rack", "cost": "{1}" },
    "exile_policy": "v1: exile ONLY excess basic lands; never nonland, payoffs, or program pieces."
  },
  "verify": { "hand_size_preserved": "the swap is 1:1", "event": "engine_cycle {swapped, turn} per activation, MEASURED after the stack empties" },
  "on_interruption": "idle_and_retry — an engine has no exit state; a missing piece simply waits",
  "self_consumption": { "resource": "none" },
  "success_metric": "program/pairing ENTRY RATE across a batch plus basics swapped per game"
}
```

## Consumer & invariants

**Discovery.** `EngineFacade.comboAwareLobbyPlayer` (`EngineFacade.java:302-314`)
filters `engine-program-*.json` and keys each by `filename.substring(15, len-5)`
(strip the 15-char `engine-program-` prefix and `.json`). The key → path map goes
to `ComboPilot.setEnginePrograms` (`ComboPilot.java:488`).

**Dispatch.** `ComboPilot` runs the engine cycle when both pieces are out and the
gates hold — one gated cycle per turn (`ComboPilot.java:545`) — handing off to
`EngineProgramRunner`. Unlike combo-programs there is no `program_class` and no
ComboTracker readiness/conversion; the gate is piece-presence + the cycle's own
live-condition.

**Invariants that MUST hold:**

1. `engine_id` **==** the filename id.
2. `on_interruption` is `idle_and_retry` — an engine never aborts a game turn on a
   missing piece; it waits and re-evaluates.
3. Every `cycle.gates` entry the runner relies on must be a *live, checkable*
   condition (the load-bearing one especially — here the shuffle proxy). A gate
   that is prose-only but not enforced is a correctness bug.
4. `exile_policy` (or the equivalent choose-what-to-move rule) must never touch
   payoffs, program pieces, or pairing cards.

## Validation

- **Goldfish:** `ProgramGate` counts `engine_cycle` as the verified exit event
  (an engine "succeeds" by completing a measured cycle after the stack empties).
- **Regression + A/B:** as the program family; the `success_metric` is entry rate,
  not win rate (an engine is upstream of conversion).
- **Schema (§8.2, pending):** engine-program has no polymorphic body, so a single
  JSON Schema covers it.

## Related

- Runner: [`runner-cat.md`](../runner-cat.md) → `EngineProgramRunner`
- Sibling artifacts: [combo-program](combo-program.md), [pairing-program](pairing-program.md)
- Gate 4 fixture derivation for engine programs: task #65
