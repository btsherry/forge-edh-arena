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
| `MailboxController.java` | `extends forge.ai.PlayerControllerAi`. Overrides `chooseSpellAbilityToPlay`, `mulliganKeepHand`, `declareAttackers`, `declareBlockers`. Serializes a hidden-info-safe state and exchanges it over the bus. **Every override times out to `super` (stock AI)** so a silent/slow brain never hangs the game. |
| `MailboxLobbyPlayer.java` | `extends forge.ai.LobbyPlayerAi`. Injects the controller via `IGameEntitiesFactory.createIngamePlayer` (the seam both headless and GUI paths converge on — `Game.java`), so a mailbox seat is honored in a GUI game with no engine/GUI patch. |
| `GuiPilotMatch.java` | `main(...)` launcher: bootstraps the desktop GUI, seats a human at seat 0 and `MailboxLobbyPlayer`s at seats 1–3 over the four decks, and starts the match so the human's `IGuiGame` renders it. |

### The hybrid control model (important)

The mailbox controller only intercepts the seat's **own main phases** (MAIN1 /
MAIN2, empty stack) plus **mulligan** and **combat declaration**. **Every other
priority window — opponents' turns, instant-speed responses, sub-choices
(targets, modes, copy choices) — falls through to stock `PlayerControllerAi`.**

Consequences:
- The agent plays **sorcery-speed strategy**; **stock AI plays all reactive /
  instant-speed windows** (including casting a held-up counterspell on an
  opponent's turn). So "hold up interaction" is a real option — executed at
  *stock* quality, not agent quality.
- Sub-choices for a chosen spell (which creature to copy, which mode, targets)
  are made by **stock**, so an agent can't yet execute a line whose value hinges
  on a sub-choice (e.g. Glasspool Mimic's copy target).

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
  "decisionType": "CAST_SPELL | MULLIGAN | DECLARE_ATTACKERS | DECLARE_BLOCKERS",
  "prompt": "…",
  "state": {
    "seat","turn","phase","life","manaPool","untappedManaSources",
    "handSize","handLands","librarySize","ownBoardPower",
    "battlefield":[…names…],"hand":[…names…],"command":[…],"graveyard":[…],"exile":[…],
    "stack":[…],
    "opponents":[{"seat","life","poison","creaturePower","battlefield":[…names…]}],
    /* + "defenders":[{id,label,type}] for DECLARE_ATTACKERS */
    /* + "attackers":[{id,label}]       for DECLARE_BLOCKERS  */
  },
  "options": [ {"id":0,"label":"Pass (do nothing)","cost":null,"type":"PASS"}, … ]
}
```

**Response** (`resp-<n>.json`), by `decisionType`:
- `CAST_SPELL` → `{"chosenId": <option id>}` (id `0` = pass)
- `MULLIGAN` → `{"keep": true|false}`
- `DECLARE_ATTACKERS` → `{"attackers":[{"attacker":<cardId>,"defender":<entityId>}, …]}` (`[]` = no attack)
- `DECLARE_BLOCKERS` → `{"blocks":[{"blocker":<cardId>,"attacker":<cardId>}, …]}` (`[]` = no blocks)

Malformed / unknown ids fall back to stock. Trivial windows (no castable
ability / no eligible attacker / no eligible blocker) are **not** sent — they
auto-pass to stock ("Lever 2", already implemented in the controller gates).

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

1. **No instant-speed windows for the agent.** Reactive plays (counters, tricks,
   response-blocks) are made by *stock* AI, not the agent — interaction happens,
   but at stock quality.
2. **Serialization is name-only.** State lists card *names*, not current P/T,
   counters, tapped/summoning-sick status, attached auras, or activated
   abilities. Agents are therefore blind to auras/modifications (e.g. a
   commander turned off by Kenrith's Transformation) and miss non-obvious lines
   (a creature's activated ability as a mana source — Grinning Ignus; a fetch
   gated by a spent counter — Scholar of New Horizons).
3. **Sub-choices go to stock** (copy targets, modes, targeting) — see hybrid model.
4. **Narration is unreliable.** Agents sometimes report plays that didn't happen;
   trust the board (`arena-status.py` / the request state), not the agent's prose.
5. **No state feed during the human's turn** (the dashboard reads a pending
   *opponent* request; there is none while the human acts).
6. **Latency.** Each consulted decision costs an agent resume + think (seconds to
   minutes on a large model). A per-decision poll from the orchestrator batches a
   whole turn per wake to reduce this.

## Upgrade roadmap

**Track 1 — loop tightening & action speed**
- ✅ Lever 2: trivial-subphase gate (empty windows auto-pass to stock).
- Terser brain protocol: `{chosenId}` + one-line reason (less think-time, less confabulation).
- Whole-turn drain (batch a turn per wake) + a file monitor as the cross-phase backstop.

**Track 2 — observability & correctness (highest play-quality value)**
- Richer serialization: per-card P/T, counters, tapped/sick, attached auras, and
  activated abilities with their mana output. Directly fixes the blind spots in
  limitation #2.
- Persistent `game-state.json` snapshot each decision (and during the human's
  turn) so the dashboard/observer is never blind.
- Anti-confabulation: feed the resulting state back; agents re-derive from the
  request each time.

**Track 3 — deeper capability**
- Sub-choice mailboxing (targets, modes, copy choices).
- v2 reactive windows: mailbox instant-speed priority so agents make counters/
  tricks/response-blocks at agent quality.
- Teacher→student: feed caught misplays into both the agent briefs and the
  deterministic runner.

**Track 4 — packaging & release**
- Versioned protocol spec + docs + an example brain → "bring your own agent."
- Self-contained module (seat + launcher + scripts + dashboard).
- GPL-3.0, non-commercial fan-content compliance; no card images needed for the
  mailbox path.
