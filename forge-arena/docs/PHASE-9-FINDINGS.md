# Phase 9 ingestion — results across all four decks

341 cards, 7 subagents, four decks. Enforcement verified independently:
**0 capabilities outside vocabulary, 0 fabricated script_evidence, 0
out-of-decklist interactions.**

## Cross-deck recurrence — the promotion signal

49 of 142 proposals recurred across independent agents that could not see
each other:

| decks | class |
|---|---|
| 7 | `graveyard_recursion` |
| 6 | `counterspell` |
| 5 | `protection_grant`, `mass_indestructible_grant`, `p1p1_counter_placer` |
| 4 | `spell_copy`, `ai_removedeck_flag`, `modal_dfc_land` |
| 3 | `spell_uncounterable_static`, `mana_amplifier_aura`, `does_not_untap`, ... |

93 singletons are what pruning is for. **Only 1 class currently clears the
3-DISTINCT-DECK bar**, because most proposals are still deck-shaped — the
vocabulary needs canonicalization before promotion means anything.

## Findings that change behaviour

### Giada — the wipe/protect pairing, resolved from scripts

| card | actual scope | verdict |
|---|---|---|
| Avacyn | `Permanent.Other+YouCtrl` — lands included | makes Armageddon one-sided |
| Teferi's Protection | `Permanent.YouCtrl` phased | makes Armageddon one-sided |
| Clever Concealment | `Permanent.nonLand+YouCtrl` | does NOT protect lands |
| Emeria's Call | `Creature.nonAngel+YouCtrl` | protects nothing in an ANGEL deck |
| Farewell | exiles, not destroys | cannot pair with Avacyn at all |

Independently reproduces the PR-52 bug (Clever Concealment's "nonland
permanents you control" contains "permanents you control" as a substring)
and adds a trap I had not found (Emeria's Call).

**The wipes may never have been castable at all**: Ravages of War, Ondu
Inversion and Vanquish the Horde use `SP$ DestroyAll | ValidCards$` with NO
`ValidTgts`, so bound to `targeted_removal` "the executor resolves a target
list that does not exist and the cast is abandoned."

**Giada's registered combo cannot loop as modelled.** Heliod/Ballista needs
`lifelink_grant` (Heliod's `AB$ Pump | KW$ Lifelink` — as plain `pump` the
loop gains no life and aborts), `lifegain_trigger` (`T:Mode$ LifeGained`),
and `p1p1_counter_placer` (Ballista's ammunition; `pump` models it as
expiring).

### Selvala — the phase-boundary problem

**Omnath, Locus of Mana** carries `S:Mode$ UnspentMana` (green survives
phase ends). Her plan is float mana in a main phase and win in combat —
**mana empties at phase end**, so Omnath is what makes the line legal, and
we model neither him nor the constraint.

Also on her critical path: Umbral Mantle's `Cost$ 3 Q` is an untap COST not
an effect, and its ability lives on the equipped creature via `AddAbility$`;
Castle Garenbrig's mana is legal for CREATURE abilities (covers the Mantle,
not Staff of Domination); Lightning Greaves grants Shroud, so equipping the
Mantle afterwards is ILLEGAL — a sequencing trap that locks the pilot out of
its own combo.

### Urza — mana that cannot pay for the engine

**Mishra's Workshop** (`RestrictValid$ Spell.Artifact`) and **Throne of
Eldraine** (`RestrictValid$ Spell.ChosenColor+MonoColor`) both produce mana
that **cannot pay Urza's `{5}`**. Tagged `mana_ability_big` they silently
overstate combo-turn mana.

**Power Artifact / Forensic Gadgeteer** reduce ABILITY costs, not spell
costs, and `MinMana$ 1` matters: Basalt Monolith's `{3}` untap becomes `{2}`
against a 3-mana tap (infinite), but Grim Monolith's `{4}` becomes `{3}`
(net zero, NOT infinite).

### Wrong-capability traps avoided

Static Orb and Winter Orb are not `untap` — they invert it. Swan Song is not
`token_maker` (the Bird goes to the opponent). Chrome Mox / Isochron Scepter
/ Manifold Key contain `DB$ Pump` as `ForgetImprinted$` bookkeeping, not P/T.
Emeria's Call and Kabira Takedown were t0-tagged `mana_ability`, which would
have the executor tap an instant for mana.

## Corrections to my own claims, from checking rather than assuming

- **`AI:RemoveDeck:All` is a `-10` priority penalty, not a ban.** 31 cards
  carry it across the four decks. It does NOT explain PR-65's failure:
  Grinning Ignus reached hand 7 times and the battlefield 4 times. The combo
  failed on plain draw variance — 38 of 74 observations had neither piece on
  board.
- **My extractor had two copies** and the package builder imported the
  unfixed one, so all three new decks carry the `SP$`/`AB$` bug I had already
  fixed. Three independent agents flagged it. Synced.
- **`is_commander` was false on Giada** — I only wired the flag for the
  Purphoros package. Flawless Maneuver and Akroma's Will both key off it.
