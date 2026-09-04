# forge-arena review, round two — Fable 5.1 reviewers, blind, compared with Opus round one

Date 2026-09-04. Tree at `916bee81fbd` (everything from the affirmed interactive plan, items 1–16, is in; live game 19 has been played on it). Companion to `2026-09-03-full-review.md` (round one) and `docs/BUG-LOG.md` (the running ledger, updated from this document).

## Method

Round one (2026-09-03) used four Opus reviewers, one per area, plus Gemini over the same source bundles, plus my own direct read. Round two re-ran the same four briefs and the same three Gemini bundles with **Fable 5.1 reviewers**, on the tree *after* the sixteen fixes, **blind**: no bug log, no list of what had changed, no round-one reports. The point was to see what a stronger reviewer finds unaided, and to see whether it notices the code that changed the same day.

Every claim in this document that carries a verdict was checked by me against source before it was written down. Tags: **✔** I re-derived it; **◐** the reviewer's citation is correct and the mechanism reads right but I did not execute it; **✘** refuted.

Cost of round two: four Fable agents, 350–630k tokens and 13–21 minutes each (the tests/docs reviewer was the outlier at 629k and 21 minutes); Gemini three passes of ~250k tokens each, under two minutes each.

## Headline

1. **Fable found everything Opus found that is still open, and about twenty things Opus did not.** The additional finds are mostly one causal step deeper than Opus stopped: not "this set is overloaded" but "because it is overloaded, this expiry branch is dead code and the pilot runs a phantom conversion for eight turns"; not "counting per event" but "so a deck whose programs are all unreadable passes the conversion floor at 100 %".
2. **Fable noticed the code that changed yesterday and found three collateral defects in it**, which is the strongest evidence that the blind read was real: the per-game log symlink (item 13h) silently broke the digest watcher and the stop-time count; the contract test (item 15) writes tracked files; the cycle-replay path is the untouched sibling of the punt-memo bug fixed in item 3.
3. **One new P1 has an outward-facing consequence and needs a decision now.** The shipped v3.3.2 tar on the public bucket carries three DeckCheck API payloads under `decks/*/dossier/.cache/`, each with the account's `creator.username`, `creator.avatar` and `is_owner`. Nothing at runtime reads that cache. See BL-18.
4. **One new P1 is a design question, not a bug.** The runner's punt produces a *legal* answer (no blocks, no attackers, first legal id, keep hand, pass priority) where the engine would have handed the decision to stock Forge AI. The README's "never worse than a normal Forge opponent" is therefore not true on a timeout. See BL-19.
5. **Gemini round two repeated round one.** Same shape, same two loud P0s that do not survive (a "compilation error" on an overload that exists; "shared state corruption" that stock Forge AI performs identically), three sound P2s, and no awareness of what changed. A 250k-token cold read produces roughly the same list twice.

## Scorecard

| Area | Opus (round one) | Fable (round two, blind) | Overlap on the still-open items | New in round two, verified | Opus items Fable did not re-find |
|---|---|---|---|---|---|
| A engine / harness / report | 38 ✔ / 4 ◐, top-10 led by wall-clock, ArenaRunner, `getAi()`, dispatch `return first` | 20 ✔ / 6 ◐, 21 bugs, 9 design, top-10 led by the same three | wall-clock (HL-01), ArenaRunner (HL-02), second `AiController` (HL-05), Selvala names and oracle regex (HL-10), white-only pips (HL-10), swallowed discovery IO | funnel counts dispatches as fires and counts per event (P1); `Map.of` breaks cross-JVM byte determinism; worker stride aliases the latin-square offset; `activateAtOpponent` never sets `lastFailure`; drawn/discarded telemetry counts tutors | dispatch `return first` on null step (HL-06) |
| B combo / prep / bindgen / ingest | 31 ✔ / 3 ◐ | 31 ✔ / 4 ◐, 19 bugs, 9 design | gitignored dossiers (HL-03), two ingestion pipelines (HL-04), `firedShortcuts` overload (HL-09), `BASIC_LANDS` (HL-07), one-archetype BindGen (HL-11), Gemini key in URL, broken `build-ingestion-packages.py` | `bankedPhase` compares phase *names*, so `pool_expired` is dead code and conversion state survives across turns (P1); program dispatch fabricates conversion state (P1); `arena-add-deck.py` output violates both schemas it tags, `TutorWeights` NPEs on it (P1); `ProgramGate` derives `""` card names for template pieces; events schema omits ~12 emitted types; four cost parsers with three X policies | `PayoffRules` Clue/symmetric-draw false positives (HL-08) |
| C Python runner / scripts / packaging | 24 ✔ / 4 ◐ | 13 ✔ / 7 ◐, 15 bugs, 8 design; also mined 222 archived seat logs (17,553 decisions) for ground truth | none of Opus's top items remain (all fixed yesterday); agreed posture on validation, keys, no `eval` | punt-vs-stock policy (P1, design); cycle replay records and replays punts; digest watcher and stop count broken by the per-game symlink; `replay.py` ships without its fixtures; Java never sweeps a stale outbox at construction; `DECLARE_ATTACKERS` stricter than `chooseDefender`; `ratings.sweep` globs before it locks; `claude -p` inherits the operator's CLAUDE.md and hooks; whitespace in deck names; advisor unsupervised with an unguarded log write | `pending_context` unbounded (BL-13); `_cycle_rebind` prefix binding (BL-08); `ObserverSnapshot` debounce trailing edge (BL-07); add-deck quantity regex (BL-14) |
| D tests and docs | ~50 concrete checks | 96 classes assessed one by one, 20 stale doc claims, 15 verified claims, dead-code census | unreproducible gate (17 classes on gitignored dossiers), fallback invariant tested once, `-Dmaven.test.skip` bypass, `SelvalaGoldfishRun` never runs, assertion-free tests, single-card seam tests, INVENTORY counts | contract test writes tracked fixtures; child surefire `argLine` replaces the parent's `--add-opens`; REACT gating and combat declaration have no E2E test; Java-side malformed-answer matrix missing; README documents a `--verify` flag that does not exist and the wrong launch order; INTERACTIVE-ARENA header still says v3.2, nine decks, react-autopass shipped; `announceRequirements` pinned by a test on a documented dead path | (none material) |

Calibration: Fable's CONFIRMED tags held up in every case I checked (about forty). Two of its findings I would soften rather than refute: the heartbeat's "process alive" semantics is the simplified design Ben affirmed in item 12, not a defect, and the `a || b && c` predicate in `GuardedCastTargetIntegrityTest` reads as intended. Opus's CONFIRMED tags also held in round one; the difference is reach, not accuracy.

## What both rounds agree on

These are already in the bug log. Fable's reports add line-level mechanism to each and change no severity: HL-01 wall-clock (Fable adds that `EventRecorder.close` is unsynchronized, so the zombie thread can write after `game_end` and break the canary's last-line assert), HL-02, HL-03, HL-04, HL-05, HL-07, HL-09, HL-10, HL-11, the unreproducible gate, the single-surface fallback test, `-Dmaven.test.skip`, the never-run goldfish class, INVENTORY drift.

## New in round two, verified

### Interactive (Project 2), added to the bug log

| ID | Sev | Finding | Verdict | Fix |
|---|---|---|---|---|
| BL-18 | P1 | **DeckCheck payloads ship in the public package.** `build-light-package.sh` rsyncs `dossier/.cache/` per deck; `forge-light-llm-20260901.tar.gz` (also `-latest`) contains `deckcheck-*.json` for three decks with `creator.username`, `creator.avatar`, `is_owner`, `deckview_id`. No runtime path reads `.cache` (grep of runner, interactive, bootstrap, launch scripts). | ✔ | Drop the rsync line, or exclude `deckcheck-*.json`; re-cut and overwrite `-latest` with the next release (BL-17). |
| BL-19 | P1 | **Punt policy.** `rules.safe_default` answers every punt legally: no blocks, no attackers, first `min` ids, keep, pass priority. The engine treats a *null or non-conforming* response as "fall to stock" on every one of those surfaces (`super.declareBlockers` etc.). So a timed-out lethal `DECLARE_BLOCKERS` becomes "no blocks" where stock would chump. `packaging/README.md:13-15` claims the opposite. The explicit stock counter in `exchange()` only counts nulls, so these punts are invisible to item-12's telemetry. | ✔ | Ben's call. Cheapest correct form: a `{"stock": true}` answer the engine maps to the stock path and counts; the runner emits it on model failure for the stateful kinds and keeps `safe_default` only where the two coincide (`CHOOSE_NUMBER` puntHigh, CONFIRM item-10 rule). Fix the README sentence either way. |
| BL-20 | P2 | Cycle replay appends every answer to `_hist`, including `source == "punt"`, and `_cycle_try_arm` does not refuse a punt. A punted CONFIRM inside a loop replays the decline up to 64 rounds as source `cycle`, uncounted as punts. Sibling of the item-3 memo bug. | ✔ | Append to `_hist` only for real sources; refuse to arm across a punt; test. |
| BL-21 | P2 | Item 13h collateral: `arena-digest.py` opens `game.jsonl` once and the symlink is re-pointed per game, so the digest goes silent after game one; `arena-stop.sh` counts only the current game but says "(preserved)"; README and INVENTORY §6 still describe an append-only file; `runner/replay.py` reads `tests/fixtures`, which the package excludes. | ✔ | Inode-aware reopen in the digest; honest stop count; doc sentences; ship the fixtures or drop `replay.py`. |
| BL-22 | P2 | `MailboxProtocol`'s constructor never sweeps `outbox/`. After a JVM crash with a `resp-1.json` left behind, a hand relaunch (bypassing `arena-stop`) lets the new engine consume the stale response before the runner's gameId sweep runs. | ◐ | Sweep the outbox in the constructor; Python GCs a lingering resp when the next same-game request appears. |
| BL-23 | P2 | `rules.validate` hard-rejects a missing `defender`; `chooseDefender` accepts it when exactly one defender is legal. With one opponent left a Java-legal answer becomes `{"attackers": []}` via the punt. | ✔ | Accept a missing defender when `defender_ids` has one entry; update the pinned test. |
| BL-24 | P2 | `claude -p` runs with `cwd` at the repo root and default settings, so every call loads `/Users/toor/Claude/CLAUDE.md` and project settings and fires user hooks. `--bare` is not an option (it disables OAuth, and the seats run on the subscription). | ◐ | `--setting-sources ""` for hooks; `cwd` in an empty directory outside `~/Claude` for CLAUDE.md discovery; pin both in the golden argv test. |
| BL-25 | P2 | Tests: `ProtocolContractTest` writes ten tracked fixtures (dirty tree on drift, throws on a read-only checkout); the child `<argLine>` replaces the parent's `--add-opens` set; REACT gating and combat declaration have no end-to-end test; the Java side has one malformed-answer test in total. | ✔ | Compare-and-fail with an explicit refresh flag; inherit the parent argLine; a `SILENT`-brain matrix over every decision type; a negative-answer data provider. |
| BL-26 | P2 | `ratings.sweep` globs before taking the lock and renames a path that a concurrent sweeper may have moved; `process_spool` indexes spool keys directly. Advisor `_record` writes its jsonl unguarded and the advisor has no restart loop. | ✔ | Glob under the lock, guard the rename, validate keys; guard the write; supervise like the seats. |
| BL-27 | P2 | `extract_json` slices first `{` to last `}` and mana symbols in prose defeat it (plausible); whitespace in a deck name word-splits in three scripts; the `arena-stop` fallback `pkill` is repo-agnostic. | ◐ | `raw_decode` walk with tests; slugify or reject whitespace with a message; scope the fallback to `$ROOT`. |
| BL-28 | P2 | From Gemini round two, verified: `gameId` is millis+pid so two games in one millisecond in one JVM collide; the runner has no SIGTERM handler, so teardown orphans one in-flight `claude` child per seat; the mtime fallback grants a fresh window when the request file has vanished. | ✔ | Counter suffix; signal handler that terminates the child; punt when the file is gone. |

BL-16 (docs drift) is extended with Fable's concrete list: README's `--verify` flag does not exist; README gives the launch order as teardown → preflight (it is preflight → teardown); `--advisor` is a no-op (advisor is on by default); INTERACTIVE-ARENA's header still says v3.2, nine decks and a shipped react-autopass; the or-models path is `logs/cache/` not `logs/control/`; field notes 53 and 57–60 are out of order; INVENTORY §1c describes an ArchUnit rule the test does not enforce (it fences game internals, not GUI imports, and `bootstrap` imports GUI).

W-5 (watch): heartbeat liveness means "process alive". Through a 60–90 s pre-warm or a crash-restart loop the engine waits the full timeout per decision. This is the simplified item-12 design; measure before changing.

### Headless (Project 1), recorded and deferred like the rest of HL-*

| ID | Sev | Finding | Verdict |
|---|---|---|---|
| HL-13 | P1 | The combo funnel counts program *dispatches* as fires (`combo_shortcut` emitted before a runner exists) and `BatchStats` increments `shortcutGames` / `eventualWinAfterFire` / `sameTurnConversions` per event with no per-game dedupe, unlike `readyGames`. A deck whose programs are all unreadable passes `PilotFloors` at 100 %. | ✔ |
| HL-14 | P1 | `pooledManaStillLive` compares `bankedPhase` to `view.phase()`, a phase *name*; `convert()` only runs in MAIN1, so the comparison is always true, `pool_expired` is dead code, and banked-pool state survives across turns. Program dispatch also sets `bankedPhase`/`currentRoute` with no pool injected. Deepens HL-09. | ✔ |
| HL-15 | P1 | `arena-add-deck.py` writes `combos.json` and `deck-cards.json` that violate the schemas they tag (`spellbook_snapshot` is an int, `deck_hash` missing, `mana_needed` null, `zone_req` missing; deck-cards rows carry `layout`/`scryfall_id` under `additionalProperties: false`). `TutorWeights` NPEs on `deck_hash`. Verified on the sheoldred dossier. Deepens HL-04. | ✔ |
| HL-16 | P2 | `Map.of("combat", …, "other", …)` in `GameEventBridge` and two `ComboPilot` sites: iteration order is per-JVM salted, so cross-process byte determinism does not hold; `SeedDeterminismTest` is single-JVM. | ✔ |
| HL-17 | P2 | Worker stride equals the latin-square offset with default counts, so a worker that dies after three respawns removes one whole seating arrangement from the batch; `summarize()` does not warn. | ✔ |
| HL-18 | P2 | `ProgramGate.deriveFixture` yields `""` card names for `{"template": …}` pieces (six Urza programs), producing `flagged engine_crash: NullPointerException` verdicts that blame the engine. | ◐ |
| HL-19 | P2 | The events schema's closed `t` enum omits about twelve emitted types (`pool_expired`, `program_abort`, `engine_cycle`, `pairing_*`, …); `ComboPilotTest` validates every event, which is one reason those paths have no tests. | ✔ |
| HL-20 | P2 | Four mana-cost parsers with three X policies (`X→1`, `X→xValue`, `X→0`); the compiled pairing estimate and the legacy `PairedPlay` price the same pair differently. `ProgramRunner` swallows its own parse failure with no event; `activateAtOpponent` returns false without `lastFailure`. | ◐ |

## Refuted or not sustained

- Gemini round two P0 "`MagicColor.fromName(char)` is a compilation error": the `char` overload exists (`MagicColor.java:73`). ✘
- Gemini round two P0 "`setActivatingPlayer` during enumeration corrupts shared state": stock Forge AI does the same on the same objects in every window. ✘
- Gemini round two P1 "REACT memo ignores mana and hand": the signature includes options, every seat's life and the seat's own pool, and REACT options are affordability-filtered. ✘
- Gemini round one's P0s (record-writer torn appends, path traversal in dossier loading) remain overstated for a local single-user tool; the append size point is real and is in HL-*.
- Fable runner B10 (heartbeat semantics) is the affirmed design; kept as W-5, not a bug.
- Fable tests-docs' precedence note on `GuardedCastTargetIntegrityTest:209` reads as the author's intent (orb gone, or hand refilled with an empty stack).

## The reviewers, compared

**Depth.** Opus stopped at the defect; Fable followed the defect to its consequence and usually to the test that should have caught it and why it could not. Three examples: the dead `pool_expired` branch (Opus saw the overloaded set, not that the expiry can never fire); the funnel (Opus saw `firedShortcuts` double duty, not that `BatchStats` counts per event); the DeckCheck payload (Opus listed `.cache` as "tracked" in a drift table, Fable asked what was in it).

**Ground truth.** The Fable runner reviewer read the 222 archived seat logs and computed the punt/wedge/timeout/cycle counts before writing, and used them to classify the multi-thousand-second `WINDOW LOST` lines as laptop-sleep artifacts (monotonic vs wall clock) rather than reporting them as a bug. Opus reasoned from code alone.

**Handling of yesterday's changes.** Fable did not re-report anything fixed in items 1–16, and found three defects in the changed code (BL-20, BL-21, BL-25). It also correctly described item 2's deadline discipline, item 12's heartbeat, item 13h's symlink and item 15's fixture flow as they now are. Gemini described several of them as they were before.

**Misses.** Fable did not re-find four small open Opus items (BL-07, BL-08, BL-13, BL-14) and, on the headless side, HL-06 and HL-08. None is large. Opus did not find any of the twenty new items, which is the expected direction given the model gap.

**Calibration.** Both tagged CONFIRMED/PLAUSIBLE honestly. Fable used PLAUSIBLE more often on the runner (7 of 20), always where execution would have been needed. Gemini's severity labels are not usable without verification in either round.

**Cost.** Fable reviewers ran 350–630k tokens and 13–21 minutes each, roughly 1.3–2× the Opus reviewers. Per verified new finding the Fable round was cheaper.

## Recommended order (Ben's call)

1. **BL-18** — strip the DeckCheck payloads from the package and re-cut `-latest` (folds into BL-17, which is already staged in PATCH-NOTES).
2. **BL-19** — decide the punt policy. It changes what a timeout costs on every stateful surface.
3. **BL-21 + BL-20** — the 13h and item-3 collateral; small, tested, closes the round-two loop on yesterday's work.
4. **BL-22, BL-23, BL-28** — protocol edges; each a few lines with a test.
5. **BL-24** — `claude -p` isolation; one argv change and one `cwd`.
6. **BL-25, BL-16** — test-side and doc-side hygiene when next in those files.

## Sources

Scratchpad `review/`: `fable-engine.md`, `fable-combo-prep.md`, `fable-runner.md`, `fable-tests-docs.md` (round two); `agent-*.md` (Opus, round one); `gemini2-*.md` and `gemini-*.md`; `brief.md` (the shared reviewer brief).
