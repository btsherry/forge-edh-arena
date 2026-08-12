# forge-light-llm

Four-player Commander (EDH) games where the seats are piloted by LLM
"brains" — Claude models making every decision over a file-based mailbox
protocol — with a human optionally taking seat 0 in the desktop GUI. Every
decision is logged with the board state the model saw, the options it was
given, what it chose, and why: a growing dataset for deck analysis and for
crafting deterministic game AI.

Built on [Forge](https://github.com/Card-Forge/forge) (GPL-3.0); the engine
ships prebuilt — see `LICENSE`. Non-commercial fan project. Magic: The
Gathering is © Wizards of the Coast.

## Requirements

- macOS or Linux (POSIX shell; developed on macOS)
- **JDK 17+** — `java` on PATH, or set `JAVA_HOME`
- **Python 3.9+** — stdlib only, no pip installs
- **Claude Code CLI** (`claude`), logged in — brains run on your Claude
  subscription. *Optional:* without it every seat times out per decision and
  falls back to Forge's built-in AI; the game still plays, just not LLM-driven.
- Network: only for ingesting **new** decks (Scryfall + Commander Spellbook)
  and primer generation. The six bundled decks play offline.

No install or setup step: unpack, run.

## Quick start

From the package root:

```sh
# all-AI: four brains play, the GUI opens as a spectator view
forge-arena/scripts/arena-play.sh --all-ai

# you + three brains: you are seat 0 in the GUI
forge-arena/scripts/arena-play.sh --human selvala-heart-of-the-wilds.dck   # or {your-deck-name.dck}

# watch decisions land, live (the central all-seats log)
tail -f forge-arena/runner/logs/game.jsonl

# stop everything, archive this game's logs, clear the mailbox
forge-arena/scripts/arena-stop.sh
```

Defaults: `--model opus --effort medium`, 90 s decision timeout. Knobs:
`--model haiku|sonnet|opus|fable`, `--effort low|medium|high|xhigh|max`,
`--timeout N` (use `--timeout 300` at xhigh/max effort or seats will punt
past the deadline). Mid-game you can re-dial any seat from the GUI's **AI
dock tab** (per-seat model/effort steppers, token/cost telemetry) or with
`runner/arena-ctl.py` — changes apply at the seat's next decision.

## The table

Default roster, seats 0–3: Selvala, Purphoros, Giada, Urza. In `--human`
mode you take seat 0 with **any** ingested deck (pass its `.dck` name); in
`--all-ai` mode all four seats are brains.

**Agents can pilot any deck.** Set `ARENA_SEAT_DECKS` to four deck slugs in
seat order before launching — it repoints the engine's seats and the brains
together, and preflight checks the new lineup automatically:

```sh
ARENA_SEAT_DECKS="swords-plunder purphoros-god-of-the-forge giada-font-of-hope urza-lord-high-artificer" \
  forge-arena/scripts/arena-play.sh --all-ai
```

Six decks ship in `forge-light-llm/forge-arena/decks/`; every deck there —
bundled or ingested — can sit at any seat.

## Ingesting a new deck

```sh
python3 forge-arena/scripts/arena-add-deck.py path/to/my-deck.dck
```

Six steps, all visible: parse the `.dck` → resolve oracle text (Scryfall) →
fetch real combos (Commander Spellbook) → implementability lint against
Forge's card database (warns on cards the engine may not fully script;
`--strict` refuses them) → strategy primer → write. Outputs, per deck:

```
forge-light-llm/forge-arena/decks/<slug>.dck                       playable deck registration
forge-light-llm/forge-arena/decks/<slug>/dossier/deck-cards.json   full oracle text (the brain's card knowledge)
forge-light-llm/forge-arena/decks/<slug>/dossier/combos.json       the deck's real combo lines
forge-light-llm/forge-arena/decks/<slug>/dossier/.cache/           content-addressed API caches
forge-light-llm/forge-arena/docs/primers/<slug>-deckcheck.md       strategy primer (see below)
```

Primer options — the pilot plays far better with a good one:
**A** paste a [DeckCheck.co](https://deckcheck.co) review (recommended),
**B** generate locally (`claude` fable/max with live EDHREC research — takes
a few minutes), **skip** play from dossier + combos only. Re-runs are cheap:
API responses are cached; `--no-cache` forces a refetch, `--verify` checks an
existing deck. Then play it: `arena-play.sh --human my-deck.dck`.

## Scripts

| Script | What it does |
|---|---|
| `scripts/arena-play.sh` | One-shot launch: teardown → preflight → seat brains → GUI; `--all-ai` or `--human [deck.dck]` |
| `scripts/arena-stop.sh` | Full teardown: kill GUI + runners, archive seat logs, clear mailbox |
| `scripts/arena-add-deck.py` | Bare `.dck` → playable seat (dossier + combos + lint + primer) |
| `scripts/arena-status.py` | Ground-truth table snapshot from the engine: pending decision, all seats' life + board |
| `scripts/arena-digest.py` | One compact line per game turn — an ambient "how's it going" feed |
| `scripts/run-pilot-match.sh` | The underlying GUI launcher (arena-play calls it); direct use for custom setups |
| `scripts/run-gui.sh` | Plain Forge desktop GUI, no mailbox seats — sanity checks |
| `runner/run_table.sh` | Starts the per-seat brain daemons (arena-play calls it); `--preflight` verifies every seat's files |
| `runner/arena-ctl.py` | Set any seat's model/effort mid-game |
| `runner/status.py` | seatd health + narrative dashboard ("numbers over vibes") |
| `runner/usage_report.py` | Per-seat token-burn report, works mid-game |
| `runner/replay.py` | Offline brain replay against recorded fixtures — no engine, real model calls |

## Logs & data out

Everything lands in `forge-light-llm/forge-arena/runner/logs/`:

| File | Contents |
|---|---|
| `seat-N.log` | Human-readable decision stream for seat N |
| `seat-N.jsonl` | The same, structured |
| `seat-N.usage.json` | Rolling token/cost snapshot for the seat |
| `game.jsonl` | **The dataset.** One JSON object per decision, all seats, accumulating across games |
| `gui.out`, `run_table.out` | Engine and runner supervision output |
| `archive/<timestamp>-stop/` | Every finished game's full log set, moved here by `arena-stop.sh` |

Nothing is clobbered: `arena-stop.sh` rolls each game's logs (seat logs +
engine/runner output) into a timestamped `archive/` folder, and `game.jsonl`
is append-only. That makes game histories easy to share — the whole
`runner/logs/` tree is self-contained, so
`tar czf my-arena-logs.tgz forge-arena/runner/logs/` captures everything if
you're willing to contribute games.

`seat-N.log` — what a decision looks like:

```
18:48:28 [seat 0] seq=1 MULLIGAN turn=0  -> {"keep": true} [model 6.87s]  # Three lands incl. Ancient Tomb, Sanctum Weaver ramp, Selvala castable T3; free mull not worth losing playable hand.
18:49:19 [seat 0] seq=2 CAST_SPELL turn=1 MAIN1 -> {"chosenId": 5} [model 9.06s]  # T1 Forest; green source needed for Sanctum Weaver next turn, Tomb saved for artifacts.
```

`game.jsonl` — one decision record (truncated; `board` carries the full
public state the model saw):

```json
{"ts": 1786503529.888, "seat": 2, "deck": "giada-font-of-hope", "turn": 25,
 "phase": "COMBAT_DECLARE_BLOCKERS", "type": "REACT", "seq": 168,
 "source": "memo", "model": "opus", "effort": "low",
 "answer": {"chosenId": 0}, "why": "identical window already passed this turn",
 "board": {...}}
```

The engine also maintains
`forge-light-llm/forge-arena/mailbox/observer-state.json` — a ground-truth
snapshot (turn, phase, per-seat life/hand-size/library/board, winner when the
game ends) refreshed as the game runs; `arena-status.py` pretty-prints it
alongside pending decisions.

## Lifecycle notes

- First GUI launch creates Forge's standard user-preference directories
  outside this package (window layout, game settings) — the package itself
  stays read-only apart from `decks/`, `docs/primers/`, `runner/logs/`, and
  `mailbox/`.
- `arena-stop.sh` rolls the game's logs into `archive/` and clears the
  mailbox; `game.jsonl` is never cleared — it is the accumulating dataset.
- To fully remove: delete this directory. Nothing else is installed.

## Troubleshooting

- **"PREFLIGHT FAILED — required files missing"** — a seat's deck lacks its
  dossier or primer; the message names each gap and the fix is
  `arena-add-deck.py <deck.dck>`.
- **Seats keep punting / falling back to stock AI** — `claude` not logged in,
  or effort too high for the timeout: raise `--timeout` (300 for xhigh/max).
- **`java` errors at launch** — need JDK 17+; set `JAVA_HOME` if your PATH
  java is older.
- **GUI must be started via the scripts** — the engine resolves `res/`
  (card database, skins) relative to its working directory; the launchers
  handle that.

## Not in this package

The headless statistics harness this project pairs with (seed-paired batch
runs, A/B deck testing, compiled combo executors) is a separate project and
none of its scripts, docs, or per-deck artifacts ship here. Also pruned from
the Forge resources: Adventure mode, music, and non-English card names.
