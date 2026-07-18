# Phase 6 — Conversion, Coverage, and Speed (v3)

*The plan for taking the arena from "combos fire" to "any dropped-in deck plays Magic well: assembles its combos early, fires them, converts them into wins, and closes games at realistic speed." Iterated adversarially (Claude ↔ Gemini) before execution; version log at bottom.*

## 0. Mission and acceptance bar

**Mission:** drop in ANY Commander deck → prep detects its combos and win routes → the pilot assembles early, fires every viable combo when present, converts fires into wins, and plays credible Magic in between. No deck-specific logic anywhere in main code.

**Phase-exit criteria (measured on a seed-paired 200-game 4-pilot batch, rotation-aware attribution):**

| Metric | Today (pr34-validation) | Phase-6 exit bar |
|---|---|---|
| **Same-turn conversion: engine fired WITH an outlet available (hand/battlefield/command) → win that turn** | ~0% outside purphoros | **≥ 90%** *(Gemini R1: the defining combo metric — a fire-to-win gap of turns means the module failed)* |
| Fire→win conversion (per fired seat, any horizon) | ~25% | **≥ 60% every deck** |
| Fire-turn median | 24 | **≤ 12** |
| Win-turn median (all games — value wins count) | 32 | **≤ 18** (secondary health metric) |
| Timeout draws | 36% | **< 10%** |
| Combo coverage: combos with sim-verified bindings | 9/42 (21%) | **≥ 80%, and 100% of bindable-by-existing-archetype** |
| Gauntlet | 8/8 rows | **1 row per bound combo, all firing** |
| Crash rate | ~5% (upstream AI recursion) | **< 1%** |

The bar numbers are proposals — Ben adjusts, then they freeze for the phase.

## 1. Evidence base (why these workstreams)

- **long-200 + pr34-validation (398 games, seed-paired):** every archetype fires live; conversion is the wall. Purphoros converts 6/6 because its payoff IS an outlet (token-ETB ping). Selvala banks 1000 mana 28× and wins 4. Urza 0/3. Giada wins 41 with zero combo fires (stock aggro + pilot shields + lethal alpha).
- **Stall autopsy (11 distinct):** unanimous — bindings correct, conversion behavioral. Found the re-fire suppression bug (fixed, PR-35).
- **Coverage audit (2026-07-18):** 42 combos across the pod, 9 bound (21%). Urza: 22/23 unbound — the pod's densest combo deck is effectively unpiloted.
- **combo-conversion-playbook.md:** the 13-class outlet taxonomy + conversion state machine + fire-timing + mulligan theory. The design source for Workstream A.
- **game-ai-architectures.md** *(in flight)*: decision-architecture survey for the arbitration design (Workstream C).
- **mtg-rules-digest-conversion.md** *(in flight)*: CR-derived legal constraints for the conversion module (priority windows, pool-empties-at-phase-end, SBA timing, loop shortcuts).

## 2. Workstream A — the Conversion Module (the big lever)

A new pilot module, `ConversionPlanner`, owning everything after a fire. Replaces the current thin route-pick + payoff-deploy.

**A1. Outlet vocabulary (win-routes/5).** New payoff classes from the playbook taxonomy: `x_drain_each_opponent` (premium), `x_damage_single`, `activated_ping_sink`, `lifegain_battery`, `aristocrat_drain`, `etb_ping_each` (exists as ping_each_opponent), `mass_pump` (exists), `alt_win` (win-the-game text, by condition), `self_draw_engine` (the DIG class), `mill_opponents` (delayed flag). Every class carries structural flags: `hits_all_opponents`, `hits_self`, `needs_combat`, `resolves_delayed`, `feeder_required` (untap/counter/token/mana source that must be present). Detection = oracle-text predicates in PayoffRules; ambiguity traps from playbook §6 encoded as tests.

**A2. The conversion state machine.** On every own MAIN with a fired-but-unconverted engine (fresh or re-fired pool), scanning **hand ∪ battlefield ∪ COMMAND ZONE** (Gemini R1: a Commander AI that forgets the command zone is useless — Urza/Thrasios-class commanders ARE the outlet or the dig):
1. Table-wide outlet castable/activatable? → fire it once at scripted X / full amount.
2. Single-target outlet? → **loop-to-lethal**: repeat activation/cast per opponent in threat order until dead or resources exhausted.
3. No outlet available but a self-draw engine (X-draw, activated draw, commander dig ability) reachable? → **dig with the mana**: draw big, re-scan, go to 1. Guard: never draw past library-minus-one without an alt-win or in-hand kill.
4. None of the above → dump pool into the biggest castable draw/tutor/creature (commander included), bank the rest, and let the re-fire window (PR-35) refresh next turn.
Invariant (the playbook's first law): **never end a turn with an unused engine and an unsearched library.**

*Gemini R2 guard rails, all adopted:* (a) **color profile** — every outlet-castability check compares the pool's color (ShortcutOrder.poolColor + battlefield sources) against the outlet's cost; a colorless pool never commits to a dig unless a colorless-castable outlet or filter remains reachable; (b) **dig reservation** — before any dig, the outlet's projected cast cost is RESERVED out of the pool (a mana-neutral draw loop like the Top family must never strand the pilot with a drawn outlet it cannot cast); (c) **commander tax** — every command-zone castability predicate adds the current tax (2× prior casts) and increments it across simulated loop iterations; (d) **deck-empty guard** stays: never draw the final card without an alt-win or secured kill.

*Scoping note (Gemini R1, adjudicated):* v1 of the module acts at **sorcery-speed own-turn windows** — every combo in the current pod enters at MAIN1 by binding (`entry_phase`), and determinism/testability beat instant-speed generality this phase. The binding vocabulary keeps `entry_phase` so instant-speed lines (Flash-Hulk class, end-step Thrasios) become a Phase-7 extension of the same seams, not a rewrite. **Phase-transition trap** (pool empties at phase end, CR 500.4): outlets carry a `phase_requirement` flag; combat-dependent outlets are ranked below same-phase outlets, and the pool is never assumed to survive into combat — creatures deploy IN the pool's phase, then combat runs pool-free.

**A3. Loop-to-lethal executor support.** A new controller capability: repeat a proven activation N times at real resolution (bounded, watchdog-guarded, per-opponent targeting) — the Ballista/Reservoir pattern. Validation: one activation on a copy must reduce a life total (the injectCopy pattern generalized). **Interruption handling (Gemini R1):** each iteration is a normal priority-passing step, so opponent interaction lands BETWEEN iterations; the executor re-verifies outlet presence per iteration and falls into the existing abort/re-fire machinery on piece loss — no special interrupt handler, the step model IS the interrupt handler. **Elimination re-evaluation:** after any opponent's life reaches 0, SBAs remove them and their permanents leave (CR 800.4a) — the loop re-reads the alive-opponent set every iteration, never a cached list.

**A4. Legal-constraint compliance.** Apply the rules-digest checklist (pool lifetime within phase, priority windows, holding priority on own win triggers, SBA re-evaluation after each elimination mid-loop).

**Exit test:** gauntlet rows where the engine + outlet are present fire AND WIN same-turn; rows with engine + dig + outlet-in-library win via the dig path.

## 3. Workstream B — full combo coverage

**B1. Bindgen sweep** *(running)*: all 33 unbound combos through Gate 3.5 (LLM binding + sim verification). Expected outcome: some bind to the five existing archetypes; the rest produce archetype proposals.
**B2. Archetype gap analysis (EMPIRICAL — 30 bindgen proposals clustered, 2026-07-18):** Urza's unbound tail converges on exactly TWO families: (a) **CastRecastDrawLoop** — Sensei's Divining Top + cost-reducer + draw engine: tap to draw + re-top, recast free; bounded product = CARDS DRAWN (the playbook's §1.11 dig engine as a provable loop — this archetype's product feeds the conversion module's dig path directly); (b) **CastBounceLoop** — Tidespout Tyrant / bounce-trigger + free mana rocks: cast trigger bounces the rock, recast, net mana + unbounded cast triggers (storm-count/trigger product; Mana Vault/Grim Monolith variants are mana-positive). Building these two archetypes converts most of Urza's 22 unbound combos in one stroke. Each new archetype = executor + validation + bindings + gauntlet rows.
**B3. Detection-only fallback stays honest:** combos that stay unbound remain detection-only and are REPORTED per batch (no silent coverage claims).

**Exit test:** coverage table ≥ bar; every bound combo has a green gauntlet row.

## 4. Workstream C — time-to-fire (assembly speed)

**C1. Action arbitration** (design LANDED — game-ai-architectures.md): the survey's verdict is a **hybrid utility-arbiter + HTN decomposition over our existing scripted-with-validation substrate** (the pattern shipped hybrids use: utility selects the goal/method, authored decomposition sequences execution; no in-loop search — MTG's Turing-completeness and 4-player stack make rollouts a hazard, and Ward & Cowling's core lesson is that search only amplifies a good scripted policy anyway). Two-stage design: (1) HTN-style **precondition gates** prune ineligible levers (hard, exact, testable); (2) a **deterministic utility score** over five signals — distance-to-fire (a Churchill-Buro-style landmark lower bound: min acquisition/mana steps to a legal line — the DOMINANT term), mana runway, threat level, protection window, redundancy — each through a data-table response curve, **weighted-sum combined (Gemini R2: product combination flattens the gradient when any factor is zero — anything truly veto-worthy is a Stage-1 HARD GATE, never a multiplier)**, argmax wins, and the CURRENT fixed order becomes the tie-break. Hidden information handled by fixed worst-case determinization (visible open mana = assumed interaction), never sampling. Full score vector logged per decision for regression tests. Receding-horizon: recompute distance-to-fire across ALL live lines each window, commit only the next action (exploits lucky tutors, routes around discards). The critical-path rule redirects tutors to the piece on the longest remaining chain.
**C2. Fire-timing gate** (playbook §2): open-interaction estimate + protection-in-hand flag; fire when clear, dig when not — replaces patience=0 always-fire. **Static-hate coverage (Gemini R1+R2, adjudicated twice):** lock pieces are caught organically by validation-on-copy (the proof runs under the real static layer and refuses honestly) — but R2 is right that silent refusal is stalling, not playing. Adopted: a static-blocked validation surfaces **`BLOCKED_BY_PERMANENT` with the suspected blocker** in SimResult's blocked-reason vocabulary; the arbiter treats it as a signal that elevates removal-flavored actions (minimum viable this phase: telemetry + tutor/stock bias toward answers; full removal targeting is a stretch goal). Gauntlet row: hate piece on the copy → refusal event carries the blocker name.
**C3. Tutor/dig aggressiveness:** tutors count as piece-equivalents in mulligan and assembly distance; X-dig spells join the structural tutor class.

**Exit test:** fire-turn median ≤ 12 on the standard batch; goldfish gauntlet unchanged (no regression to t3-5 fires).

## 5. Workstream D — infrastructure and drag removal

**D1. Upstream recursion patch** (`// ARENA-PATCH` + UPSTREAM-PATCHES.md): break the AiAttackController ↔ shouldPumpCard mutual recursion (depth guard) — ~5% of games crash on it today.
**D2. Moxfield fetcher** (moxfield-hello key available): `prep.sh --moxfield <url>` → decklist → .dck → standard prep. This is the "drop in any deck" front door.
**D3. Rotation-aware BatchStats audit:** verify per-deck attribution in reducers uses per-game seat arrays (the analysis-script bug, checked in the tool itself).
**D4. Stock-AI decision timeout hygiene at 6 workers** (existing mitigation holds; document).

## 6. Validation protocol (fixed for the phase)

1. Every PR: full suite + gauntlet green before commit.
2. Every behavioral PR: seed-paired 200-game batch vs the previous baseline; report the exit-criteria table.
3. Phase exit: 1k seed-paired A/B (pilot-on vs pilot-off) — the thesis measurement, run once, on Ben's call.
4. All analysis rotation-aware; stall dumps autopsied per batch.

## 7. PR sequence (proposed)

| PR | Content | Workstream |
|---|---|---|
| 36 | win-routes/5 outlet vocabulary + PayoffRules predicates + re-preps (adds `deck_empty_win`, `phase_requirement`, `hits_all_opponents`, `hits_self`, `feeder_required` flags) | A1 |
| 37 | **Loop-to-lethal executor + validation seam** (Gemini R1: execution before routing — provable standalone with scripted inputs) | A3 |
| 38 | **ConversionPlanner state machine** (hand ∪ battlefield ∪ command scan, dig-with-mana, pool-legal sequencing) feeding the PR-37 executor | A2, A4 |
| 39 | Bindgen-driven archetype #6 (highest-coverage cluster) | B2 |
| 40 | Archetype #7 + coverage gauntlet expansion + static-hate refusal row | B2, C2 |
| 41 | Arbitration + fire-timing gate | C1, C2 |
| 42 | Upstream recursion patch + Moxfield fetcher + BatchStats audit | D |

Order rationale: A before C (conversion multiplies existing fires; speed multiplies conversion); within A, executor before state machine (test the kill mechanism with scripted inputs, then build the router that feeds it — Gemini R1's dependency-inversion fix); B interleaves as bindgen results arrive; D whenever a slot opens.

## 8. Risks / open questions (for adversarial review)

- Outlet detection false positives (symmetric effects, "each player") — mitigation: `hits_self` flag + life-buffer check + sim validation before use.
- Loop-to-lethal wall-clock cost at real resolution (the 10^4-pool lesson) — mitigation: bounded N, per-iteration game-over check, watchdog.
- Arbitration nondeterminism risk — mitigation: integer scoring, total ordering, seeded tie-breaks, unit tests per signal.
- Are the exit bars right? (fire-turn ≤ 12 may be aggressive for 3-piece combos.)
- Gemini review rounds appended below.

## Version log
- v1 (2026-07-18): initial draft from batch evidence + playbook + coverage audit. Research docs pending.
- v2 (2026-07-18): Gemini adversarial round 1 adjudicated — command-zone scan, same-turn-conversion exit metric, PR 37/38 swap, instant-speed scoping note, phase-transition flags, loop-interruption-by-step-model; game-ai-architectures.md folded (utility+HTN hybrid, distance-to-fire landmark, worst-case determinization, receding horizon); bindgen sweep results folded (34 proposals → CastRecastDrawLoop + CastBounceLoop clusters).
- v3 (2026-07-18): Gemini round 2 adjudicated — weighted-sum arbiter scoring (product flattens), BLOCKED_BY_PERMANENT surfacing to the arbiter, commander-tax-aware castability, color-profile + dig-reservation guard rails on the conversion state machine.
