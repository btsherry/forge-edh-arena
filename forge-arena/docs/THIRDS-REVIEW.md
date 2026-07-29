# Thirds review — role redundancy across the nine compiled combo programs

PR-chi, task 2. For every live program, the question a batch cannot answer on
its own: **which OTHER cards in the deck could satisfy each program role**, so
the combo fires from more board states than the one the compiler happened to
name. Every claim below cites the actual Forge script
(`forge-gui/res/cardsfolder`, read only) — oracle prose has burned this
project too many times to be evidence on its own.

Decks reviewed: `decks/urza-lord-high-artificer.dck`,
`decks/giada-font-of-hope.dck`. Programs reviewed: the six that were live
before PR-chi (two Giada ping_loops, four Urza mana_loops) plus the three
Tidespout cast_bounce programs PR-chi brings up.

Verdict shorthand: **QUALIFIES** (recommend adding to the role /
resolve_from list), **NEEDS RUNNER WORK** (real third, blocked on a known
extension), **DISQUALIFIED** (looks like a third, script says no).

---

## Giada, Font of Hope

### 1. `1274-3693` — Heliod, Sun-Crowned + Walking Ballista (ping_loop)

Roles: **engine** (lifegain → targeted +1/+1 counter), **outlet** (repeatable
damage that spends and recovers counters), plus the per-turn **lifelink
grant** Heliod's activated ability provides.

- **Engine thirds (lifegain → counter on the OUTLET):**
  - *Archangel of Thune* — already compiled as program 2919-3693's engine
    (`PutCounterAll`, untargeted). The deck's only other engine.
  - *Exemplar of Light* — **DISQUALIFIED.** Script:
    `T:Mode$ LifeGained ... Execute$ TrigPutCounter` puts the counter **"on
    this creature"** (self only, no target). It can never re-ammo Ballista;
    it is a synergy body, not a combo piece.
- **Lifelink-granter thirds (the role 2919-3693 compile-resolved to
  Heliod):**
  - *Akroma's Will* — **NEEDS RUNNER WORK.** Script: `SP$ Charm` with mode
    `DBLife` = "creatures you control gain lifelink, indestructible, and
    protection from each color until end of turn". A real, self-contained
    granter (already identified in PR-zeta and left uncompiled), but it is
    (a) a CAST-type grant — the runner's per_turn grant path resolves
    battlefield activated abilities only — and (b) a Charm whose mode the
    AI picks, the same mode-control backlog class as Final Showdown. Both
    extensions are already queued; this card is the payoff for building
    them. No JSON change is possible until then.
  - *Resplendent Angel* — **DISQUALIFIED.** `A:AB$ Pump | Cost$ 3 W W W |
    Defined$ Self | KW$ Lifelink` — grants lifelink to **itself only**;
    it can never put lifelink on Ballista.
  - *Lyra Dawnbringer* — **DISQUALIFIED.** `S: Affected$
    Angel.Other+YouCtrl | AddKeyword$ Lifelink` — Angels only; Walking
    Ballista is a Construct.
  - *Righteous Valkyrie, Serra Paragon, Conjurer's Mantle* — scripts show
    lifegain triggers / recursion / vigilance respectively; none grants
    lifelink to another creature. Not thirds.
- **Outlet thirds:** none. No other permanent in the deck converts counters
  into repeatable targeted damage. Walking Ballista is 1-deep, which is why
  the tutor weights already treat it as they do.

**Recommendation:** no addable role cards exist in-deck today. The highest-
value move for BOTH Giada programs is the cast-type grant extension (with
charm-mode control), which converts Akroma's Will from a flagged aside into
a second granter — that is a runner PR, not a JSON edit.

### 2. `2919-3693` — Archangel of Thune + Walking Ballista (+ Heliod granter)

Same three roles; the granter is the compile-resolved piece.

- **Granter thirds:** identical analysis to above — *Akroma's Will* only,
  NEEDS RUNNER WORK. Nothing else in the deck grants lifelink to a chosen
  non-Angel creature (scripts checked: Lyra, Resplendent Angel, Righteous
  Valkyrie, Gisela — Gisela has native lifelink, grants nothing).
- **Engine thirds:** *Heliod himself* is the reverse pairing (compiled as
  1274-3693) — the two programs already cover both orderings.
- **Recommendation:** none addable; same runner-extension dependency.

---

## Urza, Lord High Artificer — mana_loop family

Shared roles: **engine** (tap-for-N artifact with a scripted self-untap
cost), **reducer** (makes untap cheaper than the tap's yield), **sink**
(repeatable pool spender; Urza's `{5}`).

### 3. `4131-5149` — Power Artifact + Basalt Monolith
### 4. `4131-5390` — Basalt Monolith + Forensic Gadgeteer
### 5. `2585-5149` — Power Artifact + Grim Monolith

- **Engine thirds:** the deck's complete set of self-untapping tap-rocks is
  Basalt Monolith (`A: Mana T, Amount$ 3` + `A: Untap Cost$ 3`) and Grim
  Monolith (`Amount$ 3` + `Untap Cost$ 4`) — both already compiled. *Mana
  Vault* looks like a third but is **DISQUALIFIED for mana_loop**: its
  untap is an upkeep trigger (`T:Mode$ Phase | Phase$ Upkeep ... Cost$ 4`),
  not an activated ability — there is no in-phase untap to loop. (It IS a
  cast_bounce rock; see below — the bounce is its untap.)
- **Reducer thirds:** the deck's ability-cost reducers are exactly the two
  compiled ones — Power Artifact (`ReduceCost Type$ Ability | Amount$ 2 |
  MinMana$ 1`) and Forensic Gadgeteer (`ReduceCost Type$ Ability | Amount$
  1 | MinMana$ 1`, artifacts you control). *Etherium Sculptor*, *Foundry
  Inspector*, *Cloud Key*, *Sapphire Medallion* are all **DISQUALIFIED**
  for this role: every one is `ReduceCost ... Type$ Spell` — they discount
  CASTS, not activated abilities, so Basalt's `{3}` untap never gets
  cheaper. (They matter to the cast_bounce family instead — see below.)
  - Missing pair, correctly absent: **Grim + Gadgeteer alone nets zero**
    ({4} untap − {1} = {3} paid vs {C}{C}{C} produced) — do not compile it.
  - Stacking note: with BOTH reducers out, Grim's untap is {4}−2−1 → {1}
    (MinMana 1) and 2585-5149's measured net rises from +1 to +2 per pair;
    the runner's `expected_net_per_pair` is a floor, so this already works
    unmodified.
- **Sink thirds:** none repeatable. *Fomori Vault* (`Cost$ 3 T Discard<1>`)
  taps itself — once per turn, not a loop sink. *Rings of Brighthearth*
  (`AbilityCast ... pay {2}, copy that ability`) could double each Urza
  sink activation ({2} buys a second exile) — a real future upgrade, but it
  is an optional trigger with its own payment decision, not a role slot in
  the current schema. Urza's `{5}` stays the only sink; that is a fact of
  the deck, not a compiler miss.
- **Doc lint found during review:** `combo-program-2585-5149.json`
  `pieces[1]` still reads `"attach_to": "Basalt Monolith"` / "attached to
  Basalt Monolith" — stale prose from the clone. The parts the runner
  actually reads (`setup[].target`, `preconditions.attached.host`) all
  correctly say Grim Monolith, so behavior is right; the prose should be
  fixed on the next JSON touch.

### 6. `4821-5261` — Isochron Scepter + Dramatic Reversal (float_then_copy)

- **Engine/imprint thirds:** no other repeatable-copy engine or untap
  instant in deck (*Nexus of Fate* and bounce lines were explicitly scoped
  out as non-engine exit states by Ben in PR-mu). *Lithoform Engine* can
  copy an activated ability per turn but is not an imprint engine.
- **The real third is the secondary requirement**, `artifact_mana_
  production_at_least 3`: every rock counts toward it, so the fodder adds
  recommended below (Lotus Petal — `A: Mana | Cost$ T Sac<1>` scores as a
  one-shot float; Welding Jar has no mana ability and scores 0) also widen
  THIS program's entry, for free.
- **Recommendation:** no role-list change.

---

## Urza — Tidespout cast_bounce family (PR-chi: 542-5034, 542-2364, 542-2585)

Roles: **engine** (per-cast bounce trigger), **rock** (tap yield strictly
above recast cost), **fodder** (the zero_cost_artifact template,
`resolve_from` = Mox Amber / Chrome Mox / Mox Opal today), **outlet**
(Aetherflux Reservoir, deploy-or-defer).

### Engine thirds

- **Hullbreaker Horror** — **NEEDS RUNNER WORK, real third.** Script:
  `T:Mode$ SpellCast ... Execute$ TrigCharm`; oracle modes: "return target
  spell you don't control" / "**return target nonland permanent**" — mode 2
  CAN target our own rock/fodder, so every 542-* program has a 513-*
  sibling (the legacy binding family PR-61 already enumerated:
  513-5034, 513-2364, 513-3682). The blocker is that the trigger is a
  **Charm**: the obligation seam sets targets, but the MODE choice runs
  through `CharmEffect.makeChoices` — the same mode-control backlog as
  Akroma's Will and Final Showdown. Compile the 513 clones the day that
  lands; JSON-only, per the PR-sigma precedent.

### Rock thirds (tap yield > recast cost, enters untapped)

- **Mox Amber as ROCK, combo `542-3682`** — **QUALIFIES; compile it.**
  Script: `A:AB$ ManaReflected | Cost$ T | Valid$ Creature.Legendary+
  YouCtrl,Planeswalker.Legendary+YouCtrl` — with Urza (legendary, blue) on
  the battlefield it taps for {U}; ManaCost:0 so the recast is free. Net +1
  per iteration and the loop needs ZERO mana to start — the cheapest entry
  in the whole family, and the combo is already in `combos.json`
  (popularity 12522) with a legacy CastBounceManaLoop binding that the
  one-path rule retires on compile. Precondition to encode: a colored
  legendary creature/planeswalker we control (Urza suffices; Emry, Drafna,
  Arcum, Tezzeret also satisfy it). Fodder resolves from the same template
  minus Mox Amber itself.
- *Arcane Signet, Thought Vessel* — **DISQUALIFIED**: tap 1, recast {2} —
  net negative.
- *Everflowing Chalice as rock* — **DISQUALIFIED**: uncounted at X=0 it
  taps for 0; kicked it costs mana. No positive configuration.

### Fodder thirds (the zero_cost_artifact template — the review's main ask)

Deck's full {0}-cost artifact set: Mox Amber, Chrome Mox, Mox Opal,
Mox Diamond, Lotus Petal, Welding Jar, Everflowing Chalice (base {0}).

- **Lotus Petal** — **QUALIFIES, add to resolve_from.** Script: one
  activated ability (`Cost$ T Sac<1/CARDNAME>`), **no ETB trigger, no
  replacement effect** — as fodder it is never activated, just cast and
  bounced. Clean.
- **Welding Jar** — **QUALIFIES, add to resolve_from.** Script: one
  activated ability (`Sac<1/CARDNAME>: Regenerate target artifact`), no
  ETB, no replacement. Bonus while it sits: a free regeneration shield for
  the rock or the outlet against artifact destruction.
- **Mox Opal** — already listed; fine. Metalcraft only gates its MANA
  ability (`Activation$ Metalcraft`), which the fodder role never uses.
- **Chrome Mox** — **demote to LAST in resolve_from** (currently second).
  Script: `T:Mode$ ChangesZone ... OptionalDecider$ You | Execute$
  TrigExile` — every recast re-asks the imprint "may", and the decision is
  stock's (`confirmAction` falls through while a program is live for
  non-hinted triggers). If stock ever answers yes, each iteration exiles a
  nonartifact, nonland card from HAND — undeclared self-consumption that
  the program schema says is "none". A measured hand-drain has not been
  observed yet, but the safe order costs nothing: Mox Amber, Lotus Petal,
  Welding Jar, Mox Opal, Chrome Mox.
- **Mox Diamond** — **DISQUALIFIED.** Script: `R:Event$ Moved |
  Destination$ Battlefield ... discard a land card instead ... If you
  don't, put it into its owner's graveyard` — every recast either eats a
  land from hand or the fodder dies mid-loop (which the runner correctly
  aborts as `fodder_never_resolved`). Structurally self-consuming.
- **Everflowing Chalice** — **DISQUALIFIED.** Script: `K:Multikicker:2`.
  The kick decision at cast is stock's, and PR-pi measured stock kicking
  greedily (the Multikicker heist ate a 180-mana bank). Any kick moves the
  pool and the runner's fodder spend-proof aborts — correctly, because a
  kicked "free" cast is spending the loop's bank.
- **Mishra's Bauble-class (not in deck; asked explicitly):** the script
  (`A:AB$ PeekAndReveal | Cost$ T Sac<1/CARDNAME>`, no ETB trigger, no
  replacement, `AI:RemoveDeck:All` is deck-construction advice only) makes
  it exactly a Lotus-Petal-class fodder: castable for {0}, sits inert,
  bounces clean. **The class qualifies for the template** — and under
  Urza's static every such artifact is also a tap-for-{U} rock, so if the
  deck ever adds Bauble/Ornithopter/Memnite-class cards, they slot straight
  into `resolve_from` with no runner change.

### Outlet third

- None: Aetherflux Reservoir (`A:AB$ DealDamage | Cost$ PayLife<50> |
  NumDmg$ 50`) is the deck's only storm-count kill. The One Ring gains no
  life; nothing else converts a storm turn into a table kill without a
  library playout. The deploy-or-defer gate on Aetherflux is therefore
  correct — there is genuinely nothing else to close with.

### Cast-reducer interaction (why the runner's spend-proof is bounded)

*Etherium Sculptor*, *Foundry Inspector* (both `ReduceCost | ValidCard$
Artifact | Type$ Spell | Amount$ 1`) and *Cloud Key* (chosen type) discount
every rock RECAST at payment — Sol Ring's {1} recast becomes {0} (net +2
per iteration), Grim's {2} becomes {1}. The CastBounceRunner's recast
spend-proof accepts any measured spend in `[0, recast_cost]` for exactly
this reason: a discount is legal and favorable, while a spend ABOVE the
declared cost (an opponent's tax) breaks the declared net math and aborts.
These three cards are entry accelerants for the whole family, not roles.

---

## Recommended changes, ranked

1. **JSON-only, now:** add Lotus Petal and Welding Jar to `resolve_from`
   in all three cast_bounce programs; move Chrome Mox to last. (Order:
   Mox Amber, Lotus Petal, Welding Jar, Mox Opal, Chrome Mox.)
2. **JSON-only, next compile session:** program for `542-3682`
   (Tidespout + Mox Amber as rock) — cheapest entry, zero mana to start,
   legendary-source precondition, retires its legacy binding.
3. **Runner extension (queued class, two decks pay for it):** charm
   mode-control at the trigger seam — unlocks Akroma's Will as Giada's
   second granter AND the entire Hullbreaker 513-* cast_bounce family.
4. **Prose lint:** fix `combo-program-2585-5149.json` pieces[1]
   attach_to/requires text (says Basalt, means Grim; runner-read fields are
   correct).

Items 1–2 raise fire rates with zero code. Item 3 is the single extension
with the largest combined coverage gain across both decks.
