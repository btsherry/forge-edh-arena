# Phase 8 — prove execution, then plan

Planning only. Nothing here is built yet.

## The reframe this phase rests on

Conversion collapses in proportion to the number of steps between the engine
firing and the opponents dying:

| deck | steps | result |
|---|---|---|
| Purphoros | 0 — combo pings everyone directly | 92% same-turn |
| Giada | 1 | 9/30 |
| Selvala | 2-3 | 3/30 |
| Urza | 4 | **0/30** |

Everything we have built reasons FORWARD ("what can I do?"). The decks that
win are the ones where forward reasoning lands on the win in one hop. The
candidate fix is to reason BACKWARD from "I win" — but that is a hypothesis,
and Phase 7 is a fresh reminder of what an untested architectural hypothesis
costs.

## The order that matters: purge, prove, then build

Two decisions shape this whole phase, both from adversarial review.

**Delete before building.** The codebase carries mechanisms that measurement
has already invalidated. Carrying them into a new architecture means porting
things we know do not work.

**Prove execution before building a planner.** The shadow-state objection
(§ architecture-survey-2) says a planner reasons over abstracted predicates,
not Forge's real state, and would be fast but hallucinatory. Worse, a planner
that emits a perfect sequence is worthless if the execution layer cannot
perform it. So the second PR is a gate, not a feature.

---

## PR-1 — The Great Purge

Deletions only. No new logic. Everything here is dead by measurement, not by
taste.

| removing | why |
|---|---|
| `KillPredictor.predictCombat` (passive) | Measured to answer "what would stock AI do", not "does my attack kill". Referenced only by its own test. |
| `KillPredictor.predictAlphaStrike` + `PREDICT_DECIDE` arm | A/B: 33 steered attacks, 19 wins vs baseline 20. Zero benefit, ~24% exception rate. |
| `ComboPilot.distanceToFire()` | Built as a metric, never emitted, never read. |
| `lethalAlphaOrder` (PR-34 worst-case blocker math) | Superseded and never demonstrated to convert. Removed, NOT replaced (see Deferred D-1). |
| `LethalityPlanner` 4-tier haste chain (32 refs) | PR-54 made attack-eligibility the real predicate; the chain is vestigial. |
| `PredictionFidelityTest`, `KillPredictorTest` | Diagnostics that already told us what they were built to find. |

**Kept, against review advice — flagged for Ben's call.** Gemini argued the
unused payoff classes and their `ConversionPlanner` branches are YAGNI and
should go: 8 of 18 classes are unused by our four decks, and untested surface
area rots. That is a fair hygiene argument and I am half-persuaded.

The distinction I would draw is between **vocabulary and execution paths**:

- The payoff *classification* vocabulary (`oracle_win`, `x_drain_each_opponent`,
  `mill_opponents`...) is how prep DESCRIBES an arbitrary deck. Thassa's
  Oracle is one of the most common EDH win conditions; deleting its class
  means the next deck dropped in is silently undescribed. That is the
  project's first goal, not speculative generality.
- The *executable branches* keyed off classes no deck has (`TABLE_WIDE`, `DIG`)
  are genuinely untested code, and Gemini is right that they are liability.

**DECIDED (Ben): keep the vocabulary, delete the untested branches.** The
classification vocabulary is the ingestion contract for decks we have not
seen; the untested execution branches are liability.

---

## The finding that changes PR-2, and possibly the whole diagnosis

Ben pointed at Urza's own card, and it reframes the Urza failure.

```
A:AB$ Shuffle | Cost$ 5 | ... Shuffle your library, then exile the top card.
                              Until end of turn, you may play that card
                              without paying its mana cost.
SVar:DBPlay: ... MayPlayWithoutManaCost$ True
```

With infinite mana, `{5}` is a **repeatable free-cast engine**: each
activation plays another card off the top for nothing. Repeated, it plays out
the deck. And Urza is a COMMANDER — always available from the command zone,
with infinite mana paying any amount of commander tax. The root precondition
of his whole plan is therefore always satisfiable, regardless of draws.

That completes the line exactly:

```
GOAL  three opponents dead
  <- Aetherflux Reservoir activated x3        pre: 50 life each
  <- life >= 50                               <- Aetherflux gains 1 life per
                                                 spell cast this turn,
                                                 cumulative (storm-shaped)
  <- many spells cast this turn               <- Urza {5} activated repeatedly,
                                                 each activation = one free cast
  <- infinite mana                            <- any bound mana combo
  <- Urza on battlefield                      <- command zone, tax paid by
                                                 the infinite mana
```

**And prep cannot see any of it.** Urza's payoff classes are
`ping_any_target` and `life_cost_outlet` (both Aetherflux),
`draw_engine_permanent`, `haste_equip`, and `commander_creature` — a generic
tag. There is **no payoff class in `PayoffRules` for "repeatable activated
ability that converts mana into free casts."** The pilot ends up holding
infinite mana, holding Aetherflux, and having no representation of the one
ability that connects them.

### What this does to the diagnosis

We characterized Urza as "four steps from engine to kill". That was
generous: **step two has no representation in our model at all.** The gap is
in the VOCABULARY, not (or not only) in forward-versus-backward reasoning.

This is a materially cheaper hypothesis than the planner, and it is testable
on its own. A new deck-agnostic payoff class — any repeatable activated
ability granting `MayPlayWithoutManaCost` or equivalent — plus a conversion
step that spends banked mana on it, might connect infinite mana to the kill
without any planner at all.

**It does not replace PR-2, it sharpens it.** The Paper Test now has a
concrete script to hand-write, which raises its value: it becomes a test of
whether the ENGINE SEAMS can execute this known-correct line, with the
planning question isolated out.

## PR-2 — The Urza Paper Test (GO / NO-GO GATE)

**Nothing after this PR is justified until it passes.**

Hand-write the exact action sequence a flawless planner would emit for
Urza's Aetherflux line. Inject it as a **throwaway probe** — hardcoded card
names in main code violate constraint 1, so this is explicitly temporary and
is deleted in PR-6 regardless of outcome. Run the 30-game seed-paired batch.

- **Converts near 90% same-turn** → the engine seams can carry a combo from
  engine to kill. Plan GENERATION is worth automating. Proceed.
- **Does not convert** → the failure is in execution (priority passes, stack
  resolution, state-based actions), not planning. **STOP.** Building a
  planner to emit sequences the engine cannot perform is a second wasted
  architecture. The next phase becomes fixing execution seams instead.

Cost: roughly one afternoon. It buys the answer to "is the whole direction
real" before we spend weeks on it.

---

## PR-3 — Post-condition typing (artifacts only)

Prep tags every combo with the state it PRODUCES and every payoff with what
it REQUIRES. No behaviour change; inspectable as JSON.

Design decisions taken from the ontology review:

- **Do not adopt Commander Spellbook's taxonomy wholesale.** Its tags are
  built for human search, with semantic overlap a planner cannot see
  ("Infinite draw" implies "library accessible" only to a person). Map it
  into our own predicates during prep, enriched with Forge card data for
  constraints Spellbook omits (e.g. "infinite mana, artifact spells only").
- **"Infinite" is a BOOLEAN, not a large number.** `has_infinite_mana_U` as
  a state, never `mana = 999999` — numeric bounds break on the latter and it
  loses the distinction between an unbounded repeatable loop and a big pool.
  Finite-but-large stays numeric: `storm_count`, `life_total`,
  `cards_in_library`.
- Propositional STRIPS is the wrong formalism; preconditions are metric
  ("life >= 50"). PDDL 2.1 numeric fluents in spirit, not necessarily a PDDL
  parser.
- A `can_target_<seat>` predicate, or hexproof/ward makes the last arrow of
  every plan brittle.

---

## PR-4 — Planner core: emit AND execute

Backward-chain from GOAL (all opponents dead) through post-conditions to a
plan; the pilot executes the plan's next unmet step.

Emission and execution land together, deliberately. A plan that only emits
telemetry without driving anything is another proxy metric waiting to lie to
us — exactly the Phase 7 shape, where a shadow ledger could not validate a
prediction whose action was never taken.

---

## PR-5 — JIT precondition assertion (the honesty guard)

The cheapest defence against the shadow-state objection, and the piece that
makes the planner safe to trust. Adopted wholesale from review.

Do not keep the plan synced with Forge. Let the planner produce a long
sequence from abstracted predicates. Immediately before executing step N,
ask Forge's REAL state three questions:

1. Do I have priority?
2. Is the required mana actually available (or producible from this board)?
3. Are the specific targets present and targetable right now?

All true → execute. Any false → **the plan has diverged from reality; throw
it away and replan.**

This treats the plan as a **disposable hypothesis, not a script**, and
removes the need for any state-tracking machine. A countered spell or a
destroyed piece simply fails an assertion, and the pilot replans against the
world as it actually is.

---

## PR-6 — Delete the probe, re-measure, remove what was superseded

Remove PR-2's hardcoded probe (it always was temporary). Delete whatever
PR-3-5 superseded. Fresh seed-paired batch against the Phase 7 baseline:
selvala 3/30, purphoros 8/30, urza 0/30, giada 9/30.

**Exit bar: Urza above 0. Purphoros must not regress below 85% same-turn.**
A deliberately modest bar — Urza converting at all would be the first
evidence in this project that a multi-step deck can be piloted to a win.

---

## PR-2b — the free-cast payoff class (promoted by the Urza finding)

A new deck-agnostic payoff class for repeatable abilities that convert mana
into casts (`MayPlayWithoutManaCost` and equivalents), plus a conversion
step that spends a banked pool on it. Classified from oracle text and Forge
card data like every other class — no card names in code.

Sequenced immediately after the Paper Test because the test will tell us
whether the resulting line is executable at all. If the test passes, this is
plausibly the smallest change that moves Urza off zero, and it may make
PR-3/4/5 unnecessary for this deck — which is worth knowing before building
a planner.

## Deferred, with reasons (the other four of the requested ten)

Cut after review argued they are scope creep or fresh proxies. Recorded so
the reasoning is not lost.

**D-1 — Survival_Margin attrition rule.** A paranoid-search-flavoured combat
heuristic replacing `lethalAlphaOrder`. Cut: we are building a combo pilot,
not a combat AI, and this is another hand-written proxy of exactly the kind
that has failed four times. Revisit only if measurement shows combat is the
binding constraint. `lethalAlphaOrder` is deleted in PR-1 and NOT replaced.

**D-2 — Urza coverage (11 unbound combos).** Cut for now: Urza is 0/30 and
needs ONE line to convert, not 23 lines to exist. Mapping more combos before
any of them converts is motion without progress.

**D-3 — Deployability / the Hullbreaker affordability problem.** Lines enter
and abort because a 7-mana bouncer is unaffordable. Real, but it is
heuristic gating for a planner that does not exist yet; under a planner,
"can I afford assembly" is a precondition the plan already has to satisfy.

**D-4 — Haste chain retirement.** Folded into PR-1 rather than standing
alone.

## The biggest risk, named

That we build the planner and Urza still does not convert, because of a
structural limit in how Forge handles chained priority — a Phase 7 repeat at
larger scale. **PR-2 exists precisely to make that failure cost one
afternoon instead of a month.**
