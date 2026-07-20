# Ingestion trial — Purphoros v2, first hand-run of the new pattern

First end-to-end run of the workflow from `INGESTION-SPEC.md`, executed by
hand because six of its eight components are still design-only. 78 unique
cards, 8 Claude subagents in parallel, one Gemini synthesis call.

## The pass criterion, and the result

> Does the pipeline independently surface something our current prep cannot?

**Yes.** Gemini reconstructed the **Grinning Ignus + Runaway Steam-Kin +
Purphoros** line from card scripts:

1. Deploy Purphoros and Runaway Steam-Kin; cast red spells until Steam-Kin
   holds three counters.
2. Remove three counters for `{R}{R}{R}`; cast Grinning Ignus `{2}{R}`;
   self-bounce for `{C}{C}{R}`. Every red cast re-adds a Steam-Kin counter,
   making the cycle mana-neutral.
3. Each Ignus re-entry is a creature ETB, so Purphoros pings every opponent
   for 2. Repeat until the table is dead.

That is **combo `411-3101`, which was NOT in our binding library.** Our prep
had detected it and left it unbound; the pipeline not only found it but
described the executable line.

The chain validates cleanly — step 1 produces `ignus_loop_ready`, step 2
consumes it and produces `infinite_etb`, step 3 consumes that and produces
`opponents_eliminated`. **No dangling precondition**, which is the check
that would have caught the Urza failure.

## The over-claim the design is built to catch

Gemini marked step 2 `executable_by_harness: true` via `CastBounceManaLoop`.
**That is wrong.** The archetype requires a separate `bouncer` and `rock`;
Grinning Ignus is `Cost$ R Return<1/CARDNAME>` — it bounces itself. There is
no second card.

So T3 was right about the Magic and wrong about our engineering — precisely
the split the tier hierarchy predicts, and precisely why executability must
be **sim-verified rather than asserted**. Step 6 of the spec exists for this.

It also yields the work item we wanted: **a self-bounce variant of the
cast-bounce archetype**, derived from a real deck rather than guessed at.

## Enforcement held (verified independently, not self-reported)

| constraint | violations |
|---|---|
| capabilities outside supplied vocabulary | **0** |
| `script_evidence` not a literal substring of the script | **0** |
| `notable_interactions` outside the decklist | **0** |
| `uncertain: true` (permitted) | 20 |

Every subagent validated its own output before writing, then I re-validated
all 78 records independently. The constraints were followed as *design*, not
merely requested.

## The finding that needs a design change: vocabulary drift

**36 distinct proposals across 42, and 19 of them collide — from ONE deck in
ONE run.**

| collision | proposed on |
|---|---|
| `cost_reduction_self` / `self_cost_reduction` / `spell_cost_reduction` | three different cards |
| `permanent_removal` / `targeted_permanent_destroy` | Vandalblast / Wild Magic Surge |
| `conditional_mana_ability` / `restricted_mana_ability` / `self_bounce_mana_ability` | Sceptre / Throne / Ignus |
| `combat_damage_trigger` / `combat_damage_to_player_trigger` | Goldlust Triad / Ragavan |

The convergence loop assumed drift *across* decks and is defeated by drift
*within* one: parallel agents cannot see each other's proposals, so three
names for one concept each collect a single vote and **none ever reaches the
promotion threshold of three distinct decks.**

**Required fix:** a canonicalization pass between proposal and promotion —
cluster near-duplicates, pick a canonical name, re-map. Deterministic
clustering plus one adjudication call. This was listed as weakness #3 in the
spec with the note "I do not think it is fully solved"; it is now measured
rather than suspected.

## Bugs the subagents found in MY code

The most valuable unplanned result: the T3 pass audited T0 and won.

- **Deck size wrong.** The package builder drops quantities — `8 Mountain`
  became one entry, so it counted 80 lines against a true deck of **100
  cards**. Every count in this run is affected.
- **MDFC / Adventure names unresolvable.** 7 cards had no script. The pattern
  is `frontname_backname.txt` (`virtue_of_courage_embereth_blaze.txt`). One
  subagent escalated Virtue of Courage as possibly missing from the build;
  it is present, and my normalization was at fault — the hedge was correct
  and checking it was correct.
- **`PayLife` matched anywhere in a script.** Terror of the Peaks was tagged
  `life_cost_ability`, but its `PayLife<3>` belongs to a `RaiseCost` static
  with `Activator$ Player.Opponent` — it **taxes opponents**, it does not
  cost us life.
- **`A:` prefix did not distinguish `SP$` from `AB$`.** Sorceries and
  instants were tagged `has_activated_ability`. One subagent noted that
  tagging Grinning Ignus `mana_ability` "would imply a false infinite-mana
  loop" — **the extractor would have invented a phantom combo.**

T0 is only as trustworthy as its extractor. The tier hierarchy still holds —
the script is ground truth — but "parse of the script" is not the same thing
as "the script", and the T3 pass turns out to be a useful audit of that gap.

## Cost

8 subagent calls (~45k tokens each) plus one Gemini call, for 78 unique
cards. Under the global cache this is a one-time cost per card across all
future decks.

## Artifacts produced

Four new per-deck artifacts beyond the standard prep set:

- `capability-inventory.json` — T0 and T3 capabilities per card, provenance kept separate
- `win-plan.json` — the chained plan, flagged `executability_UNVERIFIED`
- `proposed-vocabulary.json` — 36 provisional classes with script evidence and the collision warning
- `ingestion-report.json` — coverage, enforcement results, and **prep's own list of known defects**

That last one is the point of the whole redesign: a prep run that reports
what it could not do instead of `"pass": true`.
