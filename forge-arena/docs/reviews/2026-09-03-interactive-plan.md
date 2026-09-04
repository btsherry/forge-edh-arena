# Interactive fix plan — affirmed 2026-09-03

Scope: Project 2 only (interactive table, runner, advisor, launcher, packaging). Headless harness findings from the same-day review are out of scope by decision. Every item below was discussed and affirmed one at a time; adjustments made during discussion are folded in. Nothing here has been executed.

Standing rules: seam fixes must be general (mechanics/script metadata, never card names); regression tests span at least two cards; parent-module changes require the FULL gate; no jar rebuilds while a game runs.

## 1. Trigger aiming — DONE 2026-09-03 (field note 57, `TriggerAimContractTest`)
- Only optional triggers get the id-0 "decline" option; mandatory triggers never do.
- `chooseTargetsFor` records decline vs no-answer while aiming; no-answer on either kind falls to stock (`doTrigger`), matching every other surface.
- Optional trigger explicitly declined keeps today's rules-correct auto-aim + decline-at-resolution (CR 603.3d).
- Test: one mandatory and one optional targeted trigger; scripted decline and scripted silence.

## 2. Decision budget — DONE 2026-09-03 (`test_budget_deadline.py`)
- Timeout is its own explicit `--timeout` flag, independent of effort. No derivation from effort, no clamp on the in-game effort dial. Mismatches are legitimate experiments.
- `decide()` receives the request deadline; `ensure_session` gets time remaining, `_call` gets what is left after init; punt on time under the five-second floor. Delete the 240 s literal; the clock never restarts.
- Log line when init consumed the window (seconds spent, seconds left).

## 3. Punt memo — DONE 2026-09-03 (`test_memo_only_from_model.py`)
- Feed the REACT memo only from `source == "model"`.
- Reset `_deviation` at the top of `handle()`.
- Test: one failed REACT, then an identical window must be a model call.

## 4. Refused cast feedback — DONE 2026-09-03 (`RefusedCastFeedbackTest`; also 11c modal-cast result)
- `lastRefused` state field + prompt sentence stating what the engine measured: needed N, payable now from pool plus one activation of each untapped source is M; float first if a sequence was intended.
- Suppress the refused option from the very next window only.
- Brief line documenting the field. Two-cards test.

## 5. Advisor lifecycle — DONE 2026-09-03 (`test_advisor_lifecycle.py`)
- `AdvisorFeed` stamps `gameId` on every file; advisor resets only on id change (replaces seq comparison).
- Resume consumes the backlog quietly (context only, no stale notes streamed), announces once.
- New-game reset also resets `gov_turn` / `gov_budget`.
- First advisor tests: interleaved numbering must not reset; id change must; resume must not re-stream.

## 6. Mana table in state — DONE 2026-09-03 (`ManaTableTest`)
- `manaSources`: per untapped source — id, name, yield now (live board), colors, `restricted`, `sick`, `cost` beyond tap. Identical basics collapsed with `count`.
- `manaAvailableNow` = pool + unrestricted, non-sick, tap-only yields (same quantity the engine's refusal uses).
- `ritualsInHand`: spells whose chain has a Mana part — cost, projected yield on current board, net, colors. Multipliers/modifiers (mana-event triggers or replacements) listed with `kind: "multiplier"` and no number.
- Detection by mechanics only. Brief paragraph. Test across a scaling land, a restricted source, a sick creature, a ritual, a multiplier.

## 7. Ingestion, naming, and the 400-card invariant (extended rigor: edge cases, error handling, observability, correctness)
- Scryfall is canonical for authored and built files; Forge's name is a runtime encoding at the `.dck`/live-state boundary.
- Translate by printing: Scryfall (set, collector number) joined to Forge edition data; fall back to name forms (combined, then front face); nothing resolves → named failure at ingest, before any write. Verify at fix time that Forge edition data carries collector numbers for the deck's printings; use Scryfall reprint data to find a Forge-known printing when it does not.
- `deck-cards.json` entries gain `forge_name`, `scryfall_id`, `set`, `collector_number`; `name` stays Scryfall's.
- Ingest writes a manifest: `.dck` SHA, count, Forge card-DB stamp, resolved names.
- Launch preflight: hash compare in Python, milliseconds. Mismatch → refuse ("deck changed since ingest, re-run arena-add-deck"). No manifest → refuse. Card-DB stamp changed → warn, start.
- No JVM at launch, ever.
- Start invariant in `GuiPilotMatch`: count real (non-placeholder) cards per loaded deck; any seat under 100 refuses the launch with deck and card names to `gui.out` and a status file.
- End invariant on game-over: per owner, count cards across all zones (library, hand, battlefield, graveyard, exile incl. face-down, command, stack), tokens and copies excluded; result spool records per-seat totals; shortfall writes a `CARD-VANISH` line naming seat and count. Mid-game conservation stays with `arena-cardwatch.py`.
- Align `run_table.sh` static check with the resolver as a fast pre-check that defers to the manifest.
- Live check: re-ingest Sythis; Room line survives; probe reports 100 clean.

## 8. Game identity in the mailbox — DONE 2026-09-03 (engine a783291a475; seat reader `GameIdentityTests`; advisor reader lands with item 5)
- `gameId` (start millis + pid, once per `Game`) on every request and feed file.
- Seat runner resets/sweeps only on id change; drops the 3 s heuristic and `_answered_at`. Runner restart mid-game adopts the id (rejoin, not reset). Missing field → old heuristic + one log line.
- One log line per id change with both ids and swept-file count; `game.jsonl` rows carry `gameId`.

## 9. Packager
- Missing-jar loop moved out of the pipe subshell; collect all missing, fail naming them; assert `lib/` count equals classpath count; fix the README `&& cp ||` misreport.
- Prove the negative with a fake classpath entry; diff `lib/` listing against v3.3.2.

## 10. CONFIRM punt — DONE 2026-09-03 (engine fields a783291a475; `safe_default` structural; confirm/pay_unless/choose_cards fixtures)
- Engine adds `hasCost` and `isMine` to `OptionalChoose`/untyped confirms.
- `safe_default` says yes only when free and mine; everything else declines. A punt never spends new mana, regardless of pool (sole existing exception: committed X announces). Word lists removed; stopgap word-boundary tightening until the field lands.
- Add `CONFIRM`, `PAY_UNLESS`, `CHOOSE_CARDS` fixtures to the punt-legality test.

## 11. Four controller defects
- a. Mind-slave: slave's controller routes to the master's mailbox; requests carry `controllingSeat` and a prompt line.
- b. Pay-unless: set `inPaymentContext` around `payComputerCosts`.
- c. Charm: return the real cast result; failures surface via `lastRefused`.
- d. Untyped confirms: gate by "source is the seat's own spell/ability", not by the word "play"; carry `hasCost`/`isMine`.
- Two-cards tests for a and b.

## 12. Silent brain (simplified form)
- Runner touches `seat-N/heartbeat` every 5 s (advisor too).
- Engine stats it once per request before blocking; older than 15 s → stock immediately, one log line per transition each way. Unreadable/stat failure → treat as alive (gate can only shorten a wait).
- No engine-side breaker: item 2 makes wedged models punt on time; runner wedge recovery stays the single layer.
- `observer-state.json` gains per-seat `brainAlive`; result spool records stock-decision counts per seat.
- Both launch scripts default to 90; engine stamps its timeout on each request (consistency only, never derivation).
- Dead-brain test doubles as the missing "never hangs" test.

## 13. Runner and launcher hygiene
- a. `handle()` guarded: log traceback, answer `safe_default`, continue.
- b. `.resolve()` on the combos path; warn when absent.
- c. `ratings.py`: write ladders per spool, rename last.
- d. Stop shipping and reaping `react-autopass.py`; keep in repo.
- e. PID files under `runner/logs/pids/`; `arena-stop` kills by PID, pattern fallback only without PID file; `run_table.sh` under `setsid`. Manual teardown test.
- f. Move `or-models.json` to `logs/cache/`.
- g. Launcher: check `$2` before use; show preflight stderr; `basename` the human deck.
- h. Rotate `game-<gameId>.jsonl` with a current symlink; readers glob.

## 14. Briefs
- Seat brief: replace "a pass is played for you" with the real per-type safe-default table.
- Advisor brief: fix heading and decision-type names.
- Test asserting brief table and `rules.safe_default` agree.
- Watch punt rate and `latency_s` for the calibration effect.

## 15. Tests and docs
- Per-decision-type schema emitted from Java; Java test producing one request per controller branch; Python test feeding every `safe_default` through it.
- Dead-brain test (5 ms poll, 1 s timeout).
- Migrate four probe-regex classes and eleven thread-leaking classes to `MailboxTestKit`, preserving assertions.
- Widen single-card seam tests to two cards as their seams are touched.
- Refresh INVENTORY from the tree; fix JDK line and the 0.15 s poll figure.

## 16. Decision surfaces still on stock (backlog)
- Candidates: `chooseSomeType`, `orderSimultaneousSa`, `assignCombatDamage`, `chooseColor*`, `chooseCardsForConvokeOrImprovise`, `chooseSingleSpellForEffect`.
- Measure firing frequency in recent logs first; open the top one or two under the existing discipline (genuine choice only, vetted, fail to stock, added to the wire schema). Rest stay listed.

## Suggested execution order
Engine-side fields that others depend on first (8 gameId, 10/11d confirm fields, 12 timeout stamp), then 1, 3, 2, 4, 6, 10, 11, 12, 5, 8 readers, 9, 13, 7, 14, 15 alongside, 16 last. Standard gate per change set; FULL gate is not expected since no parent module is touched; live validation game after the controller items land.
