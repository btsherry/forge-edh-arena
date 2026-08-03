# Working Plan — 2026-08-03 (post-compaction anchor)

**Read this first after the compaction.** It captures the full discussion between
Ben and the main agent (me) on turning deck ingestion into a *repeatable,
scalable, accurate* process, records both sides' decisions, and lists the ordered
deliverables with exact file paths + naming. Nothing here has been executed yet
except this doc. The agreed **first work item** is the **artifact atlas** (see §8).

Related durable context: memory `feedback_subagent_discover_compile.md`;
`docs/PR-LOG.md` (the arc); the gold discovery pipeline —
`docs/SYNERGY-INGESTION.md` + `docs/CANARY-BRIEF-GOLD.md` (contract + brief), with
`scripts/gemini_wholedeck.py` / `scripts/selvala-wholedeck-ingestion-*.js` (the
harnesses); and `.claude/skills/arena-dev/SKILL.md` (the compile skill).

---

## 1. Why this exists (the concern that triggered it)

The **exemplary** run was the whole-deck discovery on Ben's **curated** Selvala
list (`selvala-heart-of-the-wilds`): full deck card text + **all** card scripts +
the strategy/deckcheck doc + the rules digest loaded into context, plus external
signal (EDHREC / Scryfall / Spellbook), run as a **structured Fable workflow**
(Phase I wide → Phase II deep → adversarial verify) with an **independent Gemini
cross-check**. 200 records, 0 hallucinations. It finally produced the synergies /
play-patterns / combos Ben had been reaching for.

For the second list (`selvala-competitive`) the main agent used a **lighter,
improvised** single-agent discovery (one Fable prompt written on the spot; no
Gemini cross-check, no EDHREC/Scryfall, no wide/deep phases, no adversarial
panel, no full-context front-load) and then started proposing to *standardize
that shortcut*. **That is drift and must not happen.** The shortcut is a
regression in method, not an improvement.

**Ruling: the exemplary whole-deck process is THE standard. We formalize and
EXTEND it into skills/docs/tooling so every deck gets identical treatment — we do
not thin it, replace it, or drift from it.**

---

## 2. Target pipeline (the process every deck goes through)

1. **Acquire** (deterministic, T0–T2; no models):
   - decklist + quantities + commander; per-card oracle/type/cost; **per-card raw
     Forge script** (`forge-gui/res/cardsfolder/<letter>/<slug>.txt`) = T0 ground truth.
   - **Scryfall**: each card's EDHREC rank → a gross power/importance proxy.
   - **Spellbook**: the *complete* attested combo list for the deck — a **work
     list**, not a signal (see completeness bar §4).
   - **EDHREC**: top-~10 co-occurring cards per card, intersected with the deck →
     **high-co-occurrence in-deck pairs**; those pairs then seed **web/forum
     research** (Draftsim, Reddit, articles) for play-pattern prose keyed on the
     matching card names.
   - legality vs banlist; strategy primer (labelled UNVERIFIED HINT); prior
     telemetry by deck hash.
2. **Discover** (TWO research subagents, full parity):
   - **Fable** and **Gemini** each get the **same** package — full deck text, all
     scripts, strategy doc, rules digest, EDHREC pairs + web findings, Spellbook
     combos — and each runs **Phase I wide** (every anchor) → **Phase II deep**
     (top 15 richest anchors) with an adversarial-verify pass.
   - They **corroborate / contradict / extend** each other. Gemini runs via a
     **shell script** (the `gemini_wholedeck.py` pattern) so it costs **zero
     Claude subagent tokens** — exhaust Gemini freely; stay token-efficient on the
     Claude side.
   - Output schema per finding: `pieces` (all in deck), `mechanism` (quoting real
     script costs), `runner_shape` OR `shape_is_new`, `is_infinite`,
     `yield_model`, `script_evidence` (literal substring), `why_new`.
3. **Compile** (main agent = me, SOLO): with card text + scripts + strategy +
   rules digest **and** the code structure/files in context, author tight /
   correct / efficient / elegant runners + programs. Honest triage **routes each
   finding to the right bucket and never drops a desirable play**: a **finite
   loop/sequence that boosts play or develops board state IS desirable** — capture
   it as a **bounded program**, a **sequencing/tutor weight**, or a **play-
   pattern**, NOT as an *infinite*-mana loop it isn't (the only real error is that
   misclassification — a finite thing compiled as infinite just enters and
   aborts). Genuinely reject only: **duplicates** of compiled combos, **wrong-deck
   shapes that truly cannot execute here**, and **unverifiable/hallucinated**
   mechanics. **Validate against schema (§8.2) → goldfish (ProgramGate) →
   seed-paired A/B.**
4. **Activate**: each finding resolves to exactly one of {compiled program on a
   working+tested runner; tutor/protection/sequencing **weight**; **shape_is_new
   backlog** (a mandatory runner to build)}.
5. **Measure**: goldfish per program; seed-paired batch A/B by deck name.

---

## 3. Division of labor (the pattern — do not violate)

- **Subagents DISCOVER** (full context, zero-hallucination bar, read scripts
  themselves, never guess a cost).
- **Main agent COMPILES** solo (scripts in context, honest triage). **Blind
  subagent authoring of programs/runners is banned** — that was the near-miss Ben
  stopped.
- Every step is **validation-gated**: regression 270/270 → goldfish → seed-paired
  A/B. Change priority order: **correctness → efficiency → elegance.**

---

## 4. Completeness bar (Ben's ruling — STRICT)

A deck's ingestion is **not done** until **every combo and every distinct winning
synergy is accounted for**, where:
- **All Spellbook combos** are implemented (bounded/attested; ~5–50/deck).
- **`shape_is_new` counts as NOT DONE.** All necessary runners must be **written
  AND tested** to clear ingestion. `shape_is_new` is a mandatory work item, never
  a permanent flag. (This is why #98 GOG-brostorm and any other new shapes are
  gating, not optional.)
- **Finite loops/sequences that boost play or board state are DESIRABLE** —
  captured as a **bounded program**, a **sequencing/tutor weight**, or a play-
  pattern. Value-only synergies likewise → weights. Nothing is rejected merely for
  being finite; only genuine dups / truly-unexecutable / hallucinated findings are
  dropped.
- Nothing is silently absent.

Operationally: a synergy ends in exactly one bucket — **program** (genuine, win-
relevant, executable, distinct mechanism), **weight**, or **shape_is_new →
build+test the runner**. A deck is complete only when the shape_is_new bucket is
empty.

---

## 5. Caps & thresholds (agreed)

| Stage | Cap | Note |
|---|---|---|
| Phase I anchors | all ~75 nonbasics | one pass each |
| **Phase II deep** | top **15** anchors by Phase-I richness | (raised from 12) |
| Discovery records | ~200 Fable + Gemini's own set, merged/deduped | discovery cap, not implementation cap |
| Compiled programs | gated by *distinct-mechanism × goldfish-executable × not-dup × win-relevant*; hard backstop ~50/deck → human-triage overflow | funnel naturally yields ~10–40 |
| **Tutor-weighted cards** | **30–40 max**; hub ceiling 0.5 below the combo band | **last night's fold hit 85 — must be pruned to top-N by density (a work item)** |

Scaling insight: the "tens of thousands" (Urza) is the *combinatorial synergy
space*, not the *Spellbook combo list* (bounded). Defense = discovery caps +
dedup-by-mechanism + the viability gate; the hard ceiling is only a backstop.

---

## 6. Decisions & rationale (both sides)

- **Schema/validator size** — Ben: can we document + enforce what we have without
  a rewrite? Me: yes — **descriptive first, enforcing second.** Reverse-engineer
  JSON Schemas from (a) what each runner actually reads and (b) the working
  program files; validate the existing set (expect ~all pass). **Fix only real
  bugs; otherwise loosen the schema to match reality** (Ben agreed). Zero existing
  runners change. New surface = a validator + a schema-per-`program_class`.
- **Per-card subagent brief** — Ben suspects it's a Phase-9/10 throwback, wants it
  gone if unused. Me: verify before cutting. **Keep** the T0 *mechanical
  extraction* (deterministic script parse, no model). The suspect is the **T3
  model per-card capability-vocabulary analysis** (`references/subagent-brief.md`,
  builds `capability-inventory.json`). Action: grep for consumers of
  `capability-inventory.json`; if unconsumed and superseded by whole-deck combo
  discovery → cut with evidence. No silent deletion.
- **Gemini parity** — run as a separate API research subagent via shell (parity
  inputs), token-free on Claude; worth a small experiment on how much parity we
  can elicit.
- **Validator failure policy** — working program that fails schema → the schema is
  wrong (widen); only tighten where non-conformance is a real bug. (Agreed.)
- **Cadence** — **one item at a time, reviewed together**, both sides must like the
  output before moving on. (Agreed.)

---

## 7. Scope decision

**Shelve `selvala-competitive`** (kept as a useful drop-in/A-B canary; return
later). **Focus on the curated `selvala-heart-of-the-wilds` list and push it to
the project's implementation limit** = the completeness bar (§4), which now
REQUIRES building the `shape_is_new` runners (GOG brostorm #98, etc.).

---

## 8. Deliverables (ordered; one at a time, reviewed)

### 8.1 Artifact atlas — **FIRST ITEM**
- Home: **`docs/atlas/`** (own subdir). Light summary + link list in the
  implementation plan; referenced by the coding skill.
- Per artifact: *what it is / who generates it (deterministic prep vs subagent vs
  hand-authored) / its schema / a canonical example / the consumer that reads it.*
- Delivery: **structure/template + the `combo-program` family entries first** (the
  artifacts we author + validate most), reviewed for FORMAT, then expand to all
  ~15 artifacts. Also the place I verify the per-card-brief question (§6).

### 8.2 Schema + validator ("XSD equivalent")
- JSON Schema per `program_class` + per artifact, reverse-engineered from runner
  field-reads + working programs. Validate existing set (expect ~all pass).
- Gate: author/register-time + a **prep validation gate**. Implementation TBD
  (Java prep gate vs standalone) — decide when we reach it.

### 8.3 Runner catalog — **`docs/runner-cat.md`**
- Per runner: shape it executes, exact program contract (fields read),
  yield_models / kinds / measures, one canonical example. Written from ALL
  existing runners (§10).

### 8.4 Coding skill (NEW, for future-me)
- A `.claude/skills/<name>/SKILL.md` (name TBD — e.g. `arena-dev` /
  `write-runner`). Onboarding checklist (load deck text + all scripts + strategy +
  rules digest + code structure BEFORE compiling), references to the atlas +
  runner-cat + schemas, how to write correct/efficient/elegant runners + compile
  programs, the validate→goldfish→A/B gate.

### 8.5 `ingest-deck` skill EXTENSION — ✅ SUPERSEDED (2026-08-03)
- The `ingest-deck` skill was **deleted** during the state truing-up; there is no
  skill to extend. The canonical discovery layer is the **gold pipeline**:
  `docs/SYNERGY-INGESTION.md` + `docs/CANARY-BRIEF-GOLD.md` (contract + brief) run via
  `scripts/gemini_wholedeck.py` and `scripts/selvala-wholedeck-ingestion-*.js`. Any
  future acquisition-layer work (EDHREC co-occurrence, Scryfall EDHREC-rank,
  Spellbook full combo list; completeness bar §4; caps §5) folds into those
  artifacts, not a skill.

### 8.6 Research-subagent briefs (parity) — ✅ ALREADY EXIST (2026-08-03)
- Not to be written anew — the Fable+Gemini parity briefs already exist and are the
  best-known-good: `docs/SYNERGY-INGESTION.md` (the shared Fable+Gemini contract +
  compilable record schema + Gemini invocation) and `docs/CANARY-BRIEF-GOLD.md` (the
  source rules-lawyer brief). Preserved from the 200-record run.

### 8.7 Per-card brief verdict — ✅ RESOLVED BY DELETION (2026-08-03)
- The T3 per-card brief (`subagent-brief.md`) was **deleted** with the `ingest-deck`
  skill, so `capability-inventory.json` now has **no producer and no consumer** — a
  clean cut (see `docs/atlas/capability-inventory.md`). The consumed T0 card facts
  live in `deck-cards.json`.

### 8.8 IMPLEMENTATION-PLAN.md update + prune
- Surgical, additive references for every new/touched doc + skill; then a pass to
  remove out-of-date / dead / dead-end-experimental content. Careful and minimal.

---

## 9. Naming nomenclature reference

- **Artifacts** (dossier, gitignored): `deck-cards.json`, `combos.json`,
  `advisory-combos.json`, `discovered-combos.json` (arena.discovered-combos/1),
  `discovered-synergies-wholedeck.json`, `combo-program-<id>.json`
  (arena.combo-program/1), `engine-program-<id>.json`, `pairing-program-<id>.json`,
  `tutor-priorities.json`, `protection-priorities.json`, `route-coverage.json`,
  `paired-plays.json`, `capability-inventory.json` (SUSPECT — §8.7),
  `dossier.json` (sha256 index), `fixtures/fixture-<id>.json`,
  `program-backlog.json`, `build-manifest.json`.
- **Combo→program mapping**: EngineFacade scans `combo-program-*.json`, keying by
  the substring between chars 14 (`combo-program-`) and −5 (`.json`); the file's
  `combo_id` must match. Combos registered in `combos.json` (Spellbook, numeric
  ids) or `discovered-combos.json` (domain, `syn-`/`ben-` ids). Readiness =
  `ComboTracker`: all named pieces reachable (hand OR battlefield) + fullySpecified.
- **program_class → runner** (dispatch in `ComboAwareLobbyPlayer`): `selvala_mana_loop`→SelvalaManaLoopRunner, `mana_loop`→ManaLoopRunner, `dreadnought_window`→DreadnoughtWindowRunner, `seedborn_engine`→SeedbornEngineRunner, `bounce_recur`→BounceRecurRunner, `cast_recur`→CastRecurRunner, `cast_bounce`→CastBounceRunner, `pairing`→PairingRunner (via action.pairing()), `engine`→EngineProgramRunner (via action.engine()), `ping_loop`/default→ProgramRunner. Unknown class → `program_class_unsupported` abort (ships flagged).
- **Yield models** (SelvalaManaLoopRunner): POWER_CONSTANT, POWER_RAMPING, ENCHANTMENT_COUNT, CREATURE_COUNT, CONSTANT, **ELF_COUNT**.
- **dreadnought_window kinds**: sac_draw, power_mana, power_draw, power_loop.
- **Outlet kinds** (deck-aware, `sink.outlets`: {card, kind, min_x}): mass_flip, fetch_swing, fetch_fixed, x_body, overrun.
- **seedborn_engine modes**: omnath_accumulate, activated_sink.
- **bounce_recur measures**: board_counters, hand_size, opp_creatures.

## 10. Existing runners (source for §8.3 catalog)
SelvalaManaLoopRunner, ManaLoopRunner, DreadnoughtWindowRunner, SeedbornEngineRunner,
BounceRecurRunner, CastRecurRunner, CastBounceRunner, PairingRunner,
EngineProgramRunner, ProgramRunner. (all in `forge-arena/src/main/java/forge/arena/engine/`)

---

## 11. Environment / process facts

- Build/test: `JAVA_HOME=/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home mvn -o -pl forge-arena -am test -Dcheckstyle.skip=true` from repo root. Full arena suite ~10 min, **270 tests** (0 failures is the bar).
- Batch: `bash forge-arena/scripts/batch.sh <config.json>` (config: run_id, seed_base, games, workers, out_dir, limits{turns,wall_clock_sec,priority_passes_per_turn}, seats[]). **NO builds while a batch runs.** batch.sh regenerates `target/classpath.txt` via `mvn install` if stale.
- Goldfish: `ProgramGate` (java `-cp target/classes:$(cat target/classpath.txt) -Darena.assets.dir=forge-gui forge.arena.prep.ProgramGate <dossier>`), or `SelvalaGoldfishRun`/`ProgramGateTest`.
- Prep: `forge.arena.prep.PrepMain <decklist> --id <id> --commander <name> --out forge-arena/decks [--offline]` (Gates 0–4 + Spellbook + tutor weights). Ingest only: `forge.arena.ingest.IngestMain`.
- Card DB path (from repo root): `forge-gui/res/cardsfolder/<letter>/<slug>.txt`. Match cards by exact `Name:` line (filename slugs are lossy — e.g. Nylea → `nylea_keeneyed`).
- **Win attribution**: `record.seats[record.winner_seat]` (seating is randomized per game — never seat index).
- **Commits**: local only on branch `arena`, **never push**, end message with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; commit at green milestones. Dossiers + `runs/` are gitignored/untracked (add code+docs selectively, never `git add -A`).
- `.dck` gotcha: the batch expects `decks/<id>.dck` at top level; IngestMain writes it under the deck's dossier — copy it up.

---

## 12. Current state (as of this doc)

- Branch `arena`, **7 commits** this arc: 7c1e906 (2 new shapes + hub fold + proofs), ed874bf (Selvala 1→7/100), 216d8d5 (drop-in reuse), 1406eba (A/B 1/100), 0d4c678 (#96 deck-aware outlets), d75a1fa (#97 ELF_COUNT), fe9f847 (re-A/B 2/100). Regression **270/270**. Nothing pushed.
- Curated Selvala **7/100** (from ~1/100); new shapes fire organically. `selvala-competitive` **shelved at 2/100**.
- **Open tasks**: #98 (GOG brostorm — first `shape_is_new` runner needed, gating completeness), #89 (adversarial review of new runners), #62–64 (standing scorecard / one-command A/B), #58–61 (mana_loop auto-emitter — note: distinct from the discover-then-compile pattern; reconsider), #65 (Gate-4 pairing/engine/template derivation), #48/#49 (Giada/Urza backlog).

---

## 13. First work item + sequence (agreed)

**START: §8.1 the artifact atlas** — structure/template + `combo-program` family
entries first, reviewed for format. Then §8.2 schema/validator (derived from the
atlas) → §8.3 `runner-cat.md` → §8.4 coding skill → §8.5–§8.7 (superseded /
resolved by the 2026-08-03 discovery-state cleanup) → §8.8 impl-plan update + prune.
Then execute the curated-Selvala completeness pass *through* these rails (which
includes building #98 and any other `shape_is_new` runners, and pruning tutor
weights to 30–40).

**Open/TBD to settle in-flight**: coding-skill name; atlas format (single doc vs
per-artifact files); validator implementation (Java gate vs standalone); Gemini
parity experiment scope.
