# build-manifest

**Schema tag:** `arena.build-manifest/1`
**Filename:** `build-manifest.json` (in `<deck>/dossier/`)
**Generator:** hand-authored / derived during Compile (triage record)
**Consumer:** **none in code** — provenance / human triage record
**Status:** live (record-only)

## What it is

The **triage ledger** of a discovery run: every one of the ~200 discovery records
sorted into `programs` (compiled to a runner) vs `non_programs` (folded to weights /
protection / left as value). It records, per program record, the display name, the
runner class, whether it `needs_code` (a `shape_is_new` runner), the anchor +
partners, and the compile rank/confidence — the audit trail for *why the build has
the programs it has*. It is a record, not an input: **no code reads it**.

## Who generates it, and when

Produced during the **Compile** step as the main agent triages
[discovered-synergies-wholedeck](discovered-synergies-wholedeck.md) into buckets.
Deterministic given the triage decisions; it mirrors, in one place, the split that
`program-backlog` + the compiled program files encode.

## Schema

| Field | Req | Meaning |
|---|---|---|
| `schema` | ✓ | `"arena.build-manifest/1"` |
| `deck`, `total` | ✓ | deck id; total records triaged (e.g. 200) |
| `programs[]` | ✓ | `{idx, disp, runner, needs_code, class, anchor, partners[], compile_rank, confidence}` — records that became programs |
| `programs[].needs_code` | ✓ | `true` = a `shape_is_new` runner had to be built |
| `programs[].runner` | ✓ | the program_class/runner it compiled to |
| `non_programs[]` | ✓ | `{idx, disp, class, anchor, partners[]}` — records folded to weights or left as value |

## Canonical example

`decks/selvala-heart-of-the-wilds/dossier/build-manifest.json` (200 total → 98
programs + 102 non-programs):

```json
{
  "schema": "arena.build-manifest/1",
  "deck": "selvala-heart-of-the-wilds",
  "total": 200,
  "programs": [
    { "idx": 0, "disp": "selvala_loop_swing", "runner": "selvala_mana_loop", "needs_code": true, "class": "win_plan", "anchor": "Finale of Devastation", "partners": ["Selvala, Heart of the Wilds", "Umbral Mantle", "Craterhoof Behemoth"], "compile_rank": 0.85, "confidence": "high" }
  ],
  "non_programs": [
    { "idx": 1, "disp": "win_plan_general", "class": "win_plan", "anchor": "Finale of Devastation", "partners": ["Craterhoof Behemoth"] }
  ]
}
```

## Consumer & invariants

**No runtime or prep consumer** — it exists for humans and for reconstructing a
build's triage after the fact. Invariants (advisory, not enforced): `programs` +
`non_programs` counts sum to `total`; every `programs[].idx` corresponds to a real
compiled [combo-program](combo-program.md); `needs_code:true` entries correspond to
`shape_is_new` runners that were actually written and tested (§4). Because nothing
reads it, drift here is silent — treat it as documentation to keep honest, not a
source of truth (the programs on disk are the truth).

## Related

- Triage source: [discovered-synergies-wholedeck](discovered-synergies-wholedeck.md)
- Truth twins (machine-read): the [combo-program](combo-program.md) files + [program-backlog](program-backlog.md)
- Human narrative: `docs/archive/SELVALA-BUILD-MANIFEST.md`
