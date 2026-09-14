# Five lenses on `experimental/voicework2` — the analysts' reports, verbatim

**Date:** 2026-09-14. **Method:** five Claude Fable 5.1 subagents, one per Boris Cherny archetype
(definitions and the brief in `ai-native-roles-2026-09-14.md`), each given the same scope and rules of
engagement (read-only: no edits, no git writes, no builds, no launches, no network) and its archetype's
lens. They ran in parallel for 11.4 minutes, 239 tool uses, 1.03 M tokens. Every report below is the
analyst's final message reproduced without edits; nothing has been fixed. Branch head at review time:
`e517f2eb300` (52 commits since the `arena` base `3e037fdc9a9`); games 46–48 archived under
`runner/logs/archive/`.

Reading order follows the archetypes: Prototyper, Builder, Sweeper, Grower, Maintainer.

---

# 1. Prototyper

## Prototyper — The branch has built the *pipes* of a talking table; the uncanny valley is because what flows through them is chosen from the wrong signals. The next cheap wins are grounding and presence, not density.

### What this branch built, as the Prototyper reads it

Fifty-two commits (`3e037fdc9a9..e517f2eb300`) turn three ElevenLabs stock voices into a composable table: a public event ring in `ObserverSnapshot.java:178-395`, a one-throat runner (`voice_runner.py`, `Player.play` at 654 is blocking `afplay`), a role-based chain table (`chains.py`, 90-odd invites), a patter clock and duty-cycle governor (`voice_runner.py:1304-1332, 1910-1954`), and three libraries per voice: 66 root ids (214 wordings), 263 table ids (353 wordings, of which 164 address lines and 56 numbers carry one wording each), 188 card ids (264 wordings); 1,662–1,664 WAVs per voice. Game 48 (`20260914-141513-stop`) ran at `8c6f887aba9` (its `launch-config.txt`), so the five commits from `7caad07a40a` to head — the silence floor, certain answers, proposal chorus, vanished-seat exits — are unplayed live. Suite: 453 OK.

Measured over games 46–48 the machine is stable and the mix is not: 4.5–4.7 seat lines/min; questions answered within 10 s at 6/18, 8/16, 7/19; content-light patter (`nothing-happening`, `this-is-fine`, `what-turn`, `good-hand`, `board-envy`, `pass-already`) at 23 %, 21 %, 21 % of seat lines despite round 31 quartering its weights; `cards-in-hand` the top id in all three games (7, 8, 9 plays from 3 wordings). In game 48: median gap 6.2 s, p90 24.2 s, max 68.6 s, 21 % of gaps over 15 s, duty 0.205 against a rowdy goal of 0.36.

### Top findings

**1. The deciding turn of game 48 was narrated by a table that did not know what was happening.** Turn 14 (Urza's, ~819–1277 s after the first spoke record) ran about seven minutes and 119 decisions: Fabricate for Basalt Monolith, Sculptor, Aetherflux Reservoir, sixteen Sensei's Top casts, Dramatic Reversal, life 40→160, three 50-point shots (`game.jsonl` whys at t14: "Loop until life ~190, then three Reservoir shots", "Life 160: fire Reservoir 50 at each opponent"). The table said 47 lines; three were "hit Selvala" (the human, +868/+955/+995 — the third from Urza himself), and *zero* were `looping`, `big-mana`, `someone-wins` or `engine-online`; none was even attempted (only `kill-that` twice, killed by seat guard and dice). Urza's last patter before shooting everyone was `nothing-happening` (+1260, ~1789420474). Why: the patter's threat model is the life leader or a 6-power creature (`voice_runner.py:1863-1876`), `looping` is gated on the game-changer list (`:2244-2251`, Top is not one), `big-mana` needs pool ≥ 8 and the dial does not scale it (`apply_chatter`, :1122-1139), and `someone-wins` needs 15 power. Direction: ground the threat and the loop in intent and mechanics, not card lists and life. The intent already exists in two places the voice never reads: the seats' `why` text (only `MULLIGAN` is consumed, `:1154-1212`) and the seat runner's own `repeat_cycle`/LOOP OFFER machinery (`seatd/runner.py:644-680, 784-854`). This is also the "seam fixes must be general" rule applied to talk.

**2. Let the brain choose the line.** The seat runners already accept extra answer keys — `turn_plan`, `deviation`, `repeat_cycle`, `until`, `stop_loop`, `hold_turn` (`seatd/runner.py:787-790, 1737-1790`). A `"say": "<id>"` key from a menu of ~20 ids, offered in `seat-brief.md` beside the others, costs no extra call and no audio; the runner records it in `game.jsonl` and the voice runner tails it as it tails mulligans. The advisor already does exactly this for Joshua (`advisor_runner.py:155-190`, `[bark:<seat>:<id>]`), so the pattern is proven in this codebase. Measure: anchored share in `arena-hygiene.py` and a blind A/B — two games, one with `say`, Ben guesses which.

**3. Deals are theatre; make them consequential.** `_deals` lives only in `voice_runner.py` (grep of `seatd/*` finds no "voice", "truce", "deal"). A seat that says "Agreed. This turn only." then attacks because its brain never heard the promise; `you-promised` fires and reveals the seam. Direction: when a deal is struck, drop a one-line RUNNER NOTE into the promised seat's next request and let the brain honour or betray it knowingly; and let the human answer a question with a Yes/No in `VAdvisor` instead of banning questions to him (`c6e266c092c`). Measure: attacks across a truce before/after; Ben's report of whether "Peace for a turn, Urza?" now lands.

**4. Presence beats filler under a silence floor.** The new floor (`SILENCE_FLOOR_S` 12/24 s ÷ chatter, `:106, 1937-1941`) is 6 s on AI turns at rowdy and forces the *best patter candidate* regardless of dice — the same pool that produced the 21 % filler. Every rendered take is a full sentence (median 2.3–2.5 s, shortest 0.96 s; only 33 takes of ~5,000 are one word). Direction: render 20–30 sub-second non-verbal atoms per voice (`[sighs]`, `[hmm]`, `[chuckles]`, a throat-clear; card-riffle SFX) and have the floor spend those first, content lines only when anchored. A quiet table where someone audibly *is there* is not uncanny; a metronome of "is anything happening?" is. Measure: p90 gap held, filler share down, Ben's rating.

**5. Overlap and backchannels.** One blocking throat means nobody says "yeah" under someone else. Real tables overlap constantly. Direction: a second `Player` channel at −6 dB for 0.3–0.6 s backchannel atoms allowed to start while the main line is playing, hop gap 0. Measure: overlap count in `voice-0.jsonl` (needs a `channel` field) and Ben's ear.

**6. Human-turn silences are where the worst gaps live.** Roughly 35 % of game-48 wall clock was Ben's turn (from `game.jsonl` decision timestamps); the 44.7 s and 37.0 s gaps sit inside turn 13. `play-faster`/`thinking-hard` target only AI seats via `slow_seats()` (`:1826-1840`). Direction: a heckle aimed at the human when his priority window has been open >30 s (the advisor knows), or the presence sounds from finding 4. Ben may veto being heckled; it is a one-game test.

**7. The threat should have memory.** `scan_combos` announced `combo-basalt-gadgeteer-online` at +557 (turn 10) and the table forgot it by turn 14. Direction: a `_threat` pin set by combo-online, game-changer casts and cast flurries, decaying over turns, that biases `hit-`/`threat-` targets ahead of the life leader. Cheap; measurable as "threat lines naming the eventual winner".

**8. Stop growing the long tail.** 164 address ids per voice include 30 colour identities × 4 families whose decks all have commander names in `address.json` — ~360 takes that cannot fire. The card library (188 ids/voice, 792 takes) produced 6 of 96 seat lines in game 48. These are the most grounded lines and should stay, but the render budget for the next round belongs to atoms (finding 4/5) and wordings for the ten most-played ids, not more cards.

### Concerns

The post-game fixes fight each other: `PATTER_REPEAT_S=300` with "named counts as generic" (`25e803b19f6`) empties the patter pool on a quiet board, and the floor then finds no candidates and falls silent again; nothing in the tests covers exhaustion. `_respond_to_proposal` (`:1511-1544`) comments "no third round" but the replies carry chain links and `after_spoken` will plan hop 2 from them; a proposal can still produce agree, disagree, clapback, laugh. Proposals answered by every seat at 0.85 may itself be uncanny; my hypothesis (unverified) is that real tables answer most proposals by action or a grunt. The Game Knights sample (`8e367f2a206`) is produced and edited: silences are cut, wit is selected — its pace figures bias the whole density model.

### Bugs and corrections

- Loop detection is card-list-gated (`:2244-2251`): sixteen Top casts in one turn drew no `looping`. Confirmed from game 48 logs.
- `barks_mana` is not scaled by the dial though the README says the dial lowers reaction thresholds; Urza floated up to 7 and never tripped `big-mana`. Confirmed from code and whys.
- `arena-hygiene.py:136` counts source `card` as anchored but card lines keep source `event`; harmless, but the metric cannot report card share.
- "No third round" comment vs behaviour, above — plausible, not seen live.

### Feature suggestions

Ranked by cost: (a) `say` key from the brains; (b) `why`-text keys (seat N, loop, lethal, infinite) into the voice; (c) presence atoms under the floor; (d) truce note into the mailbox and a Yes/No for the human; (e) threat memory; (f) backchannel channel; (g) a "storm count" line family ("that's twelve spells") fed from the cast events — whole-sentence numbers already exist for life and hand.

### Observability and efficiency

Add to `spoke` records: `turn`, `activeSeat`, `target`, `channel`; add a per-game "grounding" score: share of lines whose target or subject matches the eventual winner or the seat with the most casts that turn. Log patter-pool size at each tick so exhaustion is visible. The data that would move this: three to five hours of *unedited* pod VODs or one recorded session of Ben's own group, run through a timestamped transcriber, extracting inter-utterance gaps by active-player, a who-answers-whom matrix, question answer rate and latency, proposal outcomes (verbal / silence / action), utterance-class shares including non-verbal and backchannel, words per utterance, and overlap rate. A hand tally of one hour would already replace `PROPOSAL_P`, `SILENCE_FLOOR_S` and `hop_p` guesses with priors.

### Questions for Ben

1. Would you accept a heckle aimed at you when your window sits open?
2. May the seats' brains learn about deals and be asked to honour them, or is talk to stay purely cosmetic?
3. Is a `say` key in the decision answer acceptable given the seat-brief accuracy rules?
4. Would you record one paper session of your own pod for calibration?
5. At rowdy the floor is 6 s: is a forced line every six quiet seconds what you meant by "fewer silences"?

Verified by running: `git log --oneline arena..experimental/voicework2`, `git log -1 --format=%B` on eight commits, `sed`/`grep` reads of `voice_runner.py`, `chains.py`, `chains.json`, `table_lines.py`, `ObserverSnapshot.java`, `seatd/runner.py`, `seat-brief.md`, `advisor_runner.py`, `arena-hygiene.py`; python3 analyses over `voice-0.jsonl` and `game.jsonl` in `20260911-105547-stop`, `20260911-204333-stop`, `20260914-141513-stop`; a `wave` duration scan of the harry libraries; `cd runner && python3 -m unittest discover -s tests` (453 OK).

---

# 2. Builder

## Builder — The table talks and holds up for Ben's own games; it is not yet a 4.2 cut, because the one operation Ben performs every game (kill and respawn the voice child) leaks state, the package roughly triples, and two of the new mechanisms are unmeasured live.

### What this branch built, as the Builder reads it

Fifty-two commits (3e037fdc9a9..e517f2eb300) turn `runner/voice_runner.py` from Joshua's 850-line mouthpiece into a 2,637-line composer for four speakers. The Java side is small and gated: `ObserverSnapshot` gains a 30-entry public event ring (attack, damage, countered, cast, left, gameover) and a per-seat `pool`, all written under one monitor and moved atomically (ObserverSnapshot.java:580–586); `GuiPilotMatch` renames seats to `<Commander>-S<n>` / "Player One" and turns off the AI-card warning boxes; `VoiceFocus`/`VAdvisor` poll `logs/voice-speaking.json` four times a second to follow the talking seat's tab. The last Java change is e1e261da125 (9/10 22:08, whose body reports the gate green) and game 48's `run_table.out` shows "Player One", so the live jar carried it.

The Python side is one-way and stdlib-only: `scan_observer` → `scan_events` → `maybe_bark` → a priority queue with class-based eviction, `chains.py` planning replies from `chains.json` (109 invites), a duty-cycle governor, a patter clock with a silence floor, mulligan lines tailed from `game.jsonl`, and the BL-50 heuristic (a seat seen before and now absent is dead; voice_runner.py:2414). The seat runner grew loop stop conditions (`until`), a parked/re-armed cycle, and the loop offer, tested against a real game-47 tape (`tests/fixtures/game47-seat1-turn20.jsonl`). The audio is 1,551 manifest ids across nine libraries, 2,495 baked takes, every id present, no orphans (checked by script).

The suite is 453 OK in 20.9 s. `run_voice.sh` respawns the child after 2 s; every restart in games 46–48 was exit 143 — a deliberate SIGTERM (voice_runner.out lines 50/85, 22, 59/91), so the respawn path is exercised live in every game.

### Top findings

**1. A respawned runner forgets who is dead and what is on the board.** `eliminated`, `_seen_seats`, `_combos_done`, `_heads_up_said` and `_gc_cast_seen` are in-memory only (voice_runner.py:1115–1116, 1089, 1031). After a restart, `scan_observer` marks a seat dead only if it is flagged or vanishes *after* being seen; a seat that died before the restart is never in `eliminated`, so `patter()`'s `living` (line 1931) and `after_spoken`'s `voiced` (line 1566) include it — a dead seat can be picked to speak, undoing game 42's "dead players do not talk". `scan_combos` (line 2085) is board-driven, not event-gated, so its empty `done` set (line 2101) re-announces every complete combo on the first snapshot after a restart. I verified this by reading; no live log shows it because nobody had died and no combo was complete at any of the five restarts. Direction: on the first snapshot at turn ≥ 1, seed `eliminated` with voiced seats absent from the list (silently, no exit line) and seed `_combos_done` with combos already complete; or read the runner's own `noted`/`spoke` records back the way `_startup_already_spoken` does.

**2. Every restart produces an immediate forced line.** `last_spoken_at = -1e9` (line 1101) makes `_patter_due` immediate and, since c6e266c092c, `silent_for` astronomically large, so `breaking` (line 1928) is true and the pick goes through ungoverned with `p=1.0` (line 1710). Live: 5 of 5 restarts spoke within 3–6 s — game 46 07:54:55→07:54:58 `cards-in-hand`, 08:08:45→08:08:51 `good-hand`; game 47 20:19:23→20:19:27 `cards-in-hand`; game 48 14:07:38→14:07:41 `cards-in-hand`, 14:12:07→14:12:10 `hit-urza`. Direction: initialise `last_spoken_at` and the patter anchor to the start clock (or the last `spoke` ts in voice-0.jsonl).

**3. The package roughly triples and the documented numbers are stale.** Measured: 4,990 wavs tracked under `voices/`, 2,495 of them raws; baked 322.6 MB (bill 24.6 + cards 52.3 + table 43.5; harry 22.5/39.9/39.3; lily 22.4/42.0/36.1), raws 351 MB; ~674 MB of 22.05 kHz 16-bit mono WAV in plain git, no LFS, `.gitattributes` only `text=auto`. PATCH-NOTES says "about 270 MB"; note 103 says "~185 MB" for table+cards (measured 253 MB). The 4.1 tarball was 132 MB and WAV barely compresses. `build-light-package.sh` excludes the raws and dev tools (lines 160–163, pinned by test_hardening) but has no completeness check of the voice tree it copies. Direction: settle the audio format before the cut (afplay decodes AAC natively; the runner would need durations in the manifest instead of `wav_seconds`), keep the raws out of the merge, add `*.wav binary`, and give the packager a preflight that asserts audio for every manifest id in DEST.

**4. A muted voice at game over stalls teardown for up to two minutes.** `step()` returns before `scan_observer` while disabled (lines 2564–2570), so `final_locked` is never set and `final.json` never written, while the heartbeat thread keeps `voice_alive()` true; `arena-autostop.sh` then waits `ARENA_AUTOSTOP_VOICE_WAIT` (60) and falls back to `LINGER` (default 60, line 25). Unmuting inside that window plays the whole final sequence late. `test_autostop.py` has no voice case. Direction: while muted, keep reading the observer (drop lines, publish `final.json` at gameOver at once) and add a shell-level test of the wait.

**5. The launch banner disagrees with the runner.** `ARENA_VOICE_DUTY_HUMAN` is 0.4 in arena-config.py:54 and README.md:526; the code is 0.6 (voice_runner.py:103, changed in c6e266c092c). Game 48's `launch-config.txt` printed "0.4 [default]". The module docstring (line 37) still gives `ARENA_VOICE_YOUR_MOVE` default `on`; code says `some` (line 996). Direction: one source of defaults — have the runner emit its effective config as a record and let the banner read it.

**6. Three definitions of "anchored".** Hygiene counts event/procedural/card/opener/recap/advice (arena-hygiene.py:136); eviction treats recap/advice as optional (BARK_PRIORITY 8.0, `_bark_class` prio < 8.0); the governor's `OPTIONAL_SOURCES` is (patter, chain), so opener/recap/advice are governed as anchored while chain is not. The number Ben steers by (27 % in game 48, 38 % in 47) does not measure what the mechanism protects. Direction: a single classification function used by all three.

**7. At Ben's dial the silence floor overrides the budget.** `SILENCE_FLOOR_S` 12/24 (line 106) is divided by chatter; Ben plays at rowdy (launch-config.txt: `ARENA_CHATTER=rowdy`), giving 6 s on AI turns and 12 s on his. The average take is ~2.9 s (322 MB / 2,495 at 44.1 KB/s), so a forced line every 6 s is ~0.48 duty against a 0.36 goal, and forced lines bypass dice and governor. Built after game 48, never measured live. Direction: cap the floor's spend at the goal, or scale it with the dial the other way, and read mean duty from game 49 before cutting.

**8. Blocking playback against a 30-event ring.** `speak()` blocks the loop for the line (line 1474); `EVENT_RING = 30` is the only buffer; `scan_events` skips unseen seqs silently. Suspected, not observed. Direction: record a `gap` whenever seq jumps by more than one; if it ever fires, move playback to a thread.

**9. Debug residue shipped in the loop arming.** seatd/runner.py:825 reads `… if False else (…)`; the dead left branch indexes `h[-k][0][0]`, which would be wrong if it ever ran. `_loop_state()` defaults five attributes lazily by `hasattr`. Harmless, tested (`test_a_loop_with_a_target_tolerates_its_own_churn…`), but not production shape. Direction: delete the dead branch, initialise in `__init__`.

**10. The seam fix is one-sided, on purpose, and the audit list is known.** ObserverSnapshot still iterates `game.getPlayers()` (lines 374, 442); consumers of the same list are arena-status.py:26/147, arena-public-state.py:79, advisor_runner.py:285. Direction: keep the runner heuristic for 4.2; make `getRegisteredPlayers()` plus that audit one 4.3 commit with `ObserverSnapshotWriteTest` extended to a lost player.

### Concerns

The launcher passes `ARENA_HUMAN_DECK` (arena-play.sh:193) and relies on an inherited `ARENA_SEAT_DECKS`, which is consistent with run_table.sh:91, but a non-default roster is guessed from `DEFAULT_TABLE` until three AI decks have decided (`learn_table`). `voice_alive()` uses BSD `stat -f %m` — fine for a Mac-only arena, silently degrades elsewhere. The voice tests are unit-level with a fake clock and player driving real code on synthetic snapshots; the seatd loop tests replay a real tape, which is the better shape — the voice runner has no equivalent because observer snapshots are not archived. `resolvingSeat()` attributes a `left` event to whoever is on top of the stack, so a sacrifice-as-cost under an unrelated spell can credit the wrong seat (unverified live).

### Bugs and corrections

Findings 1, 2, 4 and 5 are bugs in the strict sense. Smaller: `gid` at voice_runner.py:2389 is computed and never used; note 103 and PATCH-NOTES carry the stale size figures; the suite emits a `ResourceWarning: unclosed socket` on 127.0.0.1.

### Feature suggestions

A small per-turn state file for the voice runner (dead seats, combos done, game changers seen, recency) so a restart is a no-op — this also makes finding 1 disappear structurally. A `--replay <archive>` mode fed by an appended snapshot tape (a few lines in the runner: append each read snapshot to `observer-tape.jsonl`, archived by arena-stop), so a game's voice behaviour can be re-run offline after a code change instead of in the next live game. A separate voice pack in the release bucket if the format stays WAV.

### Observability and efficiency

Add an `up` record to voice-0.jsonl (turn, restart count) so hygiene can count restarts without parsing voice_runner.out. Record seq gaps (finding 8). Emit the effective configuration as one jsonl record at start (finding 5). Have hygiene print mean duty against the goal per turn owner, since the floor and the human multiplier now pull in opposite directions. Compressed audio would cut the package by 5–8×.

### Questions for Ben

Is killing the child mid-game a supported operation for 4.2 (you did it in every game) — if so finding 1 is a blocker, not a nicety. Do the raws go into arena's history on merge, or to the bucket? What is the package size budget for 4.2, and is a format change in scope? At rowdy, do you want the floor to win over the budget? Should a muted game still tear down five seconds after game over? `getRegisteredPlayers()` in 4.2 or 4.3?

Verified by running: `git log --oneline arena..HEAD`; `git diff --stat arena...HEAD`; `git diff arena...HEAD -- <ObserverSnapshot, GuiPilotMatch, VoiceFocus, CAdvisor, VAdvisor, seatd/*, scripts/*, packaging/build-light-package.sh, tests/test_hardening.py>`; `cd runner && python3 -m unittest discover -s tests` (453 OK); a Python inventory of every `voices/**/manifest.json` against its wavs and raws; `git ls-files runner/voice/stock/voices` with `du`; `git count-objects -vH`; `git check-attr -a`; a Python summary of `voice-0.jsonl` and `voice-0.log` for archives 20260911-105547, 20260911-204333, 20260914-141513; `/usr/bin/grep` over `voice_runner.out`, `autostop.out`, `launch-config.txt`, `run_table.out`, and the runner, scripts and tests for the cited lines.

---

# 3. Sweeper

## Sweeper — The table works; now it needs a diet. About a quarter of what the branch carries has ever been exercised, and the rest is weight the runtime, the repo and the operator all pay for.

### What this branch built, as the Sweeper reads it

Fifty-two commits grew `runner/voice_runner.py` from 925 to 2,637 lines (`git show arena:…/voice_runner.py | wc -l`), `advisor_runner.py` from 863 to 1,031, `seatd/runner.py` from 1,533 to 1,847. On disk under `runner/voice/stock/voices/` there are 4,990 tracked WAVs (653 MB): 2,495 baked takes (323 MB) and 2,495 raw takes (351 MB) that nothing at run time reads. Each voice carries 517 ids (66 base, 263 table, 188 cards). The voice path reads 36 environment knobs (30 in `voice_runner.py`, 5 in `chains.py`, `ARENA_VOICE_FOCUS` in `VAdvisor`). Six candidate generators feed one queue (advisor tags, the event ring, procedural narration, the patter clock, chains, mulligans) and six gates stand over them (per-turn no-repeat, `RARE_REPEATS`, `PATTER_REPEAT_S`, the seat guard, the governor, the silence floor).

Live evidence, from the twelve archived `voice-0.jsonl` files of 2026-09-10 to 09-14: 1,139 lines spoken, 2,372 skipped, 210 dropped. Only 139 distinct ids were ever spoken. Every game ran with every voice knob at its default except `ARENA_CHATTER=2` from game 41 on (the `[voice] up —` line in each archive's `voice-0.log`). The table and cards libraries were rendered 23:23 and 02:13 on 09-10/11, so they have three games of exposure (46–48); commits `25e803b19f6`, `c6e266c092c` and `a0db117d8b1` landed after game 48 stopped (14:15:13) and have none.

### Top findings

**1. Raw takes in git: 351 MB, 2,495 files, zero runtime use.** `du` on `voices/*/raw` and `voices/*/*/raw`; `git ls-files voices | grep -c /raw/` = 2,495. `packaging/build-light-package.sh:161-162` excludes them from the package, so they exist only for re-bakes. Three tests pin their presence (`tests/test_bark_libraries.py:110`, `test_table_lines.py:128`, `test_card_lines.py:88`). The Joshua precedent was 12 MB; this is thirty times that in a repo whose packs already stand at 1.49 GiB (`git count-objects -vH`). Direction: keep raws in the release bucket or one archive beside the shipped tars, pin the tests to the manifest instead, and make `build_stock.py --bake` fetch on demand. Lines removed: none of code, 2,495 files. Behaviour lost: none.

**2. The colour-identity address fallback cannot fire for any deck on disk: 384 baked takes, 46.5 MB (plus 50.6 MB raw).** `who_for_deck` (`voice_runner.py:324-341`) returns the commander's slug first and falls to the colour chart only when `address.json` lacks the deck; `address.json` `commanders` lists all ten decks in `decks/`. Every `hit-`, `threat-`, `leave-me-`, `deal-` colour id (128 per voice) is in the never-spoken list. Direction: render the four address lines per commander when `arena-add-deck.py` runs (it already writes the dossier; `table_lines.py --write` is the missing step) and drop the 32-identity chart, or keep only the five mono lines as a true fallback.

**3. Twenty-seven knobs nobody has turned, several of them the same knob.** Beyond the dial, five dials say "quieter on the human's turn": `DUTY_HUMAN_MULT` 0.6 (`voice_runner.py:98`), `ARENA_VOICE_PATTER_HUMAN` 0.33 (`:1077`), `SILENCE_FLOOR_S["human"]` 24 vs 12 (`:101`), `ARENA_BARKS_CHAIN_HUMAN_P` 0.5 (`chains.py:42`), `ARENA_BARKS_HUMAN_P` 0.7 (`:1046`). Three mode-plus-probability pairs share one shape (`YOUR_MOVE`/`_P`, `COLOR`/`_P`, `BARKS`/`_P`). Two clocks drive patter (`PATTER_GAP` due-clock at `:1938-1939`, the floor at `:1940-1942`). Direction: `ARENA_CHATTER` stays the one operator dial; the rest become module constants, and `arena-config.py`'s "seat barks" block (17 rows) and the README table (`packaging/README.md:524-559`) shrink to match. One is already a doc bug: `ARENA_VOICE_DUTY_HUMAN` is documented as 0.4 (`README.md:526`, `arena-config.py:54`, note 103) but the code says 0.6 since `c6e266c092c`.

**4. The advisor's bark-tag path costs about 730 prompt tokens per advice call and 790 per recap for 1.6 % of the lines.** `bark_guide()` measured 2,928 and 3,166 characters for the default table (imported and called locally). Across the archives the advisor emitted 127 tags; the voice log shows 13 spoken with source `advice` and 5 with `recap`, the rest skipped by the seat guard, dice or "already said this turn" because `scan_events` (`:2142-2339`) fires the same ids (commander-cast, big-swing, landed-hit, removal, sweep, counter, engine-online, big-mana, kill, that-hurt, got-countered, game-changer) from the ring first. Direction: drop the tag from advice windows and recaps; that removes `BARK_WHEN`/`split_bark`/`bark_guide` (~110 lines, `advisor_runner.py:83-191`), the `recap`/`advice` sources in `maybe_bark`, and `tests/test_advisor_barks.py` (152 lines). Behaviour lost: the model-chosen `taunt`/`respect`/`slow-turn` (4, 0 and 10 spoken).

**5. Three mechanisms notice a slow seat.** `mutter()` (`:2117-2141`, `THINK_S` 8 s → "thinking", 5 spoken), `slow_seats()` (`:1826-1841`, `ARENA_BARKS_SLOW` 20 s → play-faster 6, thinking-hard 3) and the advisor's `slow-turn` tag (10). The two runner mechanisms glob the same three inboxes every step. Direction: one inbox scan feeding one line family.

**6. Chain rows never exercised, and a proposal that does not stop where its comment says.** Of 109 openers in `chains.json` (166 role/reply rows), 18 never fired in any form in twelve games: respect, nice-play, why-me, attack-them, gc-react, lost-commander, cast-big, cast-planeswalker, holding-mana, grudge, again-countered, not-again-sweep, you-promised, mull-to-four, mull-pity, mull-risky, loop, looping (36 rows). Separately, `_respond_to_proposal` sets `self._chain = None` with the comment "no third round" (`:1544`), but `after_spoken` plans from `item["chain"]`, not `self._chain`, and the yea/nay replies carry hop 1 while `disagree` invites `origin: clapback`, `you-wish` invites `laugh`, `laugh` invites `clapback`. Live pairs show the continuation pattern already (`disagree → laugh` 8, `disagree → clapback` 7, `you-wish → you-suck` 8). Unverified live for proposals themselves (no game since `c6e266c092c`).

**7. The memory layer has mostly not paid out yet.** `a546a3071cd` added 84 lines (deals, grudges, third counter, second wipe, heads-up, arc). In three games: heads-up 1, long-game 6, someone-wins 1; grudge, again-countered, not-again-sweep, you-promised 0. "deal" filler fired 26 times and drew 13 "promise" replies, but the truce's payoff never came. Direction: keep `_deals` (it is cheap and its opener fires), park the grudge and counter counters behind a game that shows them, or lower `GRUDGE_EVERY`.

**8. Dead code and stale prose in the runner.** `RECENT_WEIGHT` (`:170`) is never read; `gid` (`:2389`) and `self.game_id` (`:1112`) are assigned and never used (inherited from `arena`); `PRIORITY["bark"]=8` (`:85`) is unreachable because `maybe_bark` always passes `prio`; the `chatter_level` docstring (`:189`) still says every knob is multiplied by the dial, which `apply_chatter` (`:1122-1138`) stopped doing in `2c1f7533028`; the module docstring (`:1-56`) describes a Joshua-only runner and lists 10 of 30 knobs; `card_slug` exists twice (`voice_runner.py:342`, `card_lines.py:42`); `DEFAULT_TABLE` and roster-to-seats logic exist twice (`advisor_runner.py:45,330`; `voice_runner.py:266,269`); `seatd/runner.py:825` contains `A if False else B`, whose `A` is dead text.

**9. The cards sub-library is a long tail by design, but half of it is a pair where one would do.** 188 ids per voice, 792 takes, 134 MB baked; 11 ids spoken in three games. Every combo shape carries `-online` and `-react` (74 ids, 222 takes, 40 MB) while the generic `engine-online` spoke 18 times and one named combo once. Direction: one line per shape (the react), and let the owner's crow stay generic; low priority since Ben asked for named cards.

**10. Small efficiency wins that keep behaviour.** `scan_observer` (`:2383-2390`) reads and parses the whole snapshot every step (0.5 s, 0.1 s while a hop is pending) with no mtime check; `enabled()` reads two control files in `step()` and again in `publish_state()` and every 200 ms during playback; `VAdvisor.followVoice` polls a file at 250 ms beside the existing 1 s `refresh` timer. `_board_fp` (`:2394-2395`) uses `len(events)`, which saturates at `EVENT_RING = 30` (`ObserverSnapshot.java:90`), so after the thirtieth event that component never changes; the last `seq` is the right signal.

Ranked by lines or bytes removed against behaviour lost: (1) raws, 351 MB for nothing; (2) colour address lines, 97 MB for nothing today; (4) advisor bark tags, ~260 lines plus prompt tokens for 1.6 % of lines; (3) knobs, ~60 lines of env parsing plus 30 doc rows for a dial nobody used; (5) slow-seat scans, ~40 lines; (7) memory counters, ~40 lines pending evidence; (9) combo pairs, 20 MB.

### Concerns

The six-by-six interplay is what needed twenty fix commits in four days. In game 48 the runner recorded 65 patter governor skips, 45 chain dice skips and 32 patter dice skips against 105 lines spoken: two to three candidates per line. That is cheap in CPU but every gate is a place a future tuning session will reach for a new constant instead of removing one. The silence floor (`:1940-1953`) is a third clock that overrides both dice and budget and has no live game behind it yet. The seatd loop work (`8c6f887aba9`, +314 lines, +138-line fixture) is not a voice feature and rode along on the branch; in its one game it made two LOOP OFFERs, armed one cycle at 14:10:29 (until life >= 190) and broke it three seconds later on bind/validate, replaying zero rounds (`seat-1.log`; `"source": "cycle"` count 0 in game 48 `game.jsonl`). The README says the audio is "about 270 MB of the package"; the baked WAVs measure 323 MB, and note 103's "~185 MB baked" for the new sub-libraries measures 253 MB.

### Bugs and corrections

1. `ARENA_VOICE_DUTY_HUMAN` is 0.6 in code, 0.4 in three documents (see finding 3).
2. `seatd/runner.py:825`: the `if False else` conditional expression should be one condition.
3. `_board_fp` should carry the last event `seq`, not the ring length (finding 10).
4. `_respond_to_proposal`'s "no third round" is not what `after_spoken` enforces (finding 6); either strip `chain` from the yea/nay items or check `self._chain`.
5. `chatter_level` docstring and the module docstring are stale (finding 8).
6. `GuiPilotMatch.advisorLobbyOrGuiPlayer` (`:130`) now returns `new LobbyPlayerHuman("Player One")` where it returned `GamePlayerUtil.getGuiPlayer()`, which carries the user's preference name and avatar; the no-advisor launch loses them. Intended?
7. `human_mulligans` (`:1225-1226`) subtracts one card in the DRAW phase assuming the snapshot lands after the draw; I could not verify the ordering from the logs.
8. `RECENT_WEIGHT`, `gid`, `game_id`, `PRIORITY["bark"]` are dead.

### Feature suggestions

Split `voice_runner.py` into three files with no behaviour change: `renderer.py` (Player, Renderer, glitch and lite FX, `:458-973`, all pre-branch and stable), `table.py` (voice assignment, address, cards, combos, `:202-426`) and the daemon. Make the silence floor the only patter clock and delete the due-clock and its three knobs. Collapse `BARK_PRIORITY`'s five tiers to the two classes the governor already uses (event, card and procedural are all 5.5). Move every remaining constant into one `voice-tuning.json` next to `chains.json` so tuning is a data edit and `arena-config.py` lists one voice dial.

### Observability and efficiency

`arena-hygiene.py` already prints the anchored share; add "distinct ids spoken / ids in the seated libraries" so unused takes surface after every game rather than in a review. Record the candidate count per patter tick so the two-to-three-candidates-per-line ratio is watched. Stat before parse in `scan_observer`, one `enabled()` per step, one inbox glob per step, and fold the 250 ms focus poll into the 1 s refresh.

### Questions for Ben

1. Raws in git: the parents' precedent was 12 MB, this is 351 MB. Bucket, archive, or keep?
2. Which of the 36 knobs have you actually wanted to turn? The archives say only `ARENA_CHATTER`.
3. Colour-identity address lines: future-deck insurance, or render per commander on `arena-add-deck`?
4. Advisor bark tags: keep the model-chosen taunt/respect/slow-turn at ~750 tokens a call, or let the event ring own the table's mouth?
5. Should the seatd loop stop conditions merge on their own, with their own game evidence?
6. Is "Player One" replacing your preference name in the no-advisor launch intended?

Verified by running: `git log --format=%h%ci%s arena..HEAD`, `git diff --stat arena...HEAD`, `git diff arena...HEAD -- <files>`, `git show arena:forge-arena/runner/*.py | wc -l`, `git log -S'DUTY_HUMAN_MULT = 0.6'`, `git ls-files`, `git count-objects -vH`, `du -sh`, `python3 -m unittest discover -s tests` (453 OK in 22.8 s), Python aggregations over `voice/stock/voices/**/manifest.json`, `chains.json`, `address.json` and `logs/archive/<stamp>/{voice-0.jsonl,advisor-0.jsonl,voice-0.log,run_table.out,seat-1.log,game.jsonl}`, a local import of `advisor_runner.bark_guide` with `voice_runner.load_seat_libraries`, and `/usr/bin/grep` over the runner, scripts, README and Java sources.

---

# 4. Grower

## Grower — The table now talks about the game a third of the time at half the density Ben asked for; the 9/14 commits aim at the right gap but have not been heard, and one of them may overshoot.

### What this branch built, as the Grower reads it

Fifty-two commits turned Joshua's one-voice advisor into a four-voice table. The thing to measure is not the code but the ask, and Ben stated it in numbers: `scripts/arena-hygiene.py:139` says "Ben's goal is an anchored share past 60 % at about 8 lines/min". His qualitative notes in the log are consistent with that: "playing with the AI should feel like sitting at the table with people" (voice_runner.py:171), "minimal on my turn" (game 44), "a little patter during the human turn, especially if I idle, is okay" (2026-09-11, voice_runner.py:147), "we need more dedicated lines around mulligans" (W-19), "Vault's gone!" fell flat (game 47, table_lines.py:285), and "too many long pauses" (game 48, voice_runner.py:104).

Measured against that target from `voice-0.jsonl` (my own script plus the archived `hygiene.txt`):

| game | stamp | lines/min | speaking share | seat lines | anchored (hygiene) | about-the-game by manifest category | same line any seat within 5 min |
|---|---|---|---|---|---|---|---|
| 45 | 20260910-214016 | 7.82 | 31 % | 267 | (no source field yet) | 0 % (49 % reply, 43 % patter) | 172 |
| 46, post-fix window | 20260911-105547 (+330 min) | ~2.4–3.4 | duty 0.20 | 87 | 27 % | 33 % | 26 |
| 47 | 20260911-204333 | 4.97 | 23 % | 133 | 38 % | 36 % | 39 |
| 48 | 20260914-141513 | 4.88 | 21 % | 97 | 27 % | 32 % | 33 |

Game 45 had Ben's density with nothing to say; games 47 and 48 say something about the game a third of the time at 60 % of the density. Repeats fell fivefold. That is real progress and the mix is the harder half. The density was lost to the governor, and Ben heard the loss as "too many long pauses". The time spent inside gaps longer than 24 s went from 11 % of game 45 to 30 % of games 47 and 48; the median gap went from 2.9 s to 6 s.

### Top findings (ranked)

**1. The talk budget is an asymptote, not a budget, so the table sits at ~60 % of the dial.** `governor()` (voice_runner.py:1315–1329) gives an optional line `(1+head)·(0.15+0.85·head)` at rowdy; at duty 0.24 against goal 0.36 that is 0.58, which is exactly what game 48 logs ("governor (duty 0.24 vs goal 0.36, p=0.58)"). As the table nears the goal the chance falls to 0.15, so mean duty settles at 0.21–0.24 (hygiene: 0.20, 0.24, 0.21 for games 46–48) and never reaches 0.36. Seventy of game 48's 97 seat lines were optional (patter 45, chain 25), so this shaped the whole game. Direction: let the goal be a mean, not a ceiling — full chance below it, taper only above — and measure duty after game 49 before touching the floor. The rowdy dial should produce rowdy.

**2. The silence floor divides by the dial and at rowdy becomes 6 s; it will set the density, and it fills with filler.** `patter()` computes `floor = SILENCE_FLOOR_S[...] / max(0.25, self.chatter) * mult` (voice_runner.py:1926), so 12/24 s become 6/12 s at chatter 2.0. Game 48's median gap was already 6.2 s. The floor speaks with `p=1.0` and `ungoverned` (1717–1718) from `patter_candidates` (1842–1908), a list dominated by `nothing-happening`, `this-is-fine`, `good-hand`, `what-turn`, `deal`, `pass-already`, `cards-in-hand`, `board-envy`. The 5-minute cross-seat repeat rule shrinks that pool fast, so the floor is self-limiting to roughly two lines a minute — but those lines are the very kind Ben called "38 % filler". Meanwhile the governor and dice still killed 30 procedural narrations and 45 chain replies in game 48. Direction: do not scale the floor by the dial (or scale it gently), let it prefer board-anchored candidates (numbers, threat calls, `pass-already` at the active seat) and fall to filler last, and record the candidate pool size on the "silence floor" record so game 49 tells us how often it ran dry.

**3. Questions hung about half the time — verified, and the fix is unheard.** In game 48 I count 19 spoken questions (`deal`, `deal-*`, `whats-your-life`, `cards-in-hand`) with 8 answered by a chain hop within 12 s and 11 hung; Ben counted 8 of 17. Examples: `deal-urza` at 14:02:37 was followed by Bill's `cast-creature`, not an answer; `whats-your-life` at 14:09:11 got `board-envy` from a bystander. c6e266c092c makes hop 1 certain and bans questions to the human (voice_runner.py:1604, 1622, 1855). Direction is right; what to watch in game 49 is whether certain answers plus the proposal round (`PROPOSAL_P` 0.85 from every other player, 1511–1545) turn every `hit-X` into a three-line block that crowds out the procedural lines.

**4. Ben's mid-game runner restarts worked, but a restarted runner forgets what was said.** `voice-0.log` shows "up" at 13:53:06, 14:07:38 and 14:12:07, two seconds after 7caad07a40a (14:07:36) and 25e803b19f6 (14:12:05), so those fixes were live for the last 7½ and 3 minutes of game 48, and only c6e266c092c and a0db117d8b1 are unheard. A fresh runner reads the old log for the startup line only (1237–1242); `_said_at`, `_seat_said_at` and the shuffle bags (1046–1047, 785–799) start empty, so `board-envy.wav` played at 14:12:03 and again at 14:13:43 across the restart. Direction: on restart, replay the last five minutes of `voice-0.jsonl` into the recency maps the way the startup check already reads it. This matters because Ben's habit is to hot-swap the runner during a game.

**5. Exact-take repeats come from single-text ids, and the worst offenders are the most-picked patter lines.** `harry/manifest.json` has 13 of 66 ids with one text, including `pass-already`, `board-envy`, `empty-hand`, `what-turn`, `play-slower`; every named address line (`deal-urza`, `hit-selvala`, `threat-urza`) has one text (table manifest: 220 of 263 ids single-text, mostly numbers and addresses by design). Game 48 played `pass-already.wav` 5 times, `board-envy.wav` 5, `deal-urza.wav` 4, `hit-selvala.wav` 3; game 47 `pass-already.wav` 6; game 45 9. Same audio, same intonation, is what a listener hears as a machine. 25e803b19f6 caps these at once per five minutes across seats, which will help; a second wording each for the dozen single-text patter ids and a fallback from a named take to the generic when the named one was heard recently would finish the job. Direction, not a patch: rank ids by (times spoken ÷ takes on disk) across the archive and render wordings where the ratio is worst.

**6. The loop the table can name is only a game-changer loop; the loop that won game 48 was silent.** `loop_tick` is called only inside `if spell in self.game_changers` (voice_runner.py:2226, 2251) and for departed game changers (2282). Urza's kill in game 48 was a Top/Clue/Aetherflux storm; `seat-1.log` 14:09:57–14:10:25 reads "Loop step 1…", "Declaring the loop to life 190", and `voice-0.jsonl` has no `loop`/`looping` record. Game 47's Mana Vault loop (turn 20, 138 seat-1 decisions in 6 min 14 s) drew three card lines then 44 "already said this turn" skips while the table talked filler over it. Direction: the runner already tails `game.jsonl` for mulligan reasons (1154–1211); tail the brain's `why` for its own loop declarations and let the owner announce it and the table react. The brain literally says the word.

**7. Filler blocked the kill shot.** At 14:14:35 Bill said `nothing-happening` (patter); at 14:14:36 his `landed-hit` (event) was skipped "seat guard (2s < 5s)". The seat guard is bypassed for `OWN_ACTION_LINES` (1707) but `landed-hit` is not in the set and the guard does not evict a lower-priority line. Direction: an event line should beat a seat's own filler played seconds earlier — evict or bypass — the ladder already says events outrank patter (BARK_PRIORITY, line 95).

**8. The quiet-on-your-turn rule applied while Executive was playing Ben's seat.** Hygiene shows seat 0 made 70 decisions in game 48 and 41 in game 47, so the advisor's runner held the human seat for most of both games; `duty_goal()` (1311) still cut the budget to 0.14 on those turns (21 spoke records at goal 0.14 in game 48) while `executive_on()` (1369) gates only "your move". Ben was a spectator on those turns. Direction: treat seat 0's turn as an AI turn for the budget when Executive is on.

**9. The opening minutes are the quietest and the emptiest.** In game 48 the turn-1 window sat open from 13:55:14 to 13:58:55 (BL-49). The table said eight filler lines at goal 0.14, then noted "idle table" at 13:57:39; five of the game's eleven gaps over 24 s fall in this stretch. A real table says "we're waiting on you" or ribs the hand. Direction: a small "waiting on Player One" family keyed to the human's open window, not to the board.

### Concerns

The 9/14 commits stack three density-raising changes (floor, certain answers, proposal rounds, DUTY_HUMAN_MULT 0.4 → 0.6) on top of a governor that under-delivers for a structural reason; game 49 may swing from "too quiet" to "never stops" without telling us which lever did it. Run one game with the floor alone before the rest, or log each lever's contribution. The idle-table slowdown (150 s) and the floor interact: at an idle table the floor is 18 s at rowdy, which is fine, but the human-away case in game 48 produced pure filler, and more filler is not what an idle room needs.

### Bugs and corrections

BL-50 is exactly as written: 14:14:42 queued `that-hurt`, `kill`, `heads-up`; 14:14:47 Joshua's generic elimination; `kill` vanished without a record; the others "dropped game over"; no `human_out`. The mulligan guard is as written: 13:54:39 Harry `mull-dig`, 13:54:40 Harry `keep-seven` skipped "seat guard (1s < 5s)". The two game-48 LOOP OFFERs (14:02:14, 14:09:22) were both judged "Not a loop" by the brain, confirming the three-repeat change. Small discrepancy I did not chase: the runner's "up" line prints "chains … max 4" while `chains.json` and the launch config say `max_hops` 3. I could not find Ben's uncanny-valley note anywhere in the repository; only the review brief mentions it.

### Feature suggestions

Ranked by how much of Ben's stated target they buy: (1) procedural narration ungoverned like mulligans, since it is the cheapest "about the game" line and 30 of them died to dice in game 48; (2) the brain-declared loop line; (3) a "kill shot" family for Aetherflux-style multi-kills, since game 48 ended with one generic Joshua line for three deaths; (4) recency replay across restarts.

### Observability and efficiency

The hygiene line should print Ben's two target numbers beside the measured ones (lines/min and anchored share) and add the gap distribution (median, p90, seconds inside gaps over 24 s), since that is what he hears. Add to each "silence floor" record the pool size and the picked category; add a `turn`/`activeSeat` field to every voice record so human-turn analysis does not need a join with `game.jsonl`. Skips are 65 % of game 48's records and 82 % of game 46's; they are the best data on the branch and cost nothing.

### Questions for Ben

Is 8 lines/min still the target now that the mix is a third about the game, or did game 45's density only feel right because nothing in it mattered? At rowdy, is a 6-second floor what you meant by "too many long pauses", or were you hearing the 30–60 s gaps? Should the table stay quiet on your turn when Executive is playing it? Where is the uncanny-valley note, and which moment in game 48 prompted it?

Verified by running: `git log --format='%h %ci %s' arena..HEAD`, `git log -p arena..HEAD -- runner/voice_runner.py` (constants), `python3 -m unittest discover -s tests` (453 OK in 22.9 s), my scratchpad `voice_stats.py` over stamps 20260910-190517 … 20260914-141513, ad-hoc Python over `voice-0.jsonl`/`game.jsonl`/`seat-1.log` for games 47 and 48, `sed`/`grep` on voice_runner.py, chains.json, the three voice manifests, arena-hygiene.py, BUG-LOG.md, PATCH-NOTES.md, README.md, INTERACTIVE-ARENA.md and each archive's `hygiene.txt`, `voice-0.log` and `launch-config.txt`.

---

# 5. Maintainer

## Maintainer — The table works, but it forgets everything on restart and cannot yet explain itself after the fact

### What this branch built, as the Maintainer reads it

Fifty-two commits (arena `3e037fdc9a9` → `e517f2eb300`) add a fourth long-running process to the table: a Python voice runner (`runner/voice_runner.py`, 2,637 lines) that polls `mailbox/observer-state.json` every 0.5 s (0.1 s while an exchange is pending), tails `advisor-0.jsonl` and `game.jsonl`, and plays pre-rendered WAV takes through `afplay`. The Java side grew a 30-entry public event ring in `ObserverSnapshot` (`attack`, `damage`, `countered`, `cast`, `left`, `gameover`, per-seat `pool`), a tab-follow timer in `VAdvisor`, commander-based seat names, and a teardown handshake (`seat-0-voice/final.json`, `arena-autostop.sh` lines 64–75). The seat runner gained `until` stop conditions and a loop offer. 5,184 WAV files (675 MB) now sit in the git tree; the suite is 453 tests, green in 21.5 s, and leaves the tree clean.

Everything I found is verified against the head code and the archived logs unless marked otherwise. No live game has run on the head code: game 48 ended 14:15:06 and the last three behaviour commits landed at 14:20, 14:31 and 14:31.

### Top findings

**1. Mid-game restarts wipe the runner's memory, and they happen two or three times a game.** `voice_runner.out` in every archived game shows the supervisor line `runner exited (143)` after a `Terminated: 15`: game 48 at 14:07:25 and 14:12:03, game 47 at 20:19:21, game 44/45 three times between 21:06 and 21:08. Each one lines up with a commit to the second (7caad07 14:07:36, 25e803b 14:12:05, 34359df 20:19:21) — they are hot reloads of fresh code into a live game, not crashes (zero `step error` lines, zero tracebacks across seven games). The constructor rebuilds `eliminated`, `_seen_seats`, `_gc_cast_seen`, `_combos_done`, `_deals`, `_hits_from` from nothing (voice_runner.py:1032, 1089, 1115–1116); only the startup line is re-derived from the jsonl (:1237). After a restart a seat already dead is back in `voiced` (:1566) and `living` (:1931), so it can be picked as a bystander or patter speaker — Ben's game-42 complaint reappears by construction — and the BL-50 vanish detection is blind to any seat that left before the restart, because that seat was never in `_seen_seats`. Direction: make the runner's game memory recoverable — either rebuild it on start from its own `voice-0.jsonl` (`noted`, `human_out`, the `eliminated` events, game over) or checkpoint a small `state.json` beside the heartbeat; and fix the seam at the source (option in BL-50: iterate `getRegisteredPlayers()` with `eliminated: true`) so the snapshot itself carries the truth a restarted process can read.

**2. The records cannot place a line in game time, and the snapshot stream they depend on is never kept.** Game 48's `voice-0.jsonl` has 404 records with keys `ts, event, kind, text, stock, seconds, chars_used, library, seat, file, duty, goal, source, why, seq, hop, parent` — no `turn`, `phase`, `activeSeat`, and no ring `seq` for an event-sourced line. `observer-state.json` is a single overwritten file that `arena-stop.sh` deletes (line 84); the game 48 archive has no copy. A complaint like "Bill said 'no blocks' when I had a blocker" can only be reconstructed by joining wall clocks against `game.jsonl` and guessing the board. The eviction trace added in a0db117 is the right instinct; the game 48 log shows why it was needed (14:14:42 `queued kill seat 1`, then `player-eliminated` at 14:14:47, then nothing — no record at all). Direction: stamp every record with `turn`/`phase`/`active` from `_last_snapshot`, carry the ring `seq` on event-sourced barks, and have the observer (or the runner) append the ring events to a small `events.jsonl` that gets archived — a few KB per game.

**3. A muted table takes three minutes to tear down instead of five seconds.** `step()` returns at :2566 when `enabled()` is false, before `scan_observer` runs, so `final_locked` is never set and `final.json` is never written; the heartbeat thread (:2590–2600) keeps the runner "alive" for the watcher, which waits `ARENA_AUTOSTOP_VOICE_WAIT` (60 s) and then the full `LINGER` (120 s in human mode, arena-play.sh:96). The same holds when the advisor is paused. Direction: publish `final.json` on game over whether or not the voice is enabled (a muted sign-off still "drains"), or have `voice_alive` also check `state.json`'s `enabled`.

**4. 675 MB of WAV in the repository, with no LFS and half of it never shipped.** `git ls-tree` at HEAD: 2,585 raw takes (347 MB) plus 2,599 baked (328 MB); `.git` is 1.9 GB with 4,419 loose objects (424 MB) and a stray `tmp_pack` from an interrupted repack. `.gitattributes` is `* text=auto` only. The package excludes the raws (build-light-package.sh:160–163), yet three test files pin every raw as a file that must exist (test_table_lines.py:128, test_card_lines.py:88, test_bark_libraries.py:110), so the raws cannot be moved out of the tree without touching the suite. Every push to the private remote now carries this weight, and every future wording round adds ~1.4 MB per line (baked + raw). Direction: keep raws as release assets in the bucket the packager already uses, or LFS, and let the tests assert the raw's existence only when a `--raw` flag or the raw directory is present. Separately, `git gc` when convenient.

**5. The observer's event handling fails silent and the drift surface grew.** `ObserverSnapshot.noteEvent` swallows `RuntimeException` (:199, also :297, :318, :453) and depends on record accessors of eight upstream event classes (`a.attackersMap()`, `d.combat()`, `z.mode()`, `c.si()`, `rm.sa()`, `o.winningPlayerName()` …). A rename breaks the build loudly — good — but a semantic change (an event firing under a different mode, a null where a value was) simply stops the ring filling, and nothing counts ring events per kind: `WRITES` is only read by `ObserverSnapshotWriteTest`. The `-S<n>` name convention is now parsed in three places (`VoiceFocus.TAB_SEAT`, `arena-status.py:28`, `GuiPilotMatch.seatLabel`). Direction: at game over, log one line from the observer (writes, events by kind) and one from the runner (events consumed by kind); make `arena-hygiene.py` compare them. Put the seat-name parser in one Java helper and one Python helper.

**6. `scan_game_log` has the partial-line bug `scan_advisor` already fixed.** It reads to `size` and advances `_game_log_pos` to it (:1173–1176) without cutting at the last newline and without tracking the inode; `scan_advisor` does both (:2348–2356, the "Gemini P1" fix). A `MULLIGAN` record caught mid-write is dropped for good. Low frequency, but W-19 lines are exactly the ones this path carries. Direction: share one tail helper between the two.

**7. Two consecutive stalls do not rotate the session (W-18 still open).** `PersistentClaude.call` kills the process on timeout (brain.py:204–210) and the next call restarts it on the same `--resume` session; only `WEDGE_FAILS=3` over 60 s or `WEDGE_HARD_FAILS=6` (brain.py:34–36) forces a fresh session, and rotation is token-driven (`ARENA_ROTATE_TOKENS` 250k, `ARENA_ROTATE_HARD` 600k, runner.py:58,66). Game 48 rotated twice (transport-events.jsonl) for size, not health. Direction: a second back-to-back persistent timeout should trigger `_maybe_rotate(hard=True)` — the transcript survives rotation, the wedged process does not.

**8. Least privilege on the ElevenLabs key.** Handling is clean: no key shapes anywhere in tracked non-audio files or in any archived log (grep count 0), `launch-config.txt` prints `ELEVENLABS_API_KEY=set`, `arena-config.py:102` masks it, the runner only ever puts it in a header (:919, :954). But `arena-play.sh` scrubs OpenRouter/OAI keys from the voice and advisor processes (:182, :193) while `run_table.sh` (:171) and the advisor inherit `ELEVENLABS_API_KEY` although only the voice runner needs it; `brain.py` passes no `env` to `Popen`, so every `claude -p` child carries it. Tools are disabled (`--disallowedTools *`, brain.py:399), so exposure is theoretical. Direction: `env -u ELEVENLABS_API_KEY` on the seat and advisor launches.

### Concerns

- **Idle behaviour under the new silence floor is untested live.** Game 46 ran 02:14 → 10:03 with 1,527 voice records (975 "already said this turn" skips) and an empty `autostop.out` — the watcher never saw game over. The idle fixes (`IDLE_S` 150, `IDLE_SLOWDOWN` 3) slow the clock, but c6e266c's floor speaks "regardless of dice and budget" every 36 s (AI turn) or 72 s (human turn) at normal until the per-turn `(speaker, line)` set is exhausted — roughly 45 forced lines on a game left on the human's priority. Bounded, but watch game 49.
- **The floor and the governor pull against each other.** At every dial the floor alone lands near the duty goal (12 s ÷ chatter with ~2.5 s lines ≈ 0.09–0.29), so the governor's `skipped` records become noise rather than signal.
- **`stat -f %m` in `voice_alive` is BSD syntax.** On GNU stat `-f` means file-system status; the arithmetic would misbehave. Unverified on Linux; the Player class claims Linux support.

### Bugs and corrections

- Findings 3 and 6 above are bugs.
- `arena-hygiene.py:111` counts restarts from `run_table.out` only; game 48's report says `restarts 0` while the voice runner restarted twice. The `RESTART_LINE` regex would match `voice_runner.out` if it were included.
- `scan_observer` computes `gid` (:2388) and never uses it.
- The unclosed-socket `ResourceWarning` at the end of the suite comes from `test_backends.py`'s loopback server, not from any network call.

### Feature suggestions

- A `--replay <archive>` mode for the voice runner that re-reads an archived `game.jsonl` plus the proposed `events.jsonl` with a fake clock and prints what it would have said — the only way to regression-test a live complaint without a live game.
- One `[voice] game summary` line at the final marker: lines spoken by source, duty mean, evictions, restarts, ring events consumed.

### Observability and efficiency

- CPU: the runner parses the full snapshot 2–10 times a second with no mtime short-circuit (:2383–2386); the advisor parses it 4 times a second (advisor_runner.py:38, 238–244, 979); `enabled()` reads two control files per call and runs twice per step plus every 0.2 s during playback (:686). Cheap today; stat-before-parse would make the idle table nearly free.
- Disk: `logs/cache/voice` is 173 MB in 208 files (854 KB average, 44.1 kHz WAV) after one week, growing 3–10 renders a game with a near-zero hit rate (advice sentences are unique); README says "no size cap". An age or size cap is a one-liner of policy.
- Package: the baked takes are 22.05 kHz 16-bit WAV (~44 KB/s); `afplay` decodes AAC/MP3, and `wav_seconds()` is the only reason the runner needs WAV — a duration field in the manifests would let the package drop from ~330 MB of audio to well under 100.
- Tests: the suite is fixture-pinned to exact library counts (`290 + 30 + 27 + 6` per voice, 63 stock phrases) and to ~2,600 real files on disk, so it cannot run from a package checkout and every new wording is a test edit. Clocks are injected where it matters (test_table_budget); `mutter`/`slow_seats` use wall-clock mtimes by necessity.

### Questions for Ben

1. Are the mid-game SIGTERM reloads a habit you want supported (then the runner must recover its memory) or one to stop once 4.2 ships?
2. Do you want the BL-50 seam fixed in the observer (`getRegisteredPlayers`) before the next round, accepting the audit of `arena-status.py`, `arena-public-state.py`, the round clock and autostop?
3. May the raws leave the tree for the release bucket, given the tests pin them today?
4. Is a linux/Windows table a real target, or can `voice_alive` stay BSD-only with a comment?

Verified by running: `git log --stat arena..HEAD`, `git diff arena...HEAD -- <files>`, `git ls-tree -r -l HEAD -- forge-arena/runner/voice/stock`, `git count-objects -vH`, `git status --porcelain`, `du -sh` over `runner/voice/stock`, `runner/logs/cache/voice` and the archive stamps, `python3 -m unittest discover -s tests` (453 OK, 21.5 s), Python one-liners over `voice-0.jsonl`, `voice_runner.out`, `voice-0.log`, `transport-events.jsonl`, `autostop.out` and `hygiene.txt` for stamps 20260910-190517 through 20260914-141513, and `/usr/bin/grep` over the runner, scripts, tests, Java sources and `forge-game/src/main/java/forge/game/Game.java` (`onPlayerLost`, lines 861–1014).

---
