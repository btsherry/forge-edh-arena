# Experimental-release features — the build plan for the items Ben took from the stack rank

**Date:** 2026-09-16. **Status:** PLAN, awaiting Ben's final go. **Source:** `2026-09-16-feature-stack-rank.md`
(Ben: yes to 1, 2, 3, 4, 6, 7 and the three small tunes 10–12; item 5 as a data task with four transcript
sources). **Branch:** `experimental/voicework2`, tree clean at `4f0dca99332`. **Method (Ben, 2026-09-16 —
[[token-discipline]]):** all code by hand in the main session, no subagents, no critic; one suite run per
item gated on the exit status; one commit per item; nothing in Java, so no Maven gate.

## Order and estimates

| Step | Item | Files | New tests | Renders |
|---|---|---|---|---|
| 1 | Deals polish: offer delivery at the seat's next window; panel "no window yet"; `deal-over` certain for the player's deals | seatd/runner.py, advisor_runner.py, voice/scheduler.py | 4 | 0 |
| 2 | Procedural narration ungoverned | voice/scheduler.py | 2 | 0 |
| 3 | Grudges every second hit (tune 12) | voice/events.py | pin edit | 0 |
| 4 | Runner `up` + effective-config + game-summary records (tune 11) | voice_runner.py, scripts/arena-hygiene.py | 3 | 0 |
| 5 | Grounding score in hygiene (tune 10) | scripts/arena-hygiene.py | 2 | 0 |
| 6 | Second wordings + named → generic fallback | manifests (harry/bill/lily base + table), voice/scheduler.py | 3 | ~99 |
| 7 | Kill-shot family | table_lines.py, voice/events.py, chains.json | 3 | 36 |
| 8 | Threat memory | voice/scheduler.py, voice/events.py, voice_runner.py (checkpoint) | 6 | 0 |
| 9 | Transcript corpus + priors (item 5) | new `docs/research/pod-timing-priors.md`, a script under `scripts/research/` | — | — |

Steps 1–5 are one sitting. Step 6 is a render session (ElevenLabs, ~2,500 characters). Step 7 a short
sitting. Step 8 a sitting of its own, with a replay of games 48–50's tapes as its acceptance test.
Step 9 is Ben's recording plus one analysis pass; it can run in parallel with anything.

---

## Step 1 — Deals polish

**1a. Offer delivery at the seat's next window.** Today `_ingest_notes(req)` (seatd/runner.py:437) runs at
:1891 in `_handle_inner`, AFTER the fastpaths have had their chance on the request; a REACT window the
memo or the affordability fastpath answers never reaches the model, so a pending `deal-offer` note waits
for a window the model gets — in game 50 Purphoros's own turn, four minutes later. Change: a pending
`deal-offer` or `deal-counter` note is, like a deal in force (`_deal_guard` :498), a reason the window
goes to the model — move the "notes pending?" check ahead of the fastpaths and treat it as `_deal_guard`
does (the hand-off note "an offer is waiting for your answer"). Cycle replay: a pending offer is novelty,
the cycle pauses for one model window (the same path `_deal_conflict` :512 uses). Cost: one model call
per offer, at low effort when the window is otherwise resourceless (the existing REACT_LOW_EFFORT rule).
Test: an offer note + a memo-able REACT window → the model is asked and the prompt carries DEAL PENDING.

**1b. Panel: "hasn't had a window yet".** advisor_runner.py `_deal_tick`: an offer `open` for more than
30 s with no DEAL record → one panel line `[t14 · table] Purphoros hasn't had a decision yet — the answer
comes at his next window`, once per offer. Test: clock-advanced tick prints it once.

**1c. `deal-over` certain for the player's deals.** voice/scheduler.py `lapse_deals` (:866): `p=1.0` when
the human is a party, `DEAL_OVER_P` otherwise (Ben, game 50: a deal's lifecycle is state). Test: lapse with
the human → queued regardless of the dice; seat-to-seat → still rolled.

## Step 2 — Procedural narration ungoverned

voice/scheduler.py `maybe_bark` :635: `ungoverned = pid in MULL_LINE.values() or (source == "patter" and
p == 1.0)` gains `or source == "procedural"`. The seat guard, the once-a-turn rule and the dice on
`table_p(pid)` still apply, so a seat narrates its own turn at most once per id per turn. Game 48 evidence:
30 procedural lines died to "dice (procedural, p=…, governor …)". Test: over budget, a `land-go` still
queues; a patter line does not.

## Step 3 — Grudges every second hit (tune 12)

`GRUDGE_EVERY` 3 → 2 in voice/events.py:66; the third-counter and second-wipe rules stay. Update the
test message that names "the third hit".

## Step 4 — Runner records (tune 11)

voice_runner.py `run()`: an `up` record `{event: "up", restart: N (from voice-0.jsonl's earlier `up`
records in this game), chatter, tuning_sha, libraries}` and, at the final marker, a `summary` record
`{lines_by_source, duty_mean, evictions, gaps, atoms, restarts, ring_seen}` computed from the runner's own
counters (add a small counter dict fed by `record()`). arena-hygiene.py reads `up` for the restart count
(replacing the .out parse as the primary; keep the parse as fallback) and prints the summary line if
present. Tests: the records exist and agree with hygiene's own count.

## Step 5 — Grounding score (tune 10)

arena-hygiene.py: from the archive's `deals.jsonl`/`game.jsonl`/`voice-0.jsonl`: the eventual winner (the
`.rated` file or the last `win` record) and the busiest seat per turn (casts in `events.jsonl`); the
grounding score = share of addressed seat lines (`hit-*`, `threat-*`, `kill-that`, `youre-the-threat`,
`someone-wins`, `deal-*` targets) whose target is the eventual winner or that turn's busiest seat. One
line: `  grounding: 41% of 22 addressed lines named the winner or the turn's busiest seat`. Test on a
synthetic archive.

## Step 6 — Second wordings and the named → generic fallback

Data (twelve archives, plays ÷ takes): `pass-already` 35/1, `what-turn` 27/1, `board-envy` 27/1,
`promise` 14/1, `empty-hand` 11/1; then `cards-in-hand` 49/3, `this-is-fine` 37/3, `good-hand` 37/3,
`shut-it` 34/3, `deal` 30/3, `laugh` 69/6, `my-turn` 41/4, `nothing-happening` 40/4.
- Render: the eight single-take base ids that are picked at all (`pass-already`, `what-turn`, `board-envy`,
  `promise`, `empty-hand`, `play-slower`, `thinking-hard`, `oh-no`) get three more wordings each (4 total;
  the wordings are in the manifests' `text` lists — write them in each voice's register with varied eleven_v3
  tags), and the five three-take ids above get two more (5 total): (8×3 + 5×2) × 3 voices = 102 takes,
  ~2,400 characters. The wording sheet goes in this doc's appendix before rendering, for Ben's eye.
- Fallback: `address_swap` (voice/scheduler.py) swaps a generic id for its named wording (`deal` →
  `deal-urza`); when the named take's stem was heard in the last `PATTER_REPEAT_S`, keep the generic
  wording (which has more takes) instead of skipping. Test: two `deal` picks at the same target within
  five minutes → the second is the generic.
- Pins: `test_voice_runner` (66 stock phrases unchanged — these are seat libraries), `test_bark_libraries`
  wording counts, RenderedTable/RenderedCards counts. Every existing take stays; only variants are added.

## Step 7 — Kill-shot family

Trigger: `scan_observer`'s vanish rule (voice/events.py:1111) sees two or more seats vanish in ONE
snapshot, or the gameover snapshot eliminates two or more at once. Lines (table sub-library, 3 ids × 4
wordings × 3 voices = 36 takes): `table-kill` — the killer: "And that's the table."; `all-of-us` — a
dying seat: "All of us? At once?"; Joshua gets no new line (his `player-eliminated`/verdict stand; the
kill-shot is the seats' moment). Ordering: exits first (existing), then `table-kill` from the killer as an
anchored event line, then the game-over trio. Chain row: `table-kill` → bystander `gasp`/`no-way` atom.
Tests: two vanished seats in one snapshot → one `table-kill` from the killer (from `_last_hit_by`) after the
exits; a single death → nothing new.

## Step 8 — Threat memory

- `self._threat: dict[seat → float]` (voice_runner.py init; checkpointed; decays ×0.5 per turn roll in
  `_roll_turn`). Raised in events.py: combo online +3 (`scan_combos`), a game changer cast +2
  (`_gc_cast_seen.add` sites :901/:928), a cast flurry +1 (the `_casts` window), `call_loop` +4, a `say`
  of `looping`/`big-swing` +1, the winner's turn-boundary "big turn" +1; the human's seat included (the
  table may name Player One).
- Used in `patter_candidates` (scheduler.py:891): the `youre-the-threat`/`kill-that`/`whats-your-life`
  targets and `leader_of` prefer `argmax(threat)` when it exceeds `THREAT_MIN` (2.0), else today's life
  leader; the `hit-`/`threat-` address swap follows the same choice. `someone-wins` fires for the seat
  with threat ≥ 6 as well as for lethal power on board.
- Acceptance: `--replay` of games 48, 49, 50 → count addressed lines naming the eventual winner before the
  kill turn (game 48: Urza; 49: Purphoros; 50: Player One). Today's numbers first (the grounding score
  from step 5), then after. Tests: a combo-online raises the pin; two turns later it has decayed by half;
  a `hit-` pick prefers the pinned seat over the life leader; the pin survives a checkpoint round trip.

## Step 9 — Transcript corpus and timing priors (item 5)

**Sources (four, for variety; Ben named two):** Extra Turns (The Command Zone's long-form pod play; the
least edited of their output), Commander at Home, plus two more: **MTGGoldfish Commander Clash** (weekly,
four players, lightly edited, long silences kept, heavy banter) and **Tolarian Community College's Shuffle
Up & Play** (long-form casual pods, varied guests, table talk left in). Both are large back catalogues with
auto-captions. **Ben's own pod** via the audio routing loop (BlackHole → a local recorder → whisper) is the
fifth and best source: unedited, the register we want, and the only one with the players' consent to
transcribe.

**Method:** `yt-dlp --write-auto-sub --skip-download` for the captions (WebVTT, word-timed) of ~3 hours
per channel; captions are analysis input only — never stored in the repo (a `research/corpus/` folder,
gitignored). A script `scripts/research/pod_timing.py` extracts, per video: inter-utterance gaps by active
player when identifiable (turn markers in captions are unreliable — fall back to gaps overall and gaps
inside long stretches), question → answer latency (a caption ending in "?" followed by a different
speaker), proposal outcomes (keyword set: "hit", "kill", "deal", "peace", "alliance" → next-utterance
class), backchannel rate (single-word utterances: yeah, hmm, oof, nice), words per utterance, utterances
per minute, overlap rate (caption time overlap). Output: `docs/research/pod-timing-priors.md` with the
distributions per source and a "priors" table mapping each to a tuning key (`min_gap_s`, `patter_gap_s`,
the floor, `chain_p`, `PROPOSAL_P`, `BACKCHANNEL_P`, `hop_p`). No tuning changes in this step; Ben
decides which priors to adopt after reading the table.

**Cost:** network for the captions (Ben's go), ~3 GB of VTT text, one afternoon of scripting and reading.
No agents.

---

## Appendix A — wording sheet for step 6 (for Ben before rendering)

To be filled in this doc at the start of step 6: eight single-take ids × 3 new wordings × 3 voices, five
three-take ids × 2 new wordings × 3 voices, each with its eleven_v3 tag, in the voice's register
(Harry fiery and cocky; Bill dry and elder; Lily warm and wry).

## Appendix B — acceptance

- Suite green (exit 0) after every step; count pins updated with the renders.
- Game 51 at rowdy with tapes: an offer answered at the seat's next window (not its turn); "our truce is
  done" heard; procedural lines audibly more frequent; no repeated take twice in a row on the same id;
  hygiene prints the grounding score and the runner's summary.
- Threat memory judged on the replays of games 48–50 before game 51.
