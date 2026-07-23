# Land Tax + Scroll Rack — engine feasibility (2026-07-23)

Ben's question: can we set up and utilize Land Tax + Scroll Rack together
well? Short answer: **yes — high value, moderate build, every needed seam
already has precedent.** This is a dig engine, and the epsilon batch named
assembly (not execution) as the frontier; this engine directly attacks it.

## How the engine works (card text, both scripts read)

Land Tax ({W} enchantment): at your upkeep, IF an opponent controls more
lands than you, you MAY fetch up to 3 basic lands to hand, then shuffle.
Scroll Rack ({2} artifact, {1}{T}): exile any number of cards from hand,
draw that many from the top, put the exiled cards back ON TOP.

The cycle: Tax floods the hand with basics → Rack swaps N dead cards for N
fresh ones → Tax's next fetch SHUFFLES the returned junk away. Net: ~3 new
cards of selection every turn, no deck-out risk, no mana beyond {1}.

**The load-bearing interaction: Rack without a shuffle is worthless** — it
puts the swapped cards back on top and hands them straight back next
activation. The program must gate Rack on "a shuffle has occurred since the
last activation" (Land Tax's fetch is the in-engine shuffle source). This is
the engine's sustain guard, and it is why the pair is compiled TOGETHER.

## Stock Forge is triple-broken here (measured, 60 games)

1. **Land Tax cast at turns 15, 15, 30** across its three appearances —
   the primer says T1-3. By turn 15 the condition (opponent has more lands)
   is dead and the card is blank. Trigger clusters (≥2 Plains fetched same
   turn): 2 total across 60 games.
2. **Scroll Rack: zero casts in 60 games.** The script carries
   `AI:RemoveDeck:All` — stock AI never plays it at all.
3. Zero activations, obviously, and the exile/put-back choices have no AI.

Whatever this engine delivers is 100% pilot-delivered.

## Seams needed (all with precedent)

| Need | Seam | Precedent |
|---|---|---|
| Early cast ({W} t1-2, {2} t2-3) | program setup casts | ProgramRunner setup / preAssembly |
| Land Tax optional trigger → yes | trigger confirm/playTrigger path | orderAndPlaySimultaneousSa work (PR-beta.1) |
| Rack activation {1}{T} | AbilityResolver.resolve | every loop program |
| **Choose cards to exile** | `chooseCardsForZoneChange(dest, origin, sa, list, min, max, ...)` override, scoped to Scroll Rack + active program | chooseTargetsFor / obligation seams |
| Put-back order | irrelevant under Tax (fetch shuffles); default order accepted | — |

Exile policy (deck-agnostic): exile excess basics + lowest-weight cards by
the deck's own tutor-priorities.json weights; never exile program pieces or
payoffs (route-coverage artifacts). Reuses existing prep artifacts entirely.

## Open questions / risks

- **`AI:RemoveDeck:All` vs our cast path**: our resolveCast →
  handlePlayingSpellAbility probably bypasses the AI hint (it gates stock's
  own choices), but this needs a one-line build-time check before relying
  on it. If blocked, that is a preflight abort, loud and safe.
- **Condition maintenance**: v1 does NOT withhold land drops; with an
  EARLY cast the condition holds naturally against ramping opponents
  (Selvala/Urza). A v2 policy could deliberately hold lands (Tax feeds the
  hand 3/turn, so drops are never actually missed) — measured first.
- **Callback scoping**: chooseCardsForZoneChange serves other effects; the
  override must gate on host card + active engine program, the same
  scoping lesson as the trigger obligation seam.

## Proposed shape (not built yet)

A third program class, `arena.engine-program/1`: pieces (both cards),
setup (early casts, frequency once), per_turn cycle (confirm Tax → activate
Rack, gated on shuffle-since-last), exile policy by artifact weights,
measured verify (net new cards seen per cycle ≥ swap count; combo-piece
acquisition events), self_consumption none (Tax is optional and net
hand-positive; Rack swaps 1:1). Success metric: program/pairing ENTRY RATE
across a batch — the epsilon frontier number — plus pieces-found-per-game.
