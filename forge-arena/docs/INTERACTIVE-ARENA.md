# Interactive Arena — LLM/agent-piloted Forge seats

Play a live game of Magic (4-player Commander) in the **Forge desktop GUI**
where one or more opponents are driven by an **external agent** (an LLM, a
script, anything) through a simple **file-based mailbox protocol**. A human
plays a normal GUI seat; the agent seats are ordinary "AI" seats whose
controller, instead of thinking locally, writes each decision to a file and
blocks for an answer.

First proven end-to-end 2026-08-06: a human piloting Selvala vs three
Claude-Opus-piloted opponents (Purphoros / Giada / Urza), a full 24-turn game
won by the human via a Selvala + Umbral Mantle + Craterhoof combo turn.

Second session 2026-08-06 (v2, "fast loop"): validated `REACT`, `CHOOSE_CARD`,
and deck-aware casting live; **hardened the reactive gate**; and cut end-to-end
latency (75ms outbox poll, 0.15s seat-daemon inbox poll — was 0.5s until 2026-08-13, ~2s brain drain, brains self-serving
their own inboxes). The distilled learnings from both sessions
live under **Operational learnings** below — read that and the **protocol
contract** first if you are picking this up. (**Next architecture** further
down is the retained PRE-SHIP design — historical, not a roadmap.)

> Status (2026-09-04): SHIPPED — this seam is the core of the
> **forge-light-llm** distributable (v1 2026-08-12 → v3.3.2 2026-09-01 on R2
> as `-latest`, dated key `forge-light-llm-20260901.tar.gz`, source
> `0a1cfac3061`). v3.3.3 is PENDING (BUG-LOG BL-17): the "Unreleased" section
> of PATCH-NOTES is written, the 2026-09-04 interactive batch (2bc78d92188)
> awaits its Maven gate, and the K'rrik-class payer fix (BL-01) is not
> started. User-facing docs: `packaging/README.md` + `packaging/PATCH-NOTES.md`.
> Engineering inventory: [INVENTORY.md](INVENTORY.md). Upstream-merge safety:
> [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md). Built on Card-Forge/forge (GPL-3.0);
> non-commercial fan content under WotC's Fan Content Policy. Any distribution
> is source-available under GPL-3.0.

## Why this exists

There is no public source of good EDH turn-by-turn play to *observe* — because
no engine plays EDH well. So instead of observing good play, this lets you
**produce and sit across from it**: an agent that assembles combos, ramps,
assesses threats, and plays a real game you can watch and interrogate. It is the
"teacher" that generates the intent the deterministic combo-pilot runner (the
rest of forge-arena) must eventually reproduce without an LLM.

## Architecture

The seam's core lives in `forge-arena/src/main/java/forge/arena/interactive/`
and rides the same controller-injection seam the headless arena uses.
**The original "no parent-module patches" rule was deliberately dropped**
(2026-08-17, first for the vanished-commander engine fix): the fork now
carries deliberate patches outside forge-arena. The counts are NOT restated
here — they drifted every time they were; the authoritative list, with
per-file rationale and guarding tests, is [INVENTORY.md §1](INVENTORY.md);
the merge-safety plan is [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md).

| File | Role |
|---|---|
| `MailboxProtocol.java` | The file bus. Per-seat `inbox/`+`outbox/`; ONE instance per seat directory (`forSeat` caches; note 63); the constructor sweeps stale `resp-*`/`*.tmp` from the outbox (note 66); atomic writes (temp+rename); poll for the response; timeout → `null` (caller falls back to stock); heartbeat age check (note 58). Request/response wire records. No Forge imports — pure transport. |
| `MailboxController.java` | `extends forge.ai.PlayerControllerAi`. Overrides the top-level decisions (`chooseSpellAbilityToPlay`, `mulliganKeepHand`, `declareAttackers`, `declareBlockers`) **plus high-value sub-choices** (`chooseSingleEntityForEffect`, `chooseEntitiesForEffect`, `chooseModeForAbility`, `chooseSingleCardForZoneChange`), and since 2026-09-04 `orderSimultaneousSa` and `chooseColor`/`chooseColorAllowColorless` (notes 61, 62). Serializes a hidden-info-safe state and exchanges it over the bus. **Every override times out to `super` (stock AI)** so a silent/slow brain never hangs the game. |
| `MailboxLobbyPlayer.java` | `extends forge.ai.LobbyPlayerAi`. Injects the controller via `IGameEntitiesFactory.createIngamePlayer` (the seam both headless and GUI paths converge on — `Game.java`), so a mailbox seat is honored in a GUI game with no engine/GUI patch. `createMindSlaveController` routes a controlled seat to the master's bus with the master `Player` (note 63). |
| `GuiPilotMatch.java` | `main(...)` launcher: bootstraps the desktop GUI, seats a human at seat 0 and `MailboxLobbyPlayer`s at seats 1–3 (or all four in `--all-ai`), builds the roster (`DECKS` = Urza, Giada, Purphoros, Selvala; `buildRoster` per note 71; override via `arena.seat.decks` / `ARENA_SEAT_DECKS`), verifies every deck loads at 100 real cards (`verifyRoster` → `mailbox/launch-status.json`), and starts the match. |
| `ObserverSnapshot.java` | Event-bus-driven public snapshot (`mailbox/observer-state.json`): per-seat life/board/eliminated, whose turn — the pre-planning + dashboard + launch-liveness feed. Written on every event whose serialized state (timestamp aside) differs from the last write; no timer (note 64). |
| `GameResultSpool.java` | At game end writes `runner/results/game-<ts>-<pid>.json` (placement groups from `Game.lostPlayers`, control typing by LobbyPlayer class) — the ELO applier's input. Skips cleanly when no absolute output dir is configured (tests). |
| `AdvisorControllerHuman.java` / `AdvisorFeed.java` / `AdvisorLobbyPlayer.java` | The seat-0 **shadow feed** for the AI Advisor: mirrors the human's decision windows read-only through the same `buildState` projection (fairness lives in one place). No return channel — the advisor can never act or stall. |

Parent-module residents (see INVENTORY §1b): `forge-ai/TapCostPreference`
(tap-payment pre-selection hook consulted by `AiCostDecision`), and in
forge-gui-desktop the `AiControlFile` protocol + `V/CAiControl` (AI panel:
per-seat model/effort steppers, token/cost telemetry, ELO line) and
`V/CAdvisor` + `AdvisorLogTail` (Advisor tab + pause button).

### The hybrid control model (important)

The mailbox controller intercepts the seat's **own main phases** (MAIN1 /
MAIN2, empty stack), **mulligan**, **combat declaration**, and a set of
**high-value sub-choices** the seat makes while resolving its own effects (copy
choice, choose-a-permanent, modal/charm modes, tutor/fetch selection). It also
intercepts **reactive (instant-speed) windows**: when an OPPONENT has a
spell/ability on the stack and the seat holds a castable instant-speed response,
the seat is consulted (`REACT`) — and, **v3 (fix #13)**: at TACTICAL windows too —
every combat step and the end step, any player's turn, empty stack — whenever a
real, affordable, non-mana action exists (fogs, combat tricks, saves, end-step
flash; the request carries a `state.combat` block with attackers/defenders/
blocks). **Stock never casts for a mailbox seat anymore**: windows not worth the
brain's time are clean passes, not stock free-play (stock had withheld a
game-saving fog and burned a held Silence at dead timing). Stock still takes the
seat over wholesale on brain timeout — that degradation path is unchanged.

Consequences:
- The agent plays **sorcery-speed strategy AND its own instant-speed responses**
  to opponents' spells (counter, protect, removal-in-response), at agent quality.
  Still on stock (bounded out to avoid flooding): proactively flashing into an
  empty stack outside the tactical windows (opponents' main/upkeep/draw with
  nothing on the stack). Responding during the agent's own turn IS mailboxed —
  the reactive gate keys on who owns the stack object, not whose turn it is.
- **Sub-choices now the agent's:** which creature to copy / choose (Glasspool
  Mimic, Clone, "choose target creature" resolution effects → `CHOOSE_ENTITY` /
  `CHOOSE_ENTITIES`), which mode of a charm/modal spell (`CHOOSE_MODE`), and
  which card a tutor/search fetches (`CHOOSE_CARD`). These are gated narrowly to
  *genuine* choices (>1 legal option, or an optional single) and, for the entity
  hooks, to card/permanent options only.
- **(2026-08-17) Nearly everything above has since moved to the seat.**
  Spell/ability targeting is seat-owned (notes 14/14b/14c) including **stack
  targeting** — counters aim at the SpellAbility on the stack, never the
  stack-zone card (note 36). The seat also owns its **own triggers** (targeting
  note 34, optional yes/no note 35), pay-or-else costs, confirms, X and
  cost-reduction numbers, discards, face/state picks, and multi-card choices.
  The full current matrix — seat-owned vs deliberately-stock, with rationale —
  is [INVENTORY.md §2](INVENTORY.md). Still stock by choice: multi-target
  spells, whole-DB card naming, combat damage assignment, and mana auto-tap
  source selection (except the TapCostPreference hook). Trigger ordering and
  colour choice moved to the seat on 2026-09-04 (notes 61, 62).

### Fairness

State is built from `SeatViews.of(...)` — the hidden-information-safe read model.
Each agent sees only **its own hand + public board** (opponents' life/poison/
board/creaturePower, the stack). It cannot see opponents' hands, libraries, or
decklists. Enforced structurally by SeatView (ArchUnit-guarded, W8).

## Mailbox protocol (the contract a "brain" implements)

```
<base>/seat-<id>/inbox/req-<n>.json     ← engine writes a decision request
<base>/seat-<id>/outbox/resp-<n>.json   ← brain writes the answer (same <n>)
```
Base dir: system property `arena.mailbox.dir` (default `forge-arena/mailbox`).
Timeout: `arena.mailbox.timeout.sec` (default 300) — on timeout the seat uses
stock AI. The launcher overrides the 300s engine default to **90s** (via
`ARENA_MAILBOX_TIMEOUT` in `arena-play.sh`); both numbers below are that one
knob seen from two places. The engine deletes both files once the response is read.

**Request** (`req-<n>.json`):
```json
{
  "seq": 12, "gameId": "1756950000123-48211-1", "timeoutSec": 90,
  "seat": 3, "turn": 22, "phase": "MAIN1",
  /* gameId = one value per Game (start millis + pid + a per-process serial, note 68) —
     the ONLY new-game signal a reader should trust (plan item 8); timeoutSec = the
     engine's wait, so the runner budgets from what the engine will actually do (item 12) */
  "decisionType": "CAST_SPELL | REACT | MULLIGAN | DECLARE_ATTACKERS | DECLARE_BLOCKERS | CHOOSE_ENTITY | CHOOSE_ENTITIES | CHOOSE_MODE | CHOOSE_CARD | CHOOSE_CARDS | CHOOSE_NUMBER | PAY_UNLESS | CONFIRM",
  "prompt": "…",
  "state": {
    "seat","turn","phase","life","manaPool","untappedManaSources",
    "handSize","handLands","librarySize","ownBoardPower",
    "battlefield":[ …per-card objects… ],
    "hand":[ …per-card objects… ],
    "command":[…names…],"graveyard":[…names…],"exile":[…names…],
    "stack":[…],
    "opponents":[{"seat","life","poison","creaturePower","battlefield":[ …per-card objects… ]}],
    /* + "defenders":[{id,label,type}] for DECLARE_ATTACKERS */
    /* + "attackers":[{id,label}]       for DECLARE_BLOCKERS  */
    /* + "min","max" for CHOOSE_ENTITY/CHOOSE_ENTITIES/CHOOSE_MODE/CHOOSE_CARD(S)/CHOOSE_NUMBER */
    /* + "allowRepeat":bool for CHOOSE_MODE; "destination":<zone> for CHOOSE_CARD(S) */
    /* + "commandZone":[{name,timesCast,nextCastTax}] — own commanders */
    /* + "stackOwners":[seat...], "stackKinds":["trigger"|"spell"|...] — additive stack metadata */
    /* + "stackTargets":[["Name (id)"|"seat N",...],...] — each item's CHOSEN targets, whole chain incl.
       chained multi-target parts and charm-chosen modes; divided amounts appended as " [n]" (note 51) */
    /* + "stackOracle":["<=300-char oracle text",...] — per stack item (note 52: REACT valuation off
       ground truth, not model recall) */
    /* + "symmetryPieces":[{name,controllerSeat,untapped}], "untapNextSeat" — Winter-Orb-class facts */
    /* + effective keywords per card (indestructible/hexproof/ward/protection/evergreens, incl. granted) */
    /* + "confirmMode","triggerText","yesCost","chosenTargets" on CONFIRM(TRIGGER) */
    /* + "confirmMode":"PLAY_FROM_EFFECT" with "spell","free" on may-cast offers (note 49) */
    /* + "manaSources":[{id,name,yield,colors,restricted?,sick?,cost?,count?}] — every UNTAPPED
       producer the seat controls, one activation's yield on the live board (Cradle counts its
       creatures), colors "any"|"colorless"|letters, identical basics collapsed with count;
       "manaAvailableNow" = pool + unrestricted, non-sick, bare-tap yields (the number item 4's
       refusal measures); "ritualsInHand":[{kind:"ritual",name,cost,yield,net,colors} |
       {kind:"multiplier",name,cost}] — Mana-api spells with projected yield, TapsForMana /
       ProduceMana effects flagged with no number (plan item 6; detection by mechanics only) */
    /* + "lastRefused":{name,cost,needed,payableNow,kind,reason} on the CAST_SPELL window right
       after the engine refused the seat's pick (unaffordable, or a failed modal cast); the prompt
       carries the same sentence and that card is omitted from that ONE window (plan item 4) */
    /* + "controllingSeat":N when this seat's decisions are being made by seat N's brain
       (Mindslaver class, CR 721) — the request goes to seat N's mailbox and its prompt opens
       with "YOU ARE CONTROLLING SEAT …" (plan item 11a); + "controllerBoard":{seat,life,
       poison,hand,handSize,battlefield,graveyard,exile,commandZone,librarySize,manaPool,
       manaAvailableNow,manaSources,untappedManaSourceCount} — the MASTER's own board incl.
       its hand, on those requests only (CR 721.3, note 63) */
    /* + "purpose":"TRIGGER_ORDER"|"COLOR" on the two CHOOSE_MODE windows of notes 61/62 */
    /* + "hasCost":bool,"isMine":bool on EVERY CONFIRM — structured facts for the runner's
       punt rule (yes only when free AND mine; plan item 10). Untyped confirms reach the
       seat when their SOURCE is the seat's own spell/ability, never by message text (11d) */
  },
  "options": [ {"id":0,"label":"Pass (do nothing)","cost":null,"type":"PASS"}, … ]
}
```

**Per-card serialization.** `battlefield` (own seat and every opponent) is a list
of one object *per card* (never deduped by name — two Constructs are two entries),
built by reading the real (public) `Card` objects. Each entry:
```json
{
  "id": 217, "name": "Grinning Ignus",
  "power": 2, "toughness": 2, "sick": false,   /* P/T + summoning-sick: creatures only */
  "types": "Creature Elemental",
  "tapped": false,
  "counters": { "P1P1": 2 },                    /* omitted when the card has none */
  "auras": ["Kenrith's Transformation"],        /* Auras/Equipment attached TO this card; omitted when none */
  "abilities": [                                  /* OWN battlefield cards only (see below) */
    { "cost": "R Return this to hand", "desc": "Add {C}{C}{R}.", "producesMana": true }
  ]
}
```
- `power`/`toughness` use `getNetPower()`/`getNetToughness()`; `sick` is
  `isSick()`. All present only for creatures.
- `counters` is a map of counter kind → count (from the card's `Multiset<CounterType>`);
  the key is omitted entirely when the card has no counters.
- `auras` lists the names of Auras/Equipment/Fortifications currently attached to
  the card (its `getAttachedCards()`); omitted when nothing is attached. This is
  what makes an aura like Kenrith's Transformation visible on the creature it
  modifies.
- `abilities` is present **only on the acting seat's own** battlefield cards
  (opponents' entries omit it to keep the payload lean). It lists that card's
  **activated** abilities — *including mana abilities* — each as
  `{cost, desc (≤100 chars), producesMana}`, so a creature's activated mana
  ability (Grinning Ignus), a ritual, or a counter-gated fetch is visible.

**Own `hand`** is a list of `{name, manaCost, types}` objects (private-to-owner,
fair). Opponents' hands are **never** serialized — only counts, via `handSize`
and the `opponents` block. `command`/`graveyard`/`exile` remain plain name lists.

**Response** (`resp-<n>.json`), by `decisionType`:
- `CAST_SPELL` / `REACT` → `{"chosenId": <option id>}` (id `0` = pass; `REACT` is an instant-speed window to respond to an opponent's stack object)
- `MULLIGAN` → `{"keep": true|false}`
- `DECLARE_ATTACKERS` → `{"attackers":[{"attacker":<cardId>,"defender":<entityId>}, …]}` (`[]` = no attack)
- `DECLARE_BLOCKERS` → `{"blocks":[{"blocker":<cardId>,"attacker":<cardId>}, …]}` (`[]` = no blocks)
- `CHOOSE_ENTITY` → `{"chosenId": <cardId>}` — the copy/choose target. When the
  choice is optional an extra `{"id":0,"label":"Choose none","type":"NONE"}`
  option is offered; `{"chosenId":0}` = choose none.
- `CHOOSE_ENTITIES` → `{"chosen":[<cardId>, …]}` — a subset satisfying the
  request's `min`/`max`, no duplicates. Also carries sacrifice/destroy
  choices (note 50): prompts starting `SACRIFICE`/`DESTROY` (edicts,
  Balance-class) and `SACRIFICE PAYMENT` (which card pays an outlet
  activation or additional-cost cast) — you pick what YOU lose.
- `CHOOSE_MODE` → `{"chosen":[<modeIndex>, …]}` — mode option ids are **indices**
  into `options`; must satisfy `min`/`max`; may repeat an index only when
  `allowRepeat` is true. Since wave-2 (note 52) the same wire shape carries
  every bounded indexed choice: `OPTIONAL COSTS` (Buyback/Kicker — min 0),
  `PROTECTION`, `VOTE`, `CHOOSE A PILE`, `CHOOSE A VALUE`.
- `CHOOSE_CARD` → `{"chosenId": <cardId>}` — the tutored/searched card (id `0` =
  choose none, offered only when optional). Also used for face/state picks
  (sequential ids).
- `CHOOSE_CARDS` → `{"chosen":[<cardId>,…]}` — multi-card searches
  (Cultivate-class), discard selection, choose-N-for-effect; must satisfy
  `min`/`max`, no duplicates.
- `CHOOSE_NUMBER` → `{"chosen": <int>}` within `min`..`max` — X announcements
  on the cast path, cost-reduction amounts, generic number choices, and
  KEYWORD COST prompts (Multikicker-class: how many times to pay; max is
  the affordable cap). `state.puntHigh` marks X-like requests whose TIMEOUT
  default is max; unmarked requests (bids, Wheel of Misfortune class) time
  out to MIN (wave-3: a punt of 99 on a bid was game-losing).
- `PAY_UNLESS` → `{"chosenId": 0|1}` — 1 = pay (taxes like Rhystic/Sentinel,
  counter-unless, pay-the-difference tutors, sacrifice-unless upkeeps).
- `CONFIRM` → `{"chosenId": 0|1}` — yes/no confirms; `state.confirmMode ==
  "TRIGGER"` marks the seat's own optional "you may [pay X to]…" trigger
  (Rings-class), with `triggerText`/`yesCost`/`chosenTargets` in state;
  `state.confirmMode == "PLAY_FROM_EFFECT"` marks a may-cast offer (Isochron
  Scepter copies, Discover-class), with the offered `spell` text and whether
  it is `free` in state — on yes the seat also aims its targets (note 49).
- Optional costs (Buyback/Kicker/Entwine) are NOT a window: affordable
  variants appear as separate `[+ cost]` options in the CAST_SPELL list
  (wave-3 — mailboxing chooseOptionalCosts spammed windows at
  option-enumeration time and could hide the base spell).

**Extra answer keys** (all optional, stripped before the wire): `turn_plan`
(first own-main decision — quoted back later as advisory), `deviation`
(`{wanted, blocked_by}` — the play-quality review trail, logged loudly),
`hold_turn: true` (on a REACT pass — arm the same-turn hold posture),
`repeat_cycle: N` (loop fast-forward: the runner replays the just-completed
identical cycle N times at zero model calls, breaking on ANY novelty; cap 64).

Malformed / unknown ids / wrong-count / illegal choices fall back to stock
(never partially applied). Trivial windows (no castable ability / no eligible
attacker or blocker; a forced single sub-choice; a non-card entity option) are
**not** sent — they auto-pass to stock ("Lever 2", the controller gates).

## Running it

```sh
# THE launcher (one-shot: preflight -> teardown -> seat runners -> advisor
# (human games, on by default) -> GUI -> waits for liveness, prints one
# status line):
forge-arena/scripts/arena-play.sh --all-ai                          # 4 AI seats, spectator GUI
forge-arena/scripts/arena-play.sh --human [deck.dck] [--no-advisor] # you at seat 0
#          --linger N | --no-autostop   (auto-teardown after game over: 600s human / 60s all-AI)
#   knobs: --model haiku|sonnet|opus|fable  --effort low|medium|high|xhigh|max
#          --timeout N   (defaults: opus / medium / 90s)
forge-arena/scripts/arena-stop.sh    # teardown + ELO sweep + log archive

# Ground-truth dashboards (two DIFFERENT tools):
python3 forge-arena/runner/status.py        # seatd health/decisions (log-based)
python3 forge-arena/scripts/arena-status.py # pending-mailbox board snapshot
tail -f forge-arena/runner/logs/game.jsonl  # live decision stream

# Low-level (what arena-play wraps): runner/run_table.sh (seat daemons),
# run-pilot-match.sh (GUI JVM), run-gui.sh (plain GUI, no mailbox).
```
The launcher runs from `forge-gui/` (Forge resolves `res/` from cwd) and pulls
the desktop `--add-opens`/JVM args from `forge-gui-desktop/pom.xml`. Decks are
read from Forge's Commander deck folder + `forge-arena/decks/`.

**The brain side (SHIPPED — the Track-5 architecture below is built):** one
resident daemon per seat (`runner/seatd/`, supervised by `run_table.sh` with
restart + crash-loop damping). Each daemon holds a persistent model session
(Claude CLI `--resume`, MCP-disabled — the single biggest latency win, ~2-3s
off every decision) loaded once with the deck dossier + primer + both rules
digests, self-serves its inbox, and layers: memo/autopass/hold fastpaths,
executable plans, deviation + turn-intent capture, effort routing
(resourceless / own-trigger / free-confirm windows think at `low`), cycle
replay (`repeat_cycle`), wedge recovery (a dead session is dropped and
rejoined fresh mid-game), and transport-event emission for ratings voiding.
Any seat can instead run an **OpenRouter or OpenAI-compatible backend model**
(`ARENA_SEAT_MODELS=",or/google/gemini-2.5-pro,,oai/llama3.1"`) with $-and-call
cost rails — see `packaging/README.md` §"Other models on the backend".

## Known limitations (current, 2026-09-04)

1. **Deliberately-stock surfaces** — multi-target spells, whole-DB card
   naming, combat damage assignment, convoke/improvise payment, colour picks
   inside a payment context, mana auto-tap source selection (INVENTORY §2
   has the rationale per row). Trigger ordering left this list 2026-09-04
   (note 61).
2. **Mixed-owner trigger cascades** (my trigger + your trigger alternating on
   the stack) still cost one model call per window — the own-trigger memo
   collapse correctly refuses to fire there. Bounded, safe, slow.
3. **`canPayCost` guard conservatism** (note 41): the unaffordable-cast guard
   can refuse a genuinely payable cast (observed: Ancient Tomb pain-land).
   Self-healing — the brain gets the window back and floats mana explicitly —
   but costs a round-trip.
4. **Narration is unreliable** (unchanged): trust the request state and the
   board, never the agent's prose. The deviation log exists precisely to make
   the brain's *intent* auditable against reality.
5. **Latency floor is model think-time** (~4-6s p50 at opus/low-medium after
   the MCP-skip + fastpath + cycle-replay work). Remaining tail: mixed-owner
   cascades (#2) and first-iteration loop passes before `repeat_cycle` arms.

## Upgrade roadmap

**Track 1 — loop tightening & action speed**
- ✅ Lever 2: trivial-subphase gate (empty windows auto-pass to stock).
- ✅ Terser brain protocol: `{chosenId}` + one-line reason (see `seatd/seat-brief.md`).
- ✅ Whole-turn drain (batch a turn per wake) + a file monitor as the cross-phase backstop.
- ✅ **Reactive-gate hardening (v2):** only open a `REACT` window when a *real,
  affordable* response exists — drop all mana abilities and any spell the seat
  can't pay for. Killed the phantom "respond to a fetchland / to a spell you can't
  afford" windows that flooded the brain and stalled game 2 (see Operational
  learnings §3).
- ✅ **Speed knobs (v2):** outbox pickup `pollMillis` 200→75ms; file monitor
  2s→0.5s; brain drain poll ~10s→~2s; brains **self-serve their inbox** (drain
  autonomously) so the orchestrator is off the critical path for same-turn windows.
- Next: **pre-plan wakes** (→ Track 5) so a seat's turn is planned *before* it starts.

**Track 2 — observability & correctness (highest play-quality value)**
- ✅ Richer serialization: per-card P/T, counters, tapped/sick, attached auras, and
  activated abilities with their mana output (own battlefield). Fixed the former
  name-only blind spots.
- ✅ Persistent public observer snapshot (`observer-state.json`, event-bus driven)
  so the dashboard/observer is never blind, including during the human's turn.
- ✅ Anti-confabulation (brief-enforced): agents re-derive every decision from the
  request state; never claim a play they can't see in it; and **never infer "turn
  complete" from an empty inbox** (the game may be blocked on another seat while
  the agent's own spell is still on the stack) — they report "idle, awaiting next
  window". **Fat oracle context is REQUIRED**: summarizing card text spikes
  hallucination (agents invent abilities from card names) — keep the full per-card
  dossier (Operational learnings §1).

**Track 3 — deeper capability**
- ✅ Sub-choice mailboxing (copy/choose, modes, tutor fetch → `CHOOSE_ENTITY`/
  `CHOOSE_ENTITIES`/`CHOOSE_MODE`/`CHOOSE_CARD`). ✅ Normal spell targeting
  (`chooseTargetsFor`) became seat-owned in v3 (notes 14/14b/14c).
- ✅ v2 reactive windows (`REACT`): agent responds at instant speed to
  opponents' stack objects — own-turn responses included (the gate keys on
  stack ownership, not turn). Remaining: proactive empty-stack flash.
- Teacher→student: feed caught misplays into both the agent briefs and the
  deterministic runner.

**Track 4 — packaging & release — ✅ SHIPPED (v1 2026-08-12 → v3.3.2 2026-09-01; v3.3.3 pending)**
as **forge-light-llm**: zero-setup tarball on R2
(`-latest` alias), ten bundled decks (`build-light-package.sh` SLUGS: Sythis +
Liberator added for v3.2 — notes 45, 48; Sheoldred's Sacrifice for v3.3.2 —
PATCH-NOTES), deck ingestion incl. DeckCheck auto-primer (note 44),
README + PATCH-NOTES,
GPL-3.0 source-available. Build: `../BUILDING.md` +
`packaging/build-light-package.sh` (the manifest).

**Track 5 — autonomous per-seat brains — ✅ SHIPPED as `runner/seatd/`**
(resident daemons, supervised, warm-cache, self-serving; the design doc
[AGENT-SDK-SEATS.md](AGENT-SDK-SEATS.md) is retained as the historical plan).
Original sketch follows —
- Replace sleep/wake subagents with one **persistent Agent-SDK process per seat**
  (see *Next architecture*). Each seat runs an always-alive loop, **pre-plans on the
  public snapshot while opponents play**, and services its mailbox directly — no
  human/mainline orchestrator in the routing path. This is the path to a true
  "four autonomous seats" experience and the shape the shareable release should take.

## Next architecture — autonomous Agent-SDK seats

> **HISTORICAL (pre-ship).** This design SHIPPED as `runner/seatd/`
> (Track 5); [AGENT-SDK-SEATS.md](AGENT-SDK-SEATS.md) is the retained plan
> doc. Present-tense claims below describe the pre-2026-08-06 world. Kept
> for the reasoning; do not read as a roadmap.

**Why change anything.** Today each "brain" is a *subagent of one interactive
(mainline) session*. Subagents are **sleep/wake**: they run, idle out, and stop.
Two consequences fall out of that and gate everything else:
1. Between its turns a seat isn't watching, so it **can't plan ahead** — all
   thinking happens at the moment it's consulted ("thinking hard in main 1").
2. The **orchestrator (a human-driven session) is in the critical path** — it must
   notice each pending request and wake the right seat, adding latency and coupling
   game speed to a human's attention.

Buying more Claude accounts does **not** fix this — the limit isn't quota, it's the
subagent lifecycle. The fix is architectural.

**Target.** One long-lived **Agent-SDK process per seat**. Each process:
- Loads its **deck dossier + primer once** at startup and stays resident, so its
  context — and its prompt cache — stay **warm** across decisions.
- **Continuously tails the public `observer-state.json`** for situational awareness,
  and **pre-plans its upcoming turn** from that public board while opponents act,
  revising as the board changes and (at its turn) for its actual draw.
- Watches its own `inbox/`, handles each `req-<n>.json`, writes `outbox/resp-<n>.json`
  — the **same mailbox contract**. The Java engine side (`MailboxController` /
  `MailboxLobbyPlayer` / `GuiPilotMatch`) needs **no changes**; only the brain side
  moves from "subagent resumed per decision" to "resident process."
- Emits its reasoning to a **per-seat transcript/log** the human can watch and
  interrogate live — the "streaming like mainline" feel, per seat.

**Keys / accounts.** Four continuously-reasoning agents is heavy *sustained*
throughput; one **API key per seat** gives rate-limit headroom and clean per-seat
billing. Accounts spread the rate *ceiling*, **not** the token *bill*.

**Cost dial (decide this deliberately).** Always-on (thinking through every
opponent turn) is *dramatically* more expensive than sleep/wake. The sweet spot is
**pre-plan-on-demand**: when a seat is *on deck* (the previous seat is active), wake
it once to draft its turn from the public snapshot; it then executes fast when its
turn lands. Captures most of the "ready before the turn" benefit at a fraction of
always-on cost. Fully-resident always-on is the premium tier.

**Fairness is unchanged and must stay so.** Each process reads only its **own inbox
(its own hand)** + the **public** observer snapshot — never another seat's inbox,
never a human coaching a seat. Keep the SeatView guarantees (W8).

**Warm-cache economics.** A resident process keeps the ~35–40k fixed dossier
prompt-cached across decisions, so the marginal per-decision cost stays small. This
is strictly better than sleep/wake, where human-paced gaps expire the cache TTL and
re-pay the dossier (Operational learnings §2).

**Suggested components.**
- `seat-runner` (Agent-SDK program): args = seat id, dossier path, mailbox base.
  Loop: load context → subscribe to `observer-state.json` → on inbox req: decide +
  write resp; on on-deck: pre-plan; else idle-watch/refine plan.
- A thin **supervisor** to launch/health-check the runners and restart on crash
  (safe: the engine re-sends on timeout, so a restarted seat just picks up the next
  request; nothing is lost mid-decision because writes are atomic).
- Per-seat log for observability + teacher→student capture (Track 3).

## The shipped stack around the seam (2026-08-13 → 08-17)

Engineering summary of the major systems now layered on this seam — the
user-facing docs live in `packaging/README.md`; per-file map in INVENTORY §4.

- **Backends (OpenRouter / OpenAI-compatible), per seat.** `or/<vendor>/<model>`
  (API-billed, `OPENROUTER_API_KEY`) or `oai/<model>` (`ARENA_OAI_BASE_URL`,
  keyless local endpoints OK) via `ARENA_SEAT_MODELS` or live re-dial from the
  AI panel — a seat can detour Claude↔backend mid-game and its Claude session
  survives. Rails: `ARENA_MAX_SEAT_COST_USD` ($5/seat/game default) + a
  250-call cap that works when providers report no cost; caps/latches/failures
  degrade to safe defaults, never stall the game. Config errors fail AT LAUNCH
  on the terminal. Design contract: **no harm to the Claude path** — backend
  state is fully isolated (`seatd/backends.py`).
- **ELO ladders.** `GameResultSpool` (engine) → `runner/ratings.py` at
  teardown: pilot / deck / pilot×deck ladders, six pairwise 1v1s by finish
  order with tie groups, K-decay, per-seat panel digests, plottable history.
  Pilot attribution from `game.jsonl` decision records (majority model in the
  game window). Transport-contaminated games are **voided** (recorded with
  reason, ladders frozen; `ARENA_RATE_VOIDED=1` overrides).
- **The AI Advisor** (human games; on by default since 08-17, `--no-advisor`
  opts out): a fourth brain on the seat-0 read-only shadow feed — advice
  before you act, table-aware mulligans, color commentary, coach's memory,
  pause button, an **Ask** field (note 73); `advisor-0.jsonl` dataset.
  Supervised by `runner/run_advisor.sh` since 09-04 (note 72).
- **Smart autopass** (`ARENA_AUTOPASS`, default `casts`): stakes-based
  guarantees (own mains/combat/opponent-spell/floating-mana stops never
  skipped) + the seat runners' allowlist fastpath answering provably-no-op
  REACTs (the standalone `react-autopass.py` daemon that first did this was
  retired from the launch 08-17 and deleted 09-04 — note 42).
- **The deviation log**: every seat states its plan (`turn_plan`) and reports
  each thwarted line (`deviation {wanted, blocked_by}`) — grep `DEVIATION`
  for a play-quality review. The brief-tuning loop runs off this evidence.
- **Pace stack**: MCP-init skip (~2-3s/decision, median 8s→5s), memo +
  own-trigger cascade collapse, dead-window effort routing, and
  brain-declared **cycle replay** (game 8: three kill loops, ~200 decisions
  replayed at ~0.5s each, three opponents eliminated sequentially in ~3 min).
- **Resilience**: wedged-session detection → fresh-session rejoin with a
  board-truth note; shape-aware punt defaults (own free copy-cast → yes);
  transport events feeding the ratings void check.

## Operational learnings & field notes (2026-08-06 —)

Hard-won from two live sessions; read before optimizing anything.

1. **Fat context is non-negotiable.** *Two* separate attempts to summarize / skimp
   on oracle text produced a hallucination spike — agents invent what a card does
   from its name. Keep the **full per-card dossier**. This is a hard constraint on
   any cost optimization; don't trade it for speed or tokens.
2. **Token economics of persistent brains.** The per-agent usage number is
   *cumulative*; each wake adds a **small marginal delta**, but the total is
   dominated by the one-time dossier (~35–40k) carried in every wake. Prompt caching
   makes that carried context cheap **only when wakes are close together**;
   human-paced gaps blow the TTL and re-pay it. ⇒ a **resident (Track 5) process
   that stays warm is materially cheaper per decision** than sleep/wake. Multiple
   accounts spread the rate ceiling, not the bill.
3. **The reactive gate must be strict** (`MailboxController.chooseSpellAbilityToPlay`).
   `canPlay()` admits spells the seat can't actually pay for at instant speed (e.g.
   Mana Drain `{U}{U}` with one untapped Island), and non-trivial mana abilities
   (Sol Ring) look like "responses." Both opened **phantom `REACT` windows** for
   every seat on fetchlands and ramp spells — pure latency + token waste, and the
   reason game 2 felt slower than game 1. **Fix (v2):** in a reactive window, drop
   ALL mana abilities and require `ComputerUtilCost.canPayCost(sa, me, false)`; if
   nothing meaningful survives, fall through to stock (no window, no wake).
   Main-phase (`CAST_SPELL`) intentionally keeps `canPlay()` alone, since a mana line
   in the option list may itself enable the cost.
4. **Latency budget.** Real knobs + v2 values: outbox `pollMillis` 75ms; file
   monitor 0.5s; brain drain ~2s; brains self-serve. The **irreducible floor is
   model think-time** (fat context, ~15–90s/decision) — attack it by *planning whole
   turns at once* and *pre-planning during downtime* (§5), not by trimming context.
5. **Turn planning like a human.** Best play comes from **planning the whole turn at
   its first window** and executing subsequent same-turn windows as steps of that
   plan, revising only for the draw and opponents' actions. Humans plan *before* the
   turn starts; the Track 5 pre-plan wake replicates that. (In v2 this is enforced in
   the brain brief: "plan your entire turn upfront, then execute each step.")
6. **Anti-confabulation rules that actually mattered:** (a) never report a play you
   can't see in the state; (b) **never infer "turn complete" from an empty inbox** —
   report "idle, awaiting next window" (the game may be blocked on another seat while
   your own spell is still on the stack); (c) trust the board / `observer-state.json`
   over any agent's prose.
7. **Orchestrator-as-filter (stopgap).** For a demonstrably-uninteractive window
   (e.g. a phantom counter the seat can't pay), writing the pass directly *without* a
   brain wake unblocks the game cheaply — but the durable fix is the engine-side gate
   (§3), not manual filtering.
8. **Fairness held both directions.** Brains reason only from their own hand + the
   public snapshot; the human does **not** coach opponents' brains, even when a
   better line is visible. The agents finding lines themselves is the entire point.
9. **Validated live (v2):** `REACT` (trivial pass on a fetchland / uncastable
   counters *and* a real evaluation of a turn-2 Serra Ascendant), `CHOOSE_CARD`
   (color-aware fetch — "hand is all white → fetch Plains"), deck-aware `CAST_SPELL`
   (turn-2 Serra Ascendant played as a 6/6 flyer at 40 life), whole-turn drain, rich
   per-card state, the observer snapshot, and a clean mid-game max→medium brain
   cutover with no double-routing.
10. **Set brain effort EXPLICITLY when spawning a seat (biggest speed lever).**
    Spawn each seat brain at **`effort: low`** (keep `model` on the capable tier).
    A seat spawned *without* an effort override **inherits the session effort** — and
    a session left at **max** turns every fat-context, whole-turn-planning turn into
    a ~5-minute crawl (the "molasses" in the second half of game 2; observed turns of
    ~4.8 min each). Play quality barely moves because **the request state is ground
    truth** (the seat re-derives each decision from it regardless of effort), but wall
    time collapses. Effort is fixed at spawn, so it **cannot be lowered on a running
    agent** — you must re-spawn to change it (cheap, since a fresh brain reconstructs
    the game from the current request state). Secondary time sinks to trim next run:
    the end-of-turn idle drain (a seat polls an empty inbox ~45–90s before reporting
    idle — dead time) and over-heavy whole-turn planning at max effort.
11. **Observability = a Monitor-tool PUSH, not a Bash loop; read state on demand.**
    The orchestrator ("main") must arm the **Monitor tool** on the mailbox — a
    `while`-loop that prints one line per new `req-*.json`, `persistent: true` — so it
    **pushes a one-line notification per decision**. A plain backgrounded **Bash**
    `while true` loop does NOT work for this: a background Bash task only notifies on
    *exit*, so it logs to its output file silently and main goes blind. This exact
    mistake happened at the game-2 relaunch (main replaced the working Monitor with a
    raw Bash loop and then relied on the human to flag every window). For full state,
    read `arena-status.py` / `observer-state.json` **on demand** — and **never infer
    whose turn it is from a brain's "idle" report** (that is confabulation-by-proxy;
    a seat idles out while its own turn continues). **Cost truth:** monitor pings and
    dashboard reads are tiny; the only real token spend is **brain wakes** (one per
    decision), and an idle seat's task has *completed* — it burns nothing while
    waiting. Nothing runs up tokens "regularly" in the background; scale cost with
    decisions, not wall-clock.
12. **Auto-pass no-op protection REACTs (stopgap for a real over-trigger).** A free
    always-available protective tap (Giver of Runes: `{T}`: protection) makes the
    hardened reactive gate open a *legitimate* `REACT` on **every** opponent spell
    (the ability is real + affordable) even when nothing threatens the seat — game 2
    saw one per human spell. Real, not phantom, so the affordability filter (§3)
    doesn't catch it. Stopgap: the orchestrator verifies the stack and, when the sole
    non-pass option is such a protection ability with no threatened target, writes the
    pass directly (no brain wake). Durable fix: extend the gate to suppress
    "protect/prevent with no valid or threatened target" responses. **Shipped stopgap:**
    `scripts/react-autopass.py` — a standalone daemon that watches all inboxes and
    instantly (~200ms) passes any REACT whose non-pass options are all on a no-op
    allowlist. Cut those windows from 5-10s (orchestrator round-trip) to engine speed;
    game-2's 20-spell human turn generated 40+ such windows, all absorbed at zero
    token cost. Retire it when the engine gate lands. **RETIRED from the launch
    2026-08-17 (Ben):** the resident runners' allowlist fastpath subsumed it —
    zero daemon absorptions across three consecutive games; script kept as a
    manual fallback until it was deleted 2026-09-04 (BL-15, note 42).
13. **GAME-DECIDING GAP — the pre-damage combat instant window is not mailboxed.**
    Game 2, turn 21: Giada's brain planned blocks around **Flare of Fortitude** (free
    total fog: sac a white creature, prevent ALL damage) explicitly expecting a
    post-blockers window — which never came, because empty-stack instant priority
    (combat steps included) is still stock, and stock declined to cast it. She died
    with the save in hand to a 142-power alpha she'd have taken ZERO from. Beyond the
    lost game: until this window is mailboxed, **no AI seat can punish an
    overextension**, alpha strikes are systematically safer than real Magic, and
    fog/protection/flash decks play far below strength. Fix: open a mailbox window at
    combat-step priority (at least declare-attackers and declare-blockers/pre-damage)
    when the seat holds a castable instant — same affordability gate as REACT.
    **FIXED in v3 (2026-08-07):** tactical windows (all combat steps + end step,
    any turn, empty stack) now mailbox as `REACT` with a `state.combat` block
    (attackers/defenders/blocks), and stock's authority to cast for a mailbox
    seat is fully revoked — un-mailboxed windows return a clean pass.
14. **Equip/attach targeting fizzles from the mailbox path.** Game 2: Urza's brain
    chose Lightning Greaves' equip {0} three times; no target prompt ever surfaced
    (targeting is `chooseTargetsFor` = stock) and the ability silently fizzled each
    time. Root cause: stock's `chooseTargetsFor` re-runs the api-specific AI
    heuristics (`doTrigger`) the mailbox path bypassed, and those can DECLINE.
    **FIXED in v3 (2026-08-07):** `chooseTargetsFor` override mailboxes
    single-target choices as `CHOOSE_ENTITY` (candidates from
    `getAllCandidates`, optional decline when min=0); multi-target and unusual
    cases still fall to stock — never worse than the status quo.
    **14b — the fix was HALF-DEAD for SPELL casts (2026-08-10, found live):**
    `chooseTargetsFor` worked for activated abilities (equip), but a targeted
    SPELL cast from the mailbox never reached it. The AI cast path
    (`PlayerControllerAi.playChosenSpellAbility` -> `ComputerUtil.
    handlePlayingSpellAbility(ai, sa, chooseTargets)`) runs only the
    `chooseTargets` Runnable it's handed, which is
    `getDeferredTargetingPlayerRunnable` — that resolves a `TargetingPlayer`
    param ONLY, never the spell's own targets. So an AURA (no TargetingPlayer)
    reached casting untargeted: mana paid, then the stack rejected it
    ("Couldn't add to stack, failed to target", visible in gui.out) and the
    card was discarded from existence. Confirmed on Selvala's Wolfwillow Haven
    (t8) and Utopia Sprawl (t12); scope is EVERY targeted mailbox-cast spell,
    all decks — auras above all (her Sprawl/Wild Growth/Fertile Ground/
    Overgrowth ramp, Song of the Dryads, Kenrith's Transformation), plus
    targeted removal/pump. Same disease as #15b: a `PlayerController` hook
    alive on the human path, dead on the AI cast path. **FIXED:**
    `playChosenSpellAbility` override now, before delegating, calls
    `chooseTargetsFor(sa)` for any SA with `minTargets > 0` and no valid
    targets yet (general across all `GameEntity` target kinds); if targeting
    can't be satisfied it returns true WITHOUT casting, so the brain keeps
    priority (117.3c) and re-plans instead of losing the card. Lesson
    (again): a hook that fires on the human path is NOT automatically on the
    AI cast path — verify against `handlePlayingSpellAbility`.
    **14c — MODAL (Charm) spells were STILL losing the card (2026-08-10,
    caught by the broad soak watch): Collective Resistance cast to destroy
    Purphoros → "Couldn't add to stack, failed to target" → gone.** 14b's
    pre-targeting runs BEFORE the cast, but a Charm chooses its mode INSIDE
    the cast (`CharmEffect.makeChoices` within `handlePlayingSpellAbility`),
    so at pre-target time there is no mode → no target requirement → nothing
    set → the chosen mode's target is never assigned → lost. **FIXED:**
    `playChosenSpellAbility` now routes `ApiType.Charm` spells through a direct
    `ComputerUtil.handlePlayingSpellAbility(..., () -> chooseTargetsFor(sa))` —
    that runnable runs AFTER `makeChoices` and before the stack-add, so the
    mode's target is set at the right moment. Non-modal spells keep the 14b
    pre-target path (graceful decline). Brain-chosen modal *targets* (vs
    stock picking the mode's target) is a further refinement, not yet done.
15. **Auto-tap mana payment strands colored sources.** Forge's payment auto-tap chose
    a generic land over a colorless one for The One Ring's {4}, stranding the seat's
    only blue source and locking two castable spells out of the turn.
    **DEFERRED, documented:** a real fix means reimplementing
    `ComputerUtilMana`'s source selection — the deepest, riskiest change on the
    list for the lowest observed harm. Revisit only if it recurs at game-losing
    stakes. **15b (X values) FIXED in v3:** the mailbox cast path bypasses the
    AI pipeline where X is normally set, and stock's `announceRequirements`
    returns null for plain X costs — a brain-chosen Walking Ballista therefore
    resolved at X=0 and died. `announceRequirements` is now overridden: X/value
    announcements mailbox as `CHOOSE_NUMBER` (state.min/max, max clamped to the
    stock affordability estimate so an unpayable X can never rewind the cast);
    forced values never wake the brain.
    **15b CORRECTION (2026-08-10, proven WRONG then re-fixed): the
    `announceRequirements` override was DEAD CODE and X never worked.** It sits
    on the HUMAN cast path (`PlaySpellAbility.announceValuesLikeX` ->
    `controller.announceRequirements`). A brain's chosen spell is cast on the
    AI path — `PhaseHandler` -> `PlayerControllerAi.playChosenSpellAbility` ->
    `ComputerUtil.handlePlayingSpellAbility`, which contains ZERO X handling —
    so X stayed at its default 0. Empirical tell: **0 CHOOSE_NUMBER wakes
    across every recorded game**; Genesis Wave/Hydra/Walking Ballista/Finale
    all resolved 0/0 or X=0. (My earlier "the clamp silently forced X=0"
    diagnosis was also wrong — the clamp never ran; announceRequirements never
    ran.) **REAL FIX:** `MailboxController.playChosenSpellAbility` is now
    overridden — for a mana-X spell it announces X via the shared `mailboxManaX`
    helper (affordability-capped `CHOOSE_NUMBER`, `cancelable`) BEFORE
    delegating to super, and `setXManaCostPaid(x)`. A `-1` answer cancels: the
    override returns true without casting, so the brain keeps priority (117.3c),
    floats mana, and re-casts. `announceRequirements` retained (correct for the
    human path, unused by AI). Lesson: verify the hook is on the ACTUAL cast
    path, and treat "feature has literally never fired in telemetry" as a
    red flag, not a quiet success.
16. **Eliminations aren't pushed to brains (only discoverable via state).**
    **FIXED in v3:** the observer snapshot now carries a per-seat `eliminated`
    flag (`Player.hasLost()`), so runners/pre-planning can react to the actual
    turn-order change.
17. **RETRACTED-AND-REWRITTEN (was: notes 17-20 blaming engine seams).
    2026-08-10 opus/medium all-AI game forensics, verified against archived
    per-seat records (archive/20260810-090542-stop/seat-N.jsonl): the ENGINE
    WAS PROGRAMMATICALLY CORRECT throughout.** What actually happened:
    - Floating mana IS supported through the mailbox: non-trivial mana
      abilities (Selvala's {G},{T}: add X included) are listed as options in
      main-phase windows, mana abilities resolve immediately, and pool-funded
      casts work (Jeska's Will -> Purphoros same game; Selvala tap chosen 4x
      in the 2026-08-09 game and again in the fable/high game).
    - The t18 disaster was a BRAIN misplay chain (opus/medium, live model
      calls): it hallucinated "seven floating mana" it never generated
      (state.manaPool was in every request), never picked the Selvala tap
      option present in its own option list (verified seq 88-90), fired
      untappers at already-untapped lands (t14), and cast Genesis Wave with
      an empty pool. The earlier "activation fizzles" (t12 Giada Clue #2,
      t17 Urza {5}) are consistent with unaffordable activations being
      legally declined/rewound (733.1), i.e. brain arithmetic errors.
    - Executable plans (#1) and react-hold (#2) were BOTH OFF this game
      (runner line: no --speculative/--react-hold; arena-play.sh sets
      neither). Every misplay was a fresh per-window model decision. The
      fable/high game ran with both ON and handled Selvala correctly.
      The round-trip features are exonerated; no revert indicated.
    Real (small) harness-ergonomics gaps confirmed by the same forensics:
    a. **Silent forced-X**: Genesis Wave's X was clamp-forced (~0) with zero
       CHOOSE_NUMBER wakes this game — when the brain casts an X spell the
       clamp should ALWAYS wake the brain if the max payable X is below a
       sane threshold, so it can abort instead of wasting the spell.
    b. **isTrivialLandMana hides high-value land floats**: bare-tap filter
       drops Gaea's Cradle/Nykthos-class lands from options, so those can
       never be manually floated (only auto-paid). Filter should be
       "bare tap AND fixed single mana", not "bare tap".
    c. **Prompt hygiene**: plan-submission text appears even when the
       executor is off (gate it), and the prompt should state explicitly:
       "state.manaPool is ground truth; you have floated NOTHING unless it
       shows there" — targets the exact hallucination observed.
    d. **_record truncates option lists** (~9 entries) — seq 85 chose id 13
       with 9 recorded options; forensics needed the full list. Record all.
    Fixes pending discussion with Ben before any build.
    **ALL FOUR (a-d) SHIPPED 2026-08-10 and validated live** in a full
    opus/medium game: 1 CHOOSE_NUMBER wake (Genesis Wave X=9, deployed a
    9->17-permanent board), 12 CHOOSE_ENTITY (targeting across all 3 decks),
    0 failed-to-target, 0 punts. See also notes 14b, 15b-correction, and 21.
    *(Numbering note: 18-20 are deliberately absent — the original notes
    17-20 were retracted and folded into this rewrite.)*
21. **Self-trigger response windows aren't mailboxed — you can't respond to
    your OWN trigger during your OWN turn** (2026-08-10, confirmed at stakes:
    Selvala tried the Phyrexian Dreadnought + Greater Good line and whiffed).
    The gate mailboxes own-main-empty, reactive (an OPPONENT'S object on the
    stack), and tactical (combat/end-step, empty stack) — but the priority
    window where your own ETB/triggered ability sits on the stack, before it
    resolves, matched none of them (reactive requires `activatingPlayer != me`)
    and fell to stock, which never finds the line. Live proof: seq 157 cast
    Dreadnought planning "sac it in response to its ETB to draw"; the mailbox
    jumped from "Dreadnought spell on stack" straight to the trigger's
    RESOLUTION (choose sacrifices, seq 159) — the response window in between
    was never offered, so no tap-Selvala-for-12 and no sac-to-Greater-Good; the
    12/12 sacrificed itself for nothing. **FIXED (v4):** a fourth gated window
    `selfTrigger` — my own triggered ability on the stack, no opponent object —
    now mailboxes as `REACT`, BUT only when the seat also holds a NON-mana
    instant-speed action (a sac outlet, an instant, an activated ability) OR a
    mana ability that would add a LOT right now (>= BIG_FLOAT, currently 6).
    A bare small mana ability never wakes it (anti-flood: Selvala's
    always-available mana ability would otherwise open a window on every
    trigger). Within the window, non-trivial mana abilities ARE surfaced (like
    own-main) so "tap Selvala for 12" is available alongside the sink, and the
    seat retains priority to chain several responses.
    **BIG_FLOAT branch (added same day):** covers the NO-sink case — cast
    Dreadnought with no Greater Good, tap Selvala for 12 while the 12/12 is
    briefly on the board, let the ETB sac it, and the 12 mana PERSISTS to spend
    later this main phase (pools empty at step/phase end, not on trigger
    resolution). Yield is computed live via `manaAbilityYield` (evaluates
    Count$-style Amounts against the board). Known imperfection: on a naturally
    big-mana turn a >=6 mana ability wakes the window even with no temporary
    spike — a few extra round-trips, accepted. The exact signal ("this trigger
    is about to shrink the body inflating the yield") needs simulating the
    trigger and is deferred. RELATED / STILL OPEN: the Urza t26
    death (couldn't Mirror->Island->Mana-Drain the lethal Ojer Axonil) is the
    same family in a REACTIVE window — it needs mana-generation (or a
    land-transform) to afford the answer, which reactive windows still don't
    surface. Deferred: forward-looking affordability + mana access in reactive
    windows is a larger change; revisit if it recurs at stakes. Runner caveat
    (latent, harmless while --speculative is off): guard #4 discards the
    executable plan on ANY own-turn REACT, which would now include a
    selfTrigger window — refine to exclude self-trigger before enabling plans.
    **21b — GATE REDESIGNED (2026-08-10, per Ben: correctness/intent over
    speed; don't block play lines).** The "sac-outlet OR big-float" gate was
    Dreadnought-shaped and risked silently removing lines the brain would take
    (and it whack-a-mole'd one card while missing the trigger CLASS). Norin the
    Wary exposed it: its blink fires on every spell/attack, and the shaped gate
    still opened self-trigger windows whenever the seat held any instant, all
    wasted passes. New design: **open the self-trigger window whenever ANY real
    action is available** (playable non-empty; non-trivial mana abilities kept,
    so the no-sink Dreadnought float stays live) — no cleverness about which
    triggers deserve a window. Flood (Norin) is accepted as slowness, never
    traded against correctness. `BIG_FLOAT`/`hasNonManaAction`/`hasBigManaFloat`
    all removed. **Memo hardened alongside:** `_react_signature` now includes
    every seat's life + our mana pool (not just stack+options), so a same-turn
    window only fast-passes when the situation is TRULY unchanged and re-opens
    the instant a life total or the pool shifts — closing the "identical-looking
    but a new decision is correct" hole. Cross-turn adaptive suppression was
    considered and REJECTED (most state can change across turns; too likely to
    eat a line).
22. **COMBAT BLOCK/ATTACK LEGALITY: aggregate rules were bypassed** (2026-08-11,
    caught live by Ben: Urza blocked a menace Snarling Gorehound with ONE
    creature and it resolved — Gorehound died, Urza took 0). Root cause:
    `MailboxController.declareBlockers` / `declareAttackers` validated each
    participant with the PER-participant `CombatUtil.canBlock` / `canAttack`
    (which PASS for menace — menace is an aggregate "except by two or more"
    rule), then committed via `combat.addBlocker`/`addAttacker` **without ever
    running Forge's whole-assignment validators**. So the seam honored evasion
    (flying/reach/protection) but ignored every count-based rule. FIX: after
    assembling the assignment, `declareBlockers` calls
    `CombatUtil.validateBlocks(combat, defender)` (non-null reason = illegal →
    `undoBlockingAssignment` each + `super`), and `declareAttackers` calls
    `CombatUtil.validateAttackers(combat)` (false = illegal → `clearAttackers` +
    `super`). Now inherits Forge's full legality set: menace/min-blockers,
    max-blockers, must-block/provoke/lure, can't-block-alone, "attacks each
    combat if able", can't-attack-alone, banding. Combat DAMAGE assignment
    (banding damage-control, multi-blocker ordering, trample, deathtouch) was
    never overridden by the seam — it already defers to stock AI, so it was never
    broken and needed no change.

23. **AI Advisor shipped (2026-08-12/13).** Seat-0 shadow feed
    (`AdvisorControllerHuman` → the same `buildState` projection, fairness in
    one place), dedicated coach brain, Advisor dock tab, deliberate cadence
    (3-5 moments/turn, danger overrides — **leaned to a 1-3/turn range
    2026-08-19, note 46**), coach's memory, strictly read-only,
    pause button (08-13). Dataset: `advisor-0.jsonl`.
24. **Smart autopass, stakes-based not heuristic (2026-08-13; SUPERSEDED
    by note 42 — react-autopass retired from launch 08-17; the stakes rules
    survive in the runner fastpaths).** Own mains,
    combat declares, opponent-spell stops, floating-mana stops, and
    post-equip windows are NEVER auto-passed by any layer; everything else
    defaults to `casts` mode with ⏭ receipts. `react-autopass.py` promoted to
    standard launch (from note-12 stopgap).
25. **MDFC + keywords serialization (2026-08-13).** Bundled deck data carries
    both faces (a modal land back IS a land — mulligan judgment), and every
    board state serializes effective keywords (indestructible/hexproof/ward/
    protection/evergreens incl. granted) — facts, not recall tests.
26. **MCP-init skip — the single biggest latency win (2026-08-17).**
    `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` on every brain
    call: each decision had been paying ~2-3s to connect the host's full MCP
    roster with all tools disabled. Median decision 8s→5s; thinking share
    58%→88%. Golden-argv test pins the flags.
27. **Deviation logger + turn intent (2026-08-17).** `turn_plan` captured at
    the first own-main window and quoted back as advisory; `deviation
    {wanted, blocked_by}` logged LOUDLY. Found its first real pattern within
    hours (note 29's tax-blind labels; game-7's answer-framing tunnel vision).
28. **Modal-spell mode discard (2026-08-17, FIXED).** Charm-shell targeting
    fell through to stock `CharmAi`, which `setSubAbility(null)`-ed the
    seat's chosen mode and re-picked by its own logic — tutors "found
    nothing". Fix: target the CHAINED MODES inside the cast runnable, never
    the shell. Live-shaped regression test.
29. **Vanished commander on failed payment (2026-08-17, FIXED, 4 layers).**
    Tax-blind labels → seat chose an unpayable recast → upstream FIXME moved
    the card stack→stack and orphaned it FOREVER. Fixes: effective-cost
    labels (`[effective cost: {1}{G}{G} + {4} = 7 mana]`), local
    affordability guard (REFUSED + window returned), own `commandZone` in
    state, and the **first deliberate upstream behavioral patch**:
    `ComputerUtil.handlePlayingSpellAbility` rolls back to origin zone
    (`UnaffordableCastRollbackTest` guards it — see UPSTREAM-SYNC.md).
30. **PAY_UNLESS / CHOOSE_CARDS / CONFIRM surfaces (2026-08-17).** Every
    "pay X or else" (Rhystic/Sentinel taxes, counter-unless, pay-the-
    difference tutors, sacrifice-unless), multi-card searches
    (Cultivate-class), and yes/no confirms reach the seat. Stock's
    `willPayUnlessCost` hard-refused non-creatures — a paid-for Mana Vault
    went to the graveyard.
31. **Free alternative costs offered (2026-08-17).** `getSpellAbilities`
    strips alt-cost SAs when the base is castable; the mailbox option list
    was built from the stripped list, so Fierce Guardianship showed only as
    {2}{U} and the payer tapped four sources. Fix: enumerate via
    `getOriginalAndAltCostAbilities` cheaper-first, label `[FREE — alternative
    cost you qualify for right now; printed cost X]`.
32. **Own-trigger cascade memo + dead-window routing (2026-08-17).** When
    EVERY stack item is the seat's own trigger, the memo signature collapses
    the multiset to a set (a shrinking cascade of identical triggers
    fast-passes after one look); resourceless REACTs and own-trigger REACTs
    route to effort low — full authority, never skipped.
33. **Local ELO (2026-08-17).** See "The shipped stack" above. Design pin:
    control typing by LobbyPlayer CLASS, never by name (F-24); ratings are
    per-installation state and never ship.
34. **Trigger TARGETING was stock (2026-08-17, FIXED).** A seat's targeting
    triggers were aimed by `brains.doTrigger` heuristics — Tidespout Tyrant
    bounced its controller's own 17/17, then the Tyrant itself.
    `orderAndPlaySimultaneousSa`/`prepareTriggerViaSeat` now route each
    targeting SA in the seat's trigger chain through `chooseTargetsFor`.
35. **Optional-trigger yes/no was stock (2026-08-17, FIXED —
    game-losing class).** `WrappedAbility.resolve → confirmTrigger →
    brains.doTrigger`: stock `CopySpellAbilityAi` NEVER pays for a Rings of
    Brighthearth copy of the seat's own activated ability — Urza's
    Rings+Basalt "infinite" netted ZERO for three turns while the brain
    narrated the loop (pool 7→4→7 every cycle). Now a
    `CONFIRM (confirmMode=TRIGGER)` with trigger text, yes-cost, chosen
    targets; only an unpayable yes-cost auto-declines. Blast radius was every
    "you may [pay X to]…" trigger at the table.
36. **The two fizzles (2026-08-17, both FIXED).** (a) Seats targeted the
    stack-zone CARD, not the stack SpellAbility — `CounterEffect` reads
    `getTargetSpells()`, so every seat-cast counter resolved as a NO-OP
    (Guardianship + Swan Song both "resolved", Generous Gift survived; the
    Swan Song Bird was even created). `chooseTargetsFor` now enumerates
    `SpellAbilityStackInstance.getSpellAbility()` for stack-zone targeting
    and EXCLUDES stack-zone cards. (b) The live "(none set)" caster-side
    target loss: precondition eliminated by construction; cast-time
    diagnostics `[arena] TARGETLOSS` / `[arena] SA-SWAP` name any recurrence.
    `GuardedCastTargetIntegrityTest` replays the full game-7 collision
    (guarded cast + PAY_UNLESS interleave + counter + seat-aimed Tyrant
    trigger) in three scenarios. Test-harness lesson: option-id probe regexes
    MUST anchor to the option object (`\{"id":N,"label":"…`) — matching
    anywhere in the body hits card ids in state.battlefield (bit twice).
37. **Four more surfaces (2026-08-17).** Discard selection (visible-only,
    hidden-info-disciplined), split/adventure/MDFC face picks (finite lists
    only), card state/side picks, cost-reduction numbers, generic
    choose-N-for-effect. All reuse existing wire shapes; all fall to stock
    on any off-shape answer.
38. **Symmetry break (2026-08-17).** Detect from script metadata
    (`Mode$ Continuous` + `IsPresent$ Card.Self+untapped` + `Affected$
    Player` — exactly Winter/Static Orb + Storage Matrix; auto-excludes the
    15 self-buff while-untapped cards); when the seat's untap is NEXT, offer
    `[SYMMETRY BREAK]` — tap the piece via any CostTapType outlet with the
    piece PRE-SELECTED as payment (forge-ai `TapCostPreference` hook; no
    preference → stock untouched). The one case where a mana ability IS the
    meaningful action. Window opens for the offer. Tests across two pieces ×
    two outlets + the Druid negative.
39. **Cycle replay (2026-08-17) — loops at engine speed.** Brain declares
    `repeat_cycle: N` on a decision identical to an earlier one this turn;
    the runner replays the recorded cycle (label-rebound, validated per
    window) until N rounds or ANY novelty (new stack object, changed
    options, player left, turn boundary). Life/pool are deliberately OUTSIDE
    the signature (loops move them). Game 8 live: three armed cycles
    (16+18+18 rounds), ~200 decisions at ~0.5s, three opponents killed
    sequentially, zero broken replays. Known: brains declare one window
    early (harmless refusal, self-corrects); mixed-owner cascades stay
    model-priced by design.
40. **Transport resilience + honest ratings (2026-08-17).** Game 7: one
    seat's resident session went dark 11 min (upstream 500s), another died
    MID-COMBO — and a punt answered "no" to its own free copy-cast. Fixes:
    wedge detection (sustained failure streak, not a blip) → drop --resume,
    fresh session + rejoin note; nonzero-exit logging includes stdout (the
    API-error envelope); shape-aware punt defaults; punts/wedges →
    `transport-events.jsonl` → ratings VOID (recorded, never rated).
41. **`canPayCost` guard false-positive (2026-08-17, OPEN, self-healing).**
    The note-29 affordability guard REFUSED Ruby Medallion with an untapped
    Ancient Tomb and empty pool (stock mana logic conservative about
    pain-lands?); the brain re-took the window, floated {C}{C} explicitly,
    and cast successfully — 2 extra decisions. Watch for recurrence; the fix
    direction is investigating `ComputerUtilMana`'s pain-source treatment,
    not weakening the guard (the guard exists to prevent note-29 orphaning).
42. **Launch defaults locked — Ben's four rulings (2026-08-17).** The standard
    launch is now opinionated, and every entry point agrees: (1) `react-autopass`
    removed from `arena-play` — zero absorptions across three games, the resident
    runners' allowlist fastpath subsumed it. (The script lingered as a "manual
    fallback" until 2026-09-04, when BL-15 deleted it; the claim that stood here
    until then, that `arena-stop` "still reaps a hand-launched one", was false —
    the stop script kills by PID file and its fallback patterns name only
    `GuiPilotMatch`, `run_table.sh`, `run_advisor.sh`, `seat_runner.py` and
    `advisor_runner.py`.) (2) All model
    defaults **sonnet → opus** (`run_table` `SEAT_MODEL`, `seat_runner --model`),
    so a bare `run_table` no longer silently launches sonnet. (3) Effort unified
    at **medium** everywhere (`SEAT_EFFORT`, `seat_runner --effort`; arena-play
    was already medium) — closes the low/medium split that depended on entry
    point. (4) `--human` games enable the **seat-0 Advisor BY DEFAULT**;
    `--no-advisor` opts out, `--advisor` is an accepted no-op, and a non-ingested
    deck still auto-disables the advisor with the game launching unadvised.
    README/INVENTORY updated to match.
43. **Documentation cleanup pass (2026-08-18/19, Ben-directed).** A careful
    prune that **protected Project 1** (the research → discover → compile
    pipeline and its scripts — kept intact; "zero static callers" is not a
    death test for a manually/skill/Workflow-invoked tool). Moves: retired the
    `selvala-competitive` experiment deck (raw list + primer tracked-deleted,
    `.dck`+dossier backed up out-of-repo; never a light-package deck) and
    repointed `atlas/fixtures.md` onto the live
    `selvala-heart-of-the-wilds` combo-program example; archived completed-
    milestone docs under `docs/archive/` (`SELVALA-ARC`,
    `SELVALA-BUILD-MANIFEST`, `PAIRING-AUDIT-GIADA`, `PHASE-11-PLAN`,
    `PROJECT-BRIEF`) with attendant references repointed; moved
    `T0-VERIFICATION.md` and `WIN-ROUTES` into `docs/research/`; removed
    `brain-brief-template.md` (superseded by `seatd/seat-brief.md`) and the
    `purphoros-generated-v1.md` primer-pipeline test artifact; tuned
    `seatd/seat-brief.md`; marked `SPEC-arena-add-deck` **BUILT** (status was
    stale). `docs/archive/` and `docs/research/` are both excluded from the
    light package.
44. **DeckCheck primer integration + repeatable Moxfield import (2026-08-18/19).**
    Two halves, one shippable. **(a) Shipped, keyless:** `arena-add-deck.py
    --deckcheck <url-or-id>` auto-fetches a [DeckCheck.co](https://deckcheck.co)
    analysis (prose + bracket + CRISPI ratings) from the public read endpoint and
    renders it as the strategy primer — no copy/paste, no credits, no login. Full
    protocol reference: `docs/research/DECKCHECK-ACCESS.md`. Attendant ingest
    work: MDFC (double-faced) names now resolve (Scryfall queried by the front
    face — full "A // B" names 404); `--primer-timeout` (was a hard 1200s);
    `--primer-out`; `--no-primer-rules`; and the local-fable primer (option B) is
    now fed the rules digest + summary (A/B'd for the wall-clock cost of that
    corpus). **(b) Local testing only — NEVER bundled:** `scripts/deckcheck-import.py`
    does the authenticated round-trip (login → draft → import a
    Moxfield/Archidekt URL → save-draft → visibility → paid analyze → poll →
    deckId), giving a repeatable "share a deck URL → `.dck` → dossier + combos +
    DeckCheck primer" onboarding path. It **spends credits and uses the
    `hello/deckcheck-hello` login**, so it is deliberately kept off the package
    allow-list (the distributable path is the keyless read above). deckList is the
    99-card mainboard only (commander travels in `commanderInput`).
45. **Sythis, the eighth bundled deck (2026-08-19).** Onboarded via the note-44
    pipeline; `SLUGS` gains `sythis-harvests-hand` (dossier/combos/primer
    preflight-green for the full 8-deck set). Updates the count everywhere it
    was "seven"/"six" (Track 4, `packaging/README.md`); the PATCH-NOTES v1
    section still reads "seven" as the correct historical record for v1.
46. **Advisor cadence leaned out (2026-08-19).** Supersedes note 23's cadence.
    All *in-game* advisor commentary is now tied to a **humanly-random 1-3
    windows/turn** budget (was 3-5 with guaranteed MAIN1 + combat + danger-pierce
    stops); only `MULLIGAN` is always answered, and the **end-of-turn recap stays
    ungoverned** (always fires) so a big mid-turn play a given turn's sampling
    skipped is still covered. Rationale (Ben): fewer round-trips and tokens, and
    the range reads as more alive/human than a fixed set of guaranteed stops.
    `advisor_runner.py` `_admit` rewritten.
47. **Color-matched seat avatars (2026-08-19).** Each seat gets a built-in Forge
    avatar (`sprite_avatars.png`, 126 heads) matched to its deck: `SeatAvatars`
    tallies colored mana pips across the deck, weighted-random picks a color in
    proportion to that composition, then draws a head from that color's pool
    (without replacement across the four seats). The color→heads index is the
    checked-in classpath resource `forge/arena/avatar-colors.json` (built once by
    an offline vision pass; ships in `target/classes`). Selection uses a fresh
    `Random` — deliberately **not** `MyRandom` — so avatars vary per launch
    without touching game determinism; startup-cheap (in-memory tally + pick, no
    LLM/IO at launch). **Fail-safe:** every path wrapped — any failure leaves
    `avatarIndex` at -1 and Forge's default applies; never blocks a launch.
    Assigned from `GuiPilotMatch` before `startMatch`. 40-trial pool-correctness
    test + a startup log line.
48. **Liberator, the ninth bundled deck (2026-08-19).** A **colorless** cEDH
    build (commander: Liberator, Urza's Battlethopter) — the first colorless
    deck in the bundle — onboarded through the note-44 DeckCheck pipeline;
    `SLUGS` gains `liberator-urzas-battlethopter` (dossier/combos/primer all
    present, the four per-slug package inputs the build requires). Exercises the
    avatar path's colorless branch (note 47: no colored pips → the `C` head
    pool). Track 4's count updated to 9.
49. **`playSaFromPlayEffect` seat-owned (2026-08-19).** The last un-overridden
    cast surface: engine effects that hand the AI a ready-to-cast SA
    (`PlayEffect` — Isochron Scepter copies, `DiscoverEffect`,
    `ChangeZoneEffect` play-from-exile) went to stock
    `brains.canPlayFromEffectAI`, whose doTrigger heuristics silently declined
    a copied Counterspell the seat had set up its whole turn for (validation
    game, Urza seat). Now: optional plays surface as `CONFIRM` (mode
    `PLAY_FROM_EFFECT`, `state.spell`/`state.free`); on yes (or when
    mandatory) the seat pre-aims every min>0 targeting part of the SA chain
    through `chooseTargetsFor` before `ComputerUtil.playStack` casts it.
    `rules.py` safe-default: free → yes. Guarded by `ScepterCopyCastTest`
    (untargeted Dramatic Reversal copy untaps rocks; targeted Counterspell
    copy is seat-aimed at a stack spell and actually counters). Test-fixture
    trap for the record: `ExiledWithSource` requires
    `source.addExiledCard(c)` **in addition to** `c.setExiledWith(source)` —
    without both, PlayEffect's Valid filter comes up empty and the whole
    resolution silently no-ops (which is also what an unlinked live Scepter
    would do). Bonus finding: the one-activation test brain, left unclamped,
    comboed Scepter+Dramatic Reversal indefinitely — the seat pipeline now
    executes the classic combo end-to-end.
50. **Sacrifice choices are seat-owned (2026-08-24).** Two stock fall-throughs
    thwarted play lines: (a) EFFECT path — edicts / symmetrical sacrifices /
    Balance resolve via `choosePermanentsToSacrifice` (and its twin
    `choosePermanentsToDestroy`), which went to
    `ComputerUtil.choosePermanentsToSacrifice` worst-card heuristics; both are
    now overridden → `CHOOSE_ENTITIES` (forced take-alls answered locally,
    min==0 keeps the decline with the seat, invalid answers → stock). (b)
    COST path — `AiCostDecision.visit(CostSacrifice)` picked WHICH card pays
    an outlet activation or additional-cost cast, and blanket-refused
    `Amount$ All`; a new `SacCostPreference` hook (TapCostPreference pattern:
    additive, vetted, no-preference → stock byte-identical) lets the seat
    name the payment via a live `CHOOSE_ENTITIES` exchange — safe because
    `visit(CostSacrifice)` only runs at actual payment time, never in
    affordability scans (`ComputerUtilCost` only visits counter costs).
    Guarded by `SacrificeSeatChoiceTest`: four scenarios across two card
    classes per path (Innocent Blood, Diabolic Edict; Viscera Seer, Altar's
    Reap), each proving seat authority by sacrificing the BIG creature stock
    would never pick while the stock pick survives. Brief gains a
    "sacrifices are yours to aim" bullet; the CHOOSE_ENTITIES hint names the
    surface.
51. **Stack targets announced + advisor keyword discipline (2026-08-28, game
    15).** Ben cast Beast Within at Purphoros; Urza's seat countered it with
    the REACT "why" *"Beast Within likely kills Urza"* — the brain GUESSED
    the target because stack serialization carried source/owner/kind but not
    chosen targets, which are public at any real table. `state.stackTargets`
    now announces every stack item's chain targets ("Name (id)" / "seat N";
    `StackTargetsVisibleTest`, card + player + chained multi-target shapes —
    Arc Trail's second target rides the SubAbility chain; charm modes are
    covered because `CharmEffect.chainAbilities` stitches chosen modes into
    that same chain at cast; divided amounts are appended as " [n]"). Compounding it, the
    opus advisor had twice told the pilot to hold Beast Within "for
    Purphoros" — a destroy spell against an always-indestructible god,
    violating the brief's own check-card-text rule; the rule is now a
    verification step (read the target's serialized `keywords`, say why the
    spell beats its protections) with the incident as the example. Bright
    side, same game: Y'shtola answered a Power Artifact/Grim Monolith
    infinite-mana assembly by bouncing the Monolith AT AIM on the stack —
    the aura fizzled (textbook TARGETLOSS diagnostic capture) — and all
    three seats no-blocked a lethal 190-power trample alpha with honest
    arithmetic. 289 decisions, 0 punts/lost/wedges. Sacrifice surfaces:
    still zero live windows after two hunts (test-guarded only).
52. **Wave-2: the dual-audit sweep lands (2026-08-28).** All ten audit
    findings (SEAM-AUDIT-2026-08-28.md) fixed in one rationalized change-set
    on three shared mechanisms — `cardChoiceViaSeat`, `CHOOSE_NUMBER`, and
    the `CHOOSE_MODE` index shape — plus ONE new forge-ai interface
    (`PaymentPickPreference`) covering all four pitch-cost types. Now
    seat-owned: cleanup discard + mulligan bottoming; scry/surveil/library
    ORDER (answer order = final order, FIRST = top)/clash; generic numbers +
    non-mana announces; retargeting spells (`chooseNewTargetsFor` — stock
    returns null, a seat-cast Deflecting Swat was a silent no-op; single-
    target changes seat-aimed, restore-on-decline mirrors the human
    controller); optional costs (always mailboxed — one option is still a
    real yes/no); protection type, votes, pile splits (FaceDown domain
    False/One/True — review catch: the first cut leaked the hidden pile's
    contents; fixed + regression-asserted); mixed Card+Player choices
    (sequential synthetic ids); `stackOracle` serialization. Runner:
    `_react_signature` gains phase + combat + stackTargets digests (a
    correct early-combat pass no longer eats the post-blocks fog window —
    audit finding 1), and the autopass allowlist skips any window whose
    stackTargets name our stuff (note 12's dropped clause restored).
    Deferred with rationale: `chooseSingleReplacementEffect` (spam risk),
    routine tap-pick generalization (mana-loop pacing). Process: full diffs
    side-by-side reviewed by Gemini pre-finalize — 1 BLOCKER refuted by code
    inspection (`clearTargets()` REASSIGNS `targetChosen`, so save/restore
    of the old TargetChoices is sound — the human controller's own pattern),
    1 real FIX applied (pile visibility), 4 risk spots confirmed OK, verdict
    SHIP. Tests: shared `MailboxTestKit` harness (direct-call style — the
    fixture six older files each copy-pasted); 17 new Java + 7 new Python.
53. **Harness boil (2026-08-28, Ben-approved A–D).** Full-gate census: P1
    owned 73% of suite time (the full game IS those tests' oracle — hands
    off); P2's cost was game-boots + poll pacing, not assertions. Landed:
    (A) standard gate = `-DskipTests` (parents build, tests skip, arena
    suite runs anyway — the pom's arena.skip.tests design); FULL gate on
    parent-touching change-sets + syncs. (B) `arena.mailbox.poll.ms=5` in
    surefire; interactive consolidations (12→1, 5→1, 3→1, 4→3, ~9→1 games)
    — one merge (Blood+Edict) tried, timed out against the fixture's tiny
    libraries, and was REVERTED per the anti-contortion rule. (C) measured,
    revertible divergence-test knobs: sim turn cap 8→5 = 114s→15s with
    divergence intact at seed 1 (`-Darena.test.divergence.simTurnCap=8`
    reverts); profile divergence sits at seed 5, so seedTries stays ≥5.
    (D) AiTabHarness relic deleted. Full policy: IMPLEMENTATION-PLAN §8 +
    BUILDING.md.
54. **Wave-3: adversarial validation of wave-2, all ten findings fixed
    (2026-08-31).** Ben's mandated second pass — the wave-2 change-set plus
    my ten local-review findings went to Gemini with FULL context (whole
    seam + runner + every upstream call-site + repo map + explicit
    context-request protocol). Verdict: 10/10 VALIDATED, zero context
    requests, zero new findings, REJECT until fixed. Root-cause classes:
    (1) planning/execution leakage — the engine reuses decision surfaces to
    EVALUATE moves (getOriginalAndAltCostAbilities consults
    chooseOptionalCosts at enumeration; DrawAi.willPayCosts visits cost
    parts during scans); (2) human/AI path divergence (announceRequirements
    is human-only; Multikicker actually flows through
    chooseNumberForKeywordCost at execution time); (3) string-matching
    fragility. Fixes: optional costs became CAST-WINDOW VARIANTS (override
    returns empty during own enumeration, stock elsewhere; affordability
    vetted at offer); payment hooks are DEFAULT-DENY outside an executing
    cast (inPaymentContext — kills DrawAi and every unaudited planning
    caller); shape-aware number punts (puntHigh); top-of-library order
    reversed to engine parity (consumers stack one card at a time, LAST
    ends on top — Gemini's wave-2 OK-note on this was WRONG);
    chooseNumberForKeywordCost override (the real Chalice surface) with an
    affordable cap; threat clause strips divided-damage suffixes and skips
    own-owned stack items; kit DirectoryStream in try-with-resources;
    redirect confirm keyed on ApiType.ChangeTargets, not localized text.
    Proven by CastPathReachabilityTest: four END-TO-END casts through the
    real window flow asserting RESULTING STATE (buyback returns to hand,
    the discard payment takes the named card, Top's order physically
    lands, Chalice enters with the chosen kicks). Debugging lesson: ZONE
    MOVES CAN CREATE NEW CARD INSTANCES (sa.setHostCard(moveToStack(...)))
    — a pre-cast test reference goes stale at cast; assert final state by
    name+zone lookup, never by held reference. Honest scope note: hooks
    now also deny during stock-fallback casts and unless-cost payments
    (stock pays stock — fail-safe preserved, agency narrower; revisit if
    live games show it mattering).
55. **Deck loadability becomes a gated pipeline concern (2026-09-01).** Two
    consecutive new decks failed at their FIRST live launch on `.dck`
    defects invisible to the file-presence preflight: Y'shtola's raw
    Moxfield export (no sections) and Sheoldred's transform commander
    written as "A // B" (Forge names transform/MDFC/adventure cards by the
    FRONT face; only split-layout cards keep the full name — the loader
    silently resolves nothing, or worse, silently DROPS unresolvable main
    cards). Three-tier fix: (1) `arena-add-deck` now REGENERATES the
    registered .dck with layout-aware Forge names (Scryfall layout data)
    and runs `DeckLoadProbe` — a real-DeckSerializer load asserting
    commanders present and exactly 100 cards resolved — as step 4.5;
    (2) launch preflight gains a cheap static check (sections, non-empty
    [Commander], 100 copies) on every AI deck at every launch; (3)
    `DeckLoadProbeTest` loads every shipped .dck in the suite — the net
    that would have caught both bugs. `deckcheck-import` also writes
    commander lines front-face. ArchUnit note: the probe lives in
    `forge.arena.interactive` (it predicts GuiPilotMatch loadability) —
    `prep` may not touch `forge.deck` per the EngineFacade boundary, and
    the boundary test caught exactly that on the first draft.
56. **Counting is not resolving — the 95-card game (2026-08-31, game 18).**
    A live four-AI table (Giada/Sheoldred/Selvala/Sythis) showed Sythis
    opening at library 88 + hand 7 = 95, and gui.out carried four
    `An unsupported card was requested` lines: Katilda, Strength of the
    Harvest, Bala Ged Recovery, Branchloft Pathway — modal-DFC / disturb
    lines still written "A // B" in a deck ingested before note 55's
    front-face rule. Urza's list had the same defect (Wandering Archaic; it
    won game 17 playing 98). Why note 55's nets missed it: the loader does
    NOT drop an unresolvable name — `CardPool.add` inserts CardDb's
    UNSUPPORTED PLACEHOLDER (`CardRules.isUnsupported()`), so
    `countAll()` still says 100 and only the match drops the card. Fix:
    (1) `DeckLoadProbe.unsupportedNames()` scans the resolved pool and the
    probe + `DeckLoadProbeTest` fail on any placeholder, naming it; (2) the
    launch preflight's static check now resolves every "A // B" line
    against the card scripts — `AlternateMode:Split` keeps the full name,
    anything else must be the front face — no JVM, runs on every AI deck
    every launch; (3) the five lines fixed, plus Sythis's `[metadata]`
    Name (it still carried the Moxfield title). Also landed from the same
    session: `scripts/arena-cardwatch.py`, a card-conservation watcher
    that polls the transient seat requests (the only feed carrying every
    zone) and prints per-seat nontoken totals on change — Sythis's 97
    baseline (95 + commander + "Commander Effect") was the tell; its notes
    explain the benign GAIN/DROP pairs from mid-resolution transit
    snapshots. Advisor tab: the pause button now has three states (OFF —
    not attached / ON / PAUSED) via `AiControlFile.advisorAttached()`; it
    read "ON — click to pause" in advisor-less games because
    `advisorEnabled()` is only the pause flag and defaults true.
57. **Trigger-aim contract (2026-09-03, interactive plan item 1).** The
    full review found two defects in `prepareTriggerViaSeat` /
    `chooseTargetsFor`: (a) the id-0 "DECLINE this optional trigger" option
    was offered for EVERY aimed trigger, so a brain could "decline" a
    MANDATORY one — the code auto-aimed the first legal candidate to stack
    it legally and `confirmTrigger` (true for mandatory) let it resolve
    against a target the brain never chose; (b) a failed exchange (timeout,
    malformed, unknown id) returned the same `false` as an explicit decline,
    so a silent brain silently threw its own triggers away — the only
    surface whose timeout did not fall to stock. Now: optionality is read
    from the root `WrappedAbility` (`isMandatory()`), the decline option is
    offered only for optional triggers, `chooseTargetsFor` records
    ANSWERED / DECLINED / NO_ANSWER while aiming, and NO_ANSWER hands the
    whole trigger to stock (`doTrigger`) with a "no usable answer at aim —
    stock aims" log line. Explicit decline of an OPTIONAL trigger keeps the
    rules-correct sequence (CR 603.3d: aim to stack legally, decline at
    resolution). `TriggerAimContractTest` pins it with two cards from one
    cast — Ravenous Chupacabra (mandatory) + Aura Shards (optional) — and
    a silent-brain scenario via the kit's new `SILENT` responder.
58. **Liveness, identity and budget as protocol facts (2026-09-03, plan
    items 2, 3, 8, 10, 12).** Three things the runner used to GUESS are now
    stated by the engine. (a) `gameId` on every request and feed file: a
    fresh runner adopts the id it sees (rejoin), an id CHANGE resets memory
    and sweeps the outbox, an already-answered request the engine was slow
    to delete is skipped — the 3 s delete-race heuristic and the advisor's
    file-number comparison were both wrong in reachable cases. (b)
    `timeoutSec` on every request: the runner budgets from the engine's
    actual wait, and `decide()` carries ONE deadline through init and the
    decision call (the old code handed the same budget to both, so a lazy
    re-init could block a seat for 2x the window). Timeout stays the explicit
    `--timeout` flag — never derived from effort, never clamped; mismatches
    are legitimate experiments. (c) `<seat-dir>/heartbeat`, touched every
    5 s by a daemon thread in each runner (and the advisor): the engine stats
    it once before blocking; older than 15 s (`arena.mailbox.heartbeat.stale.ms`)
    means nobody is home and stock plays at once, one log line per
    transition; absent (older runner) or unreadable = wait as always — the
    gate can only shorten a wait. `observer-state.json` seats carry
    `brainAlive` (true/false/null) and the ELO spool carries per-seat
    `stockDecisions`. Also: a punt no longer feeds the REACT memo (only
    `source == "model"` does), and the CONFIRM punt is structural — yes only
    when `isMine && !hasCost` — replacing a word heuristic where "play"
    matched "player".
59. **Scryfall canonical, Forge at the boundary, 400 cards or no game
    (2026-09-03, plan item 7).** The 09-01 DFC rule in arena-add-deck (layout
    'split' keeps "A // B", everything else front face) was a whitelist, and
    it already missed Rooms (layout 'room'; Forge keeps the combined name) —
    the next ingest would have rewritten Sythis's correct Secret Arcade line
    into a placeholder. Now: (a) Scryfall is canonical in every built file
    (`deck-cards.json` entries carry `scryfall_id`, `set`,
    `collector_number`; `name` stays Scryfall's); (b) Forge's name is looked
    up in Forge's OWN database by `DeckLoadProbe --resolve` — the PRINTING
    first (Scryfall set + collector number → edition entry → card DB), name
    forms second (combined, then front face) — and stored as `forge_name`,
    the only thing the .dck writer reads; (c) anything unresolved is a NAMED
    failure before a single file is written (Forge lacks the newest sets and
    some cards forever — the game must not start short, so neither may the
    ingest); (d) ingest writes `dossier/manifest.json` (.dck SHA-256, card
    count, a card-DB stamp, every resolution) and the launch preflight
    compares the hash in milliseconds — missing manifest or changed .dck
    refuses with the fix named, a changed DB stamp only warns; NO JVM at
    launch, ever (Ben: "15 s at startup is way too long"); (e) start
    invariant — GuiPilotMatch runs `playabilityProblems` on every loaded deck
    and refuses a seat short of 100 real cards, writing
    `mailbox/launch-status.json` so arena-play reports it at once; (f) end
    invariant — GameResultSpool counts every owned card across all zones
    (tokens/copies/emblems/effects excluded) and logs `CARD-CHECK` per seat or
    `CARD-VANISH` on a shortfall, with `cards`/`deckSize` in the spool.
    `--manifest-only` writes the manifest for a deck whose dossier another
    tool built (the four Java-prepped decks), touching nothing else. Tests:
    `DeckLoadProbeResolveTest` (Room + MDFC by printing, name-form fallback,
    unresolved, placeholder named), `CardConservationTest`.
60. **The wire contract, tested from both sides (2026-09-03, plan item 15).**
    Fourteen decision types and ~25 state keys were specified in prose and
    checked by `String.contains` in test brains; the Python punts were tested
    against hand-written fixtures that agreed with the Python validator by
    construction. Now `schemas/arena.mailbox-request.1.schema.json` states
    the request shape (top-level fields, the state keys a reader may rely on,
    per-type conditionals), `ProtocolContractTest` drives nine surfaces
    through the real controller, validates every request the engine wrote
    against it and writes one ENGINE-EMITTED fixture per type to
    `runner/tests/fixtures/engine/`, and `test_engine_fixtures.py` feeds each
    through `rules.safe_default` + `rules.validate`. A field the engine
    renames now fails a Java test; a punt the engine would reject now fails a
    Python test. Also in this item: the four seam tests still using the
    probe regex INVENTORY §3 forbids (matching `"id":N` anywhere in the body)
    moved to the kit's anchored option lookups (`idOf`/`idOfWhere`), and the
    nine pre-kit classes whose scripted brains polled for 150 s past their
    test now stop with the test (`legacyBrainAlive` + `@AfterMethod`).
    `HeartbeatGateTest` is the suite's first dead-brain test.
61. **Trigger ordering is the seat's (2026-09-04, BL-02, CR 603.3b).** Game
    19: `orderSimultaneousSa` fired 6× for the sacrifice deck in batches of
    2–22, every order chosen by stock. Now `MailboxController.
    orderSimultaneousSa` groups the seat's simultaneous triggers by
    `triggerKey` (host name + trigger text); with two or more DISTINCT groups
    it opens a `CHOOSE_MODE` window with `state.purpose = "TRIGGER_ORDER"`,
    one option per group (label `host — text`, suffix `×N` for N identical
    triggers), `min = max = groups`, `allowRepeat = false`. The answer lists
    the groups in RESOLUTION order — first listed resolves first — and
    `orderViaSeat` reverses it into stack-push order. One group (a batch of
    identical triggers) never opens a window, which is what keeps a
    22-trigger death batch cheap. Anything but a full permutation (null,
    repeat, out of range, wrong count, exception) → `super.
    orderSimultaneousSa`, counted by `stockSurface`. Runner: no new
    validator — CHOOSE_MODE's min = max plus the no-repeat rule already force
    a permutation; the brief gained a paragraph. `TriggerOrderWindowTest`:
    two pairs of death triggers on different cards (Midnight Reaper resolves
    first; Grim Haruspex + Cruel Celebrant as the second pair), identical
    triggers open no window, a silent brain falls to stock. Landed in
    2bc78d92188 with the standard gate still to run. See it live:
    `grep TRIGGER_ORDER runner/logs/seat-N.jsonl`.
62. **Colour choice is the seat's outside payment (2026-09-04, BL-03).** Game
    19: `chooseColor` / `chooseColorAllowColorless` was the most consulted
    stock surface (27 consultations — engine asks, not decisions; W-1). Now
    `colorViaSeat`: when NOT `inPaymentContext` and two or more colours are
    legal (WUBRG filtered by the offered `ColorSet`, plus "colorless" when
    the allow-colorless overload asks), a one-pick `CHOOSE_MODE` window with
    `state.purpose = "COLOR"` and the colours' long names as option labels.
    Payment-context consultations (the payer's planning scans and
    tap-for-this-cost picks — the wave-3 F2 lesson) and single-colour asks
    stay stock; null or malformed → stock. Gated on context, never on card.
    `ColorChoiceWindowTest`: Voice of All + Story Circle by direct controller
    call; a payment context opens nothing; silent → stock. Same commit and
    gate status as note 61. The human seat's mono-colour autopick (advisor
    QoL) is untouched.
63. **One bus per seat directory, and the master's own board (2026-09-04,
    BL-05, CR 721.3).** `MailboxProtocol.forSeat` now caches one instance per
    normalized seat directory (`BUSES`). The request sequence lives on the
    bus, and item 11a's Mindslaver controller had been built on a FRESH bus
    for the master's directory — `seq` restarted at 1 and the runner rightly
    skipped the reused file names as already answered. `MailboxLobbyPlayer.
    createMindSlaveController` also passes the master `Player`; every
    controlled request now carries `state.controllerBoard` — the master's own
    `seat, life, poison, hand, handSize, battlefield, graveyard, exile,
    commandZone, librarySize, manaPool, manaAvailableNow, manaSources,
    untappedManaSourceCount` — the master's brain reading its own hand while
    it plays the slave's cards; a seat playing itself carries no such key.
    `MindSlaveRoutingTest` asserts both (the master's Sol Ring in hand is
    visible); `StaleOutboxSweepTest` asserts `forSeat` identity. Schema gains
    `controllerBoard`.
64. **Observer snapshot: write on change, no timer (2026-09-04, BL-07).** The
    200 ms debounce had no trailing edge — the last event of a burst was never
    written — and `write` was unsynchronized. Ben: no scheduler. Now
    `ObserverSnapshot.write` is `synchronized`, serializes on EVERY event,
    strips the timestamp, and skips the write when the bytes equal the last
    write (`lastKey`); game-over still forces one. `WRITES` counts for tests;
    `ObserverSnapshotWriteTest`: two life changes in a row → the second is on
    disk; identical events → no rewrite.
65. **Decision log: two plain files, archived together (2026-09-04, BL-21;
    reverts item 13h).** Item 13h made `game.jsonl` a symlink re-pointed per
    game; `arena-digest.py` kept the old inode and went silent after game
    one, `arena-stop` counted only the current game while printing
    "(preserved)", and every plain `tail -f` broke. Ben: "avoid any solution
    that risks file corruption, fragments or failures." Now
    `runner.py:_game_log_paths` appends each record to `game.jsonl` — a PLAIN
    append-only file for the whole session, the human `tail -f` target — AND
    to `game-<gameId>.jsonl`, the per-game machine record
    (`ratings.slice_game_log` reads every regular `game*.jsonl` beside it);
    a symlink left by a pre-BL-21 runner is unlinked once. Transport events
    are not rotated either: each carries `gameId` and the void check filters
    by the spool's id (BL-09; unstamped events still count). `arena-stop.sh`
    archives `game.jsonl` and `game-*.jsonl` with the seat logs whenever ANY
    session log exists (the old test needed seat logs AND gui.out together)
    and prints `N decisions across M game(s) (archived)`. `replay.py` prints
    one line and exits 2 when `tests/fixtures` is absent — the package
    excludes both the fixtures and the script.
66. **Stale outbox swept at construction (2026-09-04, BL-22).** A JVM crash
    leaves `resp-N.json` behind; a hand relaunch that skipped `arena-stop`
    could let the new engine consume it as the answer to THIS game's request
    N. `MailboxProtocol`'s constructor deletes `outbox/resp-*` and `*.tmp`
    and logs `swept N stale outbox file(s) at start`; the runner's sweep on a
    gameId change (note 58) stays. `StaleOutboxSweepTest`.
67. **Brain calls load no settings (2026-09-04, BL-24).** `claude -p` ran with
    default setting sources, so every decision loaded the operator's user and
    project settings, hooks and plugins. Now every call passes
    `--setting-sources ""` (probed: accepted, OAuth login unaffected; `--bare`
    was ruled out — it disables OAuth and the seats run on the subscription).
    NOT changed, per Ben ("running in / is not safe"; no hidden directories):
    the working directory — calls still run from the repo / package root
    (`brain.py` `self.root`), so the CLI still auto-discovers `CLAUDE.md` files
    in the directories above it. The README's Requirements footnote says so;
    `test_golden_claude.py` pins the argv.
68. **Protocol edges (2026-09-04, BL-28; Gemini round two, verified).** (a)
    `gameIdFor` is `millis-pid-serial` (`GAME_SERIAL`, an AtomicInteger): two
    Games created in one millisecond of one JVM shared an id. Schema pattern
    widened, the fixture normaliser keeps `"1-1"`, `ProtocolFieldsTest`
    asserts distinct ids for back-to-back games. (b) `seat_runner.py`
    installs SIGTERM/SIGINT handlers that call `brain.kill_child()` on the
    tracked `Popen` (`brain._run` reports the child through `on_child`), so
    teardown no longer orphans one in-flight `claude` call per seat. (c)
    `runner.py`: when the request file has already vanished on a real inbox,
    the budget is zero and the seat punts at once (`punt: request file
    vanished`) — the mtime fallback used to grant a fresh window. Tests in
    `test_round_two_runner.py` and `test_round_two_brain.py`.
69. **Punts are unreplayable (2026-09-04, BL-20).** Sibling of item 3's memo
    bug: cycle replay appended every answer to `_hist`, punts included, so a
    punted CONFIRM inside a loop could replay as source `cycle` for up to 64
    rounds, uncounted as punts. Now a punt is recorded with shape `None`,
    `_cycle_try_arm` refuses any candidate cycle containing a non-replayable
    step, and a runner exception clears the tape. Alongside (BL-08):
    `_cycle_rebind` matches label + type + cost before the label-prefix
    fallback, so one costed ability on a card cannot cross-bind to another.
    `test_round_two_runner.py`.
70. **Single legal defender filled in (2026-09-04, BL-23).** `rules.validate`
    hard-rejected a DECLARE_ATTACKERS entry without `defender`, while the
    engine's `chooseDefender` accepts that when exactly one defender is legal
    — so with one opponent left a Java-legal answer punted to
    `{"attackers": []}`. Now the sole legal id is filled in; with several
    legal defenders the field is still required. `test_rules.py` +
    `test_round_two_runner.py`.
71. **Default rosters (2026-09-04, item R, Ben).** One rule, three
    implementations that must agree: an all-AI table seats Urza, Giada,
    Purphoros, Selvala in that order; a human game seats the human's deck at 0
    (Selvala when none is named — ANY ingested deck otherwise) and then the
    first three roster decks that are not the human's (Urza, Giada, Purphoros
    for the default). Sources: `GuiPilotMatch.DECKS` + `buildRoster` (static
    and GUI-free — extracted from `startCommanderMatch` with `verifyRoster`
    and `slugOf`, the BL-12 prep; a missing deck file is a launch-status
    problem), `run_table.sh` (`ARENA_HUMAN_DECK`, passed by `arena-play.sh`),
    `advisor_runner.DEFAULT_TABLE` + `table_opponents`. `ARENA_SEAT_DECKS`
    still overrides all three together. `test_round_two_ops.TableRosterRule`.
    Same batch (BL-27): `arena-play.sh` and `run-pilot-match.sh` refuse a deck
    file name containing whitespace with a one-line message, and
    `arena-stop.sh` only signals PIDs whose command line names this checkout.
72. **Advisor supervised, bounded and guarded (2026-09-04, BL-26 / BL-13).**
    The advisor ran once under nohup; one I/O error ended it silently while
    the engine kept filling its inbox. Now `arena-play.sh` starts
    `runner/run_advisor.sh`, the same restart-loop shape as `run_table.sh`'s
    seats (2 s damper; the loop's PID in `logs/pids/advisor-loop.pid`, the
    child's rewritten to `logs/pids/advisor.pid` on every restart); its log
    and stream writes are guarded with `except OSError`; `pending_context` is
    bounded to `CONTEXT_MAX_LINES = 40`, dropping the oldest and saying how
    many. Same batch, ratings: `sweep` lists spools UNDER the lock, a spool
    another sweeper already renamed is not an error, and a malformed spool is
    marked `.skipped` with the missing key named. `test_round_two_ops.py`.

73. **Ask the advisor (2026-09-04, Ben).** The Advisor tab has a text field
    and an **Ask** button (Enter sends). `AiControlFile.askAdvisor` writes
    `logs/control/ask/ask-<millis>-<serial>.json` atomically (temp +
    ATOMIC_MOVE, whitespace/control characters collapsed, 500-char cap);
    `advisor_runner._handle_asks` scans the directory every poll in numeric
    order, deletes each file on pickup (the panel's "sent" signal — the
    button reads *Sending…* until then, and says so after 20 s with nobody
    home), folds any pending context, makes one direct call and streams
    `[tN · you] q` / `[tN · advisor] a`; record kind `ask` in
    `advisor-0.jsonl`. Questions are handled BEFORE the pause gate, so a
    paused advisor still answers a typed question. Same one-way file channel
    as every other advisor path — no socket, no engine thread, nothing the
    game can wait on. Table talk between seats was considered and dropped
    (prompt cost on every decision, hidden-information posture).

74. **Auto-teardown when the match is fully finished (2026-09-04, Ben).**
    Games used to loiter: after the outcome the JVM kept the match screen
    up and every runner polled forever. `arena-play.sh` now starts
    `scripts/arena-autostop.sh` (PID in `pids/autostop.pid`) once the match
    is live: a plain sleep loop (no scheduler) that polls the observer
    snapshot for the engine's own `gameOver: true` (a forced write on the
    outcome event) or for the GUI JVM's PID to vanish (window closed), then
    lingers `--linger N` seconds (default 600 in human games so the final
    board can be read, 60 all-AI; 10 when the GUI is already gone) and
    `exec`s `arena-stop.sh` — the same kill/rate/archive/clear as a hand
    stop. A hand stop always wins: `arena-stop` kills a waiting watcher by
    its PID file (`ours()` marker), and a watcher that wakes to a cleared
    mailbox exits without stopping anything. `--no-autostop` leaves the
    table up. Tests: `runner/tests/test_autostop.py` drives the script through
    its env hooks against a temp tree with a stub stop command.
