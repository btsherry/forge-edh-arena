# pairing-program

**Schema tag:** `arena.pairing-program/1`
**Filename:** `pairing-program-<id>.json` (in `<deck>/dossier/`)
**Generator:** hand-authored (main agent, Compile step)
**Consumer:** `EngineFacade` scan → `ComboPilot.setPairingPrograms` → `PairingRunner`
**Status:** live

## What it is

A hand-authored plan for a **two-card board-control play**: a mass removal spell
("wipe") cast into your own reactive **shield**, so the table's board dies and
yours survives. It is a *respond-on-stack* sequence — cast the wipe, then cast the
shield in response while the wipe is still on the stack — fired once per pair per
game when opponents present enough of a threat. The archetypal case is a one-sided
wrath: Doomskar (destroy all creatures) under Teferi's Protection (phase out all
your permanents until your next turn). The mechanism validity of each pair was
adjudicated by a two-auditor card-text audit (`docs/PAIRING-AUDIT-GIADA.md`).

## Who generates it, and when

**Hand-authored by the main agent** in the **Compile** step. It is compiled from a
`paired-plays.json` entry (the deck's generated wipe+shield candidates) into an
explicit sequence, with both scripts in context. `compiled_from` records the
`script_hashes`, the `oracle_cross_check`, the `mechanism_validity` verdict, and
the `audit` doc pointer — the phasing-vs-destroy and coverage-vs-scope reasoning
that makes the pair one-sided.

## Schema

| Field | Req | Read by | Meaning |
|---|---|---|---|
| `schema` | ✓ | (validator) | literal `"arena.pairing-program/1"` |
| `pairing_id` | ✓ | keying | **must equal the filename id** (`pp-...`) |
| `name` | ✓ | logs | human label |
| `compiled_from` | ✓ | provenance | `paired_plays_entry`, `script_hashes`, `oracle_cross_check`, `mechanism_validity`, `audit` |
| `wipe` | ✓ | `PairingRunner` | `{card, mechanism, scope, timing, cost}` — the removal half |
| `protection` | ✓ | `PairingRunner` | `{card, mechanism, coverage, duration, timing, cost}` — the shield half |
| `sequencing` | ✓ | `PairingRunner` | `{mode:"respond_on_stack", steps[]}` — the ordered cast/response line |
| `fire_policy` | ✓ | `PairingRunner` | when to fire (`{type, min_combined_opponent_creature_power, note}`) |
| `verify` | ○ | measurement | `{measure_at, own_preserved, opponents_reduced}` invariants |
| `on_interruption` | ✓ | runner | `fresh_evaluation` |
| `self_consumption` | ○ | runner/humans | both cards one-shot; once per game per pair |

### `wipe` / `protection` vocabularies

- `wipe.mechanism`: `destroy` (extend as new wipes are compiled); `scope`:
  `CREATURES` / (broader scopes as added); `timing`: `sorcery` / `instant`.
- `protection.mechanism`: `phasing` (extend); `coverage`: `all_own_permanents`
  (or narrower); `duration`: `until_your_next_turn`. Coverage vs the wipe's scope
  is what makes the play one-sided — the audit checks exactly this.

## Canonical example

`decks/giada-font-of-hope/dossier/pairing-program-pp-doomskar-teferi-s-protection.json`:

```json
{
  "schema": "arena.pairing-program/1",
  "pairing_id": "pp-doomskar-teferi-s-protection",
  "name": "Doomskar + Teferi's Protection",
  "compiled_from": {
    "paired_plays_entry": "pp-doomskar-teferi-s-protection",
    "script_hashes": { "doomskar": "838042d370feb9a0", "teferi_s_protection": "2aae3a433d13bc43" },
    "mechanism_validity": "VALID per the two-auditor audit (36/36 verdict convergence): phasing vs destroy, coverage all_own_permanents vs scope CREATURES.",
    "audit": "docs/PAIRING-AUDIT-GIADA.md"
  },
  "wipe": { "card": "Doomskar", "mechanism": "destroy", "scope": "CREATURES", "timing": "sorcery", "cost": "{3}{W}{W}" },
  "protection": { "card": "Teferi's Protection", "mechanism": "phasing", "coverage": "all_own_permanents", "duration": "until_your_next_turn", "timing": "instant", "cost": "{2}{W}" },
  "sequencing": {
    "mode": "respond_on_stack",
    "steps": [
      "preflight BOTH casts JOINTLY resolvable; retryable, nothing spent",
      "cast wipe; verify THE WIPE ITSELF is on the stack next window",
      "cast protection (cheapest non-sacrifice mode) in response; shield must be SEEN on the stack",
      "yield until the stack empties; opponents snapshotted at resolution; own measure DEFERRED to our next turn (phasing)"
    ]
  },
  "fire_policy": { "type": "threat_gated", "min_combined_opponent_creature_power": 6 },
  "verify": {
    "measure_at": "next_untap",
    "own_preserved": "own scoped count >= count at wipe cast (measured post phase-in)",
    "opponents_reduced": "opponents' scoped count at resolution < count at wipe cast"
  },
  "on_interruption": "fresh_evaluation",
  "self_consumption": { "resource": "none", "note": "both cards one-shot; once per game per pair" }
}
```

## Consumer & invariants

**Discovery.** `EngineFacade.comboAwareLobbyPlayer` (`EngineFacade.java:290-301`)
filters `pairing-program-*.json` and keys each by `filename.substring(16, len-5)`
(strip the 16-char `pairing-program-` prefix and `.json`). The key → path map goes
to `ComboPilot.setPairingPrograms` (`ComboPilot.java:395`). Separately, the deck's
`paired-plays.json` is merged into the executor bindings (`EngineFacade.java:253`).

**Dispatch.** `ComboPilot` fires the pair once per pair per game (`:579`) via
`PairingRunner`, when `fire_policy` is satisfied (opponents' combined creature
power ≥ the threshold) and both cards are castable. There is no `program_class`
and no ComboTracker readiness — the gate is castability + the threat threshold.

**Invariants that MUST hold:**

1. `pairing_id` **==** the filename id, and it should match a `paired-plays.json`
   entry (`compiled_from.paired_plays_entry`).
2. The one-sidedness is real: `protection.coverage` must actually cover the
   `wipe.scope` on your side (the audit gate). A pair where the shield does not
   protect against your own wipe is a correctness bug, not a program.
3. `sequencing.mode` is `respond_on_stack` and the steps must verify the wipe is
   *seen on the stack* before the shield is cast — never fire blind.
4. Own-side measurement is **deferred** when the shield phases (measure at
   `next_untap`, after phase-in), never at resolution.

## Validation

- **Audit:** two-auditor card-text audit per pair (`docs/PAIRING-AUDIT-GIADA.md`);
  a pair ships only on verdict convergence.
- **Goldfish + A/B:** as the program family; `verify.own_preserved` /
  `opponents_reduced` are the correctness assertions.
- **Schema (§8.2, pending):** single JSON Schema (no polymorphic body); the
  validator should also cross-check `paired_plays_entry` resolves.
- **Gate 4 fixture derivation for pairing programs:** task #65.

## Related

- Runner: [`runner-cat.md`](../runner-cat.md) → `PairingRunner`
- Sibling artifacts: [combo-program](combo-program.md), [engine-program](engine-program.md)
- Upstream: `paired-plays.json`, `protection-priorities.json`; audit `docs/PAIRING-AUDIT-GIADA.md`
