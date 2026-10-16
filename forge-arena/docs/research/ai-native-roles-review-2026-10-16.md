# Five lenses on the table — round two, the analysts' reports verbatim

**Date:** 2026-10-16. **Method:** five Claude Fable 5.1 subagents, one per Boris Cherny archetype (definitions and this round's brief in `ai-native-roles-2026-10-16.md`; the method in `ai-native-roles-2026-09-14.md`), each given the same scope and rules of engagement (read-only: no edits, no git writes, no builds, no launches, no network) and its archetype's lens. Subject: Project 2 only — the voiced table with agentic seat brains; Project 1 and the Jev experiment were excluded by name. They ran in parallel for 23.9 minutes, 334 tool uses, 1.40 M tokens (five analysts, 254k–308k each). Every report below is the analyst's final message reproduced without edits, including its machine-summary block; nothing has been fixed. Tree at review time: `arena` head `516794401fa`. The readable version with charts is `ai-native-roles-review-2026-10-16.html`.

Reading order follows the archetypes: Prototyper, Builder, Sweeper, Grower, Maintainer.

---

# 1. Prototyper

## Prototyper — The pipes now carry intent (a `say` key, binding deals, atoms, threat memory all shipped), but the brains' real voice is still private: the next step-change is letting a seat say, in its own words, the one line it already wrote in `why` — at a break, at lethal, and when Ben talks to it.

### What you read and what shipped, as the Prototyper reads it

Since the September review every bet my lens placed was built on `experimental/voicework2` and shipped in v4.2/v4.3: the seats' `say` key (`10abb2b2837`; `rules.py:120-122` SAY_MENU of 18 ids, `:265` SAY_WINDOWS, `:275` `say_offer`; `runner.py:316-326`; `events.py:333-372` `brain_intent`), the atoms and the under channel (`3267f8c8799`, `aefca699f97`; `voice/atoms.py`, 24 ids × 3 voices; the manifest note records Ben's "one of the best suggestions"), loops called from mechanics or the brain's own intent (`1429ddc95ea`; `events.py:636-645` LOOP_CASTS=4, `:647-666`), threat memory (`scheduler.py:516-538`), the heckle (`events.py:182-216`), deals both ways with the offer pane for the human (`b7713455929` … `3f0439d7e71`; `rules.py:128-136`, `runner.py:356-600`, `scheduler.py:960-1009`), the grounding score, and 13.5 hours of real pods measured (`docs/research/pod-timing-priors.md`, no tuning changed). Not built: intent keys from `why` text (stack rank item 9), the storm-count family (item 8), on-deck pre-planning (`INTERACTIVE-ARENA.md:406-466`; `speculative` is only a prompt flag, `runner.py:80, 2135`), a `turn_plan` record (0 keys in any seat log), any cross-game memory.

Measured over the 18 archives of 9/16–10/06 (12 with Ben at seat 0, 6 all-AI): 6,205 model decisions; the brains added `say` on 419 of 4,809 windows that offered it (8.7 %); 465 says in all, of which 186 were spoken (40 %), median 6.5 s after the decision, p90 12.2 s. Brain-chosen lines are 0–30 of each game's seat lines (2–12 %). Anchored share 13–51 % against the 60 % target in every game. About 55 deals struck, 3 broken, ~10 refused. Ben spoke to a seat five times; no seat answered in words.

### Top findings

**1. The brains already say the lifelike thing — in `why`, where nobody can hear it.** The three knowing deal breaks are the proof. `20260918-160124`, seat 2, t15 DECLARE_ATTACKERS (1 s before the ledger's "deal broken: 2<->1 by 2", ts 1789765202): *"Tezzeret -5 animates ~8 artifacts next turn; no Urza flyers can block — kill the walker, truce-break worth it"*, say=`kill-that`. Same game t22, breaking the alliance with Ben: *"Player One's Seedborn/Cradle board outraces me; 4 life, no reach … lethal now outweighs the alliance"*, say=`youre-the-threat`. Game 64 (`20261002-131143`) t18, seat 3: *"27 trample into 17 life; Urza's 1/4 block absorbs at most 4, so lethal"*, say=`big-swing`; "lethal" appears in 20 of its 749 whys. The table heard `kill-that`, `youre-the-threat`, `big-swing`. The menu is the ceiling: 18 static ids, `taunt` chosen 0 times in 465, `promise` twice (its twin is `deal-with-you`, `events.py:61` — the id means *accept*, a naming trap). Why it matters: Ben's "very very good" table is grounded by proxies (life leader, threat pin); the only process that knows *why* a seat is doing what it does is the seat, and it is told "The human cannot hear your reasoning, only your say" (`seat-brief.md`). Direction: a free-text `line` key (≤12 words, validated, logged) offered on exactly three windows — the one where a deal is broken (`runner.py:560-600` already recognises it), a DECLARE_ATTACKERS the brain calls lethal, and the window after a table-talk note — rendered live in the seat's own voice. The machinery exists: `renderer.py:500-575` renders text through eleven_flash_v2_5 under a 20,000-char cap (`:422`); the human games used at most 1,048 chars (`20260917-154748`), 182 live Joshua lines across 12 games. Each seat manifest already carries its `voice_id`; the renderer reads one (`:400`), so the work is one `Renderer` per library plus a priority lane (`CHAIN_HOP_PRIORITY`, `scheduler.py:26`) so the line plays inside the moment rather than 12–18 s later like advice does (record→playback median 15.0/12.5/11.9 s in `20260917-154748`, `20260918-160124`, `20260926-003649`). Measure: Ben's rating, chars per game, share of breaks and lethals with a spoken reason.

**2. Ben can talk to the seats; no seat has ever talked back.** `advisor_runner.py:1291-1310` relays `@urza <words>` as a `table-talk` note; `runner.py:422-428` renders it: *"says to you … you may answer with a say … or ignore it"*. Five uses: `20260917-154748` t14 "make me an offer" (seat 2's next model window came 518 s later), t15 "we are all going to die, you have it as soon as you use your commander's ability" (seat 1 was mid-loop, answered nothing); `20260918-160124` t22 "I will remember this, you are an oath breaker", "if you kill me, purphoros becomes a creature again, I am the only thing keeping him turned off", "you should pull back your attack" — seat 2 said `no-deal` to a separate truce and `gg` three seconds later; `20261006-203245` t12 "You really suck!" — four affordability fast-path windows passed (`src=affordability`, +15…+18 s), the note reached the model 41 s later, the brain said nothing. Cause: only a deal note or an unshown offer holds the fast path (`runner.py:2066-2068, 2112-2118`); table talk waits for whatever window next needs the model, and the answer can only be a menu id. Why it matters: this is the one channel where the human addresses a brain directly, and the second message above is a real argument (a bluff or a truth about Purphoros) that a human opponent would answer. Direction: treat a table-talk note like an unshown offer for one window (three lines at `:2112`), and give that window the free-text `line` from finding 1. This is the cheapest experiment in the report and the one most likely to change how the table feels.

**3. The most-heard words at the table are still the chorus and the filler.** Top spoken ids across the 18 games: `agree` 187, `disagree` 171, `laugh` 163, live advice 120, then `this-is-fine` 101, `pass-already` 97, `nothing-happening` 97, `what-turn` 90, `good-hand` 90, `long-game` 89, `cards-in-hand` 87, `whats-your-life` 83. Brain-chosen lines total 186 — fewer than `agree` alone. Of 385 queued `agree`/`disagree`, the parents are `youre-the-threat` 57, `this-is-fine` 55, `kill-that` 52, `nothing-happening` 52, `someone-wins` 42, `long-game` 15: about 120 are a seat agreeing with *filler*, because `chains.json` invites `this-is-fine → disagree`, `nothing-happening → agree`, `long-game → agree/pass-already`. "Nothing's happening." "Agreed." is the metronome September described, now with a reply. The priors doc says proposals draw a reply 100 % of the time in real pods — proposals, not weather. Chain plus patter are 65–90 % of seat lines in every hygiene report; anchored never reached 60 %. Direction: subtraction — remove the three filler invites, let only `PROPOSAL_LINES`/prefixes (`scheduler.py:80-81`) draw a chorus, and spend the freed duty on findings 1–2. Measure: anchored share and `agree`/`disagree` count per game.

**4. The table remembers; the brains do not — the memory lives in the wrong process.** `voice-state.json` (`20261006-203245`) holds `hits_from {1:{2:3, 3:2}}`, `last_hit_by`, `deals`, `threat`, `countered_n`, `sweeps`; the grudge line fires on the second hit (`events.py:67, 932-935`; `grudge` spoken 38 times). A brain's memory is its resident session (`brain.py:103`, `PersistentClaude`), rotated at a token cap into dossier + `record.py` (12,000 chars, newest 6 turns full): life totals, stack names, its own plays and whys — no attacks received, no deals struck or broken, no words said to it (`record.py:89-173`; `runner.py:1954, 1981` pass no `extra_lines` though the parameter exists). Game 64 rotated 10 times (hygiene). Deals survive only as runner-side maps re-noted each window (`runner.py:524-557`) — "Breaking it is a choice the table will remember" (`:462`) is a promise the brain cannot keep after a rotation. In 6,205 whys the words "remember", "revenge", "oath", "bluff" occur zero times; "truce/alliance" 159 times (2.6 %), 23 of 163 attack decisions cite a deal — so what the brain *is* told shapes play. Direction: three record-head lines via `extra_lines` — who has hit me and how often, deals in force and broken (both ways), the last thing the human said to me. Cost: an afternoon; no Java. Measure: whys that cite history; attacks returned to the seat that hit first.

**5. Nobody thinks between turns.** The shipped seat is wake-on-request: the on-deck pre-plan in `INTERACTIVE-ARENA.md:406-466` was never built, `turn_plan` is kept in memory only (`runner.py:118-121, 2250-2253`) and never recorded, and the plan executor is off by default. A lifelike player telegraphs: "I've been waiting for this" before the Craterhoof. Direction: one call when the seat goes on deck (the previous seat's turn start, visible in the observer snapshot): 20 words of plan plus one `say`, written to game.jsonl so the voice can speak intent before action. Cost ≈ +1 call per own turn (+10–15 % calls; game 64's seats made 99–264 calls). Measure: lines spoken *before* the deciding cast.

**6. Backend diversity: the archives say not yet, and the cost ledger says why.** Only two August archives ran a backend seat — `or/nvidia/nemotron-3.5-lightning:free` at seat 2: `20260813-164335` 18 decisions, latency median 13.0 s, p90 37 s; `20260813-170617` 8 decisions, median 33.2 s, 2 of 8 punted on TimeoutError at 72 s and 120 s, one WINDOW LOST (`seat-2.log` 16:49:28, 16:56:43). The subscription Opus seats then ran 6.6–9 s median on the spawn transport and now run 1.6–3.6 s on the persistent one. The usage files put the API-equivalent cost of a game at $194–$2,407 with 12–104 M cache-read tokens (game 64: $1,363, 645 calls, 103 M) — a billed backend at Opus class pays that; a cheap one was slow and punty. A backend seat also keeps only its last 8 exchanges (`backends.py:146-167`, 2–24) and never receives the record (`brain.py:606-608`): amnesiac by construction, which finding 4 says is the wrong direction. What diversity would add is *character* — a different model is a different player — and a test of whether deals work against a non-Claude brain. Direction: dead end until a model answers the schema in under 5 s at under $5 a game; the cheap version of "different players" is different briefs — each seat manifest already carries a `temperament` string the Advisor sees but the seat brain never does.

**7. The table is structurally polite to Ben.** `leader_of` excludes `human_seat` (`scheduler.py:540-553`), so a brain's `kill-that`/`youre-the-threat` is re-aimed at the life leader among the AI seats even when its why names Player One (the t22 line above). In the 12 human games every brain line aimed at seat 0 was a deal line. Questions are never asked of the human (A14), heckles are the only lines addressed to him. Direction: when a say's why names "Player One", keep the target; one game, Ben's veto.

### Concerns

The pod priors (14.6 utterances/min, 84 % talk density, flat-to-rising hop odds) are a trap for this lens: chasing them with canned lines reproduces finding 3 at double speed; a pod is dense *because* every line is about the game. Free text depends on ElevenLabs at run time — the package without a key stays baked (Step 10, parked), so finding 1 is a key-holder feature unless the baked `TERMS`-style families grow (they already did: table ids 263 → 329 per voice). The live lane's 12–18 s record-to-play lag is queue discipline, not TTS; without a priority lane a seat's reply lands after the next window. Two games distort every per-minute metric: `20260918-093644` (720 min wall, 13 lines) and `20260926-003649` (385 min, a 7,248 s gap).

### Bugs and corrections

- **Confirmed** — 79 of 250 skipped brain says died as "stale intent" (`INTENT_MAX_AGE_S` = 10, `events.py:51`) because `step()` plays audio synchronously (`voice_runner.py:946-990`, `speak` at `:985`, blocking `afplay` in `renderer.py:246`) and tails game.jsonl only between lines; a say recorded while a chain plays is read too late. Stamp the age from when the tail was last read, or process `scan_game_log` before `speak`.
- **Confirmed** — 72 skips "already said this turn": the brain repeats `big-swing` (22), `gg` (15), `that-hurt` (9) because the SAY_OFFER (`rules.py:266-267`) never tells it what it already said; one clause ("already said this turn: …") fixes it.
- **Confirmed** — a table-talk note does not hold the fast path (`runner.py:2112-2118`); delivery took 41 s and 518 s in the cases above.
- **Confirmed** — `chains.py:22` still says "the player cannot talk back to the seats yet"; `advisor_runner.py:1291` has relayed talk since game 54.
- **Plausible** — `promise` → `deal-with-you` (`events.py:61`) inverts the word's meaning for the brain; `taunt` is never chosen; the menu needs the ids the brains actually reach for (`heads-up` 39 spoken, `big-swing` 28, `that-hurt` 20).
- **Plausible** — `leader_of`'s human exclusion re-aims a brain line meant for Ben (finding 7); not traced to a specific spoken line.
- **Hypothesis** — brains never emit `turn_plan` at all (0 in seat logs could be non-emission or non-recording; `runner.py:2250` stores it in memory only).

### Feature suggestions (ranked by cost)

1. **S** — Hold the fast path one window for a table-talk note (`runner.py:2112`); the human gets an answer within seconds, not minutes.
2. **S** — Tell the brain what it said this turn; stamp intent age from the tail read (the two leaks above recover ~150 of 250 lost says).
3. **S** — Delete the filler → chorus invites in `chains.json`; chorus only on real proposals.
4. **S** — Record-head memory lines through `extra_lines`: hits received, deals in force/broken, the human's last words.
5. **M** — A free-text `line` key at three moments (break, lethal, reply to the human), live-rendered in the seat's voice under the existing 20k-char cap, priority lane.
6. **M** — On-deck pre-plan call with a `say`, recorded, so intent is spoken before action.
7. **M** — Give the seat brains their manifest `temperament` (one line in the init prompt) — three different players without three models.
8. **M** — Cross-game rivalry: the voice reads `runner/ratings-history.jsonl` at startup for a "you beat me last time" family; the brain's init gets one sentence of history against this human.
9. **L** — Deals v2 (kill pacts, conditions): dead end until free text exists; the brain can lawyer terms the runner cannot check.
10. **L** — Backend seats: dead end at today's latency and memory; revisit only with a persona or research goal.

### Observability and efficiency

Record `say_offered` per window so uptake has a denominator (today it is my approximation, 8.7 %); write `turn_plan` and the free-text `line` to seat jsonl; put `anchored` on `spoke` records (hygiene derives it from `source`); a "human answered within N s" metric for talk and offers; time-to-play per brain line (decision ts → spoke ts; median 6.5 s today); note-delivery latency (file written → prompt); active time beside wall time in hygiene so lines/min survives a laptop sleep; grounding on a bigger base than 6–74 addressed lines. Efficiency: the subscription path re-reads 12–104 M cached tokens a game; every experiment above adds notes, not calls, except the on-deck plan (+1 call per own turn) and live rendering (≤ a few hundred chars a game).

### Questions for Ben

1. May the seats speak free text in their own voices when a key is present — a line they wrote, validated and logged — or must everything the seats say stay baked?
2. May a seat call *you* the threat, by name, when its reasoning says so? May it answer an insult?
3. If you had to choose: one seat that answers your words within ten seconds, or thirty per cent more lines?
4. Should a seat remember you across games ("you beat me on Thursday"), or does every game start clean?
5. What is backend diversity *for* — cost, character, or research? The answer decides whether it is dead.

### Follow-up on the September report

**Landed (11):** the `say` key (F2); deals consequential plus a Yes/No for the human (F3, the offer pane); presence atoms (F4); backchannels on an under channel (F5); the human-turn heckle (F6, `waiting-on-you` spoken 46 times); threat memory (F7, `someone-wins` 39); loops from mechanics and the brain's intent (F1 in part); the card-list-gated loop bug fixed (LOOP_CASTS); `turn`/`target`/`channel`/`seq` on `spoke` records; the grounding score; the pod-VOD priors measured (as a study, not a tuning). **Standing (4):** the headline — content-light patter and chain replies still dominate (finding 3); intent keys from `why` text (never built; finding 1 is its successor); stop growing the long tail (table ids 263 → 329 per voice, the TERMS family); proposals answered by every seat — the priors say replies are universal, but the chorus now answers filler. **Superseded (4):** the storm-count family (LOOP_CASTS=4 covers it); the "no third round" comment-vs-behaviour bug (`terminal: True`, `self._chain = None`, `scheduler.py:512`); `arena-hygiene`'s card-source miscount (sources are now listed by class); patter-pool exhaustion under the floor (the floor spends atoms, `FLOOR_ATOM_MAX_RUN`).

```json
{"lens": "Prototyper",
 "findings": [
  {"id": "P1", "title": "The brain's reason at a break or lethal never reaches the table; the say menu is the ceiling", "kind": "feature", "severity": "P1", "confidence": "confirmed", "area": "brain-brief", "effort": "M", "sources": ["runner/seatd/rules.py:120-122", "runner/voice/events.py:333-372", "runner/voice/renderer.py:400-422", "20260918-160124-stop t15/t22", "20261002-131143-stop t18"]},
  {"id": "P2", "title": "The human can talk to seats; table-talk waits for the next model window (41-518 s) and is answered by an id or nothing", "kind": "bug", "severity": "P1", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/seatd/runner.py:2066-2118", "runner/advisor_runner.py:1291-1310", "20261006-203245-stop t12", "20260918-160124-stop t22", "20260917-154748-stop t14"]},
  {"id": "P3", "title": "Chorus and filler are the most-heard words; ~120 of 385 agree/disagree answer filler via chains.json invites", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "voice", "effort": "S", "sources": ["runner/voice/stock/voices/chains.json", "runner/voice/scheduler.py:80-82,480-513", "18 hygiene.txt 2026-09-16..10-06"]},
  {"id": "P4", "title": "Social memory lives in the voice runner; the brain's record omits hits, deals and talk across rotations", "kind": "feature", "severity": "P2", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/seatd/record.py:89-173", "runner/seatd/runner.py:1954,1981", "20261006-203245-stop/voice-state.json", "20261002-131143-stop/hygiene.txt"]},
  {"id": "P5", "title": "No on-deck pre-planning; turn_plan never recorded", "kind": "feature", "severity": "P3", "confidence": "confirmed", "area": "runner", "effort": "M", "sources": ["docs/INTERACTIVE-ARENA.md:406-466", "runner/seatd/runner.py:80,118-121,2250-2253"]},
  {"id": "P6", "title": "Backend diversity is a dead end at today's latency, cost and memory", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "runner", "effort": "L", "sources": ["20260813-164335-stop/seat-2.jsonl", "20260813-170617-stop/seat-2.log 16:49:28,16:56:43", "runner/seatd/backends.py:146-167", "runner/seatd/brain.py:606-608", "seat-*.usage.json 2026-09-16..10-06"]},
  {"id": "P7", "title": "leader_of excludes the human: brain lines are never aimed at Ben", "kind": "concern", "severity": "P3", "confidence": "plausible", "area": "voice", "effort": "S", "sources": ["runner/voice/scheduler.py:540-553", "runner/voice/events.py:58"]},
  {"id": "P8", "title": "79 brain says dropped as stale because the voice loop blocks on playback", "kind": "bug", "severity": "P2", "confidence": "confirmed", "area": "voice", "effort": "S", "sources": ["runner/voice_runner.py:946-990", "runner/voice/events.py:51,347", "runner/voice/renderer.py:246"]},
  {"id": "P9", "title": "72 brain says dropped as already-said: the prompt never tells the brain what it said this turn", "kind": "bug", "severity": "P2", "confidence": "confirmed", "area": "brain-brief", "effort": "S", "sources": ["runner/seatd/rules.py:266-267", "voice-0.jsonl skipped records, 18 archives"]},
  {"id": "P10", "title": "chains.py docstring says the player cannot talk back; the relay exists", "kind": "bug", "severity": "P3", "confidence": "confirmed", "area": "docs", "effort": "S", "sources": ["runner/chains.py:22", "runner/advisor_runner.py:1291"]},
  {"id": "P11", "title": "promise maps to deal-with-you; taunt never chosen — menu ids the brains misread or ignore", "kind": "bug", "severity": "P3", "confidence": "plausible", "area": "voice", "effort": "S", "sources": ["runner/voice/events.py:61", "game.jsonl say counts, 18 archives"]},
  {"id": "P12", "title": "Seat brains never see their manifest temperament; persona briefs are free diversity", "kind": "feature", "severity": "P3", "confidence": "confirmed", "area": "brain-brief", "effort": "M", "sources": ["runner/voice/stock/voices/bill/manifest.json", "runner/advisor_runner.py:155-192", "runner/seatd/brain.py:304-335"]},
  {"id": "P13", "title": "Cross-game memory: ratings-history exists, nothing reads it at the table", "kind": "feature", "severity": "P3", "confidence": "confirmed", "area": "voice", "effort": "M", "sources": ["runner/ratings.py:1-12,449", "runner/ratings-history.jsonl"]},
  {"id": "P14", "title": "Uptake, time-to-play and note-delivery latency are not recorded", "kind": "observability", "severity": "P3", "confidence": "confirmed", "area": "scripts", "effort": "S", "sources": ["scripts/arena-hygiene.py", "voice-0.jsonl spoke keys"]},
  {"id": "P15", "title": "Is free text in the seats' voices acceptable, and may a seat name Ben the threat?", "kind": "question", "severity": "P2", "confidence": "hypothesis", "area": "voice", "effort": "S", "sources": ["runner/seatd/seat-brief.md TABLE TALK", "runner/voice/scheduler.py:540-553"]}
 ],
 "metrics": [
  {"name": "say uptake on offered windows (seats 1-3)", "value": 8.7, "unit": "%", "source": "game.jsonl, 18 archives 2026-09-16..10-06"},
  {"name": "brain says reaching speech", "value": 40, "unit": "%", "source": "465 says / 186 spoke, voice-0.jsonl"},
  {"name": "say to spoke lag median", "value": 6.5, "unit": "s", "source": "game.jsonl ts vs voice-0.jsonl spoke ts"},
  {"name": "brain says skipped stale", "value": 79, "unit": "lines", "source": "voice-0.jsonl skipped source=brain"},
  {"name": "brain says skipped already-said", "value": 72, "unit": "lines", "source": "voice-0.jsonl skipped source=brain"},
  {"name": "agree/disagree queued", "value": 385, "unit": "lines", "source": "voice-0.jsonl queued, 18 archives"},
  {"name": "anchored share range", "value": 51, "unit": "% max (min 13, target 60)", "source": "hygiene.txt, 18 archives"},
  {"name": "deals struck", "value": 55, "unit": "deals (3 broken, ~10 refused)", "source": "voice-0.jsonl kind=deal ledger notes"},
  {"name": "attack whys citing a deal", "value": 14, "unit": "% of 163", "source": "game.jsonl model DECLARE_ATTACKERS"},
  {"name": "human words to a seat", "value": 5, "unit": "messages, 0 answered in words", "source": "advisor-0.jsonl talk/invite"},
  {"name": "live render chars used max", "value": 1048, "unit": "chars of 20000 cap", "source": "20260917-154748-stop voice-0.jsonl"},
  {"name": "advice record to playback lag median", "value": 15.0, "unit": "s", "source": "20260917-154748-stop"},
  {"name": "OpenRouter seat latency median", "value": 33.2, "unit": "s (2 of 8 punts)", "source": "20260813-170617-stop seat-2"},
  {"name": "persistent Opus latency median", "value": 2.5, "unit": "s (game 64)", "source": "20261002-131143-stop hygiene.txt"},
  {"name": "API-equivalent cost per game max", "value": 2407, "unit": "USD-equivalent (subscription, $0 actual)", "source": "20260916-111916-stop seat-*.usage.json"},
  {"name": "cache-read tokens per game max", "value": 104, "unit": "M tokens", "source": "20260926-003649-stop seat-*.usage.json"},
  {"name": "advisor think time median", "value": 3.6, "unit": "s (309 calls)", "source": "advisor-0.jsonl 12 human games"},
  {"name": "atoms per game range", "value": 85, "unit": "max (min 9)", "source": "voice-0.jsonl channel=under"},
  {"name": "stock takes per seat voice", "value": 1089, "unit": "WAV (607 ids)", "source": "runner/voice/stock/voices/*/"}
 ],
 "september": {"landed": 11, "standing": 4, "superseded": 4}}
```


---

# 2. Builder

## Builder — v4.3 holds together for one operator who keeps the laptop awake: the seam, the supervisors and the package are sound and live-exercised, but a sleeping machine is read as a stalled brain, the one cross-language contract test skips the window v4.3 added, and the release cut cannot see its own preflight fail.

### What I read and what shipped, as the Builder reads it

Branch `arena` at `516794401fa`, 445 commits since the September review including the upstream merge. The seam is `MailboxController` (5,141 lines, ~95 overrides, read by section) over `MailboxProtocol` (349 lines): atomic temp-then-rename writes both ways, a 75 ms outbox poll, a 300 s engine default that every launcher overrides to 90 s (`run-pilot-match.sh:37`, `run_table.sh`, `seat_runner.py`), a 15 s heartbeat-stale gate against the runner's 5 s beat, the BL-22 outbox sweep, one bus per seat directory (BL-05). The engine publishes `timeoutSec` on every request and the runner re-budgets from it (`runner.py` `_handle_inner`, "engine timeout is … budgeting from the engine's value"), so the knob really is one. The Python side answers inside 0.8 × timeout from the request file's mtime, drives one long-lived `claude --input-format stream-json` process per seat (`brain.py:103–231`), kills it on its own deadline, counts a stall (`brain.py:503`), rotates the session after two consecutive stalls (`runner.py` ~2340, W-18's fix) and rebuilds game memory from `game.jsonl` on a restart (`runner.py:1922–1958`). Supervision is `run_table.sh`'s 2 s restart loop with an INT/TERM trap, the same shape for the advisor and the voice, `arena-stop.sh` killing by PID file behind an `ours()` command-line guard, and `arena-autostop.sh` polling `gameOver` every 5 s with a 60 s voice sign-off wait. Packaging is nine scripted steps with the BL-47 jar-by-revision rule, the BL-18 cache exclusion and the C5 `check-voice-takes.py` preflight; `cut-release.sh` refuses a dirty tree and runs seven checks; `ship-release-s3.py` multipart-uploads and reads both objects back by sha256. The shipped tarball is 500,548,035 bytes; the voice tree is 4,336 WAVs, 496 MB plus 636 KB of sfx, raws gone, `*.wav binary` in the root `.gitattributes`.

The second sync (`5de150bfbb8` + `81d7cea3d0f`, 2026-10-02 15:25–16:10) took 356 upstream commits, 235 files / +8,691 −4,482 under `forge-game`, `forge-ai`, `forge-core` and the GUI, and cost 43 hand-written lines in `MailboxController` (the `chooseNewTargetsForCopy` port, 3462–3490), one fenced seeded test (HL-22) and 45 minutes plus a 14-minute acceptance game (`docs/UPSTREAM-SYNC.md:329–358`).

Tests: 166 `@Test` methods in 50 interactive classes (`MailboxTestKit` is the fixture), 32 of them in the `extended` group across 13 classes that the standard gate excludes (`pom.xml:29`); `OptionalAndMultiTargetTest`, `StaleTargetsClearedTest` and `ProtocolContractTest` are in the standard gate, `ScepterCopyCastTest` is not. The kit builds a real `Game` with a `MailboxLobbyPlayer`, a scripted brain thread over the real file bus at `arena.mailbox.poll.ms=5`, and a `SILENT` responder that exercises the timeout floor — this is the live seam, not a mock of it. `ProtocolContractTest` validates every emitted request against the JSON schema and writes ten engine fixtures that `test_engine_fixtures.py` validates punts against. Python: 744 tests OK in 57.8 s (one `ResourceWarning: unclosed socket`, D7 still open); two of 53 files read real tapes (`test_cycle_history.py` on the game-47 fixture, `test_engine_fixtures.py`), the rest drive real runner code on synthetic requests with the CLI and HTTP transports stubbed; `test_autostop.py` runs the real shell script eight ways including the voice wait; `test_hardening.py` pins the jar rule in both scripts and runs `arena-play.sh --stops restore` for real.

Live, across the 18 in-scope archives (2026-09-16 → 10-06): 11,528 decisions, 19 punts (0.16 %), 12 lost windows, 0 runner restarts, 0 tracebacks, 0 Java exceptions, and the heartbeat gate fired and recovered twice (`20260926-003649/gui.out:240,243` "brain absent (heartbeat 941s / 7199s stale)", then "brain back" ×2).

### Top findings

**1. Sleep is the table's commonest live failure, and the seam reads it as a stalled brain.** Ten of the 19 archived punts and all 12 lost windows carry latencies no 72 s timer can produce: `20260918-093644/seat-1.log` 00:02:56 `[punt 519.52s]`, 00:38:37 `[punt 2128.97s]`, 09:12:51 `[punt 30852.89s]` with "persistent call used the window (-30781s left) — no spawn retry"; `seat-2.log` 22:11:19 `[punt 1965.3s]`, 23:43:08 `[punt 5488.8s]`; `20260926-003649/seat-0.log` (the Executive runner) 21:41:37 `[punt 7200.19s]`, 22:41:55, 23:43:02, 00:22:01 each followed by "two consecutive persistent-call stalls (2)/(3)/(4) — rotating the session now (stall-x2)". The first v4.3 cut's acceptance game is the same shape (BUG-LOG, "v4.3 cut twice": 17 punts / 19 timeouts / 16 lost windows between 17:30 and 12:06 "while the machine slept", which seeded BL-64). Mechanism: both deadlines are wall-clock (`runner.py` `deadline = mtime + 0.8 * self.timeout_s`; `brain.py:203–207`), so on every wake the runner kills a healthy process, counts a stall, fires stall-x2, and the 45 s rotation then times out too (`seat-1.log` 09:13:44 "model call timed out (45s)"); the engine's own wake decides the window by stock (that is how a stale target reached Counterspell in BL-64); hygiene prints `!! HYGIENE: punts` and ratings void the game (`20260926`'s spool is `.voided`). Why it matters: a red hygiene flag, a voided rating and a seam bug all came from a closed lid, and the counters Ben steers by cannot tell sleep from a model stall. Direction (S): detect the jump (elapsed > 2 × the window, or wall vs. monotonic drift), record `punt: machine slept`, skip the kill and the stall count; a `sleep` kind in `transport-events.jsonl` and a hygiene line; optionally `caffeinate -i -w $GUI_PID` in `arena-play.sh` for all-AI tables.

**2. The contract test has a hole exactly where v4.3 landed, and the schema is behind the wire.** `MailboxController.java:1434` emits `"purpose", "TARGETS"` and `:1436` `"declinable"` on CHOOSE_ENTITIES; `schemas/arena.mailbox-request.1.schema.json:98` enumerates `purpose` as `["TRIGGER_ORDER", "COLOR"]`, "CHOOSE_MODE only", and has no `declinable`. The suite is green only because `ProtocolContractTest` never drives a TARGETS window — `fixtures/engine/choose_entities.json` is "Choose up to two (0-2)" with `purpose: None`. `test_engine_fixtures.py:45` pins `gameId` to `^\d+-\d+$`, which the live wire (`1791343109224-2091-1`, the BL-28 serial, allowed by the schema) does not match, and the fixtures carry `timeoutSec: 300` where live is 90. Why: the schema is the documented contract the Python side builds on; a validator pointed at a live TARGETS request rejects it, and the Python side of v4.3 (`test_game64_fixes.py`, 25 tests) is tested on hand-made requests only. Direction (S): add `TARGETS` and `declinable`; make the contract test emit one Tezzeret/Frost Breath window; relax the regex to the schema's pattern.

**3. `cut-release.sh` cannot see its own preflight fail.** Step [3/4] runs `(cd "$DEST" && forge-arena/runner/run_table.sh --preflight 2>&1 | tail -1)` and step [2/4] runs `build-light-package.sh --force | tail -3`; POSIX `sh` has no `pipefail`, so `set -e` sees `tail`'s zero. The build step is caught indirectly by the VERSION-equals-HEAD grep; the package preflight is not. This is the 9/3 rule in the BUG-LOG header ("capture Maven's exit status, never a filtered tail") reappearing in the release path. Direction (S): run to a file, test the status, then print the tail.

**4. The table's own records have no schema; the two "mailbox-side" schemas the brief names are Project 1's.** `arena.game-record.1.schema.json` is referenced only by `harness/GameRecord.java`, `SchemaValidationTest`, `BatchIntegrationTest`; `arena.events.1.schema.json` only by `report/*` tests. `GameResultSpool.java:149` writes `{"schema": 1, "gameId": …}`, which the game-record schema (`additionalProperties: false`, `seed`, `game_index`) rejects. `game.jsonl` mixes decision rows with `type: DEAL` rows (nine in `20260916-192313`), which `arena-hygiene.py:182–188` tallies as "runner-answered … None 9". Why: 120 archives are "the research corpus, never delete", and the hygiene script is their only de-facto schema. Direction (M): one `arena.table-record.1.schema.json` for `game.jsonl` / `seat-N.jsonl` / `transport-events.jsonl` rows plus a test that validates one archived game; hygiene skips DEAL rows.

**5. The seam's own map is stale.** `MailboxController.java:58–81` still says "normal spell targeting (chooseTargetsFor, deliberately left on stock…), confirmAction, trigger ordering, mana-color, numbers, yes/no — stays on super" while `chooseTargetsFor` (1637), `multiTargetsViaSeat` (1395), `confirmAction` (3349), `orderViaSeat` (4059), `colorsViaSeat` (3880) and `numberViaSeat` (2599) are all mailboxed; `docs/INTERACTIVE-ARENA.md:315` "Known limitations (current, 2026-09-08)" lists "multi-target spells" as deliberately stock after v4.3 moved them to the seat; `packaging/README.md:368` says the audio is "about 270 MB" against 496 MB on disk in a 500 MB tarball. For a 5,141-line file the header is what the next person reads first. Direction (S).

**6. stall-x2 landed and worked once for real; the W-5/BL-06 cost and the in-window rotation remain.** `20260917-132142/seat-1.log` 13:10:27 and 13:11:40: two genuine 72 s stalls at t16, "rotating the session now (stall-x2)", the seat recovered; the advisor timed out in the same minute ("[r4-t15 · advisor] (no answer …)" ×2) — a host-wide stall of about three minutes, not a seat bug. The rotation is bounded to `min(45, 0.5 × timeout)` (`runner.py:1985`) but still spends inside the window. `PersistentClaude.call` (`brain.py:213–231`) already reads stream-json events line by line and only looks for `result`. Direction (S): the W-13 watch item — kill a call that has emitted nothing for N seconds and retry in what remains; build the replacement session outside the window.

**7. The sync was cheap and well-recorded, and left one standing liability with "(reading)" as its arbiter.** `UPSTREAM-SYNC.md:185–213` is the right artefact: a row per seam that leans on upstream semantics, with what the 356 commits changed under each. Its new row — "`chooseNewTargetsForCopy` (our verbatim port, since this sync) … Arbiter: `ScepterCopyCastTest` (reading)" — is a second copy of a private upstream method pinned by nothing, and `ScepterCopyCastTest` is in `extended`, off the standard gate. Plausible, not shown: row 1 notes `resetOnceResolved()` no longer resets targets, and the first game on the merged engine produced BL-64 (leftover targets on a hand card's ability); BUG-LOG calls it pre-existing. Direction (S): a test that diffs the port against upstream's method text at test time (the `UpstreamMarkerTest` pattern); ten minutes with `StaleTargetsClearedTest` on tag `pre-sync-20261002` turns the BL-64 belief into a verdict.

**8. Test residue reached a game archive, and the advisor lacks the seat runner's teardown.** `20260916-111916/claude-persistent-seat-1.err` is 2,484 bytes of twelve identical "Error: --resume requires a valid session ID … Provided value "sess-A"" — `sess-A` is the fixture id of `test_budget_deadline.py:82` / `test_wedge_recovery.py:38`, so a real `claude` was spawned by a test and its stderr landed in the live `runner/logs/`, which `arena-stop.sh` archived with the next game. `brain.py:483` derives that path from `self.root` (the repo root), not from `log_dir`; today's suite run left `runner/logs/` clean, so the current stubs hold. Separately, `advisor_runner.py` and `voice_runner.py` install no SIGTERM handler (grep `signal|kill_child`: none) while `seat_runner.py` does (BL-28); `arena-stop.sh`'s `kill` then `kill -9` orphans an in-flight advisor call, and under Executive the advisor owns a second brain (`advisor_runner.py:785 SeatRunner(0, …)`). No orphan on the box now. Direction (S): route the `.err` path through `log_dir`; add the BL-28 handler to the advisor.

**9. Supervision has no watchdog for a live-but-dead engine and no damper for a Claude seat.** `run_table.sh` `seat()` damps crash loops only `if is_backend`; `arena-autostop.sh` stops on `gameOver` or a vanished GUI PID, so a JVM whose game thread died (BL-47's shape: "game thread dead, seats idle") keeps a table up until a human notices. Neither path has fired since 9/16 (all 18 hygiene blocks: "restarts 0"). Direction (S): autostop also stops an all-AI table whose `observer-state.json` mtime is older than N minutes; a damper for every seat.

### Concerns

The 90 s window and the 72 s budget are serial per decision: the archives show no pre-warm punts (turn-0 mulligans all answered), so W-5's cost is real only on a slow host, but there is still no GUI signal while a seat sits in a 90 s wait. `MailboxProtocol.exchange` leaves a late `resp-N.json` if the runner writes inside the poll gap; the runner's 2 s consume-wait and the startup sweep cover it, and seq never restarts within a JVM, so this is safe by two mechanisms rather than one. The `extended` group (32 tests, 13 classes) is off the standard gate by design; after a sync the FULL gate ran, but a routine gate does not run `ScepterCopyCastTest`, `UnaffordableCastRollbackTest` or `FallbackMatrixTest`. The runner's stall counter is reset only by a successful rotation (`brain.py:618`), so under sleep every later punt re-spends a 45 s rotation (`20260926`: counts 2, 3, 4). `ship-release-s3.py` reads 1 GB back to verify two objects — honest, and fine for one operator. `run_table.sh --preflight` is the best piece of launch engineering here: sha-stamped manifests, 100-card and DFC checks, no JVM at launch.

### Bugs and corrections

- Sleep/wake punts classified as model stalls, process killed, stall-x2 and rotation fired, rating voided — **confirmed** (finding 1).
- Schema `purpose` enum lacks `TARGETS` and `declinable`; contract test never emits the window — **confirmed** (finding 2).
- `test_engine_fixtures.py:45` regex stricter than the wire and the schema — **confirmed**.
- `cut-release.sh` masks the package preflight's exit status behind `tail` — **confirmed** (finding 3).
- `arena-hygiene.py:182–188` counts DEAL rows as runner-answered decisions ("None N") — **confirmed**.
- Stale seam docs: `MailboxController.java:58–81`, `INTERACTIVE-ARENA.md:315` item 1, `README.md:368` — **confirmed**.
- Test stderr archived with a game (`20260916-111916/claude-persistent-seat-1.err`) — **confirmed once**; `brain.py:483` root-derived path as the standing hazard — **plausible**.
- Advisor runner orphans its in-flight CLI call on `arena-stop` — **plausible** (by reading; no orphan observed).
- BL-64 made likelier by the sync's `resetOnceResolved` change — **plausible**, low.
- A Claude seat crashing after its init call re-pays the init every 2 s with no damper — **hypothesis** (zero restarts in 18 games).

### Feature suggestions (ranked by cost)

1. (S) Sleep detection in the runner and the brain, a `sleep` transport event, a hygiene line; `caffeinate` for all-AI tables.
2. (S) `TARGETS`/`declinable` in the schema and one TARGETS case in `ProtocolContractTest`.
3. (S) Exit-status capture in `cut-release.sh`; a `src`-newer-than-`classes` freshness check before packaging.
4. (S) A port-diff test for `chooseNewTargetsForCopy` against upstream's text.
5. (S) Autostop staleness watchdog; a crash damper for every seat; the BL-28 handler in the advisor.
6. (S) Stream-silence early kill and retry (W-13), rotation built outside the window.
7. (M) A schema for the table's records and a test over one archived game.
8. (M) A seat-side `--replay <archive>` that drives `SeatRunner` from an archived `game.jsonl` with the transport stubbed — the voice runner already has exactly this (`voice_runner.py:84, 1132`, from the archived `observer-tape.jsonl`), and it is the cheapest way to make finding 1's fix verifiable offline.

### Observability and efficiency

Add `sleep` and `clock-jump` kinds to `transport-events.jsonl` and a "sleep windows" line to hygiene so punts split into stalls / invalid answers / sleep (today: 5 / 4 / 10). Write the engine's "brain absent / brain back" transitions to `engine-events.jsonl` (they live only in `gui.out`). Skip DEAL rows in the decision tally. Seventeen of eighteen `.err` files are empty — archive them only when non-empty. The suite grew from 453 in 20.9 s to 744 in 57.8 s; the loopback server's unclosed socket (D7) is still the one warning. Reading back 1 GB per ship is acceptable; a HEAD-plus-size check before the byte verify would skip the second download when the copy failed outright.

### Questions for Ben

1. Is a table left up through a laptop sleep a supported state? It happened in three of twenty-one games including the first v4.3 acceptance; if yes, finding 1 is the next fix, if no, `caffeinate` plus a "slept" line is enough.
2. Should a sleep/wake ever count toward stall-x2, or should the counter reset on a wake?
3. Do the two Project 1 schemas stay in `schemas/` beside the one live contract, and does the archive corpus deserve a schema of its own?
4. Is `extended` meant to stay off the routine gate now that the sync's hand-worked row is arbitrated only there?
5. Is the verbatim `chooseNewTargetsForCopy` port something you want pinned by a test, or accepted as a reading until W-23 opens a seat window for copies?

### Follow-up on the September report

Landed (6): #1 restart memory — `voice-state.json` with `_durable_state` (`voice_runner.py:514–545`: eliminated, seen seats, combos done, game changers, deals) in every archive; #2 the forced line on restart — `last_spoken_at = self.clock()` (`:330`), restored on resume (`:712`); #4 muted teardown — a muted runner still reads the snapshot and publishes `final.json` (`:97`), with two voice cases in `test_autostop.py:106,123`; #6 one definition of anchored — `voice/scheduler.classify_source` used by hygiene (`arena-hygiene.py:49–63`); #8 ring gaps recorded — "ring gaps 0" in every hygiene block, never fired; #9 the `if False` residue — gone, loop state initialised in `_init_loop_state` (`runner.py:957`). The September feature "`--replay <archive>` from an appended snapshot tape" landed too (`observer-tape.jsonl` archived; `voice_runner.py:1132`), as did the BSD-`stat` concern (B5). Standing (2): #3 package size — the raws were purged, `*.wav binary` and the C5 preflight exist, but the format is still WAV, the tarball is 500 MB and `README.md:368` keeps the old number; #10 `getRegisteredPlayers()` — `ObserverSnapshot.java:478, 557, 771` still iterate `getPlayers()`, by Ben's decision for the mutation-tick fingerprint (W-20 E1). Superseded (2): #5 banner-vs-runner defaults — the knobs were retired into `tuning.json` and a test pins the banner to the code; #7 the silence floor at rowdy — measured (duty 0.44–0.52 in the 9/16–17 rowdy games) and answered by making `normal` the default (0.27 and 0.35 in games 64–65). The unclosed-socket warning stands; the unused `gid` cannot be mapped — the file was rewritten from 2,637 to 1,265 lines.

```json
{"lens": "Builder",
 "findings": [
  {"id": "B1", "title": "Sleep/wake read as a model stall: punts, process kills, stall-x2, voided rating", "kind": "bug", "severity": "P1", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/seatd/runner.py:_handle_inner deadline", "runner/seatd/brain.py:203-207", "runner/seatd/brain.py:503", "runner/logs/archive/20260918-093644-stop seat-1.log 09:12:51", "runner/logs/archive/20260926-003649-stop seat-0.log 21:41:37", "docs/BUG-LOG.md v4.3 cut twice"]},
  {"id": "B2", "title": "Request schema lacks TARGETS/declinable; contract test never emits the v4.3 window; fixture regex stricter than the wire", "kind": "bug", "severity": "P2", "confidence": "confirmed", "area": "tests", "effort": "S", "sources": ["src/main/java/forge/arena/interactive/MailboxController.java:1434-1436", "schemas/arena.mailbox-request.1.schema.json:98", "runner/tests/fixtures/engine/choose_entities.json", "runner/tests/test_engine_fixtures.py:45"]},
  {"id": "B3", "title": "cut-release.sh masks the package preflight exit status behind tail", "kind": "bug", "severity": "P2", "confidence": "confirmed", "area": "packaging", "effort": "S", "sources": ["packaging/cut-release.sh step 3 preflight line", "packaging/cut-release.sh step 2 build line"]},
  {"id": "B4", "title": "Table records have no schema; game-record and events schemas are Project 1's; hygiene counts DEAL rows as decisions", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "docs", "effort": "M", "sources": ["src/main/java/forge/arena/interactive/GameResultSpool.java:149", "scripts/arena-hygiene.py:182-188", "runner/logs/archive/20260916-192313-stop game.jsonl DEAL rows"]},
  {"id": "B5", "title": "Seam docs stale: MailboxController Javadoc, Known limitations item 1, README audio size", "kind": "bug", "severity": "P3", "confidence": "confirmed", "area": "docs", "effort": "S", "sources": ["src/main/java/forge/arena/interactive/MailboxController.java:58-81", "docs/INTERACTIVE-ARENA.md:315", "packaging/README.md:368"]},
  {"id": "B6", "title": "Genuine stalls still cost the full window; rotation spends inside it; no stream-silence early kill", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/logs/archive/20260917-132142-stop seat-1.log 13:10:27", "runner/seatd/runner.py:1985", "runner/seatd/brain.py:213-231", "docs/BUG-LOG.md W-13 BL-06 W-5"]},
  {"id": "B7", "title": "Sync port of a private upstream method pinned only by a reading in an extended-group test", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "sync", "effort": "S", "sources": ["src/main/java/forge/arena/interactive/MailboxController.java:3462-3490", "docs/UPSTREAM-SYNC.md:185-213", "81d7cea3d0f", "pom.xml:29"]},
  {"id": "B8", "title": "Test stderr archived with a game; advisor and voice runners lack the BL-28 SIGTERM handler", "kind": "bug", "severity": "P3", "confidence": "plausible", "area": "tests", "effort": "S", "sources": ["runner/logs/archive/20260916-111916-stop/claude-persistent-seat-1.err", "runner/seatd/brain.py:483", "runner/seat_runner.py install_signal_handlers", "runner/advisor_runner.py:785"]},
  {"id": "B9", "title": "No watchdog for a live-but-dead engine; no crash damper for Claude seats", "kind": "concern", "severity": "P2", "confidence": "hypothesis", "area": "scripts", "effort": "S", "sources": ["scripts/arena-autostop.sh main loop", "runner/run_table.sh seat() damper", "docs/BUG-LOG.md BL-47"]},
  {"id": "B10", "title": "Seat-side --replay from an archived game.jsonl (the voice runner already has one)", "kind": "feature", "severity": "P3", "confidence": "confirmed", "area": "tests", "effort": "M", "sources": ["runner/voice_runner.py:84", "runner/voice_runner.py:1132", "runner/replay.py:1-10"]},
  {"id": "B11", "title": "Engine brain-absent/back transitions and sleep windows absent from the jsonl records", "kind": "observability", "severity": "P3", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/logs/archive/20260926-003649-stop/gui.out:240-243", "runner/seatd/runner.py:_transport_event"]},
  {"id": "B12", "title": "Is a table left up through laptop sleep a supported state", "kind": "question", "severity": "P1", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["docs/BUG-LOG.md v4.3 cut twice", "runner/logs/archive/20260918-093644-stop", "runner/logs/archive/20260926-003649-stop"]}
 ],
 "metrics": [
  {"name": "archived decisions (18 games)", "value": 11528, "unit": "decisions", "source": "hygiene.txt in each in-scope archive"},
  {"name": "punts", "value": 19, "unit": "punts", "source": "game.jsonl source=punt across the 18 archives"},
  {"name": "sleep-shaped punts (latency > 2x window)", "value": 10, "unit": "punts", "source": "seat-*.log 20260918-093644 and 20260926-003649"},
  {"name": "windows lost", "value": 12, "unit": "windows", "source": "hygiene.txt runner signals"},
  {"name": "runner restarts", "value": 0, "unit": "restarts", "source": "run_table.out 'runner exited' across 18 archives"},
  {"name": "Java exceptions in gui.out", "value": 0, "unit": "lines", "source": "grep over 18 archives"},
  {"name": "Python tests", "value": 744, "unit": "tests OK in 57.8 s", "source": "python3 -m unittest discover -s tests"},
  {"name": "Java interactive @Test methods", "value": 166, "unit": "tests in 50 classes, 32 in extended", "source": "grep src/test/java/forge/arena/interactive"},
  {"name": "MailboxController", "value": 5141, "unit": "lines", "source": "wc -l"},
  {"name": "voice takes shipped", "value": 4336, "unit": "wav files, 496 MB", "source": "find/du runner/voice/stock"},
  {"name": "v4.3 tarball", "value": 500548035, "unit": "bytes", "source": "docs/BUG-LOG.md field note 107"},
  {"name": "second sync engine delta", "value": 235, "unit": "files (+8691/-4482), 43 hand-written lines", "source": "git diff --stat 3e037fdc9a9..fb4d8091126; git show --stat 81d7cea3d0f"}
 ],
 "september": {"landed": 6, "standing": 2, "superseded": 2}}
```


---

# 3. Sweeper

## Sweeper — The diet half happened: the knobs and the dead code went, but half the voice stock has never spoken, the raw takes still weigh 351 MB in history, and the docs now outweigh the runtime.

### What you read and what shipped, as the Sweeper reads it

Since the September review (`e517f2eb300`) 89 non-merge commits touched `forge-arena`. Three of my ten findings landed outright: `9c10a30a438` turned 36 voice knobs into five plus `runner/voice/stock/voices/tuning.json` (27 keys); `222f0d563fc` split `voice_runner.py`; `d54ab30bd08` deleted the raw takes from the tree. The runtime did not shrink. The voice path is now `voice_runner.py` 1,265 + `voice/events.py` 1,353 + `voice/scheduler.py` 1,233 + `renderer.py` 663 + `atoms.py` 347 + `table.py` 299 + `chains.py` 140 = 5,300 lines, against 2,777 in September (+91 %: the under channel, deals, restart memory, tapes). `seatd/runner.py` grew 1,847 → 2,365, `advisor_runner.py` 1,031 → 1,749. Tests: 53 files, 13,973 lines, 744 tests, OK in 54 s (exit 0, one unclosed-socket `ResourceWarning`). The Java seam is 9,083 lines, `MailboxController` 5,141 with 108 methods.

Live evidence: 18 archives (`20260916-111916-stop` → `20261006-203245-stop`), 4,943 lines spoken, 5,349 skipped, 901 dropped, 131 deal-ledger rows. Every one of the 18 `launch-config.txt` files shows every knob at its default except `ARENA_CHATTER` (rowdy 15, normal 3) and one `ARENA_JFR=1`.

### Top findings

**1. The raw purge was a deletion, not a purge: 2,495 raw takes, 351.0 MB, are still in `arena` history.** `git ls-tree -r -l d54ab30bd08^ -- runner/voice/stock/voices | grep /raw/` sums to 351.0 MB; `git log --all -- '…/raw'` lists seven reachable commits. The hardening plan §10 (`docs/reviews/2026-09-14-voicework2-hardening-plan.md:230`) says "prepared 2026-09-16, NOT executed; runs on Ben's merge go"; the merge happened 9/17 and the rewrite never ran, and there is no `.bundle` in the repo directory. `.git` is 2.2 GB (packs 1.06 GB + 652 MB + 391 MB), and `git count-objects` reports "garbage found: .git/objects/pack/tmp_pack_7LjlU3" — the stray pack the plan's performance ledger named. Why it matters: every clone and every backup pays 351 MB for audio nothing reads, and the private remote carries it too. Direction: either run §10 as written (filter-repo on `arena`, bundle kept and gitignored, force-push the private remote) at the next sync boundary, or declare the history permanent and close §10; in both cases `git gc --prune=now` after the reflog (705 entries) expires. Lines removed: none. Behaviour lost: none.

**2. Half the voice stock by bytes has never spoken: 1,932 of 4,329 manifest-backed files, 265.5 MB of 532 MB.** Aggregated over the 18 `voice-0.jsonl` files against every `manifest.json` (ids map to `<id>.wav`/`<id>-N.wav`). Per voice: table 230 of 329 ids silent (247 files, 25–31 MB each), cards 148 of 188 (200 files, 30–40 MB each), base 5 of 66, atoms 3 of 24; Joshua's root stock 31 of 66 ids (35 files, 8.0 MB). Of the silent table ids, 151 are address lines and 55 are `deal-<colour>` lines; the colour-identity chart alone is 512 files, 64.7 MB across four voices with zero fires — kept by Ben's decision (plan §2: "the fallback for every commander other people bring"), and `who_for_deck` (`voice/table.py:219-234`) confirms it can only fire for a deck absent from `address.json`. The part the plan left open is due: "Combo `-online` + `-react` pairs — keep; revisit after five more games". Eighteen games later, 64 of 74 combo ids never spoke (8 `-online`, 2 `-react` did), 68 of 87 game-changer card ids and 16 of 27 commander ids never spoke, and 56 of the 330 distinct ids that did speak spoke exactly once. Direction: an eviction rule, not a one-off: a sub-library id unspoken across the last N archives moves to the release bucket, not the package. First candidates by size: the `-react` half of the combo pairs (37 ids × 4 voices, ~148 files, ~20 MB), the 31 silent Joshua quotes (8 MB), the 16 silent commander triplets for decks not on the table. The package would drop from ~480 MB toward ~400 MB with no line any game has heard lost.

**3. 53 knobs read, 22 ever set by anything, one turned in eighteen games.** Census over `runner/`, `scripts/`, `packaging/` and the Java seam: 49 `ARENA_*` names are read through `environ.get`/`${…}` plus four through `backends._env_num` (`backends.py:117-147`). The voice half was cleaned; the weight now sits elsewhere: `ARENA_ROTATE_TOKENS`/`ROTATE_HARD` (`seatd/runner.py:64,72`), `ARENA_REACT_LOW_EFFORT` (`:1618`), `ARENA_ADVISOR_ROTATE_TOKENS` (`advisor_runner.py:612`), `ARENA_AUTOPASS_RECEIPTS` (`:843`), four `ARENA_AUTOSTOP_*` timings (`arena-autostop.sh:31-77`), seven backend knobs — all at default in all 18 `launch-config.txt`. Three are read and documented nowhere: `ARENA_STOPS` (`arena-play.sh:46`), `ARENA_PACKAGE_CP_TXT` (`build-light-package.sh:54`), `ARENA_OAI_CTX` (`backends.py:133`, invisible to the `LaunchBanner` census test at `tests/test_hardening.py:366-367` because its regex only sees `environ.get`). The banner (`arena-config.py`, 31 rows) and the README table (`packaging/README.md:483-562`, 30 rows) describe a surface nobody touches. Direction: repeat the voice move — a `runner/seatd/tuning.json` for rotation, react-effort, receipts and autostop numbers; the operator keeps the launcher flags plus `ARENA_CHATTER`, `ARENA_BARKS`, `ARENA_VOICE*`, `ARENA_AUTOPASS*` (about 12 rows). Removed: ~60 lines of env parsing, ~19 banner rows, ~19 README rows; `LaunchBanner` keeps the rest honest. Breaks: nothing at default.

**4. The backend path has had no live game since 2026-08-13.** `ARENA_SEAT_MODELS=(unset)` in every archive; `backends.py` (453 lines), `tests/test_backends.py` (339), README §"Other models on the backend" (`:589-623`), seven knobs, the `set_model`/`parse_model` branches in `brain.py:350-380` and both control-file pollers carry it. Kept by the parked OpenRouter plan and its no-harm contract, so not a deletion candidate; but `backends.py:445-446 reset_mod_counter` is the only function in the whole runner referenced nowhere (not even by a test). Direction: delete the two lines; mark the section optional in the banner; revisit the 800 lines when the plan is unparked.

**5. The advisor and the seat runner each carry their own control-file poller and session rotator.** `_init_control`/`_apply_control`: `advisor_runner.py:702-770` (68 lines) and `seatd/runner.py:185-240` (55 lines) — the same mtime-then-parse, torn-write-retried protocol with two divergent policies (the seat debounces a backend swap 2 s, `:214-221`; the advisor refuses backends outright, `:736-747`). `_maybe_rotate`: `advisor_runner.py:819-835` and `seatd/runner.py:1960-1992`, the same record-render-then-`brain.rotate` with different caps. Direction: one `runner/control.py` `ControlFile(path, on_model, on_effort, debounce_s)` and one `rotate_session(brain, record, cap, timeout)`; about 70 lines removed and one place to fix the next torn-write bug. Breaks: nothing; both tests files (`test_rotation_and_executive.py`, `test_stall_rotation.py`) drive the public behaviour.

**6. The documents outweigh the runtime and three of them are stale on their face.** `docs/INTERACTIVE-ARENA.md` is 156 KB; the field notes section (`:508-2174`) is 1,667 lines, 121.6 KB, 112 notes, with notes 103–107 appended in reverse order after 102 (`:2127-2143`). "Known limitations (current, 2026-09-08)" (`:315-346`) item 1 still says multi-target spells stay stock — superseded by BL-61 (`MailboxController.java:1395 multiTargetsViaSeat`, `:1528 divideViaSeat`, shipped v4.3); item 7 says the no-key voice is "not yet seen" — seen in `20260916-164732-stop` (`[voice] up … live=off (no ELEVENLABS_API_KEY)`). Three historical sections (`:347-507`, 161 lines) describe the pre-ship world. `docs/BUG-LOG.md` is 202 lines but 102.8 KB (longest line 2,556 characters) and still lists W-4 in the watch list with "CLOSED 2026-10-02" in the row. `packaging/PATCH-NOTES.md` ships whole (`build-light-package.sh:198`): 42 KB of its 58 KB is v1–v4.1 (`:202-952`). `docs/PR-LOG.md` (80 KB) has not been appended since 2026-08-02 despite its own "append with every PR" rule; `docs/IMPLEMENTATION-PLAN.md` (116 KB) is the Project 1 master spec ("headless … at batch scale"). Direction: field notes to `docs/field-notes/2026-0M.md` by month and INTERACTIVE-ARENA.md back under 40 KB; re-date and re-check the limitations list at each release; drop the W-4 row; ship only the v4.x patch notes (−42 KB per package); PR-LOG, IMPLEMENTATION-PLAN, AGENT-SDK-SEATS and SPEC-executable-turn-plans to `docs/archive/`. About 350 KB relocated, nothing lost.

**7. Tuning has two homes again.** `tuning.json` says it holds "every number the table's talk runs on that is not an operator's choice"; beside it sit 96 module-level numbers — 57 in `scheduler.py` (`SILENCE_FLOOR_S :75`, `IDLE_S :151`, `RECENT_S :159`, `PATTER_REPEAT_S :160`), 16 in `events.py` (`THINK_S :65`, `GRUDGE_EVERY :67`), 12 in `atoms.py`, 11 in `voice_runner.py`. The plan's "one `HUMAN_TURN_MULT`" did not land: `duty_human` 0.6, `patter_human` 0.33, `barks_human_p` 0.7, `chain_human_p` 0.5 (tuning.json) plus `SILENCE_FLOOR_S["human"]` 24 and `DUTY_HUMAN_MULT` (`scheduler.py:72,75`) are still six numbers for one feeling, and the two patter clocks (`_patter_due` and the floor) survive side by side in `scheduler.py:1186-1198`. Direction: either the ~15 human-turn and clock numbers move into tuning.json, or its note stops claiming completeness.

**8. Experimental seat flags off in every game since July.** `SEAT_SPECULATIVE=0` and `SEAT_REACT_HOLD=0` in all 18 `launch-config.txt`; the code is `seatd/runner.py:1408-1456 _plan_guard`, the `speculative`/`react_hold` branches at `:1876, :2135, :2274, :2295`, `rules.py:506-536 bind_plan_step`, `run_table.sh:39-44`, `seat_runner.py:66-87`, `tests/test_plan.py` (79) and `test_hold.py` (66), and `docs/SPEC-executable-turn-plans.md` (8.6 KB, 2026-08-09). About 130 runtime lines, 145 test lines, one spec. Direction: a decision — ship it in a game or shelve it; the restart-memory layer is the contrast (`voice_runner.py:514-732`, ~219 lines, `test_restart_memory.py` 293; 0 restarts in 18 archives) and it stays by Ben's explicit decision ("a hot-swapped runner is normal and must not forget").

**9. The package ships a generator whose only importers it excludes, and one orphan script is Project 1 by nature.** `build-light-package.sh:158-165` rsyncs `runner/` whole minus `table_lines.py`, `card_lines.py`, `build_stock.py`; `runner/voice/joshua_lines.py` (347 lines) is imported only by those three files (`grep -rl joshua_lines`), so it ships to no purpose. `scripts/observe-play.py` (192 lines, last touched 2026-07-29, "Observe play across a batch run dir") is referenced only by `docs/INVENTORY.md`, `IMPLEMENTATION-PLAN.md` and `PR-LOG.md`; it belongs on the Project 1 list, not in the operator set. `runner/seat_runner.py:1-12` still says brain mode "lands in H3-H4". Direction: one more `--exclude`, one re-homed file, one docstring.

**10. Test doubles are copied, not shared.** 377 lines of `Fake*` scaffolding across the suite: ten `FakeBrain` classes of 16–18 lines (`test_advisor_ask.py:19`, `test_advisor_barks.py:23`, `test_advisor_lifecycle.py:22`, `test_advisor_quips.py:16`, `test_deals_advisor.py:31`, `test_deals_seat.py:34`, `test_cycle_replay.py:29`, `test_round_two_ops.py:86`, `test_backends.py:58`, `test_rotation_and_executive.py:180`), three `FakePlayer`, two `FakeMailbox`. To the brief's question: the doubles sit at process boundaries (audio device, model process, mailbox, a scripted HTTP endpoint) and no test asserts on a fake's own behaviour; the cost is duplication, not false confidence. Direction: `tests/fakes.py`, about 150 lines removed.

### Concerns

`MailboxController` has nothing to subtract by call-site: every private method is called, no constant or field is mentioned once, and the three names the scan flags (`preferredTapCards :352`, `preferredSacCards :2181`, `preferredPaymentCards :2671`) are engine overrides. Its weight is three methods — `chooseSpellAbilityToPlay` 470 lines (`:464-933`), `buildState` 314 (`:4151-4464`), `playChosenSpellAbility` 269 (`:934-1202`) — and thirteen `stockSurface(...)` hand-backs (`:1398-1517, :3828-4130`) that are the honest map of what is still stock. The chains table: 33 of 112 openers (28 of 168 rows in `chains.json`) never queued a reply in 18 games; hop 3 fired 10 times in 1,446 candidates — the hop cap is doing nothing and costing nothing. The "already said this turn" gate skipped 1,534 candidates, more than any dice roll — the busiest gate is the cheapest, good. The seat brief is 18.5 KB and the advisor brief 6.1 KB per session; the advisor's bark guide is unchanged at 2,928/3,166 characters (~730/790 tokens) on 309 advice calls across the 12 advisor games, producing 163 of 4,943 spoken lines (3.3 %) — kept by decision, but the plan's rider "the guide text can still be trimmed" has not been taken up: only 12 of its 32 ids ever reach the air.

### Bugs and corrections

1. **confirmed** `packaging/README.md:368` "about 270 MB of the package" — the stock measures 517 MiB on disk and the same file's line 27 says the package is ~480 MB.
2. **confirmed** `docs/INTERACTIVE-ARENA.md:315-346` is dated 2026-09-08 and items 1 and 7 are superseded (finding 6).
3. **confirmed** `docs/BUG-LOG.md` watch list still carries W-4 with "CLOSED 2026-10-02" in the row.
4. **confirmed** field notes 103–107 are out of sequence at `docs/INTERACTIVE-ARENA.md:2127-2143`.
5. **confirmed** `runner/seatd/backends.py:445-446 reset_mod_counter` is dead.
6. **confirmed** `ARENA_OAI_CTX` (`backends.py:133`) is undocumented and invisible to the knob census test; `ARENA_STOPS` and `ARENA_PACKAGE_CP_TXT` are read and documented nowhere.
7. **confirmed** `runner/seat_runner.py:1-12` docstring describes a plan ("lands in H3-H4") that shipped in August.
8. **confirmed** `tuning.json`'s note claims every non-operator number lives there; 96 do not (finding 7).
9. **confirmed** the raw purge of plan §10 did not run; 351.0 MB remains reachable (finding 1).
10. **plausible** the suite's `ResourceWarning: unclosed socket` comes from the scripted endpoint in `tests/test_backends.py:16-57`; harmless, but it is the only noise in a clean 744.
11. **hypothesis** September's `human_mulligans` DRAW-phase ordering question (`voice/events.py:572`) remains unverified; no archive shows a wrong hand count, so it is at worst dormant.

### Feature suggestions

Ranked by cost. **S (an hour each):** delete `reset_mod_counter`; drop the W-4 row; fix README:368; re-date and correct the limitations list; add `--exclude '/voice/joshua_lines.py'`; ship PATCH-NOTES v4.x only; `git gc --prune=now` once the reflog expires. **M (a day each):** `runner/control.py` for the shared poller and rotator; `tests/fakes.py`; a `seatd/tuning.json` and a 12-row banner; the field notes out of INTERACTIVE-ARENA.md; `docs/archive/` for the four pre-ship documents; `observe-play.py` onto the Project 1 list. **L (Ben's call plus a release):** the history rewrite with bundle and force-push; the stock eviction rule and its first pass (cards `-react` half, silent Joshua quotes, off-table commander triplets); ship-or-shelve for speculative plans and react hold.

### Observability and efficiency

`arena-hygiene.py` already prints "40 distinct spoken / 1561 available" per game (`20261006-203245-stop/hygiene.txt`) — the September suggestion landed. The missing step is cumulative: an `arena-hygiene.py --stock-census` over `logs/archive/` that lists ids unspoken in the last N games with their bytes (the 60-line aggregation behind finding 2) so the eviction list maintains itself instead of waiting for a review. The launch banner should end with one count — "1 of 31 settings changed from default" — so the knob table's irrelevance is visible at every launch. Candidate pressure is about 2.1 per spoken line (4,192 queued + 5,349 skipped + 901 dropped against 4,943 spoke); the governor, the dice and the no-repeat gate are cheap and the 16-game average of 275 lines per game is fine. The `_inbox_files` cache (`events.py:129-155`) ended the triple inbox glob; `_board_fp` now carries the ring `seq` (`events.py:1156`); the voice render cache is capped at 0 B. The one efficiency item still open is the 2.2 GB object store (finding 1).

### Questions for Ben

1. The raw history: rewrite and force-push the private remote (plan §10, bundle kept), do it at the next upstream sync, or accept 351 MB forever?
2. Is "never spoken in the last eighteen games" sufficient grounds to move a sub-library to the bucket — the colour chart excepted by your decision — starting with the combo `-react` half and the 31 silent Joshua quotes?
3. Speculative plans and react hold have been off in every archived game: a game with them on, or shelve the code, tests and spec?
4. The non-voice knobs (rotation, react effort, receipts, autostop): a `seatd/tuning.json` like the voice's, leaving about 12 operator rows?
5. May the field notes leave INTERACTIVE-ARENA.md for dated files, and PR-LOG, IMPLEMENTATION-PLAN, AGENT-SDK-SEATS and the turn-plans spec go to `docs/archive/`?
6. Should the package carry only the v4.x patch notes?

### Follow-up on the September report

Landed: (3) the 27 knobs — 36 → 5 plus `tuning.json`, `9c10a30a438`, and the `ARENA_VOICE_DUTY_HUMAN` doc mismatch retired with it; (5) the slow-seat scans share one cached inbox read (`events.py:129`), though `mutter` (8 s) and `slow_seats` (20 s) remain two line families by design; (7) the memory layer paid out — 131 deal rows, 61 struck, `grudge` 38 and `heads-up` 43 lines, `GRUDGE_EVERY` 3 → 2 (`events.py:67`); (8) dead code and stale prose — `RECENT_WEIGHT`, `if False else`, `PRIORITY["bark"]` gone, docstrings rewritten, the split done (`card_slug` still twice, `table.py:237`/`card_lines.py:63`, and `DEFAULT_TABLE` twice, `advisor_runner.py:46`/`table.py:158`); (10) the efficiency items — `_board_fp` on `seq`, the cache cap, the glob cache. Of the September bugs, 1, 2, 3, 4, 5 and 8 are fixed (`after_spoken` now marks the proposal reply `terminal` at `scheduler.py:510-512`); 6 was affirmed by Ben as intended; 7 is still unverified.

Still standing: (1) the raws left the tree but not the history (finding 1); (6) chain rows that never fire — 33 openers in 18 games; (9) the combo pairs, whose "revisit after five more games" is now overdue (finding 2).

Superseded by decision: (2) the colour-identity address lines, kept as the fallback for other people's decks; (4) the advisor bark tags, kept — the rider to trim the guide text was not taken up.

```json
{"lens": "Sweeper",
 "findings": [
  {"id": "S1", "title": "Raw takes deleted from the tree, not from history: 2,495 files, 351.0 MB reachable; .git 2.2 GB with a stray tmp_pack", "kind": "concern", "severity": "P1", "confidence": "confirmed", "area": "packaging", "effort": "L", "sources": ["git ls-tree d54ab30bd08^ -- runner/voice/stock/voices", "docs/reviews/2026-09-14-voicework2-hardening-plan.md:230", ".git/objects/pack/tmp_pack_7LjlU3"]},
  {"id": "S2", "title": "Half the voice stock never speaks: 1,932 of 4,329 files, 265.5 MB; combo pairs 64/74 silent, cards 68/87, Joshua root 31/66; colour chart 512 files 64.7 MB kept by decision", "kind": "concern", "severity": "P1", "confidence": "confirmed", "area": "voice", "effort": "L", "sources": ["runner/voice/stock/voices/*/{table,cards}/manifest.json", "runner/logs/archive/20260916-111916-stop..20261006-203245-stop/voice-0.jsonl", "runner/voice/table.py:219"]},
  {"id": "S3", "title": "53 ARENA_* knobs read, 22 ever set, one turned live in 18 games; three undocumented; banner 31 rows, README 30", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "scripts", "effort": "M", "sources": ["runner/logs/archive/*/launch-config.txt", "scripts/arena-play.sh:46", "packaging/build-light-package.sh:54", "runner/seatd/backends.py:133", "runner/tests/test_hardening.py:366"]},
  {"id": "S4", "title": "Backend path unused live since 2026-08-13 (453 + 339 test lines, 7 knobs); reset_mod_counter dead", "kind": "concern", "severity": "P3", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/seatd/backends.py:445", "runner/logs/archive/*/launch-config.txt"]},
  {"id": "S5", "title": "Control-file poller and session rotator duplicated between advisor and seat runner (~120 lines, divergent policies)", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "runner", "effort": "M", "sources": ["runner/advisor_runner.py:702", "runner/seatd/runner.py:185", "runner/advisor_runner.py:819", "runner/seatd/runner.py:1960"]},
  {"id": "S6", "title": "Docs outweigh runtime: 121.6 KB of field notes, stale 9/08 limitations, W-4 stale row, 42 KB of old patch notes shipped, PR-LOG dead since 8/02", "kind": "bug", "severity": "P2", "confidence": "confirmed", "area": "docs", "effort": "M", "sources": ["docs/INTERACTIVE-ARENA.md:315", "docs/INTERACTIVE-ARENA.md:508", "docs/BUG-LOG.md:21", "packaging/PATCH-NOTES.md:202", "packaging/build-light-package.sh:198", "docs/PR-LOG.md"]},
  {"id": "S7", "title": "Tuning has two homes: tuning.json 27 keys vs 96 module constants; six human-turn numbers; two patter clocks", "kind": "concern", "severity": "P3", "confidence": "confirmed", "area": "voice", "effort": "M", "sources": ["runner/voice/stock/voices/tuning.json", "runner/voice/scheduler.py:72", "runner/voice/scheduler.py:75", "runner/voice/scheduler.py:1186", "runner/voice/events.py:65"]},
  {"id": "S8", "title": "Speculative plans and react hold off in every archived game (~130 runtime + 145 test lines + spec); restart memory never exercised live but kept by decision", "kind": "question", "severity": "P3", "confidence": "confirmed", "area": "runner", "effort": "M", "sources": ["runner/seatd/runner.py:1408", "runner/seatd/rules.py:506", "runner/run_table.sh:39", "runner/voice_runner.py:514", "runner/logs/archive/*/launch-config.txt"]},
  {"id": "S9", "title": "Package ships joshua_lines.py (347 lines) whose only importers are excluded; observe-play.py is a Project 1 orphan; seat_runner.py docstring stale", "kind": "bug", "severity": "P3", "confidence": "confirmed", "area": "packaging", "effort": "S", "sources": ["packaging/build-light-package.sh:158", "runner/voice/joshua_lines.py", "scripts/observe-play.py:1", "runner/seat_runner.py:1"]},
  {"id": "S10", "title": "377 lines of copied test doubles (ten FakeBrain classes); doubles sit at boundaries, none tests the mock", "kind": "concern", "severity": "P3", "confidence": "confirmed", "area": "tests", "effort": "M", "sources": ["runner/tests/test_advisor_ask.py:19", "runner/tests/test_deals_seat.py:34", "runner/tests/test_backends.py:58", "runner/tests/test_barks_runtime.py:85"]},
  {"id": "S11", "title": "README says the audio is about 270 MB; the stock is 517 MiB and the same file says ~480 MB package", "kind": "bug", "severity": "P3", "confidence": "confirmed", "area": "docs", "effort": "S", "sources": ["packaging/README.md:368", "packaging/README.md:27"]},
  {"id": "S12", "title": "Advisor bark guide unchanged at 2,928/3,166 chars on 309 calls for 3.3% of spoken lines; only 12 of 32 ids ever fire", "kind": "observability", "severity": "P3", "confidence": "confirmed", "area": "advisor", "effort": "S", "sources": ["runner/advisor_runner.py:89", "runner/advisor_runner.py:155", "runner/logs/archive/*/advisor-0.jsonl"]},
  {"id": "S13", "title": "Cumulative stock census in arena-hygiene and a changed-from-default count in the banner", "kind": "feature", "severity": "P3", "confidence": "confirmed", "area": "scripts", "effort": "S", "sources": ["scripts/arena-hygiene.py:107", "scripts/arena-config.py:32", "runner/logs/archive/20261006-203245-stop/hygiene.txt"]}
 ],
 "metrics": [
  {"name": "voice runtime lines (voice_runner + voice/* + chains)", "value": 5300, "unit": "lines", "source": "wc -l runner/voice_runner.py runner/voice/*.py runner/chains.py"},
  {"name": "voice runtime growth since 2026-09-14", "value": 91, "unit": "percent", "source": "2,777 -> 5,300 lines"},
  {"name": "seatd/runner.py lines", "value": 2365, "unit": "lines", "source": "wc -l"},
  {"name": "advisor_runner.py lines", "value": 1749, "unit": "lines", "source": "wc -l"},
  {"name": "python tests", "value": 744, "unit": "tests", "source": "python3 -m unittest discover -s tests (54 s, OK)"},
  {"name": "ARENA_* knobs read by code", "value": 53, "unit": "knobs", "source": "census over runner/, scripts/, packaging/, src/"},
  {"name": "knobs set by any launcher or script", "value": 22, "unit": "knobs", "source": "census"},
  {"name": "knobs changed from default in 18 archived games", "value": 1, "unit": "knobs", "source": "runner/logs/archive/*/launch-config.txt (ARENA_CHATTER)"},
  {"name": "voice stock files", "value": 4336, "unit": "files", "source": "find runner/voice/stock -name '*.wav'"},
  {"name": "voice stock size", "value": 517, "unit": "MiB", "source": "du -sh runner/voice/stock"},
  {"name": "stock files never spoken in 18 games", "value": 1932, "unit": "files", "source": "manifests vs voice-0.jsonl"},
  {"name": "stock bytes never spoken in 18 games", "value": 265.5, "unit": "MB", "source": "manifests vs voice-0.jsonl"},
  {"name": "colour-chart address lines", "value": 64.7, "unit": "MB", "source": "address.json colors x table manifests, 512 files, 0 fires"},
  {"name": "lines spoken, 18 games", "value": 4943, "unit": "lines", "source": "voice-0.jsonl event=spoke"},
  {"name": "distinct ids spoken, 18 games", "value": 330, "unit": "ids", "source": "voice-0.jsonl"},
  {"name": "raw takes still in arena history", "value": 351.0, "unit": "MB", "source": "git ls-tree -r -l d54ab30bd08^"},
  {"name": ".git size", "value": 2.2, "unit": "GB", "source": "du -sh .git"},
  {"name": "chain openers that never queued a reply", "value": 33, "unit": "of 112", "source": "chains.json invites vs voice-0.jsonl queued"},
  {"name": "deal ledger rows, 18 games", "value": 131, "unit": "rows", "source": "deals.jsonl (61 struck)"},
  {"name": "advisor bark guide", "value": 2928, "unit": "chars", "source": "advisor_runner.bark_guide (advice); 3,166 recap"},
  {"name": "INTERACTIVE-ARENA.md field notes", "value": 121627, "unit": "bytes", "source": "awk over docs/INTERACTIVE-ARENA.md:508-2174"},
  {"name": "PATCH-NOTES pre-v4.2 bytes shipped", "value": 42004, "unit": "bytes", "source": "packaging/PATCH-NOTES.md:202-952"},
  {"name": "test double lines", "value": 377, "unit": "lines", "source": "ast over runner/tests/test_*.py"},
  {"name": "MailboxController methods with no call site", "value": 0, "unit": "methods", "source": "regex scan over src/main, src/test, forge-gui-desktop/forge/arena"}
 ],
 "september": {"landed": 5, "standing": 3, "superseded": 2}}
```


---

# 4. Grower

## Grower — Ben's asks landed in code faster than the games could hear them: of 32 asks I traced since 9/14, 14 are heard in a later archive, 12 landed with no game yet exercising them, 4 landed and were not heard, 2 did not land — and the one dial he keeps turning (rowdy) is pool-limited, not budget-limited.

### What I read and what shipped, as the Grower reads it

Eighty-eight `arena` commits (9/14 → 10/16), the BUG-LOG open table, watch list and per-game notes for games 49–65, the patch notes v4.2 → v4.3, the six plans in `docs/reviews/2026-09-16-*` and `-17-*`, and the eighteen in-scope archives. The brains made 11,528 decisions in those games (6,205 by the model, 19 punts, 0 tracebacks, 0 Java exceptions); the voices spoke 4,943 lines; the ledger holds 61 struck deals. Ben's stated targets have not moved: `scripts/arena-hygiene.py:67-68` still prints `TARGET_LINES_PER_MIN = 8.0`, `TARGET_ANCHORED = 0.60`, while `packaging/PATCH-NOTES.md` v4.2.1 re-bases the measured norm to "about 6 seat lines a minute at a human table, 7–8 all-AI". The product shifted under the code: Ben stopped handing his seat to the Executive after v4.2 shipped (seat-0 decisions 100 / 108 / 105 / 106 in games 50, 52, 53, 54; then 0, 0, 3, 0, 0 in 58, 59, 60, 62, 66; 45 in game 63 only across the sleeps). The human at seat 0 now plays every turn himself and talks to Joshua (19 typed asks, `advisor-0.jsonl` kind `ask`). That is the surface to iterate.

### Top findings

**1. Rowdy is pool-limited, and the 9/18 "tad more" was not heard.** At rowdy the eleven human/all-AI games measured 4.3–7.2 seat lines/min (median 6.0) and anchored 22–42 % against 8 / 60 %; `099550468c3` raised the goal .36 → .405 and the two rowdy human games since measured 5.2/min on Ben's turns and 6.5 on AI turns (game 63, sleeps excluded) and 5.3 (game 66). The budget is no longer the limiter: the top skip reason everywhere is `already said this turn` (game 60: 379 skips against 246 spoken lines; game 63: 301 against 530; game 55: 151), the silence floor reports "the pool is filler only" and sighs an atom instead (game 53: 49 such skips, each with `pool 12, anchored 0`), and procedural narration — the cheapest anchored line — is still rolled at p .30–.45 after being made budget-free (`scheduler.py:707`; game 64 lost 57 procedural lines to dice while 46 spoke; game 51 lost 17). The only game past 50 % anchored was game 64 at *normal* (51 %), because a lower dial buys fewer filler lines. Direction: stop turning the dial; grow the anchored pool (procedural p → 1.0 at rowdy, a sibling wording when the brain's `say` id was already said, more procedural ids), and re-state the target beside the measurement (finding 17).

**2. Sleep is the only red left on the human path, and the declined fix cost Ben a rated win.** Game 61's three proposals (`docs/BUG-LOG.md:192` (a)–(c): `caffeinate -i`, hygiene sleep detection, stall classification) were declined on 9/18. Game 63 (`20260926-003649-stop`): the observer tape has five wall-clock jumps (961 s at 19:22, 7,258 s at 19:40, 5,151 s at 21:41, 2,124 s at 23:07, 2,391 s at 23:43); all six punts, six lost windows and the one wedge sit on them (seat 0 under Executive at 19:38:28, 21:41:37, 22:41:55, 23:43:02, 00:22:01; seat 2 at 19:40:07), `ratings.out` says "VOID (recorded, not rated): seat 0 session wedged mid-game" (`runner/ratings.py:217-220`), and the voided record shows Ben won (`placementGroups [[0],…]`, 40 turns, Sheoldred's Sacrifice). BL-64 (10/03) then came from "an overnight sleep timeout" too. Direction: wrap the GUI JVM in `caffeinate -i` in `arena-play.sh`; hygiene prints "machine slept N× (Xh)" from the tape instead of `!! HYGIENE: punts 6`; ratings do not void a wedge whose wall clock jumped.

**3. The only v4.3 human game ran without Joshua's voice, and Ben muted it and left at turn 15.** `20261006-203245-stop/voice-0.log:5-7` (20:18:55): the hard-coded voice id (`runner/voice/joshua_lines.py:321`) returned HTTP 404 `voice_not_found`, no library voice named `Jousha-W.O.P.R.` (`runner/voice/stock/manifest.json:431`) was found, "live lines off — stock phrases only". Advice latency median 6.2 s (the slowest of the corpus; 2.7–3.5 s in games 49–54), 20 of 37 advice lines dropped or skipped (`voice disabled: N advisor record(s) not read` ×20, `no audio` ×9). Ben typed "You really suck!" to a seat at 20:27:37, muted at 20:27:58 (`voice-0.log:80`), and `autostop.out` reads "GUI JVM gone before game over" at 20:32:34, with Urza at 12 after Giada's swing. `hygiene.txt` says `OK` and `render failures 1`. There is no BUG-LOG note for this game. Direction: hygiene must shout when live lines are off with a key set; ask Ben what he heard (question 1); check the account's voice before the next game.

**4. The Advisor is now the product, and it is good where it is good and optimistic on deals.** Every typed ask was answered directly in 2.8–12.6 s (`advisor_runner.py:1172`) except two 60 s timeouts in game 58 (13:06:20, 13:10:22, empty answers, the `--timeout 60.0` default at line 1732) — the game Ben called "could be clearer". Catches worth keeping: the Drannith Magistrate block (game 59, 15:22:23, "The plan is right but it's blocked"), the 63 % land math (15:12:22), the Staff-loop correction when Ben called an illegal line (game 62, 13:56:55: "You're right that Selvala can't tap twice on her own"). Misses Joshua names himself: "I should have warned you a turn ahead about how Torbran and Purphoros stack" (game 62, `advisor-0.jsonl:715`, after Ben fell to 4), and "a deal with her was never going to protect you" (15:54:30) fourteen minutes after "It's a good deal" (15:40:58) blessed the alliance Giada broke for exact lethal at 15:54:00. The `danger` kind exists (25 records in the corpus) and fired once in game 62. Direction: every deal read carries one line on what the partner gains by breaking it at Ben's life total (the brains already reason this way: "Buy two turns", game 50; "last opponent at 7 dies to my fliers", game 53); a `danger` the turn before a visible lethal stack.

**5. Deals were honoured, but the deal life was small talk, and since 10/02 there are none.** 61 struck, 4 broken (all by attack; two by Giada in game 62, one the lethal betrayal of Ben's alliance), 31 lapsed on time — 93 % honoured. 49 of the 61 were voice-struck small-talk truces; the brains proposed 18 times in twelve games (about one offer per 25 table turns) and refused Ben 4 of 7. After `3a10dafdf9b` removed `deal` from the filler pool, games 65 and 66 hold zero ledger rows and zero brain offers (`PROPOSE_EVERY_TURNS = 4`, `rules.py:226`, is now moot). The offer pane was heard live in game 63: three seat→player offers answered in 8 s, 5 s and 5 s (18:59:26 accepted and kept to turn 33; 00:29:25 and 00:29:35 refused). Direction: measure three more games before touching anything; if the brains stay at zero, the deal feature is dormant and needs a cue at threat moments, not a shorter cooldown.

**6. The kill-shot family fired once and the game-over lock killed it.** Game 59 (`20260917-154748-stop/voice-0.jsonl`, 15:47:12–13): three seats vanish from one snapshot, `all-of-us` and `table-kill` are queued, then "dropped … game over" one second later (`scheduler.py:406-407`), and the table plays two generic `eliminated` lines, `win`, `strange-game`, `game-over-gg`. The family has never been heard. Same shape as BL-50's September drops. Direction: the lock must let the exits-first block (`events.py:1169`) and a queued kill-shot through before it closes.

**7. The brains' own line is heard 42 % of the time.** 719 `source: brain` records: 186 spoke, 250 skipped, 255 queued, 28 noted. Skips: `already said this turn` 72, the DEAL answer already spoke 33 (correct dedupe), seat guard 13, stale intent 12+ (game 59 t15: 50). The most agentic channel on the table is mostly silence. Direction: see finding 1 — fall to a sibling wording, not to nothing.

**8. The loop turn is the human's longest wait, and the table now talks through it.** Game 59 t15: 25.7 min, 511 decisions, 598 s of model time (385 cycle-answered); game 60 t18: 10.4 min, 1,084 decisions; game 55 t18: 10.2 min, 875. The engine pass, not the model, is the clock. BL-53 landed and was heard: 5.1–6.2 seat lines/min inside those turns. Direction: this is the parked snappiness item; measure engine pass cost before any runner work.

**9. Urza wins 6 of 15 decided games; Ben 2 of 10 (one with Executive playing from turn 13, one voided).** Ben's own words name him: "Uhoh I thnk we just lost to Urza" (59), "urza is having a cracked start" (60), "Oh christ, Urza's Sphinx" (62); game 59 ended in a one-turn table kill at 68 life, game 60 in 50 to Player One. Direction: a question (below), not a patch.

**10. The silences moved to Ben's turn.** Game 60: 14 of 17 gaps over 24 s on his turn; game 62: 95 of 109 (Ben played slowly while working); human-turn pace 2.0–3.8/min at rowdy against 3.4–8.4 on AI turns (`duty_human: 0.6`, `tuning.json:11`). Heckles fill it (BL-54 heard: 18 in games 60 and 63, `waiting-on-you` the third most-spoken id in game 60). His turns were 58 % of game 60's clock and 69 % of game 62's.

### Concerns

Model latency median drifted 1.6–2.7 s (games 49–62) → 3.6 s / p90 7.0 s in game 66 (79 calls, after the sync and the unlogged alias move to `claude-opus-5-5`, BL-59); one small game, but it is the human's wait. Hygiene's `advisor: … skipped 160` (game 59) reads like dropped advice; the records are un-advised `PRIORITY` windows. Convoke planning scans (`STOCK-SURFACE chooseCardsForConvokeOrImprovise`: 413 in game 60, 81 in 57 and 61, 65 in 63) are the one stock surface still growing and appear nowhere in `hygiene.txt`. Exact-take repeats are solved (1–8 % within five minutes, game 45 was 64 %); the new repetition is `agree`/`disagree`/`laugh` as the top ids of games 53–63.

### Bugs and corrections

- Kill-shot family dropped by the game-over lock (game 59, 15:47:13) — **confirmed**.
- Joshua's voice id not found, live lines off for all of game 66; no library voice by the stored name — **confirmed event**; cause (voice removed or renamed in the account) — **hypothesis**.
- Two 60 s ask timeouts with empty answers (game 58, 13:06:20, 13:10:22) — **confirmed**; the panel line says "ask again", nothing retries.
- Game 63 voided on a sleep wedge; hygiene reports it as six punts — **confirmed**, by design (W-3, `ratings.py:217`); correction proposed in finding 2.
- The TERMS line ("One round.") was heard once: game 63 (launched 18:10, between `3f0439d7e71` 17:57 and `00e246b515e` 18:22) skipped 7 of 9 on the seat guard; game 64 lost 2 of 3 to `dice (chain, p=0.15)` and one expired, before `3a10dafdf9b` made it state — **confirmed**, closed by 10/02, unobserved since.
- Joshua blessed the game-62 alliance that was broken for lethal — **plausible** as a quality defect, not a code bug.
- Human-turn voice pace at rowdy sits at the 0.6 multiplier (2.0–3.8/min) — **confirmed**, by design (Ben, game 44); the question is whether the rule still holds.

### Feature suggestions (ranked by cost)

S — `caffeinate -i` around the GUI JVM; hygiene "machine slept"; ratings sleep-aware. S — procedural p 1.0 at rowdy; brain `say` falls to a sibling wording. S — hygiene shouts on live-lines-off. M — deal read carries the partner's break incentive; `danger` the turn before lethal. M — kill-shot through the lock. L — a roster/difficulty choice at launch (Urza's 40 %).

### Observability and efficiency

`hygiene.txt` should print: STOCK-SURFACE counts by surface (`GUI_SIGNALS`, `arena-hygiene.py:145`, has none); live-lines state and the voice id lookup result; advice latency median and the ask count (I computed 2.7–6.2 s); "advised N of M windows" instead of `skipped`; the concrete model id (BL-59); a sleep line from the tape. Game 66 needs its BUG-LOG note. Efficiency: model time is 43–85 % of wall in brisk games (game 57: 85 %, game 64: 84 %) and 8–26 % in Ben's long ones; the engine pass during loops is the next cost to measure.

### Questions for Ben

1. Game 66: what did you hear before muting at 20:27:58 and closing at 20:32? Was Joshua's voice removed from the account?
2. Is 8 lines/min at 60 % anchored still the target hygiene should print, or is "rowdy ≈ 6" (the README) the accepted pace?
3. Your turns are now half to two-thirds of the clock; does "minimal on my turn" still hold, or should the table fill your idle minutes beyond heckles?
4. Urza wins 40 % of decided games and twice ended one in a single turn; is that the table you want, or should the roster rotate?
5. Will you take the `caffeinate` fix now that it voided your own win?

### Follow-up on the September report

Landed (12): governor as a mean (`c2d24c52c25`); floor pool with `pool`/`picked`/`anchored` fields; certain answers (game 49: every question answered); restart memory (`264fe3a6497`, unexercised: 0 restarts in eighteen games); second wordings (repeats 64 % → 1–8 %); brain-declared loops (loop lines in 49, 52, 56, 57, 60, 62, 64, 65); guard by class; Executive's turn treated as an AI turn (games 50–54: 4.3–6.2/min on seat 0's turns with Executive on vs 2.2–4.6 without); the opening heckle (BL-54, heard from game 51); the observability asks (targets and gaps printed, `turn`/`active` on every record); BL-50's vanish rule (game 49's three deaths); recency replay. Standing (3): the density target is unmet for a new reason (the pool, finding 1); procedural narration still diced; the kill-shot now dies to the lock (finding 6). Superseded (2): the "stacked levers" concern — 36 knobs became `tuning.json`; the 8-lines/min question — the README re-based to measured pace without a decision.

Verified by running: `git log 1b99b0d56d2..HEAD -- forge-arena`, `git log -1 --format=%ci` on the 9/25 commits, my scratchpad `grower_measure.py` over the eighteen archives (`game.jsonl`, `voice-0.jsonl`, `deals.jsonl`, `advisor-0.jsonl`, `events.jsonl`, `.rated`/`.voided`, `gui.out`), ad-hoc Python over the observer tape of game 63 and the voice/advisor records of games 58, 59, 62, 64, 66, and `grep`/`sed` on `arena-hygiene.py`, `scheduler.py`, `events.py`, `advisor_runner.py`, `rules.py`, `ratings.py`, `tuning.json`, `joshua_lines.py`, `manifest.json`, `BUG-LOG.md`, `PATCH-NOTES.md`, the plans and each archive's `hygiene.txt`, `launch-config.txt`, `autostop.out`, `ratings.out`.

```json
{"lens": "Grower",
 "findings": [
  {"id": "G1", "title": "Rowdy is pool-limited; the 9/18 'tad more' was not heard", "kind": "concern", "severity": "P1", "confidence": "confirmed", "area": "voice", "effort": "M", "sources": ["scripts/arena-hygiene.py:67", "runner/voice/scheduler.py:707", "20260917-200618-stop", "20260926-003649-stop", "20261006-203245-stop"]},
  {"id": "G2", "title": "Sleep punts voided Ben's win in game 63; declined caffeinate fix bit twice more", "kind": "bug", "severity": "P1", "confidence": "confirmed", "area": "scripts", "effort": "S", "sources": ["20260926-003649-stop", "runner/ratings.py:217", "docs/BUG-LOG.md:192"]},
  {"id": "G3", "title": "Game 66 ran without Joshua's voice (404 on the stored voice id); Ben muted and quit at t15; hygiene said OK", "kind": "bug", "severity": "P1", "confidence": "confirmed", "area": "voice", "effort": "S", "sources": ["20261006-203245-stop", "runner/voice/joshua_lines.py:321", "runner/voice/stock/manifest.json:431"]},
  {"id": "G4", "title": "The Advisor is the product now; its deal reads are optimistic", "kind": "concern", "severity": "P2", "confidence": "plausible", "area": "advisor", "effort": "M", "sources": ["runner/advisor_runner.py:1172", "20260918-160124-stop", "20260917-154748-stop"]},
  {"id": "G5", "title": "Deals honoured 93 % but 80 % were small talk; zero deals since the 10/02 filler removal", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/seatd/rules.py:226", "20261002-131143-stop", "20261002-160838-stop", "20261006-203245-stop"]},
  {"id": "G6", "title": "Kill-shot family fired once and was dropped by the game-over lock", "kind": "bug", "severity": "P2", "confidence": "confirmed", "area": "voice", "effort": "M", "sources": ["runner/voice/scheduler.py:406", "20260917-154748-stop"]},
  {"id": "G7", "title": "Brains' own say lines heard 42 % of the time", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "voice", "effort": "S", "sources": ["runner/voice/scheduler.py:166", "20260917-154748-stop"]},
  {"id": "G8", "title": "Loop turns are the human's longest waits (10-26 min); engine pass is the clock", "kind": "concern", "severity": "P3", "confidence": "confirmed", "area": "runner", "effort": "L", "sources": ["20260917-154748-stop", "20260917-200618-stop", "20260916-200023-stop"]},
  {"id": "G9", "title": "Urza wins 6 of 15 decided games; Ben 2 of 10", "kind": "question", "severity": "P3", "confidence": "confirmed", "area": "brain-brief", "effort": "L", "sources": ["20260917-154748-stop", "20260917-200618-stop", "20260918-160124-stop"]},
  {"id": "G10", "title": "Long silences now sit on the human's turn; is 'minimal on my turn' still the rule", "kind": "question", "severity": "P3", "confidence": "confirmed", "area": "voice", "effort": "S", "sources": ["runner/voice/stock/voices/tuning.json:11", "20260917-200618-stop", "20260918-160124-stop"]},
  {"id": "G11", "title": "Model latency median 3.6 s in game 66 vs 1.6-2.7 s before", "kind": "concern", "severity": "P3", "confidence": "hypothesis", "area": "runner", "effort": "S", "sources": ["20261006-203245-stop", "docs/BUG-LOG.md:15"]},
  {"id": "G12", "title": "Two 60 s ask timeouts with empty answers in game 58", "kind": "bug", "severity": "P3", "confidence": "confirmed", "area": "advisor", "effort": "S", "sources": ["runner/advisor_runner.py:1732", "20260917-132142-stop"]},
  {"id": "G13", "title": "Hygiene is blind to live-lines-off, machine sleep, STOCK-SURFACE counts, advice latency; 'skipped' mislabels", "kind": "observability", "severity": "P2", "confidence": "confirmed", "area": "scripts", "effort": "S", "sources": ["scripts/arena-hygiene.py:145", "20261006-203245-stop", "20260926-003649-stop"]},
  {"id": "G14", "title": "No BUG-LOG note for game 66, the only v4.3 human game", "kind": "observability", "severity": "P3", "confidence": "confirmed", "area": "docs", "effort": "S", "sources": ["docs/BUG-LOG.md:197", "20261006-203245-stop"]},
  {"id": "G15", "title": "TERMS family ('the seats say how long') heard once in the corpus", "kind": "concern", "severity": "P3", "confidence": "confirmed", "area": "voice", "effort": "S", "sources": ["20260926-003649-stop", "20261002-131143-stop"]},
  {"id": "G16", "title": "Hygiene prints target 8/60 while README states rowdy ≈ 6 measured", "kind": "question", "severity": "P3", "confidence": "confirmed", "area": "docs", "effort": "S", "sources": ["scripts/arena-hygiene.py:67", "packaging/PATCH-NOTES.md:49"]}
 ],
 "metrics": [
  {"name": "seat_lines_per_min", "value": 4.4, "unit": "lines/min", "source": "20260916-111916-stop"},
  {"name": "seat_lines_per_min", "value": 6.7, "unit": "lines/min", "source": "20260916-132428-stop"},
  {"name": "seat_lines_per_min", "value": 7.2, "unit": "lines/min", "source": "20260916-161902-stop"},
  {"name": "seat_lines_per_min", "value": 6.0, "unit": "lines/min", "source": "20260916-164732-stop"},
  {"name": "seat_lines_per_min", "value": 6.7, "unit": "lines/min", "source": "20260916-181902-stop"},
  {"name": "seat_lines_per_min", "value": 6.5, "unit": "lines/min", "source": "20260916-192313-stop"},
  {"name": "seat_lines_per_min", "value": 6.1, "unit": "lines/min", "source": "20260916-200023-stop"},
  {"name": "seat_lines_per_min", "value": 8.3, "unit": "lines/min", "source": "20260916-223014-stop"},
  {"name": "seat_lines_per_min", "value": 6.9, "unit": "lines/min", "source": "20260917-114013-stop"},
  {"name": "seat_lines_per_min", "value": 6.0, "unit": "lines/min", "source": "20260917-132142-stop"},
  {"name": "seat_lines_per_min", "value": 4.8, "unit": "lines/min", "source": "20260917-154748-stop"},
  {"name": "seat_lines_per_min", "value": 4.3, "unit": "lines/min", "source": "20260917-200618-stop"},
  {"name": "seat_lines_per_min", "value": 0.3, "unit": "lines/min (muted)", "source": "20260918-093644-stop"},
  {"name": "seat_lines_per_min", "value": 2.5, "unit": "lines/min (normal)", "source": "20260918-160124-stop"},
  {"name": "seat_lines_per_min", "value": 5.9, "unit": "lines/min (awake minutes)", "source": "20260926-003649-stop"},
  {"name": "seat_lines_per_min", "value": 5.4, "unit": "lines/min (normal)", "source": "20261002-131143-stop"},
  {"name": "seat_lines_per_min", "value": 5.6, "unit": "lines/min (normal)", "source": "20261002-160838-stop"},
  {"name": "seat_lines_per_min", "value": 5.3, "unit": "lines/min", "source": "20261006-203245-stop"},
  {"name": "anchored_share", "value": 35, "unit": "%", "source": "20260916-111916-stop"},
  {"name": "anchored_share", "value": 32, "unit": "%", "source": "20260916-132428-stop"},
  {"name": "anchored_share", "value": 42, "unit": "%", "source": "20260916-161902-stop"},
  {"name": "anchored_share", "value": 33, "unit": "%", "source": "20260916-164732-stop"},
  {"name": "anchored_share", "value": 32, "unit": "%", "source": "20260916-181902-stop"},
  {"name": "anchored_share", "value": 37, "unit": "%", "source": "20260916-192313-stop"},
  {"name": "anchored_share", "value": 22, "unit": "%", "source": "20260916-200023-stop"},
  {"name": "anchored_share", "value": 35, "unit": "%", "source": "20260916-223014-stop"},
  {"name": "anchored_share", "value": 29, "unit": "%", "source": "20260917-114013-stop"},
  {"name": "anchored_share", "value": 31, "unit": "%", "source": "20260917-132142-stop"},
  {"name": "anchored_share", "value": 26, "unit": "%", "source": "20260917-154748-stop"},
  {"name": "anchored_share", "value": 28, "unit": "%", "source": "20260917-200618-stop"},
  {"name": "anchored_share", "value": 42, "unit": "%", "source": "20260918-093644-stop"},
  {"name": "anchored_share", "value": 13, "unit": "%", "source": "20260918-160124-stop"},
  {"name": "anchored_share", "value": 25, "unit": "%", "source": "20260926-003649-stop"},
  {"name": "anchored_share", "value": 51, "unit": "%", "source": "20261002-131143-stop"},
  {"name": "anchored_share", "value": 42, "unit": "%", "source": "20261002-160838-stop"},
  {"name": "anchored_share", "value": 42, "unit": "%", "source": "20261006-203245-stop"},
  {"name": "model_latency_median", "value": 1.7, "unit": "s", "source": "20260916-111916-stop"},
  {"name": "model_latency_median", "value": 2.0, "unit": "s", "source": "20260916-132428-stop"},
  {"name": "model_latency_median", "value": 2.2, "unit": "s", "source": "20260916-161902-stop"},
  {"name": "model_latency_median", "value": 1.9, "unit": "s", "source": "20260916-164732-stop"},
  {"name": "model_latency_median", "value": 2.0, "unit": "s", "source": "20260916-181902-stop"},
  {"name": "model_latency_median", "value": 1.9, "unit": "s", "source": "20260916-192313-stop"},
  {"name": "model_latency_median", "value": 2.1, "unit": "s", "source": "20260916-200023-stop"},
  {"name": "model_latency_median", "value": 2.2, "unit": "s", "source": "20260916-223014-stop"},
  {"name": "model_latency_median", "value": 2.7, "unit": "s", "source": "20260917-114013-stop"},
  {"name": "model_latency_median", "value": 2.3, "unit": "s", "source": "20260917-132142-stop"},
  {"name": "model_latency_median", "value": 2.5, "unit": "s", "source": "20260917-154748-stop"},
  {"name": "model_latency_median", "value": 1.6, "unit": "s", "source": "20260917-200618-stop"},
  {"name": "model_latency_median", "value": 2.2, "unit": "s", "source": "20260918-093644-stop"},
  {"name": "model_latency_median", "value": 2.4, "unit": "s", "source": "20260918-160124-stop"},
  {"name": "model_latency_median", "value": 2.2, "unit": "s", "source": "20260926-003649-stop"},
  {"name": "model_latency_median", "value": 2.5, "unit": "s", "source": "20261002-131143-stop"},
  {"name": "model_latency_median", "value": 2.1, "unit": "s", "source": "20261002-160838-stop"},
  {"name": "model_latency_median", "value": 3.6, "unit": "s", "source": "20261006-203245-stop"},
  {"name": "decisions", "value": 391, "unit": "count", "source": "20260916-111916-stop"},
  {"name": "decisions", "value": 402, "unit": "count", "source": "20260916-132428-stop"},
  {"name": "decisions", "value": 229, "unit": "count", "source": "20260916-161902-stop"},
  {"name": "decisions", "value": 898, "unit": "count", "source": "20260916-164732-stop"},
  {"name": "decisions", "value": 557, "unit": "count", "source": "20260916-181902-stop"},
  {"name": "decisions", "value": 638, "unit": "count", "source": "20260916-192313-stop"},
  {"name": "decisions", "value": 1258, "unit": "count", "source": "20260916-200023-stop"},
  {"name": "decisions", "value": 528, "unit": "count", "source": "20260916-223014-stop"},
  {"name": "decisions", "value": 652, "unit": "count", "source": "20260917-114013-stop"},
  {"name": "decisions", "value": 427, "unit": "count", "source": "20260917-132142-stop"},
  {"name": "decisions", "value": 645, "unit": "count", "source": "20260917-154748-stop"},
  {"name": "decisions", "value": 1423, "unit": "count", "source": "20260917-200618-stop"},
  {"name": "decisions", "value": 545, "unit": "count", "source": "20260918-093644-stop"},
  {"name": "decisions", "value": 375, "unit": "count", "source": "20260918-160124-stop"},
  {"name": "decisions", "value": 714, "unit": "count", "source": "20260926-003649-stop"},
  {"name": "decisions", "value": 749, "unit": "count", "source": "20261002-131143-stop"},
  {"name": "decisions", "value": 885, "unit": "count", "source": "20261002-160838-stop"},
  {"name": "decisions", "value": 212, "unit": "count", "source": "20261006-203245-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260916-111916-stop"},
  {"name": "punts", "value": 1, "unit": "count", "source": "20260916-132428-stop"},
  {"name": "punts", "value": 1, "unit": "count", "source": "20260916-161902-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260916-164732-stop"},
  {"name": "punts", "value": 2, "unit": "count", "source": "20260916-181902-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260916-192313-stop"},
  {"name": "punts", "value": 1, "unit": "count", "source": "20260916-200023-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260916-223014-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260917-114013-stop"},
  {"name": "punts", "value": 2, "unit": "count", "source": "20260917-132142-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260917-154748-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260917-200618-stop"},
  {"name": "punts", "value": 6, "unit": "count (all on sleep boundaries)", "source": "20260918-093644-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20260918-160124-stop"},
  {"name": "punts", "value": 6, "unit": "count (all on sleep boundaries)", "source": "20260926-003649-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20261002-131143-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20261002-160838-stop"},
  {"name": "punts", "value": 0, "unit": "count", "source": "20261006-203245-stop"},
  {"name": "deals_struck", "value": 0, "unit": "count", "source": "20260916-111916-stop"},
  {"name": "deals_struck", "value": 3, "unit": "count", "source": "20260916-132428-stop"},
  {"name": "deals_struck", "value": 3, "unit": "count", "source": "20260916-161902-stop"},
  {"name": "deals_struck", "value": 2, "unit": "count", "source": "20260916-164732-stop"},
  {"name": "deals_struck", "value": 2, "unit": "count", "source": "20260916-181902-stop"},
  {"name": "deals_struck", "value": 6, "unit": "count", "source": "20260916-192313-stop"},
  {"name": "deals_struck", "value": 2, "unit": "count", "source": "20260916-200023-stop"},
  {"name": "deals_struck", "value": 1, "unit": "count", "source": "20260916-223014-stop"},
  {"name": "deals_struck", "value": 5, "unit": "count", "source": "20260917-114013-stop"},
  {"name": "deals_struck", "value": 4, "unit": "count", "source": "20260917-132142-stop"},
  {"name": "deals_struck", "value": 6, "unit": "count", "source": "20260917-154748-stop"},
  {"name": "deals_struck", "value": 4, "unit": "count", "source": "20260917-200618-stop"},
  {"name": "deals_struck", "value": 0, "unit": "count", "source": "20260918-093644-stop"},
  {"name": "deals_struck", "value": 11, "unit": "count", "source": "20260918-160124-stop"},
  {"name": "deals_struck", "value": 9, "unit": "count", "source": "20260926-003649-stop"},
  {"name": "deals_struck", "value": 3, "unit": "count", "source": "20261002-131143-stop"},
  {"name": "deals_struck", "value": 0, "unit": "count", "source": "20261002-160838-stop"},
  {"name": "deals_struck", "value": 0, "unit": "count", "source": "20261006-203245-stop"},
  {"name": "deals_broken", "value": 1, "unit": "count", "source": "20260916-132428-stop"},
  {"name": "deals_broken", "value": 2, "unit": "count", "source": "20260918-160124-stop"},
  {"name": "deals_broken", "value": 1, "unit": "count", "source": "20261002-131143-stop"},
  {"name": "brain_offers", "value": 18, "unit": "count across games 53-64", "source": "20261002-131143-stop"},
  {"name": "offer_answer_latency_median", "value": 12, "unit": "s", "source": "20260926-003649-stop"},
  {"name": "executive_seat0_decisions", "value": 100, "unit": "count", "source": "20260916-132428-stop"},
  {"name": "executive_seat0_decisions", "value": 1, "unit": "count", "source": "20260916-161902-stop"},
  {"name": "executive_seat0_decisions", "value": 108, "unit": "count", "source": "20260916-164732-stop"},
  {"name": "executive_seat0_decisions", "value": 105, "unit": "count", "source": "20260916-181902-stop"},
  {"name": "executive_seat0_decisions", "value": 106, "unit": "count", "source": "20260916-192313-stop"},
  {"name": "executive_seat0_decisions", "value": 0, "unit": "count", "source": "20260917-132142-stop"},
  {"name": "executive_seat0_decisions", "value": 0, "unit": "count", "source": "20260917-154748-stop"},
  {"name": "executive_seat0_decisions", "value": 3, "unit": "count", "source": "20260917-200618-stop"},
  {"name": "executive_seat0_decisions", "value": 0, "unit": "count", "source": "20260918-160124-stop"},
  {"name": "executive_seat0_decisions", "value": 45, "unit": "count", "source": "20260926-003649-stop"},
  {"name": "executive_seat0_decisions", "value": 0, "unit": "count", "source": "20261006-203245-stop"},
  {"name": "advice_lines_spoken", "value": 1, "unit": "count", "source": "20260916-111916-stop"},
  {"name": "advice_lines_spoken", "value": 3, "unit": "count", "source": "20260916-132428-stop"},
  {"name": "advice_lines_spoken", "value": 2, "unit": "count", "source": "20260916-161902-stop"},
  {"name": "advice_lines_spoken", "value": 0, "unit": "count (no key)", "source": "20260916-164732-stop"},
  {"name": "advice_lines_spoken", "value": 2, "unit": "count", "source": "20260916-181902-stop"},
  {"name": "advice_lines_spoken", "value": 7, "unit": "count", "source": "20260916-192313-stop"},
  {"name": "advice_lines_spoken", "value": 4, "unit": "count", "source": "20260917-132142-stop"},
  {"name": "advice_lines_spoken", "value": 18, "unit": "count", "source": "20260917-154748-stop"},
  {"name": "advice_lines_spoken", "value": 21, "unit": "count", "source": "20260917-200618-stop"},
  {"name": "advice_lines_spoken", "value": 19, "unit": "count", "source": "20260918-160124-stop"},
  {"name": "advice_lines_spoken", "value": 43, "unit": "count", "source": "20260926-003649-stop"},
  {"name": "advice_lines_spoken", "value": 0, "unit": "count (voice 404)", "source": "20261006-203245-stop"},
  {"name": "advice_latency_median", "value": 6.2, "unit": "s", "source": "20261006-203245-stop"},
  {"name": "advice_latency_median", "value": 5.0, "unit": "s", "source": "20260917-132142-stop"},
  {"name": "advice_latency_median", "value": 3.2, "unit": "s", "source": "20260926-003649-stop"},
  {"name": "typed_asks", "value": 19, "unit": "count across human games", "source": "20260918-160124-stop"},
  {"name": "human_placement", "value": 3, "unit": "place of 4", "source": "20260916-111916-stop"},
  {"name": "human_placement", "value": 1, "unit": "place of 4 (Executive from t13)", "source": "20260916-132428-stop"},
  {"name": "human_placement", "value": 3, "unit": "place of 4", "source": "20260916-161902-stop"},
  {"name": "human_placement", "value": 2, "unit": "place of 4", "source": "20260916-164732-stop"},
  {"name": "human_placement", "value": 3, "unit": "place of 4", "source": "20260916-181902-stop"},
  {"name": "human_placement", "value": 3, "unit": "place of 4", "source": "20260917-132142-stop"},
  {"name": "human_placement", "value": 2, "unit": "place of 4", "source": "20260917-154748-stop"},
  {"name": "human_placement", "value": 2, "unit": "place of 4", "source": "20260917-200618-stop"},
  {"name": "human_placement", "value": 3, "unit": "place of 4", "source": "20260918-160124-stop"},
  {"name": "human_placement", "value": 1, "unit": "place of 4 (voided)", "source": "20260926-003649-stop"},
  {"name": "urza_wins", "value": 6, "unit": "of 15 decided games", "source": "20261002-160838-stop"},
  {"name": "exact_take_repeats_5min", "value": 5, "unit": "%", "source": "20260916-111916-stop"},
  {"name": "exact_take_repeats_5min", "value": 8, "unit": "%", "source": "20260916-132428-stop"},
  {"name": "exact_take_repeats_5min", "value": 7, "unit": "%", "source": "20260916-161902-stop"},
  {"name": "exact_take_repeats_5min", "value": 4, "unit": "%", "source": "20260916-164732-stop"},
  {"name": "exact_take_repeats_5min", "value": 6, "unit": "%", "source": "20260916-181902-stop"},
  {"name": "exact_take_repeats_5min", "value": 4, "unit": "%", "source": "20260916-192313-stop"},
  {"name": "exact_take_repeats_5min", "value": 5, "unit": "%", "source": "20260916-200023-stop"},
  {"name": "exact_take_repeats_5min", "value": 7, "unit": "%", "source": "20260916-223014-stop"},
  {"name": "exact_take_repeats_5min", "value": 3, "unit": "%", "source": "20260917-114013-stop"},
  {"name": "exact_take_repeats_5min", "value": 3, "unit": "%", "source": "20260917-132142-stop"},
  {"name": "exact_take_repeats_5min", "value": 3, "unit": "%", "source": "20260917-154748-stop"},
  {"name": "exact_take_repeats_5min", "value": 4, "unit": "%", "source": "20260917-200618-stop"},
  {"name": "exact_take_repeats_5min", "value": 1, "unit": "%", "source": "20260918-160124-stop"},
  {"name": "exact_take_repeats_5min", "value": 4, "unit": "%", "source": "20260926-003649-stop"},
  {"name": "exact_take_repeats_5min", "value": 7, "unit": "%", "source": "20261002-131143-stop"},
  {"name": "exact_take_repeats_5min", "value": 5, "unit": "%", "source": "20261002-160838-stop"},
  {"name": "exact_take_repeats_5min", "value": 2, "unit": "%", "source": "20261006-203245-stop"},
  {"name": "model_time_share_of_wall", "value": 52, "unit": "%", "source": "20260916-111916-stop"},
  {"name": "model_time_share_of_wall", "value": 73, "unit": "%", "source": "20260916-132428-stop"},
  {"name": "model_time_share_of_wall", "value": 57, "unit": "%", "source": "20260916-161902-stop"},
  {"name": "model_time_share_of_wall", "value": 65, "unit": "%", "source": "20260916-164732-stop"},
  {"name": "model_time_share_of_wall", "value": 57, "unit": "%", "source": "20260916-181902-stop"},
  {"name": "model_time_share_of_wall", "value": 65, "unit": "%", "source": "20260916-192313-stop"},
  {"name": "model_time_share_of_wall", "value": 63, "unit": "%", "source": "20260916-200023-stop"},
  {"name": "model_time_share_of_wall", "value": 73, "unit": "%", "source": "20260916-223014-stop"},
  {"name": "model_time_share_of_wall", "value": 85, "unit": "%", "source": "20260917-114013-stop"},
  {"name": "model_time_share_of_wall", "value": 51, "unit": "%", "source": "20260917-132142-stop"},
  {"name": "model_time_share_of_wall", "value": 43, "unit": "%", "source": "20260917-154748-stop"},
  {"name": "model_time_share_of_wall", "value": 26, "unit": "%", "source": "20260917-200618-stop"},
  {"name": "model_time_share_of_wall", "value": 12, "unit": "%", "source": "20260918-160124-stop"},
  {"name": "model_time_share_of_wall", "value": 84, "unit": "%", "source": "20261002-131143-stop"},
  {"name": "model_time_share_of_wall", "value": 57, "unit": "%", "source": "20261002-160838-stop"},
  {"name": "model_time_share_of_wall", "value": 45, "unit": "%", "source": "20261006-203245-stop"},
  {"name": "longest_turn_wall", "value": 1542, "unit": "s (t15, 511 decisions)", "source": "20260917-154748-stop"},
  {"name": "longest_turn_wall", "value": 622, "unit": "s (t18, 1084 decisions)", "source": "20260917-200618-stop"},
  {"name": "longest_turn_wall", "value": 612, "unit": "s (t18, 875 decisions)", "source": "20260916-200023-stop"},
  {"name": "lines_per_min_inside_loop_turn", "value": 5.1, "unit": "lines/min (t15)", "source": "20260917-154748-stop"},
  {"name": "lines_per_min_inside_loop_turn", "value": 5.5, "unit": "lines/min (t18)", "source": "20260917-200618-stop"},
  {"name": "heckle_lines", "value": 2, "unit": "count", "source": "20260916-161902-stop"},
  {"name": "heckle_lines", "value": 6, "unit": "count", "source": "20260917-132142-stop"},
  {"name": "heckle_lines", "value": 18, "unit": "count", "source": "20260917-200618-stop"},
  {"name": "heckle_lines", "value": 11, "unit": "count", "source": "20260918-160124-stop"},
  {"name": "heckle_lines", "value": 18, "unit": "count", "source": "20260926-003649-stop"},
  {"name": "heckle_lines", "value": 3, "unit": "count", "source": "20261006-203245-stop"},
  {"name": "long_gaps_on_human_turn", "value": 14, "unit": "of 17 gaps over 24 s", "source": "20260917-200618-stop"},
  {"name": "long_gaps_on_human_turn", "value": 95, "unit": "of 109 gaps over 24 s", "source": "20260918-160124-stop"},
  {"name": "human_turn_lines_per_min", "value": 3.4, "unit": "lines/min vs 5.3 on AI turns", "source": "20260917-200618-stop"},
  {"name": "human_turn_lines_per_min", "value": 5.2, "unit": "lines/min vs 6.5 on AI turns", "source": "20260926-003649-stop"},
  {"name": "brain_say_spoken_share", "value": 42, "unit": "% (186 spoke / 250 skipped)", "source": "20260917-154748-stop"},
  {"name": "already_said_this_turn_skips", "value": 379, "unit": "count vs 246 spoken", "source": "20260917-200618-stop"},
  {"name": "already_said_this_turn_skips", "value": 301, "unit": "count vs 530 spoken", "source": "20260926-003649-stop"},
  {"name": "procedural_lines_lost_to_dice", "value": 57, "unit": "count vs 46 spoken", "source": "20261002-131143-stop"},
  {"name": "kill_shot_lines_spoken", "value": 0, "unit": "count (2 queued, dropped game over)", "source": "20260917-154748-stop"},
  {"name": "terms_lines_spoken", "value": 1, "unit": "of 9 struck (7 seat-guard skips)", "source": "20260926-003649-stop"},
  {"name": "terms_lines_spoken", "value": 0, "unit": "of 3 struck (dice p=0.15)", "source": "20261002-131143-stop"},
  {"name": "stock_surface_consultations", "value": 416, "unit": "count (413 convoke scans)", "source": "20260917-200618-stop"},
  {"name": "stock_surface_consultations", "value": 99, "unit": "count", "source": "20260917-114013-stop"},
  {"name": "stock_surface_consultations", "value": 72, "unit": "count", "source": "20260926-003649-stop"},
  {"name": "stock_surface_consultations", "value": 68, "unit": "count", "source": "20261002-131143-stop"},
  {"name": "sleep_gaps", "value": 5, "unit": "gaps over 5 min (961-7258 s)", "source": "20260926-003649-stop"},
  {"name": "ask_timeouts_60s", "value": 2, "unit": "count", "source": "20260917-132142-stop"},
  {"name": "advice_lines_dropped_or_skipped", "value": 20, "unit": "of 37", "source": "20261006-203245-stop"}
 ],
 "september": {"landed": 12, "standing": 3, "superseded": 2}}
```


---

# 5. Maintainer

## Maintainer — The table is reliable now; what it records about itself is not: the one cost number is 6–25× wrong, the model is an alias, and the only punts in 21 games were the laptop going to sleep

### What you read and what shipped, as the Maintainer reads it

Since September the voice runner got a checkpoint (`voice-state.json`), the records got game time (`turn`/`phase`/`active`/`seq` on every `voice-0.jsonl` row, `events.jsonl` and `observer-tape.jsonl` archived, `--replay`), the observer prints a game-over ledger (`[arena] observer: game over turn 15, 831 s; writes 594 (… failed 0, handler 0) … ring 200 (cast 97 …)`, `ObserverSnapshot.java:718-720`), stalls rotate the session (`runner.py:2351-2358`), keys were scrubbed from every process but the voice (`run_table.sh:69`, `arena-play.sh:177,191,199,214,222`), the raws left the tree (`git ls-tree` raw count 0; `test_table_lines.py:137` gates on the directory), the render cache got a cap (`renderer.py:368-369`; the dir is 0 B today), and two upstream syncs landed with every parent-module patch auto-merged (`docs/UPSTREAM-SYNC.md`, 14 semantic rows, second sync 45 min + one game). Across the 18 in-scope archives (2026-09-16 → 10-06): **restarts 0 in every game, wedges 1, Java exceptions 0, TARGETLOSS/SA-SWAP 0, persistent-stderr files empty in 17 of 18, rotations 80, punts 19**. The Python suite is 744 OK in 57.9 s (exit 0). The transport is stable; the records are the weak layer.

### Top findings

**1. The recorded dollar figure is a cumulative counter summed again — 6× to 25× too high (confirmed).** `SeatBrain._accumulate` (`brain.py:548-552`) adds `total_cost_usd` from every stream-json `result` event, but that field is the persistent process's *session-to-date* cost. Per-call deltas of `cum.cost_usd` in `20260916-111916-stop/seat-2.jsonl` rise with the call index — $0.54 at persistent call 2, $1.16 at 12, $32.27 at 182 — while the per-call usage priced at Opus list stays $0.11–0.85; the seat's game total reads $2,298 against ≈$91 from usage. `20261006-203245-stop/seat-1.jsonl`: $52.08 recorded vs ≈$8.5 (6.1×; fewer calls per process, hence the smaller ratio). The 18 archives sum to ≈$23,969 "API-equivalent; subscription-covered" (`runner.py:809-819`, `seat-N.usage.json`), and the advisor shares the path (`advisor_runner.py:567` writes `seat-0.usage.json` through the same brain). Nothing gates on it on the Claude path (the $ rail is backend-only, `backends.py:_rails_ok`), so this is a wrong measurement, not wrong play. Direction: diff successive `total_cost_usd` within one process (reset on `_persistent` restart/rotation) or price the per-call `usage` yourself; add a test with a fake process whose cumulative figure grows.

**2. Every punt that mattered in 21 games was the machine sleeping, and nothing in the stack knows it (confirmed).** `20260918-093644-stop`: four punts at exactly the wake instants of 33, 91, 35 and 514-minute gaps in `game.jsonl` (22:11:19, 23:43:09, 00:38:37, 09:12:53; `latency_s` 1965, 5489, 2129, 30853) plus six `WINDOW LOST`. `20260926-003649-stop`: five seat-0 (Advisor) punts at wake instants (19:38:28, 21:41:37, 22:41:55, 23:43:02, 00:22:01; `latency_s` 955–7200), one 98 s after; the engine logged `brain absent` twice (heartbeat stale after wake). The v4.3 first-cut acceptance game repeated it (BUG-LOG 2026-10-02: "17 punts / 19 timeouts / 16 lost windows … while the machine slept", a Scepter imprint lost). The mechanism is three wall-clock deadlines: `MailboxProtocol.exchange` (`:224`, `currentTimeMillis + timeoutMillis`), `PersistentClaude.call` (`brain.py:206`), the runner's `mtime + 0.8 × timeout` (`runner.py:2166`); the HTTP stream dies in sleep, so on wake every open window is spent. Of the 19 punts in scope, 11 are at or just after a sleep gap, 2 are the W-13 stall shape (`20260917-132142`, 13:10:28 and 13:11:40 — and the stall-x2 rotation fired at 13:11:43, W-18's fix working live), 6 are ordinary safe-defaults. No `caffeinate`/`pmset` anywhere in `scripts/` or `runner/`. Direction, cheapest first: (a) `arena-play.sh` wraps the GUI in `caffeinate -i -w <gui pid>` (one line); (b) the runner compares `time.monotonic()` against wall time and tags a punt whose latency exceeds `timeout_s` by 5× as `"sleep"` so `arena-hygiene.py` stops shouting `!! HYGIENE` for a known cause and `ratings.void_reason` can void the game; (c) in Java, measure the window with `System.nanoTime()` and extend the deadline by any wall-clock jump.

**3. BL-59 is worse than a missing label: the Elo ladder is keyed by the alias (confirmed).** Every record carries `"model": self.brain.model` (`runner.py:735,790`) — `opus` in all 18 archives; `_accumulate` never reads the result event's per-model usage (no `modelUsage` reference in `brain.py`). `ratings.attribute` picks the pilot by majority of that string (`ratings.py:177-191`), so `runner/ratings.json` holds `models: ['fable', 'human+advisor', 'opus']` — two Opus releases (the 9/25 change BL-59 records) are one Elo entity, and the launch banner (`launch-config.txt`: "model opus") and the `runner up` line (`runner.py:1888-1896`) record neither the concrete id nor the CLI version (no `claude --version` anywhere in `runner/` or `scripts/`). Direction: capture the concrete id from the first result event, stamp it on every record and the spool, key the ladder by it, and print CLI + model id in the banner.

**4. The engine and the runner count stock fallbacks independently, and only one side is read.** `GameResultSpool` writes `stockDecisions` per seat (`:169`, from `MailboxController.STOCK_FALLBACKS`, `:196-203`); `arena-hygiene.py` reads only seat logs and `game.jsonl` (`:23-35,176-234`). In `20260926-003649-stop` the spool says 7/2/1/0, the runner says punts 5/0/1/0: seat 1's two stock decisions have no runner-side trace at all, and the two `brain absent` windows were never requests. Direction: hygiene prints both columns and flags any seat where they differ; a `[mailbox seat-N] timeout seq=…` line in Java at the deadline (`MailboxProtocol.java:245-247` is silent today) would make the join exact.

**5. The Java side logs without time; the Python side logs without date.** `gui.out` `[arena]`/`[mailbox …]` lines carry no timestamp (`20261002-160838-stop/gui.out`: `[arena] CARD-CHECK seat 0: 100/100 …`, `[arena] observer: game over …`); seat, voice, advisor and autostop logs stamp `HH:MM:SS` local with no date (`seat-1.log`: `15:53:56 [seat 1] runner up …`), while the `.jsonl` files stamp epoch `ts`. A game across midnight (`20260926-003649` ran 19:22 → 00:36) or a STOCK-SURFACE line (712 convoke, 160 chooseColor across the 18 games) cannot be joined to a decision except by hand. Direction: one `arenaLog()` helper in Java with an ISO stamp; ISO dates in the three Python text logs.

**6. The archive corpus has no index, two copies of its biggest text and one 30 MB outlier.** 120 directories, 183 MB; `game.jsonl` and `game-<id>-1.jsonl` are byte-identical in every archive (BL-21 by design), `voice-0.log` equals `voice_runner.out`, `launch-config.txt` is prefixed into `run_table.out` and `gui.out` (`arena-play.sh:173-174`); `20260917-114013-stop/gui.jfr` (30.8 MB, `ARENA_JFR=1`) is 17 % of the corpus. Nothing prunes (`arena-stop.sh:72-83` only moves). Three of 18 archives carry no result record (`20260916-192313`, `-223014` hand-stopped; `20261006-203245` "GUI JVM gone before game over", `autostop.out`) and hygiene says `OK` for them. The v4.3 acceptance games live outside the corpus (`personal/forge-light-llm/forge-arena/runner/logs/archive/20261003-152754-stop`), and the game-number ↔ stamp mapping exists only in BUG-LOG prose. Direction: `arena-stop.sh` appends one line to `archive/index.jsonl` (stamp, gameId, mode, model id, result or "no result", punts, wall minutes); hygiene flags "decisions > 0 and no spool"; drop the second `game.jsonl` copy from the archive (keep the per-game file).

**7. What breaks first when Forge moves, from two syncs' evidence.** (i) The fat-jar name after a `<revision>` bump — the only thing that ever broke a live game (BL-47), now guarded in `run-pilot-match.sh:46-59` with a test, but `target/classpath.txt` carries a third copy of "which jar" and went stale at the second sync. (ii) Verbatim mirrors of `PlayerControllerAi` methods — the one hand port of sync 2 (`chooseNewTargetsForCopy`), with W-23 as residue; nothing mechanical detects a stale mirror. (iii) Seeded scenarios (HL-21/22), fenced. (iv) Signature drift in our calls (sync 1: five call sites) — loud at compile. The interactive seam imports 80 distinct upstream classes (51 `forge.game`, 6 `forge.ai`, 3 `forge.gui`); `MailboxController` alone 29, with 32 references to `ComputerUtil`/`AiController` helpers. Direction: a "mirror fingerprint" test — hash the source text of each upstream method in the semantics table and fail with the row's name when it changes, so the manual mirror-audit (step 4) becomes a red test in the probe gate.

**8. The timeout seam is right-sized and W-5's premise is stale.** Engine wait 90 s (`arena-play.sh:45`), runner budget 72 s (`runner.py:2166`), persistent call killed at the same budget (`brain.py:206-212`), heartbeat stale at 15 s (`MailboxProtocol.java:53-79`); pre-warm is now 3.9 s (`20261002-160838-stop/seat-1.log` 15:53:56 → 15:53:59), not the 60–90 s W-5 assumes. Across 18 games the gate shortened exactly the waits it should (the two post-wake `brain absent` lines) and BL-06's "one full wait" never occurred outside sleep. Direction: close W-5 as measured; keep BL-06 open on evidence.

### Concerns

- **Context per call.** Cache-read tokens per game: 12–105 M (median 61.5 M); seat 2 in `20260916-111916` sat at 540k context for 182 calls (53.4 M cache-read in 14 minutes) because the rotation prefers a turn boundary (`runner.py:2038-2044`) and a combo turn never offers one; the hard ceiling is 600k. That is subscription rate-limit budget, not dollars — but it is the single largest cost of a game.
- **A test once wrote into the live logs.** `20260916-111916-stop/claude-persistent-seat-1.err` holds 12 real-CLI lines `--resume … "sess-A" is not a UUID` — `sess-A` is the fixture id in `test_budget_deadline.py:46,82-98` / `test_wedge_recovery.py:38`. The `.err` path is `root/forge-arena/runner/logs/…` regardless of `log_dir` (`brain.py:483`). Today's suite leaves no residue (verified after the run), so the writer was an earlier test or a hand run — but the path still ignores `log_dir`.
- **No gate script pins the JDK.** W-17's rule lives in `UPSTREAM-SYNC.md` and in Project 1 scripts (`batch.sh:9`); `run-gui.sh:31` honours `JAVA_HOME` if set. Surefire (`pom.xml:86-134`): 3.2.5, `-Xmx4g -XX:+UseParallelGC`, `extended,headless-scenario` excluded by default, test mailbox rooted under `target/` only since today (`516794401fa`); 42 of 51 interactive classes use `timeOut`, 13 use `Thread.sleep` (`HeartbeatGateTest:53` asserts `waited < 500` ms — a loaded box can flake it).
- `ObserverSnapshot` still has four `catch (RuntimeException ignored)` (`:294,398,420,734`) beside the counted ones; the ledger counts writer and handler failures, not those.
- `.git`: 2.13 GiB packed plus the September stray `tmp_pack_7LjlU3` (still there, `git count-objects`).

### Bugs and corrections

- Finding 1 — **confirmed** (cumulative `total_cost_usd` summed per call).
- Finding 2 — **confirmed** (sleep punts; three wall-clock deadlines).
- Finding 3 — **confirmed** (alias in records, spool and ladder).
- Finding 4 — **confirmed** (engine 10 vs runner 6 in `20260926-003649`).
- `arena-hygiene.py` reports `OK` for an archive with decisions and no result record (`20261006-203245`) — **confirmed**.
- `.err` path ignores `log_dir` (`brain.py:483`) — **confirmed**; the 9/16 residue's writer — **plausible** (an earlier test).
- W-5's 60–90 s pre-warm — **superseded by measurement** (3.9 s).
- `test_backends.py` loopback socket still raises the suite's closing `ResourceWarning` — **confirmed** (today's run).
- The Advisor's seat-0 punts on wake count against the human seat in the spool (`stockDecisions` 7) — **plausible** that `void_reason`'s "punt pile-up on one seat" voids a human game for a sleep, not a brain.

### Feature suggestions (ranked by cost)

1. **S** — `caffeinate -i -w` around the GUI in `arena-play.sh`; sleep-tagged punts in the runner and hygiene.
2. **S** — concrete model id + CLI version in the banner, every record, the spool and the ladder key (BL-59).
3. **S** — cost by delta-of-cumulative (or priced usage) with a fake-process test.
4. **S** — `archive/index.jsonl` written by `arena-stop.sh`; hygiene flags "no result record".
5. **M** — mirror-fingerprint test for the semantics table.
6. **M** — timestamped Java `[arena]` lines and a `timeout seq=N` line; hygiene joins engine `stockDecisions` to runner punts.
7. **M** — `scripts/gate.sh` that pins `JAVA_HOME`, captures exit status, checks the surefire report timestamp and the jar count — the discipline the docs describe, as a script.

### Observability and efficiency

- Recorded per decision: `latency_s` (model only), `usage`, `cum`; not recorded: the engine-side wait, the timeout event itself, the model id, the sleep state. Model latency medians 1.6–3.6 s, p90 2.6–8.2 s across the 18 games — the file bus is not the bottleneck.
- Per game (median): 28 min wall, 557 decisions, ~330 model calls, 61.5 M cache-read tokens, 0 restarts, 4 rotations.
- Polling is stat-gated everywhere now (`voice_runner.py:746`, `advisor_runner.py:247`; engine 75 ms, runner 0.15 s, voice 0.5 s, advisor 1.0 s). The idle table is cheap.
- The stock is 517 MB / 4,336 WAV at 22.05 kHz; the package carries it; the September duration-field idea still stands.
- Secrets: clean — zero key-shaped strings in `runner/logs`, `docs`, `packaging`, `scripts`; `launch-config.txt` masks to `=set/unset`; keys come from the launching shell (no script sources a file; `~/Claude/hello` is referenced nowhere); the only new sink is the CLI stderr capture, empty in 17 of 18 archives.

### Questions for Ben

1. Should a game that crossed a sleep be voided for ratings and marked in hygiene, or do you want the engine to carry the window across the gap (the Java `nanoTime` fix)?
2. Is `caffeinate` for the GUI's lifetime acceptable, or do you sometimes want the laptop to sleep mid-game?
3. Do you want the Elo ladder re-keyed by concrete model id (which splits `opus` history at game 63) or a new ladder from the next game?
4. May the archive drop the duplicate `game.jsonl` copy, and should the package root's archives be pulled into the corpus?

### Follow-up on the September report

**Landed (14):** restart memory (`voice-state.json`, `_durable_state`/`_restore_state`, `voice_runner.py:163,514,626`; restarts 0 in all 18 games); game-time records + archived events/tape + `--replay` (`:1241`); muted teardown (`:950-954`, B1); raws out of the tree (test gated `:137`); observer game-over ledger (`ObserverSnapshot.java:718-720`); `scan_game_log` inode tail (`voice/events.py:231-249`); stall-x2 rotation (`runner.py:2351-2358`, seen live 9/17 13:11:43); `env -u ELEVENLABS_API_KEY` (B4); hygiene counts voice/advisor restarts (`arena-hygiene.py:41`, C3); `gid` now used (`_gid_cache`); BSD `stat` replaced (B5, `arena-autostop.sh:72`); summary line (`summary` event, hygiene "runner summary"); mtime short-circuits; render-cache cap (`renderer.py:368-369`).
**Still standing (3):** the WAV-size/duration-field efficiency idea (517 MB); tests pinned to library counts and real files on disk (`test_table_lines.py:131-140`, `290+30+27+6+12+24+8+55` per voice — the package excludes tests by design now); the `test_backends.py` `ResourceWarning`.
**Superseded (2):** the untested silence floor (21 games of `voice pace` lines since); the SIGTERM-reload question (the habit stopped — zero restarts in every archive).

```json
{"lens": "Maintainer",
 "findings": [
  {"id": "M1", "title": "Recorded cost_usd sums a cumulative total_cost_usd per call — 6–25× too high", "kind": "bug", "severity": "P1", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/seatd/brain.py:548-552", "runner/seatd/runner.py:809-819", "20260916-111916-stop/seat-2.jsonl", "20261006-203245-stop/seat-1.jsonl"]},
  {"id": "M2", "title": "Laptop sleep spends every open window: 11 of 19 punts in 21 games; no sleep guard, no sleep tag", "kind": "bug", "severity": "P1", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["src/main/java/forge/arena/interactive/MailboxProtocol.java:224", "runner/seatd/brain.py:206", "runner/seatd/runner.py:2166", "20260918-093644-stop", "20260926-003649-stop", "docs/BUG-LOG.md:201"]},
  {"id": "M3", "title": "Model alias in every record, the spool and the Elo ladder key; no CLI version recorded (BL-59)", "kind": "bug", "severity": "P2", "confidence": "confirmed", "area": "runner", "effort": "S", "sources": ["runner/seatd/runner.py:735", "runner/ratings.py:177-191", "runner/ratings.json", "runner/logs/archive/*/launch-config.txt"]},
  {"id": "M4", "title": "Engine stockDecisions and runner punts diverge and are never compared", "kind": "observability", "severity": "P2", "confidence": "confirmed", "area": "scripts", "effort": "M", "sources": ["src/main/java/forge/arena/interactive/GameResultSpool.java:169", "scripts/arena-hygiene.py:176-234", "20260926-003649-stop"]},
  {"id": "M5", "title": "Java seam lines have no timestamp; Python text logs have no date", "kind": "observability", "severity": "P2", "confidence": "confirmed", "area": "java-seam", "effort": "M", "sources": ["20261002-160838-stop/gui.out", "20261002-160838-stop/seat-1.log"]},
  {"id": "M6", "title": "Archive corpus: no index, duplicated game.jsonl, 30 MB JFR outlier, three archives without a result record, acceptance games outside the corpus", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "scripts", "effort": "S", "sources": ["scripts/arena-stop.sh:72-83", "20260917-114013-stop/gui.jfr", "20261006-203245-stop/autostop.out", "personal/forge-light-llm/forge-arena/runner/logs/archive/20261003-152754-stop"]},
  {"id": "M7", "title": "What breaks first on a Forge move: jar name after a version bump, then verbatim PlayerControllerAi mirrors — no mechanical stale-mirror check", "kind": "concern", "severity": "P2", "confidence": "confirmed", "area": "sync", "effort": "M", "sources": ["docs/UPSTREAM-SYNC.md", "scripts/run-pilot-match.sh:46-59", "docs/BUG-LOG.md:82", "docs/BUG-LOG.md:164"]},
  {"id": "M8", "title": "Timeout seam right-sized; W-5's 60–90 s pre-warm premise is stale (3.9 s measured)", "kind": "observability", "severity": "P3", "confidence": "confirmed", "area": "java-seam", "effort": "S", "sources": ["src/main/java/forge/arena/interactive/MailboxProtocol.java:53-79", "runner/seatd/runner.py:2166", "20261002-160838-stop/seat-1.log", "20260917-132142-stop/transport-events.jsonl"]},
  {"id": "M9", "title": "Persistent stderr path ignores log_dir; a test once wrote 12 real-CLI errors into a live archive", "kind": "bug", "severity": "P3", "confidence": "confirmed", "area": "tests", "effort": "S", "sources": ["runner/seatd/brain.py:483", "20260916-111916-stop/claude-persistent-seat-1.err", "runner/tests/test_budget_deadline.py:46"]},
  {"id": "M10", "title": "No gate script pins JAVA_HOME (W-17); discipline lives in docs; 13 timing-dependent Java test classes", "kind": "concern", "severity": "P3", "confidence": "confirmed", "area": "tests", "effort": "M", "sources": ["pom.xml:86-134", "docs/UPSTREAM-SYNC.md", "src/test/java/forge/arena/interactive/HeartbeatGateTest.java:53"]},
  {"id": "M11", "title": "Combo turns run at 300–540k context per call because rotation waits for a turn boundary", "kind": "concern", "severity": "P3", "confidence": "confirmed", "area": "runner", "effort": "M", "sources": ["runner/seatd/runner.py:2038-2044", "20260916-111916-stop/hygiene.txt"]},
  {"id": "M12", "title": "Secrets handling clean: no key shapes in logs/docs, masked launch config, env -u on every non-voice process", "kind": "observability", "severity": "P3", "confidence": "confirmed", "area": "scripts", "effort": "S", "sources": ["scripts/arena-play.sh:177-222", "runner/run_table.sh:69", "runner/seatd/backends.py:225-226"]},
  {"id": "M13", "title": "Hygiene says OK for an archive with decisions and no result record", "kind": "bug", "severity": "P3", "confidence": "confirmed", "area": "scripts", "effort": "S", "sources": ["scripts/arena-hygiene.py:269-272", "20261006-203245-stop/hygiene.txt"]},
  {"id": "M14", "title": "Should sleep games be voided or carried across the gap?", "kind": "question", "severity": "P2", "confidence": "plausible", "area": "runner", "effort": "S", "sources": ["runner/ratings.py:217", "20260926-003649-stop/game-1790385082595-63074.json.voided"]}
 ],
 "metrics": [
  {"name": "archives examined", "value": 18, "unit": "archives", "source": "runner/logs/archive 20260916 → 20261006"},
  {"name": "corpus", "value": 183, "unit": "MB in 120 directories", "source": "du -sh runner/logs/archive"},
  {"name": "punts", "value": 19, "unit": "across 18 games (11 at sleep/wake)", "source": "game.jsonl source=punt"},
  {"name": "runner restarts", "value": 0, "unit": "across 18 games", "source": "hygiene.txt"},
  {"name": "rotations", "value": 80, "unit": "transport events", "source": "transport-events.jsonl"},
  {"name": "median game wall time", "value": 28, "unit": "minutes (non-sleep games)", "source": "game.jsonl ts"},
  {"name": "median cache-read tokens per game", "value": 61.5, "unit": "M tokens", "source": "seat-N.usage.json"},
  {"name": "recorded cost over 18 games", "value": 23969, "unit": "USD as logged (over-counted 6–25×)", "source": "seat-N.usage.json cost_usd"},
  {"name": "cost over-count ratio", "value": 25.3, "unit": "× (seat 2, game 20260916-111916)", "source": "seat-2.jsonl cum.cost_usd deltas vs usage"},
  {"name": "python suite", "value": 744, "unit": "tests OK in 57.9 s", "source": "python3 -m unittest discover -s tests"},
  {"name": "upstream classes imported by the seam", "value": 80, "unit": "distinct", "source": "grep ^import forge. src/main/java/forge/arena/interactive"},
  {"name": "java interactive test classes using timeOut", "value": 42, "unit": "of 51", "source": "grep timeOut src/test/java/forge/arena/interactive"},
  {"name": "model latency median", "value": 2.2, "unit": "s (range 1.6–3.6 across games)", "source": "hygiene.txt"},
  {"name": "stock surfaces: convoke/improvise", "value": 712, "unit": "STOCK-SURFACE lines across 18 games", "source": "gui.out"}
 ],
 "september": {"landed": 14, "standing": 3, "superseded": 2}}
```


---
