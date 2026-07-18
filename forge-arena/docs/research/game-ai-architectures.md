# Game-AI Decision Architectures for the Combo Pilot

Research brief for the next-generation decision layer of Forge EDH Arena's scripted combo pilot. The pilot is a deterministic, artifact-driven, no-in-loop-search system that rides specific engine seams. This document surveys the field, extracts principles (not code), and ends with ranked, format-general recommendations aimed at the two headline metrics: **fire-turn** (median 24 today; goldfish speed is t3–5) and **fire→win conversion** (25% today).

Throughout, keep one framing in mind: our pilot already *is* a scripted state machine with validation. The question is not "which architecture do we adopt wholesale" but "which ideas from richer architectures do we graft onto the machine we have, without importing an in-loop search."

---

## Q1 — Architecture Survey

Each entry: what it is · canonical shipped example · strengths/weaknesses · verdict for our pilot.

### (a) Behavior Trees (BT)
A tree of composable nodes — **selectors** (try children in priority order until one succeeds), **sequences** (run children in order, abort on failure), **decorators/conditions** — evaluated top-down each tick. Damián Isla's 2005 GDC talk "Handling Complexity in the Halo 2 AI" popularized them; Halo 3 layered an **Objectives System** on top: a tree of prioritized, self-describing tasks with activation scripts and capacities, letting squads "filter down" to the most important task right now (Isla's "plinko machine").

- **Strengths:** modular, interruptible, designer-authorable, reactive to state changes, cheap to evaluate, easy to unit-test a subtree.
- **Weaknesses:** no lookahead, no native notion of a *goal* or a *plan*; long strictly-ordered sequences become brittle; arbitration is purely left-to-right static priority.
- **Verdict:** BT selector ordering is exactly the "fixed priority order" our pilot already suffers from — adopting vanilla BTs would formalize the arbitration problem, not solve it. The genuinely useful import is the **Halo 3 Objectives layer**: reframe each competing action source as a *self-describing task with a computed priority*, and let a scorer (not tree position) decide. That is the seed of our arbiter (Q3).

### (b) GOAP — Goal-Oriented Action Planning
Jeff Orkin's system for F.E.A.R. (Monolith, 2005; later Deus Ex: Human Revolution, Tomb Raider). Adapts STRIPS: actions have preconditions and effects; the planner runs **A\*** backward from a goal world-state to the current state, assembling a least-cost action sequence at runtime. The agent chooses a goal, then *discovers* the sequence rather than having it authored.

- **Strengths:** decouples goals from the actions that satisfy them; emergent, re-planned sequencing; robust to failure (re-plan when the world changes).
- **Weaknesses:** searches over world-states every re-plan (cost/heuristic sensitive); plans one primitive action at a time; needs a clean symbolic model of effects.
- **Verdict:** The *representation* is the prize, not the runtime A\*. Modeling our levers (ramp, tutor, draw, protect, deploy) as **actions with preconditions and effects over an artifact-state**, plus a **goal** ("combo line assembled and fired"), gives us a principled substrate for both arbitration (Q3) and time-to-goal reasoning (Q4). We do not need in-loop A\* — our combos have a *known* small set of target lines, so the "plan" is mostly precomputed. GOAP's goal/precondition vocabulary is the win.

### (c) HTN — Hierarchical Task Networks
Guerrilla Games has shipped HTN planning since Killzone 2, matured through Killzone 3 and Horizon Zero Dawn. A **compound task** is decomposed by **methods** (each with preconditions) into ordered **subtasks / primitive actions**; planning starts from a root task ("behave") and tries methods in authored order. Unlike GOAP's one-action-at-a-time planning, HTN emits **macro plans** — coherent multi-action sequences. Empirically Killzone 3 plans are short (≤4 actions typical, up to ~12 rare).

- **Strengths:** authored task decomposition captures designer intent; produces long *coherent* plans; **method preconditions + ordering are a clean arbitration mechanism**; hierarchy tames complexity.
- **Weaknesses:** authoring burden; less reactive than a BT; the domain must be hand-modeled.
- **Verdict:** **The best structural fit for a combo pilot.** A combo *is* a compound task: `Win → (Assemble line) → (Acquire missing pieces) + (Reach mana) + (Secure protection) → (Fire outlet)`. Our per-archetype line executors are already de-facto HTN methods; formalizing them — each method carrying explicit preconditions and a chosen decomposition — directly addresses "no explicit goal decomposition" and the missing outlet-usage step (the 25% conversion gap). HTN is the backbone; utility (below) selects among methods.

### (d) Utility AI / Infinite Axis Utility System (IAUS)
Every candidate action is scored on multiple **considerations**, each input normalized through a **response curve** and multiplied together; the highest-scoring action wins. The Sims models needs-satisfaction this way; Dave Mark & Mike Lewis's IAUS (GDC 2015; ArenaNet's Guild Wars 2 heroes) is the canonical data-driven form, built so designers author NPC packages with little code. Dave Mark's *Behavioral Mathematics for Game AI* is the reference.

- **Strengths:** smoothly arbitrates *many competing considerations*; data-driven and tunable; graceful degradation; naturally continuous (near-ties resolve sensibly).
- **Weaknesses:** no lookahead or sequencing — it picks the best *next* action, not a plan; curve tuning is an art; scores can be opaque without instrumentation.
- **Verdict:** **This is the arbitration engine our pilot lacks.** Utility scoring is precisely how to replace "6 sources in fixed priority order" with a signal-driven decision. Its weakness (no sequencing) is covered by pairing it with HTN — utility *selects the method*, HTN *sequences within it*. This utility+HTN pairing is our recommended core.

### (e) Rule-Based / Expert Systems
Hand-written condition→action rules. Classic CCG bots and **Forge's own AI** are this: Forge evaluates each card individually with local heuristics.

- **Strengths:** transparent, deterministic, fast, trivially testable per rule.
- **Weaknesses:** brittle; rules don't compose into global plans; combinatorial rule explosion; no optimization across a turn; documented failure modes — Forge won't double-Shock a 4/4, plays tricks pre-combat "like a beginner," barely acts on the stack, and can infinite-loop (cast Man-o'-War with no target, bounce itself, recast).
- **Verdict:** This is the **stock fallback** we already wrap. It is the floor, not the ceiling. The lesson is cautionary: our pilot's own fixed-priority levers are a rule-based system in miniature and inherit the same "no global arbitration" weakness. Fix that with utility/HTN rather than adding more rules.

### (f) MCTS and Practical Variants
Monte Carlo Tree Search builds a search tree by sampling rollouts, balancing exploration/exploitation (UCB). For hidden information it is adapted via **determinization** (sample a concrete world consistent with observations, solve it as perfect-info) and **Information-Set MCTS (IS-MCTS)** (Cowling, Powley & Whitehouse — search trees of *information sets*, validated on Dou Di Zhu and Spades, beating knowledge-based AI with no game-specific knowledge). In the Hearthstone/SabberStone community the strongest agents use **IS-MCTS + sparse sampling, rolling-horizon evolution, pruned BFS**, with a state-evaluation function and a large per-turn budget (~30s), modeling the opponent's hand as "dummy" cards (determinization).

- **Strengths:** strong play with little domain knowledge; principled uncertainty handling; anytime.
- **Weaknesses:** needs a fast forward-model; MTG's stack + priority explode the branching factor; MTG is **Turing-complete** (Dagstuhl 2019), so rollouts can non-terminate on the very loops our pilot builds; real-time budget pressure.
- **Verdict:** **Off the table as an in-loop engine — by design and by the Turing-completeness hazard.** But two ideas transfer cleanly and *deterministically*: (1) our existing "validate the line on a game-state copy before firing" is a **bounded 1-ply rollout** — generalize it to *score* candidate lines by simulated makespan and pick the minimum; (2) **determinization** is how to reason about hidden information without probability — enumerate a small fixed set of consistent worlds and require a line to succeed across them. No tree, no RNG, still testable.

### (g) Scripted State Machines with Validation
Deterministic FSMs that drive a fixed sequence, gated by validity checks. Canonical examples: fighting-game combo executors, RTS build-order scripts, and speedrun TAS. **This is what our pilot is.**

- **Strengths:** fully deterministic, fast, exactly reproducible, trivially testable — ideal for a batch simulator.
- **Weaknesses:** brittle under input variance (real draws vs. goldfish), and *no arbitration*: transitions are hard-coded, so competing opportunities can't be weighed.
- **Verdict:** Keep the substrate — determinism is a feature for a batch harness and for regression testing. The upgrade is to make *transition selection* signal-driven (utility) and *sequence choice* goal-driven (HTN), rather than positional.

### (h) Hybrid Architectures
Shipped AAA AI is almost always hybrid: a BT with utility-scored selector branches; a GOAP/HTN planner whose primitive actions execute as BT subtrees; an FSM for major modes with utility inside one mode. Recent formalizations (e.g. "GOBT": goal-oriented + utility-based selection inside behavior trees) show the pattern — **utility selects the goal/method, a planner or authored decomposition sequences the execution.**

- **Verdict:** **This is the target architecture.** Concretely for us: a thin top-level FSM for game phase → an HTN-style decomposition of the win condition into tasks → a **utility arbiter** choosing which task/lever to advance this priority window → our existing validated scripted executors as the primitive-action layer. Every layer stays deterministic.

**Fit summary:**

| Architecture | In-loop search? | Arbitrates well? | Sequences well? | Fit for our pilot |
|---|---|---|---|---|
| Behavior Trees | No | Static priority only | Medium | Objectives layer useful |
| GOAP | Yes (A\*) | Via cost | Yes (1 action/step) | Borrow representation only |
| **HTN** | Optional | **Method preconditions** | **Yes (macros)** | **Backbone** |
| **Utility / IAUS** | No | **Excellent** | No | **Arbiter** |
| Rule-based | No | Poor | Poor | Fallback floor |
| MCTS / IS-MCTS | Yes | Emergent | Emergent | Borrow determinization + bounded rollout |
| Scripted+validation | No | None | Yes (fixed) | Current substrate — keep |
| **Hybrid (utility+HTN)** | No | **Excellent** | **Excellent** | **Recommended** |

---

## Q2 — Card-Game AI Specifically

**What the strong ones actually use.** No commercial or research card AI relies on a single paradigm; the strongest are simulation/search + a hand-tuned evaluation function, and the strongest *practical* ones for hidden information use determinization.

| System | Approach | Notes / limits |
|---|---|---|
| **Forge (ours)** | Per-card local heuristics (rule-based) | Java; evaluates cards individually; weak on synergy, barely acts on the stack, can loop. Our pilot exists *because* stock Forge can't drive combos. |
| **MTGA "Sparky"** | Bot logic runs locally on the client | WotC acknowledges the core difficulties: long games make **credit assignment** hard, huge card pool means per-card play-pattern knowledge, decks are stale. Suboptimal by design. |
| **XMage** | Limited simulation + scoring (min-max-ish) over 25k+ cards | Full rules enforcement; AI is weak on deep interactions and poorly documented — a cautionary tale about scaling shallow search across a huge card pool. |
| **SabberStone (Hearthstone)** | IS-MCTS + sparse sampling; also rolling-horizon evolution, pruned BFS | Research platform, ~98% of base cards. ~30s/turn budget. Determinizes opponent hand with dummy cards. Best 2019 agent = IS-MCTS + sparse sampling. |
| **Ward & Cowling 2009** | Monte-Carlo search for *card selection* in MTG | Foundational: MC search **with rule-based rollouts** beat both pure rule-based and stochastic players. Chose MTG explicitly as a test bed for imperfect-info search + opponent modeling. Key lesson: **a good scripted policy inside the rollout is what makes search work** — search amplifies a decent heuristic, it doesn't replace one. |
| **IS-MCTS (Cowling/Powley/Whitehouse)** | Search over information sets | Beat knowledge-based AI on Dou Di Zhu and Spades with *no* game-specific knowledge; identifies determinization's core error (it searches a tree that doesn't match the true imperfect-info game). |
| **Henry Ward et al. 2020** | ML for MTG *drafting* | Deck construction, not in-game play — separate subproblem. |
| **UrzaGPT (2025), LLM-MTG-DDA (2025)** | LoRA-tuned / prompted LLMs for card play & dynamic difficulty | Emerging; promising for card-choice and difficulty tuning, but non-deterministic, slow, and unsuited to a batch harness needing millions of reproducible decisions. |

**Why MTG is harder than Hearthstone (and why this shapes our design):**

1. **Priority + the stack.** Any player can act on *any* player's turn, at instant speed, in response to items on the stack. Hearthstone actions happen only on your own turn. This multiplies the effective decision points and makes rollouts branch violently — and is exactly why in-loop search is impractical here and our pilot rides specific seams (`chooseSpellAbilityToPlay`, `declareAttackers`, `confirmAction`).
2. **Turing-completeness (Dagstuhl 2019).** MTG can encode arbitrary computation; the combos we *build* are unbounded loops. A naive forward-model rollout can non-terminate — hence our bounded-product shortcut (1000 mana / 30 tokens) is not a hack but a *necessary* abstraction, mirroring how StarCraft planners abstract income rather than simulate every worker.
3. **Four-player hidden information.** Three hidden hands + libraries mean the space of consistent worlds is enormous; determinization needs many more samples than in a 2-player game. Practical consequence: reason over a *small fixed* determinization set, not a probability distribution.
4. **Sparse, delayed reward.** Games are long; a decision's payoff arrives many turns later — the credit-assignment problem WotC cites. This is why a *scripted, goal-directed* pilot (which knows the win condition a priori) beats a reward-learning agent for our purpose: we don't need to *discover* the goal, only to *reach it fast*.

**Net:** the field's own evidence says: (a) pair search/scoring with a strong scripted policy (Ward & Cowling), (b) determinize hidden info into a few concrete worlds, (c) abstract unbounded loops into bounded products, (d) exploit that we *know* the goal. Our architecture should double down on the scripted policy and add principled *arbitration* and *scheduling* around it — not import a tree search.

---

## Q3 — The Arbitration Problem

Our pilot has ~6 competing action sources per priority window — line step, ramp, tutor, pre-assembly, payoff deploy, stock fallback — resolved in a **fixed order**. Fixed order is the disease shared by BT selectors and rule-based systems: it cannot say "tutor is usually third, but this turn we're one piece from lethal and safe, so fire the line instead."

**How the surveyed architectures arbitrate:**

| Architecture | Arbitration mechanism | Transferable idea |
|---|---|---|
| BT | Static left-to-right selector priority | (what we have — reject) |
| Halo 3 Objectives | Tasks self-describe a **computed priority**; filter to top | Make each source emit a *score*, not occupy a *slot* |
| GOAP | A\* picks the **least-cost** plan satisfying the goal | Cost = a proxy for "closest to firing" |
| HTN | **Method preconditions** gate applicability; ordered fallback | Hard gates before soft scoring |
| **Utility / IAUS** | **Multi-axis score via response curves; max wins** | **The core selection rule** |

**Recommended arbitration design — a deterministic utility arbiter over a fixed signal set.**

Replace the fixed priority list with: *each action source proposes an action with a bounded utility score; the highest score wins; a fixed tie-break preserves determinism.* Structure it in two stages so gates stay hard and scoring stays soft:

**Stage 1 — HTN-style precondition gates.** A source only enters the contest if its method preconditions hold (e.g. "deploy payoff" requires the payoff in hand and mana available). This prunes the field before any scoring — cheap, exact, testable.

**Stage 2 — Utility scoring over a small signal set.** Score each surviving proposal from these signals, each passed through a monotone response curve and combined (product of curves, IAUS-style, so any single veto-worthy factor can zero the score):

| Signal | Definition (deterministic, from the hidden-info view + artifact data) | Drives |
|---|---|---|
| **Distance-to-fire** | Min number of acquisition/mana steps until a known line is legal (a landmark count — see Q4) | The dominant term. Actions that *reduce* it score high. |
| **Mana runway** | Available + projected mana this/next turn vs. the cheapest completable line's cost | Gates fire vs. ramp; low runway boosts ramp/rock deploys |
| **Threat level** | Opponents' fastest observed clock + visible interaction density (counterspells/removal seen or mana up) | High threat → bias toward *finishing now* or holding protection |
| **Protection window** | Do we hold/could we cheaply hold protection; is the fire safe across the determinization set | Gates go/no-go on firing (the conversion lever) |
| **Redundancy** | Count of backup pieces / alternate lines still live | Lowers the cost of "spend a piece now" |

Selection rule: `score(source) = Π curve_i(signal_i)`; pick `argmax`; ties broken by a fixed source priority (the current order becomes the *tie-break*, not the decision). This is IAUS with the goal wired in — "goal-directed utility."

**Keeping it deterministic and testable:**
- Every signal is a **pure function** of the hidden-info view + artifact tables — no RNG, no seed, no wall-clock.
- **Determinize** the "is the fire safe?" and "threat" signals by evaluating against a *fixed, ordered* set of consistent opponent worlds (e.g. worst-case: assume the visible open mana is a counterspell), not a sampled distribution.
- Response curves live in a **data table**, so tuning never touches control flow and each curve is unit-testable in isolation.
- **Log the full score vector** for every decision. Reproducible batch runs then let you regression-test "given state X, source Y must win," which is impossible with a hidden fixed order.

This single change is the highest-leverage fix for the "levers run in fixed priority order rather than being arbitrated" gap, and it directly attacks conversion (the protection-window and threat signals gate reckless fires) and fire-turn (distance-to-fire prioritizes the action that most shortens assembly).

---

## Q4 — Time-to-Goal Optimization

The right analogy for "assemble a 2–3 card combo as early as possible under draw uncertainty" is **RTS build-order optimization**: reach a target composition in minimum makespan, subject to dependencies and resources. Churchill & Buro's StarCraft work (AIIDE 2011; continuous re-optimization, CoG 2019) is the reference, and its techniques transfer almost line-for-line.

| Build-order technique | What it does | Transfer to combo assembly |
|---|---|---|
| **Depth-first branch & bound** on a goal | Recursive search for the min-makespan action sequence reaching a goal, pruned by bounds | We don't run this in-loop, but it is the *offline* tool to precompute the optimal acquisition line per opening-hand class (see Q5 #8). |
| **Concurrent-action ordering** | Simultaneously-legal actions are independent, so fix one order instead of permuting | Within a turn, deploy independent enablers (rock, cantrip, land) in a fixed canonical order — no need to reason about their sequence. |
| **Macro actions** | Bundle repeated/related primitives ("build 6 workers") to cut search depth | Bundle "ramp → tutor → protect" into a single **HTN macro** the arbiter treats as one move (Q5 #6). Cuts decision depth and encodes intent. |
| **Income / resource abstraction** | Use fixed mineral/gas rates instead of simulating workers | Abstract mana development into a **projected mana curve** rather than simulating each land drop — this *is* the "mana runway" signal. |
| **Fast-forward `When(S,R)`** | Jump time to the earliest moment a resource is available; skip null steps | "Act as soon as legal, don't hoard": deploy rocks/card advantage the first turn you can — never sandbag an enabler. |
| **Admissible landmark lower bound** | Sum durations of not-yet-started prerequisite tech as a min-time estimate for pruning | **This is our `distance-to-fire` metric.** Min turns to acquire each missing piece (tutor=fast, dig=medium, raw draw=slow) → a landmark lower bound on fire-turn. Cheap, monotone, perfect for the arbiter. |
| **Makespan objective / "as soon as legal"** | Time-optimal plans start every action the instant it's legal; hoarding never helps | Direct rule for the pilot: advance the *earliest-completing* line, and take each enabling action the turn it becomes legal. |

**Handling draw uncertainty — receding-horizon replanning.** Build orders in a live game aren't executed open-loop; robust variants **re-optimize continuously** as the state changes. The combo analog: after each draw / priority window, recompute distance-to-fire across *all* live lines and commit only the next action, not the whole plan. This is GOAP's "re-plan on world change" married to the build-order makespan objective, and it is what turns a fixed script into something that exploits a lucky tutor or routes around a discarded piece.

**Model the combo as a dependency graph and schedule earliest-start.** Represent each line as pieces + enablers + mana with dependency edges; compute an earliest-start schedule (critical path = distance-to-fire). The critical path tells you *which missing piece to tutor for first* — the one on the longest remaining chain — which is a sharper policy than "tutor in fixed priority." Prefer acquisition actions by *rate*: tutor (deterministic, 1 turn) > selective dig > raw draw (stochastic), exactly as StarCraft prefers the production path with the best time-to-unit.

Together these attack the fire-turn=24 problem at its root: today's fixed-priority levers don't ask "what is the *fastest remaining path* and which single action shortens it most?" A landmark distance-to-fire metric + earliest-start scheduling + act-as-soon-as-legal makes that the pilot's central objective.

---

## Q5 — Top Recommendations (Ranked)

Format-general changes, each: borrowed pattern · module changed · expected effect on fire-turn / conversion · size (S/M/L).

**1. Utility arbiter replacing the fixed lever order — (borrow: IAUS / Halo 3 Objectives) · module: lever arbitration layer · effect: conversion ↑↑, fire-turn ↑ · size: M.**
The keystone fix. Sources emit scores from the Q3 signal set; argmax wins; old order becomes the tie-break. Directly closes the "fixed priority order" gap and gives every later recommendation a place to plug in.

**2. Landmark "distance-to-fire" metric + earliest-start scheduling — (borrow: Churchill-Buro landmark lower bound + critical path) · module: route planner / detection · effect: fire-turn ↑↑ · size: M.**
Compute min-turns-to-legal per live line and the critical missing piece. Feeds the arbiter's dominant signal and redirects tutors to the piece on the longest chain. The single biggest lever on median fire-turn.

**3. Outlet-usage / goal-decomposition module — (borrow: HTN decomposition + GOAP goal) · module: scripted conversion · effect: conversion ↑↑ (the 25% problem) · size: M.**
Model `Win` as a compound task requiring *outlet + fuel + lethal check*, not just "loop assembled." Today the pilot assembles then flounders; an explicit decomposition that treats "route the bounded product into a win" as a required subtask with its own preconditions is the direct fix for fire→win conversion.

**4. Receding-horizon replanning each priority window — (borrow: continuous build-order re-optimization + GOAP replan-on-change) · module: top-level loop · effect: fire-turn ↑, robustness ↑ · size: M.**
Recompute distance-to-fire over all live lines every draw/window; commit only the next action. Turns the open-loop script into one that exploits good draws and routes around disruption. Natural once #1 and #2 exist.

**5. Bounded line-scoring via game-copy simulation — (borrow: MCTS rollout / DFBB bound, but 1-ply and deterministic) · module: line executors · effect: fire-turn ↑, conversion ↑ · size: M.**
Generalize the existing "validate on a copy" from a boolean into a *makespan/quality score*; when multiple lines are viable, fire the one with the lowest simulated cost. No tree, no RNG — a strict extension of what already runs.

**6. Acquisition macro-actions as HTN methods — (borrow: HTN macros + concurrent-action ordering) · module: line executors · effect: fire-turn ↑ · size: S/M.**
Bundle "ramp → tutor → protect" into single methods with explicit preconditions; deploy independent enablers in a fixed canonical order within a turn. Reduces decision depth and encodes intent; low risk.

**7. Threat/protection-aware go/no-go gate before firing — (borrow: utility gate + determinized worst-case world) · module: conversion / route · effect: conversion ↑ · size: S.**
Before firing, evaluate safety against a fixed worst-case determinization (assume visible open mana = interaction). Gate or hold for protection. Small, targeted patch on wasted fires.

**8. Offline per-opening-hand assembly plans — (borrow: build-order search — DFBB / genetic algorithms) · module: pre-assembly · effect: fire-turn ↑ · size: L.**
Precompute optimal acquisition sequences per opening-hand class offline (branch & bound or GA over the dependency graph), loaded as a lookup the arbiter consults. Highest ceiling on fire-turn, highest cost; do last, after #1–#4 prove the signal set.

**Sequencing:** ship #1 (arbiter) and #2 (distance-to-fire) together — they are co-dependent and unlock the rest. #3 (outlet module) is the independent big win for conversion and can proceed in parallel. #4–#7 are incremental refinements on that base; #8 is an optional long-horizon investment.

---

## Sources

**Architectures:** [Isla — Halo 2 AI / behavior trees (GameAIPro, AltDevBlog)](https://jahej.com/alt/2011_02_24_introduction-to-behavior-trees.html) · [Isla — Halo 3 Objectives System](https://www.readkong.com/page/building-a-better-battle-system-the-halo-3-ai-objectives-8888817) · [Orkin — Building the AI of F.E.A.R. with GOAP](https://www.gamedeveloper.com/design/building-the-ai-of-f-e-a-r-with-goal-oriented-action-planning) · [Applying GOAP to Games (Orkin, PDF)](https://www.semanticscholar.org/paper/Applying-Goal-Oriented-Action-Planning-to-Games-Orkin/0c35d00a015c93bac68475e8e1283b02701ff46b) · [Hierarchical AI for Multiplayer Bots in Killzone 3 (GameAIPro)](http://www.gameaipro.com/GameAIPro/GameAIPro_Chapter29_Hierarchical_AI_for_Multiplayer_Bots_in_Killzone_3.pdf) · [Killzone 2 Multiplayer Bots — Guerrilla](https://www.guerrilla-games.com/read/killzone-2-multiplayer-bots) · [Utility System (Wikipedia) + IAUS](https://en.wikipedia.org/wiki/Utility_system) · [Intrinsic Algorithm — IAUS (Dave Mark)](https://www.gameai.com/iaus.php) · [The Genius AI Behind The Sims (GMTK)](https://gmtk.substack.com/p/the-genius-ai-behind-the-sims) · [GOBT: Goal-Oriented + Utility in Behavior Trees](https://www.jmis.org/archive/view_article?pid=jmis-10-4-321) · [Beyond State Machines: Utility, BT, GOAP (Socratopia)](https://www.socratopia.app/library/game-code-anatomy-en/chapter-12).

**Card-game AI:** [Ward & Cowling — Monte Carlo search applied to card selection in MTG (CIG 2009)](https://pure.york.ac.uk/portal/en/publications/monte-carlo-search-applied-to-card-selection-in-magic-the-gatheri) · [Cowling, Powley & Whitehouse — Information Set MCTS](https://eprints.whiterose.ac.uk/id/eprint/75048/1/CowlingPowleyWhitehouse2012.pdf) · [Whitehouse et al. — Determinization + IS-MCTS for Dou Di Zhu](http://orangehelicopter.com/academic/papers/cig11.pdf) · [SabberStone (HearthSim)](https://github.com/HearthSim/SabberStone) · [Kowalski & Miernik — Summarizing Strategy Card Game AI Competition (arXiv 2305.11814)](https://arxiv.org/pdf/2305.11814) · [Forge AI overview (mtgrares)](http://mtgrares.blogspot.com/2010/05/forges-awesome-ai.html) · [XMage (magefree/mage)](https://github.com/magefree/mage) · [MTGA Sparky — how bots run locally](https://www.mayer.cool/writings/I-Hacked-Magic-the-Gathering/) · [Ward et al. — AI solutions for drafting in MTG (arXiv 2009.00655)](https://arxiv.org/pdf/2009.00655) · [UrzaGPT — LoRA-tuned LLMs for card play (arXiv 2508.08382)](https://arxiv.org/pdf/2508.08382) · [LLM dynamic difficulty adjustment in MTG (ScienceDirect 2025)](https://www.sciencedirect.com/science/article/abs/pii/S1875952125000771) · [MTG is Turing-complete (Dagstuhl 2020)](https://drops.dagstuhl.de/opus/volltexte/2020/12770).

**Time-to-goal / build orders:** [Churchill & Buro — Build Order Optimization in StarCraft (AIIDE 2011)](https://davechurchill.ca/publications/pdf/aiide11-bo.pdf) · [Churchill — Robust Continuous Build-Order Optimization (IEEE CoG 2019)](https://ieee-cog.org/2019/papers/paper_85.pdf) · [Build-order techniques summary (readkong)](https://www.readkong.com/page/build-order-optimization-in-starcraft-4580919) · [Brandy — Genetic algorithms for SC2 build orders](https://lbrandy.com/blog/2010/11/using-genetic-algorithms-to-find-starcraft-2-build-orders/) · [StarCraft II Build Order Optimization via DRL + MCTS (arXiv 2006.10525)](https://arxiv.org/pdf/2006.10525).
