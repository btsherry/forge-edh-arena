# Ingestion findings — prep understands a quarter of each deck

The measurement that reframed the project. Everything else in this document
follows from the table.

## The measurement

| deck | nonland cards | payoff-tagged | in a combo | **invisible to prep** |
|---|---|---|---|---|
| Urza | 68 | 7 | 24 | **41 (60%)** |
| Selvala | 70 | 11 | 11 | **53 (76%)** |
| Purphoros | 66 | 12 | 9 | **45 (68%)** |
| Giada | 70 | 10 | 3 | **58 (83%)** |

And for every one of those decks, prep reported:

```json
lint-report.json   { "pass": true, "errors": [], "warnings": [] }
unimplemented-cards.txt   (empty)
```

## The two structural flaws

### 1. Prep has no concept of its own ignorance

99 cards go in, roughly 10 get tagged, the rest are silently dropped, and the
run reports complete success. Urza's deck was fully analyzed, his single most
important ability was missed, and no artifact anywhere recorded a gap.

A pipeline that cannot say "I saw something I do not understand" cannot be
improved by running it. Every gap has to be found by a human reading game
logs — which is exactly how the last several weeks were spent.

### 2. "No card names in Java" is not the same as deck-agnostic

The 18 payoff rules are hand-written keyword matchers over oracle prose, each
added when someone noticed a deck needed it. The code contains no card names,
so the architecture *looks* general. **Its actual coverage is the union of
decks we happened to examine.**

Urza is the proof. His oracle text literally contains "without paying its
mana cost". A rule could have caught it. Nobody wrote that rule, because no
earlier deck needed it. We relocated deck-specific knowledge into a
classifier and called it architecture.

## Three sources of truth, and we use the weakest

| source | what it is | status |
|---|---|---|
| **Oracle prose** | human-readable text, ambiguous, needs 18 brittle regexes | **what we parse today** |
| **Forge card scripts** | `MayPlayWithoutManaCost$ True`, `A:AB$ Mana \| Produced$ G \| Amount$ 4`, `Cost$ PayLife<50>` — machine-readable, exact, and *what the rules engine actually executes* | **completely unused** |
| **LLM reasoning** | strategy, synthesis, "these three cards form a pattern" | used only for binding generation |

We have been reading the prose summary of a machine-readable file. This is
the same error as PR-54: approximating something the engine already knows
exactly. **"Ask the engine, do not approximate it" applies to prep, not just
to runtime.**

## The architecture: LLM proposes, engine disposes

Precedent exists in this codebase — Gate 3.5 bindgen already does LLM
generation plus simulation verification for executor bindings, and it works.
Extend that pattern rather than inventing one:

- **Mechanical capabilities ← card scripts.** Exact, zero hallucination.
  "Repeatable activated ability, costs {5}, grants play-without-paying."
- **Strategy ← LLM (Gemini).** Given verified capabilities plus the combo
  list: what is the win plan, in what order, which play patterns matter.
- **Verification ← simulation.** Anything checkable gets checked on a copy.

This puts the LLM where it is strong (synthesis, pattern naming) and away
from where it hallucinates (mechanical facts it would be inventing).

## Ben's two design decisions

### Vocabulary convergence, not vocabulary trust

We will ingest **hundreds to thousands of decks, and the same deck tens to
hundreds of times.** That scale is not a burden — it is the error-correction
mechanism. A proposed capability class is **provisional**, and the registry
tracks two independent numbers:

- **recurrence** — how many DISTINCT decks proposed this class
- **utility** — how many times a pilot DECISION actually consulted it

A one-off hallucination is proposed once, never recurs, is never used, and
gets pruned. A real pattern is proposed independently across many decks and
gets consulted in play, and is promoted to stable vocabulary. **The LLM does
not have to be right; it has to be right more often than random across
independent decks**, which is a much weaker requirement.

This is the answer to the hallucination objection that killed the naive
version of this idea: we are not trusting a single LLM call, we are taking a
vote across thousands of independent ones and checking the winners against
whether they ever mattered in a game.

### Both per-card and whole-deck

- **Per-card** extraction is cheap, parallel, and — critically — **cacheable
  globally by card name.** The same ~20k cards recur across every deck ever
  ingested. Extract once, reuse forever, re-extract only when the extraction
  version changes. At thousands of decks this is the difference between
  viable and not.
- **Whole-deck** synthesis sees what per-card cannot: that these three cards
  form a line, that this deck's plan is storm rather than combat.

Both, with the per-card cache making the whole-deck pass affordable.

## What this does to the Phase 8 planner question

Phase 8 proposed typing combos with post-conditions to feed a backward
planner. **A capability pass produces exactly that typing as a side effect**,
so PR-3 of Phase 8 is subsumed rather than competing.

More importantly it reorders the question. Phase 8's Paper Test asks "can the
engine execute a known-correct line?" This work asks "why do we not know the
lines?" — and we have now measured that we cannot see 60-83% of any deck.
Answering the second first is strictly better sequencing: a planner over a
model that contains a quarter of the deck plans over a quarter of the deck.

The Paper Test is **not cancelled** — it remains the gate before any planner
work, and it is now cheaper to run because a capability pass tells us what
the line actually is.
