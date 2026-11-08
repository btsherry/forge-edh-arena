# Brain-authored table talk — a contextual menu, addressed lines, pre-armed stances

**Date:** 2026-10-16 (evening); **revised 2026-10-18** after a Fable review of the plan against the code
(`2026-10-18-brain-authored-talk-review.md`, thirty findings, two of them P0 — §11 maps each to a change here).
**Status:** BUILT — steps 1–4 landed 2026-10-18 (suite 808 green; BUG-LOG W-25); the first game with steps 1 + 2 was Ben's "best run of the voice overs to date"; steps 3 + 4 await their first game. **Owner:** Ben. **Branch:** `arena`.
Python only (seat runner, rules, voice runner, one data file, hygiene); no Java, no new audio, no live rendering
(Ben, 2026-10-16: "No free live voice per seat"). The stock stays as it is.

Ben, on the architecture: "what we have is fakely voiced brains where one instance is effectively narrating
the game, and trying to make it sound like the brains." The split this plan keeps: the voice runner stays the
**performer and the conductor** (baked takes, the queue, the gaps, the duty budget, chains, atoms — "the one
throat every line passes through"); the **authorship** moves toward the brain, which already has a turn at
every decision and already writes its reasons. Three steps, each a sitting, each measurable in one human game.
Standing constraint (Ben, §10.3): **no new governance layer** — every guard below is one that exists today.

## 0. Where authorship sits today (facts, from the code on 2026-10-16, corrected 10-18)

- **The `say` key.** `seatd/rules.py` offers `OPTIONAL "say": one of [18 ids]` (`SAY_MENU`, `SAY_OFFER`) on
  `SAY_WINDOWS` (CAST_SPELL, REACT, DECLARE_ATTACKERS, DECLARE_BLOCKERS, CHOOSE_ENTITY, CHOOSE_ENTITIES) when
  the window has more than one option, never to seat 0 at a human table (`say_offer`). The same 18 ids on
  every window, whatever is happening. `SeatRunner._say_key` validates against `SAY_MENU`; `rules.validate`
  strips the key from the engine answer; `_record` writes `say` on the game.jsonl record (model answers only,
  consumed or not — F20). The deal paths (`deal_offer_line`, `deal_propose_line`) tell the brain to add
  `"say": take-the-deal / no-deal / counter-offer / deal`; the loop declaration is `"say": looping`.
- **The voice's intake.** `voice/events.py:scan_game_log` → `brain_intent` → `_bark(seat, say, source="brain",
  p=1.0, ctx)`. Three ids (`SAY_TARGETED`: deal, kill-that, youre-the-threat) are aimed at `leader_of(seat)` —
  the threat pin, else the highest-life OTHER seat, never the human. **"brain" is anchored but governed**
  (`scheduler.py:707-716`: the ungoverned set is mulligan lines, floor patter, procedural, deal lines, `terms-`);
  at `ARENA_CHATTER=quiet` or over budget a brain line is diced at 0.5. A brain line is enqueued with
  `evict=True`, so it clears every pending non-follow-on bark. A second copy of `SAY_MENU` lives in events.py,
  pinned equal to rules.py by `test_events_hardening`.
- **What already exists that this plan reuses instead of rebuilding.** `ADDRESS_SWAP` + `address_swap`
  (`scheduler.py:99-100, 750-774`): kill-that / archenemy / youre-the-threat / deal / why-me become `hit-<who>`,
  `threat-<who>`, `deal-<who>`, `leave-me-<who>` from the ctx's one target or aggressor, half the time
  (`table_p("address")`), with the library check and a 300 s repeat guard, applied to every bark by `maybe_bark`.
  `PROPOSAL_LINES` / `PROPOSAL_PREFIXES` (`scheduler.py:80-81`): a proposal draws a yea or nay from every other
  seat, then the subject may retort. `QUESTION_LINES` (`scheduler.py:78`): questions are answered with certainty
  and never put to the human. `OWN_ACTION_LINES` (`scheduler.py:91-94`): the lines a seat says because it just
  acted. The threat pin: `raise_threat` / `decay_threat` / `THREAT_MIN` / `threat_seat` / `leader_of`; the patter
  already pins the human when his game changer raised the threat (`scheduler.py:1121-1123`) — so "no seat ever
  calls Ben the threat" was false; only `leader_of` excludes him.
- **The stock the brain could draw on.** Per seat voice: 66 base phrase ids (21 bark, 19 reply, 15 patter,
  11 reaction), 329 table ids (44 procedural/arc/loop/deal/heckle ids; 41 `hit-<who>`, 41 `threat-<who>`,
  41 `leave-me-<who>`, 43 `deal-<colour>`, 55 `terms-`, 45 `life-`, 11 `hand-`, 8 `mull-`), 188 card ids
  (87 gc, 74 combo, 27 cmd), 24 atoms. Every phrase carries a `when` gloss and four-plus wordings. The reviewer
  verified every id this plan names exists in harry, bill, lily **and joshua** (seat 0 is Joshua's voice on an
  all-AI table). The brain sees 18 of these.
- **What the voice already detects without a call** (`scan_events`): attack (big-swing / poke / attack-you by
  the attacker; a human swing draws the defender's brace / why-me / no-blocks), damage (take-it small, that-hurt
  at `barks_hit`, grudge every second hit from the same seat, landed-hit on the human), cast (the caster's
  game-changer once a game per card, commander-cast, cast-big; the human's cast draws gc-react / oh-no / brace /
  read-that from a bystander), left (gc-gone, the sweeper's sweep and the owners' got-swept / not-again-sweep,
  lost-commander, the remover's removal; the human's removal draws the owner's oh-no), countered (the
  counterer's counter; the human's counter draws got-countered / again-countered), plus the stack, combos, life
  steps, turn openers, the patter clock, chains. **For an AI actor the event line is the actor's; the victim's or
  bystander's reaction is a chain reply** planned in `after_spoken` → `chains.plan_reply` from `chains.json`.
  None of it knows what the brain thinks.
- **What the seat runner can see at a window:** the request state (own life, pool, board, `opponents[]` with
  life, battlefield and creature power — the dead are already excluded; the stack by name with owners / kinds /
  targets / oracle; `state.combat` with attacker CARD names and the defender's name, never the attacking player;
  defenders; options with labels), the public observer snapshot it already reads on every model window
  (`runner.py:2351`, `protocol.py:227-232`): seats with life / eliminated / hand counts, `stackDetail`, the active
  seat, **and a thirty-entry ring of public events** — `damage{seat,from,amount,combat}`, `countered{seat,by,spell}`,
  `cast{seat,spell,commander,cmc}`, `left{by,seats,cards,commanders,n,tokens}`, `attack{seat,defenders,power}` —
  the same ring the voice runner scans. Plus its own memos (deals in force, pending offers, last turn) and the
  voice's `address.json` (deck → `who`: urza / giada / purphoros / selvala).
- **Measured (games 1–2, 2026-10-16):** the new text reply (table talk answered by the seat) lands 2.0–2.5 s
  after it is typed once the session is warm; decisions run 3.4 s median. The model turn is the whole latency.

## 1. What it should feel like

- **The seat says what it meant.** A seat that just took eight from Giada chooses between "you again?!",
  "that hurt", "bite me", "Giada's the threat!" — or silence — because the window it is deciding in offered
  exactly those, with one-line glosses, instead of the same eighteen ids it sees when nothing is happening.
- **The seat picks on whom it means.** "Kill that" goes at the board that has the thing; "you're the threat"
  names the seat the brain is actually worried about, and the table's threat pin follows the brains' politics
  instead of the dice. When the brain names a seat, the voice says the name through the swap that exists:
  `threat-giada`, `hit-urza` — the address lines that have never fired are exactly these.
- **The seat has reflexes it chose.** While it is asleep between windows, the voice runner performs the
  posture the brain armed at its last decision: "if anyone hits me, grudge at them", "if someone casts a game
  changer, call for its death". No call. When the human is the actor it fires at the event; when another seat is
  the actor it is the brain's pre-chosen retort to that seat's line, a beat later (§5).
- **Nothing gets louder on its own.** The same guards hold (`said_this_turn`, the seat guard, the duty budget
  for the rest of the table); brain lines never evict what is already queued; two counters cap the brains.

## 2. The data file — `runner/voice/stock/voices/say-menu.json` (step 1)

One shipped file replaces the two pinned code copies of `SAY_MENU`. **Loaded by the seat side only**
(`rules.load_say_menu()` replaces `SAY_MENU` / `SAY_OFFER`); the voice validates a brain's id by "the seat's
library carries it" (`lib_for` + `renderer.variants`) and keeps no copy. The brain-facing glosses live in this
file (one source, prompt-grade, not the manifests' `when` — F10); a test pins every id to a phrase that harry,
bill, lily and joshua all carry. The menu is **reactions, jabs, calls and addressed lines only**: the lines the
event ring does not already speak for the seat with the right context and the measured odds (F6; §12 Q2).

```json
{"schema": "arena.say-menu/1",
 "core": [
   {"id": "taunt",             "gloss": "a jab at the table"},
   {"id": "respect",           "gloss": "credit where it is due"},
   {"id": "nice-play",         "gloss": "admire the last play"},
   {"id": "gg",                "gloss": "the game is over, say so"},
   {"id": "this-is-fine",      "gloss": "deadpan: everything is fine"},
   {"id": "im-not-the-threat", "gloss": "deflect: not me"},
   {"id": "youre-the-threat",  "gloss": "name the threat", "to": true},
   {"id": "kill-that",         "gloss": "call for the table to answer their big thing", "to": true}],
 "situations": {
   "hit":          ["that-hurt", "grudge", "bite-me", "you-suck", "attack-them", "youre-the-threat", "low-life"],
   "blocking":     ["brace", "why-me", "you-wish", "attack-them", "youre-the-threat"],
   "attacking":    ["not-sorry", "archenemy", "low-life-jab", "empty-hand"],
   "countered":    ["scoff", "clapback", "you-cheat", "nerd", "bite-me", "youre-the-threat"],
   "stack_threat": ["oh-no", "wow", "read-that", "scoff", "kill-that", "nice-play", "gc-react"],
   "leader":       ["whats-your-life", "low-life-jab", "empty-hand", "cards-in-hand", "you-wish"],
   "behind":       ["low-life", "im-not-the-threat", "youre-the-threat", "attack-them", "kill-that"],
   "quiet":        ["nothing-happening", "pass-already", "what-turn", "long-game"]},
 "deal": ["take-the-deal", "no-deal", "counter-offer", "promise", "deal"],
 "loop": ["looping"],
 "needs_target": ["youre-the-threat", "kill-that", "attack-them", "archenemy", "low-life-jab", "empty-hand",
                  "whats-your-life", "cards-in-hand"],
 "stances": {
   "on_hit":       ["grudge", "that-hurt", "bite-me", "youre-the-threat", "attack-them", "this-is-fine"],
   "on_attacked":  ["brace", "why-me", "you-wish", "youre-the-threat", "this-is-fine"],
   "on_counter":   ["scoff", "clapback", "you-cheat", "nerd", "bite-me"],
   "on_gc":        ["gc-react", "kill-that", "oh-no", "scoff", "read-that", "wow"],
   "on_commander": ["oh-no", "read-that", "wow", "nice-play"],
   "on_big_spell": ["wow", "nice-play", "read-that", "oh-no", "scoff"],
   "on_removal":   ["oh-no", "scoff", "you-suck", "clapback", "bite-me"],
   "on_sweep":     ["got-swept", "not-again-sweep", "this-is-fine"]},
 "max_ids": 14, "max_says_per_turn": 2}
```

(The situation and stance lists above are ids; the shipped file carries `{"id","gloss"}` entries like `core`.)
What left the lists since the first draft, and why: every own-action / procedural line — big-swing, attack-you,
poke, no-blocks, take-it, you-promised, i-broke-it, hold-on, sure, in-response, got-countered, again-countered,
commander-cast, game-changer, engine-online, big-mana, cast-big, my-turn, early-game, heads-up — the ring speaks
each of these for the seat at the moment it happens, with the ctx the chains need (`open`, the card, the
defenders) and the odds Ben tuned (`TABLE_P`); a brain saying `big-swing` before its attack would have played the
line without the `open` list (so "no blocks" could never answer), overridden the odds with certainty, and doubled
the named card line (F6). `thats-mean` is a bystander relishing a third party's pain, not a victim's line;
`brace` and `why-me` are attack-only; `deal` is a real ledger action (a one-word say strikes a small-talk truce)
and stays with the deal paths (F10; §12 Q3). `that-hurt` / `grudge` stay in `hit` as the after-the-fact form (the
ring's same-id line dedupes through `said_this_turn`); `low-life` is offered only at own life ≤ 10,
`low-life-jab` / `empty-hand` / `cards-in-hand` only when a seat qualifies (life ≤ 10 / hand 0 / hand ≥ 7, the
patter's gates), `long-game` only past turn 14, `whats-your-life` / `cards-in-hand` never at the human
(`QUESTION_LINES`). The `deal` group is offered only when a deal line is on the prompt; `loop` only on the cycle
windows — so the deal grammar and `test_deals_seat` keep working (F11).

## 3. Step 2 — the contextual menu

**Detection — the event ring, not memos (F5).** `SeatRunner._situations(req, observer)` reads the observer's
`events` ring with one per-runner `seq` cursor (advanced on model windows only — the fastpaths do not read the
observer today and adding IO there is new IO; reset on `game_reset`), plus facts the request carries:

| Situation | How the runner knows |
|---|---|
| hit | a `damage` event with `seat == me`, `amount > 0`, `from` another seat, since the cursor; the hitter is `from[0]`; `grudge` from the second hit by the same seat (a per-game count from the ring, nothing else) |
| blocking | `decisionType == DECLARE_BLOCKERS` (the attacker from the ring's last `attack` naming me) |
| attacking | `decisionType == DECLARE_ATTACKERS`; `low-life-jab` / `empty-hand` only for a defender that qualifies |
| countered | a `countered` event with `seat == me` since the cursor; `by` is the target of the addressed ids |
| stack_threat | REACT with another seat's name on `state.stack` whose ring `cast` event has `commander`, `cmc ≥ 5`, or a game-changer name (the roster's dossier flags, read once at start — names only, the one cross-deck read besides the observer; stated in `protocol.py`'s docstring) |
| leader | strictly highest life at the table (unique max, the patter's rule), or own `ownBoardPower` above every `opponents[].creaturePower` |
| behind | lowest life, or own life ≤ 10 |
| quiet | nothing on the stack and not my turn; `long-game` only past turn 14 |

Blind spots, stated: a crash restart or a thirty-event overrun loses events exactly as the voice does (its B2 gap
record); a seat with no window through a long loop turn may be offered an old hit once, late.

**The offer.** A quiet window (no situation beyond `leader` / `quiet` active) keeps a one-line core of eight ids
(~60 tokens, today's shape). A charged window gets **14 ids total** — the active situations' ids first, in the
order above, then core to fill, deduped (F14) — each `id — gloss`, `→` marking an id that takes a seat, ~250–300
tokens (F13):

```
OPTIONAL "say": a table line your seat speaks aloud — at most one, only when it fits this moment, else omit.
Give "<id>" or {"id": "<id>", "to": <seat>} (→ = names a seat). Lines that fit now:
  that-hurt — that one landed | grudge — the same seat hit you again | bite-me — light name-calling |
  youre-the-threat→ — name the threat | attack-them→ — point the table at someone else | …
```

**Validation and record (seat runner).** `_say_key(req, raw)` accepts a string or `{"id", "to"}`; the id must be
in the set offered on this window (remembered per `seq`; off-menu → dropped with the seat-log note and a hygiene
count); `to` must be another living seat: `to ∈ {o.seat for o in opponents}` ∪ `{0}` at a human table
(`rules.all_ai_table()` decides), never self, and **never the human for a `QUESTION_LINES` id** (F8, F22). Cap:
`max_says_per_turn` per seat per `req.turn`, one counter, the third dropped with a note. The record keeps `say`
as the string id (every reader today expects a string) and adds `say_to` (int), `say_card` (the card NAME from
the chosen option's label when the window is a cast — the voice derives kind and slug the way the ring branch
does: `game_changers[seat]`, `_who[seat]`, `combos_of` — F15) and `say_offered` (the ids offered, so the hygiene
line can say whether the brains tail the list — decision 5). A `say` is recorded only for a **consumed** model
answer (F20: today a `WINDOW LOST` answer's line is spoken for a decision the engine never took).

**Voice (events.py `brain_intent`).** Accept any id the seat's libraries carry (no copy of the menu);
`ctx = {"targets": [say_to], "aggressor": say_to}` when a `to` came, plus the card ctx; an id in `PROPOSAL_LINES ∪
QUESTION_LINES ∪ ADDRESS_SWAP` with no `to` falls back to `leader_of` as today (existing sets, no second
loader); then `_bark(seat, id, turn, source="brain", p=1.0, ctx, evict=False)` — **`evict=False`** (F4: an
anchored bark clears every pending non-follow-on bark; the deal lines already queue this way). Whether a brain
line is governed stays as today unless Ben decides otherwise (§12 Q1; §6).

**Knob.** `ARENA_SAY_MENU=contextual|fixed`, read in `runner/seatd/` only (F12: `test_tuning` pins the voice
path's environment reads to the five operator knobs plus render and plumbing); banner row in `arena-config.py
KNOBS` and the `packaging/README.md` table. Default `contextual` (decision 6).

## 4. Step 3 — addressed lines

- **Contract:** `{"id": "youre-the-threat", "to": 2}`. An id in `needs_target` without a valid `to` falls back
  to the leader (today's behaviour); an id not in `needs_target` with a `to` keeps the target as the line's
  addressee (a `taunt` at seat 3 is a taunt at seat 3 — the chains may let seat 3 retort).
- **The named wording through the swap that exists (F9).** No `named` table: `ADDRESS_SWAP` gains
  `"attack-them": ("hit", "target")` and `PROPOSAL_LINES` gains `attack-them` (two tokens), so a brain's
  `attack-them` at Giada becomes `hit-giada` and draws the table's yea/nay round like `kill-that` does, instead of
  one behaviour on a coin flip. `address_swap` rolls `table_p("address")` (0.5) for the named wording; for
  `source == "brain"` the roll is skipped (one condition) so a brain that named a seat is heard naming it.
- **The threat pin follows the brain:** one line in `brain_intent` — `youre-the-threat` / `archenemy` with a `to`
  calls `raise_threat(to, THREAT_MIN, "named by seat N")` — so `leader_of` and the patter's "kill that" agree with
  what the brains say out loud. Decays as today.
- **The human as a target (decision 1: yes).** `to: 0` is accepted for every id except `QUESTION_LINES`
  (`whats-your-life`, `cards-in-hand`: asked and nobody answers — the game-48 awkwardness the patter already
  avoids). The A14 rule (nobody answers *for* the human) is untouched; the human answers for himself in the chat.

## 5. Step 4 — pre-armed stances (rewritten after F1 / F2)

**Contract (brain → runner, on every say window — decision 4):**

```
OPTIONAL "stance": a reflex your voice performs without asking you, once per trigger, when it next happens:
{"on_hit": "grudge", "on_gc": "kill-that"} — triggers: on_hit, on_attacked, on_counter, on_gc, on_commander,
on_big_spell, on_removal, on_sweep; an id from the list above that fits the trigger; "to" is whoever caused it.
```

~55 tokens. Values are an id or `{"id", "to"}`. The runner validates each trigger against `stances[trigger]`
(an id that fits no trigger is dropped with a note), records `rec["stance"]` on the decision record (and the
shared game line) and does nothing else; the performance is the voice runner's. `ARENA_STANCES=on|off` is read
in `runner/seatd/` only (F12): off = the key is neither offered nor recorded. Default on (decision 6).

**What a stance is in the voice runner — two shapes, zero new hooks, zero `continue`s.** The first draft put a
hook "at the top of each `scan_events` branch" and skipped the rest of the branch; that would have skipped the
bookkeeping the ledger, kill attribution and loop detection depend on (`_last_hit_by`, `_hits_from`,
`note_attack`, `_deal_broken`, `_gc_cast_seen`, `raise_threat`, `loop_tick`, the flurry clock, `cast_tick`,
`_sweeps`, `_countered_n` — F1), and it assumed the stance holder's own dice line exists at every trigger, which
is true for only two of eight: for an AI actor the event line is the actor's and the reaction is a chain reply
(F2). So:

- **Shape (a) — own-line substitution.** Where the stance holder's own line is spoken by the ring today, the
  dice `pid` and `p` become the stance's id and 1.0, with the event's ctx (so `aggressor`, `human_cause`, the
  card are right by construction). Sites: the `damage` branch's victim lines (take-it / that-hurt / grudge),
  the `left` branch's owner lines (got-swept / not-again-sweep), and the **human-actor** sub-branches where the
  reactor's line is spoken directly: the defender's brace / why-me / no-blocks on a human swing, the bystander's
  gc-react / oh-no / brace / read-that on a human cast, the owner's oh-no on a human removal, the victim's
  got-countered / again-countered on a human counter. At Ben's table this is the case that matters most: the
  brains' reactions to **his** plays fire at the event.
- **Shape (b) — the pre-chosen reply.** When another seat is the actor, the reaction is today a chain reply:
  in `after_spoken`, before `plan_reply` (`scheduler.py:622-626`), if the spoken opener maps to a trigger and a
  target or bystander seat holds that stance, enqueue it as the hop-1 reply with p=1.0 through the same link,
  gap, priority and ctx a planned reply gets (`scheduler.py:639-653`) and skip `plan_reply`. That inherits A14,
  the seat guard, `said_this_turn`, the hop priority and "a new turn ends the exchange" for free. The opener →
  trigger map: `big-swing | poke | attack-you → on_attacked` (holders among `ctx.targets`); `game-changer |
  gc-*-cast → on_gc` (bystanders); `commander-cast | cmd-*-cast → on_commander`; `cast-big → on_big_spell`;
  `removal → on_removal` (targets); `counter → on_counter` (targets). Honest limitation: shape (b) fires a beat
  (`chain_gap_s`, 0.25 s) after the actor's line, and only if that line played — when the actor's line was diced
  away the stance does not fire (§12 Q4 offers the one-rule fix).

| Trigger | Event | Shape | Cause (`aggressor`, the default `to`) |
|---|---|---|---|
| on_hit | `damage` on the holder, from another seat | (a) at the victim's line | the single hitter |
| on_attacked | `attack` with the holder among the defenders | (a) human attacker; (b) reply to big-swing / poke / attack-you | the attacker |
| on_counter | `countered` on the holder | (a) human counterer; (b) reply to `counter` | `by` |
| on_gc | another seat casts a game changer | (a) human caster; (b) reply to game-changer / gc-*-cast (card ctx → `card_swap`) | the caster |
| on_commander | another seat casts its commander | (a) human; (b) reply to commander-cast / cmd-*-cast | the caster |
| on_big_spell | another seat casts cmc ≥ 5, not gc / commander | (a) human; (b) reply to cast-big | the caster |
| on_removal | the holder's non-token permanent removed by another seat | (a) human remover; (b) reply to `removal` | `by` |
| on_sweep | ≥ 3 permanents across ≥ 2 owners, holder an owner ≠ `by` | (a) at the owner's got-swept line | `by` |

Firing: `source="stance"`, p=1.0, `evict=False`, the event's ctx; `"stance"` joins `ANCHORED_SOURCES` and
hygiene's fallback mirror (F18); the stance is consumed (one-shot per trigger); the per-seat fire counter and the
cap (`tuning.json: stance_fires_per_turn`, 3 — a voice number lives in the voice's data file, §12 Q8) reset at
`_roll_turn`. Lifetime: §12 Q6 (recommendation: until it fires, is replaced, or the holder's own turn begins).
Stances are checkpointed with the voice's durable state (F16) and parsed **before** the staleness return in
`brain_intent` — a stance read ten seconds late is still armed; one from a past turn is history (F19). Ledger:
`record("noted", kind="stance", why="armed|fired|expired|dropped", …)` — the existing vocabulary, so
`record_summary` and hygiene tally it without a new event name (F17).

## 6. Guards and failure modes, decided up front (one existing mechanism each)

- **Volume:** two brain says per seat per turn and three stance fires per seat per turn (decision 3) — two
  counters. `said_this_turn` (same id once a turn), the seat guard and `RARE_REPEATS` apply unchanged.
- **Eviction:** brain and stance barks are enqueued with `evict=False` (F4) — nothing queued is displaced.
- **The governor (F3):** today a brain line is anchored but governed (0.5 at `quiet` or over budget). Either
  stays so — then hygiene counts the voice's `skipped … dice (brain|stance …)` records so the lie is visible — or
  `source in ("brain", "stance")` joins the `ungoverned` expression at `scheduler.py:707` (one clause, the deal
  lines' precedent). §12 Q1.
- **Two lines for one moment:** a stance substitutes the dice line at the same site (a) or is the chain reply
  (b), so it never doubles it; an after-the-fact `say` with the ring's same id dedupes, a different id plays —
  people do comment twice. Measure before adding a rule.
- **Hallucinated or stale ids:** only the offered set validates; drops are logged and counted.
- **Wrong target:** not living / self / a question at the human → the target is dropped, the id falls back to
  its default; never an error.
- **A say that contradicts the answer (F7):** moot once the own-action lines are off the menu; if Ben wants
  them back (§12 Q2) the three that assert an action are checked against the answer (`_deal_conflict` for
  i-broke-it, non-empty `attackers` for the attack lines, empty blocks for no-blocks).
- **Prompt and latency (F13):** ~250–300 tokens on a charged window plus ~55 for the stance line on every say
  window — ~13k uncached tokens per seat per game, immaterial against the 250k rotation budget; the number at
  risk is **decision latency** (reading 14 glossed options and emitting object-valued keys): hygiene already
  prints model latency median / p90 per game — compare it before and after with `ARENA_SAY_MENU=fixed` as the
  control. Low-effort REACT windows get the core line only (F29).
- **The brief and the chat (F25):** `seat-brief.md`'s TABLE TALK paragraph describes the object form, `to` and
  `stance`; the chat prompt says "plain words, never a say" so a brain fluent in the new grammar does not answer
  table talk with `{"say": …}` and go silent.

## 7. Measurement (hygiene, one line per game)

`says: offered on W windows, answered N (that-hurt 4, grudge 2, …), off-menu D, addressed A (human H), diced S |
stances: armed S, fired F (on_hit 3, on_gc 1), expired E | brain share of spoken lines P %` — the seat-side
figures from game.jsonl (`say`, `say_to`, `say_offered`) and the seat logs' `say … dropped` lines, the voice-side
ones from voice-0.jsonl (`spoke` records already carry `source`; `skipped … dice (brain|stance …)`; the `noted
kind=stance` records). The Sweeper's manifests-vs-ledger census, split by source, then says which stock the
brains choose — the input to the staples lines and the chains work that follow.

## 8. Order of work (one sitting each; suite green; a human game between steps)

1. `say-menu.json` (ids + glosses, core / situations / deal / loop / needs_target / stances / numbers),
   `rules.load_say_menu()`, the voice drops its menu copies and validates by library; tests: every id in every
   group exists with a `when` in harry, bill, lily, joshua; the pinned-copy tests retired. No behaviour change.
2. Contextual menu: the ring cursor and `_situations`, the offer builder (`rules.build_user_prompt(…,
   say_menu=…)`), offered-set validation, `to` validation, the cap, `say_to` / `say_card` / `say_offered` on the
   record, the consumed gate, voice intake with `evict=False`, hygiene line, `ARENA_SAY_MENU` + banner + README.
   Game: the dropped-say notes, the hygiene line, decision latency vs the previous game.
3. Addressed lines: `ADDRESS_SWAP["attack-them"]`, `PROPOSAL_LINES |= {attack-them}`, the brain-source swap
   without the roll, the threat pin line, the question-line rule. Game.
4. Stances: contract, validation, record, shape (a) at the six own-line sites, shape (b) in `after_spoken`,
   lifetime, the fire counter in `tuning.json`, checkpoint, `noted` records, `ANCHORED_SOURCES`, hygiene mirror,
   `ARENA_STANCES` + banner + README. Game.
5. Docs: INTERACTIVE-ARENA (table talk), the brief, BUG-LOG rows per step, this file's §10/§12.

Tests that pin today and change with the steps (F28): `test_say_key.py` (the one-line offer, harry-only ids, log
wordings), `test_events_hardening.py` (the pinned copy, targeted → leader, `deal` with nobody standing),
`test_deals_seat.py` (`counter-offer` in the menu and friends), `test_hardening.LaunchBanner` and
`test_tuning.TheOperatorKnobs` (knobs), `test_barks_runtime` eviction and ordering cases if `evict` changes.

Not in scope here (next items, in Ben's order): the staples voice lines (Sol Ring, Arcane Signet, Command
Tower), the dialogue chains (arcs, closers, tone pools), the chat reply's own latency (the brain's turn, not the
relay). Also noted by the review and parked: after a session rotation the seat forgets what it said at the table
(`record.render` carries no says — cheap to append if continuity matters, F27).

## 9. Questions for Ben (2026-10-16) — answered in §10

1. May a seat address you? 2. Menu sizes 14 / 8? 3. Stances on every say window? 4. Caps two says / three
fires? 5. Defaults on while testing?

## 10. Ben's decisions (2026-10-18)

1. **A seat may address the human** (`to: 0`): yes.
2. **Order:** the data file, then the contextual menu, then addressed lines, then stances — a human game after each.
3. **Caps:** two brain says per seat per turn, three stance fires per seat per turn — "a fine starting place".
   Standing constraint from the same answer: "we may be inducing more governance-layer insanity into a system
   that is already so complex we have had to rationalize it multiple times" — **no new governance layer**: reuse
   the existing guards (`said_this_turn`, the seat guard, `ANCHORED_SOURCES`); the caps are two counters and
   nothing else; anything that smells like a second governor is out.
4. **Stances** offered on every say window; yard it back if it is a problem.
5. **Menu sizes:** 14 on a charged window, 8 on a quiet one; the hygiene line decides whether the brains tail the list.
6. **Defaults:** `ARENA_SAY_MENU=contextual` and `ARENA_STANCES=on` from the first build, while testing.
7. **Process:** before any code, a Fable review of this plan against the code (errors, corner cases, conflicts
   with the existing bark/speaking logic); the revisions are discussed with Ben; only then execution.

## 11. The review (2026-10-18) and what changed because of it

Full report: `docs/reviews/2026-10-18-brain-authored-talk-review.md` (read-only, 50 tool uses; it ran
`test_say_key`, `test_events_hardening`, `test_tuning.TheOperatorKnobs` green on the tree). Every id the plan
names exists in all four voices. Findings → revisions:

| Finding | Was | Now |
|---|---|---|
| F1 P0 — a `continue` at the hook would skip ledger / kill / loop bookkeeping | hooks at the top of each `scan_events` branch | no hooks, no `continue`: shape (a) substitutes at the holder's own-line sites, shape (b) is the pre-chosen chain reply (§5) |
| F2 P0 — "replaces the dice line" was false for five triggers (the actor owns the line; reactions are chain replies) | one shape for eight triggers | the trigger table names the shape per trigger; the (b) latency and its miss case are stated; Q4 |
| F3 P1 — brain lines are governed, not certain | "anchored, outside the governor" | §0 corrected; Q1 decides governed vs state (one clause either way) |
| F4 P1 — an anchored brain bark evicts every pending bark | not mentioned | `evict=False` for brain and stance barks |
| F5 P1 — the memos could not see the hitter, mistook resolution for a counter, and cmc / commander are not in the request | three memos + `state.combat` | the observer's event ring with one seq cursor; the gc flags read once from the roster's dossiers |
| F6 / F7 P1 — procedural ids double or pre-empt the ring's lines, override `TABLE_P`, lose ctx, contradict the answer | own-action ids in the lists | the menu is reactions / jabs / calls / addressed only; Q2 |
| F8 P1 — question lines at the human hang; the patter already pins the human | `to: 0` for any id | never for `QUESTION_LINES`; §0 corrected |
| F9 P1 — a second swap table and a split reply regime for `attack-them` | a `named` table | `ADDRESS_SWAP` + `PROPOSAL_LINES` gain one entry each; the brain-source roll is skipped; the pin is one line |
| F10 P1 — glosses misread (`grudge`, `thats-mean`, `brace`, `why-me`), ungated ids, `deal` in a list | manifests' `when` | prompt-grade glosses in the file; lists re-homed and gated; Q3 |
| F11 P1 — the deal and loop ids would fall off the menu | not in the file | explicit `deal` and `loop` groups, offered with their prompts |
| F12 P1 — a voice-side knob fails `test_tuning` and the five-knob rule | `ARENA_STANCES` read by the voice | both knobs seat-side only; the fire cap in `tuning.json` |
| F13 P1 — prompt cost ~2× understated; latency is the real cost | 170 / 6k | 250–300 + 55; ~13k per seat per game; measure decision latency against a `fixed` control |
| F14 P1 — "14 after the core" ambiguous | 8 + 14 | 14 total, situations first; `say_offered` on the record |
| F15–F30 P2 | — | card ctx by name; checkpoint; `noted` records; hygiene mirror; staleness order; consumed gate; joshua in the test; `to` validation from `opponents[]`; the ring's blind spots stated; the dossier read stated; brief and chat wording; `heads-up` out; the test list; low-effort windows get the core; the leader needs a unique max |

## 12. Open questions for Ben (priority order; the recommendation first)

1. **Governed or state?** Today a brain line can be diced away at 0.5 when the table is quiet or over budget
   (F3). Recommendation: **state** — `brain` and `stance` join the ungoverned clause like the deal lines; the
   brain authored it, the two counters are the volume control, the seat guard and `said_this_turn` still hold.
2. **Reactions only, or may the brain choose its procedural lines** (poke, big-swing, cast-big, no-blocks…) with
   certainty instead of `TABLE_P` odds (F6)? Recommendation: **reactions, jabs, calls and addressed lines only**;
   the ring speaks the procedural lines with the right ctx. If Ben wants the brain to pick its own cast or attack
   line, that is a stance by another name and can be added as `on_my_attack` / `on_my_cast` later.
3. **`deal` in the `behind` list?** A one-word say that strikes a small-talk truce with a brain-chosen party.
   Recommendation: **out**; the deal paths own it (the DEAL OFFER line already lets a brain propose).
4. **Stance miss case.** Shape (b) fires only when the actor's line played. Recommendation: accept for the first
   game and read the voice's `skipped … dice` count for those openers; if it matters, one rule at the actor-line
   sites — when the actor's line was diced away and a holder has the stance, speak the stance as the opener with
   the event's ctx (a few lines per site, still no `continue`).
5. **Stance lifetime.** "The rest of this turn" is often seconds, since most say windows are on others' turns.
   Recommendation: a stance lives until it fires, is replaced by a new one on the same trigger, or **the holder's
   own turn begins** — at most one round.
6. **The human as a target:** everything but question lines — confirm.
7. **One knob or two:** `ARENA_SAY_MENU=contextual|fixed` and `ARENA_STANCES=on|off`, both seat-side.
   Recommendation: two, so stances can be yarded back alone (decision 4).
8. **Where the numbers live:** `max_says_per_turn` in `say-menu.json` (a seat number), `stance_fires_per_turn` in
   `tuning.json` (a voice number) — each file owns its side. Confirm.

## 13. Ben's answers (2026-10-18) and the rule they add

1. **State.** `brain` and `stance` join the ungoverned clause (`scheduler.py:707`), like the deal lines.
2. **Not reactions only — "We want more brain speech."** The procedural / own-action lines come back onto the
   menu. The rule that makes this safe (F6, F7): **a brain's own-action say is not spoken when the record lands;
   it is HELD as the seat's pre-chosen line for its own next matching event and spoken there, at the site where
   the ring speaks that seat's own line today, with the event's ctx and p = 1.0.** `big-swing` / `attack-you` /
   `poke` said on DECLARE_ATTACKERS play at the seat's `attack` event (so `open` is known and "no blocks" can
   answer); `commander-cast` / `game-changer` / `cast-big` / `engine-online` / `in-response` said on CAST_SPELL
   or REACT play at the seat's `cast` (or stack) event with the card (so the NAMED line plays, once);
   `counter` at its `countered` event; `removal` / `sweep` at its `left` event; `i-broke-it` at `_deal_broken`'s
   breaker line; `no-blocks` / `take-it` / `landed-hit` at the sites that speak them. A held line that finds no
   matching event within the turn expires silently (`noted kind=say why=expired`) — a line for an action that
   never happened is never spoken, which is all F7 asked. The ring's dice for that seat's own line are replaced by
   the brain's choice (certainty — the point of "more brain speech"); the other seats' reactions and the chains
   run as today. Reactions, jabs, calls and addressed lines are spoken when the record lands, as before.
3. **`deal` out** of the situation lists.
4. **Accept the stance miss case** (shape (b) fires only when the actor's line played).
5. **Lifetime settled:** a stance lives until it fires, is replaced on the same trigger, or the holder's own turn
   begins — at most one round. (Held own-action lines live until the turn changes.)
6. **The human as a target:** everything but the question lines.
7. **Two knobs for now.** Ben: "we may need to make yet another flattening and simplification of all of the
   governance logic. Let's see how it all feels before we start redoing the governance." — no governance work in
   this plan beyond the two counters and the one ungoverned clause.
8. **Numbers** as proposed: `max_says_per_turn` in `say-menu.json`, `stance_fires_per_turn` in `tuning.json`.
