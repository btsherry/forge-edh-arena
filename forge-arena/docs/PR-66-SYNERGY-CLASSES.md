# PR-66 — synergy payoff classes (queued, not built)

Queued while the pr65 batch runs. Comes from the ingestion trial's most
valuable output, which was NOT the combo it found: **31 card pairings that
two independent subagents each named, present in no existing artifact.**

## Why this and not more archetypes

PR-65 bound the combo the trial named (`411-3101`) because it arrived with a
combo ID. Measured result: **distance never reached 0 in 22 games** — two
specific non-tutorable creatures plus the commander is too much assembly to
matter.

The synergies need no assembly. They are cards already doing their job, whose
interaction the pilot cannot see. That is a much better return per unit of
work, and it is what the trial actually argued for.

## The four classes

All deck-agnostic, all detectable from Forge card scripts.

### 1. `self_recurring_permanent`

A permanent whose own trigger repeatedly removes and returns itself.

```
Norin the Wary:
  T:Mode$ SpellCast | ValidCard$ Card | Execute$ TrigExile | TriggerZones$ Battlefield
```

`ValidCard$ Card` means **any player's** spell. In a four-player game with an
ETB payoff on board, this is a trigger on nearly every spell cast at the
table, permanently, from two cards that require no assembly.

*Pilot use:* deploy priority rises sharply when an ETB payoff
(`ping_each_opponent`) is already on the battlefield.

### 2. `opponent_draw_damage`

```
Razorkin Needlehead:
  T:Mode$ Drawn | ValidCard$ Card.OppOwn | Execute$ TrigDamage
```

*Pilot use:* the trigger half of a paired play (below).

### 3. `mass_draw_symmetric`

Wheel effects — every player draws. Wheel of Fortune, Wheel of Misfortune,
Reforge the Soul are all in this one deck.

*Pilot use:* with `opponent_draw_damage` deployed, one wheel is 7 draws x 3
opponents = **21 damage triggers**. This is the paired play, and it maps onto
the EXISTING `PairedPlay` archetype shape — trigger card on battlefield,
enabler cast from hand, fire when the board makes it worth it. Reuse, not new
machinery.

### 4. `damage_amplifier`

```
Torbran:  R:Event$ DamageDone | ValidSource$ Card.RedSource+YouCtrl | ReplaceWith$ DmgPlus...
Solphim:  R:Event$ DamageDone | IsCombat$ False | Replace... (doubles)
```

*Pilot use:* **this changes what counts as lethal**, and is the only one of
the four that alters existing math rather than adding a behaviour. Purphoros
deals 2; with Torbran it is 4; with Solphim as well it is 8 — per trigger,
per opponent. A lethality check that ignores amplifiers under-counts by 4x
here and will decline attacks and drills that are actually lethal.

## Scope discipline

Four payoff classes and one paired-play binding. **No new archetype, no new
executor, no planner.** Each class is a `PayoffRules` entry plus a pilot
consult, in the pattern already used by `ping_each_opponent`.

## How this gets validated

Not by win count alone at n=30 — PR-65 is a fresh reminder that a 30-game
delta is mostly noise. The check is behavioural and directly observable:

1. Does `self_recurring_permanent` change deploy order when a ping payoff is
   out? (telemetry: deploy decisions)
2. Does the wheel paired play fire when Needlehead is deployed? (telemetry:
   `line_step PAIRED_*`)
3. Does the lethality projection include amplifiers? (telemetry: the
   `lethal_alpha` guaranteed-damage figure should quadruple with both
   amplifiers out)

Item 3 is the one worth caring about most: it is a correctness bug in
existing code, not a missing feature.

## The generalization claim, stated so it can be checked

These are not Purphoros-specific. `self_recurring_permanent` covers every
flicker/blink payoff; `opponent_draw_damage` plus `mass_draw_symmetric`
covers every wheels deck — including the Mono Red Big Wheels list Ben has
not yet exported, where I predicted our vocabulary would fail. If that deck
ingests with these classes and its plan comes out coherent, the claim holds.
If it needs four more classes, the vocabulary is still deck-shaped and the
convergence loop is the only fix.
