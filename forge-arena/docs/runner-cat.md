# Runner Catalog

**One entry per runner: the shape it executes, the exact program fields it reads,
its vocabularies, its abort/exit states, and a canonical example.** Where the
[artifact atlas](atlas/combo-program.md) documents the *file contract* of a
program, this catalog documents the *execution semantics* — what the interpreter
actually does with each body block. The atlas program pages forward-link here.

Every field/vocabulary/abort string below was read from the runner source in
`src/main/java/forge/arena/engine/`, not from memory.

## Dispatch

`ComboAwareLobbyPlayer.programClassOf` reads `program_class` (default `ping_loop`;
`unreadable` on parse failure) and constructs the matching runner. An out-of-set
class aborts as `program_class_unsupported` (never misrouted). Engine and pairing
programs take their own discovery paths (`engine_id` / `pairing_id`, no
`program_class`).

| `program_class` | Runner | Body block(s) | Shape |
|---|---|---|---|
| `selvala_mana_loop` | [SelvalaManaLoopRunner](#selvalamanalooprunner) | `loop` + `sink` | variable-yield tap/untap loop → deck-aware outlet |
| `mana_loop` | [ManaLoopRunner](#manalooprunner) | `loop` + `sink` | fixed-yield mana loop → storm/outlet sink |
| `dreadnought_window` | [DreadnoughtWindowRunner](#dreadnoughtwindowrunner) | `window` | respond-on-stack exploit in an ETB-trigger window |
| `seedborn_engine` | [SeedbornEngineRunner](#seedbornenginerunner) | `engine` | untap-driven accumulation engine |
| `bounce_recur` | [BounceRecurRunner](#bouncerecurrunner) | `loop` | mana-funded ETB-recursion |
| `cast_recur` | [CastRecurRunner](#castrecurrunner) | `loop` | recast-from-refund loop |
| `cast_bounce` | [CastBounceRunner](#castbouncerunner) | `loop` + `pieces` | cast + self-bounce loop |
| `pairing` *(via `pairing_id`)* | [PairingRunner](#pairingrunner) | `wipe`+`protection`+`sequencing` | wipe + self-shield, respond-on-stack |
| `engine` *(via `engine_id`)* | [EngineProgramRunner](#engineprogramrunner) | `cycle` | background per-turn value cycle |
| `ping_loop` *(default)* | [ProgramRunner](#programrunner) | `loop`/`verify` | generic pinger / fallback |

## Shared lifecycle

Runners share a state-machine shape: **SETUP** (cast/equip pieces if `setup` /
`preconditions` demand) → **entry gate** (prove the line is fundable and diverging;
abort loudly if not) → **execute** (loop/window/cycle, hard-bounded by an iteration
cap) → **measure/exit** (assert the value actually landed after the stack empties).
Every abort emits a `program_abort` (or `*_abort`) event with a specific `reason`
— the reasons are listed per runner and are the honest record of *why* a line
didn't convert. The entry gate is the load-bearing part: a finite/break-even line
is refused at entry (e.g. `low_power`, `zero_yield`) rather than spun to the cap.

---

## SelvalaManaLoopRunner
`program_class: selvala_mana_loop` · `src/main/java/forge/arena/engine/SelvalaManaLoopRunner.java`

**Shape.** A tap-for-mana / untap loop whose per-cycle yield is a *variable* read
off the board (Selvala reads greatest power; a Weaver reads enchantment count),
funneled into a deck-aware outlet once the pool diverges.

**Body blocks:** `loop`, `sink`, `preconditions`, `setup`.

| Path | Meaning |
|---|---|
| `loop.producer.{card,activate_cost}` | the tap-for-mana source + its cost |
| `loop.yield_model` | how per-cycle yield is computed (vocab below) |
| `loop.yield_constant` / `loop.ramp_per_cycle` | constants for CONSTANT / POWER_RAMPING |
| `loop.cycle_cost` / `loop.min_net` | mana spent per cycle / minimum net to accept the loop |
| `loop.untap_sequence[].{card,cost,target,host}` | the untap step(s) that re-ready the producer |
| `loop.mana_color` | the color the pool accrues |
| `sink.kind` | `outlet_selection` |
| `sink.library_reserve` | cards to keep in library (avoid decking on the flip) |
| `sink.outlets[].{card,kind,min_x}` | **deck-aware outlet ladder** (§96); undeclared → built-in ladder |
| `preconditions[].{check,card,host}` | `on_battlefield` / `attached` / `not_summoning_sick` |

**Vocabulary.**
- `yield_model`: `POWER_CONSTANT`, `POWER_RAMPING`, `ENCHANTMENT_COUNT`,
  `CREATURE_COUNT`, `CONSTANT`, `ELF_COUNT`. (`POWER`, `TAPPED` are internal.)
- outlet `kind`: `mass_flip`, `fetch_swing`, `fetch_fixed`, `x_body`, `overrun`.

**Aborts.** `bootstrap_unfunded` (can't fund the first activation),
`low_power` (yield read below the divergence threshold — the finite-line reject),
`producer_tap_unpayable`, `no_outlet_castable` (mana but no reachable win),
`program_abort`.

**Canonical example.** `combo-program-1355-2816.json` (Sanctum Weaver + Umbral
Mantle, `ENCHANTMENT_COUNT` — the deliberate zero-yield threshold gate);
`combo-program-syn-umbral-mantle-voyaging-satyr-lotus-field-overgrowth.json`.

---

## ManaLoopRunner
`program_class: mana_loop` · `ManaLoopRunner.java`

**Shape.** A *fixed*-yield mana loop (net per cycle is a constant, not a board
read), with a storm/outlet sink. Handles the Isochron-Scepter / Dramatic-Reversal
class and float-then-copy storm lines.

**Body blocks:** `loop`, `sink`, `body`, `pieces`, `preconditions`, `setup`,
`self_consumption`.

| Path | Meaning |
|---|---|
| `loop.{card,cost,activate}` | the loop engine + activation |
| `loop.shape` | `float_then_copy` for the storm variant |
| `loop.imprint` | the imprinted card (Scepter) |
| `loop.{per_activation_pool,expected_net_per_pair,expected_net_min_per_iteration,floor,n}` | yield accounting + iteration bounds |
| `sink.{card,cost}` | the payoff |
| `sink.storm_mode` | `stock` (default) or `program_casts` |
| `sink.{storm_reserve_per_sink,max_sinks,per_activation_pool}` | storm sizing |
| `preconditions[].check` | includes `imprinted` (Scepter must hold the imprint) |

**Vocabulary.** `storm_mode`: `stock`, `program_casts`. `loop.shape`:
`float_then_copy`. precondition `check`: `imprinted`.

**Aborts.** `program_abort` (with a specific reason, e.g. `not_imprinted`).

**Canonical example.** `combo-program-4821-5261.json` (Isochron Scepter +
Dramatic Reversal).

---

## DreadnoughtWindowRunner
`program_class: dreadnought_window` · `DreadnoughtWindowRunner.java`

**Shape.** Casts a body whose ETB trigger opens a stack window, then activates an
exploit *in response* (respond-on-stack) to convert the body's stats into value
before the trigger resolves. Built for Phyrexian Dreadnought's sac-trigger window.

**Body block:** `window`.

| Path | Meaning |
|---|---|
| `window.body` | the trigger body (e.g. Phyrexian Dreadnought) — reserved from stock casting |
| `window.exploit.{card,activate,cost}` | the exploit + how it's paid/activated |
| `window.exploit.kind` | which exploit shape (vocab below) |
| `window.exploit.sacrifice` | what the exploit sacrifices (steered onto the body) |
| `window.exploit.measure` | what value to measure |
| `window.exploit.expect_min` | the floor a real burst must clear |
| `window.exploit.{untap_cost,max_cycles}` | for the bounded `power_loop` variant |

**Vocabulary.** `kind`: `sac_draw` (default), `power_mana`, `power_draw`,
`power_loop`. `measure`: `hand_size` (default), `mana_pool`.

**Aborts.** `burst_below_floor` (delta under `expect_min`),
`power_loop_below_floor`, `program_abort`. `power_loop` is hard-bounded by
`max_cycles`.

**Canonical example.**
`combo-program-syn-phyrexian-dreadnought-return-of-the-wildspeaker.json`
(`power_draw`); `...-greater-good.json` (`sac_draw`).

---

## SeedbornEngineRunner
`program_class: seedborn_engine` · `SeedbornEngineRunner.java`

**Shape.** An untap-driven accumulation engine — Seedborn Muse re-readies lands
each opponent's untap, so mana banks (Omnath) or feeds an activated sink each turn.
Bounded per turn; not an infinite loop.

**Body block:** `engine`.

| Path | Meaning |
|---|---|
| `engine.mode` | `activated_sink` (default) or `omnath_accumulate` |
| `engine.measure` | value tracked (vocab below) |
| `engine.per_turn_cap` | the per-turn bound |
| `engine.{producer,untapper,retainer,sink}` | the roles |
| `engine.{card,activate_cost,cost}` | the sink activation |

**Vocabulary.** `mode`: `activated_sink`, `omnath_accumulate`. `measure`:
`hand_size` (default), `omnath_power`, `pool_green`.

**Aborts.** `engine_abort`.

**Canonical example.** `combo-program-syn-seedborn-omnath-gaeas-cradle.json`.

---

## BounceRecurRunner
`program_class: bounce_recur` · `BounceRecurRunner.java`

**Shape.** A mana-funded ETB-recursion loop — bounce a creature to hand and recast
it, banking its ETB each cycle (Eternal Witness / Kogla / Temur Sabertooth), until
a payoff or measure floor is met.

**Body block:** `loop`.

| Path | Meaning |
|---|---|
| `loop.recur_card` | the creature recurred each cycle |
| `loop.bounce_outlet` | the bounce source (e.g. Temur Sabertooth) |
| `loop.payoff` | the ETB payoff being banked |
| `loop.measure` | what the loop accumulates (vocab below) |
| `loop.{cost,card}` | per-cycle cost |

**Vocabulary.** `measure`: `board_counters`, `hand_size`, `opp_creatures`.

**Aborts.** `program_abort`.

**Canonical example.** `combo-program-ben-ewit-sabertooth-henge.json`
(Eternal Witness + Temur Sabertooth + The Great Henge).

---

## CastRecurRunner
`program_class: cast_recur` · `CastRecurRunner.java`

**Shape.** A recast-from-refund loop — a cheap creature that returns itself to
hand, cast repeatedly while a refund source (per-cast mana / counters) pays for
it, driving a per-cast payoff (Grinning Ignus + Birgi + Purphoros).

**Body block:** `loop`.

| Path | Meaning |
|---|---|
| `loop.recur_card` | the self-returning body |
| `loop.refund_source.{kind,card}` | what refunds the recast cost |

**Vocabulary.** `refund_source.kind`: `counter_cycle`. (Runner tags its outlet
`cast_recur`.)

**Aborts.** `program_abort`.

**Canonical example.** `combo-program-ben-ignus-birgi.json` (Grinning Ignus +
Birgi, God of Storytelling — payoff enforced via `outlet_on_board`).

---

## CastBounceRunner
`program_class: cast_bounce` · `CastBounceRunner.java`

**Shape.** A cast + self-bounce mana loop — a permanent bounces itself (Hullbreaker
Horror-style trigger) so a net-positive rock can be recast for storm/lifegain,
with template-piece resolution for the fodder slot.

**Body blocks:** `loop`, `pieces`, `outlet`, `setup`.

| Path | Meaning |
|---|---|
| `loop.card` / `loop.source` | the bounce engine |
| `loop.tap_produces` | mana the rock makes |
| `loop.recast_cost` | cost to recast the fodder |
| `loop.trigger_obligations` | the bounce trigger that must be honored (mode/target steered) |
| `loop.target_cumulative_lifegain` | the lifegain floor to close |
| `pieces[].{card,template,resolve_from,role}` | named OR template pieces (`template` resolved at runtime from `resolve_from`) |

**Vocabulary.** template pieces via `pieces[].template` + `resolve_from`. (Runner
tags its outlet `cast_bounce`.)

**Aborts.** `program_abort`.

**Canonical example.** `combo-program-542-2585.json` (Tidespout Tyrant + Grim
Monolith); `combo-program-513-5034--46.json` (Hullbreaker Horror + Sol Ring +
zero-cost-artifact template).

---

## PairingRunner
via `pairing_id` (schema `arena.pairing-program/1`) · `PairingRunner.java`

**Shape.** Casts a mass-removal wipe and, in response on the stack, its own
reactive shield, so the table's board dies and yours survives. Once per pair per
game. See [pairing-program](atlas/pairing-program.md) for the file contract.

**Body blocks:** `wipe`, `protection`, `sequencing`, `fire_policy`, `verify`.

| Path | Meaning |
|---|---|
| `wipe.{card,scope}` | the removal + what it hits |
| `protection.card` | the self-shield |
| `verify.measure_at` | when own-survival is measured (deferred past phasing) |

**Vocabulary.** `wipe.scope`: `CREATURES`, `LANDS`, `NONLAND_PERMANENTS`,
`ALL_PERMANENTS`.

**Aborts.** `pairing_abort` (e.g. the shield never seen on the stack).

**Canonical example.** `pairing-program-pp-ravages-of-war-teferi-s-protection.json`.

---

## EngineProgramRunner
via `engine_id` (schema `arena.engine-program/1`) · `EngineProgramRunner.java`

**Shape.** A background card-advantage cycle with **no exit state** — two pieces on
the battlefield, one gated activation per turn, forever (Land Tax + Scroll Rack).
See [engine-program](atlas/engine-program.md) for the file contract.

**Body blocks:** `pieces`, `cycle`.

| Path | Meaning |
|---|---|
| `pieces[].{card,cost}` | the engine pieces + cast cost |
| `cycle.action.{activate,cost}` | the per-turn activation |

**Aborts.** `engine_abort`; `activation_never_resolved` (the cycle was attempted
but its activation never resolved — measured after the stack empties). Never aborts
a turn on a missing piece — it idles and retries.

**Canonical example.** `engine-program-ep-land-tax-scroll-rack.json`.

---

## ProgramRunner
`program_class: ping_loop` (default) · `ProgramRunner.java`

**Shape.** The generic pinger / fallback — a repeatable ability (Walking Ballista,
Triskelion) fired to a floor, with keyword/resource verification. This is the
runner a program with no `program_class` defaults to, so it also handles the
plain "assemble + repeatedly activate" combos.

**Body blocks:** `loop`, `verify`, `pieces`, `setup`, `preconditions`,
`exit_states`, `engine_state`, `self_consumption`.

| Path | Meaning |
|---|---|
| `pieces` / `setup` | the pieces to assemble/cast |
| `loop` + ping fields `{card,cost,targets,must_target,x_min,frequency,source,role}` | the repeatable ability |
| `verify.{keyword,resource,floor,n}` | the win check (e.g. LIFELINK drain, life to a floor) |
| `loop.trigger_obligations` | triggers to honor |
| `exit_states` / `engine_state` | declared exit conditions |

**Vocabulary.** `verify.keyword`: `LIFELINK`. `verify.resource`: `library`, `life`.

**Aborts.** `program_abort`.

**Canonical example.** `combo-program-2919-3693.json` (Archangel of Thune +
Walking Ballista — a no-`program_class` default → ping_loop).

---

## See also

- [Artifact atlas — combo-program](atlas/combo-program.md) (the file contract + dispatch invariants)
- [engine-program](atlas/engine-program.md), [pairing-program](atlas/pairing-program.md)
- Schemas: `schemas/arena.combo-program.1.schema.json` (+ engine/pairing/fixture)
- Nomenclature: `docs/working-plan-Aug-3.md` §9
