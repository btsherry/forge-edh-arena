# combo-program

**Schema tag:** `arena.combo-program/1`
**Filename:** `combo-program-<id>.json` (in `<deck>/dossier/`)
**Generator:** hand-authored (main agent, Compile step)
**Consumer:** `EngineFacade` scan → `ComboPilot` dispatch → `ComboAwareLobbyPlayer` runner switch (polymorphic on `program_class`)
**Status:** live

## What it is

A hand-authored execution plan for **one combo**: the exact line the pilot runs
once that combo's pieces are truly assembled. It is the richest, most-authored
artifact in the pipeline — each one turns a discovered/attested combo into a
deterministic sequence a runner can drive over the stock Forge AI. A combo that
has a program **runs ONLY through it** (`EngineFacade` comment,
`EngineFacade.java:274-275`); the generic assembly/tutor path stops owning it once
a program exists. The file is *polymorphic*: a shared envelope plus a
class-specific execution body selected by `program_class`, which names the runner.

## Who generates it, and when

**Hand-authored by the main agent** during the **Compile** step (§3), with the
card scripts, deck text, strategy doc, and rules digest fully in context. Never
auto-emitted, never written by a discovery subagent (blind subagent authoring is
banned). The `compiled_from` block records the provenance — the literal script
costs cross-checked and the yield/window rationale — so the author's reasoning is
auditable. Input is a discovery record (`discovered-*.json`) or a Spellbook combo
(`combos.json`); output is this program, validated before it ships.

## Schema

### Envelope (all classes)

| Field | Req | Read by | Meaning |
|---|---|---|---|
| `schema` | ✓ | (validator) | literal `"arena.combo-program/1"` |
| `program_class` | ✓ | `ComboAwareLobbyPlayer.programClassOf` (`:132`) | selects the runner; unknown → `program_class_unsupported` abort |
| `combo_id` | ✓ | `ComboPilot` (`:261`), gates & telemetry | **must equal the filename id AND a registered combo id** (see invariants) |
| `name` | ✓ | logs | human label |
| `compiled_from` | ✓ | (provenance, humans/validator) | `script_cross_check` + a `*_rationale`; quotes real script costs |
| `pieces[]` | ✓ | `ComboPilot` piece-attachment gate (`:252`) | each `{card, role, requires}`; `requires` ∈ `HAND` / `BATTLEFIELD` (+ attachment prose) |
| `setup[]` | ○ | runner | pre-line actions (e.g. cast/equip); empty when pieces are assumed in play |
| `preconditions[]` | ○ | runner | `{check, card[, host]}`; `on_battlefield` / `attached` / `not_summoning_sick` |
| `on_interruption` | ✓ | runner | exit policy, typically `fresh_evaluation` |
| `runner` | ○ | humans | prose naming the runner + the line (documentation, not parsed) |

### Polymorphic body (keyed by `program_class`)

Each class reads **one** body block. Full field semantics live in
[`runner-cat.md`](../runner-cat.md); here is the dispatch map and the body key each
runner consumes.

| `program_class` | Runner (`ComboAwareLobbyPlayer`) | Body key | Body summary |
|---|---|---|---|
| `selvala_mana_loop` | `SelvalaManaLoopRunner` (`:1007`) | `loop` + `sink` | variable-yield tap/untap loop; `yield_model` ∈ POWER_CONSTANT, POWER_RAMPING, ENCHANTMENT_COUNT, CREATURE_COUNT, CONSTANT, ELF_COUNT; `sink` = deck-aware outlet ladder |
| `mana_loop` | `ManaLoopRunner` (`:1017`) | `loop` + `sink` | fixed-yield mana loop |
| `dreadnought_window` | `DreadnoughtWindowRunner` (`:968`) | `window` | respond-on-stack value burst in a body's ETB-trigger window; `exploit.kind` ∈ sac_draw, power_mana, power_draw, power_loop |
| `seedborn_engine` | `SeedbornEngineRunner` (`:978`) | `window`/engine block | untap-driven accumulation; modes omnath_accumulate, activated_sink |
| `bounce_recur` | `BounceRecurRunner` (`:958`) | recursion block | mana-funded ETB-recursion; measures board_counters, hand_size, opp_creatures |
| `cast_recur` | `CastRecurRunner` (`:998`) | recursion block | recast-from-graveyard/hand loop |
| `cast_bounce` | `CastBounceRunner` (`:988`) | bounce block | cast + self-bounce loop |
| `ping_loop` *(default)* | `ProgramRunner` (`:1031`) | loop/ping block | generic pinger; the fallback when `program_class` is absent (defaults to `ping_loop`) |
| `unreadable` | abort | — | parse failure → aborts, never misroutes |
| *(any other)* | abort | — | `program_class_unsupported: <class>` — flagged, never misrouted (`:934-948`) |

> `pairing` and `engine` are **not** combo-program classes — they are separate
> artifacts ([pairing-program](pairing-program.md), [engine-program](engine-program.md))
> with their own schema tags and dispatch paths.

## Canonical example

`decks/selvala-heart-of-the-wilds/dossier/combo-program-1355-2816.json` — a
`selvala_mana_loop` (Sanctum Weaver + Umbral Mantle). Chosen because it exercises
the full envelope *and* is the deliberate **threshold-regression** gate (it proves
the runner refuses a break-even loop):

```json
{
  "schema": "arena.combo-program/1",
  "program_class": "selvala_mana_loop",
  "combo_id": "1355-2816",
  "name": "Sanctum Weaver + Umbral Mantle",
  "compiled_from": {
    "script_cross_check": "Sanctum Weaver — A:AB$ Mana | Cost$ T | Produced$ Any | Amount$ X, SVar:X:Count$Valid Enchantment.YouCtrl ... Umbral Mantle grants '{3},{Q}: +2/+2'. Per cycle: {T}(free) + {3}(untap) = 3 spent, E gained.",
    "yield_model_rationale": "ENCHANTMENT_COUNT — X = enchantments you control, constant across the loop. Net = E - 3.",
    "regression_note": "THRESHOLD REGRESSION ... at E=3 the entry test reports zero_yield and aborts, rather than spinning a non-diverging loop."
  },
  "pieces": [
    { "card": "Sanctum Weaver", "role": "producer", "requires": "BATTLEFIELD" },
    { "card": "Umbral Mantle", "role": "untapper", "requires": "BATTLEFIELD (attached to Sanctum Weaver)" }
  ],
  "setup": [],
  "preconditions": [
    { "check": "on_battlefield", "card": "Sanctum Weaver" },
    { "check": "attached", "card": "Umbral Mantle", "host": "Sanctum Weaver" },
    { "check": "not_summoning_sick", "card": "Sanctum Weaver" }
  ],
  "loop": {
    "producer": { "card": "Sanctum Weaver", "activate_cost": "{T}" },
    "yield_model": "ENCHANTMENT_COUNT",
    "cycle_cost": 3,
    "min_net": 1,
    "untap_sequence": [ { "card": "Sanctum Weaver", "cost": "{3}", "why": "Umbral's {3},{Q} untaps Weaver" } ]
  },
  "sink": {
    "kind": "outlet_selection",
    "library_reserve": 35,
    "primary_outlet": "Genesis Wave",
    "fallback_outlets": [ "Finale of Devastation", "Craterhoof Behemoth" ]
  },
  "on_interruption": "fresh_evaluation",
  "runner": "SelvalaManaLoopRunner (forked): ENCHANTMENT_COUNT yield; zero-yield reject at E=3 is the point of this gate."
}
```

A `dreadnought_window` example (different body block, same envelope) lives at
`decks/selvala-heart-of-the-wilds/dossier/combo-program-syn-phyrexian-dreadnought-greater-good.json`:
its body is `window: { body, exploit: { card, kind, activate, cost, sacrifice, measure, expect_min } }`.

## Consumer & invariants

**Discovery.** `EngineFacade.comboAwareLobbyPlayer` (`EngineFacade.java:276-287`)
lists the dossier, filters `combo-program-*.json`, and keys each by
`filename.substring(14, len-5)` — i.e. everything between the `combo-program-`
prefix (14 chars) and the `.json` suffix. That key → absolute path map is handed to
`ComboPilot.setProgramPaths`.

**Dispatch.** `ComboPilot` treats a detected combo as program-driven when
`programPaths.containsKey(status.id())` (`ComboPilot.java:1025,1059`) and its
pieces are *truly assembled* (readiness + the piece-attachment gate that reads
`pieces[].requires`, `:252-261`). It emits a `ProgramOrder(comboId, path)`
(`:1072-1077`). `ComboAwareLobbyPlayer.programClassOf` reads `program_class`
(default `ping_loop`, `unreadable` on parse failure) and the runner switch
(`:933-1031`) constructs the matching runner; an unknown class aborts as
`program_class_unsupported` (never misrouted to `ProgramRunner`).

**Invariants that MUST hold:**

1. **Three-way id match:** the filename id (`combo-program-<id>.json`) **==**
   the JSON `combo_id` **==** a combo id registered in `combos.json` (Spellbook,
   numeric) or `discovered-combos.json` (`syn-`/`ben-`). A mismatch means the
   program is discovered by the facade but never dispatched (no detected combo
   with that id) — a silent no-op.
2. **`program_class` is whitelisted** — one of the 8 supported classes or the
   program aborts loudly. Absent `program_class` defaults to `ping_loop`.
3. **`pieces[].requires`** must name the real zone each piece needs
   (`HAND`/`BATTLEFIELD`); the attachment gate refuses to dispatch with a piece
   still in hand (smoke-batch fix #73).
4. **The body block must match the class** (a `selvala_mana_loop` needs `loop`;
   a `dreadnought_window` needs `window`) — the runner reads only its own block.

## Validation

- **Regression:** `mvn -o -pl forge-arena -am test` (270/270); dispatch + per-class
  proofs (e.g. `DreadnoughtWindowTest`, `SelvalaGoldfishRun`).
- **Goldfish:** `ProgramGate` derives a fixture (honoring `pieces[].requires`
  zoning and funding window/loop costs) and asserts the program's own exit event
  fires.
- **A/B:** seed-paired batch by deck name.
- **Schema (§8.2, pending):** a JSON Schema per `program_class` reverse-engineered
  from the runner field-reads; author/register-time check so a malformed program is
  caught before a batch (today it silently dispatches `unreadable` and aborts).

## Related

- Runners: [`runner-cat.md`](../runner-cat.md) (per-class execution semantics)
- Sibling artifacts: [engine-program](engine-program.md), [pairing-program](pairing-program.md)
- Upstream: `combos.json`, `discovered-combos.json` (the ids this must match)
- Nomenclature: working-plan-Aug-3 §9
