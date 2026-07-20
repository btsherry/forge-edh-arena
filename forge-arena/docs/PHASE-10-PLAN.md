# Phase 10 — fix deck behaviour

Grounded in three sources that until now were never combined: the **card
scripts** (T0 ground truth), the **strategy primers** (on disk since 17 July,
read by nothing), and the **341-card ingestion pass**. Reviewed adversarially.

Baseline, deterministic harness, 27 games: **purphoros 8, giada 9, selvala 0,
urza 0.**

## Priority, corrected by review

I originally ranked Giada first. That was wrong, and the reason is worth
stating: **Giada is our second-best deck at 9/27 and Selvala and Urza win
nothing.** Ranking the working deck first is a misallocation, and the review
called it.

| rank | deck | why |
|---|---|---|
| 1 | **Selvala 0/27** | the ontology is missing her win conditions AND asserts an illegal game rule |
| 2 | **Urza 0/27** | I proposed nothing for a deck at zero — the sharpest criticism of my draft |
| 3 | **Purphoros 8/27** | a pure arithmetic bug that silently declines lethal lines |
| 4 | ~~Giada 9/27~~ | **DEFERRED.** Already winning; MLD heuristics are a rabbit hole |

---

## PR-A — Selvala: the payoff class and the phase rule

Two separate defects, both fatal on their own.

**1. We have no class for her actual payoffs.** The primer says infinite mana
"dumps the library via Greater Good, Genesis Wave, or Finale of Devastation".
Our conversion planner's outlet classes are `x_drain_each_opponent` and
`self_draw_engine` — **neither matches any of those.** So a seat with a
thousand floating mana has nothing it recognises to spend it on.

New class `x_spell_outlet`: a spell whose X consumes arbitrary mana and
converts it to board or cards.

**2. We assert an illegal rule.** Mana empties at end of phase. Our shortcut
injects a pool and the pilot may try to spend it in a later phase — which
Forge refuses. Omnath's `S:Mode$ UnspentMana` is precisely what makes
"float in main, win in combat" legal, and we model neither him nor the
constraint.

Rule: **a banked pool must be spent in the phase it was created**, unless an
`unspent_mana_grant` permanent is on the battlefield.

*Review confirmed this simplification is free:* Genesis Wave, Finale, and
Greater Good are **sorceries**. They cannot be cast in combat anyway, so
forbidding cross-phase floating forbids nothing the payoffs could have done.
It only bans generating mana in combat and spending it post-combat.

## PR-B — Urza: mana that cannot pay for the engine

Proposed because the review correctly pointed out I had offered **nothing**
for a deck at 0/27.

Three findings from the ingestion pass, all unmodelled:

- **`free_cast_grant`** — Urza's `{5}` (`MayPlayWithoutManaCost$ True`) is a
  repeatable free-cast engine and the bridge from infinite mana to the
  Aetherflux payoff. Prep tags him only `commander_creature`.
- **Restricted mana is counted as general mana.** Mishra's Workshop
  (`RestrictValid$ Spell.Artifact`) and Throne of Eldraine
  (`RestrictValid$ Spell.ChosenColor+MonoColor`) produce mana that **cannot
  pay Urza's `{5}`**. Tagged `mana_ability_big`, they overstate combo-turn
  mana — the pilot believes it can activate when it cannot.
- **Ability-cost reduction is not spell-cost reduction.** Power Artifact and
  Forensic Gadgeteer carry `Type$ Ability`. `MinMana$ 1` is load-bearing:
  Basalt Monolith's `{3}` untap becomes `{2}` against a 3-mana tap
  (infinite), Grim Monolith's `{4}` becomes `{3}` (net zero, **not**
  infinite).

New classes: `free_cast_grant`, `restricted_mana_ability` (carrying the
restriction), `ability_cost_reducer` (distinct from `cost_reducer`).

## PR-C — Purphoros: amplifier-aware lethality

The primer makes these central, not incidental: *"Damage amplifiers turn
modest token waves into table-wide kills… Torbran / Twinflame Tyrant / Ojer
Axonil stack so each ETB deals lethal table damage."* Our lethality check
counts none of them and under-projects by up to 4x, declining attacks and
drill activations that are genuinely lethal.

New class `damage_amplifier`, carrying kind: `ADDITIVE +N` (Torbran) or
`MULTIPLICATIVE xN` (Solphim, Twinflame Tyrant).

### Composition order — the review's most valuable correction

Order changes the result, and **the affected player chooses it**:

```
additive first        (2+2) x 2 = 8
multiplicative first  (2x2) + 2 = 6
```

The opponent picks the order that keeps them alive, so **the projection must
apply MULTIPLIERS FIRST, THEN ADDITIONS** and claim 6, never 8.

Assuming 8 is exactly the Phase 7 failure repeating: attack on a projection
the opponent can invalidate, they survive at 2, and we are tapped out. **A
lethality projection must never over-claim.**

## PR-D — Prep-time pruning (from the review)

Stop handing the runtime garbage and expecting it to cope.

**If a card's protective or beneficial scope explicitly EXCLUDES the deck's
own primary creature type or permanent class, do not bind it.** Emeria's Call
grants indestructible to `Creature.nonAngel+YouCtrl` — in an Angel deck it
protects nothing, and no runtime cleverness recovers from being told it does.

Deck-agnostic: the rule compares a scope against the deck's own composition,
with no card names.

## PR-E — Graceful abort on engine rejection (from the review)

The Giada finding — `SP$ DestroyAll` bound to `targeted_removal` makes the
executor build a target list that does not exist, and the cast is abandoned —
exposes an execution-layer gap, not just a classification one.

**When Forge rejects a scripted action, the pilot must record the rejection
and not retry the same action in the same state.** Otherwise a
misclassification becomes an infinite retry loop that consumes every priority
window. This is cheap and protects against every future misclassification,
not merely the ones we know about.

## Deferred: Giada's sweepers, and why

The review's argument, accepted: she is our **best-performing deck**, and MLD
heuristics are high-risk. A "winning board" gate is a proxy trap — total
power ignores a deathtouch blocker, permanent count ignores card quality, and
life totals say nothing about board presence. Getting it slightly wrong makes
Giada Armageddon from behind and lock herself out.

**If we do build it later, the gate must be the ASYMMETRY GATE, not a board
score:** only cast a mass land wipe when a land-covering protection scope is
already active. That is deterministic and measurable. Avacyn
(`Permanent.Other+YouCtrl`) and Teferi's Protection cover lands; Clever
Concealment (`Permanent.nonLand+YouCtrl`) does not. If parity cannot be
broken deterministically, do not cast the wipe.

## Validation

Not win-count alone at n=30 — the harness still diverges ~10% and small
deltas are noise. Each PR carries a directly observable check:

- **A**: does a banked pool get spent in-phase on an `x_spell_outlet`?
- **B**: does the pilot stop counting Workshop mana toward Urza's `{5}`?
- **C**: does `lethal_alpha`'s guaranteed damage rise (to the *conservative*
  composition) with amplifiers out?
- **D**: is Emeria's Call absent from Giada's bound artifacts?
- **E**: does a rejected cast appear once rather than every window?

Exit bar, deliberately modest: **Selvala or Urza above zero**, and Purphoros
not below 8.
