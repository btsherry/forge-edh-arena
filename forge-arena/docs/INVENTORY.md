# forge-arena INVENTORY — code, seams, scripts, artifacts

*Generated 2026-08-17 from the repo itself (branch `arena`, ~360 commits ahead
of upstream base `0eec0a16d0a`, 2026-07-15). Companion documents:
[UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) (how to take upstream updates safely),
[INTERACTIVE-ARENA.md](INTERACTIVE-ARENA.md) (seam architecture + field
notes), `packaging/README.md` (user-facing feature docs, ships with the
package), `packaging/PATCH-NOTES.md` (release history), `../BUILDING.md`
(build + tarball recipe).*

---

## 1. Upstream divergence — every file we changed outside `forge-arena/`

The original "no parent-module patches" rule was deliberately dropped
(first for the vanished-commander engine fix, 2026-08-17). The full delta
outside `forge-arena/` (2026-08-24 re-audit) is **31 files**: 12 modified
(9 upstream Java files, ~263 changed lines; plus `match.xml`, root
`pom.xml`, root `.gitignore`), 8 new code files parked in parent modules
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
| `forge-gui/res/defaults/match.xml` | forge-gui res | Pilot-tuned default match layout (the only res/ divergence). |

### 1c. ArchUnit boundary
`forge.arena.interactive` is a **sanctioned second seam** (ArchUnit rule,
commit cfda47447a0). Everything else under `forge.arena.*` is the Project-1
headless harness and may not import GUI classes.

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

### Still stock (deliberate, with rationale)

| Surface | Why stock |
|---|---|
| Multi-target spells (max targets > 1) | Falls back; never worse than status quo. Rare at stakes so far. |
| "Name a card" from the whole DB (`chooseSingleCardFace` predicate overload) | Unbounded option list — the mailbox never ships one. |
| Trigger ORDERING (simultaneous triggers) | Small surface, not yet observed at stakes. |
| `chooseSingleReplacementEffect` | Fires on every replaced event — window-spam risk; needs frequency data first (wave-2 deferral). |
| Routine tap-cost payment picks | `TapCostPreference` stays symmetry-armed only — a live exchange sits inside the mana-payment inner loop (pacing risk; wave-2 deferral). |
| Combat damage assignment/ordering | Never overridden; stock was never broken here. |
| Mana payment source selection | `TapCostPreference` covers the symmetry case; full auto-tap reimplementation deferred (#15). Known quirk: `canPayCost` can be conservative (Ancient Tomb refusal, note 41) — the guard refusal returns the window and brains adapt by floating first. |
| Mana-color choice | Auto-answered for mono-color commanders (v2 QoL); multicolor → GUI default. |
| `chooseCardsToDiscardFrom` when candidates aren't visible to the chooser | Hidden-info discipline. |

---

## 3. `forge-arena` Java map (module `forge.arena.*`)

| Package | Project | Contents |
|---|---|---|
| `interactive/` | 2 | The seam: `MailboxProtocol` (file bus), `MailboxController` (all overrides above), `MailboxLobbyPlayer` (controller injection), `GuiPilotMatch` (launcher, roster via `arena.seat.decks`), `ObserverSnapshot` (public event-bus state), `GameResultSpool` (ELO result writer), `AdvisorControllerHuman`/`AdvisorFeed`/`AdvisorLobbyPlayer` (seat-0 shadow feed), `SeatAvatars` (cosmetic color-matched seat portraits from deck pip mix; resource `src/main/resources/forge/arena/avatar-colors.json`, 126 heads; fail-safe, fresh-Random — never touches game determinism; assignment logged as `[arena] seat avatars:` in gui.out). |
| `bootstrap/` | shared | `ArenaBootstrap` (headless/GUI init, RNG seeding). |
| `engine/` | 1 (+SeatViews shared) | `EngineFacade`, `SeatView`/`SeatViews` (hidden-info-safe read model — the fairness boundary, ArchUnit-guarded). |
| `harness/`, `combo/`, `prep/`, `bindgen/`, `report/` | 1 | Headless batch stack (BatchMain, combo programs, dossier prep, pilot floors). Not shipped in forge-light-llm. |

Tests: `src/test/java/forge/arena/**` — 308 as of 2026-08-17, including the
seam regression suite (`*ReachesMailboxTest`, `GuardedCastTargetIntegrityTest`,
`TapSymmetryBreakTest`, `UnaffordableCastRollbackTest`, `CounterspellReachesTargetTest`).
Test-harness pattern: `ArenaBootstrap.initialize` + cards placed by zone +
`MailboxLobbyPlayer` + temp mailbox + a test-thread brain + `PhaseHandler.mainLoopStep`.
**Probe-regex rule:** match option ids only via `\{"id":(\d+),"label":"…` —
matching anywhere in the body hits card ids in `state.battlefield` (bit twice).

## 4. Python runtime map (`runner/`)

| File | Role |
|---|---|
| `seatd/runner.py` | Seat daemon: window handling, memo/autopass/hold fastpaths, executable plans, deviation + turn-intent capture, effort routing (resourceless/own-trigger/free-confirm → low), **cycle replay** (`repeat_cycle`), transport-event emission. |
| `seatd/brain.py` | Resident model session: `claude -p --resume` (MCP-disabled), per-call effort override, wedge detection → fresh-session rejoin, spend/usage accounting. |
| `seatd/backends.py` | OpenRouter (`or/<vendor>/<model>`, `OPENROUTER_API_KEY`) + OpenAI-compatible (`oai/<model>`, `ARENA_OAI_BASE_URL`) transports; per-seat cost rails (`ARENA_MAX_SEAT_COST_USD` default $5, 250-call cap), auth/model latches, mid-game Claude↔backend re-dial with session survival. |
| `seatd/rules.py` | Prompt builder, per-type answer hints, validator (strips extra keys), shape-aware safe defaults, plan-step binding. |
| `seatd/protocol.py` | Mailbox file I/O. |
| `seatd/seat-brief.md` / `advisor-brief.md` | The standing briefs (rules 1–6 + tuning bullets; counting-not-valuation discipline). |
| `seat_runner.py` / `run_table.sh` | Entry point + supervisor (restart loop, crash-loop damper for backend seats, preflight). |
| `advisor_runner.py` | Seat-0 coach (read-only shadow feed → Advisor tab). |
| `ratings.py` | ELO applier: 3 ladders (pilot / deck / pilot×deck), six-pairwise scoring with tie groups, **transport-void** (wedge or ≥8 punts/seat in window → history recorded, ladders frozen; `ARENA_RATE_VOIDED=1` overrides), flock-serialized, per-seat digests for the AI panel. |
| `arena-ctl.py`, `status.py`, `usage_report.py`, `replay.py` | Ops: mid-game re-dial, dashboards, spend reports, replay. |
| `tests/` | 110 Python tests (golden argv, rules/validator, memo, cycle replay, wedge recovery, ratings incl. void, backends, protocol). |

## 5. Scripts catalog (`scripts/`)

**Project 2 (ships in forge-light-llm):** `arena-play.sh` (one-shot launch:
preflight → teardown → runners → advisor → react-autopass → GUI → liveness),
`arena-stop.sh` (teardown + ELO sweep + archive), `run-pilot-match.sh` (GUI
JVM launcher), `run-gui.sh`, `arena-add-deck.py` (ingester),
`arena-status.py`, `arena-cardwatch.py` (live card-conservation watcher — per-seat nontoken totals across zones, 2026-08-31), `arena-digest.py`, `react-autopass.py` (manual-fallback no-op REACT daemon — retired from the standard launch 2026-08-17; the runners' allowlist fastpath covers it).

**Project 1 (stays home):** `batch.sh`, `canary.sh`, `prep.sh`, `smoke.sh`,
`fidelity.py`, `program-fidelity.py`, `observe-play.py`, `anchors.py`,
`merge_discovery.py`, `build-ingestion-packages.py`,
`build_card_scripts_index.py`, `gemini_wholedeck.py`, `capability-prototype.py`.

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
| `runner/logs/control/or-models.json` | run_table's keyless OpenRouter `/models` probe (5s cap, warn-and-continue) | backends.py (context/completion limits) + next launch's context preflight | refreshed per launch when any `or/` seat is rostered; cleared at stop. |
| `runner/logs/seat-N.{log,jsonl}` | seat daemon | humans, forensics, ELO attribution | rotated to `logs/archive/<ts>-stop/` by arena-stop. gitignored. |
| `runner/logs/game.jsonl` | all seats (append) | ELO attribution, reviews | **preserved across games** (never rotated). gitignored. |
| `runner/logs/seat-N.usage.json` | brain (atomic snapshot) | crash-restart spend seed, panel | per-game. |
| `runner/logs/transport-events.jsonl` | seat daemons (punts/wedges) | `ratings.py` void check | archived at stop. |
| `runner/logs/elo/seat-N.json` | `ratings.py` | AI panel (regex-only reader) | refreshed per rated game. |
| `runner/logs/{gui,run_table,ratings,react-autopass,advisor_runner}.out` | nohup redirects in arena-play | humans | archived at stop. |
| `runner/results/game-*.json` (+`.rated/.skipped/.voided`) | `GameResultSpool` (Java) | `ratings.py` | renamed on processing; archived. Spool SKIPS (logged) when no absolute logs/mailbox dir — never writes cwd-relative paths. |
| `runner/ratings.json`, `ratings-history.jsonl`, `ratings.lock` | `ratings.py` | panel, plots | per-installation state; survives package rebuilds; gitignored, never ships. |
| `runner/logs/advisor-0.{log,jsonl}` | advisor (stream + structured twin) | Advisor tab tail / reviews | archived at stop. In an advised human game, `seat-0.usage.json` is the ADVISOR's spend snapshot (seat 0 is the human). |
| `runner/logs/archive/<ts>-stop/` | `arena-stop.sh` | forensics, later ELO re-sweeps | every finished game's full log set + consumed spools; grows unbounded by design. |
| `decks/<slug>/dossier/*`, `.cache/`, `.dck`, primers | `arena-add-deck.py` | brains at init | per-deck, tracked (dossier conventions per deck). |

## 7. Documentation set

| Doc | Audience | State (2026-08-17) |
|---|---|---|
| `packaging/README.md` | package users | current (v3.1) |
| `packaging/PATCH-NOTES.md` | package users | current (v1→v3.1) |
| `../BUILDING.md` | developers | current |
| `docs/INTERACTIVE-ARENA.md` | seam engineers | refreshed 2026-08-17 (this pass) |
| `docs/INVENTORY.md` | (this file) | 2026-08-17 |
| `docs/UPSTREAM-SYNC.md` | maintainers | 2026-08-17 |
| `docs/IMPLEMENTATION-PLAN.md` | Project 1 | living plan, §-annotated as-builts |
| `docs/AGENT-SDK-SEATS.md` | historical | superseded by the shipped `runner/seatd` (kept as design record) |
| `docs/primers/<slug>-deckcheck.md` | brains | per-deck; Urza gained a mana-discipline section 08-17 |

## 8. Known strays / cleanup candidates

- ~~`decks/selvala-competitive.dck`~~ — removed 2026-08-19 (cleanup round).
- `scripts/selvala-wholedeck-ingestion-wf_*.js` — tracked one-off; candidate
  for deletion.
- `scripts/__pycache__/`, `runner/__pycache__/` — should be gitignored if not.
- `EDocID.java` / `CMatchUI.java` edits are the only parent-module changes
  without `[arena]` markers (action item in UPSTREAM-SYNC.md).
