# Forge EDH Arena — canonical project brief

## The goal, in one sentence
Drop in ANY Commander deck, have prep detect its combos, have an AI pilot
assemble them, fire them, and convert those fires into wins — with no
deck-specific logic anywhere in main code.

## What "done" looks like
- A new deck (Moxfield URL) is ingested, prepped, and played competently
  with zero code changes.
- Combos that exist in the deck actually fire in real games.
- A fired combo becomes a WIN, same turn, most of the time.
- Between combos the pilot plays credible Magic rather than idling.
- Swapping decks never breaks the engine; upstream Forge updates merge
  without clobbering our fork.

## Hard constraints (non-negotiable)
1. NO deck-specific logic in main code. Card names live in per-deck
   artifacts produced by prep, never in Java. This has caused two
   recommendations to be refused already.
2. 4-player free-for-all Commander. Not 1v1. Winning requires THREE
   eliminations.
3. Built on a Card-Forge fork. Upstream must remain mergeable; exactly one
   upstream patch exists so far, logged in UPSTREAM-PATCHES.md.
4. Everything is measured. Claims are backed by seed-paired batches, not
   argument. Metric of record: SAME-TURN conversion (win turn <= fire turn
   + 1), never "eventual win".

## Where we are (measured, 30-game seed-paired batches, turn cap 35)
| deck | steps from combo firing to opponents dead | wins/30 |
|---|---|---|
| Purphoros — combo pings all opponents directly | 0 | 8, and 92% same-turn conversion |
| Giada — wipe then attack | 1 | 9 |
| Selvala — infinite mana, pump, attack | 2-3 | 3 |
| Urza — mana, draw deck, find payoff, cast, activate x3 | 4 | 0 |

Conversion collapses in proportion to the number of steps between the
engine and the kill.

## What exists
- Prep pipeline: Commander Spellbook -> detected combos, executor bindings
  (combo -> one of 8 generic archetypes), payoff classes, win routes,
  tutor priorities. Per-deck JSON artifacts.
- ComboPilot: pure decision core over a hidden-info read model (SeatView).
- 8 archetypes; 29 bindings; copy-based validation before firing.
- Engine seams into Forge's controller (priority, attackers, tutors).
- Telemetry: per-decision events, batch reducers, seed-paired A/B.
- 237 tests, ArchUnit-enforced layering.

## What we just tried and abandoned (Phase 7)
Replaced heuristic predicates with real simulation: copy the game at
declare-attackers, script an alpha strike into the copy's Combat, advance
to COMBAT_DAMAGE, read who died. ~283ms p50, gated to ~2 predictions/game.
A/B, 30 seed-paired games/arm: decision arm steered 33 attacks the
baseline declined, and won 19 vs 20. No benefit.

Causes: (a) ~24% of predictions throw in real 4-player batches vs 30/30
clean in an isolated 2-player test; (b) "predicted kill" meant "at least
one opponent died", but killing one of three leaves you tapped out and
empty-boarded against two survivors — the success criterion was itself a
proxy.

## The recurring failure mode
Every failure has been a PROXY standing in for the real question:
- "does the deck own a haste card?" for "can these creatures attack?"
- "is the library unsearched?" for "am I making progress?"
- "has the turn changed?" for "has the board changed?"
- "does anyone die?" for "do I win?"
