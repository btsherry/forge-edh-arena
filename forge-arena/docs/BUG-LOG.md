# Bug log — outstanding items

Opened 2026-09-04 after the full review (`docs/reviews/2026-09-03-full-review.md`), the affirmed interactive plan (`docs/reviews/2026-09-03-interactive-plan.md`, items 1–15 shipped, 16 measuring) and live game 19. Extended the same day from the blind round-two review (`docs/reviews/2026-09-04-round-two-comparison.md`): BL-18..28, W-5, HL-13..20, and the BL-16 list. Every entry is something NOT yet fixed. Severity: **P0** corrupts state/data or a batch; **P1** wrong behaviour in play or measurement; **P2** minor or latent. Status is the only field that changes; close an entry by moving it to the "Closed" section with the commit.

Conventions still in force: seam fixes are general (mechanics, never card names); regression tests span ≥2 cards; parent-module changes take the FULL gate; capture Maven's exit status, never a filtered tail.

## Interactive (Project 2) — open

| ID | Sev | Area | Item | Evidence | Proposed fix |
|---|---|---|---|---|---|
| BL-04 | P2 | mailbox surfaces | Combat damage assignment (multi-block splits), convoke/improvise payment, spell-for-effect choice stay on stock. | Game 19: `assignCombatDamage` 1×, convoke 9× (repeated planning consultations per window), spell-for-effect 0×. | Open by evidence after a few more games; convoke needs the payment-context gate (item 10's F2 lesson) so planning scans don't open windows. |
| BL-06 | P2 | mailbox | Timeout on a silent brain still costs one full wait per decision once (the heartbeat gate only helps when the runner PROCESS is gone). | Design decision (item 12 simplified); item 2 makes wedged models punt on time, so exposure is one window. | Leave unless measured; revisit with the surfaces above. |
| BL-17 | P2 | release | **v3.3.3 cut in progress (2026-09-04).** `PATCH-NOTES.md` "Unreleased — after v3.3.2" is written; the shipped `-latest` on R2 predates every fix in this log's closed section. | — | Standard pipeline when Ben says go: fresh gate → `build-light-package.sh --force` → tar → REST-R2 PUT dated + `-latest` → verify hashes. |

## Interactive — watch items (not bugs yet)

- **W-1** Surface-count instrumentation (`STOCK-SURFACE`) counts engine consultations; convoke and color are consulted many times per window. De-duplicate by (seat, turn, phase, surface) before comparing.
- **W-2** A resumed Claude session hung three times in a row (game 19, seat 1, 72 s each) before the wedge rule fired. Three punts is ~3.6 minutes of stock play at 90 s. If it recurs, lower `WEDGE_FAILS` to 2 or shorten the second attempt.
- **W-3** Ratings void any game with a wedge; with wedges now cheap (item 2), consider voiding only when punts exceed the threshold.
- **W-4** `manaAvailableNow` counts one activation per source; the brain still misjudged Gemstone Caverns once (t42) — confirm the `restricted`/condition flags read right for condition-forked sources.
- **W-6** Two colour paths can open a COLOR window mid-payment by design of the Mana-api bypass (review 2026-09-04): `ManaEffect.handleSpecialMana` for EnchantedManaCost / EachColoredManaSymbol producers (Elemental Resonance, Charmed Pendant — neither in a shipped deck) and `specifyManaCombo` once per mana for a multi-mana combo source when the brain floats it deliberately. Watch the STOCK-SURFACE/COLOR counts; if a shipped deck hits it, narrow the bypass to Amount 1.
- **W-7** `chooseColors` with `min = 0` ("UpTo" colour effects, no shipped script uses one) cannot answer "no colour" except through the hand-back to stock.
- **W-5** Heartbeat liveness means "process alive", not "loop can answer": through a 60–90 s pre-warm or a crash-restart loop the engine waits the full timeout per decision. This is the simplified item-12 design Ben affirmed; measure before changing (round two, Fable C B10).

## Headless harness (Project 1) — deferred by decision 2026-09-03, recorded for reference

Ben removed these from planning. Listed so they are not lost; details and line numbers in `docs/reviews/2026-09-03-full-review.md` and the reviewer reports it cites.

| ID | Sev | Item |
|---|---|---|
| HL-01 | P0 | `EngineFacade` wall-clock timeout calls `setGameOver` from the harness thread while the game thread still runs; the abandoned 64 MB thread writes into a closed recorder for the worker's life. |
| HL-02 | P0 | `ArenaRunner.runOne` lets setup exceptions escape: no `GameRecord`, recorder leaked, worker killed, stride lost after 3 identical retries. |
| HL-03 | P0 | 53 combo programs, 18 pairing programs, 1 engine program are gitignored (`decks/*/`); 25 tests error on a clean checkout, `ProgramSchemaValidationTest` passes vacuously. Track the authored inputs. |
| HL-04 | P0 | Every Java-prepped dossier fails `DossierCheck` (`deck_cards` sha mismatch, caused by `arena-add-deck.py` overwriting). Two ingestion writers → one. |
| HL-05 | P1 | `ComboAwareLobbyPlayer.getAi()` returns a second `AiController`; 62 upstream call sites consult a brain that is not deciding; card memory never reset. |
| HL-06 | P1 | Nine of eleven program-dispatch branches `return first` on a null first step, forfeiting the priority window. |
| HL-07 | P1 | `PairedPlay` decides "land" from an 11-name basic-land list; land wipes score near zero against real manabases. |
| HL-08 | P1 | `PayoffRules` matches Clue reminder text and symmetric draws: Loran, Wojek Investigator, Minas Tirith shipped as draw engines. |
| HL-09 | P1 | `firedShortcuts` doubles as "pool banked" and "combo fired"; `convert()` clears it for every combo on phase change. |
| HL-10 | P1 | `SelvalaManaLoopRunner` embeds ten card names and a Rhonas/Nylea plan; `amplified()`/`perEtbDamage()` parse oracle prose; `PairingRunner` pip check is white-only. |
| HL-11 | P1 | `ExecutorBindings.executorFor` throws out of eight unguarded call sites on a known archetype with a missing param; `BindGen` lints every archetype as `TapForManaUntapLoop`; bindings/route library rewritten non-atomically. |
| HL-12 | P2 | `BatchMain` exits 0 on 100% crashes; stall dumps CWD-relative with 32-bit hash names; dead `chooseCardsForZoneChange` override; `confirmAction` lacks `@Override`; `StallAutopsy` deck gate is a substring test and reads an arbitrary `dump_path`. |
| HL-13 | P1 | Combo funnel counts program *dispatches* as fires (`combo_shortcut` before a runner exists) and `BatchStats` increments `shortcutGames`/`eventualWinAfterFire`/`sameTurnConversions` per event with no per-game dedupe; a deck whose programs are all unreadable passes `PilotFloors` at 100 %. (round two) |
| HL-14 | P1 | `pooledManaStillLive` compares `bankedPhase` to a phase *name* and `convert()` only runs in MAIN1, so `pool_expired` is dead code and banked-pool state survives across turns; program dispatch sets `bankedPhase`/`currentRoute` with no pool injected. Deepens HL-09. (round two) |
| HL-15 | P1 | `arena-add-deck.py` writes `combos.json`/`deck-cards.json` that violate the schemas they tag (`spellbook_snapshot` int, no `deck_hash`, `mana_needed` null, no `zone_req`; `layout`/`scryfall_id` under `additionalProperties: false`); `TutorWeights` NPEs on `deck_hash`. Verified on sheoldred. Deepens HL-04. (round two) |
| HL-16 | P2 | `Map.of` in `GameEventBridge:138` and two `ComboPilot` sites: per-JVM salted iteration order breaks cross-process byte determinism; `SeedDeterminismTest` is single-JVM. (round two) |
| HL-17 | P2 | Worker stride equals the latin-square offset with default counts; a worker dead after three respawns removes one whole seating arrangement and `summarize()` does not warn. (round two) |
| HL-18 | P2 | `ProgramGate.deriveFixture` yields `""` card names for template pieces (six Urza programs) → `flagged engine_crash: NullPointerException` verdicts that blame the engine. (round two) |
| HL-19 | P2 | Events schema's closed `t` enum omits ~12 emitted types (`pool_expired`, `program_abort`, `engine_cycle`, `pairing_*`, …); `ComboPilotTest` validates every event, which is one reason those paths have no tests. (round two) |
| HL-20 | P2 | Four mana-cost parsers with three X policies; `ProgramRunner` swallows its own parse failure with no event; `activateAtOpponent` returns false without `lastFailure`; `EventRecorder.close` unsynchronized (zombie thread writes after `game_end`, breaks the canary assert). (round two) |

## Closed 2026-09-04 (round-two cleanup, `docs/reviews/2026-09-04-interactive-cleanup-plan.md`)

Commits: 91cc85d9292 (P), 2bc78d92188 (J1), d1a03910f25 (J2 payer), c2e7e5ee1da (docs), 1fb8413ebcb (ratings dedupe), 7bf14c2fcad (review follow-ups), 95e8c34c18a (extended tests), 51e98b931f4. Standard gate green (363 tests), FULL gate green with the `extended` group (429 arena tests + parent modules). Live validation: game 20 (2026-09-04 02:50) was invalidated by the Claude subscription's session limit — every seat's model call failed from 02:56 and the game ran on punts; a validation game is re-run after the limit resets and its findings, if any, reopen items here.

- **BL-01** — **Life-for-mana statics are outside the stock payer's search.** With K'rrik, Son of Yawgmoth out, Mikaeus ({3}{B}{B}{B}) for 3 mana + 6 life…
- **BL-02** — **Trigger ordering is decided by stock** for the seat's simultaneous triggers (CR 603.3b gives it to the controller).…
- **BL-03** — **Any-color mana picks are decided by stock** (`chooseColor` / `chooseColorAllowColorless`).…
- **BL-05** — Mind-slave routing is untested live and the master's brain gets no `state` for its own board while controlling.…
- **BL-07** — `ObserverSnapshot` debounce has no trailing edge (last event in a 200 ms burst never written) and `write` is not synchronized.…
- **BL-08** — `_cycle_rebind` rebinds a recorded cycle answer by card-name prefix; when only one of a card's abilities carries a cost, the prefix can bind…
- **BL-09** — `transport-events.jsonl` is archived at teardown while the ratings void check reads it; multi-game sweeps can miss history.…
- **BL-10** — `status.py`'s fastpath % omits `hold`/`plan`/`cycle`; `usage_report.py` and `replay.py` index keys that pre-backend records lack; `arena-dig…
- **BL-11** — Ten seam tests still pin one card each (Fierce Guardianship, Transmute Artifact, Rings, Scepter, Aura Shards, Sanctum Weaver+Gauntlets, Selv…
- **BL-12** — No test exercises `GuiPilotMatch` (start invariant, roster, advisor wiring) or the human seat (`--human`, autopass modes, advisor-by-default…
- **BL-13** — `pending_context` is unbounded between admitted calls; the advisor writes its own control file then trusts its own mtime.…
- **BL-14** — `arena-add-deck.py` regex takes a leading number as quantity ("1996 World Champion"); Moxfield temp file leaks in `PrepMain`; DFC front-face…
- **BL-15** — `react-autopass.py` remains in the repo with a stale two-name allowlist and no threat check (no longer shipped or reaped).…
- **BL-16** — `docs/INVENTORY.md` §3 still describes `engine/` as three classes; ~50 files under `docs/` are not inventoried; `AiTabHarness` JUnit convers…
- **BL-18** — **DeckCheck API payloads ship in the public package.** `build-light-package.sh` rsyncs `dossier/.cache/` per deck; `forge-light-llm-20260901…
- **BL-19** — **A punt answers legally instead of yielding to stock.** `rules.safe_default` gives no blocks / no attackers / first `min` ids / keep / pass…
- **BL-20** — Cycle replay appends every answer to `_hist`, punts included, and `_cycle_try_arm` does not refuse a punt; a punted CONFIRM inside a loop re…
- **BL-21** — Item 13h collateral: `arena-digest.py` opens `game.jsonl` once and the symlink is re-pointed per game, so the digest goes silent after game …
- **BL-22** — `MailboxProtocol`'s constructor never sweeps `outbox/`; after a JVM crash leaves `resp-1.json`, a hand relaunch (bypassing `arena-stop`) let…
- **BL-23** — `rules.validate` hard-rejects a missing `defender`; `chooseDefender` accepts it with exactly one legal defender. With one opponent left a Ja…
- **BL-24** — `claude -p` runs with `cwd` at the repo root and default settings: every call loads `/Users/toor/Claude/CLAUDE.md`, project settings and use…
- **BL-25** — `ProtocolContractTest` writes ten tracked fixtures (dirty tree on drift; throws on a read-only checkout); the child surefire `<argLine>` rep…
- **BL-26** — `ratings.sweep` globs before it locks and renames a path a concurrent sweeper may have moved; `process_spool` indexes spool keys directly. A…
- **BL-27** — `extract_json` slices first `{` to last `}` (mana symbols in prose defeat it; plausible); whitespace in a deck name word-splits in three scr…
- **BL-28** — `gameId` is millis+pid, so two games in one millisecond in one JVM collide; the runner has no SIGTERM handler, so teardown orphans one in-fl…

## Closed (this pass, 2026-09-03 → 09-04)

Items 1–15 of the interactive plan, with commits: b0568854eb0 (1), a680583b7f4 (2), bb1917137f2/9dc20db1101 (3, 10), be668e60519 (4, 11c), 7490eb465dc (6), 04a12be8b98 (7), a783291a475 + ec2b1ede0b4 (8), 0597c40f023 (9), cde7095c2dc (11a/b, 12), b66d90ec75a (12 runner), 203d30ffe46 (5), 696c226a86f (13), ecd3bacbfe0 (14), 309bbe6d977 (15), d4e98dab13c (16 instrumentation). Live-found and fixed the same day: `getScryfallCode()` NPE in the resolver; resolver failure misreported as "Forge lacks the card"; MULLIGAN `state.hand` shape drift; eliminated seats read as CARD-VANISH (CR 800.4a).
