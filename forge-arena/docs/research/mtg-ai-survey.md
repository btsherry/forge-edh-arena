# MTG AI Survey: How Systems Plan & Execute Win Conditions and Combos

Research compiled 2026-07-17 for the Forge EDH Arena "pilot" layer. Scope: academic,
commercial, and hobby AI for MTG and comparable card games, focused on our two live
weaknesses — (1) **firing combos early and reliably** (sequencing ramp/tutors/enablers
toward the fire) and (2) **converting fired resources into wins**.

Our system for reference: headless Card-Forge/forge, 4p Commander, pilot on top of stock
AI via the `PlayerController` seam. Prep artifacts (Commander Spellbook combos, regex'd
payoff classes, win-route coverage) → detection tracker (piece reachability = distance) →
parameterized executor archetypes (`TapForManaUntapLoop`, `BounceRecastLoop`,
`SpellCopyLoop`) that **validate on a game copy** → loop shortcut (infinite → bounded
products) → `LethalityPlanner` (SPREAD_COMBAT / COMMANDER_DMG / DIRECT_DAMAGE) →
forced-attack scripting. LLM at prep/post-run only.

---

## Area 1 — Forge's own AI internals

Forge runs **two stacked AIs**. The default is a large hand-written **heuristic**
controller; an optional **simulation (lookahead)** AI can be toggled per SpellAbility.

**Heuristic layer (`forge.ai`).** Entry point `PlayerControllerAi` → `AiController`.
Main-phase logic lives in `AiController.chooseSpellAbilityToPlay()` /
`getSpellAbilityToPlay()`: it plays a land first (`getAvailableLandsToPlay` →
`filterLandsToPlay` → `chooseBestLandToPlay`, may defer to Main2 via
`isSafeToHoldLandDropForMain2`), then walks a **reactive** candidate list sorted by
`ComputerUtilAbility.saEvaluator`, gating each with `canPlayAndPayFor` /
`checkETBEffects`. Per-effect intelligence is delegated to `SpellAbilityAi` subclasses
(one per API, e.g. `DamageDealAi`, `CounterAi`). **There is no combo/goal planner** — the
source comment notes it "only works as a limited prediction of permanent spells," and it
returns plays via `singleSpellAbilityList()` one at a time, leaving multi-spell sequencing
to repeated loop iterations. Special-cases exist for Storm (min storm count), Living End,
and buyback, but these are hard-coded, not general.
Sources: [AiController.java](https://github.com/Card-Forge/forge/blob/master/forge-ai/src/main/java/forge/ai/AiController.java),
[forge-ai module](https://github.com/Card-Forge/forge/tree/master/forge-ai),
[AI wiki](https://github.com/Card-Forge/forge/wiki/AI).

**Simulation layer (`forge.ai.simulation`).** Files: `GameCopier`, `GameSimulator`,
`GameStateEvaluator` (+`SimulationCreatureEvaluator`), `SpellAbilityPicker`,
`SimulationController`, `Plan`, `SpellAbilityChoicesIterator`, `PossibleTargetSelector`,
`MultiTargetSelector`. `SpellAbilityPicker.getCandidateSpellsAndAbilities()` filters to
`AiPlayDecision.WillPlay`; `evaluateSa()` spins up a `GameSimulator` per candidate with a
**fixed RNG seed** (deterministic branching), iterates mode/target combinations via
`SpellAbilityChoicesIterator`, and keeps the highest `GameStateEvaluator.Score`. Crucially
this is **single-play lookahead** — it simulates the immediate ability's resolution, not a
multi-turn or multi-spell sequence. A `Plan`/`Decision` structure and
`formulatePlanWithPhase()` / `createNewPlan()` exist to chain a *few* ordered decisions
with phase timing, but it is not a combo assembler.
Source: [SpellAbilityPicker.java](https://github.com/Card-Forge/forge/blob/master/forge-ai/src/main/java/forge/ai/simulation/SpellAbilityPicker.java).

**`GameStateEvaluator` scoring** (useful — this is the eval we can reuse for our
`LethalityPlanner`): life ×2 (AI) / −2 (opp); cards in hand +5 (capped at max hand size) /
−4 opp; lands = 3 + 100/mana produced + 3/color + utility; other permanents ≈ 50 + 30×CMC;
planeswalkers +2/loyalty; pre-Main2 `summonSickScore` treats summoned creatures as
valueless. **`getScoreForGameOver()` returns `Integer.MAX_VALUE` on AI win /
`Integer.MIN_VALUE` on loss** — a ready-made terminal/lethal signal.
Source: [GameStateEvaluator.java](https://github.com/Card-Forge/forge/blob/master/forge-ai/src/main/java/forge/ai/simulation/GameStateEvaluator.java).

**AI scripting hints** (set on card scripts; steer stock AI + random deckbuild):
- Deckbuild: `RemoveDeck:All|Random|NonCommander`; `DeckHints:Type$…`/`Color$…`/`Keyword$…`/`Name$…`;
  `DeckNeeds` (`&`=AND, `|`=OR); `DeckHas` (signals `Counters`/`Graveyard`/`Token`); `DeckWants`.
- Play timing: `PlayMain1:TRUE|ALWAYS|OPPONENTCREATURES`; `NeedsToPlayVar:Y GE3` (LT/LE/EQ/NE/GE/GT);
  `ManaNeededToAvoidNegativeEffect`; `AILogic$…` (per-effect strategy string consumed by the `SpellAbilityAi`).
- Combat/board: `MustAttack`, `MustBeBlocked`, `HasCombatEffect`, `HasAttackEffect`, `BuffedBy`, `AntiBuffedBy`,
  `SacMe:1-6`, `UntapMe`, `EnchantMe`/`EquipMe:Multiple|Once`, `AIPreference`, `AIEvaluationModifier`, `NoZeroToughnessAI`.
Source: [Card scripting API wiki](https://github.com/Card-Forge/forge/wiki/Card-scripting-API).

**Documented combo/sequencing weaknesses** (concrete, citable):
- AI wiki states outright: strong at aggro/midrange, moderate at control, **weak at "most combo decks"; "not trained… easy to overcome knowing its weaknesses."**
- Issue #3674 "AI flaws": casts spells into "counter the first spell each turn" effects; burns
  a damage-reflecting permanent even when it's **self-lethal**; overfills optional "you may"
  triggers; **prefers the newer duplicate legend** (so the non-summon-sick copy never attacks);
  redundant removal that can go lethal on itself.
- Infinite-loop mishandling with no payoff: Oath of Druids + Emrakul (keeps re-picking the
  summon-sick Emrakul, never attacks); Gruul Ragebeast + Sprouting Phytohydra (loops fight/copy
  for no gain). Forge has loop-detection that *stops* these, but the AI enters them without a win.
- X-spells frequently cast for **X=0**; AI gets very slow with many permanents (branching).
Sources: [#3674](https://github.com/Card-Forge/forge/issues/3674),
[#4392 summarized AI problems](https://github.com/Card-Forge/forge/issues/4392),
[#6726 slow with many permanents](https://github.com/Card-Forge/forge/issues/6726).

**Takeaway:** Forge gives us free, reusable machinery (`GameCopier`+`GameSimulator`+
`GameStateEvaluator`, deterministic seed, `Plan`/`Decision`, `getScoreForGameOver`) but **no
goal-directed planner and no reliable combo firing** — exactly the gap our pilot fills.

---

## Area 2 — Other MTG engines & academic work

**XMage.** Rule/heuristic AI. In multiplayer it assigns each bot a **fixed random target
enemy** and throws everything at that one player until dead, then re-rolls — a textbook
anti-pattern for our threat model. Combat is timid: only blocks on survival-or-guaranteed-kill,
**never chump-blocks, never double-blocks**, takes lethal rather than trade. X-spells
mis-cast. Targeting logic was later reworked but remains shallow.
Source: [magefree/mage #5040](https://github.com/magefree/mage/issues/5040).

**Magarena — MCTS.** Classical UCB1 (C=√2), reward 0/1, averaged backup, uniform-random
playout ([MCTSAI.java](https://github.com/magarena/magarena/blob/master/src/magic/ai/MCTSAI.java)).
Melvin Zhang's key finding: honest MCTS on MTG plays badly because of hidden information; the
fix was **cheating determinization** — sample the opponent's hand from a random slice of their
library during playouts. Cheating MCTS is strongest; honest MCTS becomes competitive only at
high compute, still beating cheating minimax.
Sources: [Zhang slides](https://www.slideshare.net/melvinzhang/building-a-state-of-the-art-ai-to-play-magic-the-gathering),
[AIComparison wiki](https://github.com/magarena/magarena/wiki/AIComparison).

**Academic MTG.**
- **Turing completeness** (Churchill, Biderman, Herrick, FUN 2021): optimal MTG play is
  **at least as hard as the Halting Problem** — a real 2-player tournament-legal deck embeds an
  arbitrary Turing machine, no hidden info/randomness needed. Practical import: *no* general
  solver exists; bounded, scripted, or heuristic search is the only tractable path.
  [arXiv 1904.09828](https://arxiv.org/abs/1904.09828),
  [DROPS FUN 2021](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.FUN.2021.9).
- **Ensemble Determinization MCTS** (Cowling/Ward/Powley) — imperfect-info MTG via multiple
  determinized trees. [ResearchGate 260583921](https://www.researchgate.net/publication/260583921).
- **Drafting** is the well-studied sub-problem (separable from play): Ward et al "AI solutions
  for drafting in MTG" ([arXiv 2009.00655](https://arxiv.org/pdf/2009.00655)); "Learning with
  Generalised Card Representations" ([arXiv 2407.05879](https://arxiv.org/abs/2407.05879)); RL
  drafting on the LOCM testbed. Not directly relevant to in-game combo firing but confirms the
  field solves *modular* sub-problems, not whole-game play.
- **Strategy Card Game AI Competition** (LOCM; Kowalski & Miernik,
  [arXiv 2305.11814](https://arxiv.org/pdf/2305.11814)): the most transferable result. **Tree
  search won every v1.2 event** — champion "Coac" = *minimax depth-3, alpha-beta, heuristic
  pruning*; NN/deep-RL (ByteRL) only overtook in v1.5. The competition's stated top
  improvements: **move ordering + pruning, and explicit lethal (winning-move) detection.**
  Deeper search lost to *moderate search + strong expert-heuristic eval*. Opponent-hand
  prediction (ProphetCoac) gave **mixed** results.
- **Yu-Gi-Oh! is hard** (2026): deciding a winning YGO line is computationally hard —
  reinforces "bounded/scripted, not solve." [arXiv 2603.02863](https://arxiv.org/pdf/2603.02863).

**MTGA bot ladder:** no published architecture; WotC treats it as proprietary. Community
consensus is heuristic/scripted with per-deck tuning; nothing citable to design against.

---

## Area 3 — Combo / goldfish solvers (sequencing models)

These are **prep-time** tools; none run in a game loop. They model *reachability*, which is
our "distance" metric.

**Kelvin Liu MTG Combo Calculator** ([CMU page](https://www.andrew.cmu.edu/user/kmliu/mtg_combo_calc.html),
now kelvinliu.org). Input: pieces with copy counts (`A4, B2, C10`), win conditions as
piece-sets (`AB, AC, BC`), and a mulligan rule (up to 6 thresholds). Output: P(assemble a
winning piece-set) within the first *X* draws for a deck of *Y*. It is a **probability of
assembly**, not a line-optimizer or mana-aware — pieces are abstract, tutors are just extra
copies of the thing they fetch.

**Storm / "goldfishing" methodology** (EPIC Storm's storm-count combinatorics; ManaTap
mulligan sim). Competitive storm players plan lines by **net-mana and net-card accounting**:
rituals are scored by mana *delta* (Dark Ritual = +2), cantrips by card *delta* while chaining,
tutors as **wildcards for the single missing piece**. They "go off" only when the counted
storm/mana clears the lethal threshold — i.e. an explicit **float check before commit**.
Tutors are sequenced by *scarcity*: fetch the piece with the fewest redundant copies / hardest
to draw, save flexible tutors for last. Mulligans are modeled hypergeometrically to hit a
minimum enabler count by turn N.
Sources: [EPIC Storm — storm count](https://www.theepicstorm.com/the-storm-count-combinatorial-probability/),
[ManaTap mulligan sim](https://www.manatap.ai/tools/mulligan),
[hypergeometric calc](https://cardgamecalculator.com/).

**Commander Spellbook** (already our combo source) is the canonical machine-readable combo DB;
each combo lists required pieces + "produces" (infinite mana/tokens/damage) + prerequisites —
directly parseable into an assembly target and a payoff class.

---

## Area 4 — Game-AI architectures & how other card games execute plans

**Planner families** (the core design choice for our sequencing gap):
- **Behavior Tree** — reactive, no lookahead; you hand-author every branch. Good for tactics,
  bad for "figure out a non-obvious multi-step combo."
- **Utility AI** — scores actions; picks best *now*; also no multi-step plan.
- **GOAP** — *flat* action pool, planner searches actions to reach a goal-state; emergent plans
  but expensive and needs scenario-specific heuristics.
- **HTN** — *hierarchical*: designer authors **methods** that decompose a compound task
  ("assemble combo C") into subtasks ("acquire piece A", "reach M mana"); planner picks methods.
  Cheaper and more controllable than GOAP when the domain has natural hierarchy — **combos do.**
- Shipped AI is almost always **hybrid**: BT with utility-scored selectors, or GOAP/HTN whose
  primitive actions are BT subtrees.
Sources: [Tono — GOAP/Utility/BT](https://tonogameconsultants.com/game-ai-planning/),
[Socratopia ch.12](https://www.socratopia.app/library/game-code-anatomy-en/chapter-12),
[Aversa — BT vs GOAP](https://www.davideaversa.it/blog/choosing-behavior-tree-goap-planning/),
[GOBT hybrid](https://www.jmis.org/archive/view_article?pid=jmis-10-4-321).

**Slay the Spire.** Bottled AI: **enumerate every ordering of the hand via graph traversal +
forward simulation, score each terminal outcome, play the best-scoring order.** This is exactly
"scripted-plan-with-validation" at small branching — tractable because a turn's action set is
small. LLM agents (Claude-Haiku bot, AgenticSTS) struggle with *long-term* card/combo choices;
AgenticSTS's win is **structured memory instead of raw transcript** (5k vs 500k tokens) — an
argument for compiling plan state into structured artifacts, not prose.
Sources: [Bottled AI](https://github.com/xaved88/bottled_ai),
[AgenticSTS](https://the-decoder.com/ai-agents-win-at-slay-the-spire-2-after-researchers-replace-growing-chat-logs-with-structured-memory/).

**Hearthstone.** SabberStone (C# sim, ~98% base cards) + scoring tree-search; peter1591's
MCTS+NN; Silverfish MCTS. Across the board, **lethal detection is the single most important
optimization** for combo/burst decks — every strong agent special-cases "can I win now?" before
general search.
Sources: [SabberStone](https://github.com/HearthSim/SabberStone),
[peter1591 MCTS+NN](https://github.com/peter1591/hearthstone-ai),
[MCTS+SL paper](https://arxiv.org/pdf/1808.04794).

**Yu-Gi-Oh! (combo-centric game).** EDOPro's WindBot is a **deterministic, per-deck scripted
bot** — a human writes an explicit line ("if these pieces present, do steps 1..N") per
archetype. The dominant real-world approach to reliable combo execution is **authored scripts,
not search** — validating our executor-archetype design.
Source: [WindBot-Ignite](https://github.com/ProjectIgnis/WindBot-Ignite).

---

## Area 5 — Multiplayer politics / threat assessment

No mature *implemented* commander-AI threat model exists in the open engines. XMage's
**fixed-random-single-target** is the concrete failure to avoid. Human strategy literature gives
the heuristics worth encoding:
- **Threat = danger *now*, re-scored every turn**, allocating limited resources — not a locked
  target. Signals: mana advantage, board presence/permanents, commander threat, cards in hand,
  known combo proximity.
- **Archenemy rule**: when one player has a commanding lead, "form the Avengers" — the table
  (and our bot) should redirect at the leader. Conversely **don't feed the leader** by trading
  with the player who's behind.
- **Fly under the radar** until you can win: telegraphing a combo invites removal; hold the fire
  until validation says it's lethal *this* turn.
Sources: [Draftsim threat assessment](https://draftsim.com/mtg-commander-threat-assessment/),
[StarCityGames — assessing threats](https://articles.starcitygames.com/articles/assessing-threats-in-commander/).

---

## What maps onto our architecture — prioritized recommendations

**P0 — Make lethal detection first-class and continuous.** The one universal lesson (LOCM,
Hearthstone, storm): check "can I win from the current state?" at **every** priority window, not
only after a loop fires. Implement `LethalityPlanner.canWinNow()` that, for each route
(SPREAD_COMBAT / COMMANDER_DMG / DIRECT_DAMAGE), **simulates on a `GameCopier`+`GameSimulator`
game copy and accepts iff `GameStateEvaluator.getScoreForGameOver()` hits `Integer.MAX_VALUE`**.
Reuse Forge's own evaluator/terminal signal rather than a bespoke life-math check — it already
accounts for blockers, replacement effects, and simultaneous state-based actions. This directly
attacks weakness #2 (conversion) and is cheap.

**P1 — Turn the "distance" tracker into an HTN-style assembly planner (attack weakness #1).**
Combos are hierarchical, so prefer **HTN over GOAP**. At prep, compile each Commander-Spellbook
combo into an **assembly plan**: compound task `FireCombo(C)` → subtasks `{HavePiece(p_i)}` +
`HaveMana(m)` + ordering constraints, with **methods** per subtask (draw / cast / tutor / ramp).
Your executor archetypes (`TapForManaUntapLoop`, etc.) become the **primitive operators** at the
leaves. Each turn, run a cheap best-first regression over the plan to pick the **single action
that most reduces distance-to-fire** (distance = your existing reachability). This is
lightweight — no in-loop search explosion — and gives goal-directed sequencing the stock AI
lacks.

**P2 — Model tutors as scarcity-weighted wildcards; sequence ramp before durdle.** From the
combo-calc/storm literature: a tutor's value = **max distance-reduction across fetchable missing
pieces**; break ties by **piece scarcity** (fewest redundant copies) and by "is this the last
missing piece." Encode a **mana runway target** = the combo's mana cost; each turn prefer plays
that advance reachable mana toward it (ramp/rituals scored by net-mana delta, cantrips by
net-card delta), and **don't hold land drops when behind on runway** (invert Forge's
`isSafeToHoldLandDropForMain2` when a fire is in reach). This is the "sequence enablers toward
the fire" behavior we're missing.

**P3 — Adopt the "float check before commit" gate.** Before entering a loop or committing the
fire, run the storm-style verification that the **bounded product actually clears the required
threshold** for the chosen route (enough mana injected / tokens for multi-opponent lethal). We
already validate loops on a copy — extend the same copy-and-validate to the **conversion step**,
and require it to cover **all reachable opponents** (multiplayer lethal ≠ single-target). Refuse
to fire if the float check fails; keep durdling toward more resources.

**P4 — For the fire turn, brute-force sequence enumeration (Bottled-AI pattern).** On the turn a
combo is reachable, the relevant action set (enablers + payoff) is small. Enumerate the few
orderings, simulate each on a copy, and pick the ordering that reaches game-over — a
tractable, deterministic "scripted-plan-with-validation" that guarantees the fire actually
resolves. This is the WindBot/Bottled-AI approach and fits our validate-on-copy design exactly.

**P5 — Continuous threat model for forced-attack + hold decisions.** Replace any static target
with a per-turn threat score (mana adv, board, commander, hand size, combo proximity); default to
**archenemy** (hit the leader), **don't feed the player who's behind**, and **hold the fire until
`canWinNow()` says lethal**. Only script forced attacks once the `LethalityPlanner` has a
validated SPREAD_COMBAT/COMMANDER_DMG route covering the needed opponents.

**P6 — Use Forge's own hints to reduce friction when the pilot yields.** On our own combo
pieces/enablers, set `PlayMain1`, `AILogic`, `NeedsToPlayVar`, `SacMe`, `AIPreference` so the
*stock* AI at least plays enablers in Main1 and doesn't misfire them in windows we don't
override. Cheap, low-risk, complements the pilot.

**Reuse, don't rebuild:** `GameCopier`/`GameSimulator`/`GameStateEvaluator` (deterministic
seed), `Plan`/`Decision`/`formulatePlanWithPhase`, and `getScoreForGameOver` are already the
scripted-plan-with-validation substrate — build the HTN planner *on top of* them.

---

## Dead ends to avoid

- **In-loop MCTS / RL / full-game search.** MTG is Turing-complete; Magarena shows honest MCTS
  needs cheating determinization just to be mediocre; branching explodes (Forge #6726). Keep the
  game loop bounded/scripted — LLM stays at prep/post-run (our current design is correct).
- **Deep multi-turn lookahead.** The LOCM competition: moderate depth + strong eval beats deep
  search. Don't chase depth; invest in the eval/lethal check and the assembly heuristic.
- **Opponent-hand prediction as a priority.** ProphetCoac's mixed results say the ROI is poor in
  4p Commander with huge hidden state — skip it for now.
- **Entering loops without a bound-to-win check.** Forge's Oath+Emrakul / Gruul-Ragebeast bugs
  are what happens when a loop has no payoff gate. Keep the strict order loop-shortcut →
  float-check → `LethalityPlanner`; never enter a loop the planner can't convert.
- **Static single-target aggression (XMage).** Re-score threat every turn.
- **A generic in-game goldfish/probability calculator.** Kelvin-Liu/ManaTap-style tools are
  *deckbuild-time* — use them at prep to set combo priority/redundancy, not in the loop.
- **Leaning on stock Forge AI to fire combos.** Wiki + #3674 confirm it can't; the pilot must own
  the fire window end-to-end (sequence → validate → convert).
- **Free-text plan state (LLM prose).** AgenticSTS: compile plan state into **structured
  artifacts**, not transcripts, or it doesn't scale.
