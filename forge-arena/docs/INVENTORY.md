# forge-arena INVENTORY — code, seams, scripts, artifacts

*Generated 2026-08-17 from the repo itself, refreshed 2026-09-04 (branch
`arena`, 439 commits ahead of upstream base `0eec0a16d0a`, 2026-07-15; the
2026-09-04 interactive-module batch is committed but its Maven gate has not
run yet). Companion documents:
[UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) (how to take upstream updates safely),
[INTERACTIVE-ARENA.md](INTERACTIVE-ARENA.md) (seam architecture + field
notes), `packaging/README.md` (user-facing feature docs, ships with the
package), `packaging/PATCH-NOTES.md` (release history), `../BUILDING.md`
(build + tarball recipe).*

---

## 1. Upstream divergence — every file we changed outside `forge-arena/`

The original "no parent-module patches" rule was deliberately dropped
(first for the vanished-commander engine fix, 2026-08-17). The full delta
outside `forge-arena/` (2026-09-04 recount: `git diff --name-status
0eec0a16d0a..HEAD -- . ':(exclude)forge-arena'`) is **32 files**: 12 modified
(9 upstream Java files, 301 insertions / 22 deletions; plus `match.xml`, root
`pom.xml`, root `.gitignore`), 9 new code files parked in parent modules
(1b), 10 `runs/*.json` batch templates + the historical
`UPSTREAM-PATCHES.md` at root.

### 1a. MODIFIED upstream files (merge-conflict surface — see UPSTREAM-SYNC.md)

| File | Δ | Kind | Why | Marker | Guarding test |
|---|---|---|---|---|---|
| `forge-ai/.../ComputerUtil.java` | ~+30 −9 | **BEHAVIORAL** | `handlePlayingSpellAbility`'s failed-payment path: (a) spells roll back to origin zone (upstream FIXME orphaned commanders); (b) ACTIVATED abilities refund-in-place — rollbackAbility's zone surgery resolves a GRANTED ability's card-state to the GRANTOR and vanished the host (Sanctum Weaver + Gauntlets, 2026-08-19). | ✓ | `UnaffordableCastRollbackTest`, `GrantedAbilityRollbackTest` |
| `forge-ai/.../AiCostDecision.java` | ~+120 | Additive hooks | `visit(CostTapType)` → `TapCostPreference`; `visit(CostSacrifice)` → `SacCostPreference` (+ `Amount$ All` consent); `visit(CostExile/CostDiscard/CostReturn/CostPutCardToLib)` → one shared `PaymentPickPreference` consult (wave-2: which card a pitch/return cost eats), all with vet-else-stock. No preference → stock paths byte-identical. | ✓ | `TapSymmetryBreakTest`, `SacrificeSeatChoiceTest`, `PaymentPickPreferenceTest` |
| `forge-ai/.../ComputerUtilMana.java` | +15 | **BEHAVIORAL** | `canPayShardWithSpellAbility` vetted candidates by the ROOT mana part only — condition-forked scripts (Gemstone Caverns' luck-counter Any-branch; upstream TODO in the card file) were invisible at payment time, so colored shards went unpaid while explicit floats worked (six live incidents). Now uses the first chain part whose conditions are met; root fallback preserves old behavior when none are. | ✓ | `PainSourcePaymentTest` |
| `forge-game/.../MagicStack.java` | ~+45 | Diagnostic only | `[arena] FIZZLE:`/`DECLINED-TRIGGER:` stderr lines in the fizzle branch — targets snapshotted BEFORE the fizzle-check strips them (the old print said "(none set)" for stripped targets, mislabeling legitimate dead-target fizzles). No behavior change. | ✓ | `SiblingTriggerBatchTest` |
| `forge-core/.../MyRandom.java` | +36 −6 | **BEHAVIORAL** | Seedable RNG (`setSeed`) for reproducible headless batches (Project 1). | ✓ (ARENA-PATCH) | `SeedDeterminismTest` |
| `forge-game/.../Combat.java` | +6 −1 | Defensive fix | `getAttackers` snapshot vs concurrent modification crash. Upstream-worthy. | ✓ | (crash class) |
| `forge-game/.../StaticAbilityTurnPhaseReversed.java` | +34 −7 | Defensive fix | Crash guard + value-based pair choice. Upstream-worthy. | ✓ | PR-49 tests |
| `forge-gui-desktop/.../EDocID.java` | +2 | GUI wiring | Registers the Advisor + AI-panel dock tabs. | **unmarked** | (compile) |
| `forge-gui-desktop/.../CMatchUI.java` | +6 | GUI wiring | Instantiates the two arena dock tabs. | **unmarked** | (compile) |
| `forge-gui/res/defaults/match.xml` | — | GUI layout | Pilot-tuned default match layout (the only `res/` divergence). | — | (none) |

### 1b. NEW files in parent modules (zero merge-conflict surface)

| File | Module | Why it lives there |
|---|---|---|
| `forge-ai/.../TapCostPreference.java` | forge-ai | The AiCostDecision hook interface must be visible to forge-ai. |
| `forge-ai/.../SacCostPreference.java` | forge-ai | Sacrifice-payment hook interface (same pattern/reason). |
| `forge-ai/.../PaymentPickPreference.java` | forge-ai | One hook interface for exile/discard/return/put-to-library payments (wave-2). |
| `forge-gui-desktop/.../forge/arena/interactive/AiControlFile.java` | gui-desktop | AI-panel file protocol (per-seat model/effort dials, ELO line). Moved here 2026-08-12 so the desktop reactor builds it. `advisorAttached()` (2026-08-31) distinguishes no-advisor games from a paused advisor. |
| `forge-gui-desktop/.../forge/arena/interactive/AdvisorLogTail.java` | gui-desktop | Advisor tab's log tailer. |
| `forge-gui-desktop/.../controllers/CAiControl.java` + `views/VAiControl.java` | gui-desktop | AI dock tab (steppers, telemetry, ELO). |
| `forge-gui-desktop/.../controllers/CAdvisor.java` + `views/VAdvisor.java` | gui-desktop | Advisor dock tab (+ three-state pause button: OFF-not-attached / ON / PAUSED, 2026-08-31). |

Nine files in eight rows (the two dock tabs are a controller + view pair each).

### 1c. ArchUnit boundary
`src/test/java/forge/arena/ArchitectureTest.java` enforces two rules. (1) No
class under `forge.arena..` OUTSIDE `forge.arena.engine..` and
`forge.arena.interactive..` may depend on `forge.game..`, `forge.ai..`,
`forge.deck..`, `forge.item..` or `forge.player..` — `EngineFacade` is the
headless harness's single import point for Forge internals, and
`forge.arena.interactive` is the sanctioned second seam (its
PlayerController/LobbyPlayer implementations cannot route through the
facade). (2) `forge.arena.combo..` may touch nothing in `forge.arena.engine`
except `SeatView` (and its nested types) — the W8 read model. The rule says
nothing about GUI imports: `bootstrap/` and `interactive/` import
`forge-gui`/`forge-gui-desktop` classes freely.

---

## 2. Decision-surface matrix — who decides what

`MailboxController extends PlayerControllerAi`; every override times out /
falls back to stock, so a dead brain never hangs a game.

### Seat-owned (routed over the mailbox)

| Surface | decisionType | Since |
|---|---|---|
| Own main-phase play choice | `CAST_SPELL` | v1 |
| Instant-speed response (opponent object on stack) | `REACT` | v2 |
| Tactical windows (combat steps + end step, empty stack) | `REACT` | v3 (#13) |
| Own-trigger response windows | `REACT` | v4 (#21) |
| Mulligans | `MULLIGAN` | v1 |
| Attack/block declaration (whole-assignment validated, #22) | `DECLARE_ATTACKERS/BLOCKERS` | v1 |
| Copy/choose-a-permanent | `CHOOSE_ENTITY/ENTITIES` | v2 |
| Modal/charm mode choice (modes honored at cast, 08-17) | `CHOOSE_MODE` | v2 |
| Tutor/search fetch (incl. multi-card Cultivate-class) | `CHOOSE_CARD` / `CHOOSE_CARDS` | v2 / 08-17 |
| Spell + ability targeting, single-target (incl. **stack items** — counters target the spell, not the card) | `CHOOSE_ENTITY` | #14/14b/14c, hardened 08-17 |
| **Trigger targeting** (own triggered abilities aimed by seat) | `CHOOSE_ENTITY` | 08-17 |
| **Optional-trigger yes/no** ("you may [pay X to]…", Rings-class) | `CONFIRM` (mode TRIGGER) | 08-17 |
| Pay-or-else (Rhystic/Sentinel taxes, counter-unless, pay-the-difference tutors) | `PAY_UNLESS` | 08-17 |
| Yes/no confirms (cast-while-searching, optional effects) | `CONFIRM` | 08-17 |
| X announcement on the cast path | `CHOOSE_NUMBER` | #15b-correction |
| Cost-reduction numbers | `CHOOSE_NUMBER` | 08-17 |
| Discard selection (rummage/forced, visible cards only) | `CHOOSE_CARDS` | 08-17 |
| Split/adventure/MDFC face pick (finite lists) | `CHOOSE_CARD` | 08-17 |
| Card state/side pick | `CHOOSE_CARD` | 08-17 |
| Generic choose-N-cards-for-effect | `CHOOSE_CARDS` | 08-17 |
| Symmetry-break offers (tap own Winter-Orb-class piece, pre-selected payment) | option class in `REACT`/window | 08-17 |
| **Cast-from-effect offers** (Isochron Scepter copies, Discover, "may cast it without paying"-class) | `CONFIRM` (mode PLAY_FROM_EFFECT) + seat pre-aims the chain's targets | 08-19 |
| **Sacrifice by effect** (edicts, Innocent-Blood symmetrical, Balance; also `choosePermanentsToDestroy`) | `CHOOSE_ENTITIES` | 08-24 |
| **Sacrifice cost payment** (outlet activations, additional-cost casts — which card pays) | `CHOOSE_ENTITIES` via `SacCostPreference` hook | 08-24 |
| **Pitch-cost payments** (Force-of-Will exile, discard/return/put-to-library costs) | `CHOOSE_ENTITIES` via `PaymentPickPreference` hook — DEFAULT-DENY outside an executing cast (planning scans get stock, silently) | 08-28/31 |
| **Cleanup discard to hand size; London mulligan bottoming** | `CHOOSE_CARDS` | 08-28 |
| **Scry / surveil / library ORDER (first = top) / clash top-or-bottom** | `CHOOSE_CARDS` / `CONFIRM` | 08-28 |
| **Generic numbers + non-mana announces** (Wheel-of-Misfortune class, Multikicker) | `CHOOSE_NUMBER` / `CHOOSE_MODE` indices | 08-28 |
| **Retargeting spells** (Deflecting Swat class; single-target changes) | `CHOOSE_ENTITY` via `chooseNewTargetsFor` | 08-28 |
| **Optional costs (Buyback/Kicker)** | cast-window `[+ cost]` VARIANTS (no window; affordability-vetted at offer) | 08-31 |
| **Keyword pay-N-times costs (Multikicker-class)** | `CHOOSE_NUMBER` via `chooseNumberForKeywordCost` (execution-time, affordable cap) | 08-31 |
| **Protection type, votes, pile splits** | `CHOOSE_MODE` indices | 08-28 |
| **Creature-or-player choices** (mixed Card+Player lists, sequential ids) | `CHOOSE_ENTITY`/`ENTITIES` | 08-28 |
| **Trigger ORDERING** — own simultaneous triggers with 2+ distinct descriptions (grouped by host + text; identical triggers never ask); answer = resolution order, first listed resolves first | `CHOOSE_MODE` (`state.purpose = "TRIGGER_ORDER"`, `min = max = groups`) via `orderSimultaneousSa` | 09-04 (gate pending) |
| **Colour choice** outside a payment context, 2+ legal colours ("colorless" offered where allowed) | `CHOOSE_MODE` (`state.purpose = "COLOR"`, `min = max = 1`) via `chooseColor` / `chooseColorAllowColorless` | 09-04 (gate pending) |

### Still stock (deliberate, with rationale)

| Surface | Why stock |
|---|---|
| Multi-target spells (max targets > 1) | Falls back; never worse than status quo. Rare at stakes so far. |
| "Name a card" from the whole DB (`chooseSingleCardFace` predicate overload) | Unbounded option list — the mailbox never ships one. |
| `chooseSingleReplacementEffect` | Fires on every replaced event — window-spam risk; needs frequency data first (wave-2 deferral). |
| Routine tap-cost payment picks | `TapCostPreference` stays symmetry-armed only — a live exchange sits inside the mana-payment inner loop (pacing risk; wave-2 deferral). |
| Combat damage assignment/ordering | `assignCombatDamage` only counts multi-blocker cases (`stockSurface`) and defers; stock was never broken here. |
| Mana payment source selection | `TapCostPreference` covers the symmetry case; full auto-tap reimplementation deferred (#15). Known quirk: `canPayCost` can be conservative (Ancient Tomb refusal, note 41) — the guard refusal returns the window and brains adapt by floating first. |
| Colour choice INSIDE a payment context (`inPaymentContext`: the payer's planning scans and tap-for-this-cost picks), or with one legal colour | The payer already targets its colour; a window there would be a phantom (wave-3 F2 lesson). Human seat: the advisor's mono-colour autopick (v2 QoL). |
| Convoke/improvise payment, spell-for-effect choice | `stockSurface` counters only (BL-04: open by evidence). |
| `chooseCardsToDiscardFrom` when candidates aren't visible to the chooser | Hidden-info discipline. |

---

## 3. `forge-arena` Java map (module `forge.arena.*`)

| Package | Project | Contents |
|---|---|---|
| `interactive/` | 2 | The seam, 11 classes: `MailboxProtocol` (file bus — one instance per seat directory, constructor sweeps stale `resp-*`/`*.tmp` from the outbox, heartbeat age check), `MailboxController` (all overrides above, incl. 09-04's `orderSimultaneousSa` and `chooseColor*`; `gameIdFor` = millis-pid-serial; `controllerBoard` on controlled requests), `MailboxLobbyPlayer` (controller injection; `createMindSlaveController` hands the slave to the master's bus with the master `Player`), `GuiPilotMatch` (launcher; `DECKS` = urza, giada, purphoros, selvala; `buildRoster` / `verifyRoster` / `slugOf` are static and GUI-free; roster override via `arena.seat.decks`; writes `mailbox/launch-status.json`), `DeckLoadProbe` (real-loader playability probe + `--resolve` CLI the ingester calls), `ObserverSnapshot` (public event-bus state, written on every event whose serialized state changed; `WRITES` counter), `GameResultSpool` (ELO result writer; carries `gameId`, `stockDecisions`, card-conservation counts), `AdvisorControllerHuman`/`AdvisorFeed`/`AdvisorLobbyPlayer` (seat-0 shadow feed), `SeatAvatars` (cosmetic color-matched seat portraits from deck pip mix; resource `src/main/resources/forge/arena/avatar-colors.json`, 126 heads; fail-safe, fresh-Random — never touches game determinism; assignment logged as `[arena] seat avatars:` in gui.out). |
| `bootstrap/` | shared | `ArenaBootstrap` (headless/GUI init, RNG seeding). |
| `engine/` | 1 (+SeatView shared) | 30 classes (`ls src/main/java/forge/arena/engine`, 2026-09-04). Facade and read model: `EngineFacade`, `GameSimHandle`, `SeatView`/`SeatViews` (hidden-info-safe read model — the fairness boundary, ArchUnit-guarded), `SeatSpec`, `ArenaGameState`, `ArenaGameResult`, `ArenaLimits`, `EngineCrashException`, `GameAware`, `GameEventBridge`, `CardCatalog`, `CardInfo`, `ComboDetectionBridge`, `AbilityResolver`, `BindingVerifier`, `ComboAwareLobbyPlayer`, `GoldfishLobbyPlayer`, `ProgramFixtureProbe`. Program runners: `ProgramRunner`, `EngineProgramRunner`, `BounceRecurRunner`, `CastBounceRunner`, `CastRecurRunner`, `DreadnoughtWindowRunner`, `ManaLoopRunner`, `SelvalaManaLoopRunner`, `PairingRunner`, `SeedbornEngineRunner`, `TransformSacEngineRunner`. |
| `harness/`, `combo/`, `prep/`, `bindgen/`, `report/` | 1 | Headless batch stack (BatchMain, combo programs, dossier prep, pilot floors). Not shipped in forge-light-llm. |

Tests: `src/test/java/forge/arena/**` — 329 `@Test` annotations as of 2026-09-04 (grep count; data providers expand them; the surefire summary is the count that gates), including the
seam regression suite (`*ReachesMailboxTest`, `GuardedCastTargetIntegrityTest`,
`TapSymmetryBreakTest`, `UnaffordableCastRollbackTest`, `CounterspellReachesTargetTest`)
and the 2026-09-04 additions `TriggerOrderWindowTest`, `ColorChoiceWindowTest`,
`StaleOutboxSweepTest`, `ObserverSnapshotWriteTest` (plus `MindSlaveRoutingTest`'s
`controllerBoard` assertion and `ProtocolFieldsTest`'s distinct-gameId check) —
committed in 2bc78d92188 with the standard gate still to run. The TestNG group
`extended` is excluded by default (`arena.excluded.groups`; BUILDING.md) and is
empty as of that commit.
Test-harness pattern: `ArenaBootstrap.initialize` + cards placed by zone +
`MailboxLobbyPlayer` + temp mailbox + a test-thread brain + `PhaseHandler.mainLoopStep`.
**Probe-regex rule:** match option ids only via `\{"id":(\d+),"label":"…` —
matching anywhere in the body hits card ids in `state.battlefield` (bit twice).

## 4. Python runtime map (`runner/`)

| File | Role |
|---|---|
| `seatd/runner.py` | Seat daemon: window handling, memo/autopass/hold fastpaths, executable plans, deviation + turn-intent capture, effort routing (resourceless/own-trigger/free-confirm → low), **cycle replay** (`repeat_cycle`; a punt is never a replayable step, rebinding needs label + type + cost), transport-event emission (stamped with `gameId`), the two-file decision log (`game.jsonl` + `game-<gameId>.jsonl`), punt-at-once when the request file has vanished. |
| `seatd/brain.py` | Resident model session: `claude -p --resume` with `--disallowedTools "*"`, MCP disabled, `--setting-sources ""` (BL-24), cwd = repo/package root; the in-flight child is tracked so `kill_child()` can end it; `extract_json` walks braces with `raw_decode`; per-call effort override, wedge detection → fresh-session rejoin, spend/usage accounting. |
| `seatd/backends.py` | OpenRouter (`or/<vendor>/<model>`, `OPENROUTER_API_KEY`) + OpenAI-compatible (`oai/<model>`, `ARENA_OAI_BASE_URL`) transports; per-seat cost rails (`ARENA_MAX_SEAT_COST_USD` default $5, 250-call cap), auth/model latches, mid-game Claude↔backend re-dial with session survival. |
| `seatd/rules.py` | Prompt builder, per-type answer hints, validator (strips extra keys; a missing `defender` is filled in when exactly one is legal), shape-aware safe defaults (the punt table the brief states and `test_brief_contract.py` pins), plan-step binding. |
| `seatd/protocol.py` | Mailbox file I/O. |
| `seatd/seat-brief.md` / `advisor-brief.md` | The standing briefs (rules 1–6 + tuning bullets; counting-not-valuation discipline). |
| `seat_runner.py` / `run_table.sh` | Entry point + supervisor (restart loop, crash-loop damper for backend seats, preflight; roster rule: `ARENA_SEAT_DECKS` or Urza/Giada/Purphoros/Selvala, human game = first three roster decks that are not `ARENA_HUMAN_DECK`). `seat_runner.py` installs SIGTERM/SIGINT handlers that kill the in-flight `claude` child. |
| `advisor_runner.py` / `run_advisor.sh` | Seat-0 coach (read-only shadow feed → Advisor tab); `DEFAULT_TABLE` + `table_opponents` apply the roster rule; context between calls bounded to 40 lines; log writes guarded. `run_advisor.sh` is its restart loop (2 s damper, `logs/pids/advisor.pid`). |
| `ratings.py` | ELO applier: 3 ladders (pilot / deck / pilot×deck), six-pairwise scoring with tie groups, **transport-void** (wedge or ≥8 punts/seat in window → history recorded, ladders frozen; `ARENA_RATE_VOIDED=1` overrides; events filtered by the spool's `gameId`, unstamped events still count), flock-serialized (listing under the lock, renames guarded, spool keys validated → `.skipped`), per-seat digests for the AI panel. |
| `arena-ctl.py`, `status.py`, `usage_report.py`, `replay.py` | Ops: mid-game re-dial, dashboards (`status.py` counts `hold`/`plan`/`cycle` as fast paths), spend reports; `replay.py` is source-checkout-only (needs `tests/fixtures`, which the package excludes along with the script; prints a one-line explanation and exits 2 when they are absent). |
| `tests/` | 185 Python tests in 21 files (`python3 -m unittest discover -s runner/tests`, 2026-09-04; needs the gitignored dossiers on disk): golden argv, rules/validator, memo, cycle replay, wedge recovery, ratings incl. void, backends, protocol, engine fixtures, brief contract, the 2026-09-04 `test_round_two_*` files. |

## 5. Scripts catalog (`scripts/`)

**Project 2 (ships in forge-light-llm):** `arena-play.sh` (one-shot launch:
preflight → teardown → runners → advisor (`runner/run_advisor.sh`, human
games) → GUI → liveness; refuses deck names with whitespace),
`arena-stop.sh` (teardown by PID file + ELO sweep + archive of the session's
log set incl. `game.jsonl`/`game-*.jsonl`; fallback `pkill` patterns anchored
on this checkout), `arena-autostop.sh` (started by arena-play once the match is
live: waits for the engine's `gameOver` or the GUI JVM to vanish, lingers
`--linger` seconds, execs `arena-stop.sh`; a hand stop always wins), `run-pilot-match.sh` (GUI JVM launcher), `run-gui.sh`,
`arena-add-deck.py` (ingester), `arena-status.py`, `arena-cardwatch.py` (live
card-conservation watcher — per-seat nontoken totals across zones,
2026-08-31), `arena-digest.py` (counts torn lines). `react-autopass.py` was
deleted 2026-09-04 (BL-15; retired from the launch 2026-08-17 — the runners'
allowlist fastpath covers it).

**Project 1 / local only (stays home):** `batch.sh`, `canary.sh`, `prep.sh`,
`smoke.sh`, `fidelity.py`, `program-fidelity.py`, `observe-play.py`,
`anchors.py`, `merge_discovery.py`, `build-ingestion-packages.py`,
`build_card_scripts_index.py`, `gemini_wholedeck.py`,
`capability-prototype.py`, `deckcheck-import.py` (authenticated DeckCheck
round-trip for onboarding a deck for local testing — spends credits, uses the
`hello/` login; never bundled, see INTERACTIVE-ARENA note 44).

**Stray (candidates for removal):** `selvala-wholedeck-ingestion-wf_87514c03-1a9.js`
(one-off workflow artifact), `scripts/__pycache__/`.

## 6. Runtime artifacts — who writes, who reads, lifecycle

| Artifact | Writer | Reader | Lifecycle |
|---|---|---|---|
| `mailbox/seat-N/{inbox,outbox}` | engine / seat daemons | each other | deleted per decision; cleared by arena-stop. gitignored. |
| `mailbox/observer-state.json` | `ObserverSnapshot` (event bus) | seat pre-planning, advisor, dashboards, launch liveness | per-game. gitignored. |
| `mailbox/seat-0-advisor/inbox/` | `AdvisorFeed` (Java, one-way shadow of the human seat's windows) | `advisor_runner.py` | per-game; cleared at stop. The advisor has NO outbox — read-only by construction. |
| `runner/logs/control/seat-N.json` | runner (`_init_control` seeds it) + the GUI AI panel (writes re-dials) | runner polls mtime → applies model/effort at next decision | per-game; `control/` cleared at stop. |
| `runner/logs/control/advisor.json` | the Advisor tab's pause button | `advisor_runner.py` (paused = no scanning, no calls) | cleared at stop → every session starts enabled. |
| `runner/logs/control/ask/ask-<millis>-<serial>.json` | the Advisor tab's Ask field (`AiControlFile.askAdvisor`) | `advisor_runner._handle_asks` (deleted on pickup, answered in the stream, before the pause gate) | per question; `control/` cleared at stop. |
| `runner/logs/cache/or-models.json` | run_table's keyless OpenRouter `/models` probe (5s cap, warn-and-continue) | backends.py (context/completion limits) + next launch's context preflight | refreshed per launch when any `or/` seat is rostered; `cache/` survives arena-stop (only `control/` is cleared — item 13f). |
| `runner/logs/pids/*.pid` | arena-play (`run_table`, `advisor-loop`, `gui`, `autostop`), run_table (`seat-N`), run_advisor (`advisor`) | `arena-stop.sh` (kills only PIDs whose command line names this checkout) | removed at stop. |
| `runner/logs/seat-N.{log,jsonl}` | seat daemon | humans, forensics, ELO attribution | moved to `logs/archive/<ts>-stop/` by arena-stop. gitignored. |
| `runner/logs/game.jsonl` | all seats (single-line appends) | humans (`tail -f`), `arena-digest.py`, `status.py`, `arena-status.py`, ELO attribution | plain append-only file for the whole session (BL-21 reverted item 13h's symlink); moved to the archive by arena-stop together with the per-game files; never rotated during a session. gitignored. |
| `runner/logs/game-<gameId>.jsonl` | all seats (the same record, per game) | `ratings.py` (`slice_game_log` reads every regular `game*.jsonl` beside it) | one file per game; archived at stop. |
| `runner/logs/seat-N.usage.json` | brain (atomic snapshot) | crash-restart spend seed, panel | per-game. |
| `runner/logs/transport-events.jsonl` | seat daemons (punts/wedges, each stamped with `gameId`) | `ratings.py` void check (filters by the spool's `gameId`) | archived at stop, never rotated mid-session. |
| `runner/logs/elo/seat-N.json` | `ratings.py` | AI panel (regex-only reader) | refreshed per rated game. |
| `runner/logs/{gui,run_table,ratings,advisor_runner}.out` | nohup redirects in arena-play | humans | archived at stop. |
| `mailbox/seat-N/heartbeat` | seat daemon / advisor (touched every 5 s) | engine (`MailboxProtocol.heartbeatAgeMillis`; older than `arena.mailbox.heartbeat.stale.ms` = nobody home, stock at once) | per-game; removed with the seat dir at stop. |
| `mailbox/launch-status.json` | `GuiPilotMatch.verifyRoster` (`{ok, detail, ts}`) | `arena-play.sh` (reports an engine-refused launch at once) | per launch; removed at stop. |
| `runner/results/game-*.json` (+`.rated/.skipped/.voided`) | `GameResultSpool` (Java) | `ratings.py` | renamed on processing; archived. Spool SKIPS (logged) when no absolute logs/mailbox dir — never writes cwd-relative paths. |
| `runner/ratings.json`, `ratings-history.jsonl`, `ratings.lock` | `ratings.py` | panel, plots | per-installation state; survives package rebuilds; gitignored, never ships. |
| `runner/logs/advisor-0.{log,jsonl}` | advisor (stream + structured twin) | Advisor tab tail / reviews | archived at stop. In an advised human game, `seat-0.usage.json` is the ADVISOR's spend snapshot (seat 0 is the human). |
| `runner/logs/archive/<ts>-stop/` | `arena-stop.sh` | forensics, later ELO re-sweeps | every finished game's full log set + consumed spools; grows unbounded by design. |
| `schemas/arena.mailbox-request.1.schema.json` + `runner/tests/fixtures/engine/*.json` | schema: hand-maintained (09-04: `gameId` serial, `state.purpose`, `state.controllerBoard`); fixtures: `ProtocolContractTest` under `-Darena.fixtures.refresh=true` only — otherwise it COMPARES and fails on drift (BL-25) | `runner/tests/test_engine_fixtures.py` | the mailbox wire contract, tested from both sides (2026-09-03); fixtures are tracked. |
| `decks/<slug>/dossier/*`, `.cache/`, `.dck`, primers | `arena-add-deck.py` | brains at init | per-deck. `decks/*.dck` and `docs/primers/*` are tracked; `decks/*/` is gitignored, so dossiers are disk-only — the package carries them — except the five files `git ls-files forge-arena/decks` still shows under `swords-plunder/dossier/` and `swords-plunder-gc/dossier/` (tracked before the ignore). `.cache/` is a local ingestion accelerator only and is never packaged (BL-18: its DeckCheck payloads carry the account's username; the packager fails if one reaches the tree). `dossier/manifest.json` (2026-09-03, plan item 7): the registered `.dck`'s SHA-256, card count, card-DB stamp and every Scryfall→Forge name resolution; the launch preflight compares the hash in ms, no JVM. `deck-cards.json` entries carry `scryfall_id`/`set`/`collector_number` (Scryfall canonical) and `forge_name` (the loader's name, from `DeckLoadProbe --resolve`). |

## 7. Documentation set

69 files under `docs/` as of 2026-09-04 (`find docs -type f | wc -l`); the
light package ships only `docs/primers/<shipped slugs>-deckcheck.md` and the
two rules digests named below.

| Doc | Audience | State (2026-09-04) |
|---|---|---|
| `packaging/README.md` | package users | refreshed 2026-09-04 (fallback halves, rosters, log files, `--setting-sources` footnote) |
| `packaging/PATCH-NOTES.md` | package users | v1→v3.3.2 + "Unreleased — after v3.3.2" (the v3.3.3 cut is pending, BL-17) |
| `../BUILDING.md` | developers | refreshed 2026-09-04 (`extended` group, fixture refresh flag, `maven.test.skip`) |
| `docs/INTERACTIVE-ARENA.md` | seam engineers | field notes through 72 (2026-09-04) |
| `docs/BUG-LOG.md` | everyone | the outstanding-items ledger (opened 2026-09-04): interactive open items, watch items, deferred headless findings, closed-this-pass with commits |
| `docs/INVENTORY.md` | (this file) | 2026-09-04 |
| `docs/UPSTREAM-SYNC.md` | maintainers | 2026-08-17; counts refreshed 2026-09-04 |
| `docs/IMPLEMENTATION-PLAN.md` | Project 1 | living plan, §-annotated as-builts |
| `docs/AGENT-SDK-SEATS.md` | historical | superseded by the shipped `runner/seatd` (kept as design record) |
| `docs/PR-LOG.md` | maintainers | one paragraph per PR (append with every PR commit) |
| `docs/SPEC-arena-add-deck.md` | ingestion | spec for `arena-add-deck.py`, marked BUILT (note 43) |
| `docs/SPEC-executable-turn-plans.md` | runner | design spec for `--speculative` executable plans (states "not yet built"; the runner ships the guarded implementation behind `SEAT_SPECULATIVE=1`, default off) |
| `docs/SYNERGY-INGESTION.md`, `docs/CANARY-BRIEF-GOLD.md` | Project 1 | whole-deck synergy discovery: the run contract and the gold agent brief |
| `docs/runner-cat.md`, `docs/atlas/` (18 files) | Project 1 | runner execution semantics; one reference page per dossier artifact |
| `docs/working-plan-Aug-3.md` | historical | 2026-08-03 ingestion working plan (post-compaction anchor) |
| `docs/research/` (16 files) | reference | surveys, audits (`SEAM-AUDIT-2026-08-28.md`), DeckCheck protocol notes, and the two brain-loaded digests `mtg-rules-summary.md` + `mtg-rules-digest-conversion.md` (the only `research/` files that ship) |
| `docs/reviews/` (4 files) | maintainers | 2026-09-03 full review + interactive plan; 2026-09-04 round-two comparison + interactive cleanup plan |
| `docs/archive/` (8 files) | historical | completed-milestone docs (note 43) |
| `docs/primers/<slug>-deckcheck.md` (10) | brains | per-deck strategy primers; Urza gained a mana-discipline section 08-17 |

## 8. Known strays / cleanup candidates

- ~~`decks/selvala-competitive.dck`~~ — removed 2026-08-19 (cleanup round).
- `scripts/selvala-wholedeck-ingestion-wf_*.js` — tracked one-off; candidate
  for deletion.
- `scripts/__pycache__/`, `runner/__pycache__/` — gitignored (root `.gitignore` + `runner/.gitignore`).
- `EDocID.java` / `CMatchUI.java` edits are the only parent-module changes
  without `[arena]` markers (action item in UPSTREAM-SYNC.md).
