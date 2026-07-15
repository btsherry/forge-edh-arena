# Forge EDH Arena — Implementation Plan v3.3

> **Repo note (2026-07-15):** This is the master spec, authored in a planning session prior to implementation (as v3.1) and amended in-repo since. T0 verification is complete — see [T0-VERIFICATION.md](T0-VERIFICATION.md) for confirmed/corrected class names (4 corrections, incl. no engine turn cap; arena-side limits required). Per §11: when this document and the Forge source disagree, the source wins, and this document gets updated in the same PR.

**Mission:** A headless, standalone engine on top of Card-Forge/forge that runs 4-player Commander pods with assignable AI per seat, at batch scale, to compare netdecks against user-designed decks with heavy statistical, qualitative, and play-pattern analysis — plus a combo-aware AI layer (per-deck prep, live tracking, deliberate execution, combo-directed tutoring).

**This revision (v3):** adds concrete class designs, code and file-format examples, a unit/golden test suite, expanded pre-run preparation steps, a play-pattern & qualitative analytics spec, and a design response to every weakness identified in v2 §9.

**v3.1 amendments (from the Selvala end-to-end trace):** (1) executor yield may come from a third bound permanent (Arbor Elf taps the Forest, not itself); (2) executors are stage-chained and phase-aware (Staff = mana loop → draw loop → deploy/win, entered in precombat main); (3) a LethalityPlanner decides how infinite resources convert to a win against three opponents; (4) Gate 3.5: LLM-generated binding files — a Claude API call at prep time parameterizes archetype bindings per newly-encountered combo, verified by sandbox simulation before use, cached in a global binding library so the approach scales to unbounded deck inflow.

**v3.2 amendments (2026-07-15 session, post-T0 + Spellbook probe):** (1) **Win Routes spec** — docs/WIN-ROUTES.md defines the closed set of win-conversion routes (each terminating in an engine-enforced end state) plus versioned, deterministic feature-classification rules; LethalityPlanner's route enum is drawn from it, not hand-grown per trace. **Classification is per-deck, at preflight** (Gate 3): only the `produces` features actually appearing in that deck's included combos are classified, cache-first against a global feature→route mapping library — same amortization model as Gate 3.5 bindings; no global vocabulary sweeps. (2) **Gate 3 route-coverage report** — prep flags any `produces` feature in the deck's combos that the rules can't classify, before a batch runs. (3) **Gate 3.6 stall autopsy** — batches never call LLMs in-loop; instead, proven-infinite states that fail to convert within N turns are snapshotted and sent to a post-run bindgen repair pass (one Claude call per *distinct* stall, sim-verified, cached in the binding library). Rationale: keeps seed determinism and pays for each answer once. (4) Empirically verified this session: Spellbook `find-my-combos` returns per-card zone requirements, `manaNeeded`, easy/notable prerequisite split, and step text (richer than v3 assumed); per-deck cache keyed by deck hash works (Selvala list: 11 included combos, 142 almost-included, 50 distinct produces-features — all 11 resource-only, none directly lethal). (5) **Combo telemetry taxonomy + pilot-quality floors** — the §5 event log gains a normative combo/route event set (notably `combo_ignored` and `route_selected`/`route_rejected`: silence is never a valid record of a decision), §7 gains the extended funnel with hesitation metrics, and Gate 4 gains per-deck pilot-quality floors so a bad pilot is reported as a pilot problem, never silently read as a bad deck.

**v3.3 amendments (2026-07-15 session, preflight/ingestion discussion):** (1) **Default batch target is 1,000 games** (±~2.7pp Wilson CI at p=0.25; paired-seed A/B detects 3–5pp lifts), 10k remains a supported scale — Phase 1 exit criterion updated accordingly. (2) **Prep is packaged as a standalone dossier compiler** (`arena prep <deck>`): all gates run once per deck at ingestion and emit a versioned **deck dossier** (normalized list, lint/implementability reports, combos, bindings, win plan, tutor priorities, mulligan hints); batch start does no prep work — it only validates dossier freshness (deck hash, schema versions, binding-library version) and fails fast. Lands in two versions: **v1 after Phase 3** (detection artifacts, route coverage, tutor weights), **v2 after the first executor exists** (sim verification + dossier goldfish). (3) **Dossier goldfish** — prep's final gate plays N solo games with the combo-aware controller consuming the dossier against a non-interactive seat, asserting the deck executes its primary win route by turn X; needs only bootstrap + EngineFacade + the GameState sandbox (pulled into Phase 1 as shared infrastructure), not pods. (4) **Tutor priorities derive from the win plan, not just the combo list** — enabler/payoff cards (e.g. Concordant Crossroads, Craterhoof: in ~zero Spellbook combos, mandatory for Selvala's actual win line) get weights from route requirements.

**Date:** July 2026 · **Upstream:** Forge master; latest release forge-2.0.12 (Apr 2026); Java 17+; Maven; GPL-3.0.

## 1. Verified facts vs. assumptions

**Verified (repo/wiki, July 2026):** module layout (forge-core, forge-game, forge-ai, forge-gui with res/ data, GUI frontends); headless CLI simulator SimulateMatch supporting `sim -f commander` with multiple decks, `-n`, tournaments; per-player AI personality profiles in forge-gui/res/ai/*.ai; experimental lookahead ("simulation") AI; wiki warns AI-vs-AI games can run very long; new sets implemented within weeks.

**Assumptions to verify in T0 before scaffolding** (code archaeology, may have drifted): class names PlayerControllerAi, AiController, ChangeZoneAi, GameCopier, GameStateEvaluator, SpellAbilityPicker, ComputerUtilMana; RegisteredPlayer.forCommander(...); GameRules(GameType.Commander); Match.playGame(); card-script DSL location forge-gui/res/cardsfolder/; .dck section headers; a subscribable game event bus. T0 produces `forge-arena/docs/T0-VERIFICATION.md` with the corrected names; all code below uses these names provisionally and must be updated from T0 output.

## 2. Architecture (v3)

```
forge/  (fork; upstream patches tagged // ARENA-PATCH + logged in UPSTREAM-PATCHES.md)
└── forge-arena/
    ├── schemas/        Versioned JSON Schemas for every artifact (write these FIRST)
    ├── bootstrap/      Headless init of card DB from explicit paths
    ├── ingest/         Netdeck/homebrew import → .dck + deck-meta.yaml
    ├── preflight/      Legality lint, implementability check, goldfish compile
    ├── prep/           Spellbook client, cache/snapshot, artifact emitters
    ├── bindgen/        Gate 3.5: Claude API binding generator + sim verifier + global library
    ├── engine/         EngineFacade + SeatView (isolation layers — see §9 W2/W8)
    ├── harness/        ArenaRunner, seats, seeds, rotation, limits, worker pool
    ├── ai/             SeatAi factory, ComboAwareController
    ├── combo/          ComboTracker, PrereqEvaluator, LinePlanner, executors/
    ├── tutor/          TutorRanker
    ├── report/         JSONL logging, stats, TrueSkill, play-pattern analytics, narratives
    └── scripts/        smoke.sh, batch.sh, canary.sh, report.py
```

**Design rules** (unchanged from v2, now enforced by tests): all behavior behind the PlayerController seam; ComboAwareController fully data-driven from prep artifacts; no network during a batch; every run reproducible from (seedBase, artifacts, fork commit).

## 3. Pre-run preparation pipeline (expanded)

The goal-state is "solid runs": a batch either starts with everything it needs validated, or fails fast with an actionable report. Prep is a chain of gates; each emits a machine-readable report into the run directory.

**v3.3 — packaging: the dossier compiler.** Gates 0–3.6 run **once per deck at ingestion** via `arena prep <deck>`, emitting a versioned deck dossier (`decks/<id>/dossier/` — every artifact below plus a `dossier.json` index with schema/binding-library/win-routes versions and content hashes). The dossier includes **`deck-cards.json`**: the full 99+commander with per-card oracle text, mana cost, type line, and color identity, extracted from the local Forge card DB at prep time (no network). This is the self-contained card-context package handed to the LLM in Gate 3.5 binding generation and Gate 3.6 stall autopsies — the model must be able to see every payoff and enabler the deck actually contains (a stall fix often lives in the 99, not in the combo: Craterhoof, Crossroads), without any call-time DB access. As a stable per-deck text block it also prompt-caches across repeated bindgen calls. Batch start performs **no prep work**: it validates dossier freshness against the manifest and refuses stale or missing dossiers. Prep failures therefore surface at ingestion, dossiers are inspectable/diffable before a run trusts them, and the run manifest pins one dossier version per deck. The prep tool's final gate is the **dossier goldfish** (v2, requires an executor): N solo games, combo-aware controller + dossier, non-interactive opponent, asserting the primary win route executes by turn X — proving ingest → detect → assemble → execute → convert end-to-end using only bootstrap + EngineFacade + the GameState sandbox, no pods. Behavioral quality under interaction remains the canary's and batch's job.

### Gate 0 — Ingest

Accept Forge .dck, plain "1 Card Name" text, and Moxfield/Archidekt text exports. Emit normalized .dck plus deck-meta.yaml:

```yaml
# decks/selvala-b3/deck-meta.yaml
name: Selvala Heart of the Wilds — Bracket 3
source: homebrew            # homebrew | netdeck
source_url: null            # e.g. https://moxfield.com/decks/... for netdecks
archetype_tags: [big-mana, combo, mono-green]
expected_bracket: 3
author_notes: "Testing Mantle/Staff lines vs. meta netdecks"
```

Example emitted .dck (exact section headers verified in T0):

```
[metadata]
Name=Selvala Heart of the Wilds - Bracket 3
[Commander]
1 Selvala, Heart of the Wilds
[Main]
1 Umbral Mantle
1 Staff of Domination
1 Phyrexian Dreadnought
...
```

### Gate 1 — Legality lint (DeckLint)

100 cards inc. commander; singleton (basics exempt); color identity of every card ⊆ commander's; Commander banlist check against a pinned local banlist file (versioned — bans change; a run manifest must record which banlist it used). Errors block; warnings (e.g., >1 Game Changer count, for your bracket bookkeeping) annotate.

**Deferred TO-DO (v3.3, down the road — explicitly NOT current work): Gate 1.5 bracket check.** Verify a deck's `expected_bracket` (deck-meta.yaml) against its actual contents: Game Changers count (pinned versioned list, same mechanism as the banlist), 2-card infinite combos present in the Spellbook data (cheap once Gate 3 artifacts exist), tutor density, extra-turn and mass-land-denial cards. Output: warnings + a computed bracket estimate in the dossier, so "bracket-3 brew vs bracket-3 netdecks" claims are checkable and the §7 sanity anchors (a B3 shouldn't beat cEDH 70/30) have data behind them. **Sourcing option:** rather than maintaining Game Changers / bracket heuristics locally, query a Moxfield or EDHREC API for the deck's bracket / Game Changers data at prep time — same rules as Spellbook (prep-time only, per-deck snapshot cached by deck hash, version pinned in the manifest, W5 recorded-fixture contract tests), which also keeps the data current without hand-updates. Evaluate API availability/ToS when this gate is picked up. Slot after Gate 3 (it wants combo artifacts); revisit when Phase 3 lands.

*Checked 2026-07-15 — **deckcheck.co** has a documented read-only API (`https://deckcheck.co/api/external`, docs at /docs/api): `GET /deck` (keyless, 10 req/s) returns full deck data INCLUDING `bracket` and `performanceIndex` (CRISPI 0–10) plus per-card oracle text; `GET /deck-search` (API key via contact@deckcheck.co) filters by bracket/CRISPI/colors/price. Limitation: `/deck` evaluates decks hosted ON DeckCheck (by their deck id/url) — no documented submit-arbitrary-list endpoint, so evaluating OUR brews would require publishing them there first (or asking; keys are granted by email). Strong secondary use: `/deck-search` is a calibrated **netdeck sourcing** tool — pull real opponent lists AT a declared bracket for list-vs-list experiments, then ingest via Gate 0. ToS: read-only, no bulk/scrape/model-training; modest research use fits, confirm by email if usage grows. **User has a DeckCheck subscription — queued TO-DO: request/configure an API key (env var `DECKCHECK_API_KEY`, never in-repo) and test pulling summary data (CRISPI `performanceIndex`, `bracket`, `analysisPreview`) for a known deck via `/deck` and `/deck-search`, ahead of Gate 1.5 wiring.***

### Gate 2 — Implementability preflight

Every card name must resolve in Forge's card DB; emit unimplemented-cards.txt per deck. Then a goldfish compile: for each deck, run 3 solo games against a goldfish seat with a 12-turn cap, asserting no exceptions and that every castable card's script loads. This catches broken/missing card scripts before they poison a 10k-game batch. Netdecks with fresh set cards fail here most often — the report tells you whether to wait for upstream, patch a card script, or substitute.

### Gate 3 — Combo prep (Spellbook)

As v2 §5: query the Commander Spellbook find-my-combos API once per deck, keyed by `deckHash = sha256(sorted oracle names + counts)`; snapshot raw JSON; transform to artifacts (§5). Reminder of the v2 semantic rule: runtime tutor/tracking data comes only from **included** combos ("almost included" = the piece is not in the 99 — deckbuilding advice only, emitted to a separate advisory report).

**v3.2 — route-coverage report (per deck, at preflight).** Gate 3 additionally classifies each `produces` feature in the deck's included combos using the versioned rules in docs/WIN-ROUTES.md — **cache-first**: features classified for any earlier deck are library hits; only never-seen features run the rules (and, if unmatched, are flagged `unroutable` and queued for prep-time LLM classification via the Gate 3.5 machinery or human review). Output is `route-coverage.json`: each combo annotated with its reachable win routes and required payoff support from the 99. A deck whose combos are all unroutable gets a blocking warning — its win path is not expressible to the planner, so batch results would understate it. Empirical shape (verified 2026-07-15): Selvala list → 11 included combos, 50 distinct features, **all resource-only** (untap/mana/ETB/storm — none directly lethal); every win requires payoff conversion, which is exactly what the planner + route-coverage check exist to guarantee.

### Gate 3.5 — LLM-generated binding files (scales prep to unbounded deck inflow)

Hand-authoring executor-bindings.json is the pipeline's manual bottleneck (§9 W1). Gate 3.5 automates it with a generate-and-verify loop against a Claude API call, built on one structural insight: **bindings are per-combo, not per-deck.** Spellbook combo variants carry stable IDs, so a binding is generated once, stored in a global content-addressed binding library keyed by (combo_variant_id, binding_schema_version), and every subsequent deck containing that combo is a cache hit. Generation volume is O(distinct new combos ever encountered), not O(decks) — and real decks concentrate heavily on the same few thousand combos, so the library converges fast.

Per new combo:

1. **Assemble the prompt:** oracle text of each combo card (from the local card DB snapshot), Spellbook steps/prerequisites/result tags, the archetype DSL documentation, the binding JSON Schema, and 3–5 verified few-shot bindings. Instruction: respond only with JSON conforming to the schema; select an existing archetype and fill its params, or return `{"archetype": null, "proposal": "<one-paragraph description>"}` if none fits. Low temperature; the static prefix (DSL + schema + few-shots) is prompt-cached.
2. **Static gates:** JSON Schema validation; lint (every referenced card is in the combo, costs parse, param roles are legal for the archetype, yield_source references a bound permanent).
3. **Simulation verification (the oracle):** auto-construct a sandbox game state from the combo's zone_reqs (pieces onto battlefield/hand as required, generous mana), run the bound executor's validate(), and assert the profit invariant or win within bounded steps. Pass → binding marked executable, committed to the library with `{request_hash, model_id, verbatim_response, sim_transcript_hash}` for reproducibility. Fail → one repair retry with the simulation error transcript appended; second failure → combo stays detection-only with generic fallback, logged `binding_gen_failed` with reasons.

Novel-archetype proposals go to a human review queue; the LLM never emits executable Java — it only parameterizes existing archetypes or files proposals. New archetypes remain hand-written, tested code.

**Constraints:** bindgen/ runs only at prep time (the no-network-in-game-loop rule is unchanged); API key via environment variable; run manifests pin the binding-library version so batches are reproducible even as the library grows; a nightly batch job can pre-warm the library from popular-combo lists. Cost stays bounded and amortizes to ~zero for repeat combos.

### Gate 3.6 — Stall autopsy (v3.2; runtime→prep feedback loop)

The batch loop stays LLM-free, but its failures feed the next prep cycle. During a batch, if a seat **proves** infinite resources (loop shortcut fires) and the game does not reach an engine-enforced end state within N turns (default 2), the harness: (1) logs `combo_stalled` with the binding id, the LethalityPlanner's evaluated-and-rejected routes, and the reasons; (2) dumps the full game state (Forge `GameState` dump format) to `stalls/<state_hash>.txt`. Post-run, bindgen processes **distinct** stalled states (deduped by state hash → usually a handful per 10k games): one Claude API call per distinct stall, carrying the game state, the fired binding, the route catalog, and the rejection trace; the response is a repaired/extended binding or a proposed new route mapping — which passes the same schema → lint → sandbox-sim verification as Gate 3.5 before entering the library/catalog. The next batch converts those states deterministically.

Properties this preserves: seed determinism (no in-loop network), bounded cost (one call per distinct failure mode, ever — same amortization argument as Gate 3.5), and monotonic improvement (the catalog grows from observed failures, not speculation). A `--dev-live-line` single-game mode MAY later allow an interactive Claude-driven line for debugging/authoring; it is never valid in batch mode and its games are never counted.

### Gate 4 — Canary

Before any large batch: 20 games of the exact pod configuration with full logging, auto-checked for: crash rate 0, timeout rate < 10%, every seat both won ≥0 and cast its commander in ≥90% of games (catches bootstrap/AI misconfig), event-log schema validation. `scripts/canary.sh` is the gate CI runs.

**v3.2 — per-deck pilot-quality floors.** For every combo-aware seat, the canary additionally enforces acceptance criteria on the deck's *pilot*, so a bad pilot can never silently read as a bad deck:

- route coverage clean (no `unroutable` win path, from Gate 3);
- **conversion-when-ready floor**: across canary games, `line_entered` ≥ configured fraction of `combo_ready` games (default 0.5), and zero `combo_stalled` without a matching Gate 3.6 dump;
- goldfish win-turn within the deck's expected bracket band (from deck-meta.yaml);
- telemetry completeness: every ready-with-no-attempt decision point has a `combo_ignored` reason, every planner evaluation has `route_selected`/`route_rejected` events.

A deck failing floors is marked `pilot_invalid` in the canary report with the failing metric named; the batch refuses to include its results in list-vs-list conclusions (it may still run for telemetry, clearly labeled). Floors are recorded in the run manifest so "which quality bar was this experiment run under" is always answerable.

### Gate 5 — Run manifest

Every batch writes run-manifest.json first:

```json
{
  "schema": "arena.run-manifest/1",
  "run_id": "2026-07-10T21-33_selvala-vs-meta",
  "fork_commit": "a1b2c3d",
  "seed_base": 42,
  "games": 10000,
  "seats": [
    {"deck": "selvala-b3", "deck_hash": "9f3a…", "ai": {"profile": "Default", "combo_aware": true}},
    {"deck": "net-krenko", "deck_hash": "77b1…", "ai": {"profile": "Reckless"}},
    {"deck": "net-atraxa", "deck_hash": "c0de…", "ai": {"profile": "Cautious", "simulation_ai": true}},
    {"deck": "net-muldrotha", "deck_hash": "51ab…", "ai": {"profile": "Default"}}
  ],
  "rotation": "latin_square_4",
  "limits": {"turns": 30, "wall_clock_sec": 600, "priority_passes_per_turn": 2000},
  "artifacts": {"spellbook_snapshot_dates": {"selvala-b3": "2026-07-09"}, "banlist_version": "2026-06-30"}
}
```

## 4. Harness — core classes and code

```java
// harness/Seat.java
public record Seat(String deckId, AiSpec ai) {
    public static Seat of(String deckId, AiSpec ai) { return new Seat(deckId, ai); }
}

// harness/AiSpec.java
public record AiSpec(String profile, boolean comboAware, boolean simulationAi,
                     double comboPatience /*0=win asap .. 1=hold for protection*/) {
    public static AiSpec profile(String p) { return new AiSpec(p, false, false, 0.0); }
    public AiSpec comboAware(boolean b)    { return new AiSpec(profile, b, simulationAi, comboPatience); }
    public AiSpec simulationAi(boolean b)  { return new AiSpec(profile, comboAware, b, comboPatience); }
}
```

```java
// harness/ArenaRunner.java (single-game core; workers call runOne in separate processes)
public GameRecord runOne(RunConfig cfg, int gameIndex) {
    long seed = Seeds.derive(cfg.seedBase(), gameIndex);          // splittable, documented fn
    List<Seat> seated = Rotation.latinSquare(cfg.seats(), gameIndex); // seat-position fairness
    GameRules rules = EngineFacade.commanderRules();               // 40 life, cmdr dmg, free mull
    List<RegisteredPlayer> players = new ArrayList<>();
    for (Seat s : seated) {
        Deck deck = DeckStore.load(s.deckId());
        RegisteredPlayer rp = EngineFacade.registeredCommanderPlayer(deck);
        rp.setPlayer(SeatAiFactory.lobbyPlayer(s.ai(), ArtifactStore.forDeck(s.deckId())));
        players.add(rp);
    }
    try (EventRecorder rec = EventRecorder.jsonl(cfg.outDir(), gameIndex)) {
        GameOutcome outcome = EngineFacade.playWithLimits(rules, players, seed,
                cfg.limits(), rec::onEvent);                       // enforces turn/clock caps
        return GameRecord.from(gameIndex, seed, seated, outcome, rec.summary());
    } catch (EngineCrash e) {
        return GameRecord.crashed(gameIndex, seed, seated, e);     // recorded, never dropped
    }
}
```

**EngineFacade** (in engine/) is the only class allowed to import Forge internals for game setup/teardown; everything else in forge-arena compiles against the facade. This is the concrete remediation for unverified-internals risk (§9 W2): when T0 or a future rebase reveals renamed classes, the blast radius is one file (enforced by an ArchUnit test, §8).

**Timeouts as data:** games hitting any limit end as `result: "timeout_draw"` with the limiting factor recorded — never discarded (discarding biases against grindy decks, which matters when comparing your brews to stax/control netdecks).

### Shipped CLI reference (v3.3 — Phase 1 as implemented)

**`scripts/batch.sh <batch-config.json>`** — launches a batch. One positional argument: the config file (format below). Environment: `JAVA_HOME` (default `/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home`). Behavior: resolves the runtime classpath via `mvn dependency:build-classpath` (cached at `forge-arena/target/classpath.txt`, regenerated when the pom is newer), then runs `forge.arena.harness.BatchMain` from the repo root. The orchestrator JVM is light (`-Xmx512m`); worker heap comes from the config.

**The human-readable log lives at `<out_dir>/run.log`.** BatchMain prints its exact path (as a ready-to-copy `tail -f` line) at batch start, before workers spawn, and again in the completion summary — you never have to reconstruct it. Watch a running batch with `tail -f <out_dir>/run.log`; all workers append to this single file with `[wN gNNNN turn seat]`-prefixed lines at the default verbosity tier (game lifecycle + combo/route/tutor decisions).

**`batch-config.json` fields** (this file is the batch's entire argument surface):

| Field | Required | Default | Meaning |
|---|---|---|---|
| `run_id` | no | `run-<seed_base>-<games>` | manifest run id |
| `seed_base` | **yes** | — | root seed; per-game seed = `Seeds.derive(seed_base, gameIndex)` |
| `games` | **yes** | — | total games in the batch |
| `workers` | no | 4 | worker JVM count (interleaved index stride: worker w plays w, w+W, w+2W…) |
| `worker_heap` | no | `-Xmx2g` | per-worker JVM heap flag (plan W6) |
| `out_dir` | **yes** | — | run directory; created if absent |
| `assets_dir` | no | `../forge-gui` | forge-gui dir containing `res/` (explicit-path bootstrap) |
| `rotation` | no | `latin_square_4` | seat rotation scheme (`latin_square_4` \| `fixed`) |
| `limits.turns` | no | 30 | arena-side turn cap; `0` disables |
| `limits.wall_clock_sec` | no | 600 | per-game wall clock (last-resort limit; must be > 0) |
| `limits.priority_passes_per_turn` | no | 2000 | per-turn priority cap; `0` disables |
| `seats[]` | **yes** (2–4) | — | pod in canonical (manifest) order |
| `seats[].deck` | **yes** | — | path to a Commander `.dck` file |
| `seats[].profile` | no | `Default` | AI personality: `Default` \| `Cautious` \| `Experimental` \| `Reckless` |
| `seats[].simulation_ai` | no | false | per-seat lookahead AI (`AIOption.USE_SIMULATION`) |

**Outputs — per-batch, never clobbered:** every execution creates `<out_dir>/<batch_id>/` where `batch_id = <run_id>-<yyyyMMdd-HHmmss>` (numeric suffix on same-second collision), containing: `run-manifest.json` (written FIRST, schema-validated — an invalid manifest aborts with exit 2 before any game runs; carries `batch_id`), `worker-config.json` (resolved absolute paths for workers), `game-records.jsonl` (one `arena.game-record/1` line per game, atomic appends), `events/NNNNNN.jsonl` (per-game `arena.events/1` streams), `run.log` (human-tailable, `[wN gNNNN …]` lines), `worker-<N>.out` (per-worker stdout/stderr for debugging). Additionally `<out_dir>/batches.jsonl` is the **append-only batch ledger**: one `batch_start` line per batch recording the batch id and every *resolved* input (games, workers, seed_base, heap, limits, rotation, seats with absolute deck paths + profiles, assets dir, config path, fork commit), and one `batch_end` line with record counts, result mix, wins by deck, wall time, and worker failures — the running answer to "what exactly did batch X run?". Exit codes: `0` all workers clean, `1` ≥1 worker exited nonzero (crashed *games* are still exit 0 — they're records, not failures), `2` invalid manifest. A completion summary prints result counts, wins by deck, avg game time, and games/hour.

**`scripts/smoke.sh`** — the CI gate (plan §11): no positional arguments. Environment overrides: `SMOKE_GAMES` (default 8), `SMOKE_WORKERS` (2), `SMOKE_TURNS` (10), `JAVA_HOME`. Behavior: builds the module chain and runs all forge-arena unit tests, then generates a temp batch config over the four baseline decks and runs the canary via `batch.sh`. Pass criteria: record count == `SMOKE_GAMES`, zero `crash` results, non-empty `run.log`. Prints `SMOKE PASS` and the run directory, exits nonzero on any failure.

**Direct JVM entry points** (what the scripts wrap): `forge.arena.harness.BatchMain <batch-config.json>` — the orchestrator; `forge.arena.harness.WorkerMain <runDir> <workerId> <numWorkers>` — internal, spawned by BatchMain, reads `<runDir>/worker-config.json`; not intended for manual use except replaying one worker's slice for debugging.

**Phase-1 exit run** (deferred; launch when ready): a config with `"games": 1000`, `"workers": 8` over the four baseline decks, then `bash forge-arena/scripts/batch.sh <config>` — expect ~3–4 h at baseline throughput; verify <2% timeout/crash and a seed replay afterward.

## 5. Prep artifacts — file examples

**combos.json** (per deck; excerpt):

```json
{
  "schema": "arena.combos/1",
  "deck_hash": "9f3a…",
  "spellbook_snapshot": "2026-07-09",
  "combos": [
    {
      "id": "csb-4131",
      "url": "https://commanderspellbook.com/combo/4131/",
      "cards": [
        {"oracle": "Selvala, Heart of the Wilds", "forge": "Selvala, Heart of the Wilds", "zone_req": "battlefield", "commander": true},
        {"oracle": "Umbral Mantle", "forge": "Umbral Mantle", "zone_req": "battlefield"}
      ],
      "prerequisites": [
        {"type": "CREATURE_POWER_AT_LEAST", "value": 4, "raw": "You control a creature with power 4 or greater"},
        {"type": "MANA_AVAILABLE", "value": "{1}", "raw": "..."},
        {"type": "UNPARSED", "raw": "Selvala able to tap"}
      ],
      "results": ["INFINITE_GREEN_MANA", "INFINITE_UNTAP"],
      "quality": 0.95,
      "playable_in_forge": true
    }
  ]
}
```

**executor-bindings.json** (hand-authored from the auto-emitted stub):

```json
{
  "schema": "arena.executor-bindings/1",
  "bindings": [
    {
      "combo_id": "csb-4131",
      "archetype": "TapForManaUntapLoop",
      "params": {
        "engine": "Selvala, Heart of the Wilds",
        "untapper": "Umbral Mantle",
        "activation_cost": "{G}",
        "untap_cost": "{3}",
        "yield_expr": "GREATEST_POWER_AMONG_OWN_CREATURES",
        "self_pump_per_cycle": 2,
        "profit_invariant": "yield - 4 > 0 within 3 cycles"
      },
      "payoffs": ["Finale of Devastation", "Polukranos, World Eater", "Lair of the Hydra"]
    },
    {
      "combo_id": "csb-7719",
      "archetype": "TapForManaUntapLoop",
      "params": {
        "engine": "Arbor Elf",
        "untapper": "Umbral Mantle",
        "activation_cost": "{0}",
        "untap_cost": "{3}",
        "yield_source": {"type": "BOUND_PERMANENT", "select": "Forest", "constraint": "TOTAL_MANA_YIELD_AT_LEAST 4"},
        "yield_expr": "MANA_FROM_YIELD_SOURCE",
        "self_pump_per_cycle": 0,
        "profit_invariant": "yield - 3 > 0"
      },
      "note": "v3.1: yield comes from a THIRD permanent (aura-stacked Forest), not the engine creature"
    },
    {
      "combo_id": "csb-4520",
      "archetype": "TapForManaUntapLoop",
      "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Staff of Domination",
                 "activation_cost": "{G}", "untap_cost": "{4}",
                 "yield_expr": "GREATEST_POWER_AMONG_OWN_CREATURES",
                 "self_pump_per_cycle": 0, "profit_invariant": "yield - 5 > 0"},
      "stages": ["MANA_LOOP", "DRAW_LOOP(Staff:{5}{T}+{1}=6/card)", "DEPLOY_WIN"],
      "entry_phase": "MAIN1",
      "note": "v3.1: stage-chained; enter precombat main so combat remains available for the win stage"
    }
  ],
  "unbound": ["csb-2210"]
}
```

**tutor-priorities.json:**

```json
{
  "schema": "arena.tutor-priorities/1",
  "weights": {
    "Umbral Mantle": 0.95,
    "Staff of Domination": 0.90,
    "Phyrexian Dreadnought": 0.55,
    "Craterhoof Behemoth": 0.50
  },
  "derivation": "max over included combos of quality * scarcity * completion_leverage"
}
```

*v3.3: derivation extends beyond combo pieces — the win plan contributes weights for route-required enablers and payoffs (haste statics, mass pump, X-spells), scaled by how many of the deck's routes require them. In the Selvala dossier, Concordant Crossroads and Craterhoof Behemoth carry high weights despite appearing in ~zero included combos.*

**Event log** (events/000042.jsonl, excerpts):

```json
{"t":"tutor_decision","turn":5,"seat":0,"source":"Green Sun's Zenith","chosen":"Temur Sabertooth","ranked":[{"c":"Temur Sabertooth","score":0.81,"why":"completes csb-9902 next turn"},{"c":"Reclamation Sage","score":0.44,"why":"stock_heuristic"}]}
{"t":"combo_state","turn":7,"seat":0,"combo":"csb-4131","distance":0,"ready":true,"blocked_by":[]}
{"t":"combo_shortcut","turn":7,"seat":0,"combo":"csb-4131","iterations_proven":3,"bounded_product":{"mana_G":1000000}}
{"t":"game_end","turn":7,"winner_seat":0,"win_condition":"combo","combo_id":"csb-4131"}
```

**v3.2 — combo/route telemetry taxonomy (normative).** The events above are the sketch; the full per-seat event set below is required output from `ComboAwareController` + LethalityPlanner. Design rule: **silence is never a valid record of a decision** — a ready combo that is not attempted MUST emit `combo_ignored`; a route the planner considers MUST emit `route_selected` or `route_rejected`. Absence of an event means "the situation never arose," and nothing else.

| Event | Required fields (beyond turn/seat/phase) | Emitted when |
|---|---|---|
| `combo_state` | combo, distance, per-piece location | on zone-change/turn tick (distance trace) |
| `combo_ready` | combo, window (sorcery-speed? combat available?), prereqs satisfied | tracker first reports distance 0 + prereqs OK this turn |
| `combo_ignored` | combo, reason: `patience_gate` \| `no_viable_route` \| `validation_failed` \| `threat_assessment` \| `mana_reserved` | ready at a decision point but no line entered |
| `line_entered` | combo, binding id, `attempted_via: binding \| generic_fallback`, entry phase | executor takes control |
| `line_step` | stage, iteration | per executor step (sampled after N repeats) |
| `line_aborted` | cause: `interaction` \| `validation` \| `engine_error`, piece lost | line ends without completing |
| `combo_shortcut` | iterations proven, bounded product | loop shortcut engages |
| `route_selected` | route, predicate values (projected alpha, table life, blocker buffer, haste source type, oracle guard) | planner commits to a win route |
| `route_rejected` | route, failed predicate + values | each route evaluated and not chosen |
| `combo_stalled` | binding, rejected routes, state hash, dump path | proven-infinite, no end state within N turns (Gate 3.6 input) |
| `tutor_decision` | source, chosen, full ranking with per-candidate why | any search effect resolves |
| `mulligan_decision` | keep/tuck, hand distance summary, reason | each mulligan checkpoint |
| `game_end` | winner seat, win_condition, combo_id?, route? | always — full win attribution |

**v3.2 — dual log sinks (human-tailable run log).** Every run writes two sinks from the *same* event stream: `events/NNNNNN.jsonl` per game (machine-of-record, drives all §7 reducers) and a single append-only `run.log` (human-readable, meant for `tail -f` while a batch runs). The run.log renderer subscribes to the identical events, so it structurally cannot drift from the JSONL. Lines are one-per-event, line-buffered (short atomic appends across worker processes), prefixed `[worker game turn seat]`, verbosity-tiered: default = game lifecycle + combo/route/tutor events + funnel summary per game end; `--log-verbose` adds line_step/combo_state ticks. Example:

```
[w2 g0417] game start  seats: selvala-b3(0) net-krenko(1) net-atraxa(2) net-muldrotha(3)  seed=42:417
[w2 g0417 t5 s0] tutor  Green Sun's Zenith -> Temur Sabertooth  (0.81 completes csb-9902 next turn)
[w2 g0417 t7 s0] READY  csb-4131 Selvala+Mantle  (sorcery window, prereqs ok)
[w2 g0417 t7 s0] line   csb-4131 via binding  entered MAIN1
[w2 g0417 t7 s0] loop   proven x3 -> {G}*1e6 shortcut
[w2 g0417 t7 s0] route  SPREAD_COMBAT rejected (alpha 34 < table 71+blockers) -> DRAW_DECK_THEN_OVERKILL selected
[w2 g0417 t7]    WIN    seat 0 selvala-b3  combo csb-4131 route DRAW_DECK_THEN_OVERKILL  (7 turns, 94s)
[w2 g0417]       funnel ready t7, attempted t7, hesitation 0, ignored 0
```

The §7(a) auto-narrative renderer is this same renderer run post-hoc at paragraph granularity — one implementation, two moments of use.

## 6. Combo layer — key classes

```java
// combo/ComboTracker.java — consumes SeatView only (never Game): see §9 W8
public final class ComboTracker {
    private final List<ComboDef> combos;              // from combos.json
    public TrackerSnapshot recompute(SeatView view) { // called on zone-change/turn events
        List<ComboStatus> out = new ArrayList<>();
        for (ComboDef c : combos) {
            int missing = 0; List<String> where = new ArrayList<>();
            for (ComboCard cc : c.cards()) {
                Presence p = view.locate(cc);         // BATTLEFIELD, HAND, COMMAND, GY(recursion), KNOWN_TOP, ABSENT
                if (!p.reachable(view.recursionAvailable())) missing++;
                where.add(cc.forgeName() + ":" + p);
            }
            boolean ready = missing == 0 && PrereqEvaluator.satisfiable(c, view);
            out.add(new ComboStatus(c.id(), missing, ready, where));
        }
        return new TrackerSnapshot(out);
    }
}
```

```java
// combo/PrereqEvaluator.java — supported prerequisite types are an explicit enum (§9 W4)
public enum PrereqType { MANA_AVAILABLE, CREATURE_POWER_AT_LEAST, PERMANENT_UNTAPPED,
                         SORCERY_SPEED, NO_SUMMONING_SICKNESS, UNPARSED }
// UNPARSED prerequisites do NOT mark a combo unready; they mark it "validation_gated":
// the line may only be attempted after forward-simulation succeeds (§6 execution step 1).
```

```java
// combo/executors/TapForManaUntapLoop.java — parameterized archetype
public final class TapForManaUntapLoop implements LineExecutor {
    private final Params p;
    @Override public SimResult validate(SimHandle sim) {          // on a GameCopier copy
        int floating = 0, yield0 = sim.greatestOwnPower();
        for (int i = 1; i <= 3; i++) {
            if (!sim.activate(p.engine(), p.activationCost())) return SimResult.blocked("engine");
            floating += sim.lastManaYield();
            if (!sim.activate(p.untapper(), p.untapCost()))    return SimResult.blocked("untapper");
            floating -= cmc(p.untapCost()) + cmc(p.activationCost());
            if (floating > 0) return SimResult.profitable(i);      // e.g. Selvala: X-4>0 by cycle 3
        }
        return SimResult.unprofitable();
    }
    @Override public Step next(LineState st, SeatView v) { /* scripted decision for controller */ }
}
```

**v3.1 — staged, phase-aware executors.** LineExecutor gains stages so multi-phase combos work: Staff of Domination is MANA_LOOP → DRAW_LOOP → DEPLOY_WIN, and lines declare an entry_phase (default MAIN1) so a line that ends in an alpha strike doesn't start after combat.

```java
public interface LineExecutor {
    List<Stage> stages();                       // each Stage has its own invariant + step script
    SimResult validate(SimHandle sim);          // validates the FULL chain, stage by stage
    Step next(LineState st, SeatView v);        // st tracks current stage + iteration count
    Phase entryPhase();                         // v3.1: gate line-mode entry
}
```

**v3.1 — LethalityPlanner (multiplayer win conversion).** Infinite mana is not a win; the plan must kill three opponents. Before committing to a payoff, the planner evaluates routes in order and picks the first that closes the game — otherwise it defers per the patience knob:

```java
public WinRoute choose(SeatView v, InfiniteResources res) {
    long tableLife = v.opponents().stream().mapToLong(Opp::life).sum();
    if (res.hasInfiniteDraw())                 return WinRoute.DRAW_DECK_THEN_OVERKILL; // Staff line
    long alpha = projectedAttack(v, res);      // e.g. Finale X=huge + Craterhoof pump, haste source
    if (alpha >= tableLife + blockersBuffer(v)) return WinRoute.SPREAD_COMBAT;          // one swing, split
    if (res.hasInfiniteUntap() && v.commanderOnField())
                                               return WinRoute.COMMANDER_DAMAGE_SEQUENCE; // 21 to one/turn
    return WinRoute.BANK_AND_HOLD;             // shortcut resources, pass with protection up
}
```

SPREAD_COMBAT must verify damage assignment across three players (haste availability — Concordant Crossroads/Craterhoof — and each opponent's blockers), not just a raw total. COMMANDER_DAMAGE_SEQUENCE acknowledges it kills one player per combat and expects to survive a table turn — the planner weighs that against BANK_AND_HOLD.

**v3.2 — WinRoute enum from the Win Routes spec.** The four routes above were a skeleton from one deck trace. The full enum is defined in docs/WIN-ROUTES.md, which specifies routes terminating in an engine-enforced end state and the per-deck classification rules that map a deck's `produces` features onto them (`LifeReachedZero`, `CommanderDamage`, `Poisoned`, `Milled`, `WinsGameSpellEffect` — the closed set verified in T0). Additional routes beyond the sketch: DIRECT_DAMAGE_LOOP, LIFELOSS_DRAIN, EXTRA_COMBATS (whole table in one turn — preferred over INFINITE_TURNS when available), INFINITE_TURNS (not shortcut-able; planner compresses to "lethal within K combats" with K bounded by table life), ORACLE_WIN (Thassa's Oracle / Lab Man class), FORCED_DRAW_OUT / MILL_OPPONENTS (mill alone doesn't kill — the empty-library *draw* does; usually costs a turn cycle), POISON_LOOP (10, not 40), STATIC_THRESHOLD (Simic Ascendancy class; win check at upkeep — must survive to it). The catalog also carries **guards** the planner must enforce: DRAW_DECK_THEN_OVERKILL without an oracle effect in deck is self-mill death (route rejected, not attempted); "Infinite lifegain" is a survivability resource, never a win-trigger; "Near-infinite X" features are bounded quantities, not proofs; any route spanning a turn cycle inherits wipe/removal risk priced via the patience knob.

```java
// ai/ComboAwareController.java — the seam (extends stock AI, inert without artifacts)
public class ComboAwareController extends PlayerControllerAi {
    private final DeckArtifacts art; private final ComboTracker tracker; private LineState line;

    @Override public SpellAbility getAbilityToPlay(Card host, List<SpellAbility> usable, ...) {
        if (line != null) return line.executor().next(line, seatView()).toEngine(usable);
        TrackerSnapshot snap = tracker.recompute(seatView());
        Optional<ComboStatus> ready = snap.bestReady(art.qualityOrder());
        if (ready.isPresent() && patienceGate(ready.get())) {
            LineExecutor ex = art.executorFor(ready.get().id());
            if (ex != null && ex.validate(EngineFacade.copyForSim(game())).isProfitable()) {
                line = LineState.begin(ready.get(), ex);
                return line.executor().next(line, seatView()).toEngine(usable);
            }
        }
        return super.getAbilityToPlay(host, usable, ...);          // stock AI fallback, always
    }
    // similar targeted overrides: chooseSingleEntityForEffect (tutors → TutorRanker),
    // chooseCardsToDiscardFrom (protect last copies), mulligan (distance-aware keep).
}
```

```java
// tutor/TutorRanker.java
public List<Ranked<Card>> rank(List<Card> legal, SeatView v, TrackerSnapshot snap, Weights w) {
    return legal.stream().map(c -> {
        double combo = snap.completionLeverage(c, v);   // finishes line now > next turn > closer
        double stock = stockHeuristicScore(c);          // delegate to ChangeZoneAi valuation
        String why = combo > 0 ? snap.explain(c) : "stock_heuristic";
        return new Ranked<>(c, combo > 0 ? 0.5 + 0.5 * combo : 0.5 * stockNorm(stock), why);
    }).sorted(byScoreDesc()).toList();                  // full ranking logged, top pick returned
}
```

**Generic payoff fallback** (new, addresses executor-coverage gap §9 W1): when a shortcut proves infinite mana but no scripted payoff line exists, the controller sets a large floating pool and hands control back to stock AI with a one-turn "spend it" hint (stock heuristics reliably cast Finale/X-spells with 10^6 available). Unbound combos thus still convert wins, just less crisply — and the funnel telemetry (`attempted_via: generic_fallback`) tells you which bindings are worth authoring next.

## 7. Analytics: statistical, play-pattern, qualitative

**Statistical** (per deck / per pod config): win rate with Wilson 95% CI; TrueSkill rating (4-player FFA); win-turn distribution; win-condition breakdown; pairwise win matrix; seat-position effect (win rate by seat, before/after rotation correction); mulligan distribution; timeout/crash rates. A/B harness: same seeds/rotation with one flag flipped (e.g., comboAware on/off) → paired-difference reporting.

**Play-pattern fingerprints** (per deck, per game, aggregated):

- **Development:** commander cast turn; lands played vs. turns (missed-drop rate); mana spent / mana available per turn (efficiency curve); total own board power/toughness by turn.
- **Velocity:** cards drawn per turn beyond the draw step; tutors resolved and their targets' categories; average hand size.
- **Interaction:** removal/counters cast (count, timing, targets by seat); board wipes cast/suffered; times targeted by each opponent (threat-received index — a proxy for how the table perceives the deck).
- **Combo (v3.2 extended funnel):** in-99 → assembled → **ready** → attempted → resolved → **converted** → won, computed directly from the §5 taxonomy; each stage ratio localizes a failure class (low attempted/ready ⇒ patience gate or planner; low converted/resolved ⇒ routes/DEPLOY logic; low won/converted ⇒ protection/stack play). Derived metrics: **hesitation** (turns between first `combo_ready` and `line_entered`), **ready-but-never-attempted rate** (games with `combo_ready` and zero `line_entered`, broken down by `combo_ignored` reason), route-rejection distribution (which predicates fail most, from `route_rejected`), plus distance-over-time traces, shortcut usage, and aborts by cause.
- **Outcome texture:** life totals over time; first-blood / first-eliminated rates; eliminations dealt.

All computed from the JSONL streams by report/ reducers (report.py reference implementation; keep reducers pure functions over event lists so notebooks can reuse them).

**Qualitative:** (a) auto-narratives — a template renderer that turns a game's event stream into a half-page story ("Seat 2 (Krenko) opened fastest… Seat 0 assembled Selvala+Mantle on turn 7 behind Heroic Intervention…") for skim-reading hundreds of games; (b) key-moment extraction — life swings > N, board wipes, combo attempts, elimination turns, flagged with log offsets for jump-to-debug; (c) loss autopsies — for a target deck, cluster its losses by proximate cause (combo interrupted / never assembled / raced / wiped) with example game ids; (d) decision audits — stratified sample of 100 tutor/mulligan decisions with the ranker's stated reasons, for human grading (the ≥80% correctness gate).

## 8. Test suite (write alongside each module)

**Unit tests** (JUnit 5; names indicate the assertion): *[T0 correction: repo convention is TestNG — see T0-VERIFICATION.md §2.4]*

- **NameMapperTest:** oracle→Forge for split cards, DFCs, adventures, apostrophes/accents; unmapped names reported not dropped.
- **DeckHashTest:** order-insensitive, count-sensitive, commander-inclusive.
- **DeckLintTest:** 99+1 count, singleton, color identity, banlist version pinning.
- **PrereqEvaluatorTest:** each supported enum type; UNPARSED ⇒ validation-gated, never auto-ready.
- **ComboDistanceTest:** command zone counts as reachable; graveyard reachable only with recursion flag; known-top counts; distance monotonicity as pieces arrive.
- **SelvalaMantleMathTest:** net per cycle = yield − 4; with self_pump_per_cycle=2 and starting power 4, profitable by cycle ≤3; starting power 2 requires 2 floated mana.
- **LoopShortcutTest:** exactly 3 proven iterations then bounded product; no shortcut when validation fails.
- **TutorRankerTest:** line-completing target outranks generic value; tutor restrictions respected (creature-only lists never contain artifacts); empty artifacts ⇒ ordering identical to stock heuristic (inertness).
- **HiddenInfoTest:** SeatView exposes no library order or opponents' hands; ArchUnit rule: only engine/ may import forge.game.*; combo/+tutor/ may import only engine.SeatView.
- **SeedDeterminismTest** (integration): same seed ⇒ byte-identical event-log hash, twice.
- **RotationTest:** Latin-square assigns each deck to each seat equally over any 4k games.
- **TimeoutDrawTest:** turn-cap game recorded as timeout_draw with limiting factor.
- **SpellbookClientContractTest:** recorded HTTP fixtures; schema-version mismatch fails loudly; cache hit produces zero HTTP calls.
- **PreflightGoldfishTest:** deck with a known-unimplemented card fails Gate 2 with that card named.

**Golden scenario tests** (scripted game states via dev-mode state setup; the executor regression net):

- **SelvalaMantleWinsThisTurn:** Selvala + Mantle + 4-power creature on battlefield, 1 untapped Forest ⇒ assert win_condition=combo this turn.
- **SelvalaStaffNeedsPowerSix:** with only a 5-power creature ⇒ Staff line not attempted (validation catches net 0).
- **LineAbortsWhenPieceRemoved:** destroy Mantle mid-line ⇒ graceful fallback, no crash, line_aborted logged.
- **GenericFallbackSpendsInfiniteMana:** unbound-combo deck with proven infinite mana ⇒ game still ends by X-spell within 2 turns.

**v3.1 additions:**

- **MultiplayerLethalityTest:** infinite mana, Finale + Craterhoof available, but opponents' summed life + blockers exceed projected alpha ⇒ planner returns DRAW_DECK_THEN_OVERKILL or BANK_AND_HOLD, never a losing SPREAD_COMBAT.
- **StagedExecutorTest:** Staff line validates all three stages; DRAW_LOOP costs exactly 6/card; line entered in MAIN1 (assert combat still available at DEPLOY_WIN).
- **ThirdPermanentYieldTest:** Arbor Elf + Mantle + Forest with 4+ total aura yield ⇒ profitable (net = yield−3); with plain Forest ⇒ validation rejects (net −2), line never attempted.
- **BindingGenerationVerificationTest:** recorded LLM fixture with a plausible but wrong binding (e.g., Staff untap_cost:{3}) ⇒ sim verification fails, repair retry runs, on second failure the combo lands detection-only; a hallucinated binding can never reach executable.
- **BindingLibraryCacheTest:** second deck containing an already-bound combo ⇒ zero API calls, library hit, identical binding bytes.

**v3.2 additions:**

- **RouteCoverageTest:** deck whose combos produce only unmapped features ⇒ Gate 3 emits `unroutable` flag + blocking warning; fully-mapped deck ⇒ every included combo lists ≥1 reachable route.
- **OracleGuardTest:** infinite draw proven, no Thassa's/Lab Man-class effect in the 99 ⇒ DRAW_DECK_THEN_OVERKILL rejected by the planner (never attempted), BANK_AND_HOLD or another route chosen; with Thassa's Oracle present ⇒ ORACLE_WIN selected and game ends `WinsGameSpellEffect`.
- **StallAutopsyTest:** forced stall (binding whose payoffs were removed from the deck) ⇒ `combo_stalled` logged with rejected-route trace, state dump written, deduped by state hash; batch mode makes zero network calls (autopsy consumes the dumps post-run, recorded-fixture LLM).
- **TelemetryCompletenessTest:** scripted game where a combo is ready and deliberately not fired ⇒ exactly one `combo_ignored` with a valid reason enum per decision point; every LethalityPlanner evaluation emits `route_selected` or `route_rejected` with predicate values; a game with no combo activity emits none of these (no phantom events).
- **PilotQualityFloorsTest:** canary fixture where a deck's conversion-when-ready falls below the floor ⇒ canary report marks the deck `pilot_invalid` naming the failing metric, and the batch runner excludes it from comparative stats while still recording telemetry; fixture above the floor ⇒ deck admitted.

Every phase's definition-of-done = its exit criterion demonstrated by a committed script/test, not narrative.

## 9. Weakness remediations (v2 §9 → v3 design responses)

| # | Weakness (v2) | v3 design response |
|---|---|---|
| W1 | Executor authoring is a manual bottleneck | v3.1: Gate 3.5 LLM binding generation — Claude API parameterizes archetype bindings per new combo, gated by schema/lint/sandbox-sim verification (engine is the oracle; hallucinations cannot reach executable); global per-combo binding library makes cost O(distinct combos), not O(decks); generic infinite-resource fallback covers failures; human queue only for novel archetypes (which remain hand-written Java). |
| W2 | Unverified Forge internals | T0 verification doc as a hard gate; EngineFacade as the single import point for Forge internals, enforced by ArchUnit — refactors/rebases touch one class. |
| W3 | Opponent realism ceiling | Report relative deltas under paired seeds only; designated "police" seat (Cautious profile + simulation AI); goldfish seat isolates raw speed; golden LineAbortsWhenPieceRemoved proves interaction is at least mechanically respected; document that absolute win rates ≠ human-table rates. |
| W4 | Spellbook prerequisite parsing gaps | Explicit PrereqType enum; anything unparsed ⇒ validation-gated (attempt only after forward-sim proves the line), never silently ready or silently dead; prereq_unparsed telemetry drives parser iteration. |
| W5 | Third-party API dependency | Deck-hash cache + raw snapshot per deck; schema-versioned client with recorded-fixture contract tests; batches read artifacts only; snapshot date in run manifest ⇒ old experiments reproducible even if the API changes. |
| W6 | Performance unknowns | Phase 0 measures games/hour/core before commitments; loop shortcut mandatory; per-decision time caps on simulation-AI seats; process pool sizing from canary timings; JVM flags documented in scripts/batch.sh (-Xmx2g, headless). |
| W7 | GPL-3.0 / fan content | Tool remains a non-commercial research fork; if ever distributed, distribute source under GPL-3.0; no card images required for headless runs. |
| W8 | Hidden-information leaks | SeatView read-model is the only game-state surface combo/, tutor/, and analytics may touch; it structurally cannot express library order or hidden hands; ArchUnit + HiddenInfoTest enforce it. |

New prep-step protections added in v3 beyond the v2 list: legality lint with pinned banlist (W-new: silent banlist drift), goldfish-compile preflight (W-new: broken card scripts poisoning batches), canary gate (W-new: misconfiguration discovered 10k games late), and run manifests (W-new: unreproducible or mislabeled experiments).

## 10. Roadmap (v3)

| Phase | Scope | Exit criterion | Est. |
|---|---|---|---|
| 0 | Fork builds; stock 4p commander sim; T0 verification doc; games/hr measured | 100 stock games; T0 committed; perf baseline | 3–5 days |
| 1 | Harness: bootstrap, EngineFacade (+ GameState sandbox loader, v3.3), runner, seeds, rotation, limits, JSONL + run.log sinks, worker pool + DeterminismTest, RotationTest, TimeoutDrawTest | 1k-game run in an afternoon, <2% timeout/crash, seed replay (10k remains supported) | 2–3 wks |
| 2 | Ingest + preflight gates 0–2 + canary script; assignable AI (profiles, sim toggle, goldfish, controller injection) | 4 target decks pass all gates; per-seat behavior differs in logs | 1.5 wks |
| 3 | Prep pipeline gates 3+5: Spellbook client, cache, artifacts, schemas; ComboTracker detection-only + SeatView | Artifacts for all decks; distance traces in every log; inertness test green | 1.5–2 wks |
| 3.5 | Bindgen: Claude API client, prompt assembly, static gates, sandbox-sim verifier, global binding library, repair loop | BindingGenerationVerificationTest + BindingLibraryCacheTest green; Selvala's combos auto-bound and sim-verified | 1–1.5 wks |
| 3.6 | Stall autopsy: `combo_stalled` telemetry, state dumps, dedup, post-run repair pass reusing 3.5's verifier; Gate 3 route-coverage report | StallAutopsyTest + RouteCoverageTest green; a seeded stall round-trips to a repaired, sim-verified binding | 0.5–1 wk |
| 4 | Executor archetypes in Java (staged LineExecutor, catalog-driven LethalityPlanner, yield-source support), line mode, shortcut, generic fallback + golden tests | All golden scenarios incl. v3.1/v3.2 pass; Selvala wins via Mantle/Staff in live 4-player pods | 3–5 wks |
| 5 | TutorRanker, mulligan/discard integration; full analytics suite incl. narratives & autopsies; A/B evaluation | Measured lift w/ CIs; tutor audit ≥80%; analytics report generated end-to-end | 2.5–3 wks |

~4–5 months solo; Phase 4 still the riskiest estimate. Note the ordering dependency: Phase 3.5's sim verifier needs at least one working archetype executor, so implement TapForManaUntapLoop (Phase 4's first deliverable) before wiring the verification loop, then parallelize.

The Win Routes spec (route definitions + classification rules) is a documentation artifact with no code dependencies — seeded immediately post-T0 (2026-07-15, this repo) so Phase 4's planner and executor contracts are designed against the full route set rather than grown per trace. Feature classification itself runs per deck at preflight (Gate 3, cache-first); the spec and mapping library are maintained thereafter by the Gate 3.5/3.6 feedback loops. No global combo/feature sweeps are part of any workflow.

**v3.3 — `arena prep` landing plan.** The dossier compiler ships twice: **v1 at the end of Phase 3** (ingest→lint→implementability→combos→route coverage→tutor weights; everything except execution proof) and **v2 during Phase 4** once TapForManaUntapLoop exists (adds Gate 3.5 sim verification + the dossier goldfish). This keeps the ordering dependency explicit: the sandbox verifier and goldfish need one working executor, but every detection-side artifact is testable earlier via prep v1.

## 11. Handoff notes for Claude Code

- **T0 first, half a day, non-negotiable.** Grep-and-read: SimulateMatch, PlayerControllerAi, AiController, ChangeZoneAi, simulation package, .dck parser, event bus. Write docs/T0-VERIFICATION.md correcting §1; update the provisional names in this document's code sketches before implementing them.
- **Schemas first** (schemas/*.schema.json), then emitters, then consumers. Artifact schema versions are load-bearing.
- All new code in forge-arena/. Upstream edits require `// ARENA-PATCH:` + UPSTREAM-PATCHES.md entry. Candidate upstream PRs: controller injection hook, loop-shortcut/bulk-repeat utility, extra event visibility.
- PR-sized tasks, each landing with its tests from §8. CI = scripts/smoke.sh (build + unit + 25-game canary).
- Enforced invariants to keep green at all times: SeedDeterminismTest, HiddenInfoTest/ArchUnit rules, inertness (TutorRankerTest empty-artifact case).
- No network in the game loop; Spellbook client only in prep/, Anthropic API client only in bindgen/, both prep-time only, proper user agent, cache-first, keys via environment variables.
- Bindgen outputs are untrusted until verified: schema → lint → sandbox-sim, in that order; only sim-passed bindings get executable. Store request hash, model id, and verbatim response with every library entry; run manifests pin the library version.
- When in doubt between fidelity to this document and what the actual Forge source supports: **the source wins** — update this document in the same PR.
