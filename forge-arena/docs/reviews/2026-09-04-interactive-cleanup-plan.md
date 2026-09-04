# Interactive cleanup plan — 2026-09-04

Scope: every open Project 2 item in `docs/BUG-LOG.md` (BL-01..28) after the round-two review, in priority order, with the testing batched into three gates instead of one per item. Headless items (HL-*) stay deferred. Watch items (W-*) are not bugs and are left alone; BL-04 (open more stock surfaces "by evidence") and BL-06 (one-window timeout cost, "leave unless measured") are decisions already made and are not re-opened here.

Standing rules: seam fixes are general (mechanics, never card names); regression tests span at least two cards; parent-module changes take the FULL gate; capture Maven's exit status, never a filtered tail; no jar rebuilds while a game runs.

## Decisions (Ben, 2026-09-04)

- Agents: up to four Fable subagents for independent test-authoring, docs and adversarial diff review; core code by the session itself.
- D1 → **keep the legal defaults**: BL-19 reduces to making the README and brief say what a punt actually does. No `stock` answer channel.
- D2 → forge-ai payer patch, FULL gate.
- D4 → cut and upload v3.3.3 automatically once the FULL gate is green and the `.cache` negative is clean.

Walked one at a time on 2026-09-04 and affirmed, with these adjustments (folded into the items below):

- Item 7 (BL-07): no scheduler. Write on every event, synchronized, skip when the serialized snapshot is byte-identical to the last write.
- Item 9 (BL-09/10/21): the per-game symlink from item 13h is reverted. `game.jsonl` is a plain append-only file again (human `tail -f` target, archived at teardown); the same record is also appended to `game-<id>.jsonl` for machine readers; both archived at teardown. Transport events are not rotated: each event carries the game id and the sweep filters by it. "Avoid any solution that risks file corruption, fragments or failures."
- Item 11 (BL-14/15/27): the runner's REACT autopass allowlist stays as it is (card names); only the dead daemon is deleted.
- Item 12 (BL-22/23/28): smallest forms only. Constructor deletes `resp-*.json`/`*.tmp`; counter suffix; child reference plus kill in the signal handler; vanished request returns the punt; single legal defender filled in.
- Item 13 (BL-24): no working-directory change of any kind ("running in / is not safe"; no hidden directories). Pass an empty `--setting-sources`; README footnote that `CLAUDE.md` files above the install directory are auto-discovered by brain calls.
- Item 14 (BL-11/12/25): the standard gate's time must not grow. Widened two-card cases, the fallback matrix and the launcher tests are an `extended` TestNG group skipped by default and enabled in the FULL/release gate; the contract-test compare mode and the argLine fix stay in the default gate.
- New item R (rosters): all-AI default table is Urza, Giada, Purphoros, Selvala in seat order; a human game is the human on Selvala at seat 0 with Urza, Giada, Purphoros behind. One source of truth in the launcher; scripts and advisor follow it.
- Item 4/5 (BL-05): the controlling master also sees the controlled player's hidden information for the turn (CR 721.3) and `controllerBoard` carries the master's own hand.

## Decisions this plan proposed

- **D1 — punt policy (BL-19).** A punt yields to stock Forge AI on the *choice* surfaces, where the runner's default is arbitrary and stock has a real evaluator: `DECLARE_ATTACKERS`, `DECLARE_BLOCKERS`, `CHOOSE_ENTITY`/`CHOOSE_ENTITIES`/`CHOOSE_CARD`/`CHOOSE_CARDS` when a pick is mandatory, `CHOOSE_MODE`, `MULLIGAN`. A punt keeps today's never-spend answer on the *spending* surfaces, where stock could commit mana or act for the seat: `CAST_SPELL` (pass), `REACT` (pass), `PAY_UNLESS` (decline), `CONFIRM` (item-10 rule), `CHOOSE_NUMBER` (puntHigh rule), optional single picks (choose none). This respects both of Ben's earlier rules ("a punt never spends new mana"; "never worse than stock") at once. Alternative considered: stock everywhere (simpler, but a wedged brain would then have stock casting the seat's spells for a turn).
- **D2 — K'rrik payer (BL-01).** Forge-ai payer patch, FULL gate. The "explicit cast variant" alternative cannot steer the payer's shard order without touching the same code, so it is not actually cheaper.
- **D3 — new windows reuse `CHOOSE_MODE`** for trigger ordering (BL-02) and colour choice (BL-03), distinguished by `state.purpose`. No new decision type, no schema enum change, no new runner validator; the brief gains two short paragraphs.
- **D4 — release.** The v3.3.3 cut happens only after the FULL gate at the end; the upload to the public bucket is a separate, confirmed step.

## Batches and gates

Testing is batched by suite. The Python suite runs in under four seconds and is run after each Python group. The Java suite is run **twice** in total: a standard gate after the interactive-module batch, and the FULL gate after the forge-ai patch (which doubles as the release gate).

| Batch | Items | Suite |
|---|---|---|
| **P** Python runner, scripts, packaging | BL-18, BL-19 (docs), BL-20, BL-21, BL-23, BL-24, BL-26, BL-27, BL-28 (runner), BL-08, BL-09, BL-10, BL-13, BL-14 (script), BL-15 | `python3 -m unittest discover -s runner/tests` after each group; shell scripts exercised by hand with stand-ins |
| **J1** Java interactive module | BL-22, BL-28 (gameId), BL-07, BL-05, BL-02, BL-03, BL-25 (contract test, argLine, SILENT matrix, negative matrix), BL-11, BL-12, BL-14 (PrepMain temp file) | one standard gate: `mvn -o -pl forge-arena -am package -DskipTests > log 2>&1; echo MVN EXIT=$?` |
| **J2** forge-ai | BL-01 | FULL gate (also the release gate) |
| **D** docs and release | BL-16, BL-21 (docs half), PATCH-NOTES, BL-17 | no suite; hash verification after the cut |

Order of execution: P first (fast feedback, no JVM), then J1, then J2, then D. Live validation game after J2 (K'rrik line, a trigger-order window, a colour window, one forced punt).

## Batch P — Python runner, scripts, packaging

### BL-18 DeckCheck payloads in the package (P1)
- `build-light-package.sh`: delete the `.cache` rsync (line 123). The cache is an ingestion accelerator; no runtime path reads it.
- Packager negative check: after build, `find $DEST -path '*dossier/.cache*'` must be empty; fail the build otherwise.
- The shipped `-latest` is replaced by the v3.3.3 cut (batch D).

### BL-19 punt policy (P1 → docs only, per Ben's decision)
- Behaviour unchanged: a punt keeps answering legally from `rules.safe_default`.
- `packaging/README.md:13-15`: the fallback sentence states the two cases: an *invalid or late* answer falls to stock Forge AI (engine side); a *runner* punt (model timeout, wedge, invalid JSON) answers the per-type safe default listed in the brief, which never spends mana and never acts for another player.
- `seat-brief.md` table checked against `rules.safe_default` line by line; `test_brief_contract.py` pins the table.

### BL-20 cycle replay records punts (P2)
- Append to `_hist` only when `source in ("model", "fast", "plan", "hold", "cycle")`, never `punt`; `_cycle_try_arm` refuses when any window in the candidate cycle was a punt.
- Test: a loop with one punted CONFIRM never arms; an armed cycle that hits a punt breaks and re-records from the model.

### BL-21 per-game log collateral (P2, revised)
- `runner.py`: `game.jsonl` is a plain append-only file again (no symlink, no legacy rename); every record is appended to it AND to `game-<gameId>.jsonl`. `arena-digest.py` needs no reopen logic. `arena-stop.sh` archives `game.jsonl` and `game-*.jsonl` with the seat logs and prints "N decisions across M games".
- `runner/replay.py`: read fixtures from `runner/tests/fixtures/engine` when present, else print a one-line explanation and exit 2; README row updated. (The package keeps excluding tests.)
- README/INVENTORY wording is in batch D.

### BL-23 attacker validator stricter than the engine (P2)
- `rules.validate` `DECLARE_ATTACKERS`: a missing `defender` is accepted when exactly one defender id is legal and is filled in; still rejected when several are legal.
- `test_rules.py`: move the "defender omitted" case from the reject list to an accept case with one defender, and add a reject case with two defenders.

### BL-24 `claude -p` context hygiene (P2, reduced)
- `brain.py`: pass `--setting-sources ""` (probed: accepted, login unaffected) so user/project settings, hooks and plugins never load into a brain call. No working-directory change. `--bare` is ruled out (disables OAuth).
- README footnote: brain calls auto-discover `CLAUDE.md` files above the install directory; install outside such a tree or accept the extra context.
- `test_golden_claude.py`: pin the flag.

### BL-26 ratings sweep and advisor hygiene (P2)
- `ratings.sweep`: take the lock first, glob inside it, wrap each rename in try/except (a vanished spool is another sweeper's win), validate the spool's required keys before `process_spool` and `.skipped` on failure.
- `advisor_runner.py`: guard `_record`/`_stream_write` with `except OSError` like the seat runner; `arena-play.sh` runs the advisor in the same restart loop shape as `run_table.sh` seats (2 s damper, PID file rewritten each restart).
- Tests: sweep with a pre-renamed spool; malformed spool → `.skipped` not a traceback.

### BL-27 parser and script edges (P2)
- `brain.extract_json`: walk with `json.JSONDecoder.raw_decode` from each `{` until a dict parses; tests with `{G}{2}{W}` prose before the JSON.
- `arena-play.sh`, `run_table.sh`, `run-pilot-match.sh`: refuse a deck name containing whitespace with a one-line message naming the file (deck files are slugs by construction).
- `arena-stop.sh` fallback `pkill`: match on `$ROOT`-anchored paths.

### BL-28 protocol edges, runner side (P2)
- `seat_runner.py`: SIGTERM/SIGINT handler that terminates the in-flight `claude` child (tracked on the brain) and exits; `brain.py` keeps a reference to the running `Popen`.
- `runner.py:785-790`: when the request file has vanished before the stat, punt immediately (no fresh window).
- Tests: handler kills a fake child; vanished-request path returns the punt without a model call.

### BL-08 cycle rebind by prefix (P2)
- `_cycle_shape` records `(label, type, cost)` per option; `_cycle_rebind` matches on all three before falling back to the label prefix; ambiguity → no replay.
- Test: two abilities on one card, one costed, must not cross-bind.

### BL-09 transport events archived mid-sweep (P2, revised)
- No rotation. Each event carries `gameId`; `ratings.load_transport_events` filters by the spool's game id. The sweep already runs before the archive step.
- Test: two games' events in one file, one sweep, each game sees only its own.

### BL-10 dashboards (P2)
- `status.py`: fastpath % counts `hold`/`plan`/`cycle`; `usage_report.py` and `replay.py`: `.get()` with defaults for pre-backend records; `arena-digest.py`: skip torn lines with a counter.
- Tests over recorded records with and without the new keys.

### BL-13 advisor context (P2)
- `pending_context` becomes a bounded deque (last 40 lines, drop-oldest with a "… N earlier lines dropped" marker); the advisor records the mtime it wrote to its own control file and ignores that mtime on the next scan.
- Tests in `test_advisor_lifecycle.py`.

### BL-14 ingestion edges, script half (P2)
- `arena-add-deck.py`: quantity regex anchored `^(\d+)\s*[xX]?\s+(.+)$` and rejected when the remainder is a card whose name starts with a number and no separator (fallback: whole line is the card, qty 1); `_front_face` documented and covered.
- Tests: "1996 World Champion", "3x Forest", "Forest".

### BL-15 `react-autopass.py` (P2)
- Delete the script; remove the comment reference in `arena-play.sh`; INTERACTIVE-ARENA note 42 updated in batch D.

### Item R — default rosters (scripts half)
- `arena-play.sh`, `runner/run_table.sh`, `run-pilot-match.sh`, `advisor_runner.py`: default table Urza, Giada, Purphoros, Selvala; human default Selvala at seat 0 with Urza, Giada, Purphoros behind. Where a script needs the roster it derives it from the launcher's rule, not a second literal.

## Batch J1 — Java interactive module (one standard gate)

### Item R — default rosters (launcher half)
- `GuiPilotMatch.DECKS` = urza, giada, purphoros, selvala; all-AI uses that order; a human game places the human deck at seat 0 and the remaining defaults in `DECKS` order. Test in the launcher class (extended group).

### BL-22 stale outbox at construction (P2)
- `MailboxProtocol` constructor sweeps `outbox/*.json` and logs the count; the Python side already sweeps on gameId change (kept).
- Test in `HeartbeatGateTest`'s style: a pre-existing `resp-1.json` is not consumed by the first exchange.

### BL-28 gameId collision (P2)
- `gameIdFor`: `millis-pid-counter` with an `AtomicInteger`; `ProtocolFieldsTest` asserts two games created back to back get distinct ids; the fixture normaliser keeps `"1-1"`.

### BL-07 observer trailing edge (P2, simplified)
- `ObserverSnapshot.write` synchronized; no interval, no scheduler: serialize on every event and skip when the bytes equal the last write. Game-over stays forced.
- Test: two state changes in a row → the file holds the second; twenty identical events → one write.

### BL-05 mind-slave master board (P2)
- `createMindSlaveController` passes the master `Player`; `req()` adds `state.controllerBoard` (life, hand count, untapped sources, battlefield names) when `controllingSeat >= 0`.
- `MindSlaveRoutingTest` asserts the field and its shape.

### BL-02 trigger ordering (P1, D3)
- `orderSimultaneousSa`: when two or more of the seat's simultaneous triggers have distinct descriptions, open a `CHOOSE_MODE` window with `state.purpose = "TRIGGER_ORDER"`, options = `host — trigger text`, `min = max = n`, answer = indices in **resolution order** (first listed resolves first); the controller reverses into stack-push order. Identical descriptions (same card's duplicate triggers) never open a window. Null or malformed → `super.orderSimultaneousSa`.
- Brief paragraph; runner `CHOOSE_MODE` validation already enforces a permutation via `min = max` and no repeats.
- Test (`TriggerOrderWindowTest`): two upkeep triggers from two different permanents; the seat's order is honoured on the stack; identical triggers open no window; a silent brain falls to stock. At least two card pairs.

### BL-03 colour choice (P1, D3)
- `chooseColor` / `chooseColorAllowColorless`: outside a payment context and when two or more colours are legal, open a `CHOOSE_MODE` window with `state.purpose = "COLOR"` and options = colour names (plus "colorless" where allowed); mana-ability and payment-context consultations stay on stock (the payer already targets its colour). Null or malformed → stock.
- Test (`ColorChoiceWindowTest`): two "choose a colour" effects (an ETB and a cast trigger) on different cards; the seat's colour lands on the permanent; a mana ability never opens a window; silent → stock.

### BL-25 test-side hygiene (P2)
- `ProtocolContractTest`: compare against the committed fixtures and fail with a listing of differing types; `-Darena.fixtures.refresh=true` rewrites them (documented in BUILDING.md).
- `forge-arena/pom.xml`: the child `argLine` carries the parent's eight `--add-opens` flags plus the heap settings.
- `FallbackMatrixTest` (`extended` group): data provider over every decision type × {silent brain, non-JSON, wrong key, wrong type, duplicate ids, out-of-range number, foreign id}; each falls to stock with no partial application (asserted by unchanged board and no exception).

### BL-11 single-card seam tests (P2, `extended` group)
- Add the second card to each of the ten: Counterspell (Force of Will), Transmute Artifact (Reshape), Rings (Strionic Resonator), Scepter (Panoptic Mirror? no: Discover source is a different hook, so a second `PlayEffect` source such as Elsha's "cast from top"), Aura Shards (Harmonic Sliver), Sanctum Weaver+Gauntlets (Utopia Sprawl+Gauntlets), Selvala tax (Rhonas), Arc Trail (Fire // Ice), and the four in `CastPathReachabilityTest` (a second Buyback, additional-cost, order, Multikicker card each). Cards chosen at implementation time by script metadata, not memory; any card Forge cannot load is swapped, never skipped.

### BL-12 launcher and human-seat tests (P2, `extended` group)
- Extract `GuiPilotMatch.verifyRoster(decksDir, names)` (the deck loop that today lives inside `startCommanderMatch`) so it can be called without the GUI; test with a temp decks dir: a 99-card deck refuses with `launch-status.json` `ok=false` naming the deck; ten good decks pass.
- Human seat: `AdvisorLobbyPlayer` construction under `arena.advisor=true/false` yields the advisor-wrapped or plain human controller; autopass property honoured only with the advisor on (documented behaviour).

### BL-14 PrepMain temp file (P2)
- `deleteOnExit` on the Moxfield temp file plus explicit delete in a `finally`.

## Batch J2 — forge-ai (FULL gate)

### BL-01 life-for-mana statics (P1, D2)
- `ComputerUtilMana.payManaCost`: when the payer has a `PayLifeInsteadOf:<C>` keyword and the untapped sources cannot cover every remaining shard, pay the `<C>` shards with life **before** spending sources on them, subject to the existing `canPayLife` and life-floor checks; when sources suffice, behaviour is unchanged (no needless life). Generic over the colour letter, not K'rrik's name.
- Test (`LifeForManaPayerTest`, forge-arena): a player with the keyword and three Swamps casts a {3}{B}{B}{B} spell (pays 6 life) and a {2}{B} spell (pays 0 life, sources suffice); two spells, two board shapes; the arena affordability guard offers the cast.

## Batch D — docs and release

- BL-16: INVENTORY §1 counts, §1c ArchUnit description, §3 `engine/` list, §6 or-models path and per-game log semantics, §7 table; INTERACTIVE-ARENA header (v3.3.x, ten decks, react-autopass gone), notes renumbered or ordered, note 42 corrected; README `--verify` removed, launch order corrected, `--advisor` described as default-on, `game.jsonl` per-game semantics, fallback sentence (from BL-19).
- PATCH-NOTES "Unreleased" gains the round-two items; then becomes v3.3.3.
- BL-17: FULL gate green → `build-light-package.sh --force` → packager negative for `.cache` → tar → dated + `-latest` PUT → hash verification. The PUT is the confirmed step (D4).

## Execution log

- **Batch P** committed `91cc85d9292` (Python suite 175 OK; packager dry run clean: no `.cache`, `replay.py` and `react-autopass.py` absent, `run_advisor.sh` present; `arena-stop.sh` hand-run archived a session's `game.jsonl` + per-game file and reported "569 decisions across 1 game(s)"). Pushed to `private`.
- **Batch J1** committed `2bc78d92188` (WIP, gate pending). Targeted run of the eight new/changed interactive classes: 10/12 green first pass; the trigger-order test failed for two test-side reasons, both fixed in the next commit: placed permanents have no active triggers until a state check (the kit's `put` bypasses `GameAction`), and the kit's loop step resolves the top of the stack inside the step that pushed it, so the test now asserts RESOLUTION order through `GameEventSpellResolved`. Found along the way, fixed in J1: `MailboxProtocol.forSeat` created a fresh bus per call, so a Mindslaver controller restarted the request sequence at 1 and the runner skipped the reused names — one bus per seat directory now (BL-05 was live-broken, not just untested).
- **Batch J2** committed `d1a03910f25` (WIP, FULL gate pending): payer patch + `LifeForManaPayerTest` green on the first run (3 Swamps → 6 life for Mikaeus; {2}{B} → no life; Sol Ring shape → 2–4 life; no keyword → refused).
- Agents (Ben's authorization, up to four Fable): T = extended tests (BL-11/12/25), D = docs (BL-16/19/21/24, PATCH-NOTES, brief), R1 = adversarial review of P + J1. R2 reviews J2 before the FULL gate.
- BL-24 probe: `claude -p --setting-sources ""` accepted, login unaffected; `cwd=/` also worked but was rejected by Ben ("running in / is not safe") — no working-directory change shipped.
- **Standard gate on J1+J2** (`d1a03910f25`): `MVN_EXIT=0`, 363 tests, 0 failures, 7 min 10 s total. Standard-gate time did not grow past the ten-minute mark Ben set.
- **Docs agent** landed as `c2e7e5ee1da` (8 files; every claim verified against the tree; found `ratings.slice_game_log` double-counting under the dual append → fixed in `1fb8413ebcb` with a dedupe on (ts, seat, seq, type)).
- **Adversarial reviewer (P + J1)**: confirmed BL-02 stack semantics, the shared bus, `controllerBoard` scope, roster parity, POSIX details, no fixture drift. Found: the colour window was unreachable for every `ChooseColor` card (the engine calls the PLURAL `chooseColors`) and the payment-context gate also blocked the brain's own mana floats → both fixed in J1b with an end-to-end test through Story Circle / Voice of All entering; trigger-order windows had no fast path (a Purphoros table would ask on every ETB) → runner memo per group set, fed by model answers only; runner punts on the two new windows now hand the pick back to the engine's stock via the documented empty list (a deviation from D1 for the NEW surfaces only — flagged to Ben); `brain._run` waits instead of re-communicating after a kill; `arena-stop` ownership marker made path-independent and the skip is reported on stdout; a roster yielding fewer than three AI decks fails with a message; grouping moved inside the guard; stale Javadoc fixed.
- **Extended tests agent** landed as `48f3a0b28e9` (cherry-picked): BL-11 second cards for all ten seams (Force of Will, Abandon Attachments, Mirari, Mizzix's Mastery, Dire Undercurrents, Umbral Mantle, Urza as commander, Forked Bolt, Lab Rats / Thrill of Possibility / Index / Gnarlid Pack, Primal Command — each chosen from the card script's own properties); BL-25 `FallbackMatrixTest` (42 cells, 9 surfaces × malformed-answer kinds); BL-12 `GuiPilotMatchRosterTest` (10 tests: roster rule, all ten shipped decks verify, a 99-card deck and a missing file refused with the status file naming them). 82 methods green with `-Darena.excluded.groups=none`; the default gate runs the pre-change counts (verified on `CastPathReachabilityTest`: 4, not 8). Not done: the GUI-bound human-seat wiring cannot be exercised headlessly. Two behaviours the matrix documented rather than changed: on the binary surfaces (PAY_UNLESS, CONFIRM) an unknown `chosenId` reads as "no/decline", not as a stock fallback (the runner never sends unknown ids); stock's PAY_UNLESS for an opponent's effect pays {1} when it can.
- **FULL gate** on `95e8c34c18a` (`mvn -o -pl forge-arena -am package -Darena.excluded.groups=none`): `MVN_EXIT=0`; arena 429 tests green (363 default + the `extended` group), parent modules green (286, 6 pre-existing skips); 8 min 6 s. Pushed to `private` at this point.
- **Game 20** (all-AI: Urza, Purphoros, Giada, Sheoldred's Sacrifice; 02:50–03:02): invalidated. At 02:56 every seat's `claude` call began returning exit 1 with zero API duration — the subscription's session limit (the payer-review agent died on the same 429, reset 4:50 am PT). All four sessions wedged and re-initialised into the same wall; 4151 decisions, 3477 punts, turn 315 in ten minutes. Two things it did show before the wall: the launcher seated the requested roster, and the runner/engine survived a 3,477-punt storm with no `INTERNAL ERROR`, no `WINDOW LOST`, no `CARD-VANISH`, and a clean stop that archived 19 files. Validation is re-run after the reset; the cut proceeds on the green FULL gate per Ben's decision D4.
- **Game 21** (all-AI: Urza, Purphoros, Giada, Sheoldred's Sacrifice; 08:00–08:55, launched from `9bbc9cf4d39` binaries): 22 turns of clean model play, then the subscription session limit again at 08:40:56 (every seat: `claude` exit 1, zero API duration) and 44 more turns of hand-back punts to a stock finish (Purphoros survived; result void for ratings). Before the wall: 395 model decisions, 0 punts, latency p50 4.2 s / p90 8.5 s / max 31.4 s; 13 TRIGGER_ORDER windows answered live (Urza from t7 — Howling Mine draw ordered ahead of Mana Vault's untap with a stated reason; Sheoldred t21), one REFUSED cast rules-correct (K'rrik at 4 of 7 payable), no `INTERNAL ERROR`, `WINDOW LOST` or `CARD-VANISH`, no `STOCK-SURFACE` line in `gui.out`; CARD-CHECK at game over: the survivor at 100/100. New watch item W-8 (phantom REACT option: Teferi's Protection offered at 0 mana, guard caught it). The J1c review fixes (`14cd9b8b219`) were not compiled during the game (no rebuild under a live JVM); compile + targeted classes green afterwards (11 methods, 16 s).
- **FULL gate on the review fixes** (`14cd9b8b219`, `mvn -o -pl forge-arena -am package -Darena.excluded.groups=none`): `MVN_EXIT=0`; arena 429 tests green, parents 286 green (6 pre-existing skips); 8 min 6 s. Targeted classes first (TriggerOrderWindow, ColorChoiceWindow, LifeForManaPayer, StaleOutboxSweep, MindSlaveRouting, ProtocolFields): 11 methods, 0 failures. Pushed to `private`; the v3.3.3 cut proceeds from this tree per decision D4.
- **Adversarial reviewer (J2 + J1b)**, resumed after the session limit: three real defects — the trigger group key used the STACK description, which carries "[Zone Changer: <card>]", so N copies of one death trigger from N simultaneous deaths were N groups (a 22-option permutation, and the runner memo never matched) → key is now the trigger's own text; the payer's source count treated "Combo B G" as three mana (a Signet), so the life reroute did not fire on realistic boards → Combo/Any count as one; in live payment already-tapped sources were still counted → tapped tap-cost sources skipped. Also: hybrid pips keep stock's "carries the colour bit" semantics (K'rrik pays {W/B} with life as before); the hand-back punt is now counted in `stockDecisions`; the memo is documented as per-turn (it always was); `arena-stop`'s ownership marker names the arena processes exactly; the ratings attribution filters records by the spool's game id; the test kit no longer carries a literal NUL byte and swaps responders instead of starting a second poller. Recorded as watch items: W-6 (two special producers can open a COLOR window mid-payment), W-7 (`min = 0` colour effects). Tests added: six copies of one death trigger from three simultaneous deaths open no window; a Talisman counts as one mana in the payer.
