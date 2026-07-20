# Architecture survey II — what to build instead

Web + Gemini research after the Phase 7 prediction bet failed. The question:
is "scripted pilot over stock AI" the wrong frame, and what would be better?

## The finding that reframes everything

Our own results table already contains the answer, and it is not about
prediction:

| deck | steps between combo firing and opponents dead | result |
|---|---|---|
| Purphoros | **0** — the combo pings every opponent directly | **92% same-turn** |
| Giada | 1 — wipe, then attack | 9/30 |
| Selvala | 2-3 — infinite mana, pump, attack through blockers | 3/30 |
| Urza | **4** — mana, draw deck, find payoff, cast, activate x3 | **0/30** |

**Conversion collapses in proportion to the number of steps between the
engine and the kill.** Every architecture we have built reasons FORWARD:
"what can I do from here?" The decks that win are the ones where forward
reasoning happens to arrive at the win in one hop.

That is the whole problem, stated once. It is not a prediction problem, not
a coverage problem, and not a combat problem — those are symptoms.

## What we should NOT build

**AlphaZero-style RL — [MageZero](https://github.com/WillWroble/MageZero)**
is the closest real project: AlphaZero on an XMage fork, 2M-feature sparse
embedding with Weinberger hashing, transformer encoder, four decision-typed
policy heads, PUCT search. Honest reported numbers: **~250 games/hour, ~150
MCTS sims/second**, 16%→66% win rate vs minimax on ONE 60-card matchup,
still ~13% below estimated human play. Its own README lists imperfect
information as unsolved and throughput as the binding constraint.

It is 1v1 constructed. We are 4-player, 100-card singleton, and would need a
training pipeline plus orders of magnitude more games. Not viable, and not
close.

**IS-MCTS / ensemble determinization —
[Cowling, Ward & Powley (2012)](https://ieeexplore.ieee.org/document/6218176/),
IEEE ToCIAIG**, the canonical MTG search paper: determinize hidden
information, run MCTS across an ensemble, prune to get more from each
determinization. The blocker is arithmetic, not theory: MCTS needs thousands
of playouts per decision and **our measured GameCopier ply is 283 ms p50**.
A thousand playouts is five minutes per decision. Determinization also
suffers strategy fusion and non-locality, both worse with three opponents.

Both are the "more search" answer, and we have already measured that our
search unit is three orders of magnitude too slow for it.

## What to build: reason BACKWARD from the win

**[GOAP — Jeff Orkin, F.E.A.R. (2006)](https://www.gamedeveloper.com/design/building-the-ai-of-f-e-a-r-with-goal-oriented-action-planning)**,
STRIPS-style backward chaining, and **HTN** (Killzone 2, Max Payne 3, Dying
Light), which is faster and more predictable but assumes a mostly fixed task
decomposition.

The mapping onto our system is unusually direct, because **prep already
produces most of a planning domain and we throw the structure away.** Today
a combo maps to an *archetype* (how to execute it mechanically). It should
also map to a **post-condition** (what state it leaves us in), and payoffs
should carry **pre-conditions**.

Urza, as a plan rather than a pile of bindings:

```
GOAL           all opponents at 0 life
  <- Aetherflux Reservoir activation x3     pre: life >= 50 each,
                                                 Reservoir on battlefield
  <- cast many spells this turn             post: life (storm-cumulative)
                                            pre:  spells in hand, mana
  <- draw the deck                          post: spells in hand
                                            pre:  infinite mana + draw engine
  <- CastBounceManaLoop                     post: infinite mana
```

Every arrow is a fact prep can already compute or already computes. The
planner asks "can I chain post-conditions to GOAL?" and the answer tells the
pilot what to do with infinite mana — which is precisely the question it
currently cannot answer, and why it banks a thousand mana and passes.

This also explains Purphoros without special-casing it: its plan is one arrow
long, so forward reasoning could not miss it.

### Why this is the right size of change

It is not a rewrite. The executors, the copy-validation, the telemetry, the
prep pipeline all stay. What changes is that combos and payoffs get typed
by **what state they produce and require**, and a small backward-chaining
planner sits where `LethalityPlanner`'s hand-written route predicates are
now. That is the layer that has been wrong three times (PR-41, 54, 55).

## The multiplayer piece — why the A/B failed

Free-for-all with 3+ players is a different game, and the literature says so.

- **Paranoid search (Sturtevant & Korf, 2000)** — assume all opponents are
  allied against you. **Max-n (Luckhardt & Irani, 1986)** — each maximizes
  independently. Nash equilibria are not polynomial-time computable for n>2,
  and multiple equilibria with different values can exist.
- **The three-player problem / kingmaking** —
  [Mitigating Kingmaking in Multiplayer Board Games (Uppsala)](https://uu.diva-portal.org/smash/get/diva2:1876522/FULLTEXT01.pdf):
  players who are behind gang up on the leader, and a losing player's choice
  of target decides who wins. Last-survivor win conditions amplify threat
  assessment, because misdirected aggression is punished immediately and
  irreversibly.

**Commander is a paranoid environment for a combo deck specifically**: the
moment you show an infinite loop, the table plays archenemy against you.

This names our Phase 7 failure exactly. We asked "does this attack kill
someone" — a max-n-flavoured question — in a game where the answer that
matters is "does this attack leave me alive against the survivors." The
concrete replacement rule (Gemini's phrasing, and it is a good one):

> Do not tap out to kill one opponent unless the post-combat board survives
> the remaining opponents' offense — or unless the attack kills the table.

That is a *bilateral attrition constraint*, not a lethality check, and it is
cheap: it needs board power and untapped blockers, no simulation at all.

## Rejected again: deck-specific payoff scripts

Gemini's concrete step-4 advice was to hardcode payoff routines ("if infinite
mana, pump a creature with trample to sum-of-opponents-life and attack";
"cast Aetherflux, spam spells to 50 life, fire"). It would work, for these
four decks, and it violates the project's first constraint. The reviewer did
not know that constraint — this is the second consultation where its most
concrete advice had to be refused for the same reason.

The generic form is exactly the GOAP framing above: those "hardcoded
routines" ARE plans, and a planner derives them from typed pre/post
conditions instead of from card names.

## The parallel review's strongest objection — and it lands

Gemini was given a deliberately non-overlapping brief (design the ontology,
find where GOAP breaks, make the attrition rule falsifiable, and STEELMAN the
case that planning is also wrong). The steelman is the most valuable thing
either survey produced:

> A GOAP planner reasons over an ABSTRACTED SHADOW-STATE — JSON predicates
> derived from Commander Spellbook strings — not over Forge's actual game
> state. The planner will conclude "deck drawn, infinite mana, cast the
> payoff, win" while in Forge that draw triggered a mandatory discard, or a
> drawn card has an ETB needing a target, or a Rule of Law effect is out.
> Phase 7 planning over live state was too SLOW. Planning over abstracted
> state will be fast and **hallucinatory**.

That is the same proxy trap one level further out: the ontology would be a
proxy for the game state, and we would discover its divergence only after
building a planner on top of it.

### The falsifying experiment: the Urza Paper Test

Before building any ontology, planner, or PDDL layer, prove the plan is
even EXECUTABLE:

1. Hand-write the exact action sequence a flawless planner would emit for
   Urza's Aetherflux line.
2. Inject it into the pilot **as a temporary experiment**, not shipped code
   (a hardcoded script in main code violates constraint 1 — this is a probe,
   and it gets deleted).
3. Run the 30-game seed-paired batch.

- **Converts near 90%** → the engine seams can carry a combo to a kill, and
  automating plan GENERATION is worth building.
- **Does not convert** → it gets stuck on priority passes, stack
  resolution, or state-based actions. **Stop.** A planner that emits
  sequences the execution layer cannot perform is another wasted night.

This costs one afternoon and decides whether the entire direction is real.
It should happen before anything else on this page.

## Ontology design, if the test passes

Gemini's specific guidance, adopted:

- **Do not take Commander Spellbook's taxonomy wholesale.** Its tags are
  stringly-typed and built for search, with semantic overlap the planner
  cannot see ("Infinite draw" implies "library accessible" only to a human).
  Map it into our own predicates during prep, enriched with Forge card data
  for operational constraints Spellbook omits (e.g. "infinite mana, but only
  castable on artifact spells").
- **"Infinite" is a BOOLEAN, not a big number.** `has_infinite_mana_U` as a
  state, not `mana = 999999` — numeric bounds checking breaks on the latter
  and it fails to capture "unbounded repeatable loop" versus "large pool".
  Finite-but-large quantities stay numeric: `storm_count`, `life_total`,
  `cards_in_library`.
- **Propositional STRIPS is the wrong formalism.** Combo execution is
  inherently metric — "I need 3 blue, I have 1, activating this rock nets 1,
  I am short 1" is inexpressible in classic GOAP. PDDL 2.1 numeric fluents
  or SAS+.
- **Forward A* may beat backward chaining here.** The state space of a
  single turn's combo pieces is small; prior art applies PDDL to FreeCell
  and Spider Solitaire (close cousins of "execute a deterministic line"),
  while Hearthstone work (Santos et al.) used forward Monte Carlo search.
- Needs a `can_target_<seat>` fluent: hexproof/ward/protection otherwise
  makes the final arrow of every plan brittle.

## The attrition rule, made falsifiable

Paranoid assumption (Sturtevant): assume the remaining opponents coalesce
against you. Then:

```
Survival_Margin = (my_life - self_damage_committed)
                - SUM over survivors of Effective_Inbound_Lethality
```

with inbound lethality per survivor = evasive power we cannot block, plus
`max(0, their_total_power - our_available_blocker_toughness)`, and treated as
INFINITE if their commander power plus damage already taken >= 21, or infect
plus existing poison >= 10. Pillowfort effects reduce their attacker count by
what their open mana can pay.

**Testable with zero simulation and against existing seeds**: log
`Survival_Margin` at declare-attackers across a batch, and decline attacks
where it is negative. That is measurable before it is ever wired to a
decision.

## Recommendation, in order

0. **RUN THE URZA PAPER TEST FIRST.** One afternoon, throwaway code,
   decides whether any of the rest is worth building.
1. **Type the artifacts.** Give each combo a post-condition
   (`INFINITE_MANA`, `INFINITE_DRAW`, `INFINITE_CASTS`, `INFINITE_UNTAP`)
   and each payoff a pre-condition + effect. Prep work, no behaviour change,
   independently inspectable. This is the whole foundation.
2. **Backward-chain to a plan.** Replace route selection with: from GOAL,
   find a chain of post-conditions that reaches it. Emit the plan as
   telemetry before it drives anything — a plan we can read is worth more
   than a verdict we cannot.
3. **Execute the plan's next unmet step.** This is the connective tissue
   Urza lacks: infinite mana stops being a terminus and becomes a
   precondition with a known consumer.
4. **Replace the lethality check with the attrition constraint.** Cheap,
   no simulation, and directly addresses the measured multiplayer failure.
5. Coverage (11 unbound Urza combos) continues in parallel — but note that
   under a planner, an unbound combo with a KNOWN post-condition is still
   useful to the plan even before it has an executor.

## Sources

- [MageZero — AlphaZero-style RL for MTG on XMage](https://github.com/WillWroble/MageZero)
- [Cowling, Ward & Powley, Ensemble Determinization in MCTS for MTG (IEEE ToCIAIG 2012)](https://ieeexplore.ieee.org/document/6218176/)
- [Mitigating Kingmaking in Multiplayer Board Games (Uppsala)](https://uu.diva-portal.org/smash/get/diva2:1876522/FULLTEXT01.pdf)
- [Orkin, Building the AI of F.E.A.R. with GOAP](https://www.gamedeveloper.com/design/building-the-ai-of-f-e-a-r-with-goal-oriented-action-planning)
- [Forge and XMage rules engines compared](https://cgomesu.com/blog/forge-xmage-mtg/)
- [List of MTG engines](https://slightlymagic.net/wiki/List_of_MTG_Engines)
