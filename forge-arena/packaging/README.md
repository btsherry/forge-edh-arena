# forge-light-llm

Four-player Commander (EDH) games where the seats are piloted by LLM
"brains" — Claude models making every decision over a file-based mailbox
protocol — with a human optionally taking seat 0 in the desktop GUI. Every
decision is logged with the board state the model saw, the options it was
given, what it chose, and why: a growing dataset for deck analysis and for
crafting deterministic game AI.

As of v3.3 the seats own essentially every in-game decision — casting,
targeting (including retargets and copy aiming), triggers, sacrifices and
all cost payments, scry/surveil/library order, mulligan bottoming, cleanup
discards, optional costs, votes and pile splits — each with a fail-safe
that has two halves. On the ENGINE side, an answer that is invalid, late,
or missing falls to the stock game AI for that one decision. On the RUNNER
side, a punt (the model timed out, its session wedged, or its reply was
unparseable) is answered with a fixed per-type safe default: no blocks, no
attackers, keep the hand, pass priority, decline pay-or-else, the first
legal id for a mandatory pick and none for an optional one, yes to a
CONFIRM only when the effect is the seat's own and free, and for
CHOOSE_NUMBER the maximum on an X cost and the minimum otherwise. A punt
never spends new mana and never acts for another player, but it is not
stock play: a punted lethal DECLARE_BLOCKERS is "no blocks", where stock
would have chosen blocks. The table is in
`forge-arena/runner/seatd/seat-brief.md` and pinned to the code by a test.
See `PATCH-NOTES.md` for the full list of surfaces.

Built on [Forge](https://github.com/Card-Forge/forge) (GPL-3.0); the engine
ships prebuilt — see `LICENSE`. Non-commercial fan project. Magic: The
Gathering is © Wizards of the Coast.

## Requirements

- macOS or Linux (POSIX shell; developed on macOS)
- **JDK 17+** — `java` on PATH, or set `JAVA_HOME`
- **Python 3.9+** — stdlib only, no pip installs
- **Claude Code CLI** (`claude`), logged in — brains run on your Claude
  subscription. *Optional:* without it every brain call fails and each seat's
  runner answers its safe default (see above); the game still plays, just not
  LLM-driven.
- Network: only for ingesting **new** decks (Scryfall + Commander Spellbook)
  and primer generation. The ten bundled decks play offline.

No install or setup step: unpack, run.

Footnote on where you unpack it: every brain call runs the `claude` CLI from
the package root (the directory holding `forge-arena/`) with
`--setting-sources ""`, so none of
your user or project settings, hooks or plugins load into a game. The CLI
still auto-discovers `CLAUDE.md` files in the directories ABOVE the install
directory and adds them to the model's context. Install outside such a tree,
or accept that text as extra context: tools are disabled for the brains, so
they cannot act on it.

## Quick start

From the package root:

```sh
# all-AI: four brains play, the GUI opens as a spectator view
forge-arena/scripts/arena-play.sh --all-ai

# you + three brains: you are seat 0 in the GUI
forge-arena/scripts/arena-play.sh --human selvala-heart-of-the-wilds.dck   # or {your-deck-name.dck}

# watch decisions land, live (the central all-seats log)
tail -f forge-arena/runner/logs/game.jsonl

# stop everything, archive the session's logs, clear the mailbox
forge-arena/scripts/arena-stop.sh
```

**Bring your own deck:** one command turns any Commander list into a
fully-briefed AI pilot — see [Ingesting a new deck](#ingesting-a-new-deck).
Pilot it yourself with an AI table, or hand it to a brain and watch it play
its own game plan.

Defaults: `--model opus --effort medium`, 90 s decision timeout. Knobs:
`--model haiku|sonnet|opus|fable`, `--effort low|medium|high|xhigh|max`,
`--timeout N` (use `--timeout 300` at xhigh/max effort or seats will punt
past the deadline). Any seat can be re-dialed mid-game — see
[The AI panel](#the-ai-panel).

## The table

Default roster in `--all-ai` mode, seats 0–3: Urza, Giada, Purphoros,
Selvala — all four seats are brains. In `--human` mode you take seat 0 with
**any** ingested deck (pass its `.dck` name; Selvala when you pass none) and
seats 1–3 get the first three roster decks that are not yours — Urza, Giada,
Purphoros for the default. The launcher, the seat runners and the Advisor
all apply that one rule.

**Agents can pilot any deck.** Set `ARENA_SEAT_DECKS` to four deck slugs in
seat order before launching — it repoints the engine's seats and the brains
together, and preflight checks the new lineup automatically:

```sh
ARENA_SEAT_DECKS="swords-plunder purphoros-god-of-the-forge giada-font-of-hope urza-lord-high-artificer" \
  forge-arena/scripts/arena-play.sh --all-ai
```

Ten decks ship in `forge-light-llm/forge-arena/decks/`; every deck there —
bundled or ingested — can sit at any seat.

## Ingesting a new deck

```sh
python3 forge-arena/scripts/arena-add-deck.py path/to/my-deck.dck
```

Six steps, all visible, no API keys needed: parse the `.dck` → resolve
oracle text (Scryfall) → fetch real combos (Commander Spellbook) →
implementability lint against Forge's card database (warns on cards the
engine may not fully script; `--strict` refuses them) → a load probe
through Forge's REAL deck loader (catches format and double-faced-name
defects before they can ruin a launch; the registered `.dck` is rewritten
with Forge's own card names) → strategy primer → write. The pilot ends up knowing YOUR deck's actual game plan — its real
loops, what to tutor for, how to close — not a generic archetype read.
Outputs, per deck:

```
forge-light-llm/forge-arena/decks/<slug>.dck                       playable deck registration
forge-light-llm/forge-arena/decks/<slug>/dossier/deck-cards.json   full oracle text (the brain's card knowledge)
forge-light-llm/forge-arena/decks/<slug>/dossier/combos.json       the deck's real combo lines
forge-light-llm/forge-arena/decks/<slug>/dossier/manifest.json     launch manifest: .dck hash + every Scryfall→Forge name resolution
forge-light-llm/forge-arena/decks/<slug>/dossier/.cache/           content-addressed API caches (local only; never packaged)
forge-light-llm/forge-arena/docs/primers/<slug>-deckcheck.md       strategy primer (see below)
```

Primer options — the pilot plays far better with a good one:
**A** paste a [DeckCheck.co](https://deckcheck.co) review (recommended),
**B** generate locally (`claude` fable/max with live EDHREC research — takes
a few minutes), **skip** play from dossier + combos only. Re-runs are cheap:
API responses are cached; `--no-cache` forces a refetch; `--manifest-only`
re-verifies an already-registered `.dck` against Forge and rewrites just its
launch manifest. Then play it: `arena-play.sh --human my-deck.dck`.

Option A can auto-fetch — no copy/paste. Pass your DeckCheck deck URL or id
with `--deckcheck <url-or-id>` and the tool pulls the structured analysis
(prose + bracket + CRISPI ratings) straight from DeckCheck's public endpoint
and renders it as the primer. Related flags: `--primer-out PATH` (write the
primer somewhere other than `docs/primers/<slug>-deckcheck.md`),
`--primer-timeout SECS` (default 2700 for the local fable/max run in option B),
and `--no-primer-rules` (faster option-B generation — omits the rules digests
from the fable prompt, at some cost to loop-precision). Double-faced (MDFC)
card names resolve correctly during ingest.

## The AI Advisor (human games)

```sh
forge-arena/scripts/arena-play.sh --human my-deck.dck   # Advisor is ON by default; --no-advisor to opt out
```

A fourth brain — loaded exactly like the opponents (your deck's dossier,
combos, primer, both rules digests) — watches your seat and teaches in the
**Advisor tab** (lower-left dock, beside the Prompt tab):

- **Advice before you act**: a humanly-random handful of your decisions each
  turn (roughly one to three, spread across the phases and always board-aware,
  with mulligans always covered) are mirrored to the advisor the moment the
  prompt opens; its 1–3 sentence read appears in the tab while you're still
  deciding. It speaks selectively rather than at every window — the end-of-turn
  recap (below) catches anything a given turn's picks skipped.
- **Color commentary**: one line per completed turn covering the table's
  public plays — what mattered and what it means for your plan.
- **It sees your choices** and teaches from the divergence when it matters —
  gently, and never with a dedicated interruption.
- The advisor is **strictly read-only**: it has no way to act or to stall
  the game (its feed has no return channel). Advice arriving late is
  advice skipped, never a pause.

Requirements: the deck you pilot must be ingested (`arena-add-deck.py`),
and the `claude` CLI logged in. The advisor uses the game's `--model` /
`--effort` and can be re-dialed mid-game from the AI panel's seat-0 row.

**Pause button.** Advised games get an on/off button at the bottom of the
**Advisor tab**: pause mid-game (no advice, no model calls) and resume when
you want the coach back — no teardown. The AI panel's seat-0 row shows
`advisor paused` while it's off. An advised game (the `--human` default)
rates as `human+advisor` on the ladders regardless of mid-game pausing.

**Autopass** rides along (default `casts` mode): priority stops where you
have nothing castable — or only utility activations like tap abilities —
pass automatically, each narrated in the Advisor tab as
`⏭ (auto-passed — …)`. The stakes-based guarantees, learned from live play:
your own **main phases are never auto-passed** by any layer, ever; neither
are combat declare steps, stops with an opponent's spell on the stack, any
stop while you have **mana floating** (unspent pool mana signals intent),
or the whole turn after an **equipment drops** with its equip affordable.
`ARENA_AUTOPASS=strict` wakes you for ANY legal action;
`ARENA_AUTOPASS=off` disables it. Any doubt in the scan fails open to
showing the prompt.

**Bonus quality-of-life** (mono-colored commanders): arbitrary any-color
mana picks (Gemstone Caverns, City of Brass…) auto-answer with your
commander's color — one receipt in the Advisor tab, then silence.
Multicolor commanders keep the dialog.

## The AI panel

The match screen's **upper-left dock** opens on the **AI** tab (its siblings
— Stack, Combat, Log, Dependencies — are one click away). It is the live
control surface for the brains:

- **Per-seat model/effort steppers** — click ◀ ▶ to re-dial any seat
  mid-game (haiku → sonnet → opus → fable; low → max). Changes apply at that
  seat's next decision; the same knob is scriptable via `runner/arena-ctl.py`.
- **Liveness dot per seat** — green: decided within the last minute; yellow:
  within five; gray: offline or not yet started.
- **Per-seat usage line** — calls, output tokens, cache-hit rate, and the
  API-equivalent cost of the seat so far.
- **Table total** — the same figures summed across all four seats
  (subscription transport: the dollar figure is what the game *would* have
  cost on the API, not a charge).

The default match layout is tuned for manual piloting: the three opponents
share a tabbed cell across the top, your battlefield sits beneath them, and
your hand gets a full-width window under that. Like everything in the dock,
every window can be dragged and re-tabbed in-engine; layout changes persist
in your Forge preferences, not in the package.

## Local ELO ladders

Every finished game feeds three local ratings ladders automatically — **by
pilot** (each model, plus `human` and `human+advisor` as their own pilots),
**by deck**, and **by pilot×deck pair**. A 4-player game scores as six
pairwise 1v1s by finish order (simultaneous eliminations tie), starting at
1000 with K=40 for a pilot's first ten games. Nothing to configure:

- The engine records placements at game end; teardown
  (`arena-stop.sh`) rates the game and updates
  `forge-arena/runner/ratings.json` (current ladders) and
  `ratings-history.jsonl` (per-game record, plottable).
- The AI panel shows each seat's line — `ELO pilot 1042 · deck 987 ·
  pair 1010 · n=12` — refreshed after each rated game.
- Aborted/torn-down-mid-game sessions rate nothing; a game whose seat/deck
  bookkeeping looks inconsistent is skipped loudly rather than mis-rated.
- Games degraded by transport failure (a seat's model session wedging, punt
  pile-ups) are **voided**: recorded in the history with the reason, but the
  ladders never move on a contaminated result. `ARENA_RATE_VOIDED=1` rates
  them anyway.
- Ratings are per-installation state: package rebuilds preserve them, and
  they never ship in the tarball.

## What each agent receives at start-up

At every game launch, each seat's runner opens a fresh `claude` session and
sends one initialization prompt — these files, verbatim and in this order
(all bundled in the package):

1. `forge-light-llm/forge-arena/runner/seatd/seat-brief.md` — the standing
   seat brief: accuracy and fairness rules, answer format, mana discipline,
   combo duty.
2. `forge-light-llm/forge-arena/docs/research/mtg-rules-summary.md` — the
   general comprehensive-rules digest: turn structure, priority, the stack,
   combat, keywords, Commander rules.
3. `forge-light-llm/forge-arena/docs/research/mtg-rules-digest-conversion.md`
   — the deeper digest of loops/shortcuts (CR 732), mana pools, X spells,
   and win/loss state-based actions.
4. A seat-identity line: which seat it is and which deck it pilots.
5. `…/decks/<slug>/dossier/deck-cards.json` — the deck's full oracle text,
   never summarized, under the heading `DECK DOSSIER`.
6. `…/decks/<slug>/dossier/combos.json` — the deck's real Commander
   Spellbook combos (pieces, prerequisites, steps, what they produce), under
   `DECK COMBOS`.
7. `…/docs/primers/<slug>-deckcheck.md` — the strategy primer, under
   `STRATEGY PRIMER`.
8. The closing instruction: *"Reply exactly: READY"*.

The session runs with tools disabled and the seat's model/effort pinned, and
persists for the whole game — every subsequent decision resumes it, so the
big rules-plus-dossier context is paid once and prompt-cached thereafter.
`run_table.sh --preflight` verifies items 1–3 and 5–7 exist for every AI
seat before any game starts.

## Logs & data out

Everything lands in `forge-light-llm/forge-arena/runner/logs/`:

| File | Contents |
|---|---|
| `seat-N.log` | Human-readable decision stream for seat N — including `DEVIATION` lines whenever the brain's plan met reality ("wanted X — blocked by Y"); `grep DEVIATION` is the fastest play-quality review |
| `seat-N.jsonl` | The same, structured (`deviation` and `turn_intent` fields on each record) |
| `seat-N.usage.json` | Rolling token/cost snapshot for the seat |
| `game.jsonl` | **The dataset.** One JSON object per decision, all seats, one plain append-only file for the whole session (every game since the last `arena-stop.sh`) — the `tail -f` target |
| `game-<gameId>.jsonl` | The same records, one file per game (each record carries its `gameId`) — the per-game machine record; the ratings sweep reads every `game*.jsonl` beside it |
| `advisor-0.log` / `advisor-0.jsonl` | The Advisor tab's stream, and its structured twin — advice, color commentary, autopass notes, and your actual choices' seq pairing |
| `gui.out`, `run_table.out`, `ratings.out`, `advisor_runner.out` | Engine, runner, ratings-sweep, and advisor supervision output |
| `transport-events.jsonl` | Punt/wedge events from the seat runners — the ratings sweep voids games contaminated inside their window |
| `elo/seat-N.json` | Per-seat rating digest the AI panel reads |
| `control/seat-N.json`, `control/advisor.json` | The GUI↔runner control plane: AI-panel re-dials and the Advisor pause state (cleared at teardown) |
| `archive/<timestamp>-stop/` | Every finished game's full log set, moved here by `arena-stop.sh` |

Nothing is clobbered: `arena-stop.sh` moves the session's whole log set
(seat logs, engine/runner output, `game.jsonl` and the `game-<gameId>.jsonl`
files) into a timestamped `archive/<stamp>-stop/` folder and prints
`N decisions across M game(s) (archived)`; during a session `game.jsonl` is
only ever appended to. That makes game histories easy to share — the whole
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

## Scripts

| Script | What it does |
|---|---|
| `scripts/arena-play.sh` | One-shot launch: preflight → teardown → seat brains → Advisor (human games) → GUI; `--all-ai` or `--human [deck.dck]`; the Advisor is on by default in `--human` games, `--no-advisor` opts out (`--advisor` is accepted and changes nothing) |
| `scripts/arena-stop.sh` | Full teardown: kill GUI + runners (by PID file), rate the game, archive the session's logs (seat logs, `game.jsonl`, `game-*.jsonl`, engine/runner output), clear mailbox |
| `scripts/arena-add-deck.py` | Bare `.dck` → playable seat (dossier + combos + lint + primer) |
| `scripts/arena-status.py` | Ground-truth table snapshot from the engine: pending decision, all seats' life + board |
| `scripts/arena-digest.py` | One compact line per game turn — an ambient "how's it going" feed |
| `scripts/run-pilot-match.sh` | The underlying GUI launcher (arena-play calls it); direct use for custom setups |
| `scripts/run-gui.sh` | Plain Forge desktop GUI, no mailbox seats — sanity checks |
| `runner/run_table.sh` | Starts the per-seat brain daemons (arena-play calls it); `--preflight` verifies every seat's files |
| `runner/arena-ctl.py` | Set any seat's model/effort mid-game |
| `runner/status.py` | seatd health + narrative dashboard ("numbers over vibes") |
| `runner/usage_report.py` | Per-seat token-burn report, works mid-game |
| `runner/run_advisor.sh` | The Advisor's supervisor: restart loop around `advisor_runner.py` (arena-play calls it in `--human` games) |
| `runner/advisor_runner.py` | The AI Advisor brain (launched by default in `--human` games; `--no-advisor` opts out): reads the seat-0 decision shadow feed, streams teaching + color commentary |

## Seat avatars

Each seat's portrait is a built-in Forge avatar matched to its deck's colors —
derived from the deck's mana-pip mix (mono-red → a red head, a three-color deck →
its heaviest color, and so on), with per-color variety so the four seats differ
and the picks change between launches. Purely cosmetic; falls back to Forge's
default avatar on any hiccup and never affects the game.

## Other models on the backend (optional, API-billed)

By default every AI seat runs Claude through your `claude` login — no key,
no API bill. Optionally, any seat can instead run **any OpenRouter model**
or **any OpenAI-compatible endpoint** (Ollama, LM Studio, vLLM). This is
opt-in per seat and changes nothing when unused.

```sh
# seat order 0-3; empty entries keep the default Claude model.
# seat 1 -> Gemini via OpenRouter, seat 3 -> local Ollama, rest Claude:
export OPENROUTER_API_KEY=sk-or-...       # or/ seats bill THIS key
export ARENA_OAI_BASE_URL=http://localhost:11434/v1   # for oai/ seats
ARENA_SEAT_MODELS=",or/google/gemini-2.5-pro,,oai/llama3.1" \
  forge-arena/scripts/arena-play.sh --human my-deck.dck
```

Model strings: bare names (`haiku|sonnet|opus|fable`) = Claude CLI;
`or/<vendor>/<model>` = OpenRouter (needs `OPENROUTER_API_KEY`; **real
API billing**); `oai/<model>` = your `ARENA_OAI_BASE_URL` endpoint
(`ARENA_OAI_API_KEY` optional — keyless local endpoints work). Seat 0 takes
a backend model only in `--all-ai` games; the Advisor is Claude-only.
Backend entries join the AI panel's model stepper (shown as
`or:gemini-2.5-pro`, full name in the tooltip), and their usage lines say
**API-BILLED** — never "subscription-covered".

**Cost rails, and their honest limits.** Each backend seat stops calling out
(and plays on safe defaults) at `ARENA_MAX_SEAT_COST_USD` per game (default
**$5.00**, `0` = unlimited) and at `ARENA_MAX_SEAT_CALLS` HTTP attempts
(default 250) — the call cap is the rail that still works when a route
reports no cost figures. Do the arithmetic before picking a pricey model:
every call re-sends the seat's full context (a ~50–100K-token deck dossier
plus recent history — depth tunable via `ARENA_BACKEND_HISTORY`, default 8),
so an Opus-class model at $15/M input costs **~$2+ per decision** and hits
the $5 cap within a couple of turns, while a ~$1/M model plays most of a
game under it. Two caveats: OpenRouter **BYOK** routes report only
OpenRouter's fee as cost (~5% of real spend), and `oai/` endpoints report
none — in both cases set a hard limit on the provider key itself; that
limit, not ours, is the real rail. Timeouts/latches degrade a backend seat
to safe defaults exactly like a Claude timeout — the game never stalls.

## Driving it from an agent session

The scripts are friendly to being driven by a Claude Code (or similar) agent
session — `arena-digest.py` exists precisely to be wrapped in a background
monitor (one compact line per turn, immediate lines for punts and
eliminations). Keep two lifecycles straight:

- **Game processes** (GUI, seat runners, restart loops) are fully owned by
  the scripts — `arena-stop.sh` kills and archives them.
- **Watchers the agent arms** (a digest monitor, a `tail -F` on the logs)
  are deliberately NOT touched by teardown. `arena-stop.sh` moves
  `game.jsonl` into the archive and the next game's runners create a fresh
  one; `tail -F` (follow by name) re-attaches to the new file, so one watcher
  spans every game in a session. Arm once per session, not per game.

Teardown order when you're done: `arena-stop.sh` → stop your own watchers →
audit for strays with
`pgrep -fl 'GuiPilotMatch|seat_runner|run_table|arena-digest'` (empty =
clean). `arena-stop.sh` prints a note whenever observer processes are still
watching the logs, so a driving agent sees the reminder in the teardown
output itself.

## Lifecycle notes

- First GUI launch creates Forge's standard user-preference directories
  outside this package (window layout, game settings) — the package itself
  stays read-only apart from `decks/`, `docs/primers/`, `runner/logs/`, and
  `mailbox/`.
- `arena-stop.sh` moves the session's logs, `game.jsonl` included, into
  `archive/` and clears the mailbox; nothing is deleted, so the accumulating
  dataset is `runner/logs/archive/*/game.jsonl` plus the live file.
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
