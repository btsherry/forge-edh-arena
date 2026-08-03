# Artifact Atlas

**One reference page per artifact the ingestion pipeline reads or writes.** The
atlas is the map between the JSON files that live in a deck's `dossier/` and the
Java that consumes them. It exists so that future-me (and the `arena-dev` coding
skill, §8.4) can answer, for any artifact, five questions without re-reading the
engine:

1. **What is it** — its role in the pipeline, in one paragraph.
2. **Who generates it** — the [generator class](#generator-taxonomy) (deterministic
   prep / research subagent / hand-authored / derived-fold), and *when*.
3. **Schema** — the `schema:` tag and the field-by-field contract actually read by
   the consumer. Deep per-runner semantics live in
   [`runner-cat.md`](../runner-cat.md); the atlas states the file contract.
4. **Canonical example** — a real file on disk (path + excerpt), never invented.
5. **Consumer** — the exact class + code path that reads it, plus the invariants
   that must hold (naming keys, id matching, cross-file references).

This is descriptive documentation of the artifacts **as they exist today** — it is
the input to the schema/validator work (§8.2), which turns these contracts into
machine-checkable JSON Schemas. Where a working file disagrees with a schema, the
schema is wrong (widen it); see the [validation](#validation-status) note.

> **Source of truth.** Every field description here was read from the runners and
> from real dossier files, not from memory. When a runner changes what it reads,
> the matching atlas page and `runner-cat.md` change in the same commit.

---

## The entry template

Every atlas page follows this shape. Copy it verbatim when adding an artifact.

```markdown
# <artifact-family>

**Schema tag:** `arena.<name>/<version>`
**Filename:** `<glob>` (in `<deck>/dossier/`)
**Generator:** <one of the generator taxonomy classes>
**Consumer:** <class + method>  →  <runner/effect>
**Status:** <live | suspect | deprecated>

## What it is
<One paragraph: role in the pipeline, what it makes the pilot do.>

## Who generates it, and when
<Generator class, the pipeline step, the exact producer (PrepMain / IngestMain /
subagent discovery / hand-authored compile / deterministic fold).>

## Schema
<Field-by-field contract. Envelope fields first; then any polymorphic body,
keyed by its discriminator. Mark: required vs optional, read-by-whom. Link
runner-cat.md for execution semantics rather than duplicating them.>

## Canonical example
<Real path on disk + an excerpt. Never fabricate.>

## Consumer & invariants
<The scan/keying/dispatch path (cite file:line). The invariants that MUST hold
for the artifact to be found and run: filename keys, id matching, cross-refs.>

## Validation
<How it is checked today (schema §8.2 status, ProgramGate goldfish, A/B) and
what a validator should enforce.>

## Related
<Links: runner-cat entry, sibling artifacts, the schema file once it exists.>
```

---

## Generator taxonomy

Every artifact is produced by exactly one of these. The taxonomy is the vocabulary
the atlas, the coding skill, and the validator share.

| Class | Producer | Model? | Determinism | Examples |
|---|---|---|---|---|
| **T0/T1/T2 deterministic prep** | `PrepMain` / `IngestMain` (Gates 0–4, Spellbook fetch, tutor fold) | no | reproducible from inputs | `deck-cards.json`, `combos.json`, `advisory-combos.json`, `route-coverage.json`, `fixtures/*`, `dossier.json`, `build-manifest.json` |
| **Research subagent (T3 discovery)** | Fable + Gemini discovery subagents, full-context, adversarially verified | yes (discovery only) | curated, not reproducible | `discovered-synergies-wholedeck.json`, `discovered-combos.json` |
| **Hand-authored (main agent, Compile)** | the main agent, scripts in context, honest triage (§3) | no (author judgement) | reviewed, not auto-emitted | **`combo-program-*.json`**, **`engine-program-*.json`**, **`pairing-program-*.json`** |
| **Derived fold (main agent, deterministic)** | compiled from discovery records into weights/pairs | no | reproducible from discovery | `tutor-priorities.json`, `protection-priorities.json`, `paired-plays.json` |
| **Suspect / under review** | possibly a Phase-9/10 throwback | — | pending §8.7 verdict | `capability-inventory.json` |

**Blind subagent authoring of the hand-authored class is banned** (§3 of the
working plan; memory `feedback_subagent_discover_compile`). Subagents *discover*;
the main agent *compiles* the program family with the card scripts fully in
context.

---

## The program family (authored first)

The three **hand-authored program artifacts** are the execution-bearing output of
the Compile step — the files we author and validate most, so they get atlas pages
first (§8.1). They share a shape: a `schema` tag, a stable id that is also the
filename key, a `compiled_from` provenance block quoting real script costs,
`pieces`, and a class-specific execution body. `EngineFacade` discovers all three
by filename prefix from the dossier and hands them to `ComboAwareLobbyPlayer`,
which dispatches each to its runner.

| Artifact | Schema | Runner | Shape it executes |
|---|---|---|---|
| [combo-program](combo-program.md) | `arena.combo-program/1` | polymorphic on `program_class` (see page) | a single combo's line — loop / window / recursion, exit-stated |
| [engine-program](engine-program.md) | `arena.engine-program/1` | `EngineProgramRunner` | a background per-turn card-advantage cycle, no exit state |
| [pairing-program](pairing-program.md) | `arena.pairing-program/1` | `PairingRunner` | a wipe + self-shield, respond-on-stack, once per game |

---

## Index (all artifacts)

Grouped by generator class (§ [generator taxonomy](#generator-taxonomy)). The
**Consumer** column says whether the runtime pilot reads it (R), only prep reads it
(P), or nothing reads it (—).

**Hand-authored — the program family** (Compile step):

| Page | Schema | Consumer | Role |
|---|---|---|---|
| [combo-program](combo-program.md) | `arena.combo-program/1` | R | per-combo execution plan (polymorphic on `program_class`) |
| [engine-program](engine-program.md) | `arena.engine-program/1` | R | background no-exit-state value cycle |
| [pairing-program](pairing-program.md) | `arena.pairing-program/1` | R | respond-on-stack wipe + shield |

**Discovery / combo inputs:**

| Page | Schema | Generator | Consumer |
|---|---|---|---|
| [deck-cards](deck-cards.md) | `arena.deck-cards/1` | prep (T0) | P |
| [combos](combos.md) | `arena.combos/1` | prep (Spellbook) | R + P |
| [advisory-combos](advisory-combos.md) | `arena.advisory-combos/1` | prep | — (advice) |
| [discovered-combos](discovered-combos.md) | `arena.discovered-combos/1` | hand/subagent | R + P |
| [discovered-synergies-wholedeck](discovered-synergies-wholedeck.md) | `arena.discovered-synergies-wholedeck/1` | subagent (Fable+Gemini) | P + compile |

**Derived weights / pairs:**

| Page | Schema | Generator | Consumer |
|---|---|---|---|
| [tutor-priorities](tutor-priorities.md) | `arena.tutor-priorities/1` | derived fold | R |
| [protection-priorities](protection-priorities.md) | `arena.protection-priorities/1` | prep | R |
| [paired-plays](paired-plays.md) | `arena.paired-plays/1` | prep | R |
| [route-coverage](route-coverage.md) | `arena.route-coverage/2` | prep (win-routes) | R + P |

**Prep / goldfish / index:**

| Page | Schema | Generator | Consumer |
|---|---|---|---|
| [fixtures](fixtures.md) | `arena.program-fixture/1` | prep (ProgramGate) | P (goldfish) |
| [dossier](dossier.md) | `arena.dossier/1` | prep (PrepMain) | P (integrity) |
| [program-backlog](program-backlog.md) | `arena.program-backlog/1` | prep (ProgramGate) | P + compile |
| [build-manifest](build-manifest.md) | `arena.build-manifest/1` | compile (triage) | — (record) |
| [capability-inventory](capability-inventory.md) ⚠️ | `arena.capability-inventory/2` | T3 per-card brief | — (⚠️ §8.7) |

### Also in the dossier — not yet paged

These prep intermediates and human reports exist in a dossier but don't yet have
atlas pages (listed so nothing is silently absent; add pages if a consumer or
question arises):

- `deck-meta.yaml` — deck identity (commander, id) — T0 prep
- `card-scripts-index.json` — per-card Forge-script path + hash index — T0 prep
- `spellbook-raw.json` / `spellbook-raw.meta.json` — raw Spellbook API dump (input to `combos.json`)
- `lint-report.json` — Gate 1 legality/lint result — prep
- `implementability-report.json` — Gate 2/3 implementability — prep
- `unimplemented-cards.txt` — cards with no Forge script — prep
- `discovered-synergies-fable.json` / `discovered-synergies.json` — earlier/partial discovery variants (the whole-deck file supersedes)
- `discovered-synergies-wholedeck-REPORT.md` — human-readable discovery report
- `.dck` — the Forge deck file (top-level copy is what the batch loads, §11)

---

## Validation status

**§8.2 is done for the artifacts that need it.** Machine-checkable JSON Schemas
now live in `schemas/` (draft-2020-12, `arena.<name>.<ver>.schema.json`):

- **Authored via §8.2:** the program family (`combo-program`, `engine-program`,
  `pairing-program`, `program-fixture`) plus `protection-priorities`,
  `paired-plays`, `discovered-combos`, `advisory-combos`, `program-backlog`,
  `build-manifest`, `discovered-synergies-wholedeck`.
- **Pre-existing:** `combos`, `deck-cards`, `dossier`, `route-coverage` (1 & 2),
  `tutor-priorities` (+ non-dossier `events`, `game-record`, `run-manifest`,
  `route-library`, `executor-bindings`, `autopsy-proposals`).
- **Intentionally unschema'd:** `capability-inventory` — the §8.7 cut candidate
  (no consumer); no sense schema-ing a deprecated artifact.

Validated two ways: `SchemaValidationTest` (curated valid/invalid fixtures — the
invalids are the real failure modes, e.g. a typo'd `program_class` that would be
the runtime `program_class_unsupported` abort) and `ProgramSchemaValidationTest`
(sweeps every on-disk dossier program + artifact file, ~180 real files across 6
decks; skips cleanly on a clean checkout so it doubles as a local author-time
gate). Runtime enforcement remains descriptive-first: a malformed program still
dispatches as `unreadable` and aborts at runtime — wiring the schema check into
program *load* (fail-loud instead of silent-abort) is the reserved "enforcing"
follow-on. The program family is additionally validated by the `ProgramGate`
goldfish and seed-paired A/B batches.
