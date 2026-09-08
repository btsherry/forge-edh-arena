# How the arena runs — in plain words

Written 2026-09-07 for Ben, after a night of surprises. Short sentences. No
jargon without a definition. Every number here comes from the archived logs of
game 25 unless it says otherwise.

## The five pieces

**The engine.** Forge. It runs the game. It asks each player questions:
"attack with what?", "respond to this spell, or pass?".

**The mailbox.** A folder on disk, one per AI seat (`mailbox/seat-N`). The
engine writes each question as a file and waits for an answer file. That is
all the engine knows about AI.

**The runner.** A Python program, one per seat (`runner/seat_runner.py`). It
has no intelligence. It watches the mailbox. For each question it does three
things. First, it decides whether the question is worth asking at all. If
every option is useless, it answers "pass" itself, in milliseconds, for free.
Second, if the question is real, it hands it to the brain. Third, it checks the
brain's answer is legal and writes it back. Every rule named below lives here.

**The brain.** Claude, and nothing else. At the start of a game the runner
opens one chat with Claude, using the same program you use to talk to Claude
Code, running with no screen. It pastes in the seat's dossier: deck list,
combos, primer, rules notes. Claude says READY. From then on each real question
is one more message in that same chat. So "agent", "session", "brain" and
"Claude call" all mean one thing here: one long chat per seat per game.

**The advisor.** A fourth chat of the same kind, with all four dossiers pasted
in. It reads your seat's questions and comments instead of answering them. With
the Executive button it answers them.

There is no other model use. Voice is text-to-speech. Autopass, fastpaths and
the mailbox never touch a model.

## Why one question can cost a million tokens

A chat has no memory of its own. Every message you send carries the whole
conversation so far. Claude reads all of it, then answers. This is true of
every chat with every model, including Claude Code.

The dossier is about 50,000 tokens. Each question adds about 4,700 more: the
board going in, the reasoning coming back. Giada answered 210 questions in game
25. By the end each new question meant re-reading close to a million tokens.

Caching makes the re-read fast. That is why answers still took 4 seconds late
in the game. But the read still counts against your plan. Over game 25 Giada's
seat alone read 95 million tokens. That is what ran the plan out twice.

The letter itself is small: about 4,000 tokens in, about 30 back. The
re-reading is the part that was invisible.

## What the runner does before it asks (layer one)

Rules, in the order they are tried. The first offer of any new shape always
goes to the brain. Only repeats and dead choices are cut.

- **No-op allowlist.** Every option is a known do-nothing. Pass.
- **Affordability.** Every option costs more mana than the seat has right now.
  Pass. Free, X, Phyrexian and unknown costs go to the brain.
- **Dead reactors.** Only counterspells or spell-copiers are offered and there
  is no spell on the stack, only abilities. Pass.
- **Memo.** The same window this turn, same stack, same options, same own
  life, opponents' life in the same 5-point band. Pass.
- **Repeat.** No mana, only tap-only utilities offered, the brain already
  passed the same offer this turn, own life has not dropped. Pass.
- **Auto-yield.** The brain already passed with this ability on top of an
  all-abilities stack this turn; same options, life not down, no new mana, no
  item aimed at the seat. Pass. Any spell on the stack turns this off.

Example, game 25, turn 23. You activate Staff of Domination. Giada's only
option is to tap The One Ring, and she has no mana. The first time, the brain
is asked and passes. Every later Staff activation that turn is passed by the
runner, unless her life drops or something targets her. Before tonight that
was 58 brain calls in one turn. Now it is one.

## Keeping the chat thin (layer two)

Every answer envelope reports how much the model just read. When that passes
`ARENA_ROTATE_TOKENS` (default 250,000), the runner waits for the next turn
boundary and starts a fresh chat. It pastes in three things:

1. The same dossier, word for word, from disk.
2. A game record the runner renders from its own log files
   (`runner/seatd/record.py`): life totals each turn, what was seen on the
   stack, what this seat did and the reason it gave at the time, quoted. No
   model writes it. Other seats' reasons never appear.
3. Then READY, and the next question with the full board as always.

Game 25's record for any seat is about 2,500 tokens. A fresh chat reads about
60,000 tokens per question instead of 900,000. The advisor rotates the same
way at `ARENA_ADVISOR_ROTATE_TOKENS` (default 400,000) with the public record.

## Keeping the chat warm (layer three) — what the data said

The plan was a keep-alive for idle stretches. The logs disagreed. Game 25 had
13 full cache re-writes across three seats. Eleven happened within twelve
seconds of the previous call; only two followed an idle gap over five minutes,
and one of those was a deliberate restart. Idle time is not the cause. The
re-writes look like ordinary best-effort cache eviction, about 2 percent of
calls. A keep-alive would spend tokens and fix nothing. What does help is layer
two: a re-write at 250,000 tokens costs a quarter of one at 900,000. So no
keep-alive was built, on purpose.

## The Executive button

Second button in the Advisor panel: "Advisor Executive: OFF — click to
toggle". It writes `logs/control/executive.json`.

- At your next priority, your controller sees the file and installs a mailbox
  controller over your seat, using Forge's own override (the Mindslaver path).
  From that decision on, the engine asks the seat-0 mailbox instead of you.
- The advisor process sees the same file. It starts a seat-0 runner **on its
  own brain**, the chat that already holds all four dossiers, sends that chat
  one hand-off message, and answers the seat-0 mailbox. No second agent.
- Click again. At the next priority the override removes itself and hands
  that decision back to you. The advisor's chat gets one "you are advising
  again" message.

Not yet seen live: how the match screen looks while you are overridden. Forge
shows a Mindslavered player as controlled. The first human game on the branch
answers that.

## What a game costs, before and after (estimate)

One seat, a game like 25. "After" is an estimate from replaying the logs, not
a measurement.

| | Today | After layers one and two |
|---|---|---|
| Model questions | 210 | about 130 |
| Tokens re-read per question, late game | 900k | under 250k |
| Total tokens read, whole game | 95M | roughly 20M |

## Three more low-risk steps (built 2026-09-07 late; validated in games 26–27; the persistent process is the default since 2026-09-08)

1. **One persistent process per seat.** Today each question spawns a new
   `claude -p` process that resumes the chat. A long-lived process with the
   same chat saves the spawn, well under a second per question, and lets the
   runner stream the answer as it arrives. Same chat, same memory, no change to
   what the model reads. Worth about 400 seconds of wall clock over a game.
2. **Lower effort for unthreatened reactions.** A reaction window where the
   stack holds only other players' abilities and nothing aims at the seat is a
   short question. Answering it at low effort saves one to two seconds each,
   on the most common window shape, without touching first offers or threats.
3. **The engine mirrors auto-yield.** The runner's yield rule saves the model
   call but still pays a mailbox round trip, about a third of a second. If the
   engine skipped opening a window the runner would yield anyway, that trip
   disappears too. Same rule, one layer lower, with the same guards.

## When a runner dies (added 2026-09-08)

Each seat's runner sits in a restart loop. If it crashes or is killed, a new
one starts two seconds later. Before today the new one had a fresh chat and
no memory of the game. Now it reads its own decisions so far from the game
log, renders the same record a rotation uses, and pastes dossier + record +
READY into its first message. The seat log says `RESTART mid-game detected`.
Whatever the engine asked during the two-second gap was answered by stock.

## What you see at launch and at stop (added 2026-09-08)

At launch, one banner: every setting in effect, with `[default]` or
`[SET — default …]` after each. It is saved as `runner/logs/launch-config.txt`
and copied to the top of `run_table.out` and `gui.out`, so each log explains
its own run. Keys are shown as set or unset, never printed.

At stop, one hygiene block: decisions and who answered them, model share and
latency, each seat's context size, rotations and persistent-process
fallbacks, punts, refusals, deviations, timeouts, restarts, wedges, the
engine's mirrored yields, voice and advisor counts. The last line is `OK` or
`!! HYGIENE: …` naming what was not zero. It is saved as `hygiene.txt` in the
archive folder beside the logs.
