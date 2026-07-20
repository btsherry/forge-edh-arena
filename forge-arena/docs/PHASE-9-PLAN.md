# Phase 9 — teach prep to read the deck

Planning record. See `research/ingestion-findings.md` for the measurement
this rests on: **prep is blind to 60-83% of every deck's nonland cards and
reports complete success.**

Phase 8 (`PHASE-8-PLAN.md`) is **not discarded** — its purge list and its
Urza Paper Test gate survive, and its PR-3 (post-condition typing) is
subsumed by PR-A below. Phase 8 resumes after prep can see the deck.

---

## PR-A — Capability extraction from Forge card scripts

**Zero LLM. Zero hallucination risk. Probably the single largest coverage
win available.**

Forge ships every card as a structured script (`forge-gui/res/cardsfolder`)
containing exactly what we have been trying to infer from prose:

```
A:AB$ Mana | Cost$ T | Produced$ G | Amount$ 4      -> repeatable mana, yield 4
SVar:DBPlay: ... MayPlayWithoutManaCost$ True       -> free-cast grant
A:AB$ DealDamage | ValidTgts$ Any | Cost$ PayLife<50>  -> damage outlet, life cost
T:Mode$ SpellCast | ...                             -> cast trigger
```

Parse every nonland card in a deck into structured capabilities: what it
produces, what it costs, whether it is repeatable, what it targets, what
triggers it. These are FACTS from the file the rules engine executes, not
inferences.

Urza's `{5}` becomes visible here without anyone writing a rule about Urza.

**Exit:** the invisible-card percentage per deck, measured before and after.

## PR-B — Prep must account for every card

The bug behind every other bug: prep cannot report its own ignorance.

- `unimplemented-cards.txt` becomes real: every nonland card prep cannot
  characterize is listed, with why.
- `lint-report.json` carries a coverage figure and **warns loudly** below a
  threshold.
- A deck whose commander is uncharacterized is an ERROR, not a warning.

This turns a silent blind spot into a work queue, and makes every subsequent
change measurable. It is small, and it should probably ship first.

## PR-C — Global card-capability cache

Keyed by card name + script hash. The same ~20k cards recur across every
deck ever ingested; extract once, reuse forever, re-extract only when the
extractor version changes.

At the stated scale — hundreds to thousands of decks, the same deck ingested
tens to hundreds of times — this is the difference between viable and not,
and it makes the LLM passes affordable because they too are cached per card.

## PR-D — LLM per-card enrichment (Gemini)

For cards PR-A cannot characterize, ask Gemini for structured capability
tags. **Not prose.** The output contract is a fixed JSON shape, and every
proposed class enters the registry as PROVISIONAL.

Per-card, parallel, and cached by PR-C — so the marginal cost across
thousands of decks approaches zero.

## PR-E — The capability registry and its convergence loop

**The mechanism that makes trusting an LLM safe.** A proposed class is
provisional and carries two independent counters:

- **recurrence** — how many DISTINCT decks independently proposed it
- **utility** — how many times a pilot DECISION actually consulted it in a
  real game

Promotion requires both. Pruning removes classes that recur rarely and are
never consulted. A one-off hallucination is proposed once, never recurs,
never gets used, and dies. A real pattern is proposed independently across
many decks and gets consulted in play.

**The LLM does not have to be right. It has to be right more often than
random across independent decks** — a far weaker requirement, and one the
scale of ingestion is uniquely suited to check.

Utility counting requires a small telemetry addition: when a pilot decision
reads a capability class, say so.

## PR-F — Whole-deck strategy synthesis (Gemini)

One call per deck, given the verified capability inventory plus combos:
what is this deck's win plan, ordered, as structured
`(precondition -> action -> postcondition)` steps; which play patterns
matter; what should be prioritized early.

Structured output only. Prose strategy is unusable by code and would be
another proxy.

## PR-G — Wire strategy into route planning

Replace the hand-written win-route predicates with the synthesized plan.
This is where Phase 8's planner question returns, now over a model that
actually contains the deck.

**Gate: the Urza Paper Test (Phase 8 PR-2) runs before this.** If the engine
cannot execute a known-correct line, a better plan changes nothing.

---

## Sequencing note

PR-B first (small, makes everything measurable), then PR-A (largest win, no
risk), then PR-C (makes the rest affordable), then D/E together (the LLM and
its safety mechanism must not ship apart), then F, then G behind the Paper
Test gate.

## Open question for later

Ben raised that deck prep may want to become an **interactive session** —
subagents plus third-party APIs, managed live rather than as a batch script.
Recorded, not yet designed. The per-card cache (PR-C) is a prerequisite
either way, since an interactive session over an uncached 99-card deck would
be unusably slow.
