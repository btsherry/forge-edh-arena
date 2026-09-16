# Pod timing priors — what four real Commander pods sound like, in numbers

**Date:** 2026-09-16. **Status:** measurement only — **no tuning changed, and
nothing here is a recommendation.** Ben reads the priors table and decides.
**Plan:** `docs/reviews/2026-09-16-release-features-plan.md` step 9 (item 5).
**Branch:** `experimental/voicework2`.

The voice runner paces the table's talk on constants that were guessed: how
long a seat waits before the next line (`min_gap_s`), how long the table may
sit silent before the patter clock pokes it (`patter_gap_s`, `SILENCE_FLOOR_S`),
how often a line is answered (`chain_p`, `chain_decay`), how often a proposal
draws a response (`PROPOSAL_P`), how often a line draws a murmur
(`BACKCHANNEL_P`). This doc measures the same quantities on 13.5 hours of real
four-player casual Commander and puts the runner's own games 49 and 50 beside
them.

**Reproduce:**

```
forge-arena/scripts/research/pod_timing.py forge-arena/research/corpus
forge-arena/scripts/research/pod_timing.py --runner-log \
  forge-arena/runner/logs/archive/20260916-111916-stop/voice-0.jsonl \
  forge-arena/runner/logs/archive/20260916-132428-stop/voice-0.jsonl
```

Stdlib only; the script parses WebVTT itself (no `webvtt` module in this
environment).

---

## 1. The corpus

Captions only — **no audio and no video was downloaded**, and the captions
themselves are **never committed**: they live under
`forge-arena/research/corpus/`, which is gitignored (`.gitignore:123`, verified
with `git check-ignore`). Total on disk: 7.9 MB of VTT. Nothing from the
transcripts is quoted in this doc beyond one five-word fragment used to show
the caption shape.

| Source | Video id | Title (shortened) | Duration | Captions |
|---|---|---|---|---|
| Extra Turns (The Command Zone) | `rpmtX_DoPGQ` | Game Knights' Biggest Losers — Extra Turns 70 | 55:11 | auto, word-timed |
| Extra Turns | `lwYB9MNHjFg` | Mono Mono-Black Battle — Extra Turns 64 | 68:07 | auto, word-timed |
| Extra Turns | `6of5iD_QppM` | Magic Card Designer vs His Own Creations — Extra Turns 63 | 73:58 | auto, word-timed |
| Commander at Home | `2Bxe8QjsFrU` | Leonard Williams goes big with Kona — Ep 107 | 60:21 | auto, word-timed |
| Commander at Home | `GaQevLUrMrQ` | Alex Ward makes deals with demons — Ep 106 | 56:28 | auto, word-timed |
| Commander at Home | `bHPdRzz0F0s` | Amber Glenn stole my job — Ep 103 | 94:24 | auto, word-timed |
| Commander Clash (MTGGoldfish) | `NSbFq6kvFdc` | Mono-Red Lifegain vs Storm vs Bob vs Fliers | 48:15 | auto, word-timed |
| Commander Clash | `gjwqQF0ZvBk` | 1993 vs 2003 vs 2016 vs 2026 | 72:53 | auto, word-timed |
| Commander Clash | `Qte0MW2umq8` | $30 Unsleeved Commander | 57:04 | auto, word-timed |
| Shuffle Up & Play (Tolarian) | `2UOeO2IJRFM` | Matt Mercer Rolls Up Sephiroth Commander — SU&P 109 | 81:35 | auto, word-timed |
| Shuffle Up & Play | `MRPqL8vlYa4` | Loading Ready Run vs Good Games Morley — SU&P 108 | 85:11 | auto, word-timed |
| Shuffle Up & Play | `mOAPEYoFZWU` | We Made Mark Rosewater Play With Our Decks — SU&P 96 | 63:07 | auto, word-timed |

| Source | Videos | Video hours | Measured hours | Utterances | Caption type |
|---|---|---|---|---|---|
| Extra Turns | 3 | 3.29 | 3.28 | 2,627 | auto (`en`), word-timed |
| Commander at Home | 3 | 3.52 | 3.48 | 3,585 | auto (`en`), word-timed |
| Commander Clash | 3 | 2.97 | 2.97 | 2,286 | auto (`en`), word-timed |
| Shuffle Up & Play | 3 | 3.83 | 3.83 | 3,404 | auto (`en`), word-timed |
| **Total** | **12** | **13.61** | **13.55** | **11,902** | |

**Substitutions and choices.**

- **No channel blocked us and no source needed replacing.** All four named
  sources delivered; no fallback (Spike Feeders, I Hate Your Deck) was needed.
- **Extra Turns is not its own channel.** `@ExtraTurns` 404s; the series lives
  on The Command Zone's channel (`UCLsiaNUb42gRAP7ewbJ0ecQ`). Episodes were
  picked by title from a search of that channel, newest first (70, 64, 63).
- **Commander Clash is not on `@MTGGoldfish`.** The gameplay series moved to
  the sister channel `@MTGGoldfishCommander`; the main channel's recent uploads
  are Against the Odds and Standard content. Gameplay episodes only were taken
  — not the "Commander Clash Podcast" talk shows, which are four people at
  microphones with no game, and not the ~15-minute "Clash Post-Game" clips.
- **Shuffle Up & Play:** episode 107 (`iYFXrEiw7TY`, 86:52) was downloaded and
  then **dropped and replaced** by episode 96 (`mOAPEYoFZWU`, 63:07) because
  109 + 108 + 107 came to 4.23 h, over the 4-hour-per-source cap; 109 + 108 + 96
  is 3.83 h.
- **Commander at Home:** the MagicCon Vegas live show (`-Hi8Tlq_Dvc`) was
  skipped — a stage show with an audience is not the register we are measuring.
- Every one of the twelve has **auto captions only** (`en` and `en-orig`, which
  are byte-identical; the duplicate was deleted). **No video in the corpus has
  a manual caption track**, so the whole corpus is auto-caption quality.

---

## 2. Method

**Parsing.** YouTube auto-captions roll: each cue repeats the previous line and
adds one new line carrying per-word timings, e.g. a cue whose new text begins
`I will put this in` arrives as `I` at the cue start and `will`, `put`, `this`,
`in` each with their own `<hh:mm:ss.mmm>` stamp. The script takes the timed
line only, dedupes on (time, word), strips `<c>` tags and HTML entities, and
builds one word stream per video. `[music]` / `[applause]` / `[laughter]` cues
are recorded as non-speech spans and the gaps they cover are excluded.

**Utterance.** A word's spoken end is estimated as
`start + clamp(0.085·len + 0.10, 0.12, 0.60) s`, capped at the next word's
start. A silence of **≥ 0.6 s**, or a `>>` speaker-change mark, ends the
utterance. 84% of utterance boundaries in this corpus carry a `>>`, so an
utterance is very close to a speaker turn.

**Definitions used below.**

- **gap** — silence between the end of one utterance and the start of the next.
- **onset** — start-to-start interval; how often a new line begins.
- **question → answer latency** — an utterance ending in `?`, then the gap to
  the next utterance.
- **proposal** — an utterance containing hit / attack / kill / swing at / deal /
  peace / truce / alliance / team up **and** a target (a pronoun or a
  name-shaped capitalised token). Outcome classified inside 8 s: *reply*,
  *silence* (next utterance later than 8 s), *nothing* (end of transcript).
- **backchannel** — yeah / yep / ok / okay / nice / oof / ooh / hmm / wow / no /
  yes / sure / right / damn / ouch / whoa / what / oh. Two rates are reported:
  a whole utterance that is nothing but one or two of these (a *floor*, because
  the aligner usually glues a bare "Yeah." onto the same speaker's next
  sentence), and the turns that *open* with one, which is the shape
  `BACKCHANNEL_P` actually models.
- **chain** — a run of turns where each next turn is a different voice inside
  2 s. `hop1` is the odds a line gets answered at all, `hop2` the odds the
  answer gets answered, and so on.

---

## 3. Per-source and pooled

| Source | gap med | p75 | p90 | p99 | max | onset med | % time in gaps > 4 s | > 15 s /min | > 30 s /min | utt/min | words/utt | Q→A med | Q→Q | prop reply ≤ 8 s | ≤ 2 s | bc-open/min | hop1 | hop2 | chain len |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Commander at Home | 0.37 | 0.92 | 1.72 | 5.88 | 46.9 | 2.48 | 5.4 | 0.014 | 0.014 | 17.16 | 6 | 0.12 | 0.08 | 1.00 | 0.94 | 2.82 | 0.72 | 0.80 | 4.86 |
| Commander Clash | 0.28 | 0.75 | 1.24 | 3.80 | 7.6 | 3.12 | 1.1 | 0.000 | 0.000 | 12.84 | 8 | 0.04 | 0.05 | 1.00 | 0.96 | 2.57 | 0.74 | 0.78 | 5.07 |
| Extra Turns | 0.37 | 0.92 | 1.50 | 4.90 | 14.7 | 2.88 | 1.9 | 0.000 | 0.000 | 13.36 | 8 | 0.03 | 0.06 | 1.00 | 0.97 | 2.62 | 0.68 | 0.80 | 4.92 |
| Shuffle Up & Play | 0.28 | 0.77 | 1.40 | 4.76 | 29.8 | 2.56 | 2.5 | 0.013 | 0.000 | 14.83 | 7 | 0.12 | 0.09 | 1.00 | 0.97 | 2.87 | 0.73 | 0.83 | 5.84 |
| **Pooled (12 videos)** | **0.36** | **0.84** | **1.48** | **5.16** | **46.9** | **2.72** | **2.8** | **0.007** | **0.004** | **14.64** | **7** | **0.11** | **0.07** | **1.00** | **0.96** | **2.73** | **0.72** | **0.80** | **5.16** |

Seconds unless noted. `Q→Q` = share of answers that are themselves questions.
`bc-open/min` = turns per minute that open with a murmur. `chain len` = mean
turns in a back-and-forth run.

Per video, for the spread:

| Video | gap med | p90 | max | onset med | utt/min | Q→A med | prop reply ≤ 2 s | bc-open/min | hop1 | chain len |
|---|---|---|---|---|---|---|---|---|---|---|
| commander-at-home/2Bxe8QjsFrU | 0.20 | 1.40 | 41.4 | 2.40 | 17.15 | 0.12 | 1.00 | 2.57 | 0.76 | 5.81 |
| commander-at-home/GaQevLUrMrQ | 0.36 | 1.80 | 46.9 | 2.48 | 16.88 | 0.24 | 0.92 | 2.91 | 0.70 | 4.33 |
| commander-at-home/bHPdRzz0F0s | 0.29 | 1.49 | 45.3 | 2.56 | 17.33 | 0.12 | 0.93 | 2.94 | 0.71 | 4.70 |
| commander-clash/NSbFq6kvFdc | 0.20 | 1.00 | 6.2 | 3.12 | 11.81 | 0.08 | 1.00 | 2.47 | 0.69 | 4.91 |
| commander-clash/Qte0MW2umq8 | 0.28 | 1.16 | 6.0 | 3.16 | 13.28 | 0.04 | 0.97 | 2.51 | 0.75 | 4.45 |
| commander-clash/gjwqQF0ZvBk | 0.20 | 1.15 | 6.4 | 3.04 | 13.18 | 0.08 | 0.94 | 2.69 | 0.78 | 5.82 |
| extra-turns/6of5iD_QppM | 0.28 | 1.24 | 10.8 | 2.80 | 13.75 | 0.00 | 1.00 | 2.71 | 0.70 | 6.07 |
| extra-turns/lwYB9MNHjFg | 0.44 | 1.64 | 9.3 | 2.96 | 13.29 | 0.00 | 1.00 | 2.88 | 0.68 | 4.26 |
| extra-turns/rpmtX_DoPGQ | 0.43 | 1.49 | 10.4 | 3.04 | 12.93 | 0.19 | 0.88 | 2.19 | 0.65 | 4.57 |
| shuffle-up-and-play/2UOeO2IJRFM | 0.20 | 1.32 | 29.8 | 2.48 | 16.25 | 0.12 | 0.91 | 3.11 | 0.71 | 5.19 |
| shuffle-up-and-play/MRPqL8vlYa4 | 0.20 | 1.09 | 27.2 | 2.48 | 16.07 | 0.12 | 0.97 | 3.32 | 0.75 | 6.70 |
| shuffle-up-and-play/mOAPEYoFZWU | 0.12 | 1.00 | 24.8 | 2.96 | 11.32 | 0.04 | 1.00 | 1.97 | 0.77 | 5.76 |

The three headline shapes, stated plainly:

1. **A pod is almost never silent.** 84.4% of the clock is somebody talking.
   The median gap between turns is a third of a second; the p99 is 5.2 s. A
   silence longer than 15 s happened **six times in 13.5 hours** (0.007/min),
   and longer than 30 s **three times** — and all three of those sit in
   Commander at Home, whose intro and deck-tech cutaways leave a hole in the
   caption track (three more, 24–30 s, are Shuffle Up & Play's).
2. **Everything gets answered, fast.** 100% of the 450 detected proposals drew
   a reply inside 8 s, 96% inside 2 s. 95% of questions were answered inside
   2 s; only 7.5% of answers were themselves questions.
3. **Talk accelerates rather than decaying.** Once a back-and-forth starts, the
   odds the *next* hop happens go **up**: hop1 0.72, hop2 0.80, hop3 0.83,
   hop4 0.81. Mean run 5.2 turns, median 3, longest 47.

---

## 4. The table's own numbers — games 49 and 50

Same statistics, run over the runner's `spoke` records, `kind: "bark"`, seat
not null — the seats' lines. `kind: "atom"` (the murmur layer) is excluded from
the gap series and reported separately; Joshua's advice/quip/colour lines and
the startup/game-over markers are excluded entirely.

| | Game 49 (`20260916-111916-stop`) | Game 50 (`20260916-132428-stop`) | Pooled pods |
|---|---|---|---|
| seat lines | 65 | 133 | 11,902 utterances |
| span | 14.9 min | 19.7 min | 13.55 h |
| lines per minute | **4.37** | **6.73** | **14.64** |
| gap median | **5.18 s** | **4.87 s** | **0.36 s** |
| gap p75 | 7.02 s | 6.60 s | 0.84 s |
| gap p90 | 15.86 s | 13.82 s | 1.48 s |
| gap p99 | 130.12 s | 38.57 s | 5.16 s |
| gap max | 291.59 s | 47.68 s | 46.92 s |
| share of clock spent talking | 18.2% | 27.5% | 84.4% |
| share of clock inside gaps > 4 s | 73.2% | 61.4% | 2.8% |
| gaps > 15 s per minute | 0.605 | 0.506 | 0.007 |
| gaps > 30 s per minute | 0.134 | 0.253 | 0.004 |
| median line length | 2.32 s | 2.32 s | 2.04 s |
| chain hop1 | 0.372 | 0.391 | 0.718 |
| chain hop2 | 0.312 | 0.324 | 0.801 |
| chain hop3 | 0.200 | 0.091 | 0.825 |
| mean chain length | 1.51 | 1.53 | 5.16 |
| gap inside a chain (median) | 1.03 s | 0.98 s | 0.19 s |
| atoms per minute | 1.75 | 2.18 | — |
| atoms per seat line | 0.40 | 0.32 | — |

Game 50's line count (133), pace (6.7/min), median gap (4.87 s) reproduce the
figures already in `BUG-LOG.md` for that game, so the runner-log path of the
script agrees with what was recorded by hand on the day. (The max gap differs:
this script measures the whole seat-line series including the pre-turn-1
window; the BUG-LOG figure was taken after it.)

The single biggest difference is not any one probability: **the arena's table
talks about a fifth of the time and a real pod talks about five sixths of the
time**, and the arena's silences are two orders of magnitude more common at
every long threshold.

---

## 5. Priors table

Today's value, the measured prior, and one line of what the measurement is.
**Nothing here is a recommendation.**

| Key | Where | Today | Measured prior | Note |
|---|---|---|---|---|
| `min_gap_s` | `tuning.json` | `8` | pod onset-to-onset median **2.72 s**, p90 8.48 s; pod gap median 0.36 s | The floor between two lines. The pod's *whole* start-to-start rhythm sits below today's floor; today's 8 s is roughly the pod's onset **p90**. Divided by `ARENA_CHATTER` at start-up (floor 3 s), so rowdy already moves it. |
| `patter_gap_s` | `tuning.json` | `[5, 7]` | pod gaps > 4 s occur **0.25/min** and hold 2.8% of the clock; gap p99 **5.16 s** | The patter clock's trigger window. A 5–7 s hole is a once-per-several-minutes event in a real pod — the window is set at about the pod's 99th percentile of silence. |
| `SILENCE_FLOOR_S["ai"]` | `scheduler.py:75` | `12.0` | pod gaps > 15 s: **0.007/min** (6 in 13.5 h); max gap 46.9 s | "Never let it go quieter than this." A pod goes 12 s silent a handful of times an hour, and mostly at production seams (intro, deck tech). Arena game 49: 0.605/min. |
| `SILENCE_FLOOR_S["human"]` | `scheduler.py:75` | `24.0` | pod gaps > 30 s: **0.004/min** (3 in 13.5 h) | Same measure at the human floor's scale. Not separable from the AI case in the corpus: the captions do not say whose turn it is. |
| `chain_p` (`first_hop_p`) | `tuning.json`, `chains.py:43` | `0.6` | pod **hop1 = 0.718** (0.68–0.74 per source); arena hop1 0.37 / 0.39 | Odds the line gets answered by another voice inside 2 s. |
| `chain_decay` | `tuning.json`, `chains.py:72` | `0.5` | pod **hop2/hop1 = 1.12** (hop2 0.80, hop3 0.83, hop4 0.81) | Real pods do not decay — once two people are going, the third hop is *more* likely than the first. Arena measured decay 0.83–0.84 (the dice say 0.5; the observed ratio is higher because only lines that survived the governor are in the log). |
| `chain_max_hops` | `tuning.json` | `3` | pod mean run **5.16** turns, median 3, max 47 | Turns in one back-and-forth. Today's cap equals the pod's *median*, not its mean. |
| `chain_gap_s` | `tuning.json` | `0.25` | pod gap inside a chain: median **0.19 s**, p90 1.09 s; arena 1.03 / 0.98 s | The pause between chained lines. The one constant already sitting inside the pod distribution. |
| `PROPOSAL_P` | `scheduler.py:82` | `0.85` | pod proposal reply rate **1.00** within 8 s (0.96 within 2 s), n = 450 | Odds a "let's hit him / truce?" line draws any reply. Silence after a proposal did not occur once in this corpus. |
| `PROPOSAL_TARGET_P` | `scheduler.py:82` | `0.5` | **not measurable** | Whether the reply addresses the proposer by name needs speaker identity, which captions do not carry. |
| `BACKCHANNEL_P` | `atoms.py:40` | `0.35` | **18.7%** of turns open with a murmur (**2.73/min**); bare-murmur floor 0.29/min | Odds a mapped main line draws a murmur. The bare-utterance rate is a hard floor (the aligner glues "Yeah." to the speaker's next sentence), so 0.187 is the usable number and the truth is between it and 0.35. Arena: 0.32–0.40 atoms per seat line. |
| `hop_p` | `chains.py:70` | `chain_p · decay^(hop−1)` | pod hop series **0.72, 0.80, 0.83, 0.81** | The shape, not just the scale: measured hop odds are flat-to-rising, today's are geometric-falling. |
| *(no key)* pace | — | game 49 **4.4**, game 50 **6.7** lines/min | pod **14.6** utterances/min | The aggregate the constants add up to. |
| *(no key)* talk density | — | game 49 **18.2%**, game 50 **27.5%** of the clock | pod **84.4%** | Ditto, in time rather than counts. |
| *(no key)* line length | — | arena median **2.32 s** | pod median **2.04 s**, 7 words | The one place the arena already matches a pod. |

---

## 6. Caveats

1. **Edited, not raw.** All four shows cut. Commander at Home and Shuffle Up &
   Play cut hardest — their long silences (shuffling, thinking, rules lookups)
   are *removed*, which is exactly the thing we are trying to measure. So the
   pod gap distribution is a **lower** bound on real-table silence and the
   utterances-per-minute figure is an **upper** bound. Commander Clash keeps
   more dead air in (its max gap over 3 hours is 7.6 s — it also has the
   tightest edit, so its low max is the *absence* of production cutaways, not
   the presence of silence). Extra Turns is the least edited of the four by
   reputation and sits mid-pack on every measure.
2. **Auto-caption error.** Every track is machine-generated: mis-transcriptions,
   invented punctuation, and (worst for us) **punctuation-driven measures are
   soft**. The question rate rests entirely on the aligner's `?`, and the
   proposal keyword set will pick up "deal" in "big deal" and "what's the deal"
   as well as "let's make a deal".
3. **No speaker labels.** There is no way to tell who is speaking. The `>>`
   mark says the voice *changed*; 84% of utterance boundaries carry one. So
   every "different voice" statistic here (chains, proposal replies) is really
   "a different voice", never "seat 2 answered seat 1".
4. **No active player.** Whose turn it is is not recoverable. The plan
   anticipated this ("turn markers in captions are unreliable"); in practice
   they are absent, not unreliable. Nothing in this doc is broken down by
   active player, and the script reports `active_player: null` rather than
   guessing.
5. **Overlap is a floor, and here the floor is zero.** Measured cue overlap is
   **0.0000 in all twelve videos**: YouTube's aligner serialises the audio into
   non-overlapping cues by construction. Real pods interrupt constantly. Take
   nothing from this number except that captions cannot see it.
6. **The 0.6 s utterance threshold and the word-duration estimate are
   modelling choices.** Both are named constants at the top of the script
   (`UTTERANCE_GAP_S`, `WORD_MIN_S`/`WORD_MAX_S`) and both move the gap median;
   the long-gap counts, the chain series and the reply rates are almost
   insensitive to them.
7. **Sample size for the arena side is two games**, 198 seat lines total, one
   of which (49) was a 10-turn game that ended early and carries a 292 s
   pre-turn-1 hole that BL-54 has since addressed. Games 49 and 50 are not a
   distribution.
8. **Ben's own pod is not in this corpus.** Step 9 named it the fifth and best
   source — unedited, the right register, and the only recording with the
   players' consent. Everything above is the public-YouTube stand-in; the
   comparison worth having is this table re-run on a raw recording, where the
   silences are real and the speakers can be labelled.

## 7. What the data could not answer

- Anything per-seat or per-turn: **who** spoke, **whose turn** it was, whether
  the answer came from the seat that was addressed (`PROPOSAL_TARGET_P`).
- True interruption/overlap rate (§6.5).
- Whether a pod's silence is *comfortable* — the corpus is edited, so the
  question "how long will four people sit quietly before someone speaks" is
  precisely the one it cannot answer (§6.1).
- `your_move_p`, `table_p`, `duty_*`, `barks_*`, `color_p` and the patter
  fractions: these describe which line the runner picks, not conversation
  timing, and have no caption-side counterpart.
