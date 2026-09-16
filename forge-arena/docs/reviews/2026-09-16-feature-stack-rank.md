# Feature stack rank — what else ships in the experimental release

**Date:** 2026-09-16. **Source:** the five-lens review (`docs/research/ai-native-roles-review-2026-09-14.md`)
mined for every feature suggestion, plus the open items from games 49 and 50. **Method (Ben's):** a
synthetic benefit score 1–20 (impact and utility at the table), minus a complexity-and-risk score 1–10,
minus a size-and-effort score 1–10. Net = B − C − S. Ties broken by benefit.

**Already built, not ranked:** the `say` key; presence atoms and the under channel (backchannels and
overlap); the checkpoint and restart memory; the tapes and `--replay`; `tuning.json`; stat-before-parse;
the render cache cap; hygiene's pace/gaps/ids lines; turn/seat stamps on every record; the heckle;
brain-declared loops; table deals. **Declined by Ben, not ranked:** compressed audio (WAV stays for
Windows/Linux); dropping the advisor bark tags; removing the colour address lines.

| # | Feature | B | C | S | Net |
|---|---|---|---|---|---|
| 1 | Offer delivery at the seat's next window, plus "no turn yet" in the panel | 12 | 3 | 2 | **7** |
| 2 | Procedural narration ungoverned, like mulligans | 11 | 3 | 1 | **7** |
| 3 | Threat memory: the table names the real threat, not the life leader | 14 | 4 | 4 | **6** |
| 4 | Second wordings for the single-take lines, and named → generic fallback | 12 | 2 | 4 | **6** |
| 5 | Calibration priors from one recorded real pod session | 15 | 3 | 6 | **6** |
| 6 | A kill-shot family for multi-kill endings | 9 | 2 | 3 | **4** |
| 7 | "Our truce is done" spoken every time; the lapse is state | 6 | 1 | 1 | **4** |
| 8 | A storm-count family ("that's twelve spells") | 8 | 2 | 3 | **3** |
| 9 | Intent keys read from the brains' `why` text (lethal, infinite, "seat N") | 10 | 5 | 3 | **2** |
| 10 | A grounding score per game in hygiene | 6 | 2 | 2 | **2** |
| 11 | Runner `up`, effective-config and game-summary records | 5 | 1 | 2 | **2** |
| 12 | Let the memory layer pay out: grudges every second hit | 4 | 1 | 1 | **2** |
| 13 | Yes / No buttons for a seat's question to the player | 11 | 5 | 5 | **1** |
| 14 | A test suite that runs from a package checkout (no audio files pinned) | 8 | 3 | 5 | **0** |
| 15 | A separate voice pack in the release bucket | 7 | 3 | 4 | **0** |
| 16 | Executive may propose deals, not only accept | 7 | 5 | 3 | **−1** |
| 17 | One line per combo shape instead of an online/react pair | 3 | 2 | 2 | **−1** |
| 18 | Deals v2: kill pacts and conditional deals | 13 | 8 | 7 | **−2** |
| 19 | The observer walks the registered-player list (BL-50 at the source) | 6 | 6 | 4 | **−4** |

---

## 1. Offer delivery at the seat's next window — net 7 (B12 C3 S2)

In game 50 Purphoros answered Ben's offer four minutes after it was typed, because a seat's brain only
speaks when the engine asks it something and his next window was his own turn. Two changes: deliver a
pending note at ANY decision the seat gets, including reaction windows the runner would otherwise
fastpath (the deal hand-off already forces those to the model while a deal is in force — extend it to
"a note is pending"), and print "Purphoros hasn't had a window yet" in the panel after thirty seconds
so the wait is legible.
**Defense:** the deals feature is the release's headline and this is the seam that makes it feel broken;
the code paths exist and the change is a condition and a panel line. Highest net at the lowest cost.

## 2. Procedural narration ungoverned — net 7 (B11 C3 S1)

"Land, go", "pass with mana up", "tapped out", "just a poke", "no blocks", "in response" are the cheapest
lines that are about the game, and in game 48 thirty of them died to the dice or the budget while filler
survived. Treat them like mulligans: always worth the breath, outside the governor, still under the seat
guard and the once-a-turn rule.
**Defense:** the Grower ranked it first for Ben's stated target (more of the talk about the board); it is
one set membership. Risk is a chattier table on a long turn, which the per-turn rule bounds.

## 3. Threat memory — net 6 (B14 C4 S4)

The patter's threat model is the life leader or a six-power creature, so in game 48 the table said "hit
Selvala" three times while Urza assembled a Reservoir kill, and forgot a combo it had announced four
turns earlier. A `_threat` pin per seat, raised by combo-online, game-changer casts, cast flurries and the
brains' own `looping`/`say` intent, decaying a step per turn, biases `hit-`, `threat-`, `kill-that` and
`youre-the-threat` targets ahead of the life leader.
**Defense:** the Prototyper's first finding and the largest remaining grounding gap; the atoms and deals
made the table lifelike, this makes it right. Measurable: "threat lines naming the eventual winner" from
the tapes.

## 4. Second wordings and the named → generic fallback — net 6 (B12 C2 S4)

Thirteen of the sixty-six base ids have one wording, and they are the most-picked patter lines
(`pass-already` played five times in game 48, `board-envy` five, `deal-urza` four). The same take twice is
the surest machine tell. Rank ids by plays ÷ takes across the archives, render a second and third wording
where the ratio is worst (roughly 120 takes), and when a named address line was heard in the last five
minutes fall back to its generic.
**Defense:** cheap renders, no logic risk, and it attacks the repeat problem Ben hears directly. Effort is
mostly ElevenLabs time and the count-pin updates.

## 5. Calibration priors from a recorded pod — net 6 (B15 C3 S6)

Every timing constant at the table (the floor, the proposal reply odds, the hop odds, the gap) is a guess
against Game Knights, which is edited and narrated. One recorded hour of Ben's own pod, or three hours of
unedited VODs (Commander at Home, Extra Turns), through a timestamped transcriber yields the priors: gaps
by active player, who answers whom, question latency, proposal outcomes, backchannel rate, words per
utterance.
**Defense:** the highest benefit on the list, because it replaces guesses in a dozen places at once; the
effort is Ben's time to record and one analysis pass, not code. It ranks with the code items because the
release will be judged by ear.

## 6. A kill-shot family — net 4 (B9 C2 S3)

Game 48 ended with three players falling in eight seconds and one generic Joshua line. A small family for
the multi-kill moment: the killer's "and that's the table", a dying seat's "all of us?", Joshua's "a clean
sweep"; triggered when two or more seats vanish in one snapshot.
**Defense:** an ending is the moment players remember; twelve renders and one trigger that already exists
(the vanish rule sees all three at once).

## 7. "Our truce is done" every time — net 4 (B6 C1 S1)

In game 50 the lapse of Ben's deal was printed in the panel but lost its dice at the table, so the players
never heard it end. Ben's own ruling on Joshua's assessment applies: a deal's lifecycle is state. Make
`deal-over` certain for deals the player is party to; keep the roll for seat-to-seat deals.
**Defense:** one constant and a test; it belongs with item 1 as the deals polish pass.

## 8. A storm-count family — net 3 (B8 C2 S3)

Whole-sentence numbers exist for life and hand; a "that's twelve spells this turn" family fed from the
cast ring gives the table something true to say during a storm or a loop turn, where today it starves.
**Defense:** grounded and cheap, but it overlaps the loop line and item 3; ranks below them.

## 9. Intent keys from the brains' `why` — net 2 (B10 C5 S3)

Beyond `say` and cycle records, scan the brains' reasoning for "lethal", "infinite", "kill seat N" and
let the voice react. High benefit when it fires; risk is false positives from free text ("not lethal yet")
and a brittle vocabulary.
**Defense:** worth trying after item 3, which gives it a place to put the signal; not before.

## 10–12. Observability and small tunes — net 2 each

A grounding score per game (share of lines aimed at the eventual winner or the busiest seat), an `up`
record with restart count plus an effective-config record and a one-line game summary from the runner,
and lowering `GRUDGE_EVERY` to two so the memory layer pays out. Cheap, useful to us, invisible to players.

## 13. Yes / No buttons for a seat's question — net 1 (B11 C5 S5)

Today no question is put to the player because the player cannot answer. Two buttons in the Advisor panel
("Yes" / "No") would let "peace for a turn?" be asked of Ben and answered in a click; the deals relay
already covers the typed path. Java GUI work plus the FULL gate.
**Defense:** real benefit, but the typed `@urza accept` covers most of it and the Java gate is the cost;
a 4.3 item.

## 14–15. Packaging and the suite — net 0

A suite that runs from a package checkout (fixtures pinned to counts, not files) and a voice pack in the
release bucket. Both matter for other people running the release; neither changes the table.

## 16–19. Below the line

Executive proposing deals (B7, but it muddies "the player's offers are the player's"); pruning combo pairs
(Ben wants named cards); deals v2 with kill pacts and conditions (B13 but the brain can lawyer terms the
runner cannot check — revisit after v1 has ten games); the observer's registered-player walk (correct at the
source, but five readers to audit and the cadence fix already covers the voices — 4.3).

---

## Proposed cut for the experimental release

Items 1, 2, 4, 6, 7 and the small tunes (10–12) are a day's work in this session with no agents and no
Java. Item 3 is a second day. Item 5 needs Ben's recording. Items 13–19 wait for 4.3 or later.
