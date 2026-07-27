# Combo Ingestion Landscape — Research Report

**Date:** 2026-07-27
**Method:** Multi-source research with 3-vote adversarial verification per claim. 21 claims survived; 4 were refuted and are listed at the end for transparency. All surviving claims were verified against primary sources (live API calls, upstream source code, published papers).

**Scope — four questions:**
1. Commander Spellbook's full data model at API depth (produces/requires FEATURE graph, resolving a combo's "amorphous third thing").
2. How other projects play Magic programmatically (Forge upstream AI, XMage AI, RL/MCTS research) — multi-step lines, loops, win detection, and what failed.
3. Combo ingestion (turning combo databases into executable plans) anywhere in the ecosystem.
4. Win-state/conversion modeling ("I have infinite X, now win").

---

## Executive summary

Commander Spellbook is the only machine-readable combo database in the ecosystem, and its backend (public REST API, MIT-licensed Django source) exposes exactly the graph we need: each combo variant carries machine-readable `uses` (cards + zones + states), `requires` (generic Scryfall-query templates — the "amorphous third thing" as a first-class object), and `produces` (typed feature objects), with server-side `result:` queries closing the combo→feature→combo chain. The one hard gap is that **step sequences are numbered English prose**, so compilation to our program JSON requires a constrained NL-parsing pass validated by replay in Forge. Every engine and research AI examined — Forge's GameSimulator (depth-3 cap, terminal-only win scoring), XMage's minimax (depth ~4, loops actively suppressed as a freeze-failure mode), MCTS research (million-state branching at 3 ply even in a lands-and-creatures toy game), and the Turing-completeness result (optimal MTG play is undecidable) — independently confirms that emergent search cannot find or execute combo lines and that loops must be bounded, declared constructs. This is direct, primary-source validation of the compiled-program + interpreter + governor architecture: Forge owns rules, the pilot owns intent, and win conversion must be explicit in the program because no evaluator in the ecosystem recognizes "infinite X" as a win before the terminal state.

---

## Q1 — Commander Spellbook data model at API depth

### F1. Public REST API + MIT open source (HIGH confidence, 3-0 / 3-0)

**What it is.** Commander Spellbook exposes a public, no-auth Django REST backend at `https://backend.commanderspellbook.com/` (v5.7.5 at verification time) with 13 resources including `variants`, `features`, `cards`, `templates`, `variant-suggestions`, `variant-aliases`, `find-my-combos`, and `estimate-bracket`. Both the site and backend are MIT-licensed and actively maintained (both repos pushed 2026-07-27).

**Evidence.**
- https://backend.commanderspellbook.com/ (live API root, verified 2026-07-27)
- https://commanderspellbook.com/about/ — "Backend REST API"; "The source code for the website and the backend server are completely free and open source under the MIT license."
- https://github.com/SpaceCowMedia/commander-spellbook-backend (SPDX-detected MIT)

**Mapping to our architecture.** This is the mass-compilation feedstock. The API requires no scraping and no auth; the schema can be read directly from `backend/spellbook/models/` when the JSON is ambiguous. Note the caveat: MIT covers the *code*; licensing of the combo *content* is a separate, unverified question. Also note `find-my-combos` (POST a decklist, get combos present/almost-present) — a ready-made endpoint for the deck-ingestion side of the arena, and `estimate-bracket` for power-level metadata.

### F2. The five-relation combo model — the "amorphous third thing" is a first-class object (HIGH, 3-0 / 3-0)

**What it is.** The core `Combo` model encodes exactly five relationship types (verified in `backend/spellbook/models/combo.py`):

| Relation | Target | Meaning |
|---|---|---|
| `uses` | Card (through CardInCombo) | Specific cards the combo uses |
| `requires` | Template (through TemplateInCombo) | Generic card slots ("a way to grant X") resolved by a validated Scryfall query |
| `needs` | Feature (through FeatureNeededInCombo) | Features consumed |
| `produces` | Feature (through FeatureProducedInCombo) | Features emitted |
| `removes` | Feature (through FeatureRemovedInCombo) | Features negated |

At the API surface, each *variant* (the denormalized, user-facing combo) carries a `produces` array of feature objects (`id`, `name`, `status`, `uncountable`, plus `quantity`) and a `requires` array of template objects (`id`, `name`, `scryfallApi`, `scryfallQuery`, plus `zoneLocations`, card-state fields, `mustBeCommander`). Live example: template id 46 "Permanent that can be cast using {C}" with query `mv<=1 (mana={0} or mana={1} or mana={C}) is:permanent`; feature id 1774 "Aura or Equipment that grants deathtouch". Features carry a `status` taxonomy (HIDDEN_UTILITY / PUBLIC_UTILITY / HELPER / CONTEXTUAL / STANDALONE) and an `uncountable` flag used by variant generation.

**Evidence.**
- https://backend.commanderspellbook.com/variants/?limit=1 (live, 2026-07-27)
- https://github.com/SpaceCowMedia/commander-spellbook-backend — `backend/spellbook/models/combo.py`, `template.py`, `feature.py`

**Mapping to our architecture.** The "amorphous third thing" — a mana engine needing an outlet, a trigger needing a payload, "a way to grant lifelink" — is *not free text*; it is either a Feature edge or a Template with an executable Scryfall query. Our compiler can: (a) resolve `requires` templates to the concrete cards actually in the deck under test (run the `scryfallQuery` against the deck list, or use the template's `replacements` M2M in the backend DB); (b) treat `produces` features as the program's declared *output type*, which is exactly what our program classes are (`mana_loop` produces "Infinite colorless mana"; `ping_loop` produces "Infinite damage"). Nuance found during verification: at the variant level, feature-consumption (`needs`) edges are pre-resolved into cards/templates at variant-generation time — the raw needs-edge lives on the `Combo` model in the backend, not the variant JSON — so chaining at the API level goes through feature queries (see F4) or through the backend models directly.

### F3. Initial state is machine-readable; step sequences are English prose (MEDIUM-HIGH, 2-1)

**What it is.** Variant setup compiles cleanly: `uses` entries carry `card`, `quantity`, `usedFace`, `zoneLocations` (enumerated: `"B"`/`"H"`/`"G"`/`"L"`/`"E"`/`"C"`), `mustBeCommander`, and zone-specific state fields (`battlefieldCardState`, `exileCardState`, `libraryCardState`, `graveyardCardState` — free-form text, usually empty). `manaNeeded` is mana-notation text (`"{2}"`), `manaValueNeeded` is numeric. But `easyPrerequisites`, `notablePrerequisites`, and crucially `description` (the step-by-step line) are human-readable English — e.g. "Activate Basalt Monolith's first ability by tapping it, adding {C}{C}{C}. … Repeat." There are **no typed step objects or action enums anywhere in the payload**.

**Evidence.**
- https://backend.commanderspellbook.com/variants/?q=Basalt+Monolith+Rings+of+Brighthearth (live, 2026-07-27)
- `variant.py` in the backend repo: `description` — "Long description, in steps"

**Mapping to our architecture.** This defines the compiler's shape: zone/state/mana setup maps mechanically onto program preconditions (governor entry gates), but the step body requires an NL→primitive translation pass. The good news: descriptions are numbered, use a small verb vocabulary ("Cast", "Activate", "Sacrifice", "Repeat", "Resolve"), reference card names verbatim, and end loops with an explicit "Repeat." marker — a constrained-grammar parser plus LLM fallback, *validated by replaying the compiled program in Forge*, is feasible. The 2-1 vote reflects two minor labeling quibbles (manaValueNeeded is numeric; card-state fields are free text), not disagreement about the core split.

### F4. The combo→feature→combo chain is queryable server-side (HIGH, 3-0)

**What it is.** The `/variants/` endpoint accepts the site's full search syntax via `q=`, including `result:"<feature name>"` (substring match on produced feature names) and combinations like `q=card:"Basalt Monolith" result:"Infinite colorless"`. Verified live: the filter is genuinely applied server-side (nonsense feature names return 0 results; the expected Basalt Monolith combos return exactly). `/features/` and `/templates/` are enumerable resources (~600 features, 100+ templates scanned during verification).

**Evidence.**
- https://backend.commanderspellbook.com/variants?q=result:"Infinite mana" (live, 2026-07-27)
- https://backend.commanderspellbook.com/features/, /templates/

**Mapping to our architecture.** This resolves the "amorphous third thing" *compositionally*: given a deck containing a mana engine that produces "Infinite colorless mana", query variants/features for consumers of that output present in the same deck — i.e., automatic engine→outlet pairing, which is our `pairing` and `engine` program classes discovered from data instead of hand-authored. Practical note: for mass compilation, pull the full dataset once (paginated `/variants/`) and join `produces.feature.id` locally rather than issuing thousands of live queries; use `result:` queries for incremental/spot lookups. One refuted claim matters here: features are *not* provably flat (the claim that no feature-to-feature edges exist was refuted 0-3), so check the backend's Feature model for utility/child relationships before assuming client-side joins are the only chaining mechanism.

---

## Q2 — How other projects play Magic programmatically

### F5. Forge upstream: maintainers rate their own AI "pretty bad for most combo decks" (HIGH, 3-0)

**What it is.** The official Card-Forge wiki AI page (synced 2026-07-26): "The AI is: Best with Aggro and midrange decks, Poor to Ok in control decks, **Pretty bad for most combo decks**." The README separately states the AI "does not understand card combos"; the per-card `AILogic$` hint system exists precisely because the generic AI cannot sequence card-specific interactions unaided.

**Evidence.** https://github.com/Card-Forge/forge/wiki/AI

**Mapping to our architecture.** This is the upstream's own justification for our entire layer: compiled per-combo programs (ping_loop / mana_loop / pairing / engine) executed by interpreters, with a governor, *over* stock AI — rather than trusting or extending the AI to find lines. The "most" qualifier is real: some combos limp along via hand-written AILogic hints, which is the upstream's (non-scalable) version of what we're doing systematically.

### F6. Forge's simulation AI has a Plan abstraction — but plans are discovered by brute-force simulation, capped at depth 3 (HIGH, 3-0 / 3-0)

**What it is.** `SpellAbilityPicker` (forge-ai, opt-in via `AIOption.USE_SIMULATION`; the default AI is even shallower per-ApiType heuristics) simulates each candidate SpellAbility on a full `GameCopier` copy of the game, keeps the highest heuristic score, and builds a `Plan` of chained `Decision`s; it can defer actions to a later phase (`formulatePlanWithPhase`, e.g. waiting until `COMBAT_DECLARE_BLOCKERS`). But `SimulationController.MAX_DEPTH = 3` (private static, no setter, no other reference in forge-ai) hard-caps recursion, and recursion also stops the moment a winning score (`Integer.MAX_VALUE`) is found. Plans are flat `List<Plan.Decision>` — **no loop or iteration construct exists**; an N-iteration ping loop would need N separate decision entries, structurally unreachable under the cap. Plan machinery also only sequences actions within the current turn.

**Evidence.**
- `forge-ai/src/main/java/forge/ai/simulation/SpellAbilityPicker.java` (lines 128, 152-156, 208-241, 341-376 upstream master, commit 6e937ead; identical in our fork)
- `forge-ai/src/main/java/forge/ai/simulation/SimulationController.java` line 15: `private static int MAX_DEPTH = 3;`; lines 53-55: `shouldRecurse()`

**Mapping to our architecture.** Two direct consequences. (1) The stock AI can be trusted for *tactical filler* — 1-3 step value plays, blocking, targeting — which is exactly the Forge-owns-rules / pilot-owns-intent boundary: leave MAX_DEPTH alone, never try to widen it into combo territory. (2) Loops must be an *interpreter-level* construct with explicit iteration semantics, because the underlying plan representation literally cannot express them. The Plan/Decision replay machinery (with `initialScore` validation on replay) is worth studying as prior art for our interpreter's "verify the game state still matches the program's expectation before each step" governor check. A caveat worth keeping honest: greedy per-priority re-planning *can* execute longer lines when every intermediate step independently improves the score — but combo lines are precisely the ones whose intermediate steps are score-neutral or negative.

### F7. Forge's win detection and evaluation: terminal-state only, shallow material heuristic, multiplayer under-supported (HIGH, 3-0 / 3-0)

**What it is.** `GameStateEvaluator` returns win/loss sentinels (`Integer.MAX_VALUE` / `MIN_VALUE`) *only* when `game.isGameOver()`, by inspecting `game.getOutcome()`. Otherwise the score is shallow material: `2 * life`, `+5` per own card in hand / `-4` per opponent card, per-card battlefield evaluation (non-creature permanents ≈ `50 + 30 * CMC`), plus mana-base value. `GameSimulator.simulateSpellAbility` resolves the entire stack (halting on game over) before scoring. There is **no representation of combo potential, engine assembly, or feature-like concepts**; an intermediate combo-piece state scores ~110 points vs. MAX_VALUE for a win. Every "infinite" reference in forge-ai is a guard *preventing* the AI from recursing into a loop; `PlayerControllerAi.java:404` has a TODO admitting the AI cannot evaluate "infinite loop / unwinnable position" states. Multiplayer is explicitly under-supported (three `// TODO: more than 2 players` comments; opponent life is averaged).

**Evidence.**
- `forge-ai/src/main/java/forge/ai/simulation/GameStateEvaluator.java` lines 71-92, 98, 117-130, 142-164 (fork and upstream master identical)
- `forge-ai/src/main/java/forge/ai/simulation/GameSimulator.java` lines 228-271

**Mapping to our architecture.** The value signal for combo states must come from the pilot, full stop: the compiled program *is* the evaluator for its own line (each completed step = progress; governor exit states = the terminal conditions the engine's evaluator can't see coming). Win conversion ("I have infinite X, now win") must be explicit program steps that drive the game to an actual `isGameOver()` state — kill every opponent within the line — because that terminal state is the only thing Forge recognizes. The multiplayer TODOs are a live risk for our 4-player pods: any place we *do* lean on the simulation evaluator (tactical filler) inherits averaged-opponent-life myopia.

### F8. XMage's strongest AI: shallow minimax at four decision points; structurally blind to combo windows (HIGH, 3-0 / 3-0)

**What it is.** XMage's "mad bot" (`ComputerPlayer6/7`, `Mage.Server.Plugins/Mage.Player.AI.MAD`) is depth-limited alpha-beta minimax over cloned game states: `maxDepth = 4` at default skill (client default skill=2; skill≥4 scales up), `MAX_SIMULATED_NODES_PER_CALC = 5000`, think time `skill * 3` seconds. Depth counts *sequential priority actions*, not turns ("Ended due max actions chain depth limit"). Moreover, `ComputerPlayer7.priorityPlay()` invokes game-tree search at exactly four decision points — PRECOMBAT_MAIN, DECLARE_ATTACKERS, DECLARE_BLOCKERS, POSTCOMBAT_MAIN — and unconditionally `pass(game)` on UPKEEP, DRAW, BEGIN_COMBAT, damage steps, END_TURN, and CLEANUP, with no stack-emptiness check. It cannot act in upkeep/end-step/damage-step windows on any player's turn.

**Evidence.**
- https://github.com/magefree/mage — `ComputerPlayer6.java` (L54, L94-99, L335, L546), `ComputerPlayer7.java` (priorityPlay switch), ref 6958cdf

**Mapping to our architecture.** Independent confirmation, from the other major open-source rules engine, of the same two lessons as F6: search depth measured in priority actions can never reach combo length, and *phase coverage* is as important as depth. For us: our interpreter must register for priority in the exact windows each program needs (upkeep triggers, end-step activations, instant-speed responses) rather than inheriting the engine AI's phase schedule — a governor responsibility ("this program's steps execute in these windows") that neither engine's AI models at all.

### F9. XMage treats combo loops as a failure mode to suppress — and its win detection is emergent terminal-state scoring (HIGH, 3-0 / 3-0)

**What it is.** `calculateActions` caches zero-cost actions (`actionCache` keyed on rule+sourceId, no game-state component, cleared only at end of turn) and refuses to repeat them *even when the search selected the repeat as the best action* — one loop iteration per turn, maximum. An empty search result is logged as "nothing to choose or freeze/infinite game". Corroboration: GitHub issue #2023 ("Basalt Monolith + computer ai = infinite loop", open since 2016); forum reports of 12GB-RAM lockups. Win detection: `GameStateEvaluator2.WIN_GAME_SCORE = 100000000`, awarded only when a simulated state within the depth horizon is already won (`checkIfGameIsOver()` / `hasWon()`, plus a life≤0 shortcut); minimax short-circuits on it ("win - break"). A developer comment in `ComputerPlayer.java` states it outright: "AI don't need huge values for X, cause can't use infinite combos."

**Evidence.**
- https://github.com/magefree/mage — `ComputerPlayer7.java` (actionCache guard), `ComputerPlayer6.java` (win-break), `score/GameStateEvaluator2.java`
- https://github.com/magefree/mage/issues/2023

**Mapping to our architecture.** The sharpest single datapoint in the whole survey: when a search-based AI meets an infinite loop, its two available behaviors are *freeze* or *suppress* — never *execute-and-convert*. Executing a loop as a win line requires intent-level knowledge (what the loop produces, how many iterations suffice, what the exit state is) that no evaluator can recover from state deltas, because each iteration is score-neutral. That is verbatim the spec for our `ping_loop`/`mana_loop` classes: declared product, declared iteration count (lethal damage + margin, or "enough mana for the outlet"), declared exit state, governor-enforced cap. It also validates the tournament-rules framing: MTG's own loop-shortcut rule (declare a finite iteration count) is the human-play version of our governor.

### F10. Theory: optimal MTG play is undecidable — even with all moves forced (HIGH, 3-0 / 3-0)

**What it is.** Churchill, Biderman & Herrick (arXiv:1904.09828; peer-reviewed at FUN 2021, LIPIcs 157) embed an arbitrary Turing machine in a legal two-player game: "optimal play in real-world Magic is at least as hard as the Halting Problem," and — the stronger result — "even recognising who will win a game in which neither player has a non-trivial decision to make for the rest of the game is undecidable." All moves in the construction are forced, fixing the flaw in the earlier 2012 construction; an independent reimplementation exists (github.com/Cerno-b/mtg-turing-machine).

**Evidence.** https://arxiv.org/abs/1904.09828; DOI 10.4230/LIPIcs.FUN.2021.9

**Mapping to our architecture.** Pure forward simulation of a deterministic loop can fail to terminate, and no general algorithm can detect that it will — so a loop executor *must* impose explicit iteration caps and declared exit states rather than simulating to a fixed point. This is the theoretical floor under the governor design. Honest scoping: this is a worst-case result over an adversarially constructed Legacy board state; it proves no *complete* general algorithm exists, not that bounded heuristic search is useless for practical Commander states. Our narrow loop classes (monotone life-drain pings, mana accumulation) have provable termination — but only *because* we classify them and declare their exits, which is the point.

### F11. MCTS research on MTG: even a toy ruleset explodes; the winning trick was decision decomposition (HIGH, 3-0 / 3-0 / 3-0)

**What it is.** The canonical MCTS-for-MTG study (Cowling, Ward & Powley, IEEE TCIAIG 2012) did **not** use the full rules: single-color vanilla creatures plus lands, basic combat only, "encoding of the rules … represents a significant software engineering problem in practice." No combo, loop, stack-interaction, or infinite-line handling anywhere; win detection is life≤0 or deck-out. Even so: ~75-90 states at 1 ply, 7000-8000 at 2 ply, ~a million at 3 ply; the naive all-possible-deals MCTS player won only 23% against a hand-coded expert-rules player. Their strongest structural enhancement was decomposing compound moves into a **binary yes/no decision tree** (play card / don't, level by level), so parts of a compound move are reinforced separately — consistently strong and >3x faster per move than alternatives.

**Evidence.**
- https://www.researchgate.net/publication/260583921 (author PDF: https://eprints.whiterose.ac.uk/75050/1/EnsDetMagic.pdf, DOI 10.1109/TCIAIG.2012.2204883)

**Mapping to our architecture.** Three takeaways. (1) The academy never got past a toy ruleset — using Forge as the rules oracle is the correct division of labor and is itself the "significant software engineering problem" already solved. (2) Branching-factor math kills any hope of search-based combo discovery at runtime; compilation ahead of time is the only tractable route. (3) The binary-decomposition result is directly reusable at *interpreter choice points*: when a program has a genuine branch (which outlet? which target ordering?), frame it as small sequential yes/no decisions rather than one combinatorial compound move — cheaper, and each sub-decision is independently evaluable by the stock AI's heuristics.

### F12. Practical card-game AI plans single-turn horizons only (MEDIUM, 2-1)

**What it is.** Hoover et al. (arXiv:1907.06562, "The Many AI Challenges of Hearthstone"): MetaStone's stock agent "simply searches up until the end of the current move and uses a heuristic evaluation function, not even attempting to predict the opponent's move." Corroborated by the successor project's (Spellsource) `GameStateValueBehaviour` javadoc — explicitly "a 'single turn horizon' AI." Forge's `SpellAbilityPicker` has the same property (plan machinery guards on `getPlayerTurn() != player`; sequences within the current turn only).

**Evidence.** https://arxiv.org/pdf/1907.06562; Spellsource javadoc for `net.demilich.metastone.game.behaviour.GameStateValueBehaviour`

**Mapping to our architecture.** Multi-*turn* lines (assemble engine turn N, protect it, convert turn N+1; or upkeep-trigger engines that pay off across turns) have no representation in any stock agent surveyed. Our `engine` program class — persistent intent that survives turn boundaries, with the governor tracking assembly state across turns — fills a gap that is unfilled everywhere, not just in Forge. The 2-1 vote reflects the generalization beyond the single quote, but the quote itself and the Forge corroboration were verified against primary sources.

---

## Q3 — Combo ingestion elsewhere in the ecosystem

**Finding: no prior art for compilation-to-executable-plans exists.** This is a negative result, but a well-supported one:

- Commander Spellbook itself is the ingestion *source*, not an ingestion *consumer*: its data model (F2) is built for display and deck-checking (`find-my-combos` returns combos present/almost-present in a decklist), not execution. Deck-site integrations (EDHREC/Archidekt/Moxfield combo panels are Spellbook-backed) are display-layer only — no project found turns Spellbook entries into machine-executable game actions.
- Forge upstream's closest analog is per-card `AILogic$` hints (F5) — hand-written, card-scoped, non-compositional.
- XMage's only combo-awareness is deck-validation power scoring (`Mage.Deck.Constructed/AbstractCommander.java`), not gameplay (F9 verification).
- Academic work stopped at toy rulesets (F11); the Turing-completeness line (F10) is about impossibility, not ingestion.

**Mapping to our architecture.** The compiler we're building (Spellbook variant JSON → program JSON per combo, classed as ping_loop/mana_loop/pairing/engine) has no existing implementation to borrow — but also no competing convention to conform to. The pieces all exist (machine-readable setup, feature graph, Scryfall-resolvable templates, English step text with regular structure) and nobody has assembled them. The step-text NL parse (F3) is the only genuinely novel-risk component; everything else is joins and code generation.

*(Confidence: MEDIUM as a negative claim — absence of evidence across the surveyed sources, not a verified impossibility. No surviving adversarially-verified claim covers EDHREC/Archidekt/Moxfield internals directly.)*

---

## Q4 — Win-state / conversion modeling

Synthesis across F7, F9, F10:

1. **Nobody models conversion.** Both engines recognize a win only as an already-terminal simulated state (`isGameOver()` in Forge; `checkIfGameIsOver()`/life≤0 in XMage) inside a 3-4 action horizon. There is no "I have infinite X ⇒ I win" reasoning anywhere in the surveyed ecosystem, and XMage's developers state affirmatively that their AI "can't use infinite combos."
2. **Spellbook's `produces` features are the missing conversion vocabulary.** "Infinite colorless mana," "Infinite damage," "Near-infinite lifegain," "Infinite draw triggers" — these are precisely the intermediate win-relevant states the evaluators can't see, already normalized into ~600 typed features with an `uncountable` flag.
3. **Conversion must therefore be an explicit compiled construct:** a mapping from produced feature → conversion routine (outlet card in deck, resolved via `requires` templates or feature-chaining per F4) → concrete terminal sequence (deal ≥ sum of opponents' life totals; loop mill; Ballista X = lethal) that the governor executes to an actual engine-recognized game-over. Iteration counts must be computed, finite, and declared (F10): lethal-plus-margin, never "until done."
4. **Exit states are first-class:** every program needs declared exits for *converted* (win achieved), *fizzled* (interrupted mid-line — governor must know what board state remains), *capped* (iteration limit hit without lethal — e.g. opponents gained life mid-loop), and *blocked* (outlet unavailable). Forge will not detect any of these for us except the first, and only at the moment it becomes terminal.

---

## Ranked recommendations for mass combo compilation

1. **Bulk-ingest Commander Spellbook via the paginated `/variants/` API and compile setup mechanically.** `uses` (zones, quantities, commander flags, faces) + `manaNeeded`/`manaValueNeeded` → program preconditions and governor entry gates, zero NL parsing required. Join `produces.feature.id` locally for the feature graph; keep `result:` queries for spot checks. Pin the backend version (5.7.5) and re-verify schema on upgrade. *(F1, F2, F3)*

2. **Resolve "amorphous third thing" slots at deck-compile time, not runtime.** For each `requires` template, run its `scryfallQuery` against the deck under test (or use backend `replacements`) to bind concrete outlet/enabler cards into the program JSON; for engine→outlet pairing, join produced features against consumers present in the same deck. Emit a `pairing` program per resolved pair and an `engine` program for the unpaired engine (with a "no outlet" blocked-exit). *(F2, F4)*

3. **Make win conversion an explicit program section keyed by produced feature.** Maintain a small library of conversion routines (feature name → routine template: infinite mana + X-outlet, infinite damage → distribute lethal, infinite mill, infinite lifegain → non-win, mark as engine-only) and require every compiled program to end in either a conversion routine or a declared non-winning product. Compute iteration counts as lethal-plus-margin; never open-ended. Reject at compile time any combo whose produced features have no conversion routine and no in-deck consumer — that's a coverage gap report, not a silent skip. *(Q4 synthesis, F7, F9, F10)*

4. **Build the step-text parser as constrained grammar + replay validation, and treat replay-in-Forge as the acceptance gate.** Parse the numbered `description` steps (small verb set, verbatim card names, explicit "Repeat." loop markers) into program primitives; accept a compiled program only if the interpreter can replay it from the declared setup state in a headless Forge game to its declared exit. Failures route to a manual/LLM-assisted queue. This converts the NL risk into a measurable pass rate and guarantees no compiled program encodes a line Forge's rules reject. *(F3, F11)*

5. **Governor owns phase windows and turn persistence.** Register program-specific priority windows (upkeep, end step, instant-speed response points) explicitly per program class — both engines auto-pass exactly the windows combo lines need (F8), and no stock agent plans across turns (F12). Engine-class programs must checkpoint assembly state across turns.

6. **Keep the Forge-owns-rules / pilot-owns-intent boundary exactly where it is.** Do not raise MAX_DEPTH or teach the evaluator about combos — depth-3 tactical filler is what the stock AI is good for, and every surveyed attempt to make search find combo lines failed on branching factor or loop semantics. Borrow two specific mechanisms instead: Forge's Plan/Decision replay-validation pattern for the interpreter's per-step state checks (F6), and Cowling's binary decision decomposition for interpreter choice points (F11).

7. **Track coverage as a first-class metric.** Per deck: combos found by `find-my-combos`, programs compiled, programs passing replay, produced features with conversion routines, features without. "Mass compilation without missing play lines" is measurable as exactly these ratios; the feature `status` taxonomy (STANDALONE vs HELPER/CONTEXTUAL) prioritizes which gaps matter.

---

## Caveats

- **Split votes:** F3 (2-1) and F12 (2-1) carry minor qualifications noted inline; treat as medium confidence. The Q3 negative finding (no ingestion prior art) is absence-of-evidence across surveyed sources, not proof.
- **Content licensing:** MIT covers Spellbook's code; the combo database *content* license is unverified. Check before redistributing compiled programs derived from it.
- **Time-sensitivity:** API shapes verified live 2026-07-27 against backend 5.7.5; Forge upstream at commit 6e937ead; XMage at ref 6958cdf. All are actively developed — re-verify on major version bumps. The papers (2012, 2019/2021) are fixed.
- **Illustrative example gap:** no literal "grants lifelink" feature/template was found in ~600 features / 100 templates scanned; an exactly analogous one exists ("Aura or Equipment that grants deathtouch"). The mechanism is confirmed; specific slot coverage varies.
- **Feature-graph nuance:** `needs` edges are pre-resolved at variant-generation time; raw feature-consumption edges live in the backend `Combo` model, not the variant JSON. The claim that Feature objects are flat (no feature-to-feature edges) was *refuted* — inspect `feature.py` relationships before finalizing the local join strategy.

## Refuted claims (transparency)

Rejected in adversarial verification; do **not** cite:

- "Feature entities are flat — no feature-to-feature edges; chaining must be computed client-side." (0-3)
- "Forge's AI is purely heuristic with no learned components, so combo execution must be supplied externally." (1-2 — the conclusion may hold but this framing failed verification)
- "Nearly all published Hearthstone AI work builds on MCTS; hidden information is the identified core failure mode." (1-2)
- "The Hearthstone paper concludes MCTS cannot search beyond a single turn and pixel-based deep RL is the wrong representation." (0-3)

## Open questions

1. What license governs Commander Spellbook's combo *data* (as opposed to its MIT code), and does compiling it into redistributable program JSON require attribution or ShareAlike terms?
2. What exactly do the Feature model's non-flat relationships (utility/child edges, `status` semantics) encode, and can they shortcut engine→outlet pairing beyond the produces/needs join?
3. What fraction of variant `description` texts parse cleanly under a constrained grammar (verb set + card names + "Repeat.")? A 200-variant sample run would size the NL-parsing risk empirically.
4. Do EDHREC/Archidekt/Moxfield consume Spellbook beyond display (e.g., internal APIs or enrichment), and does Spellbook's `estimate-bracket` endpoint encode power-level heuristics reusable for arena matchmaking?
