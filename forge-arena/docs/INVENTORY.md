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
outside `forge-arena/` is **16 files**: 8 modified upstream files (~150
changed lines), 7 new files parked in parent modules, 1 config.

### 1a. MODIFIED upstream files (merge-conflict surface — see UPSTREAM-SYNC.md)

| File | Δ | Kind | Why | Marker | Guarding test |
|---|---|---|---|---|---|
| `forge-ai/.../ComputerUtil.java` | +12 −9 | **BEHAVIORAL** | `handlePlayingSpellAbility`'s failed-payment path moved the card stack→stack and orphaned it (upstream FIXME; ate a commander). Now rolls back to origin zone. | `[arena]`-class comment ✓ | `UnaffordableCastRollbackTest` |
| `forge-ai/.../AiCostDecision.java` | +38 | Additive hook | `visit(CostTapType)` consults `TapCostPreference` first (symmetry-break tap pre-selection). No preference → stock path byte-identical. | ✓ | `TapSymmetryBreakTest` |
| `forge-game/.../MagicStack.java` | +18 | Diagnostic only | `[arena] FIZZLE:` stderr line in the fizzle branch (targets + stack dump). No behavior change. | ✓ | (log-only) |
| `forge-core/.../MyRandom.java` | +36 −6 | **BEHAVIORAL** | Seedable RNG (`setSeed`) for reproducible headless batches (Project 1). | ✓ (ARENA-PATCH) | `SeedDeterminismTest` |
| `forge-game/.../Combat.java` | +6 −1 | Defensive fix | `getAttackers` snapshot vs concurrent modification crash. Upstream-worthy. | ✓ | (crash class) |
| `forge-game/.../StaticAbilityTurnPhaseReversed.java` | +34 −7 | Defensive fix | Crash guard + value-based pair choice. Upstream-worthy. | ✓ | PR-49 tests |
| `forge-gui-desktop/.../EDocID.java` | +2 | GUI wiring | Registers the Advisor + AI-panel dock tabs. | **unmarked** | (compile) |
| `forge-gui-desktop/.../CMatchUI.java` | +6 | GUI wiring | Instantiates the two arena dock tabs. | **unmarked** | (compile) |

### 1b. NEW files in parent modules (zero merge-conflict surface)

| File | Module | Why it lives there |
|---|---|---|
| `forge-ai/.../TapCostPreference.java` | forge-ai | The AiCostDecision hook interface must be visible to forge-ai. |
| `forge-gui-desktop/.../forge/arena/interactive/AiControlFile.java` | gui-desktop | AI-panel file protocol (per-seat model/effort dials, ELO line). Moved here 2026-08-12 so the desktop reactor builds it. |
| `forge-gui-desktop/.../forge/arena/interactive/AdvisorLogTail.java` | gui-desktop | Advisor tab's log tailer. |
| `forge-gui-desktop/.../controllers/CAiControl.java` + `views/VAiControl.java` | gui-desktop | AI dock tab (steppers, telemetry, ELO). |
| `forge-gui-desktop/.../controllers/CAdvisor.java` + `views/VAdvisor.java` | gui-desktop | Advisor dock tab (+ pause button). |
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

### Still stock (deliberate, with rationale)

| Surface | Why stock |
|---|---|
| Multi-target spells (max targets > 1) | Falls back; never worse than status quo. Rare at stakes so far. |
| "Name a card" from the whole DB (`chooseSingleCardFace` predicate overload) | Unbounded option list — the mailbox never ships one. |
| Trigger ORDERING (simultaneous triggers) | Small surface, not yet observed at stakes. |
| Combat damage assignment/ordering | Never overridden; stock was never broken here. |
| Mana payment source selection | `TapCostPreference` covers the symmetry case; full auto-tap reimplementation deferred (#15). Known quirk: `canPayCost` can be conservative (Ancient Tomb refusal, note 41) — the guard refusal returns the window and brains adapt by floating first. |
| Mana-color choice | Auto-answered for mono-color commanders (v2 QoL); multicolor → GUI default. |
| `chooseCardsToDiscardFrom` when candidates aren't visible to the chooser | Hidden-info discipline. |

---

## 3. `forge-arena` Java map (module `forge.arena.*`)

| Package | Project | Contents |
|---|---|---|
| `interactive/` | 2 | The seam: `MailboxProtocol` (file bus), `MailboxController` (all overrides above), `MailboxLobbyPlayer` (controller injection), `GuiPilotMatch` (launcher, roster via `arena.seat.decks`), `ObserverSnapshot` (public event-bus state), `GameResultSpool` (ELO result writer), `AdvisorControllerHuman`/`AdvisorFeed`/`AdvisorLobbyPlayer` (seat-0 shadow feed). |
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
`arena-status.py`, `arena-digest.py`, `react-autopass.py` (no-op REACT daemon).

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
| `runner/logs/seat-N.{log,jsonl}` | seat daemon | humans, forensics, ELO attribution | rotated to `logs/archive/<ts>-stop/` by arena-stop. gitignored. |
| `runner/logs/game.jsonl` | all seats (append) | ELO attribution, reviews | **preserved across games** (never rotated). gitignored. |
| `runner/logs/seat-N.usage.json` | brain (atomic snapshot) | crash-restart spend seed, panel | per-game. |
| `runner/logs/transport-events.jsonl` | seat daemons (punts/wedges) | `ratings.py` void check | archived at stop. |
| `runner/logs/elo/seat-N.json` | `ratings.py` | AI panel (regex-only reader) | refreshed per rated game. |
| `runner/logs/{gui,run_table,ratings,react-autopass,advisor_runner}.out` | nohup redirects in arena-play | humans | archived at stop. |
| `runner/results/game-*.json` (+`.rated/.skipped/.voided`) | `GameResultSpool` (Java) | `ratings.py` | renamed on processing; archived. Spool SKIPS (logged) when no absolute logs/mailbox dir — never writes cwd-relative paths. |
| `runner/ratings.json`, `ratings-history.jsonl`, `ratings.lock` | `ratings.py` | panel, plots | per-installation state; survives package rebuilds; gitignored, never ships. |
| `runner/logs/advisor-0.jsonl` | advisor | reviews | archived at stop. |
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

- `decks/selvala-competitive.dck` — untracked on disk, deliberately excluded
  from the package; commit or remove.
- `scripts/selvala-wholedeck-ingestion-wf_*.js` — tracked one-off; candidate
  for deletion.
- `scripts/__pycache__/`, `runner/__pycache__/` — should be gitignored if not.
- `EDocID.java` / `CMatchUI.java` edits are the only parent-module changes
  without `[arena]` markers (action item in UPSTREAM-SYNC.md).
