# Phase 7 — Real prediction lines

## The problem this phase exists to fix

Every conversion failure we have diagnosed in the last three rounds had the
same shape: **a hand-written predicate that approximates a question the rules
engine can answer exactly.**

| PR | The proxy we wrote | The question it stood in for |
|----|--------------------|------------------------------|
| 54 | "does the deck own a haste card?" | can these creatures attack? |
| 55 | "is the library unsearched?"       | am I making progress toward a kill? |
| 56 | "has the turn changed?"            | has the board changed? |

Each proxy was reasonable when written and wrong in play. PR-41 is the cost
in miniature: a full PR spent widening the haste search, predicted to unblock
~99 conversions, measured at 21%→19% — statistically unchanged. PR-54 then
deleted the requirement outright, because the requirement was fictional.

The decks confirm it. Conversion success is inversely proportional to how
many proxies sit between the fire and the kill:

- **Purphoros** — `DIRECT_DAMAGE_LOOP`. Outlet *is* the win. Zero proxies. **92% same-turn.**
- **Selvala** — kills only through combat: haste, sickness, declaration, blockers. Four proxies. **58 fires → 2 same-turn wins.**
- **Urza** — `DECK_ACCESS` + `INFINITE_TURNS`: neither is a win condition at all. **23 fires → 1.**

Selvala and Urza are 81 fires and 3 same-turn wins between them. That is the
entire gap, and it is concentrated exactly where the proxy count is highest.

## The principle

> Where the engine can answer a question, ask it. Do not approximate it.

Not "add a search". Not "add an evaluator". Replace *predicates that guess*
with *predictions that execute*, at a small number of decision points.

## What already exists (this is mostly a wiring job)

Forge ships a complete simulation AI at `forge-ai/src/main/java/forge/ai/simulation/`:
`GameCopier`, `GameSimulator`, `GameStateEvaluator`, `SpellAbilityPicker`.

We already use the machinery — `GameSimHandle.copyOf` wraps `GameCopier` with
our imprint/exile fidelity shim, and the **drill** proves an activation on a
copy before arming. The drill is also the part that works. That is not a
coincidence, and it is the template for this whole phase.

The critical primitive is `GameStateEvaluator.simulateUpcomingCombatThisTurn`:
copy the game, `devAdvanceToPhase(COMBAT_DAMAGE)`, inspect the result. A real
attack, resolved by the real rules engine, with real blockers.

### What we adopt, and what we explicitly reject

**Adopt the machinery**: `GameCopier`, `devAdvanceToPhase`, `resolveStack`.
Rules-correct, maintained upstream, already in our dependency graph.

**Reject the scalar evaluator.** `GameStateEvaluator.getScoreForGameStateImpl`
carries `// TODO: more than 2 players` and computes
`score -= 2 * opponentLife / (players - 1)` — it *averages* opponent life. In
a 4-player pod, killing one opponent barely moves that number. Worse:
`resolveStack(gameCopy, aiPlayer.getWeakestOpponent())` assumes a single
opponent. A heuristic board score is itself a proxy; adopting it would import
the exact class of bug we are removing, with 2-player assumptions on top.

**We do not need a score.** A combo pilot's question is boolean:
*does this line kill someone?* Read it off the simulated state — opponent life
≤ 0, or `game.isGameOver()`. No weights, no tuning, no averaging.

## Measured cost (spike, discarded after measuring)

Timed on live mid-game boards, 12 iterations after JIT warmup:

| Turn | Permanents | Bare copy | Copy + advance to COMBAT_DAMAGE | Advances OK |
|------|-----------|-----------|--------------------------------|-------------|
| 6 | 6 | 16.6 ms | **36.7 ms** | 12/12 |
| 12 | 14 | 18.8 ms | **44.3 ms** | 12/12 |

Two conclusions, both load-bearing:

1. **It works.** 24/24 advances completed without throwing. The mechanism is real.
2. **~17 ms is fixed copy overhead**, not board-size scaling. 6→14 permanents
   cost only +20%, so late-game boards degrade gracefully rather than exploding.

**Budget: ~40 ms per prediction.** This is affordable a few times per turn and
catastrophic per priority window (`ArenaLimits` allows 2000 priority passes per
turn — that would be 80 seconds of prediction per turn). **The gating discipline
is the design**, not an optimization to add later.

## MEASURED: what the copy actually simulates (PR-58 finding)

The original draft assumed "copy the game, advance to COMBAT_DAMAGE, read
who died" answers *does my attack kill?* **It does not, and this was
measured rather than argued.**

`devAdvanceToPhase` runs `onPhaseBegin` for every phase it crosses. The
declare-attackers hook is what makes a controller declare — so by the time
the copy reaches COMBAT_DAMAGE, **the copy's own AI has chosen the attack**.
The verdict describes what stock AI would have done, not what we intend to do.

Measured on live Selvala boards, own turns only:

| Turn | Creatures | Power | Life before | After passive sim |
|------|-----------|-------|-------------|-------------------|
| 7  | 2 | 2  | 40 / 40 | 40 / 40 |
| 9  | 4 | 6  | 40 / 38 | 40 / 38 |
| 11 | 6 | 9  | 40 / 32 | 40 / **26** |
| 12 | 9 | 29 | 40 / 26 | 40 / 26 |

At turn 12 the seat held **9 creatures and 29 power and the simulation
attacked for zero**. A decision built on that would have concluded "attacking
does nothing" and passed the turn — the identical failure to the proxies this
phase exists to remove, but now wearing a simulation's authority.

**Injecting our own attackers after the advance does not work either** (also
measured, also zero): once the phase has begun the declaration is resolved,
and `CombatUtil.canAttack` refuses every further attacker.

### The consequence for the design

The copy must be taken while the live game is **already at declare-attackers,
with the declaration still open**. There is exactly one place that is true:
inside our own `declareAttackers` seam. So the prediction lives there,
scripts the alpha into the copy's own `Combat`, and lets the engine resolve
blockers and damage from there.

This is a narrower primitive than the draft imagined, and a correct one.
`KillPredictor.predictAlphaStrike` documents the phase requirement as a
precondition rather than an inconvenience.

## Where predictions are allowed to run

**Gated on state, not on a counter** (Gemini review, accepted — the original
draft used a flat cap of 3/turn, which is arbitrary in exactly the wrong way:
it wastes budget on turn 2 when nothing is happening and starves the pilot on
the one turn it is trying to go off). The cheap read-model is the pre-filter,
and it is free — PR-54 already computes what we need:

- **Combat prediction runs only if** `attackReadyPower >= lowest opponent life`.
  Below that the attack cannot kill anyone and there is nothing to predict.
- **Conversion prediction runs only if** a combo has fired and the candidate
  outlet is actually reachable this window.

The intended shape is **zero predictions on most turns and many on the turn it
matters**. A wall-clock ceiling per turn (not a call count) is the backstop, so
a pathological board degrades to the read-model instead of eating the batch.

The two call sites:

1. **The combat decision** (own combat, past the power gate) — "does this attack
   kill anyone?" Replaces the `SPREAD_COMBAT` predicate stack and the PR-34
   worst-case blocker arithmetic with an actual resolved combat.
2. **Post-fire conversion** (combo fired, outlet reachable) — "does the banked
   pool plus this outlet kill anyone?" Replaces `ConversionPlanner`'s
   class-ranking guess with a resolved answer.

Everything else — assembly, tutoring, mulligan, deploy ordering — keeps using
`SeatView`. Those are cheap, frequent, and not where the failure is.

## Migration: A/B cutover, plus fidelity logging

The original draft proposed full shadow mode — run both systems, compare
verdicts, cut over later. Gemini called that procrastination dressed as rigor,
and it is half right. We already know the predicates fail; an agreement matrix
telling us so again buys nothing and doubles the compute.

But the argument only covers the headline question. The risk that actually
keeps me up is **copy infidelity** — a prediction that is confidently wrong
because `GameCopier` dropped state (it already drops imprints, host exiles and
exiledWith back-links; PR-33 shims those three, and there may be more). A
confidently wrong prediction is strictly worse than an honest proxy, and an
A/B win-rate number cannot distinguish "prediction was right" from "prediction
was wrong but the game was won anyway."

So: **A/B for the decision, prediction-vs-outcome logging for fidelity.**

**Stage 1 — feature-flagged A/B.** Predictor ON vs OFF, same seeds. Compare
same-turn conversion and wall clock. This is the go/no-go.

**Stage 2 — fidelity ledger.** Every prediction records what it predicted and
what actually happened in the real game (predicted kill → did the opponent
die?). Near-free — one event per prediction, not a parallel execution — and it
converts copy infidelity from an invisible risk into a counted number. If
predicted-kill/actual-survive is non-trivial, the copy is lying and we fix the
copy before trusting anything downstream.

**Stage 3 — delete the dead predicates.** Only after their replacement has
outperformed them on measured games. Nothing is deleted on the strength of an
argument, including this one.

## Risks, stated plainly

- **Wall clock.** Under state gating most turns predict zero times, but a
  go-off turn may predict several. Worst case if the gates leak — every turn,
  both call sites — is ~2.8 s per seat per game, ×4 seats ≈ 11 s per game. On top of current runtime, across 6
  workers, this could materially lengthen batches. Stage 1 measures it before
  we commit. *Mitigation if it bites: drop to 1 prediction/turn (combat only) —
  that alone addresses the Selvala gap.*
- **Copy fidelity.** `GameCopier` already drops imprints, host exiles, and
  exiledWith back-links; PR-33 shims those three. There may be more. A
  prediction from an unfaithful copy is a confident wrong answer — strictly
  worse than an honest proxy. Shadow mode surfaces this as divergence we can
  inspect, which is the main reason Stage 1 exists.
- **`devAdvanceToPhase` is dev tooling**, not a supported AI API. It worked
  24/24 here, but it is a thinner contract than the rest of the engine, and an
  upstream Forge update could change it. Log it in `UPSTREAM-PATCHES.md` as a
  dependency to watch even though we are not patching it.
- **Non-combat kills.** Advancing to `COMBAT_DAMAGE` predicts combat. Urza's
  Aetherflux line is not combat — it needs `simulateSpellAbility` instead.
  Call site 2 covers it, but it is a different mechanism and should not be
  assumed to come free with call site 1.
- **CONCURRENCY AND HANGS — the bet-money risk** (Gemini review, accepted).
  The spike ran 24 iterations single-threaded. Batches run 6 workers. Forge's
  engine internals are a plausible home for mutable statics and shared caches
  that behave differently under parallelism — and we have already been bitten
  by exactly this class of thing once (PR-49: infinite mutual recursion in
  `StaticAbilityTurnPhaseReversed`, which needed a ThreadLocal reentrancy
  guard). Worse and more likely: **simulating a board that contains an
  infinite combo can hang the simulation itself.** These decks exist to make
  infinite loops; `resolveStack` on such a board has no reason to terminate,
  and a 40 ms budget silently becomes forever, taking a worker with it. Every
  prediction must run under a hard wall-clock timeout that degrades to the
  read-model on expiry. This is now step 1 of the sequence, before any
  behaviour change.

## Who declares blockers in the simulation?

Gemini raised this as the plan's biggest unstated assumption, and it is a real
gap in the original draft — but the answer is better than it feared, *in our
setting specifically*.

Advancing to `COMBAT_DAMAGE` requires opponents to declare blockers, which
means their controllers make decisions inside the copy. In a batch arena the
opponents **are** Forge AI seats. So the blocker decisions in the prediction
are made by the same AI that will make them in the real game: the prediction
is not an approximation of the opponent, it *is* the opponent. That is
strictly more faithful than PR-34's worst-case blocker arithmetic, which
assumes opponents always block optimally with their top creatures.

Two caveats survive, and both are handled above:
- If a decision path ever waits on input, the worker hangs → covered by the
  mandatory timeout.
- Against a differently-behaving opponent (a human, a stronger AI) the
  prediction would degrade to an assumption. Out of scope today; worth
  recording as a boundary of the claim.

## Urza needs progress, not just terminal kills

Gemini's strongest substantive point, and the original draft was wrong here.

A boolean "did someone die in this horizon" returns **false** for every action
Urza actually needs to take: establish the loop, draw the deck, bank mana,
take extra turns. A pilot that only pulls the trigger on terminal kills never
sets up. `DECK_ACCESS` and `INFINITE_TURNS` are Urza's whole route table, and
neither is a terminal state.

But the proposed remedy — adopt a scalar board score — reintroduces exactly
what this phase exists to remove, with 2-player assumptions attached. The
answer is a third thing, and it is still a fact rather than a guess:

> **Predict the loop's PRODUCT, not the board's value.**

Simulate N iterations on the copy and read off what the engine actually
produced: mana in pool, cards drawn, turns banked, life gained. Those are
measured quantities, not weighted heuristics. "This loop nets +3 mana per
iteration and is therefore infinite" is an engine-answered fact. "This board
is worth 47 points" is a proxy.

This also matches the one part of the system that already works — the loop
executors' `SimResult.profitable(n)` validation, which is precisely a product
measurement on a copy. We are generalizing the working pattern, not importing
a new one.

## What this does NOT do

- No in-loop search, no minimax, no rollouts. One prediction, one decision.
  (The research survey's verdict was "utility arbiter + HTN, no in-loop search";
  this is narrower still, and deliberately so.)
- No utility arbiter yet. An arbiter ranks options; it is only worth building
  once the options carry real answers instead of proxy scores. It becomes the
  natural Phase 8 if Phase 7 lands.
- No deck-specific logic. Every call site reads the deck's own artifacts.

## Sequence

1. **Concurrency + hang spike.** 6 threads copying and advancing fat
   Selvala/Urza boards, including a board with a live infinite combo. Prove no
   corruption, no hang. Ship the timeout wrapper. **No behaviour change.**
2. **Call site 1: combat prediction**, state-gated, feature-flagged, Selvala
   first. A/B by seed + fidelity ledger.
3. **Call site 2: loop-product prediction** for Urza (the mechanism from the
   section above, not a rerun of call site 1).
4. **Delete the dead predicates** the two cutovers have replaced.

## Exit bar

Selvala and Urza same-turn conversion, currently **3 wins from 81 fires (3.7%)**,
above **40%**. Purphoros must not regress below 85%. Batch wall clock must not
more than double.
