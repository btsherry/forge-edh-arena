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

> Status: research prototype ("v1"). Built on Card-Forge/forge (GPL-3.0);
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

All new code lives in `forge-arena/src/main/java/forge/arena/interactive/`. No
parent-module patches — it rides the same controller-injection seam the headless
arena uses.

| File | Role |
|---|---|
| `MailboxProtocol.java` | The file bus. Per-seat `inbox/`+`outbox/`; atomic writes (temp+rename); poll for the response; timeout → `null` (caller falls back to stock). Request/response wire records. No Forge imports — pure transport. |
| `MailboxController.java` | `extends forge.ai.PlayerControllerAi`. Overrides the top-level decisions (`chooseSpellAbilityToPlay`, `mulliganKeepHand`, `declareAttackers`, `declareBlockers`) **plus high-value sub-choices** (`chooseSingleEntityForEffect`, `chooseEntitiesForEffect`, `chooseModeForAbility`, `chooseSingleCardForZoneChange`). Serializes a hidden-info-safe state and exchanges it over the bus. **Every override times out to `super` (stock AI)** so a silent/slow brain never hangs the game. |
| `MailboxLobbyPlayer.java` | `extends forge.ai.LobbyPlayerAi`. Injects the controller via `IGameEntitiesFactory.createIngamePlayer` (the seam both headless and GUI paths converge on — `Game.java`), so a mailbox seat is honored in a GUI game with no engine/GUI patch. |
| `GuiPilotMatch.java` | `main(...)` launcher: bootstraps the desktop GUI, seats a human at seat 0 and `MailboxLobbyPlayer`s at seats 1–3 over the four decks, and starts the match so the human's `IGuiGame` renders it. |

### The hybrid control model (important)

The mailbox controller intercepts the seat's **own main phases** (MAIN1 /
MAIN2, empty stack), **mulligan**, **combat declaration**, and a set of
**high-value sub-choices** the seat makes while resolving its own effects (copy
choice, choose-a-permanent, modal/charm modes, tutor/fetch selection). It also
intercepts **reactive (instant-speed) windows**: when an OPPONENT has a
spell/ability on the stack and the seat holds a castable instant-speed response,
the seat is consulted (`REACT`). Windows not worth the brain's time — empty-stack
instant priority, the seat's own spell merely resolving, forced passes — still
fall through to stock `PlayerControllerAi`.

Consequences:
- The agent plays **sorcery-speed strategy AND its own instant-speed responses**
  to opponents' spells (counter, protect, removal-in-response), at agent quality.
  Still on stock (bounded out to avoid flooding): proactively flashing into an
  empty stack, and responding to interaction *during the agent's own turn*.
- **Sub-choices now the agent's:** which creature to copy / choose (Glasspool
  Mimic, Clone, "choose target creature" resolution effects → `CHOOSE_ENTITY` /
  `CHOOSE_ENTITIES`), which mode of a charm/modal spell (`CHOOSE_MODE`), and
  which card a tutor/search fetches (`CHOOSE_CARD`). These are gated narrowly to
  *genuine* choices (>1 legal option, or an optional single) and, for the entity
  hooks, to card/permanent options only.
- **Sub-choices still stock:** normal **spell targeting** (`chooseTargetsFor`
  mutates the SpellAbility in place — deliberately left on stock), plus all the
  trivial/forced hooks (`confirmAction`, trigger ordering, mana-color, numbers,
  yes/no). So a line whose value hinges on a *spell target* (as opposed to an
  effect's choose/copy/mode/fetch) is still stock's.

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
stock AI. The engine deletes both files once the response is read.

**Request** (`req-<n>.json`):
```json
{
  "seq": 12, "seat": 3, "turn": 22, "phase": "MAIN1",
  "decisionType": "CAST_SPELL | REACT | MULLIGAN | DECLARE_ATTACKERS | DECLARE_BLOCKERS | CHOOSE_ENTITY | CHOOSE_ENTITIES | CHOOSE_MODE | CHOOSE_CARD",
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
    /* + "min","max" for CHOOSE_ENTITY/CHOOSE_ENTITIES/CHOOSE_MODE/CHOOSE_CARD */
    /* + "allowRepeat":bool for CHOOSE_MODE; "destination":<zone> for CHOOSE_CARD */
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
  request's `min`/`max`, no duplicates.
- `CHOOSE_MODE` → `{"chosen":[<modeIndex>, …]}` — mode option ids are **indices**
  into `options`; must satisfy `min`/`max`; may repeat an index only when
  `allowRepeat` is true.
- `CHOOSE_CARD` → `{"chosenId": <cardId>}` — the tutored/searched card (id `0` =
  choose none, offered only when optional).

Malformed / unknown ids / wrong-count / illegal choices fall back to stock
(never partially applied). Trivial windows (no castable ability / no eligible
attacker or blocker; a forced single sub-choice; a non-card entity option) are
**not** sent — they auto-pass to stock ("Lever 2", the controller gates).

## Running it

```sh
# Desktop GUI, human vs 3 mailbox seats (Selvala seat 0 by default):
ARENA_MAILBOX_TIMEOUT=600 forge-arena/scripts/run-pilot-match.sh
# Ground-truth table dashboard (whose turn, all seats' life/board, pending decision):
python3 forge-arena/scripts/arena-status.py
# Plain GUI launch (no mailbox):
forge-arena/scripts/run-gui.sh
```
The launcher runs from `forge-gui/` (Forge resolves `res/` from cwd) and pulls
the desktop `--add-opens`/JVM args from `forge-gui-desktop/pom.xml`. Decks are
read from Forge's Commander deck folder + `forge-arena/decks/`.

**The brain side:** one agent per seat, given a static brief (its own deck's
oracle text + primer + a short EDH rules card) once, then resumed per decision
(context persists — the deck is not re-read). An orchestrator watches the
inboxes (see `arena-status.py`, or a file monitor) and routes each pending
request to the right agent, which writes the response file.

## Known limitations (v1)

1. **Reactive play is partial.** The agent now makes its own instant-speed
   responses when an opponent has a spell/ability on the stack (`REACT`), but
   proactively flashing into an empty stack, and responding during the agent's
   own turn, are still stock (bounded out to avoid flooding own-turn windows).
2. **Some sub-choices go to stock.** The agent now makes copy/choose, modal, and
   tutor-fetch sub-choices (`CHOOSE_ENTITY`/`CHOOSE_ENTITIES`/`CHOOSE_MODE`/
   `CHOOSE_CARD`), but **normal spell targeting is still stock** (`chooseTargetsFor`
   mutates the SpellAbility in place and is deliberately not intercepted) — see
   hybrid model.
3. **Narration is unreliable.** Agents sometimes report plays that didn't happen;
   trust the board (`arena-status.py` / the request state), not the agent's prose.
4. **Observer snapshot is coarse.** The dashboard now stays live during the
   human's turn via the public event-bus `observer-state.json`, but it's a
   ~200ms-debounced public snapshot (no hands/libraries), not a per-priority feed.
5. **Latency.** Each consulted decision costs an agent resume + think (seconds to
   minutes on a large model). A per-decision poll from the orchestrator batches a
   whole turn per wake to reduce this.

## Upgrade roadmap

**Track 1 — loop tightening & action speed**
- ✅ Lever 2: trivial-subphase gate (empty windows auto-pass to stock).
- ✅ Terser brain protocol: `{chosenId}` + one-line reason (see `brain-brief-template.md`).
- Whole-turn drain (batch a turn per wake) + a file monitor as the cross-phase backstop.

**Track 2 — observability & correctness (highest play-quality value)**
- ✅ Richer serialization: per-card P/T, counters, tapped/sick, attached auras, and
  activated abilities with their mana output (own battlefield). Fixed the former
  name-only blind spots.
- ✅ Persistent public observer snapshot (`observer-state.json`, event-bus driven)
  so the dashboard/observer is never blind, including during the human's turn.
- Anti-confabulation: feed the resulting state back; agents re-derive from the
  request each time.

**Track 3 — deeper capability**
- ✅ Sub-choice mailboxing (copy/choose, modes, tutor fetch → `CHOOSE_ENTITY`/
  `CHOOSE_ENTITIES`/`CHOOSE_MODE`/`CHOOSE_CARD`). Remaining: normal spell
  targeting (`chooseTargetsFor`).
- ✅ v2 reactive windows (`REACT`): agent responds at instant speed to opponents'
  stack objects. Remaining: proactive empty-stack flash, own-turn responses,
  and normal spell targeting (`chooseTargetsFor`).
- Teacher→student: feed caught misplays into both the agent briefs and the
  deterministic runner.

**Track 4 — packaging & release**
- Versioned protocol spec + docs + an example brain → "bring your own agent."
- Self-contained module (seat + launcher + scripts + dashboard).
- GPL-3.0, non-commercial fan-content compliance; no card images needed for the
  mailbox path.
