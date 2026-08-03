# Synergy discovery brief — Selvala, Heart of the Wilds (canary: 10 anchors, ≤50 pairings)

You are a Magic: The Gathering expert analyst. Find the powerful two-or-more-card synergies / play-patterns that the **ANCHOR CARDS** (listed at the end) form with cards in this Commander deck (Selvala, Heart of the Wilds). Output **compilable** records we will turn into game logic and validate in an engine.

## How to think (non-negotiable)
- Reason **holistically, like a rules lawyer**, over the whole deck at once. Do **not** decompose cards into fixed categories/primitives and bucket-match — Magic interactions are text-exact and emergent from the comprehensive rules, and bucketing causes skips. Read the real text and the Forge script, hold the deck in mind, find where an anchor's ability legally combines with other card(s) for a powerful play.
- Keyword overlap is only an **attention hint** — never exclude a card because it didn't match a keyword.
- **The Forge card script is ground truth**, not oracle prose (prose phrasing hides interactions; the script states them exactly).
- **Find chains (3–4 cards), not just pairs.** Follow the interaction wherever it legally leads.
- **Reject false positives** by reasoning the rules: does the anchor's ability *actually profit*, and is every step legal? A legal-but-worthless interaction is a trap — reject it, say why.

## Forge card-script DSL primer (how to read the `.txt` scripts)
**Fast path:** every deck card's EXACT script file path is pre-indexed at
`forge-arena/decks/selvala-heart-of-the-wilds/dossier/card-scripts-index.json`
(a `{name: absolute_path}` map, `cardsfolder_root` given). Read scripts directly
from those paths — do NOT derive filenames or glob the cardsfolder.

- Header: `Name:`, `ManaCost:`, `Types:`, `PT:` (power/toughness), `Oracle:`.
- `A:AB$ <Api> | Cost$ <cost> | ValidTgts$ <restriction> | ...` — an **A**ctivated ability. `AB$` names the effect (`Untap`, `Mana`, `ChangeZone`, `Pump`, `Draw`, `Attach`…). `Cost$` uses symbols: `T`=tap, `Q`=untap, mana like `G`/`2`/`{2}{G}`, `Sac`=sacrifice, `PayLife`, counters, etc. `ValidTgts$` restricts targets (e.g. `Forest`, `Creature.YouCtrl`).
- `S:Mode$ Continuous | Affected$ <...> | Add...` — a **S**tatic ability (e.g. `AddType$ Forest` = the affected permanents *gain* the Forest type; `is a Forest` in prose).
- `T:Mode$ <event> | Execute$ <svar> | ...` — a **T**riggered ability.
- `K:` — a keyword (Hexproof, Trample, Indestructible…). `SVar:` — a named variable/subroutine (e.g. `SVar:X:Count$Valid Creature.YouCtrl`). `AILogic$` — a stock-AI hint (ignore for legality).

## Our execution model (so your output is compilable)
Combos/synergies are executed by **runners** interpreting **compiled program JSON** (`program_class` + `preconditions` + a `loop` or `win_plan` + a `sink/outlet`). Existing runner **shapes**:
- `mana_loop` — a producer taps for mana; an untapper-chain re-readies it each cycle; net-positive → bank → force-cast an outlet. Fields: `producer{card,activate_cost}`, `untap_sequence:[{card,cost,target}]`, `cycle_cost`, `yield_model`, `min_net`.
- `bounce_recur` — an activated bounce returns a value creature; recast fires an ETB payoff each cycle.
- `pairing` — a board wipe + an instant shield that covers its scope.
- (there is no runner yet for a *pump-loop → power-payoff*, or several other shapes — if a synergy needs a mechanism no existing shape covers, set `shape_is_new: true` and describe the shape.)
A **combo is DATA over a shape**; a genuinely new mechanism is a **new runner**. Tag every record with the shape it compiles to.

## Test-harness format (so your proposed test is runnable)
We fixture a board by putting named cards into play (`moveToPlay`), clearing summoning sickness (`setSickness(false)`), and attaching equipment/auras (`attachToEntity`); then we measure the mana pool, total board power, opponent life, and program events, and assert the expected delta. Your `engine_test` must name the exact cards+zones to set up, the activations to perform, the measurable outcome that confirms it, and the condition that would refute it.

## External research (inference HELPERS, never hard filters — must never make you skip a deck card)
- Web-search real discussion (Reddit/forums/primers/articles) of the anchors' and Selvala's synergies; capture concrete play lines + sources.
- EDHREC co-occurrence: `curl -sS -A "Mozilla/5.0" https://json.edhrec.com/pages/cards/<slug>.json` — `num_decks` is a faint "played together" sniff only (staple-dominated; NOT functional synergy).
- Scryfall: `https://api.scryfall.com/cards/search?q=...` with `otag:` function tags / `oracle:` search to sniff mechanically-related cards.

## Output — a JSON array, one record per synergy, EACH with the compilable fields:
```
{
  "anchor": "<one of the anchor cards>",
  "partner_cards": ["..."],
  "n_cards": 2,
  "program_class": "mana_loop|bounce_recur|pairing|ramp_sequence|protection|win_plan|other",
  "shape_is_new": false,
  "pieces": [{"card":"", "role":"producer|untapper|payoff|enabler|outlet|protection", "forge_cost":"{3}", "target":""}],
  "loop": {"activate_cost":"", "untap_sequence":[{"card":"","cost":"","target":""}], "cycle_cost":0, "yield_model":"", "min_net":0},
  "win_plan_steps": ["ordered steps, if a win-con rather than a loop"],
  "preconditions": [{"check":"on_battlefield|attached|not_summoning_sick","card":"","host":""}],
  "mechanism": "one-sentence, rules-exact why it works (cite CR where subtle)",
  "produces": "mana|board|damage|cards|protection|win",
  "magnitude": "",
  "win_relevance": "which of the deck's win-conditions/plans this fuels",
  "novelty_vs_dossier": "new|already-known (check decks/selvala-heart-of-the-wilds/dossier/{advisory-combos,discovered-synergies,combos}.json)",
  "confidence": "high|med|low",
  "false_positive_check": "",
  "engine_test": {"fixture":[{"card":"","zone":"battlefield|hand","attach_to":""}], "activate":["ordered activations"], "expect_measurable":"e.g. +3 green mana vs baseline", "reject_if":""},
  "compile_rank": 0.0
}
```
Set `compile_rank` in [0,1] = win_relevance × magnitude × novelty × confidence (win-plans over ramp, infinite over incremental, new-in-dossier over known, rules-solid over speculative). We will compile+test the highest-ranked first.

## Scope / caps for THIS canary run
- Anchor only on the 10 cards listed below (partners may be any deck card).
- Emit **at most 50 records total**, the 50 highest `compile_rank`. If you find more, keep the best 50 and note in the coverage line how many you dropped.
- End with a one-paragraph COVERAGE NOTE: which anchors were richest, roughly how many candidates you considered per anchor, and any anchor with no real synergy (say why).
