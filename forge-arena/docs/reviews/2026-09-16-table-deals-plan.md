# Table deals — the player makes deals through the Advisor chat, and the seats keep or break them knowingly

**Date:** 2026-09-16. **Status:** IN EXECUTION (Ben's go, same day; decisions in §11). **Owner:** Ben. **Branch:** `experimental/voicework2`
(after the hardening round; before or after the 4.2 merge is Ben's call — nothing here touches Java).

Ben: "The seats being able to make deals feels like a huge leap in verisimilitude." Today the seats
strike truces in the VOICE layer only: "Deal, Urza? Don't hit me, I don't hit you" → "Deal. For one
turn." is remembered for eight turns (`scheduler.py` `_deals`, `DEAL_TURNS`) and an attack across it
earns "You promised! Liar!" (`events.py` you-promised). The brain that "promised" never heard the
promise — the betrayal is a coincidence the table dresses up. The player cannot deal at all.

## 1. What it should feel like

- **You propose.** In the Advisor chat: `@urza peace for a turn?` or `deal urza: don't attack me this
  turn and I won't attack you`. Joshua does not answer it; he is a ghost outside the game. He relays.
- **The seat answers in its own voice**, at its next decision, and MEANS it: "Deal. For one turn."
  or "No deal, you're the threat." The answer is the brain's, spoken through the seat's `say` line.
- **The seat then plays to it** — or breaks it on purpose, knowing the table will call it. A brain
  that accepts and then attacks you is choosing betrayal, and the seat's "I promise nothing" or the
  table's "You promised! Liar!" lands on a real decision.
- **Seat-to-seat deals become real the same way**: when the voice layer records a truce between two
  AI seats, both brains are told, once, in their next request.
- **You are told what was agreed and when it lapses**, in the Advisor panel, so a promise is a fact
  on your screen, not something you have to remember you heard.

## 2. Vocabulary — what a deal can be (v1)

Keep the terms few and mechanical so the runner can check them and the brain cannot lawyer them:

| Deal | Meaning the runner enforces / observes | Lapses |
|---|---|---|
| `truce` (default) | neither side ATTACKS the other (combat damage). Spells, abilities, blocks, pings stay legal — the table already treats "don't hit me" this way | after N of the SEAT's turns (default 1, max 3); or at once when either side attacks the other |
| `no-target` | neither side targets the other's permanents or player with spells/abilities | same |
| `alliance` | both: truce + no-target | same |

Not in v1: kill-target pacts ("we both hit Giada"), resource gifts, conditional deals. Those need
enforcement the runner cannot check and invite the brain to invent terms. The `say` menu already has
`deal`, `promise`, `take-the-deal`, `no-deal`, `you-promised`.

## 3. The channels — three that exist, one to add

1. **You → Joshua (exists).** The Advisor tab's chat writes `logs/control/ask/ask-<ts>-<n>.json`
   `{"ask": text}`; `advisor_runner._handle_asks` → `_answer_ask` prompts the advisor brain. **Change:**
   `_handle_asks` recognises a deal proposal FIRST (`@<commander|seat> …`, or a line starting `deal`
   naming a commander) and routes it as a **deal message**, not a question. Anything else stays an ask.
2. **Joshua → a seat (ADD).** A per-seat notes file the seat runner already has the shape for:
   `mailbox/seat-<n>/notes/<ts>-<kind>.json` — the runner reads it where it builds `_runner_note`
   (today an in-process string: the LOOP OFFER, LOOP PAUSED). New kinds: `deal-offer`, `deal-struck`,
   `deal-lapsed`, `deal-broken`. The advisor runner writes the offer; the voice runner (which already
   owns the truce memory) writes struck/lapsed/broken for BOTH parties. One writer per kind, no races.
3. **A seat → the table (exists).** The seat's answer to a deal is a `say` id in its decision
   (`take-the-deal` / `no-deal` / `promise`) — validated, recorded in `game.jsonl`, voiced by the voice
   runner as an anchored line (source `brain`). **Change:** a new answer key `"deal": {"with": 0,
   "kind": "truce", "turns": 1, "accept": true|false}` beside `say`, so the runner does not have to
   infer the decision from a wording. The seat runner validates it (the offer must exist, the terms may
   only be tightened — fewer turns — never widened) and writes it to `game.jsonl` like `say`.
4. **The seat → you (exists).** The advisor runner already tails `game.jsonl` for the digest; a
   `deal` record becomes one panel line: `[t7 · Urza] accepts: truce, 1 turn (until Urza's next turn ends)`
   and Joshua's colour may mention it, as an observer ("Urza took your deal; he still has a Wurmcoil").

## 4. The deal record — one source of truth

The voice runner is the single owner of table memory today (`_deals`, checkpointed). It becomes the
**deal ledger**: `logs/deals.jsonl` (append-only, archived by arena-stop) with records
`{ts, turn, kind: "offer|struck|refused|lapsed|broken", between: [a, b], terms: {...}, by, seq}`, plus
the live `_deals` map extended from `(a, b) → struck_turn` to `(a, b) → {kind, until_turn_of, struck}`.
Sources of a struck deal: (i) a `deal` answer from a seat brain accepting the player's offer;
(ii) the existing voice-layer chain `deal → take-the-deal/promise` between two AI seats (today's
path, kept — it becomes the "small talk" way seats deal with each other, and now it TELLS both brains).
Breaks are detected where they are today (`events.py`: an attack across a truce → `you-promised`),
extended for `no-target` (a `cast`/stack event whose targets include the other party). A break writes
`deal-broken` to both notes files; a lapse writes `deal-lapsed`.

## 5. What the brains are told, exactly (prompt budget ≤ 120 tokens each)

- **Offer (once, in the next request):** `RUNNER NOTE: Player One (seat 0) offers a TRUCE for 1 of
  your turns: neither of you attacks the other. Answer with "deal": {"with": 0, "kind": "truce",
  "turns": 1, "accept": true} or "accept": false, and a "say" (take-the-deal / no-deal). Decide as this
  deck would: a truce with the threat is a mistake; a truce with the weakest seat buys tempo.`
- **Struck (both parties, once):** `RUNNER NOTE: you have a TRUCE with Player One (seat 0) until the
  end of your next turn: do not attack them. Breaking it is a choice the table will remember.`
- **Broken by the other side:** `RUNNER NOTE: Player One broke your truce (attacked you turn 8). You
  owe them nothing.` **Broken by this seat** (it attacked across it): nothing — it chose.
- **Lapsed:** `RUNNER NOTE: your truce with Player One has ended.`
- `seat-brief.md` gets one paragraph under TABLE TALK: deals are real, kept by default, broken only
  on purpose and for a reason worth saying; never invent terms; the human cannot hear your reasoning,
  only your `say`.

The advisor's brief gets one line: the human's deal messages are relayed, never answered; Joshua may
comment on a struck or broken deal as an observer.

## 6. Enforcement — observe, never force

The runner never overrides a brain's decision to honour a deal (that would be the Executive problem
again). It (a) tells the brain, (b) records what happens, (c) lets the table react. The one mechanical
hand: while a truce with the human is in force, the seat runner's affordability/attack fastpaths
(anything that answers DECLARE_ATTACKERS without the model) must NOT auto-attack the human — those
windows go to the model with the note. Reason: a fastpath cannot "choose" betrayal.

## 7. Voice

- New table ids, three voices × four wordings: `deal-with-you` (a seat accepting the player's offer,
  addressed: "Deal, Player One. One turn."), `no-deal-with-you`, `deal-over` ("Our truce is done."),
  `you-broke-it` (the human attacked across a truce — the seat, angry), `i-broke-it` ("I know what I
  promised. I lied."). ~60 renders. The generic `promise`/`take-the-deal`/`no-deal` keep serving
  seat-to-seat.
- The chain table: `deal-with-you` invites a bystander's `hah`/`tsk` atom and, at 0.35, a `youre-next`
  jab at the seat that dealt; `you-broke-it` invites `laugh` from a bystander.
- Joshua: one colour line at most per struck/broken deal, from the existing colour path, no new audio.

## 8. Failure modes, decided up front

- The brain ignores the offer (no `deal` key): the runner records `refused` after the window and the
  seat says nothing; the panel shows "Urza did not answer." Never re-ask.
- The human offers to a dead seat, a seat mid-loop, or twice in a turn: the advisor panel says so;
  nothing is written.
- The brain "accepts" then attacks the same turn: recorded `broken`, `you-promised` fires, the panel
  says "Urza broke the truce", and Joshua may note it. That is a feature.
- A deal outlives a runner restart: `_deals` is already in the checkpoint; the ledger file is the
  fallback.
- Executive on: the advisor plays your seat — it may still relay your typed offers (you are the
  player even when the advisor holds the mouse), and it must itself honour a truce it accepted on
  your behalf (the seat-0 runner gets the same notes).

## 9. Order of work (one sitting each, suite green, no Java)

1. **Ledger + notes channel** (voice runner writes `deals.jsonl` and `mailbox/seat-<n>/notes/`; seat
   runner reads notes into `_runner_note`; checkpoint carries the extended `_deals`). Tests: struck →
   both notes; lapsed; broken; restart keeps it.
2. **Seat answer key `deal`** (rules.py validation, runner.py record, brief paragraph; the fastpath
   hand-off in §6). Tests: accept/refuse/tighten/widen-refused/no-answer.
3. **Advisor relay** (`_handle_asks` parses `@commander` / `deal …`, resolves the commander to a seat
   via `address.json`, writes the offer note, panel lines for offer/answer/struck/broken/lapsed; the
   advisor brief line). Tests: parse, resolve, dead seat, twice in a turn, panel text.
4. **Voice** (five ids rendered; `deal` answers voiced; chain rows; Joshua colour). Tests: RenderedTable
   count pins, the chain rows, a struck deal from a `deal` record voices `deal-with-you` addressed.
5. **Game 50**: Ben offers Urza a truce on turn 3 and Purphoros one on turn 6; we read the ledger,
   the panel, and whether a brain broke one on purpose.

Rough size: ~600 lines across advisor_runner.py, seatd/runner.py + rules.py, voice/scheduler.py +
events.py, table_lines.py; ~60 renders; four test files. Two Fable implementers (advisor+seatd,
voice), one critic, then me. Estimated one working session.

## 10. Questions for Ben

1. Deal kinds: truce only for v1, or truce + no-target + alliance as tabled?
2. Duration unit: the SEAT's turns (proposed — unambiguous to the brain) or full table rounds?
3. May a seat COUNTER-offer ("two turns, not one")? Proposed: no in v1; accept/refuse only, tightening allowed.
4. Should Joshua ever advise you on a deal ("don't trust Purphoros at 40 life")? Proposed: only if you ask him.
5. Executive holding your seat: may it accept a seat's offer on your behalf, or only relay yours?
6. Build now on the experimental branch before the merge, or after 4.2 ships?

## 11. Ben's decisions (2026-09-16) and the contract the lanes build to

1. **All three kinds** in v1: `truce`, `no-target`, `alliance`.
2. **Duration, both forms:** `rounds: N` (N of the SEAT's own turns from the strike — "for one turn"
   as the table already says it) OR `until_turn: N` (an absolute game turn, inclusive). Exactly one.
   The ledger stores both resolved: `until_turn` is computed at the strike for a `rounds` deal so the
   lapse check is one comparison.
3. **Counter-offers, tried:** a brain may answer `accept: false, counter: {kind, rounds|until_turn}`;
   the counter reaches the player's panel; the player accepts with `@urza accept` (or refuses by
   ignoring it — it lapses at the end of the turn). One counter per offer; a counter to a counter is a
   refusal. Cut if it does not play well.
4. **Joshua advises on every deal you strike or have broken** — Ben revised this after game 50 (the 30 %
   roll left the advisor silent at the moment the player acts on his read: "it sounds more like critical
   state information that needs to be delivered"). One line through the colour path, every time; the
   offer itself is relayed, never answered; always when you ask him.
5. **Executive may accept deals:** while Executive holds seat 0, a seat's offer to the player goes to
   the seat-0 runner like any seat's, and its `deal` answer is VOICED — in Joshua's voice, since in
   Executive mode Joshua is the player at the table (Ben: "this preempts Joshua's ghost-like presence").
   Joshua gets three deal lines rendered (accept / refuse / counter). Executive may not PROPOSE deals
   (the player's typed offers are still relayed as the player's).
6. **Build now** on `experimental/voicework2`; this branch is the experimental release (four voices,
   deals, more AI interactivity), rollback to 4.1 possible on player feedback. After this feature:
   mine the five-lens reports for every feature suggestion, stack-rank by benefit minus risk/effort
   with Ben, decide what else ships in the experimental release.

### The contract

**Notes file (advisor/voice → a seat runner):** `mailbox/seat-<n>/notes/<ts_ms>-<kind>.json`, one JSON
object, consumed (deleted) by the seat runner when it builds the next prompt; kinds and bodies:
- `deal-offer`: `{"kind":"deal-offer","from":0,"to":n,"deal":{"kind":"truce|no-target|alliance","rounds":1}|{"…","until_turn":12},"offer_id":"<ts>-<from>-<to>","text":"<the player's words>","turn":7}`
- `deal-counter` (to the player's seat-0 runner only in Executive; else the advisor panel): same + `"counter": true`
- `deal-struck`: `{"kind":"deal-struck","between":[a,b],"deal":{...,"until_turn":N},"offer_id":…,"turn":…}`
- `deal-broken`: `{"kind":"deal-broken","between":[a,b],"by":a,"how":"attack|target","turn":…}`
- `deal-lapsed`: `{"kind":"deal-lapsed","between":[a,b],"turn":…}`
The seat runner renders each as one RUNNER NOTE sentence (§5 wording) and drops the file.

**Seat answer key:** `"deal": {"offer_id": "...", "accept": true}` | `{"offer_id": "...", "accept": false}` |
`{"offer_id": "...", "accept": false, "counter": {"kind": "...", "rounds": N} | {"kind": "...", "until_turn": N}}`.
Validation (rules.py): the offer_id must be a pending offer for this seat; a counter may change kind
or duration once. Recorded in `game.jsonl` as `"deal": {...}` beside `say`; stripped from the engine
answer. The seat also adds a `say` (take-the-deal / no-deal / a new `counter-offer` id).

**Ledger (voice runner owns it):** `logs/deals.jsonl`, append-only, records
`{ts, turn, event: "offer|counter|struck|refused|lapsed|broken|expired", between:[a,b], by, deal:{kind, until_turn, rounds?}, offer_id, seq}`;
live `_deals: (a,b) -> {"kind","until_turn","struck","offer_id"}` both directions, checkpointed.
Lapse: at the end of the turn `until_turn` (turn roll to until_turn+1). Break: attack event across a
truce/alliance; a cast/stack `targets` including the other party across a no-target/alliance.

**Advisor grammar (in the Advisor chat):** `@<commander-or-seat> <words>` — words parsed for a kind
(`truce|peace|no target|alliance|ally`, default truce), a duration (`N turn(s)|round(s)` → rounds N;
`until turn N` → until_turn; default rounds 1), or `accept` / `no` for a pending counter. Unparsable →
Joshua answers it as a normal ask. A dead seat, a seat with an open offer already, or Executive on
for the target's own offers → a panel line, no note.

**Voice ids (table sub-library, 3 voices × 4):** `deal-with-you`, `no-deal-with-you`, `counter-offer`,
`deal-over`, `you-broke-it`, `i-broke-it`. **Joshua (stock, 3 wordings each):** `joshua-deal-yes`,
`joshua-deal-no`, `joshua-deal-counter` (Executive mode only). Chains: `deal-with-you` → bystander `hah`/`tsk`
atom and `youre-next` at 0.35; `you-broke-it` → bystander `laugh`.


---

## 12. Seat-made offers (built 2026-09-16, after Ben: "seats offering each other and me deals")

The plan above gave the seats the answering half only. This section adds the proposing half; everything
downstream (answers, the ledger, notes, lapse, break, the spoken answers) is unchanged.

**Seat side (`runner/seatd`).** On a `CAST_SPELL` or `DECLARE_ATTACKERS` window of its own turn, from turn
`PROPOSE_MIN_TURN` (3), with no offer of its own open and none pending against it, and at least
`PROPOSE_EVERY_TURNS` (6) table turns after its last, the prompt carries one line
(`rules.deal_propose_line`) naming the living parties. The brain may answer
`"deal": {"propose": {"to": n, "kind": "truce|no-target|alliance", "rounds": 1-3 | "until_turn": N, "text"?: "…"}}`
plus `"say": "deal"`. `rules.validate_proposal` checks the party (another living seat, seat 0 included), the
kind and exactly one duration. The runner writes the SAME `deal-offer` note the advisor writes for the player
into `mailbox/seat-<n>/notes/` (`from` = the seat), records
`{"type": "DEAL", "deal": {"offer_id": "<ts>-<from>-<to>", "propose": true, "with": n, "terms": {...}, "text"?}}`
in game.jsonl, and remembers its one open offer (`_my_offers`), forgotten a turn later or on the answer's
note. New note kind `deal-refused` ("Urza refused your offer of a truce."). Offer notes two turns old are
dropped at ingest (a note for seat 0 waits for the Executive; stale by then). Seat 0 never proposes.

**Voice side (`runner/voice`).** `deal_answer` routes `propose` to `deal_proposal`: an `offer` ledger record;
an offer to the player is remembered beside the counters (`_deal_counters`, `proposal: true`, one turn
longer) so the advisor's control file answers it; the seat speaks the `deal` line to the party
(address-swapped "Deal, Urza?"), ungoverned (`DEAL_PROPOSE_LINE`), terminal — the voice chain's small-talk
truce never answers a real offer. The `say: deal` beside it stays quiet (`DEAL_SAY_TWINS`). The control
directory now takes `<ts>-refuse.json` too: `refused` (by 0) in the ledger and a `deal-refused` note to the
seat. A DEAL answer from seat 0 (the Executive) pops the remembered offer so nothing expires twice.

**Advisor side (`runner/advisor_runner.py`).** `_on_seat_offer`: seat to seat → one `[table]` line
("Urza offers Purphoros truce, 2 turns"). Seat to player → `[Purphoros] offers you alliance until turn 10 —
"…" (@purphoros accept/no)`, an `_offers` entry with status `proposed` (lapses at the end of the following
turn: "Purphoros's offer lapsed"), and Joshua's assessment at once (no dice — state). `@purphoros accept` /
`@purphoros no` answer a proposal as they answer a counter (statuses `offer-accepted` / `offer-refused`,
control file `<ts>-accept|refuse.json`). Executive on → "the Executive answers for you", no entry: the
seat-0 runner answers the note itself. The player's own `refused` ledger record is not echoed; a proposal's
`expired` record is not repeated after the tick's lapse line.

**Tests:** `SeatOffers` in test_deals_seat.py, `ASeatsOwnOffer` in test_deals_voice.py, `SeatOffers` in
test_deals_advisor.py. **Not rendered:** kind-specific offer wordings; the generic/named `deal` line serves.
**Next:** prove it in a live game (a seat proposes, another answers; a seat proposes to Ben, he answers in
the chat); the Yes/No pane (stack rank #13) is the answer surface for later.

## 13. Turns vs rounds (2026-09-18)

Ben's ruling: a TURN is one player's turn on the game's turn counter; a ROUND is one turn for every living player. §2's `rounds: N` is unchanged (resolved at the strike to strike + N × living). New: `turns: N` (1–12), resolved at the strike to strike + N; the advisor grammar reads `N turns` as turns and `N rounds` as rounds (before this both meant rounds); every human-facing duration is labelled in its unit with the resolved end turn; the brains may counter/propose in turns; a deal accepted after its named turn has passed is `expired`, not struck. Rationale and edge cases: BUG-LOG 2026-09-18.
