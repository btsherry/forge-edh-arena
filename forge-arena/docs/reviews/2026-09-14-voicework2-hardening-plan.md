# voicework2 hardening plan — mined from the five-lens review

**Date:** 2026-09-14 (evening). **Status:** PLAN, nothing executed. **Inputs:** the five analysts'
reports in `docs/research/ai-native-roles-review-2026-09-14.md`, spot-checked against the code at
`1b99b0d56d2`. **Branch:** `experimental/voicework2` (never pushed; no commits to `arena`).

**Ben's decisions so far (2026-09-14):** a hot-swapped runner is normal and must not forget; the
silence floor stays as built until he reports whether it overshoots at rowdy; add a second "under"
channel and the non-verbal atoms; kill all unused raw takes; yes to recommendations 1–4 (restart
memory, floor pool logging with anchored preference, turn/seat stamps + event tape + replay mode,
brain intent for loops + a `say` key). Everything else below is proposed and waits for him.

**Ben's decisions, later the same evening (answers to §9):** (1) purge the raws from the branch
history before the merge, with a bundle backup kept in the repo directory and gitignored; (2) KEEP the
advisor's bark tags and KEEP the colour-identity address lines — the system will be distributed to
people who ingest many decks of their own, and the colour fallback is what speaks for a commander
nobody rendered; (3) governor as a mean, not a ceiling — rowdy should be rowdy; (4) no agent work
split: one pair of hands, serially; (5) audio stays WAV — the Windows (winsound / .NET SoundPlayer)
and Linux (paplay / aplay) backends play WAV only, so AAC would need a new dependency on every
other machine; (6) the observer fix waits on more context (given in chat); (7) heckles at the player
are welcome, but the advisor never responds to them: Joshua is a ghost outside the game, the seats
speak to the player, and the player cannot talk back to the seats yet — so the chain planner's
"Joshua answers a line aimed at the human" path is removed (A14); deals between seats stay, and a
player → advisor → seat-brain relay for the human's own deals is a feature-push item, not this
round; (8) "Player One" stays the human's name in every human game; in a four-player all-AI game
every seat is named `<Commander>-S<n>` (already the code since `e1e261da125`; unverified live since,
see A13). The feature push comes after this round; the features Ben is taking are the ones in §4
plus §5.1 and the heckle family with the rule above.

Ground rules for the work: suite green before every commit; the FULL Maven gate only for Java
changes and never during a game; message file written before any conditional commit; secrets never
printed; upstream Forge files untouched.

---

## 1. Bug ledger

Every bug or correction the five reports raised, deduplicated. "Rep." names the reporting lenses
(P Prototyper, B Builder, S Sweeper, G Grower, M Maintainer). Phase numbers refer to §6.

### 1A. Run-time correctness (voice runner)

| # | Bug | Evidence | Fix direction | Rep. | Phase |
|---|---|---|---|---|---|
| A1 | A respawned runner forgets who is dead, which combos it announced, what was said recently, and the vanish detector is blind to seats that left before the restart | `voice_runner.py:1032,1089,1115-1116`; restarts at 14:07:25 and 14:12:03 in game 48 (`voice_runner.out`, exit 143 = SIGTERM hot reload); `board-envy.wav` 14:12:03 and 14:13:43 across a restart | Checkpoint `logs/voice-state.json` (§4.1); load on start when the game id matches; fall back to rebuilding recency and eliminations from `voice-0.jsonl` | B1 G4 M1 | 0 |
| A2 | Every restart speaks a forced line within seconds | `last_spoken_at = -1e9` (`:1101`) makes the floor's `silent_for` astronomical; 5 of 5 restarts spoke in 3–6 s | Initialise the clock from the checkpoint, else from the last `spoke` record, else `now` | B2 | 0 |
| A3 | Proposal replies invite a second hop: the "no third round" comment is not what `after_spoken` enforces (it plans from `item["chain"]`, not `self._chain`) | `:1511-1545`, `:1560`; `disagree → laugh` 8, `disagree → clapback` 7 already live for ordinary chains | Mark yea/nay and retort items `terminal`; `after_spoken` returns on a terminal item | P4 S6 | 1 |
| A4 | Loop detection is gated on the game-changer list; the Top/Reservoir loop that won game 48 drew no `looping` | `:2244-2251`; `seat-1.log` "Declaring the loop to life 190"; sixteen Top casts | Triggers become: brain intent from `game.jsonl` (§4.4), a game changer self-bounced (kept), and a mechanic trigger: the same card cast ≥ 4 times in one turn | P1 G6 | 1 |
| A5 | A seat's own filler blocks its event line: `nothing-happening` then `landed-hit` skipped "seat guard (2s < 5s)" at 14:14:35–36 | `landed-hit` not in `OWN_ACTION_LINES` (`:1707`); the guard never evicts | The guard holds only between two lines of the same class; an anchored line follows the seat's own optional line freely | G7 | 1 |
| A6 | The quiet-on-your-turn budget applied while Executive was playing Ben's seat (70 seat-0 decisions in game 48 at goal 0.14) | `duty_goal()` (`:1311`) ignores `executive_on()` (`:1369`) | `human_turn` for budget, patter gap and floor = active is the human AND Executive is off | G8 | 1 |
| A7 | `big-mana` never fired: pool ≥ 8 and the dial does not scale it; Urza floated 7 | `apply_chatter` `:1122-1139`; README says the dial lowers thresholds | One constant, pool ≥ 6, no dial | P2 | 1 |
| A8 | `_board_fp` uses `len(events)`, which saturates at the 30-entry ring, so the idle detector can miss activity late in a game | `:2394-2395`; `EVENT_RING = 30` | Fingerprint the last event `seq` | S10 | 1 |
| A9 | `scan_game_log` reads to `size` without cutting at the last newline or tracking the inode; a MULLIGAN record caught mid-write is lost | `:1173-1176` vs `scan_advisor` `:2348-2356` | One shared `_tail(path, state)` helper for both | M6 | 1 |
| A10 | `human_mulligans` assumes the DRAW snapshot lands after the draw (off-by-one risk) | `:1225-1226`; unverified | Verify on the first observer tape (§4.3); fix if wrong | S(7) | 2 |
| A11 | Patter pool exhaustion: `PATTER_REPEAT_S` 300 with "named counts as generic" can empty the pool on a quiet board, and the floor then finds nothing | `25e803b19f6`, `c6e266c092c`; no test | Log pool size on every floor tick; when the pool is empty or filler-only the floor spends an atom (§4.5) | P | 1 |
| A12 | The startup banner prints "chains … max 4" while `chains.json` says `max_hops` 3 | `voice-0.log` up line | Print the loaded value | G | 1 |
| A13 | All-AI tables: every seat must be `<Commander>-S<n>`; the last archived all-AI games (9/10 morning) predate `e1e261da125` and still show `mailbox-seat0-…` | `GuiPilotMatch.seatName`/`buildRoster` (`:227,308`); `GuiPilotMatchRosterTest` | Verify with the roster test and one all-AI launch; fix if seat 0 is mislabelled | Ben | 2 |
| A14 | Joshua answers a seat's line aimed at the human (`plan_reply` returns a Joshua quip when the resolved replier is the human seat) — Ben: the advisor never responds to voices speaking to the player | `chains.py:126-129`; `chains.json` note line 876 | Remove the Joshua branch; a line aimed at the human gets no reply until the player can answer | Ben | 1 |

### 1B. Process, teardown, transport, security

| # | Bug | Evidence | Fix direction | Rep. | Phase |
|---|---|---|---|---|---|
| B1 | A muted voice at game over stalls teardown 2–3 minutes: `step()` returns before `scan_observer` when disabled, so `final.json` is never written while the heartbeat says alive | `:2564-2570`, `:2590-2600`; `arena-autostop.sh:64-75`; LINGER 120 s human mode | `scan_observer` always runs; disabled lines are dropped with a record; `final.json` published at game over regardless | B4 M3 | 1 |
| B2 | `scan_events` skips unseen ring seqs silently (blocking playback vs a 30-entry ring) | `:1474`, ring 30; suspected, not observed | Record a `gap` whenever seq jumps by more than one; move playback to a thread only if it ever fires | B8 | 1 |
| B3 | Two consecutive persistent-call stalls do not rotate the session (W-18) | `brain.py:204-210`, `WEDGE_FAILS=3` over 60 s | A second back-to-back timeout triggers `_maybe_rotate(hard=True)` | M7 | 1 |
| B4 | `ELEVENLABS_API_KEY` is inherited by every seat and advisor `claude -p` child (tools disabled, exposure theoretical) | `run_table.sh:171`, `arena-play.sh:182,193`, `brain.py` `Popen` without `env` | `env -u ELEVENLABS_API_KEY` on seat and advisor launches | M8 | 1 |
| B5 | `voice_alive()` uses BSD `stat -f %m` | shell string in the watcher | `os.stat` in Python, or a comment fencing it to macOS | B M | 1 |
| B6 | The game-48 loop arm broke on bind/validate three seconds after arming; zero cycle rounds replayed | `seat-1.log` 14:10:29; game 48 `game.jsonl` has no `source: cycle` | Replay seat 1's game-48 tape through the harness; decide whether the break was correct (Reservoir shots change target) or a binding bug | S | 2 |

### 1C. Records, metrics, packaging

| # | Bug | Evidence | Fix direction | Rep. | Phase |
|---|---|---|---|---|---|
| C1 | Voice records carry no `turn`, `phase`, `activeSeat`, or ring `seq`; snapshots are never archived; complaints cannot be replayed | game 48 `voice-0.jsonl` keys; `arena-stop.sh:84` deletes the snapshot | Stamp every record; append consumed ring events and changed snapshots to tapes (§4.3) | P B G M | 0 |
| C2 | Three definitions of "anchored" (hygiene, eviction class, governor) — the share Ben steers by measures something else | `arena-hygiene.py:136`; `BARK_PRIORITY`; `OPTIONAL_SOURCES` | One `classify(item)` used by all three | B6 P3 | 1 |
| C3 | Hygiene counts restarts from `run_table.out` only ("restarts 0" in game 48 with two voice restarts) | `arena-hygiene.py:111` | Include `voice_runner.out`; the runner also writes an `up` record with a restart count | M | 1 |
| C4 | Package figures are stale: PATCH-NOTES "about 270 MB", note 103 "~185 MB"; measured baked 323 MB, raws 351 MB | `du` on `voices/` | Re-measure after the raw purge and write the numbers once, in the README | B3 S | 3 |
| C5 | No `*.wav binary` in `.gitattributes`; no packager preflight that every manifest id has audio in DEST | `.gitattributes` = `text=auto`; `build-light-package.sh:160-163` | Add both | B3 | 1 |
| C6 | `logs/cache/voice` grows without a cap (173 MB / 208 files after a week, near-zero hit rate) | README "no size cap" | Age 14 days or 200 MB cap, oldest first | M | 1 |

### 1D. Docs, dead code, duplication

| # | Item | Evidence | Rep. | Phase |
|---|---|---|---|---|
| D1 | `ARENA_VOICE_DUTY_HUMAN` documented 0.4 in `README.md:526`, `arena-config.py:54`, note 103; code 0.6 since `c6e266c092c` (the knob is retired in §2, so the rows go) | B5 S3 | 1 |
| D2 | Module docstring (`:1-56`) describes a Joshua-only runner and lists 10 of 36 knobs; `chatter_level` docstring (`:189`) says every knob scales with the dial; `ARENA_VOICE_YOUR_MOVE` default documented `on`, code `some` | S8 B5 | 1 |
| D3 | Dead: `RECENT_WEIGHT` (`:170`), `gid` (`:2389`), `self.game_id` (`:1112`), `PRIORITY["bark"]` (`:85`, unreachable) | S8 B M | 1 |
| D4 | `seatd/runner.py:825` `… if False else …` debug residue; `_loop_state()` lazy `hasattr` defaults | B9 S | 1 |
| D5 | `card_slug` twice (`voice_runner.py:342`, `card_lines.py:42`); `DEFAULT_TABLE` + roster-to-seats twice (`advisor_runner.py:45,330`, `voice_runner.py:266,269`); the `-S<n>` seat-name convention parsed in three places (`VoiceFocus.TAB_SEAT`, `arena-status.py:28`, `GuiPilotMatch.seatLabel`) | S8 M5 | 0/3 |
| D6 | `GuiPilotMatch.advisorLobbyOrGuiPlayer` returns `new LobbyPlayerHuman("Player One")` in the no-advisor launch, dropping the user's preference name and avatar — intended? | S(6) | ask |
| D7 | The suite's `ResourceWarning: unclosed socket` comes from `test_backends.py`'s loopback server | M | 1 |

### 1E. Observer (Java) — Phase 3, behind the FULL gate

| # | Item | Evidence | Fix direction | Rep. |
|---|---|---|---|---|
| E1 | BL-50 at the source: `ObserverSnapshot` iterates `game.getPlayers()`; a loser vanishes before most polls see `eliminated` | `ObserverSnapshot.java:374,442`; `Game.java:861-1002` | Iterate `getRegisteredPlayers()` with `eliminated: hasLost()`; audit the readers first: `arena-status.py:26,147`, `arena-public-state.py:79`, `advisor_runner.py:285` (round clock), `arena-autostop.sh`; extend `ObserverSnapshotWriteTest` with a lost player | B10 M1 |
| E2 | `noteEvent` swallows `RuntimeException` at four sites; nothing counts ring events per kind, so an upstream semantic change silently empties the ring | `:199,297,318,453`; `WRITES` read only by the test | Failure counters; one summary line (writes, events by kind, failures) at game over; hygiene compares written vs consumed | M5 |

---

## 2. Simplification ledger

| Today | Proposed | Behaviour kept? |
|---|---|---|
| 36 environment knobs on the voice path | 5 operator knobs: `ARENA_CHATTER`, `ARENA_BARKS` (seat-voice kill switch), `ARENA_VOICE_YOUR_MOVE`, `ARENA_VOICE_SFX`, `ARENA_VOICE_FOCUS` (GUI). Renderer settings (`ARENA_VOICE_ID/MODEL/FORMAT/MAX_CHARS/FX/GLITCH`) stay as Joshua's render config; `ARENA_HUMAN_DECK`/`ARENA_SEAT_DECKS` are launch plumbing. The other 24 become constants in one `runner/voice/stock/voices/tuning.json` (data, documented once); `arena-config.py`'s seat-bark block and the README table shrink to match | Yes at defaults; the archives show only `ARENA_CHATTER` was ever set |
| Five "quieter on the human's turn" dials (`DUTY_HUMAN_MULT`, `PATTER_HUMAN`, `SILENCE_FLOOR_S["human"]`, `CHAIN_HUMAN_P`, `BARKS_HUMAN_P`) | One `HUMAN_TURN_MULT` applied to budget, patter gap, floor, chain and react odds — and switched off while Executive plays the seat (A6) | Same feel, one number |
| Two patter clocks (the due clock and the floor) | One scheduler: `due = last_spoken + gap(dial, human, idle)`; candidates ranked anchored (numbers, threat calls, `pass-already` at the active seat) → filler → atom; the governor rolls only filler; quiet ≥ floor skips the dice. The floor's numbers stay as Ben has them until he reports | Yes; the floor becomes a rule inside the clock, not a third clock |
| `BARK_PRIORITY` five tiers (event/card/procedural 5.5, opener 5.8, recap/advice 8.0, patter 8.5) | Two classes (anchored, optional) plus chain; one `classify()` shared with eviction, governor and hygiene (C2) | Yes; event, card and procedural already share a tier |
| Three slow-seat mechanisms (`mutter` 8 s, `slow_seats` 20 s, the advisor's `slow-turn` tag) globbing the same inboxes | One inbox scan per step feeding one line family (thinking at 8 s, play-faster at 20 s) | Yes |
| Advisor bark tags | **Kept (Ben).** The guide text can still be trimmed for tokens without changing what it offers | — |
| Colour-identity address lines | **Kept (Ben):** they are the fallback for every commander other people bring; nothing renders per deck on their machines | — |
| `voice_runner.py` 2,637 lines | Split, behaviour-preserving: `runner/voice/renderer.py` (Player, Renderer, FX — pre-branch, stable), `runner/voice/table.py` (assignment, address, cards, combos, roster — absorbs the D5 duplicates), `runner/voice/scheduler.py` (queue, classify, governor, patter, chains glue), `runner/voice_runner.py` (daemon: scans, events, loop). Tests import the new paths | Yes; the split is Phase 0 so parallel work maps to files |
| Combo `-online` + `-react` pairs (74 ids, 222 takes, 40 MB; 11 card ids spoken in three games) | Keep; Ben asked for named cards. Revisit after five more games | — |
| Memory counters that never fired (grudge, again-countered, not-again-sweep, you-promised: 0 in three games) | Keep `_deals` (its opener fires); lower `GRUDGE_EVERY` 3 → 2; leave the rest until a game shows them | — |

---

## 3. Performance ledger (no correctness risk)

| Change | Where | Why |
|---|---|---|
| Stat before parse: skip the JSON parse when the snapshot's mtime and size are unchanged | `scan_observer` `:2383-2386`; `advisor_runner.py:238-244` (4 parses/s) | 2–10 full parses a second today; an idle table becomes nearly free |
| One `enabled()` evaluation per step, mtime-cached, and the 200 ms playback poll stats the control files instead of reading them | `:686`, `step()`, `publish_state()` | Two file reads per call, several calls per step |
| One inbox glob per step (falls out of the slow-seat merge) | `mutter`, `slow_seats` | Three globs over the same directories |
| `_board_fp` on the last event `seq` (A8) | `:2394` | Correctness and cheaper |
| Cap `logs/cache/voice` (C6) | renderer | 173 MB and growing with no hits |
| `git gc --prune=now` after the raw purge; remove the stray `tmp_pack` | repo | 4,426 loose objects (425 MB), 5 packs (1.49 GB) |
| ~~AAC/M4A~~ **Decided: WAV stays.** afplay decodes AAC, but winsound, .NET SoundPlayer, paplay and aplay play WAV only; ffplay needs ffmpeg installed | — | Revisit only with a portable decoder dependency |
| Not changing: `VAdvisor.followVoice` 250 ms poll | GUI | It is a stat of one small file and the tab follow's snappiness is a feature Ben likes |

---

## 4. Approved new behaviour — designs

### 4.1 Restart memory (recommendation 1; "they should not forget")

- **Checkpoint** `runner/logs/voice-state.json` beside the heartbeat, written atomically on every change of a durable set and at most every 5 s for the recency maps: `gameId`, `eliminated`, `seen_seats`, `combos_done`, `gc_cast_seen`, `heads_up_said`, `sweeps`, `countered_n`, `deals`, `last_hit_by`, `said_at`/`seat_said_at` (last 5 min), shuffle-bag cursors, `last_spoken_at`, the duty window's samples, patter due/anchor, `game_over_said`/`final_locked`.
- **Start:** if the checkpoint's `gameId` matches the snapshot's, load it all; the runner resumes as if it had never stopped, and the first line comes when the clock says so (A2). If there is no checkpoint (a crash before the first write), rebuild eliminations and recency from the last ten minutes of its own `voice-0.jsonl` (the `noted`, `eliminated`, `human_out` and `spoke` records), as `_startup_already_spoken` already does for the opener.
- **Tests:** a scenario runs half way, a second runner is constructed on the same logs directory, and: the dead seat stays silent, the complete combo is not re-announced, no line plays before the first gap, the line said two minutes ago is not repeated, the shuffle bag continues.

### 4.2 The floor's pool (recommendation 2)

- Each "silence floor" record gains `pool` (candidate count), `anchored` (how many were board-anchored) and `picked` (category).
- Candidates rank anchored → filler → atom; the numbers stay as built. Ben reports on rowdy after game 49; the dial division changes only on his word.

### 4.3 Stamps, tapes and replay (recommendation 3)

- Every voice record carries `turn`, `phase`, `active` from `_last_snapshot`; event-sourced barks carry the ring `seq`.
- The runner appends each consumed ring event to `logs/events.jsonl` and each **changed** snapshot, compacted (turn, phase, active, stack, event seq, per seat: life, hand, pool, battlefield names) to `logs/observer-tape.jsonl`; `arena-stop.sh` archives both (estimate 2–6 MB per game before gzip).
- `voice_runner.py --replay <archive>` drives the runner from the tape with a fake clock and a dry player, prints what it would have said with why, and ends with the hygiene summary. Every future complaint becomes an offline test; the first tape is game 49's.

### 4.4 Brain intent and the `say` key (recommendation 4)

- **Intent read from `game.jsonl`** (the runner already tails it for MULLIGAN): a `source: "cycle"` record or an answer carrying `repeat_cycle`/`until` → the owner's `looping` line at once and the table's `loop` reactions; `why` text scanned for a small vocabulary (loop, infinite, lethal, storm, combo) as a weaker trigger for `someone-wins`/`kill-that` targeting. This also fixes A4.
- **`say` key:** `seat-brief.md` offers one compact menu line of ~20 ids (taunt, respect, nice-play, kill-that, youre-the-threat, im-not-the-threat, deal, no-deal, looping, big-swing, that-hurt, gg …) with the rule "at most one, only when it fits, never on a procedural window". The seat runner validates against the menu and records it; the voice runner speaks it as an anchored line (source `brain`) under the seat's guard. Budget: ≤ 150 prompt tokens per call; measured per game — if under 1 % of lines use it after three games, it goes.

### 4.5 The under channel and the atoms (Ben: "one of the best suggestions")

- **Player:** `play_under(path, volume=0.5)` starts a second `afplay -v 0.5` without waiting; one under-line at a time; killed on mute and at the game-over lock like the main channel.
- **Library:** `voices/<lib>/atoms/manifest.json`, ~24 ids per voice rendered with eleven_v3 audio tags — sigh, hmm, chuckle, short laugh, gasp, cough, throat-clear, tsk, exhale, groan, oof, ooh, hah, mm-hm, yeah, no way, nice, wow, ugh, hmph, whistle, come on, oh no, right — each trimmed to ≤ 1.2 s and baked at the library gain minus 3 dB; plus three table sounds (card riffle, shuffle, dice) from the sound-effects endpoint or the existing SFX path. **Probe first** (three atoms × three voices, Ben listens), then the full set: ~75 renders, under 1,000 characters.
- **Three triggers:** (1) a backchannel under a main line — when seat A's opener or event line plays, a listener (the target first, else a bystander) may put an atom 0.4–0.8 s in at p ≈ 0.35, chosen by class (a hit → gasp/oof from the target; a jab → hah/tsk from a bystander; a proposal → hmm/mm-hm); (2) presence at the floor — when the pool is empty or filler-only, an atom on the main channel from a living seat (sigh, hmm, riffle) instead of a content line, re-arming the clock at 60 % of the floor so content still comes; (3) instant reactions — a gasp at a big swing, a kill or a sweep from a seat that is not speaking, on the under channel, no queue.
- **Rules:** never during Joshua's advice, never after the lock, never from an eliminated seat, at most one atom per seat per 6 s, never two at once, not counted toward duty. Records: `kind: atom`, `channel: main|under`. Tests with fake players on both channels.

### 4.6 Kill the raws

- **Tree:** `git rm -r` every `voices/**/raw/` (2,495 files, 351 MB) in one commit; add `runner/voice/stock/voices/**/raw/` to `.gitignore` so future `--render` output stays local; persist each library's computed `gain_db` in its manifest at bake time so new takes bake to the same level without the old raws (`library_gain` is computed from all raws today); tests stop asserting raw files (`test_bark_libraries.py:87,110`, `test_table_lines.py:128`, `test_card_lines.py:88`) and pin the manifests instead.
- **History (recommended, ask):** the branch has never left this machine, so its history can be rewritten before the merge: `pip install git-filter-repo`, then drop `*/raw/*` from every commit on the branch (backup first as a `git bundle` in the release bucket, ~350 MB), then `git gc --prune=now`. Without this, the merge carries 351 MB of dead blobs into `arena`'s history for good.

---

## 5. Proposed, awaiting Ben

1. **Governor as a mean, not a ceiling** — **approved (Ben: rowdy should rowdy).** Full chance below the goal (dial boost kept), taper to the floor over [goal, 1.5 × goal]. Phase 1, scheduler.
2. **Threat memory** (Prototyper #7): a decaying `_threat` pin set by combo-online, game-changer casts and cast flurries, biasing `hit-`/`threat-` targets ahead of the life leader.
3. **"Waiting on Player One" family** — **approved (Ben: heckles are great)**, keyed to the human's priority window being open > 30 s; the advisor never answers a heckle (A14). Phase 1, daemon.
4. **Kill-shot family** (Grower): multi-kill lines for a Reservoir-style ending, instead of one generic Joshua line for three deaths.
5. **Second wordings for the single-text patter ids** (Grower #5): rank ids by spoken ÷ takes across the archive; render where the ratio is worst (`pass-already`, `board-envy`, `empty-hand`, `what-turn`, `play-slower`, the named `deal-`/`hit-`/`threat-` lines); a named take falls back to its generic when heard in the last five minutes.
6. **Deals** — seats may deal among themselves (kept as built). The human's own deals go player → advisor chat → seat brain and back through the seat's voice: the ask channel (`logs/control/ask/`, `VAdvisor` → `advisor_runner._answer_ask`) already carries the human's text to the advisor; a relay would route an ask addressed to a seat into that seat's next request as a note and let the brain answer with a `say`. **Feature push, not this round.**
7. ~~Drop the advisor bark tags / remove the colour lines~~ — **both kept (Ben).**
8. ~~Audio format~~ — **WAV stays (portability).**
9. **`getRegisteredPlayers()` in the observer** (E1): 4.2 or 4.3?
10. **BL-49** (Executive toggle during an open window): still designed, not built; it touches the human's input, so it stays out until Ben says go.
11. ~~"Player One" in the no-advisor launch~~ — **stays (Ben: the player is the seat in a human game).**

---

## 6. Sequencing

- **Phase 0 — foundation, serial (one pair of hands):** the module split (§2), the checkpoint and restart clock (4.1), record stamps and tapes (4.3), the shared `classify()` (C2). Everything later touches these; doing them first turns the rest into file-local work. Suite green, one commit each.
- **Phase 1 — parallel by module, worktree-isolated:**
  - *scheduler:* one clock, two classes, `HUMAN_TURN_MULT` + Executive rule, guard rule (A5), proposal terminal items (A3), `big-mana` constant (A7), `_board_fp` seq (A8), knob retirement into `tuning.json`, governor change if approved.
  - *renderer + atoms:* `play_under`, the atoms library and probe, triggers, records, tests; raw purge (tree), `gain_db` in manifests, `.gitattributes`, cache cap, packager preflight.
  - *daemon + intent:* `_tail` helper (A9), brain intent + `say` key (4.4) in seatd + voice, muted teardown (B1), seq gap record (B2), stat-before-parse, `enabled()` cache, one inbox scan.
  - *edges:* seatd dead branch and `_loop_state` (D4), W-18 rotation (B3), `env -u` (B4), `voice_alive` (B5), hygiene (C2, C3, targets and gap distribution, distinct ids), docs (D1, D2), dead code (D3), tests pinned to manifests.
- **Phase 2 — verify:** suite; the game-47 loop fixture; replay of game 48's seat-1 tape for B6; an adversarial review pass over the diff; **game 49 at rowdy with tapes on**, Ben hot-swaps the runner once on purpose and judges the floor by ear; hygiene reads duty against the goal per turn owner, gap distribution, questions answered, proposals answered, atoms per minute.
- **Phase 3 — Java and merge prep:** observer E1/E2 with the reader audit and `ObserverSnapshotWriteTest`, seat-name helper (D5), FULL gate; history purge of the raws, `git gc`, re-measured package numbers (C4); then merge to `arena` and cut 4.2 only on Ben's explicit go.

---

## 7. Who does the work — the Cherny-agents question

Ben proposes archetype subagents doing the work in their domains. Assessment:

- **Correctness.** The archetypes partition *judgement* well; they do not partition *files*. All five reports point into `voice_runner.py`, and the floor, governor, guard and eviction interact — five agents editing one 2,600-line file in parallel would merge badly and reason about each other's half-applied semantics. After the Phase 0 split, the natural partition is by module (scheduler, renderer + atoms, daemon + intent, edges), which is what §6 Phase 1 uses. Each agent runs the suite in its own worktree; I integrate; a separate adversarial reviewer reads the combined diff before anything is committed. That is the review-then-verify shape that produced today's findings, applied to the fixes.
- **Efficiency.** Parallel implementers cut wall-clock by three to four times on Phase 1; token cost is the price (the review cost 1.03 M tokens for reading alone; implementing is heavier). Phase 0 cannot be parallelised and is the critical path. Atoms rendering is serial on ElevenLabs anyway.
- **Elegance.** The lens metaphor is elegant for analysis because every lens sees the whole; for implementation the module boundary is the elegant unit because the tests and the commits fall out of it. Keep the archetypes as the *brief* each implementer carries (the Sweeper brief for the scheduler agent, the Builder brief for the renderer agent, the Maintainer brief for the daemon agent, the Grower brief for the edges and hygiene agent), not as the unit of assignment.
- **Decided (Ben): no agent split.** One pair of hands does all of it, serially, in the module order of §6 Phase 1 (scheduler, renderer + atoms, daemon + intent, edges), one commit per item with the suite green. The adversarial pass at Phase 2 is a second read of the whole diff before game 49, not an agent.

---

## 8. Test plan (per phase)

- Phase 0: restart scenarios (4.1); record stamps present on every record kind; tape written on change only; `--replay` reproduces a synthetic scenario's spoken list exactly; the split leaves the suite at 453 OK with only import-path edits.
- Phase 1: terminal proposal items plan no hop; guard rule cases (optional→anchored passes, anchored→anchored holds); Executive-on turn is an AI turn for the budget; same-card-cast ≥ 4 fires `looping`; `_tail` on a half-written line and on an inode change; muted game over publishes `final.json`; atoms: backchannel under a main line, floor spends an atom on an empty pool, never two at once, eliminated seats silent, lock kills the under channel; `say` validated against the menu and spoken once; knob retirement: `tuning.json` loads, env knobs gone from `arena-config.py` output; hygiene: one classifier, restarts counted from both logs.
- Phase 2: game 49 with tapes; the replay of game 49's own tape reproduces its spoken list; adversarial reviewer's findings closed or logged.
- Phase 3: `ObserverSnapshotWriteTest` lost-player case; FULL gate exit 0 checked, not the tail.

---

## 9. Open questions for Ben (in the order the plan needs them)

1–5, 7, 8: answered (see the decisions block at the top).
6. Observer `getRegisteredPlayers()` in 4.2 (Phase 3 here) or 4.3? Context given in chat on 2026-09-14; Ben to decide.
9. Go for Phase 0.
