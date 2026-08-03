# advisory-combos

**Schema tag:** `arena.advisory-combos/1`
**Filename:** `advisory-combos.json` (in `<deck>/dossier/`)
**Generator:** T0/T1 deterministic prep (`ComboPrep`)
**Consumer:** **none at runtime** — deckbuilding advice only (Gate 3 semantic rule)
**Status:** live (advisory)

## What it is

Spellbook combos that are **almost** in the deck — at least one piece is *not* in
the 99. These are **deckbuilding suggestions** ("add one card and this combo comes
online"), never runtime tutor or tracking data. The distinction is a hard Gate 3
semantic rule: the pilot must never chase a combo it cannot actually assemble from
the deck, so these are quarantined out of `combos.json`.

## Who generates it, and when

**Deterministic prep** (`ComboPrep`), the complement of the `combos.json` filter:
Spellbook variants where the deck holds some-but-not-all pieces land here. No model.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.advisory-combos/1"` |
| `note` | ✓ | the guardrail: "almost-included … never runtime tutor/tracking data" |
| `combos[]` | ✓ | `{id, cards[str], produces[str]}` — note `cards` is a plain name list here, not `{name,zone_req}` objects |

## Canonical example

`decks/giada-font-of-hope/dossier/advisory-combos.json` (22 combos):

```json
{
  "note": "almost-included: at least one piece is NOT in the 99 — deckbuilding advice only, never runtime tutor/tracking data (plan §3 Gate 3 semantic rule)",
  "combos": [
    { "id": "553-1271", "cards": ["Approach of the Second Sun", "Scroll Rack"], "produces": ["Win the game"] },
    { "id": "104-3693", "cards": ["Cleric Class", "Walking Ballista"], "produces": ["Infinite damage", "Infinite lifegain", "Infinite lifegain triggers"] }
  ],
  "schema": "arena.advisory-combos/1"
}
```

## Consumer & invariants

**No runtime consumer** — the file exists for a human deckbuilder and for
completeness accounting. The load-bearing invariant is the *negative* one:
nothing in `combos.json` (runtime) may also appear here, and the pilot/tracker must
never read this file. A combo listed here whose pieces are in fact all in the deck
is a prep bug (it should have been promoted to `combos.json`).

## Related

- Runtime sibling: [combos](combos.md)
- The Gate 3 rule: working-plan-Aug-3 §3; `docs/INGESTION-SPEC.md`
