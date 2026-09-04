# forge-light-llm

Four-player Commander (EDH) where the seats are piloted by LLM "brains":
Claude models making every in-game decision over a file-based mailbox, with
you optionally in seat 0 of the desktop GUI. Every decision is logged with
the board the model saw, the options it had, what it chose and why: a
growing dataset for deck analysis and for crafting deterministic game AI.
Two uses: watch four brains play any deck you hand them, or pilot your own
deck with an AI coach at your shoulder.

As of v3.4 the seats own essentially every decision: casting, targeting
(retargets and copy aiming included), triggers and their order, colour
choices, sacrifices and every cost payment, scry/surveil/library order,
mulligan bottoming, cleanup discards, optional costs, votes, pile splits. Two fail-safes back that up. On the
engine side an invalid, late or missing answer falls to Forge's stock AI for
that one decision. On the runner side a punt (timeout, wedged session,
unparseable reply) answers a fixed per-type safe default: pass, no attackers,
no blocks, keep the hand, decline pay-or-else, the first legal id for a
mandatory pick and none for an optional one, yes to a CONFIRM only when the
effect is the seat's own and free, and for CHOOSE_NUMBER the maximum on an X
cost and the minimum otherwise. A punt never spends new mana
and never acts for another player, but it is not stock play: a punted lethal
block is "no blocks". The table is in `forge-arena/runner/seatd/seat-brief.md`
and pinned by a test; `PATCH-NOTES.md` lists every surface.

**Download:** [forge-light-llm-latest.tar.gz](https://pub-6a4e610a9fd04c94b51eb95344c3013f.r2.dev/forge-light-llm-latest.tar.gz)
(always the current release; v3.4, 2026-09-04, ~113 MB). Each release also
keeps its dated object, this one
[forge-light-llm-20260904b.tar.gz](https://pub-6a4e610a9fd04c94b51eb95344c3013f.r2.dev/forge-light-llm-20260904b.tar.gz);
`PATCH-NOTES.md` inside says which version you have. Unpack anywhere:
`tar xzf forge-light-llm-latest.tar.gz`.

Built on [Forge](https://github.com/Card-Forge/forge) (GPL-3.0); the engine
ships prebuilt, see `LICENSE`. Non-commercial fan project. Magic: The
Gathering is © Wizards of the Coast.

## Requirements

- macOS or Linux (POSIX shell; developed on macOS)
- **JDK 17+** on PATH, or `JAVA_HOME` set
- **Python 3.9+**, stdlib only, no pip installs
- **Claude Code CLI** (`claude`), logged in. Brains run on your Claude
  subscription, not the API. *Optional:* without it every brain call fails
  and each seat plays its safe default; the game still plays, just not
  LLM-driven.
- Network only to ingest a **new** deck (Scryfall, Commander Spellbook) or
  generate a primer. The ten bundled decks play offline.

No install step: unpack and run.

**Where you unpack it matters a little.** Every brain call runs `claude` from
the package root (the directory holding `forge-arena/`) with
`--setting-sources ""`, so none of your settings, hooks
or plugins load into a game. The CLI still auto-discovers `CLAUDE.md` files in
the directories *above* the install and adds them to the model's context.
Install outside such a tree, or accept that text as extra context; the brains
have no tools, so they cannot act on it.

## Quick start

From the package root:

```sh
forge-arena/scripts/arena-play.sh --all-ai                          # four brains, spectator GUI
forge-arena/scripts/arena-play.sh --human selvala-heart-of-the-wilds.dck   # you at seat 0 (+ AI Advisor)
tail -f forge-arena/runner/logs/game.jsonl                          # every decision, live
forge-arena/scripts/arena-stop.sh                                   # stop now, archive, clear
```

Defaults: `--model opus --effort medium`, 90 s decision timeout. Knobs:
`--model haiku|sonnet|opus|fable`, `--effort low|medium|high|xhigh|max`,
`--timeout N` (use 300 at xhigh/max or seats punt past the deadline). Any
seat can be re-dialed mid-game from [the AI panel](#the-ai-panel).

**The table tears itself down when the match is over.** Once the engine
reports game over, or you close the game window, the launcher lingers
`--linger N` seconds (default 120 in human games so you can read the final
board, 60 all-AI) and runs the same stop as `arena-stop.sh`: kill, rate,
archive, clear. `--no-autostop` leaves the table up; a hand stop always wins.

**Bring your own deck**: one command turns any Commander list into a fully
briefed pilot, see [Ingesting a new deck](#ingesting-a-new-deck).

## The table

Default roster, seats 0–3: Urza, Giada, Purphoros, Selvala. In `--human`
mode you take seat 0 with any ingested deck (pass its `.dck` name; Selvala
when you pass none) and seats 1–3 get the first three roster decks that are
not yours. The launcher, the runners and the Advisor apply that one rule.

Any deck can sit at any seat. `ARENA_SEAT_DECKS` takes four slugs in seat
order and repoints the engine and the brains together; preflight checks the
new lineup:

```sh
ARENA_SEAT_DECKS="swords-plunder purphoros-god-of-the-forge giada-font-of-hope urza-lord-high-artificer" \
  forge-arena/scripts/arena-play.sh --all-ai
```

Ten decks ship in `forge-light-llm/forge-arena/decks/`.

## Ingesting a new deck

```sh
python3 forge-arena/scripts/arena-add-deck.py path/to/my-deck.dck
```

Six visible steps, no API keys: parse the `.dck`; resolve oracle text
(Scryfall); fetch the deck's real combos (Commander Spellbook); lint every
card against Forge's database (warns on cards the engine may not fully
script, `--strict` refuses them); probe the list through Forge's real deck
loader, which catches format and double-faced-name defects before a launch
and rewrites the registered `.dck` with Forge's own card names; write the
strategy primer. The pilot ends up knowing *your* deck's game plan, loops and
tutor targets, not an archetype read. Outputs:

```
forge-light-llm/forge-arena/decks/<slug>.dck                        playable registration
forge-light-llm/forge-arena/decks/<slug>/dossier/deck-cards.json    full oracle text (the brain's card knowledge)
forge-light-llm/forge-arena/decks/<slug>/dossier/combos.json        the deck's combo lines
forge-light-llm/forge-arena/decks/<slug>/dossier/manifest.json      launch manifest: .dck hash + every Scryfall→Forge name resolution
forge-light-llm/forge-arena/decks/<slug>/dossier/.cache/            API caches (local only, never packaged)
forge-light-llm/forge-arena/docs/primers/<slug>-deckcheck.md        strategy primer
```

**Primer options.** The pilot plays far better with a good one. **A**
(recommended) paste a [DeckCheck.co](https://deckcheck.co) review, or pass
`--deckcheck <url-or-id>` to pull the structured analysis (prose, bracket,
CRISPI ratings) straight from DeckCheck's public endpoint. **B** generate
locally with `claude` fable/max and live EDHREC research (a few minutes;
`--primer-timeout SECS`, default 2700; `--no-primer-rules` omits the rules
digests from that prompt, faster at some cost to loop-precision). **Skip**
and play from dossier plus combos. Re-runs are cheap: API responses are
cached; `--no-cache` forces a refetch; `--primer-out PATH` writes the primer
somewhere other than `docs/primers/<slug>-deckcheck.md`; `--manifest-only`
re-verifies an already registered `.dck` and rewrites only its manifest.
Then: `arena-play.sh --human my-deck.dck`.

## The AI Advisor (human games)

A fourth brain, loaded exactly like the opponents (your dossier, combos,
primer, both rules digests), watches your seat and teaches in the **Advisor
tab** of the lower-left dock. On by default in `--human` games;
`--no-advisor` opts out. Your deck must be ingested and `claude` logged in.

- **Advice before you act.** A humanly random one to three of your decisions
  per turn, spread across the phases and always board-aware (mulligans
  always), are mirrored to the advisor as the prompt opens; its one-to-three
  sentence read lands in the tab while you are still deciding. It speaks
  selectively rather than at every window; the end-of-turn commentary catches
  what a turn's picks skipped.
- **Colour commentary.** One line per completed turn on the table's public
  plays and what they mean for your plan.
- **It sees your choices** and teaches from the divergence, without a
  dedicated interruption.
- **Chat.** The black field at the bottom of the tab (Enter or **Chat**) sends
  one question straight to the advisor; the exchange appears in the same
  stream as `[t12 · you] …` / `[t12 · advisor] …`. One question at a time
  (the button reads *Sending…* until it is picked up), answered even while
  the advisor is paused.
- **Pause.** The tab's button pauses and resumes the coach mid-game (no
  advice, no model calls) without a teardown; the AI panel's seat-0 row shows
  `advisor paused` meanwhile. An advised game rates as `human+advisor`
  regardless of pausing.
- **Strictly read-only.** The advisor's feed has no return channel; it cannot
  act or stall the game. Advice that arrives late is skipped, never waited on.

The advisor uses the game's `--model` / `--effort` and can be re-dialed from
the AI panel's seat-0 row.

**Autopass** rides along (default `casts`): priority stops where you have
nothing castable, or only utility activations like tap abilities, pass
automatically, each
narrated in the tab as `⏭ (auto-passed — …)`. Hard guarantees: your own main
phases are never auto-passed, nor combat declare steps, nor a stop with an
opponent's spell on the stack, nor any stop while you have mana floating, nor
the turn after an equipment lands with its equip affordable. Any doubt fails
open to showing the prompt. `ARENA_AUTOPASS=strict` wakes you for every
legal action; `ARENA_AUTOPASS=off` disables it. Mono-coloured commanders also
get any-colour mana picks (Gemstone Caverns, City of Brass…) auto-answered in
the commander's colour, with one receipt in the tab; multicolour commanders
keep the dialog.

## The AI panel

The match screen's upper-left dock opens on the **AI** tab (Stack, Combat,
Log and Dependencies are one click away): the live control surface for the
brains.

- **Model and effort steppers per seat.** ◀ ▶ re-dials any seat mid-game
  (haiku → sonnet → opus → fable; low → max); applies at that seat's next
  decision. Scriptable via `runner/arena-ctl.py`.
- **Liveness dot per seat.** Green: decided within the last minute. Yellow:
  within five. Grey: offline or not started.
- **Usage per seat and for the table.** Calls, output tokens, cache-hit rate
  and the API-equivalent cost. On the subscription transport that dollar
  figure is what the game *would* have cost, not a charge.

The default layout is tuned for piloting: the three opponents share a tabbed
cell across the top, your battlefield beneath, your hand full width below.
Every window drags and re-tabs in-engine; layout persists in your Forge
preferences, not in the package.

## Local ELO ladders

Every finished game feeds three ladders: by pilot (each model, plus `human`
and `human+advisor`), by deck, and by pilot × deck. A four-player game
scores as six pairwise results by finish order (simultaneous eliminations
tie), from 1000 with K=40 for a pilot's first ten games. Teardown rates the
game and updates `forge-arena/runner/ratings.json` and
`ratings-history.jsonl`; the AI panel shows each seat's line (`ELO pilot 1042
· deck 987 · pair 1010 · n=12`). Aborted or torn-down-mid-game sessions rate
nothing, inconsistent
bookkeeping is skipped loudly, and games degraded by transport failure (a
wedged session, punt pile-ups) are **voided**: recorded with the reason, but
the ladders never move on a contaminated result (`ARENA_RATE_VOIDED=1`
overrides). Ratings are per-installation state: package rebuilds preserve
them and they never ship in the tarball.

## What each brain receives at start-up

Each seat's runner opens one `claude` session per game and sends these files
verbatim, in this order, all bundled:

1. `forge-light-llm/forge-arena/runner/seatd/seat-brief.md`: the standing seat brief
   (accuracy and fairness rules, answer format, mana discipline, combo duty).
2. `forge-light-llm/forge-arena/docs/research/mtg-rules-summary.md`: the comprehensive-rules
   digest (turn structure, priority, the stack, combat, keywords, Commander).
3. `forge-light-llm/forge-arena/docs/research/mtg-rules-digest-conversion.md`: loops and
   shortcuts (CR 732), mana pools, X spells, win/loss state-based actions.
4. A seat-identity line: which seat, which deck.
5. `…/decks/<slug>/dossier/deck-cards.json`, the full oracle text, never
   summarized, under `DECK DOSSIER`.
6. `…/decks/<slug>/dossier/combos.json`, the real Commander Spellbook combos
   (pieces, prerequisites, steps, result), under `DECK COMBOS`.
7. `…/docs/primers/<slug>-deckcheck.md` under `STRATEGY PRIMER`.
8. *"Reply exactly: READY"*.

The session runs with tools disabled and model/effort pinned, and persists
for the whole game, so the rules-plus-dossier context is paid once and
prompt-cached thereafter. `run_table.sh --preflight` verifies items 1–3 and
5–7 for every AI seat before a game starts.

## Logs and data out

Everything lands in `forge-light-llm/forge-arena/runner/logs/`:

| File | Contents |
|---|---|
| `game.jsonl` | **The dataset.** One JSON object per decision, all seats, one plain append-only file for the whole session (every game since the last stop); the `tail -f` target |
| `game-<gameId>.jsonl` | The same records, one file per game (each record carries its `gameId`); the ratings sweep reads these |
| `seat-N.log` / `seat-N.jsonl` | Seat N's decision stream, readable and structured (`deviation` and `turn_intent` fields per record), with `DEVIATION` lines whenever the plan met reality ("wanted X — blocked by Y"); `grep DEVIATION` is the fastest play-quality review |
| `seat-N.usage.json` | Rolling token and cost snapshot |
| `advisor-0.log` / `advisor-0.jsonl` | The Advisor tab's stream and its structured twin: advice, commentary, autopass notes, your Chat exchanges, and your actual choices paired to their decision seq |
| `gui.out`, `run_table.out`, `ratings.out`, `advisor_runner.out`, `autostop.out` | Engine, runners, ratings sweep, advisor supervisor, auto-teardown watcher |
| `transport-events.jsonl` | Punt and wedge events; the ratings sweep voids games contaminated inside their window |
| `elo/seat-N.json` | Per-seat rating digest the AI panel reads |
| `control/seat-N.json`, `control/advisor.json`, `control/ask/` | The GUI↔runner control plane: seat re-dials, the Advisor pause state, Chat questions (one file each, deleted on pickup); cleared at teardown |
| `archive/<timestamp>-stop/` | Every finished game's full log set, moved here at stop |

Nothing is clobbered. Stop moves the session's whole log set into a
timestamped archive folder and prints `N decisions across M game(s)
(archived)`; during a session `game.jsonl` is only appended to. The
`runner/logs/` tree is self-contained, so `tar czf my-arena-logs.tgz
forge-arena/runner/logs/` captures everything if you want to share games.

A decision in `seat-N.log`:

```
18:49:19 [seat 0] seq=2 CAST_SPELL turn=1 MAIN1 -> {"chosenId": 5} [model 9.06s]  # T1 Forest; green source needed for Sanctum Weaver next turn, Tomb saved for artifacts.
```

The same kind of record in `game.jsonl` (truncated; `board` carries the
public state the model saw):

```json
{"ts": 1786503529.888, "seat": 2, "deck": "giada-font-of-hope", "turn": 25,
 "phase": "COMBAT_DECLARE_BLOCKERS", "type": "REACT", "seq": 168,
 "source": "memo", "model": "opus", "effort": "low",
 "answer": {"chosenId": 0}, "why": "identical window already passed this turn",
 "board": {...}}
```

The engine also keeps `forge-light-llm/forge-arena/mailbox/observer-state.json`, a
ground-truth snapshot (turn, phase, per-seat life, hand, library and board,
`gameOver` and the winner) refreshed as the game runs; `arena-status.py`
pretty-prints it with the pending decisions.

## Scripts

| Script | What it does |
|---|---|
| `scripts/arena-play.sh` | One-shot launch: preflight → teardown → brains → Advisor (human) → GUI → auto-teardown watcher. `--all-ai` or `--human [deck.dck]`; `--no-advisor` (`--advisor` accepted, no-op); `--linger N`, `--no-autostop` |
| `scripts/arena-stop.sh` | Stop now: kill GUI and runners by PID file, rate the game, archive the session's logs, clear the mailbox |
| `scripts/arena-autostop.sh` | The watcher `arena-play.sh` starts: waits for the engine's `gameOver` or the window to close, lingers, runs `arena-stop.sh` |
| `scripts/arena-add-deck.py` | Bare `.dck` → playable seat (dossier, combos, lint, load probe, primer) |
| `scripts/arena-status.py` | Ground-truth table snapshot: pending decision, every seat's life and board |
| `scripts/arena-digest.py` | One compact line per game turn, immediate lines for punts and eliminations; follows the log for ambient monitoring |
| `scripts/arena-cardwatch.py` | Live card-count check per seat against the deck's 100 |
| `scripts/run-pilot-match.sh`, `scripts/run-gui.sh` | The underlying GUI launcher, and plain Forge without seats |
| `runner/run_table.sh` | Starts the per-seat brain daemons; `--preflight` verifies every seat's files |
| `runner/arena-ctl.py` | Set any seat's model or effort mid-game |
| `runner/status.py`, `runner/usage_report.py` | Seat health dashboard; per-seat token-burn report, works mid-game |
| `runner/run_advisor.sh`, `runner/advisor_runner.py` | The Advisor's supervisor and the Advisor brain |

Seat portraits are built-in Forge avatars matched to each deck's mana-pip
mix (mono-red gets a red head, a three-colour deck its heaviest colour),
varied per launch so the four seats differ. Cosmetic only: any hiccup falls
back to Forge's default avatar and never affects the game.

## Other models on the backend (optional, API-billed)

By default every AI seat runs Claude through your `claude` login: no key, no
bill. Any seat can instead run an **OpenRouter** model or an
**OpenAI-compatible** endpoint (Ollama, LM Studio, vLLM). Opt-in per seat;
nothing changes when unused:

```sh
export OPENROUTER_API_KEY=sk-or-...                    # or/ seats bill THIS key
export ARENA_OAI_BASE_URL=http://localhost:11434/v1    # for oai/ seats
ARENA_SEAT_MODELS=",or/google/gemini-2.5-pro,,oai/llama3.1" \
  forge-arena/scripts/arena-play.sh --human my-deck.dck   # seats 0-3; empty = Claude
```

Model strings: bare `haiku|sonnet|opus|fable` = Claude CLI;
`or/<vendor>/<model>` = OpenRouter (needs `OPENROUTER_API_KEY`; **real API
billing**); `oai/<model>` = your `ARENA_OAI_BASE_URL` endpoint
(`ARENA_OAI_API_KEY` optional; keyless local endpoints work). Seat 0 takes a backend model
only in `--all-ai` games; the Advisor is Claude-only. Backend seats join the
AI panel's stepper (shown as `or:gemini-2.5-pro`, full name in the tooltip)
and their usage lines say **API-BILLED**, never "subscription-covered".

**Cost rails and their limits.** A backend seat stops calling out and plays
safe defaults at `ARENA_MAX_SEAT_COST_USD` per game (default $5, `0` =
unlimited) and at `ARENA_MAX_SEAT_CALLS` HTTP attempts (default 250; the rail
that still works when a route reports no cost). Every call re-sends the seat's
full context (a 50–100K-token dossier plus recent history,
`ARENA_BACKEND_HISTORY` deep, default 8), so an Opus-class model at $15/M
input costs ~$2+ per decision and hits the cap within a couple of turns,
while a $1/M model plays most of a game under it. OpenRouter BYOK routes
report only OpenRouter's fee (~5% of real spend) and `oai/` endpoints report
nothing: set a hard limit on the provider key itself, because that limit, not
ours, is the real rail there. Timeouts and latches degrade a backend seat to
safe defaults exactly like a Claude timeout; the game never stalls.

## Driving it from an agent session

The scripts suit a Claude Code (or similar) agent driving the table.
`arena-digest.py` is built to be wrapped in a background monitor. Two
lifecycles: **game processes** (GUI, runners, the auto-teardown watcher) are
owned by the scripts and ended by `arena-stop.sh`, or by the watcher when the
match is over; **watchers the agent arms** (a digest monitor, `tail -F` on
the logs) are deliberately left alone by teardown, re-attach to the next
game's fresh `game.jsonl` by name, and are yours to stop. Arm them once per
session, not per game. Teardown order when you are done: `arena-stop.sh` (or
let the watcher do it), then stop your own watchers, then audit for strays
with `pgrep -fl 'GuiPilotMatch|seat_runner|run_table|arena-autostop|arena-digest'`
(empty = clean). `arena-stop.sh` prints a note whenever observers are still
running, so a driving agent sees the reminder in the teardown output.

## Lifecycle and troubleshooting

- The package stays read-only apart from `decks/`, `docs/primers/`,
  `runner/logs/` and `mailbox/`. First GUI launch creates Forge's standard
  preference directories outside it. To remove: delete this directory;
  nothing else is installed.
- Nothing is deleted at stop; the accumulating dataset is
  `runner/logs/archive/*/game*.jsonl` plus the live files.
- **"PREFLIGHT FAILED — required files missing"**: a seat's deck lacks its
  dossier or primer; the
  message names each gap, the fix is `arena-add-deck.py <deck.dck>`.
- **Seats keep punting or falling to stock**: `claude` not logged in, or the
  effort too high for the timeout (use `--timeout 300` at xhigh/max). If every
  seat starts punting within two seconds at once, your Claude subscription
  has hit its session limit; stop the table and wait for the reset.
- **The table vanished after the game**: that is the auto-teardown; the logs
  are in `archive/`. Use `--linger N` or `--no-autostop` to change it.
- **`java` errors at launch**: JDK 17+ is required; set `JAVA_HOME` if the
  PATH java is older.
- **Start the GUI through the scripts**: the engine resolves `res/` (card
  database, skins) relative to its working directory and the launchers handle
  that.
