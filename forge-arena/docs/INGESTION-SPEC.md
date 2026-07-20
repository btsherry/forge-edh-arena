# Ingestion spec — the interactive session, subagents, and Gemini

Companion to `INGESTION-WORKFLOW.md`. This is the executable contract:
what runs, what gets handed to whom, what must come back, and where it
breaks.

## Correction to the previous draft

The earlier design sent only *uncharacterized* cards to T3. **That was
wrong**, for the exact reason this project keeps being wrong: looking at
combo cards and ignoring the rest is how we ended up blind to 60-83% of
every deck.

Concretely — Selvala's unbound combos include **Voyaging Satyr + Gaea's
Cradle**. A *land* is load-bearing in a combo we cannot execute. Gap-only
review would have skipped it.

**Every card goes to T3, lands included.** The efficiency objection is
answered by deduplication and caching rather than by narrowing scope:

- A 99-card deck is typically **~65-75 UNIQUE names** (37 Forests are one
  name).
- Analysis is cached **globally by card name + script hash**. A basic Forest
  is analyzed once in the project's lifetime; Sol Ring once, then never
  again across thousands of decks.
- Steady-state marginal cost per new deck approaches only its genuinely
  novel cards.

Scope stays whole-deck. Cost is controlled by not doing the same work twice.

---

## Part 1 — The workflow, step by step

### Step 0 — Session start (human)

`claude` session, deck source in hand (`.dck` path or Moxfield URL). A
**custom skill** (`/ingest-deck`) drives everything below so that every deck
gets identical treatment. The skill is the enforcement mechanism: prompts,
schemas, and validation live in it, not in whatever I happen to type.

### Step 1 — Acquire (deterministic, no model)

| datum | source | notes |
|---|---|---|
| decklist, quantities, commander | `.dck` / Moxfield API | |
| oracle text, type line, mana cost, CMC | Forge card DB | |
| **card script** | `res/cardsfolder/**.txt` | T0 ground truth |
| combos | Commander Spellbook API | T2, attested |
| legality | banlist snapshot | |
| strategy primer | Moxfield description / EDHREC / user notes | **hint only, never load-bearing** |
| prior telemetry | previous runs of this deck hash | if any |
| existing capability vocabulary | global registry | supplied to every model call |

Output: one **deck package**, plus a per-card package for each unique name.

### Step 2 — Mechanical extraction (deterministic, T0)

Parse every script into structured capabilities. Ground truth. Never
overwritten by any later stage. Doubles coverage before a model is involved.

### Step 3 — Per-card analysis (Claude subagents, parallel)

Every unique card not already in the cache. Fanned out in batches.

**Why Claude subagents rather than Gemini here:** they have tool access. A
subagent can open the actual script file, cross-check the oracle text
against it, and quote real evidence. Gemini gets what we paste; a subagent
can verify.

### Step 4 — Whole-deck synthesis (Gemini)

One call with the complete package: all cards with their verified
capabilities, all combos, the primer, and prior telemetry.

**Why Gemini here:** this is holistic synthesis over a large context with no
tool use required, which is where it has been strongest in this project.
It also keeps the synthesis independent of the per-card pass, so the two can
be cross-checked.

### Step 5 — Cross-validation (deterministic)

Compare subagent per-card roles against Gemini's whole-deck plan. Any card
the plan calls load-bearing that per-card analysis called irrelevant — or
vice versa — is a **flag for human review**. Two independent passes
disagreeing is signal, not noise.

### Step 6 — Binding, sim-verification, acceptance gate

Existing bindgen, now capability-informed. Every binding sim-verified on a
copy. Then the acceptance gate: **goldfish the deck and confirm the pilot
executes step 1 of its own win plan.** Prep fails otherwise.

### Step 7 — Human review queue (interactive)

Surfaced for decision, everything else automatic:

1. New vocabulary proposals (provisional until they recur AND get used)
2. Cross-validation disagreements from Step 5
3. Acceptance-gate failures — the real work queue: "this plan needs an
   executor we do not have"

---

## Part 2 — Handoff to Claude subagents (per card)

### What each subagent receives

```
CARD PACKAGE
  name, mana_cost, type_line, cmc, color_identity
  oracle_text
  forge_script          <- the complete raw file
  script_path           <- so it can re-read/verify
  combos_containing_this_card   [ids + piece lists]  (may be empty)
  deck_context: { commander, color_identity, deck_size,
                  archetype_hint_from_primer (optional) }
  capability_vocabulary: [ {name, definition}, ... ]
```

### What each subagent must return

```json
{
  "card": "<exact name as supplied>",
  "capabilities": ["<from supplied vocabulary ONLY>"],
  "proposed_new": [{
    "name": "snake_case",
    "definition": "one sentence, MECHANICAL not strategic",
    "script_evidence": "<exact substring of forge_script>",
    "why_existing_insufficient": "<one sentence>"
  }],
  "role": "combo_piece|enabler|payoff|ramp|interaction|protection|tutor|land_utility|land_basic|filler",
  "role_rationale": "<one sentence, may reference deck_context>",
  "activation_summary": [{
    "cost": "<from script>", "effect": "<from script>", "repeatable": true|false
  }],
  "notable_interactions": ["<other cards IN THIS DECK, by exact name>"],
  "uncertain": true|false,
  "uncertainty_reason": "<required iff uncertain>"
}
```

### Constraints enforced in code, not requested politely

1. `capabilities` ⊆ supplied vocabulary. Unknown values **rejected**, never
   coerced to the nearest match.
2. Every `proposed_new.script_evidence` must be a **literal substring of the
   supplied `forge_script`.** Fails → the proposal is discarded
   automatically, no human reads it. **The single highest-value guard in the
   design.**
3. `notable_interactions` may only name cards in this decklist.
4. `activation_summary.cost` must appear in the script.
5. `uncertain: true` is always acceptable and never penalised. A model
   permitted to say "I don't know" beats one obliged to guess.
6. **Batch size ≤ 10 cards per subagent.** Larger batches measurably
   degrade per-item care, and one bad card should not poison ten.

### Why `role` is asked here despite being strategy-adjacent

`role` is asked with **deck context supplied**, which is the point: a Sol
Ring in a storm deck is `ramp`; Gaea's Cradle in Selvala is `combo_piece`.
Mechanics alone cannot make that call, and it is the judgement that gap-only
review would have missed. It is explicitly separated from
`capabilities` (pure T0) so a wrong role never corrupts a mechanical fact.

---

## Part 3 — Handoff to Gemini (whole deck)

### What Gemini receives

```
DECK PACKAGE
  commander, color identity, decklist with quantities
  FOR EVERY CARD: capabilities (verified), role, activation_summary
  combos: full list with piece names and Spellbook feature tags
  capability_vocabulary with definitions
  strategy_primer (optional, LABELLED AS UNVERIFIED HINT)
  prior_telemetry (optional): wins, fires, conversion, common stall reasons
  harness_capabilities: the 8 archetypes we can actually execute,
                        and the payoff classes the pilot understands
```

That last field matters. Gemini should know **what we can execute**, so its
plan is expressed in things the harness can do — and so it can tell us
explicitly when the deck's best line needs something we lack.

### What Gemini must return

```json
{
  "deck_identity": "<one sentence: how this deck wins>",
  "win_plan": [{
    "step": 1,
    "requires": ["<capability | state predicate | card name>"],
    "action": "<what the pilot does>",
    "produces": ["<capability | state predicate>"],
    "cards": ["<must exist in decklist>"],
    "executable_by_harness": true|false,
    "missing_executor": "<required iff executable_by_harness is false>"
  }],
  "alternate_lines": [ ...same shape... ],
  "play_patterns": [{
    "name": "snake_case",
    "trigger_condition": "<when the pilot should do this>",
    "cards": [...],
    "priority": 1
  }],
  "mulligan_policy": {"keep_if": [...], "ship_if": [...]},
  "early_priorities": ["<card names, turns 1-4>"],
  "threat_profile": "<what makes this deck dangerous, for opponent modelling>",
  "known_weaknesses": [...],
  "unverified_claims": ["<anything drawn from the primer rather than data>"]
}
```

### Constraints enforced in code

1. Every card named exists in the decklist.
2. Every capability referenced exists in the verified inventory.
3. **Chain validation:** step N's `requires` must be satisfied by an earlier
   step's `produces`, by an opening-state predicate, or by a named card in
   the deck. **A dangling precondition rejects the plan.** This is the Urza
   bug — infinite mana with no consumer — as a mechanical check.
4. `executable_by_harness: false` **must** carry `missing_executor`. This is
   how the deck tells us what to build, and it feeds the Step 7 queue.
5. `unverified_claims` must list anything sourced from the primer, keeping
   hint-derived reasoning separable from data-derived reasoning.

---

## Part 4 — Gaps and weaknesses in this approach

Named honestly, because the last two architectures failed on things I had
not written down.

### 1. Reproducibility — the biggest one

An interactive session gives different results run to run. Two ingests of
the same deck could produce different plans, and we would not know which is
better.

*Mitigation:* every artifact records `prompt_version`, `vocabulary_version`,
`model`, and `script_hash`. Re-ingesting an unchanged deck with unchanged
versions must produce **compatible** artifacts; a diff is a regression
signal. Cache by content hash so repeat ingests are free and identical by
construction.

### 2. The human is the bottleneck

If every deck needs Ben's review, this does not reach hundreds of decks.

*Mitigation:* review is required only for NEW vocabulary, disagreements, and
acceptance failures. As the vocabulary converges these approach zero — deck
#200 should need no review at all. **If review volume is not falling with
deck count, the convergence loop is broken and that is the alarm.**

### 3. Vocabulary drift

Independent sessions will propose `free_cast_grant`, `cast_without_paying`,
and `alternative_cost_grant` for the same thing.

*Mitigation:* the vocabulary is supplied on every call, so proposals are
already anchored. Near-duplicate detection at promotion time, and promotion
is centralized rather than per-session. This is a real risk and I do not
think it is fully solved.

### 4. Silent regression on re-ingest

We will re-ingest the same deck many times. Nothing today would notice if a
prompt change made deck #7's plan worse.

*Mitigation:* keep a golden set of decks with known-good artifacts and
known conversion rates. Any prompt or vocabulary change re-runs them, and a
drop in conversion blocks the change. **Without this, the convergence loop
can quietly converge on something worse.**

### 5. Partial failure

If 3 of 75 cards fail analysis, does the deck ship?

*Answer:* yes, with the failures recorded and the deck flagged — EXCEPT that
a failed **commander** or a card named in a combo is fatal. That is the Urza
rule generalized.

### 6. Cost at scale, honestly

First deck: ~70 subagent calls plus one Gemini call. Tenth deck sharing a
staple-heavy list: perhaps 20. Hundredth: single digits. **But the first
tranche is genuinely expensive** and there is no way around it if the answer
is to be correct. Steady state is cheap; the ramp is not.

### 7. Gemini sees only what we paste

Unlike subagents, Gemini cannot verify. If our package has an error, its
plan inherits it silently.

*Mitigation:* Gemini's plan is validated against the same verified inventory
we built the package from, and cross-checked against the per-card pass in
Step 5. It cannot introduce a card or capability that does not exist.

### 8. The acceptance gate may be too strict early on

If prep FAILS whenever the harness cannot execute step 1, most decks will
fail initially — we have 8 archetypes and Magic has thousands of lines.

*Mitigation:* the gate distinguishes **"the plan is incoherent"** (a real
prep failure) from **"the plan is coherent but needs an executor we lack"**
(a successful analysis with a work item). Only the first fails. The second is
exactly the output we want: a prioritized list of executors to build,
derived from real decks rather than guessed.

---

## Part 5 — Why a skill, not a prompt

Consistency and enforcement. A skill pins prompt text, JSON schemas,
validation rules, batch size, the vocabulary snapshot, and the review-queue
mechanics. Without it, deck #1 and deck #40 get different treatment and the
convergence loop is measuring my prompt variance rather than the decks.

The skill should also **refuse to proceed** on schema violations rather than
repairing them quietly — a silently repaired hallucination is the failure
mode this whole design exists to prevent.
