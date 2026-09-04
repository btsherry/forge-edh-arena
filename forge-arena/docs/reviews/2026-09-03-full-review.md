# forge-arena full review — 2026-09-03

Scope: everything written in this fork under `forge-arena/` plus the arena seams carried in the parent modules (`forge-ai`, `forge-game`, `forge-core`, `forge-gui-desktop`). The upstream Forge engine itself is out of scope. Branch `arena` at `0a1cfac3061` (v3.3.2).

## How this was produced

Three independent sources, then one synthesis.

- **Fable 5.1 (this session), direct read.** The whole interactive layer (`MailboxProtocol`, `MailboxController` all 3,433 lines, `GuiPilotMatch`, `ObserverSnapshot`, `GameResultSpool`, `AdvisorControllerHuman`, `AdvisorFeed`, `SeatAvatars`, `DeckLoadProbe`, the GUI seam classes), the Python mailbox transport (`protocol.py`), the launch and teardown scripts, and the full diff of the parent-module patches vs `master`. Every claim below marked ✔ was checked by me against source; ◐ means a reviewer confirmed it by reading and I did not re-derive it; ○ means plausible but unconfirmed.
- **Four Opus reviewers**, one per area, read-only: (A) engine/harness/report, (B) combo/prep/bindgen/ingest, (C) Python runner/advisor/scripts, (D) tests and doc drift. Each read its whole scope, cited file:line, and tagged confirmed vs plausible. Their full reports are in the session scratchpad (`review/agent-*.md`).
- **Gemini (gemini-pro-latest)**, three passes over the same source bundles (Project 2, Project 1, tests+INVENTORY). Gemini's output was shorter and shallower; where it overlapped it mostly agreed, and its two loudest P0 claims did not survive verification (see "Calibration").

Severity: **P0** corrupts state, data, or a batch; **P1** wrong behaviour in real play or measurement; **P2** minor, cosmetic, or latent.

## Verdict

The codebase is two projects of very different maturity sharing one module.

**Project 2 (the interactive table) is fundamentally sound.** The mailbox transport is careful on both sides (atomic writes, partial-read tolerance, orphan sweeps, seq-regression detection). The hidden-information discipline holds: I found no path that leaks an opponent's hand or library order to a brain. The controller's fail-open contract (every override degrades to stock AI) is real for almost every surface. The defects are in the edges: budget accounting when a session re-inits, a punt being remembered as a decision, trigger-aiming windows that quietly skip the stock floor, and an advisor whose lifecycle logic is wrong in three independent ways. None of these corrupts a game; all of them make the seats play worse than the model would, silently.

**Project 1 (the headless harness) has real structural problems that affect the numbers it exists to produce.** The wall-clock timeout path ends a game from the wrong thread while the game thread is still running. Setup failures produce no game record and take out a worker's whole stride. Combo-aware seats carry a second `AiController`, so half the upstream AI consults a brain that is not making decisions. Nine of eleven program-dispatch branches forfeit the seat's priority window on a null first step. And the entire body of hand-authored combo programs is gitignored. The A/B measurements built on this layer are noisier than their PR numbers imply.

**The test gate is honest at the unit level and hollow at the integration level.** Roughly a third of the suite cannot run on a clean checkout, several live-shaped tests do not scope their assertion to the seam they name, and the single most repeated reliability claim in the docs (timeout degrades to stock) has no test.

**Security exposure is low** (local, single-user, no untrusted network input reaches a shell or `eval`), with a handful of hygiene items.

## The ranked list

Cross-source, whole codebase. "Found" names the source; "Verified" is my check.

| # | Sev | Finding | Where | Found | Verified |
|---|---|---|---|---|---|
| 1 | P0 | Wall-clock timeout ends the game from the harness thread while the game thread still runs: `setGameOver` clears every controller mid-decision, fires the outcome event into bridges that assume the game thread, and the abandoned 64 MB thread keeps writing into a closed recorder for the worker's life | `EngineFacade.java:120-128, 193-230` | A | ✔ |
| 2 | P0 | Setup exceptions (bad deck, missing dossier, unreadable artifacts) escape `runOne`, leak the recorder, produce no `GameRecord`, kill the worker, are retried identically 3x, and the stride is lost | `ArenaRunner.java:40-56` | A | ✔ |
| 3 | P0 | 53 combo programs, 18 pairing programs and every route/tutor/protection artifact are gitignored (`decks/*/`); 25 tests error on a clean checkout and the schema gate passes vacuously | `forge-arena/.gitignore` | B, D | ✔ (known convention; the risk stands) |
| 4 | P0 | Every shipped Java-prepped dossier fails its own integrity gate (`deck_cards` sha mismatch on all four); a combo-aware batch exits 2 | `DossierCheck.java:66-76`, `BatchMain.java:96-108` | B | ✔ (Giada recomputed) |
| 5 | P1 | Combo-aware seats get a second `AiController` from `getAi()`; 62 upstream call sites consult a brain that is not deciding, and its card memory is never reset per turn | `ComboAwareLobbyPlayer.java:2038-2068` | A | ✔ |
| 6 | P1 | Nine of eleven program-dispatch branches `return first` when the runner's first call is null, passing the seat's whole priority window; the fix landed in one branch only | `ComboAwareLobbyPlayer.java:981-1069` | A | ✔ |
| 7 | P1 | Decision budget spent twice: `ensure_session` gets the budget, then `_call` gets the original budget again, so one decision can block the seat for 2x the deadline and go deaf across several engine windows | `brain.py:329-335` | C | ✔ |
| 8 | P1 | A punt (timeout, wedge, invalid) is memoized as if the brain passed; all identical REACT windows that turn auto-pass with a `why` that claims the brain considered them, and the punt counter feeding the ratings void check is suppressed | `runner.py:811-821` | C | ✔ |
| 9 | P1 | Trigger aiming offers "DECLINE this optional trigger" even for mandatory triggers, then auto-aims the first legal candidate; and a timeout during trigger aiming becomes a decline instead of falling to stock | `MailboxController.java:916-924, 2631-2670` | Fable, Gemini | ✔ |
| 10 | P1 | Refused unaffordable cast returns "played" with no signal to the brain, which can re-pick the same spell every window (model-call livelock, not a hang) | `MailboxController.java:573-587` | Gemini (as P0), Fable | ✔ (downgraded) |
| 11 | P1 | Advisor lifecycle: `chosen-n` reuses the request seq while digests/notes take fresh seqs, so ordinary interleaving looks like a new game and drops the session; pause/resume does the same and floods the backlog; a second game in-process never re-arms the governor | `AdvisorFeed.java:62-92`, `advisor_runner.py:312-334` | C | ✔ |
| 12 | P1 | `PairedPlay` decides "is this a land" from an 11-name basic-land list; land wipes score near zero against a real manabase and creature wipes count every nonbasic as a target, re-breaking the PR-49 fix | `PairedPlay.java:146-161` | B | ✔ |
| 13 | P1 | `PayoffRules` matches Clue reminder text and symmetric draws: Loran of the Third Path, Wojek Investigator, Minas Tirith ship in Giada's `draw_engine_permanent` list and the conversion planner will fire them | `PayoffRules.java:234-236` | B | ✔ |
| 14 | P1 | Two ingestion paths write incompatible dossiers into the same directory; the Python one clobbers the Java one (cause of #4), violates `arena.combos/1` on 7 of 10 decks, and drops `template_requirements` so every template combo reads as fully specified | `arena-add-deck.py:266-280`, `PrepMain` | B | ◐ |
| 15 | P1 | `firedShortcuts` doubles as "pool banked" and "combo fired"; program dispatch sets `bankedPhase` without a pool, so the next phase emits a false `pool_expired` and clears the fired-set for every combo, defeating the refire lockout | `ComboPilot.java:1104-1122, 1736` | B | ✔ |
| 16 | P1 | The packager cannot fail on a missing jar: `exit 1` inside a piped `while` exits the subshell; the tarball ships incomplete and dies at first launch | `build-light-package.sh:65-69` | C | ✔ |
| 17 | P1 | `SelvalaManaLoopRunner` embeds ten card names and a Rhonas/Nylea "god plan" in engine code, against the project's own generality rule; the general `sink.outlets` mechanism already exists beside it | `SelvalaManaLoopRunner.java` (table in A's report) | A | ◐ |
| 18 | P1 | Oracle-prose regexes decide lethal alpha (`amplified`) and whether a whole loop aborts (`perEtbDamage`), the exact anti-pattern the same file documents as a lesson | `ComboAwareLobbyPlayer.java:1739-1748`, `CastRecurRunner.java:277-284` | A, Gemini | ✔ |
| 19 | P1 | The mailbox has no game identity; new-game detection is inferred from seq monotonicity with a 3 s heuristic, and the `game_reset` branch never sweeps the outbox, so a stale `resp-1.json` answers the next game's first decision if two matches run in one JVM | `protocol.py:101-107`, `runner.py:616-626` | C | ✔ |
| 20 | P1 | Test gate is not what the docs say: `-Dmaven.test.skip=true` still skips it, checkstyle enforces two rules, `batch.sh` skips checkstyle with the flag BUILDING.md forbids, and the recorded green run was on JDK 25 against a "JDK 17 exactly" doc | `pom.xml:95`, `batch.sh:17`, `BUILDING.md` | D | ◐ |

## Findings by area

### 1. Interactive engine side (Java) — Fable direct read

What is right, and worth saying because it is the load-bearing part: `MailboxProtocol` is small, pure, atomic, and never throws into the game. `MailboxController.buildState` is the single fairness choke point and it holds: opponents contribute battlefield, graveyard, face-up exile, command zone, hand and library counts, and commander damage; nothing else. Every override I traced falls to `super` on null, malformed, wrong-count, or illegal answers. The parent-module patches (`TapCostPreference`, `SacCostPreference`, `PaymentPickPreference`, the `handlePlayingSpellAbility` rollback, the `MyRandom` thread-local, the turn-reversal reentrancy guard, the `Combat.getAttackers` snapshot) are additive, marked `[arena]`, and fall through to stock for every controller that does not implement the hook. The `MailboxController` design of vetting brain answers against engine-computed legal sets before mutating anything is the right shape.

Defects, all verified in source:

- **Mandatory triggers can be "declined" (P1, #9).** `chooseTargetsFor` offers option 0 "DECLINE this optional trigger (it will do nothing)" whenever `triggerAimDepth > 0`, without checking `WrappedAbility.isMandatory()`. `prepareTriggerViaSeat` then auto-aims `cands.get(0)` and adds the trigger to `pendingTriggerDecline`, but `confirmTrigger` returns true early for mandatory triggers, so the trigger resolves against an arbitrary legal target while the brain was told it would do nothing. A mandatory "destroy target creature" trigger can hit the seat's own creature.
- **Timeout during trigger aiming skips the stock floor (P1, #9).** In the same path a null exchange returns false and is treated identically to a decline. Every other surface degrades to stock on timeout; this one degrades to "do nothing".
- **Refused cast is invisible to the brain (P1, #10).** `playChosenSpellAbility` returns true after `REFUSED unaffordable cast`, which is logged to stderr only. The next window has identical options and no note. Cheap fix: exclude the refused SA from the next window or add a `lastRefused` field to state.
- **Mind-slaved seats route to the wrong brain (P2).** `MailboxLobbyPlayer.createMindSlaveController` builds the controller for the slave's own seat id, so under Mindslaver the slave's brain controls itself instead of the master's brain controlling it.
- **`payCostToPreventEffect` pays with stock heuristics (P2).** When the brain says "pay", `payComputerCosts(new AiCostDecision(...))` runs with `inPaymentContext` false, so `preferredSacCards`/`preferredPaymentCards` return null and stock picks which creature or card pays. Inconsistent with the seat-owns-payment design everywhere else.
- **Untyped confirm gate is a string match (P2).** `confirmAction` with `mode == null` mailboxes only if the message contains "play". Fragile; acknowledged in the F10 comment for ChangeTargets but not fixed generally.
- **Charm cast ignores the result (P2).** The `ApiType.Charm` branch returns true regardless of what `handlePlayingSpellAbility` returned.
- **ObserverSnapshot debounce has no trailing edge (P2).** The last event in a burst under 200 ms is never written; the dashboard is stale until the next event. Concurrent writes to the shared `.tmp` are possible if any event is fired off the game thread (Guava dispatches on the posting thread); a `synchronized` on `write` costs nothing.
- **Six of the 106 abstract `PlayerController` decisions are worth a second look.** 40 are overridden; 69 stay on stock. Most of the remainder are engine plumbing, but `chooseSomeType` (Serra's Emissary's card type), `chooseColor`/`chooseColorAllowColorless`, `orderSimultaneousSa` (trigger order), `assignCombatDamage`, `chooseCardsForConvokeOrImprovise`, and `chooseSingleSpellForEffect` are real decisions a brain would want.
- **Timeout mismatch by default (P2).** `run-pilot-match.sh` defaults the engine to 300 s, `run_table.sh` defaults the runner to 90 s. `arena-play.sh` passes one value to both, so only manual launches diverge. The engine should publish its timeout in each request.
- **No circuit breaker on a silent brain (P2, operability).** With a dead brain each decision waits the full timeout, then stock plays. Dozens of decisions per turn at 90 s each is an unplayable game rather than a degraded one. After N consecutive timeouts the seat should drop to stock for the turn, or shorten its wait.

### 2. Python seat runner, advisor, launch scripts — reviewer C, verified by Fable

Transport confirmed subscription-only: the only Claude path is `subprocess.run(["claude","-p","-",...])` pinned by a golden test; no `anthropic` import anywhere; backend keys never reach argv. The error state machine in `backends.py` and its 21 tests are the best-engineered code in the runner.

- **#7 budget spent twice** (✔). `decide()` hands `ensure_session` up to the whole budget, then `_call` the original `timeout_s`. A lazy re-init after a wedge blocks the single-threaded loop for up to 480 s on a 72 s deadline.
- **#8 punt memoized** (✔). Only `source == "model"` should feed `react_seen`.
- **#11 advisor lifecycle** (✔ Java side, ◐ Python consequences). `publishChosen(n)` reuses the request seq while `publishDigest`/`publishNote` increment it, so `chosen-7` after `digest-9` reads as a seq regression. Fix on either side: a game id in the feed, or ignore `chosen`/`note` kinds for regression detection.
- **#19 no game identity / no sweep on reset** (✔).
- **CONFIRM punt says yes to anything mentioning a "player"** (P2, ✔). `"play" in prompt` matches "player"; the negative list omits "pay {2}", "return", "tap". This is the one default-accept in an otherwise default-deny posture.
- **Stale `_deviation` stamped on every fastpath/memo/punt record** (P2, ◐). Reset it at the top of `handle()`.
- **`ratings.py` renames the spool `.rated` and appends history before persisting the ladders** (P2, ◐). A crash between leaves permanent divergence.
- **`handle()` has no exception guard** (P2, ◐). Any raise kills the process; `run_table.sh` restarts it with a fresh session and a full dossier re-init.
- **`react-autopass.py` ships despite the build script saying it stays home** (P2, ◐). It writes into every seat's outbox with no staleness or threat check and a stale two-name allowlist. Delete it or make it read-only.
- **Teardown is `pkill -f` with no PID files** (P2, ◐). Kills every table on the machine, ignores `ARENA_MAILBOX_DIR`, and `trap 'kill 0'` in `run_table.sh` signals the launching shell's process group because `arena-play.sh` backgrounds without `setsid`.
- **`arena-stop.sh` clears `logs/control/`, deleting `or-models.json`**, so the 50-line context preflight in `run_table.sh` can never run (P2, ◐).
- **`arena-play.sh` reports every advisor preflight failure as "deck not ingested"** because stderr is discarded; `--model` as the last argument crashes under `set -u`; a deck name with spaces or a path prefix silently disables the advisor (P2, ◐).
- **`combos.json` path lacks `.resolve()`** unlike its siblings; a relative `__file__` yields zero combos with no log line (P2, ◐).
- **`game.jsonl` is unbounded and fully read on every sweep/status**, while `transport-events.jsonl` (which the void check needs) is archived at teardown (P2, ◐).
- **Briefs describe a failure model that is not the code's** (P2, ◐). `seat-brief.md` says a bad answer becomes a pass; `safe_default` keeps hands, says yes to free triggers, answers `max` for `puntHigh` numbers. `advisor-brief.md` names decision types that do not exist.

### 3. Headless harness (engine/harness/report) — reviewer A, verified by Fable

- **#1 timeout path unsound** (✔). `LimitEnforcer.trip` already shows the right shape: it ends the game from inside event dispatch on the game thread. The wall-clock path should set a cooperative flag the enforcer trips, and treat a thread that will not stop as fatal for the worker.
- **#2 setup exceptions escape** (✔). Catch `Throwable` in `runOne`, close the recorder in `finally`, always emit a crash record.
- **#5 double `AiController`** (✔). Make `getAi()` a delegating decorator over `super.getAi()`, or move the sacrifice steering into `choosePermanentsToSacrifice` on the controller where it already has a sibling.
- **#6 dispatch forfeits the window** (✔). One parameterised test over the eleven `program_class` values with a runner stubbed to return null would catch it.
- **`PairingRunner` in `MEASURE_DEFERRED` passes every window until the seat's next turn** (P1, ◐). Four global turns surrendered to record one measurement.
- **`PairingRunner`'s joint-mana pip check is hard-coded to white** (P1, ◐), and `coloredPips` counts hybrid `{W/U}` as white.
- **#17 Selvala card names in engine code** (◐). The general mechanism (`sink.outlets`, `tryOutlet`) sits beside the hard-coded ladder.
- **#18 oracle-prose regexes** (✔). `amplified()` also keys on `pilot.amplifierNames()`, a per-deck name list.
- **`chooseCardsForZoneChange` override is dead** (P2, ◐): upstream `allowMultiSelect` excludes AI controllers; the codebase knows this in two comments and kept the 53 lines anyway.
- **`confirmAction` lacks `@Override`** (P2, ◐): a signature change upstream silently kills the seam.
- **Eleven near-identical runners, ~4,700 lines, no shared abstraction** (design). Each redeclares `SETTLE_GRACE_WINDOWS`, `ITERATION_CAP`, the JSON load with a swallowed exception, the stack gate, and the settle/measure state machine. This duplication is the direct cause of #6.
- **Priority-pass budget vs one-action-per-window runners** (○). 2,000 passes/turn vs runners that float one mana ability per window and cap at 400 iterations plus sinks; a winning conversion turn can plausibly trip `PRIORITY_PASSES` and score as a draw. Check `limiting_factor` on fire turns in an existing batch.
- **`BatchMain` exits 0 on a 100% crash rate**; `summarize` NPEs on a malformed winner index; `forkCommit` is CWD-dependent and swallows to `"0000000"` (P2, ◐).
- **Stall dumps use a CWD-relative dir and a 32-bit `String.hashCode()` filename** (P2, ◐; Gemini also flagged the hash).

### 4. Combo planning, prep, ingestion — reviewer B, verified by Fable where marked

- **#3 dossiers untracked** (✔). The memory notes say this is a deliberate convention ("the PACKAGE carries it"). The risk is unchanged by being deliberate: the authored inputs (`combo-program-*.json`, `pairing-program-*.json`, `engine-program-*.json`, `discovered-*.json`) have no history, no review, and no backup. Track the authored inputs; keep the derived caches ignored.
- **#4 dossiers fail their own gate** (✔ on Giada). Cause is #14: `arena-add-deck.py` rewrites `deck-cards.json` after `PrepMain` hashed it.
- **#14 two ingestion paths** (◐ on schema counts). 6 of 10 dossiers have no `dossier.json` and can never be a batch seat.
- **#12 basic-land list in `PairedPlay`** (✔). `SeatView.OpponentView.battlefield()` is a name set with no types; the fix has to carry a type bit.
- **#13 misclassified draw engines** (✔ on shipped Giada data). Strip parenthesised reminder text and reject symmetric draw clauses in `classifyCard`; neither names a card.
- **#15 `firedShortcuts` overloaded** (✔).
- **Known archetype with a missing param throws out of `executorFor` into the game loop** (P1, ✔ no guard). The schema's "data can never crash a batch" holds only for unknown archetype names.
- **`BindGen` can generate one of seven archetypes and lints every archetype as `TapForManaUntapLoop`** (P1, ◐). 0 of 26 shipped bindings carry provenance; 34 proposal rows. It is a proposal writer today.
- **Non-atomic, unlocked rewrites of the hand-curated bindings library and route library** (P1, ◐). `SpellbookClient` shows the temp+`ATOMIC_MOVE` pattern in the same package.
- **`StallAutopsy`'s deck gate is a substring test an empty string passes, can select the wrong deck, and reads an arbitrary `dump_path` from a JSON event into an external API call** (P1, ◐).
- **`arena-add-deck.py`'s DFC whitelist misses the `room` layout** (P1, ◐). Sythis's `Secret Arcade // Dusty Parlor` is correct today and the next ingest run rewrites it to the front face, reopening the class of defect fixed in `ee3e4962796`. `DeckLoadProbe` already answers the right question; it just runs after the rename decision.
- **`deck-cards.json` holds Scryfall `A // B` names while the live game reports front faces** (P1 latent, ◐). 48 such names across the ten dossiers; none currently reaches a payoff/tutor/protection list, so it is a landmine, not a live fault.
- **Three disagreeing closed sets of payoff classes** (23 constants / 17 assignable / 11 in the route-library schema); the classes the conversion planner most needs (`x_spell_outlet`, `unspent_mana_grant`, `damage_amplifier`) can be added by neither human nor model (design, ◐).
- **`combo/` depends on `prep/` (`PayoffRules`, `ProtectionFinder.Scope`)**, which also holds the network clients the docs say the game loop must never reach; the ArchUnit test does not see it (design, ◐).
- **Program JSONs are accreted, not modelled**: 22 top-level keys, `program_class` in 9 values, the outlet expressible in four shapes, class-specific bodies validated as bare objects (design, ◐).

### 5. Tests and the gate — reviewer D, Gemini

- **A third of the suite cannot run on a clean checkout** (#3). Only `DeckSwapSafetyTest` guards for absence; the rest throw `NoSuchFileException`.
- **No wire-contract test in either language.** 14 decision types and ~20 state keys are specified in prose and enforced by `String.contains` in test brains. Project 1 has 23 schemas and two validation classes for its artifacts; Project 2's actual IPC boundary has zero. `SafeDefaultAlwaysLegal` proves two Python functions written together agree; there is no `CHOOSE_CARDS`, `PAY_UNLESS`, or `CONFIRM` fixture.
- **The "never hangs" degradation path has no test.** No test starts a game with no brain, a dead brain, or a late brain. `arena.mailbox.poll.ms=5` is already pinned for speed; a no-brain test costs seconds.
- **Four seam tests still use the probe regex INVENTORY forbids** (`"id"\s*:\s*(\d+)[^}]*<Name>` across the whole body); `MailboxTestKit.idOf` has the strict form.
- **Five live-shaped tests do not scope to the seam they name** (`SelvalaManaLoopTest` counts all `mana_pair` drills; `GoldfishGauntletTest` counts any shortcut; `DreadnoughtWindowTest` accepts a win by another line; `LethalDrillTest` arms the drill by hand; `TriggerSurfacesReachMailboxTest` documents trigger targeting as covered and does not test it).
- **Three tests assert nothing**; one of them (`ArenaGameStateTest`) is the sole reference to a dead 20-line class; `SelvalaGoldfishRun` never executes because its name misses surefire's includes.
- **Eleven classes leak 150-second polling threads** into the single reused fork (Gemini flagged this too; the `-Xmx4g` pom setting treats the symptom).
- **Ten seam regressions are pinned to one card each**, against the project's own ≥2-cards rule; `TapSymmetryBreakTest` and `SacrificeSeatChoiceTest` show compliance.
- **Determinism is proven for two 4-turn stock games in one JVM**; not across JVMs, not with combo-aware seats (whose `GameSimHandle.copyOf` consumes the game thread's RNG), not after a timeout.
- **Zero unit coverage of `ComboPilot`'s program surface** (eleven public methods with no test hits), of `advisor_runner.py` (404 lines), of `SeatRunner.handle()` end to end, of any shell script, of `MailboxController` in isolation.
- **Gate weaker than described** (#20).

### 6. Documentation drift — reviewer D

INVENTORY's upstream-divergence list (§1a/§1b), the part that protects a rebase, is **correct**. Everything else has drifted: three different test counts in three files (292 / 308 / actual 340), Python tests 110 vs 124, README "current (v3.1)" vs v3.3.2, INTERACTIVE-ARENA "refreshed 08-17" vs an 08-31 file, `__pycache__` "should be gitignored" when it is, and §6's "dossiers tracked" when `.gitignore` says otherwise. Missing entirely: `deckcheck-import.py`, `DeckLoadProbe`, `banlists/`, `bindings/`, `route-library/`, `schemas/`, ~50 of ~60 files under `docs/`. Fifteen of eighteen behavioural claims sampled in INTERACTIVE-ARENA and the README verify exactly against code; the stale three are the 0.5 s seat poll (now 0.15 s since 08-13), the 292-test gate, and JDK 17.

### 7. Security and safety

Low exposure overall. Credentials are read in-process and sent as headers; `arena-play.sh` strips backend keys from the advisor and GUI environments; no `eval`, `exec`, or `shell=True` anywhere; LLM output reaches only `json.loads` and whitelist validation; the model has no tools. Items:

- `gemini_wholedeck.py` puts the API key in the URL query string (use `x-goog-api-key`).
- `backends.py` logs provider error bodies verbatim (120 chars); some providers echo keys. Redact before logging.
- `StallAutopsy` reads a filesystem path from a JSON event and ships the contents to an external API with no confinement.
- `run-pilot-match.sh` interpolates `ARENA_SEAT_DECKS`/`ARENA_AUTOPASS` unquoted into the JVM argv while whitelisting `ARENA_SEAT_MODELS` two lines below.
- `merge_discovery.py`, `anchors.py`, `gemini_wholedeck.py` take an unvalidated deck slug into paths.
- `pkill -f` teardown can kill unrelated processes whose argv mentions `GuiPilotMatch`.
- Gemini's prompt-injection-via-deck-file concern is real in principle and irrelevant in practice for a single-user local tool; noted, not ranked.

## Architecture and object model

Five themes recur across every reviewer:

1. **Two god classes carry both projects.** `MailboxController` (3,433 lines, 40 overrides) and `ComboAwareLobbyPlayer` (2,464 lines, eleven runner lifecycles, combat math, drill state machine). Both are testable only through full games, which is why the suite takes six minutes and why the seam tests are one-card-deep. The extractable pieces are clear: state projection out of the controller; combat lethality math out of the lobby player; a `Runner` interface plus abstract base under the eleven runners.
2. **The mailbox contract lives in prose and two hand-maintained implementations.** The fix is a schema per `decisionType` emitted by Java and loaded by Python, plus one Java test that feeds every `safe_default()` output through the controller. This single change closes the largest class of silent breakage in Project 2.
3. **"Seat" is `Player.getId()` by coincidence.** Both projects assume seats are positional 0-3 and equal to Forge's player id; nothing asserts it. An upstream change to id allocation breaks mailbox directories, deck-to-seat mapping, control files, ratings attribution and drill target labels simultaneously and silently.
4. **Card names where mechanics should be.** `SelvalaManaLoopRunner`'s ladder and god plan, `FLIP_DRAW_ENGINES`, `PairedPlay.BASIC_LANDS`, `amplifierNames`, three disagreeing autopass allowlists, `SeedbornEngineRunner`'s default untapper. The project's own rule is right and the general mechanisms mostly already exist next to the hard-coded ones.
5. **Silent degradation is the default failure mode.** Five swallow-and-continue paths in the combo layer, `catch (IOException ignored)` on dossier discovery, ten runner constructors that `catch (Exception) { p = null; }`, `ExecutorBindings.load` returning empty on a missing file while `RouteLibrary.load` refuses. A combo-aware seat can run a whole batch with nothing loaded and the manifest says `combo_aware: true`.

The parent-module patch footprint is 16 files / ~860 lines, all marked, all additive. That is a manageable sync burden, but the real upstream coupling is not there: it is the 40 overridden `PlayerControllerAi` signatures, the raw card-script parameter strings (`RestrictValid`, `Produced`, `Amount`, `Origin`), the public `CostRemoveCounter.counter` field, and `GameCopier` internals that `GameSimHandle` repairs by hand. None of that is compile-checked against a contract.

## Calibration: where the sources disagreed

- **Gemini P0 "infinite loop on unpayable spell"** → P1. It is a livelock costing one model call per iteration, not a hang; the brain sees identical options and will usually pick differently. The real defect is that the brain is never told. (#10)
- **Gemini P0 "stale-response TOCTOU"** → P2. `protocol.py` already sweeps the outbox at startup, re-checks the request before writing, and GCs its own late response. The residual is the in-JVM second-match case reviewer C found (#19), which is a missing sweep on `game_reset`, not a race.
- **Gemini P0 "cross-process append tearing on `game-records.jsonl`"** → P2 hardening. POSIX guarantees `O_APPEND` offset atomicity, not payload atomicity for large writes, so tearing is possible in principle on records over a page; not observed, and per-worker files would remove the question.
- **Gemini P1 "commander damage ignores amplifiers"** → P2. Confirmed in source, but `lethalAlphaOrder` is a deliberate lower bound; missing a kill is the accepted direction. Reviewer A's point that `amplified()` itself is regex-on-prose is the more important finding.
- **Gemini P1 "ObserverSnapshot concurrent writes"** → P2. Guava dispatches on the posting thread and Forge posts from the game thread; concurrent writes need an off-thread event. A `synchronized` costs nothing and should be added anyway.
- **Gemini's "replace filesystem IPC with sockets"** is a preference, not a finding. The file bus is careful, observable by a human with `ls`, and survives either process dying. The measured 75 ms + 150 ms poll floor is the cost; a game id in the protocol buys more than a socket would.
- **Reviewer A vs the project on `SeedDeterminismTest`**: the test is honest about what it runs; the gap is that the production configuration (combo-aware seats, separate JVMs, wall-clock timeouts) is never the one tested.
- **Reviewer B's #3 (dossiers untracked)** conflicts with a recorded decision that dossiers are disk-only and the package carries them. I keep it at P0 because the decision protects the repo from churn and does nothing for the authored programs, which are the asset.

## Suggested sequencing

Cheap and high-value first; structural work after.

**Week 1, one-screen fixes:**
`runOne` catches `Throwable` and always records (#2). `getAi()` becomes a delegating decorator (#5). Dispatch branches check `first != null` (#6). `_call` gets the remaining budget (#7). Memo only on `source == "model"` (#8). Trigger aim checks `isMandatory()` and treats a null exchange as stock (#9). Refused cast writes a `lastRefused` note into the next request (#10). `game_reset` sweeps the outbox (#19). Packager collects missing jars and checks after the loop (#16). `firedShortcuts` split into `bankedPool` and `firedCombos` (#15). Strip reminder text and reject symmetric draws in `classifyCard` (#13). Guard `buildExecutor`. Add `@Override` to `confirmAction`; delete the dead `chooseCardsForZoneChange`.

**Week 2, contracts:**
A `gameId` field on every mailbox request and in the advisor feed; both Python readers key reset and sweep off it (#11, #19). A Java test that emits one request per `MailboxController` branch and validates every `safe_default()` answer against it. A no-brain / dead-brain / late-brain test. Track the authored program inputs (#3) and re-run `PrepMain` so the dossier hashes are true again (#4). Point the schema sweep at generated artifacts, not fixtures.

**Month 1, structure:**
Fix the wall-clock timeout path to end the game on the game thread (#1). One ingestion writer (#14). A `Runner` interface under the eleven runners. `SeatView.OpponentView` carries card types so `PairedPlay` stops guessing (#12). Move the Selvala ladder and god plan into program JSON (#17). Extract combat math from `ComboAwareLobbyPlayer` and state projection from `MailboxController`. PID-file teardown. Refresh INVENTORY from the tree.

Everything in this document is a finding, not a change; no file outside `docs/reviews/` was touched.
