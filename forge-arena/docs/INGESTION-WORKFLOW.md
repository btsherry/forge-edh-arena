# The ingestion workflow — correct, then efficient, then elegant

Design for replacing prep. Not yet built.

Ordering principle, taken literally: **every design choice below is made for
correctness first.** Where correctness and efficiency conflict, efficiency
loses. Where efficiency and elegance conflict, elegance loses.

---

## Part 1 — What prep does today, audited

### Current gate chain (`PrepMain`)

| gate | what it does | data source |
|---|---|---|
| 0 ingest | deck list → card records | `.dck` file or Moxfield API |
| 1 lint | legality / banlist | static banlist snapshot |
| 2 implementability | can Forge play these cards; goldfish compile | Forge card DB |
| 3 combos + coverage | detected combos, payoff classes, win routes | Commander Spellbook API + **18 hand-written regexes over oracle prose** |
| tutor weights | which tutors fetch which pieces | Gate 3 artifacts |
| autopsy | stall diagnosis, route library repair | prior run logs + LLM |
| 3.5 bindgen | combo → archetype bindings | LLM + **sim verification** (opt-in) |

### Data sources currently consulted

1. Deck list (`.dck` / Moxfield)
2. Forge card **database** — for "can Forge play this card"
3. Commander Spellbook — combo list
4. Oracle **prose** — for payoff classification
5. LLM — bindings only, and only when opted in

### Data sources NOT consulted, all available

1. **Forge card SCRIPTS** (`res/cardsfolder/*.txt`) — the structured ability
   definitions the rules engine actually executes. The single largest miss;
   the prototype doubled coverage from these alone.
2. **Strategy primers** — deck descriptions, EDHREC archetype pages, the
   author's own notes. `deck-meta.yaml` has `archetype_tags: []` and
   `author_notes: null` on every deck.
3. **Prior run telemetry** — we have thousands of games of evidence about
   what each deck actually does, consulted only by the autopsy.

### The two defects, restated

- **Prep cannot report its own ignorance.** 60-83% of nonland cards are
  silently dropped and the run reports `pass: true`.
- **Payoff classification is 18 hand-written regexes over prose**, so
  coverage equals the union of decks someone happened to examine.

---

## Part 2 — The new workflow

### The correctness spine: a ground-truth hierarchy

Every fact carries a provenance, and **a lower tier may never override a
higher one**:

| tier | source | may be trusted for |
|---|---|---|
| **T0** | Forge card script | mechanical fact — costs, produced mana, targets, triggers, grants |
| **T1** | Simulation on a `GameCopier` copy | behavioural fact — does this line actually resolve and profit |
| **T2** | Commander Spellbook | combo membership (attested, not proven) |
| **T3** | LLM (Gemini / subagent) | synthesis, naming, strategy, priority |

This is the rule that makes the LLM safe to use at all: **it is never asked
for a fact that T0 or T1 can answer.** It is asked what those facts MEAN
together.

---

### Stage 0 — Acquire (deterministic, cached)

Fetch, in parallel, into one package per deck:

- deck list → card names, quantities, commander flag
- **per card: the Forge script file, oracle text, type line, mana cost**
- Commander Spellbook combos for the deck
- strategy primer if one exists (Moxfield description, EDHREC archetype,
  user-supplied notes) — optional, never load-bearing
- prior telemetry for this deck hash, if we have run it before

Everything here is cached by **card name + script hash**. The same ~20k cards
recur across every deck ever ingested; this is what makes later stages
affordable.

### Stage 1 — Mechanical extraction (deterministic, T0, no LLM)

Parse every card script into structured capabilities: produced mana and
amount, activation costs, life costs, targets, triggers (`SpellCast`,
`ChangesZone`, `Attacks`, `Upkeep`), grants (`MayPlayWithoutManaCost`,
keyword grants), zone changes, repeatability.

**This is ground truth and is never overwritten by a later stage.**
Prototype-measured: coverage roughly doubles here, before any LLM is
involved.

### Stage 2 — Declare ignorance (deterministic)

Partition every nonland card into:

- **characterized** — Stage 1 produced capabilities
- **parsed but uncharacterized** — script read, no known pattern matched
- **unreadable** — no script found (e.g. double-faced name normalization)

The second and third lists ARE the LLM work queue, and they are also the
prep report. **A deck whose COMMANDER is uncharacterized fails the gate
outright** — that is the Urza case, and it should have been an error.

This stage is the whole fix for defect #1 and should ship before anything
else, because it converts a silent blind spot into a measurable work queue.

### Stage 3 — Per-card enrichment (T3, tightly scoped)

**Only the Stage 2 queue is sent.** Not the deck. Sending 99 cards when 30
are unknown is 3x the cost and 3x the hallucination surface.

The package per card, and nothing more:

```
card name, mana cost, type line
oracle text
THE RAW FORGE SCRIPT
the current capability vocabulary, with definitions
```

The required return, strictly schema-validated:

```json
{
  "card": "<exact name as given>",
  "capabilities": ["<from the supplied vocabulary only>"],
  "proposed_new": [{
      "name": "snake_case_identifier",
      "definition": "one sentence, mechanical not strategic",
      "script_evidence": "<the exact token/line from the script>",
      "why_existing_insufficient": "..."
  }],
  "uncertain": true|false
}
```

**Hard constraints on the return, enforced in code, not requested politely:**

1. Every entry in `capabilities` must exist in the supplied vocabulary.
   Unknown values are rejected, not coerced.
2. Every `proposed_new` MUST carry `script_evidence` that **literally occurs
   in the script we sent.** A proposal citing text that is not in the file is
   a hallucination and is discarded automatically. This is the single
   highest-value constraint in the design.
3. No strategy, no ratings, no prose. Mechanics only — strategy is Stage 4's
   job and mixing them invites the model to reason about the wrong thing.
4. `uncertain: true` is an acceptable answer and is never penalised. A model
   allowed to say "I don't know" is far more useful than one that must guess.

### Stage 4 — Whole-deck synthesis (T3)

One call, given the full verified capability inventory plus combos plus the
strategy primer:

```json
{
  "win_plan": [
    {"step": 1,
     "requires": ["<capability or state predicate>"],
     "action": "<what the pilot does>",
     "produces": ["<capability or state predicate>"],
     "cards": ["<must exist in this deck>"]}
  ],
  "play_patterns": [{"name": "...", "when": "...", "cards": [...]}],
  "early_priorities": ["<card names>"],
  "notes_for_humans": "..."
}
```

**Constraints enforced in code:**

1. Every card named must exist in the decklist.
2. Every capability referenced must exist in the Stage 1/3 inventory.
3. The chain must connect: step N's `requires` must be satisfied by some
   earlier step's `produces`, or by an opening-state predicate. **A plan with
   a dangling precondition is rejected and regenerated** — this is exactly
   the Urza failure (infinite mana with no consumer) caught mechanically.

### Stage 5 — Binding and archetype mapping (T1 verification)

Existing bindgen, now fed capabilities instead of guessing from names. Every
binding is **sim-verified on a `GameCopier` copy** before it is written —
this already works and is the model for the whole design.

Combos that map to no archetype are recorded with their capabilities, so
they are *visible to the planner as unexecutable* rather than absent.

### Stage 6 — Acceptance gate (T1)

**Prep is not "done" because it produced files.** It is done when the deck
demonstrably executes the first step of its own plan.

Goldfish the deck with the pieces for `win_plan[0]` placed, and assert the
pilot performs that step. If it cannot, prep FAILS with a specific reason.

This is the gate that would have caught Urza on day one: a plan whose first
step is "activate Urza's `{5}`" fails immediately if nothing can express
that activation.

---

## Part 3 — Where the human sits (the interactive part)

Automatic, no approval needed:

- Stages 0, 1, 2 (deterministic)
- Stage 3 returns using **existing** vocabulary
- Stage 5 bindings that sim-verify
- Stage 6 acceptance

Queued for review:

- **New vocabulary proposals.** Held as provisional, never auto-promoted.
  Promotion requires recurrence across distinct decks AND utility (a pilot
  decision actually consulted it) — the convergence loop. A human can
  promote early or reject outright.
- **Win plans with a rejected/dangling chain** after one regeneration.
- **Acceptance-gate failures**, which are the real work queue: "this deck's
  plan needs a capability the harness cannot execute."

The interactive session is therefore not "watch prep run". It is: prep runs
itself, and surfaces **the three things only a human should decide** —
is this new vocabulary real, is this plan sane, and do we build the missing
executor.

---

## Part 4 — Why this is correct before it is fast

Five mechanisms, each aimed at a specific way we have already been wrong:

1. **Ground-truth hierarchy** — the LLM is never asked a question the script
   can answer. Directly prevents "invented a mechanical fact".
2. **Script-evidence requirement** — a proposed capability citing text absent
   from the file is auto-discarded. Prevents plausible-but-fabricated
   vocabulary without a human reading every proposal.
3. **Closed vocabulary on the hot path** — Stage 3 may only use existing
   classes; anything new is quarantined. Prevents silent vocabulary drift.
4. **Chain validation** — a plan with a dangling precondition is rejected
   mechanically. This is the Urza bug expressed as a check.
5. **Acceptance gate** — prep fails unless the deck performs step 1 of its
   own plan. Prevents the current failure mode where prep reports success
   over a model containing a quarter of the deck.

Efficiency comes from the cache (per card, globally, by script hash) and
from only sending the LLM what T0 could not answer — typically ~30 cards per
deck, and near zero on the second deck that shares them.

Elegance is deliberately last. The capability histogram hints that archetype
binding could eventually be *derived* from capabilities rather than authored
— that is an elegance win, and it is explicitly deferred until the correct
version works.
