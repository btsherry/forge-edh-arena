# dossier

**Schema tag:** `arena.dossier/1`
**Filename:** `dossier.json` (in `<deck>/dossier/`)
**Generator:** deterministic prep (`PrepMain`)
**Consumer:** prep integrity (`DossierCheck`, `SpellbookClient`, `DeckLint`, `ComboPrep`, `GoldfishCompile`, `Ingest`)
**Status:** live

## What it is

The dossier's **manifest and integrity index**: a `sha256` for every prep-produced
artifact, the schema/version pins the dossier was built against (win-routes,
banlist, Spellbook snapshot), and a rolled-up `status` per prep gate. It is how prep
detects a stale or tampered artifact (hash mismatch) and how a reader learns the
provenance of everything else in the folder. It indexes the *whole* dossier —
including artifacts that don't have their own atlas page.

## Who generates it, and when

**Deterministic prep**: `PrepMain` writes it last, after every other artifact, so
each hash is final. No model. Reproducible from the artifacts it indexes.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.dossier/1"` |
| `deck_id`, `deck_hash`, `created` | ✓ | identity + timestamp |
| `versions` | ✓ | `{schemas, win_routes, banlist, spellbook_snapshot, route_library}` — the pins |
| `artifacts` | ✓ | `{logical_name: {path, sha256}}` — the integrity index (deck, deck_meta, deck_cards, lint_report, implementability_report, unimplemented_cards, spellbook_raw(+meta), combos, advisory_combos, route_coverage, tutor_priorities, program_backlog, …) |
| `status` | ✓ | per-gate rollup: `{lint, implementability, route_coverage, sim_verified, goldfish, programs}` |
| `warnings[]` | ✓ | prep warnings (empty = clean) |

## Canonical example

`decks/purphoros-god-of-the-forge/dossier/dossier.json`:

```json
{
  "schema": "arena.dossier/1",
  "deck_id": "purphoros-god-of-the-forge",
  "deck_hash": "f0d3c7d5...",
  "created": "2026-07-20T01:08:51Z",
  "versions": { "schemas": "1", "win_routes": "win-routes/6", "banlist": "2026-07-15-approx", "spellbook_snapshot": "2026-07-18" },
  "artifacts": {
    "deck_cards": { "path": "deck-cards.json", "sha256": "6d84ea29..." },
    "combos":     { "path": "combos.json",     "sha256": "0eec7695..." },
    "tutor_priorities": { "path": "tutor-priorities.json", "sha256": "b0aa160a..." }
  },
  "status": { "lint": "pass", "implementability": "pass", "route_coverage": "clean", "goldfish": "not_run", "programs": "0 executable, 0 flagged, 6 no_program" },
  "warnings": []
}
```

## Consumer & invariants

Read by prep integrity checks (`DossierCheck` and the prep classes that verify an
input hasn't drifted). Invariants: every `artifacts[].sha256` matches the file on
disk (a mismatch means a hand-edit or stale build — fail loudly); `deck_hash`
matches the `.dck`; `versions` pins are consistent across the dossier (a program
built against an old win-routes version is suspect). Note the index lists artifacts
without atlas pages yet (`lint_report`, `implementability_report`,
`spellbook_raw`, `deck_meta`, `unimplemented_cards`).

## Related

- Writer: `PrepMain`; checker: `DossierCheck`
- Indexes every dossier artifact — the closest thing to a machine-readable atlas
