# capability-inventory  ⚠️ DEPRECATED (orphaned)

**Schema tag:** `arena.capability-inventory/2`
**Filename:** `capability-inventory.json` (in `<deck>/dossier/`)
**Generator:** ~~T0 mechanical extraction + T3 model per-card analysis (ingest-deck per-card brief)~~ — **producer removed** (the `ingest-deck` skill + its per-card brief were deleted 2026-08-03)
**Consumer:** **NONE** — no `.java` / `.py` / `.sh` reads it (grep, whole repo)
**Status:** ⚠️ **DEPRECATED / orphaned** — no producer and no consumer; §8.7 resolved by deletion

## What it is

A **per-card capability vocabulary**: for each of the 99, a T0 tag set
(deterministic script parse — `has_activated_ability`, `mana_ability`, …), a T3 tag
set + prose analysis (a model reading the card: `role`, `rationale`,
`activations`, `interactions`, `uncertain`/`reason`). It was the Phase-9/10 attempt
to build a searchable capability index of the deck. The whole-deck combo discovery
(the exemplary process) has since superseded it as the way synergies get found.

## Why it is flagged

Ben suspected this is a throwback that is no longer consumed. **Confirmed:** a
repo-wide grep for `capability-inventory` / `capabilityInventory` finds **only
documentation mentions** (PR-LOG, IMPLEMENTATION-PLAN, working-plan, research) —
**no code** reads the file at prep time or runtime. The T3 layer (a Claude subagent
per card) is expensive and, on this evidence, produces nothing anything downstream
uses.

**§8.7 is now resolved — by deletion.** On 2026-08-03 the `ingest-deck` skill and
its per-card brief (`subagent-brief.md`) were removed, so the T3 per-card model
analysis no longer runs and this file has **no producer**. The T0 *card facts* the
pipeline actually uses live in [deck-cards](deck-cards.md) (which IS consumed) —
this file's own `t0` tag list was a separate, unconsumed vocabulary. Any
`capability-inventory.json` still sitting in a dossier is a stale output of a
retired step, not load-bearing.

## Who generates it, and when

Historically, the `ingest-deck` skill's **per-card brief** (`subagent-brief.md`,
**now removed**): `provenance.t0 = "forge card script"` (deterministic),
`provenance.t3 = "claude subagent, script-evidence enforced"` (a model per card).
Schema is at **v2**. Nothing generates this file anymore.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.capability-inventory/2"` |
| `deck_id` | ✓ | dossier id |
| `provenance` | ✓ | `{t0: "forge card script", t3: "claude subagent, script-evidence enforced"}` |
| `cards[]` | ✓ | per-card entry (below) |
| `cards[].card` | ✓ | name (join key) |
| `cards[].t0` | ✓ | deterministic capability tags (script parse) |
| `cards[].t3` | ✓ | model capability tags |
| `cards[].role`, `rationale` | ○ | model classification + reasoning |
| `cards[].activations[]` | ○ | `{cost, effect, repeatable}` |
| `cards[].interactions[]` | ○ | related card names the model flagged |
| `cards[].uncertain`, `reason` | ○ | model's self-flagged low confidence |

## Canonical example

`decks/urza-lord-high-artificer/dossier/capability-inventory.json` (91 cards):

```json
{
  "schema": "arena.capability-inventory/2",
  "deck_id": "urza-lord-high-artificer",
  "provenance": { "t0": "forge card script", "t3": "claude subagent, script-evidence enforced" },
  "cards": [
    {
      "card": "Academy Ruins",
      "t0": ["has_activated_ability", "mana_ability"],
      "t3": ["mana_ability", "has_activated_ability"],
      "role": "land_utility",
      "rationale": "Taps for {C} and rebuys a broken combo artifact from the graveyard onto the library top.",
      "activations": [ { "cost": "T", "effect": "Add {C}", "repeatable": true }, { "cost": "1 U T", "effect": "Put target artifact card from your graveyard on top of your library", "repeatable": true } ],
      "interactions": ["Aetherflux Reservoir", "Isochron Scepter", "Sensei's Divining Top", "Emry, Lurker of the Loch"]
    }
  ]
}
```

## Consumer & invariants

**No consumer.** Nothing in `src/` (or scripts) loads this file — verified by
repo-wide grep (only doc references). There are therefore no runtime invariants to
uphold. With both producer and consumer gone, this page is the **record of a
deprecated artifact** — kept so a future reader knows the file in older dossiers is
inert, not load-bearing.

## Related

- The consumed T0 card facts (keep): [deck-cards](deck-cards.md)
- The superseding process: [discovered-synergies-wholedeck](discovered-synergies-wholedeck.md)
- Producer brief (REMOVED 2026-08-03): was `.claude/skills/ingest-deck/references/subagent-brief.md`
- Verdict: working-plan-Aug-3 §8.7 (task #105) — resolved by deletion
