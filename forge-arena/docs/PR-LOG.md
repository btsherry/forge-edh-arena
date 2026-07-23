# Running PR log

One paragraph per PR: what was added and why, plus new files/artifacts it
introduced. MAINTENANCE RULE: append an entry with every PR commit. Detail
lives in the commit messages; this is the map.

## Foundation (PRs 1–14) — harness, prep gates, first executor
- **PR-1..5** Module skeleton, versioned JSON schemas, headless bootstrap and
  RNG seeding; EngineFacade with arena limits and ArchUnit layer isolation;
  dual-sink event recording (per-game JSONL + tailable run.log); seeded
  Latin-square seat rotation; worker-pool batch driver with smoke/batch
  scripts. *Artifacts introduced: run dirs with game-records.jsonl,
  events/NNNN.jsonl, run.log, batches.jsonl ledger.*
- **PR-6..10** The prep gate chain: Gate 0 ingest (deck-cards.json + dossier
  skeleton), Gate 1 legality lint vs pinned banlist (lint-report.json), Gate 2
  implementability/goldfish compile (implementability-report.json), canary
  divergence proof, Gate 3 Commander Spellbook client (combos.json,
  advisory-combos.json, route-coverage.json).
- **PR-11..13** SeatView hidden-info read-model (the ONLY game surface the
  combo layer may touch) + detection-only ComboTracker; `arena prep` dossier
  compiler; LLM classification fallback + route library (prep autopsy).
- **PR-14** TapForManaUntapLoop, the first executor archetype, and the
  sim-validation seam: prove a loop on a GameCopier copy before firing.
  *Global artifact: bindings/executor-bindings.json.*

## Pilot and conversion (PRs 15–39) — the combo pilot learns to fire
- **PR-15..19** ComboAwareController with line mode and decision telemetry;
  LethalityPlanner + RoutePlan; loop shortcut + stall watchdog; TutorRanker
  (tutor-priorities.json); ASSEMBLY/DEPLOY stages — first assembled,
  proven, fired, WON game; affordability gate.
- **PR-20..23** Gate 3.5 bindgen (LLM binding generation, sim-verified) and
  Gate 3.6 stall autopsy; turn_state/turn_summary play telemetry; BatchStats
  reducers with funnels, fingerprints, and seed-paired A/B compare.
- **PR-24..30** Payoff-visible tutor urgency + distance-aware mulligan;
  scripted DEPLOY_WIN conversion; pre-assembly speed work; BounceRecastLoop
  and SpellCopyLoop archetypes (+ token-flood shortcut — Purphoros pilots);
  X-rider guards; goldfish gauntlet; ramp sequencing.
- **PR-31..35** PairedPlay + ImprintCopyLoop archetypes; copy-fidelity shim
  (imprint/exile links GameCopier drops); continuous lethal-check alpha;
  window-bounded re-fire. Research: combo-conversion-playbook.md,
  game-ai-architectures.md, mtg-rules-digest-conversion.md.
- **PR-36..39** win-routes/5 outlet vocabulary; loop-to-lethal drill;
  ConversionPlanner state machine (spend the banked engine: table-wide →
  drill → dig); CastBounceManaLoop archetype; run-log observability.

## Measurement and correction (PRs 40–53)
- **PR-40..45** Honest-measurement pass: sameTurnWin metric, abort taxonomy,
  deck-swap safety across all 12 pod permutations, Moxfield ingestion
  (later found nonviable vs Cloudflare — export files are the interface).
- **PR-41 family** The haste-split saga: win-routes/6 split, step-resolution
  failure naming, dig-vs-tutor priority, the pool-blind tutor, and the tutor
  seam (chooseSingleCardForZoneChange) — 255 tutor decisions after 366 games
  of zero.
- **PR-46..52** 64MB deep-stack game thread; LifegainPingLoop (Giada's
  combo archetype); PairedPlayFinder reads card text for wipe+protect pairs
  Spellbook cannot see (paired-plays.json); reentrancy guard for the
  infinite-recursion crash (UPSTREAM-PATCHES.md #1); SelfTopdeckRecastLoop;
  threat-score targeting; hygiene pass.
- **PR-53** Turn cap 35 by measurement; bounded surefire heap (the fork
  SIGSEGV was G1 GC, not stack — corrected the PR-52 record).

## Phase 7 — the prediction bet (PRs 54–66): built, measured, rejected
- **PR-54/55/56** Three proxy bugs, one shape: haste-ownership vs can-attack;
  digging outranking a live kill; clock-driven vs board-driven replanning.
- **PR-57..61** KillPredictor primitive (hang-guarded, concurrency-proven),
  alpha-strike observation, budget re-measured in production, honest
  no-answer causes, highest-yield mana ability resolution, the decision arm.
  Plans: PHASE-7-PLAN.md.
- **PR-62..66** A/B verdict: 33 steered attacks, zero benefit — do not cut
  over. Bouncer affordability; five Urza bindings via existing archetype;
  SelfBounceRecastLoop (found by ingestion, not a human); synergy classes
  queued (PR-66). Research: architecture-survey-2.md, PROJECT-BRIEF.md.
- **PR-67** THE PIVOT: seeded batches never reproduced (15/30 diverged).
  Per-thread RNG upstream (UPSTREAM-PATCHES.md #2); prediction stack deleted.
  Every prior A/B retroactively unreliable; first trustworthy baselines follow.

## Phase 9–10 — ingestion rebuild and deck fixes (PRs A–D2, 68–77)
- **Ingestion** (docs: PHASE-9-PLAN.md, INGESTION-WORKFLOW.md,
  INGESTION-SPEC.md, ingestion-findings.md, ingestion-trial-purphoros2.md;
  skill: .claude/skills/ingest-deck). Prep was blind to 60–83% of nonland
  cards while reporting pass. Rebuilt on Forge card SCRIPTS as T0 ground
  truth + 341-card LLM pass (7 subagents), script-evidence enforced.
  *New per-deck artifacts: capability-inventory.json,
  discovered-synergies.json, proposed-vocabulary.json, win-plan.json,
  ingestion-report.json. Global: capability-registry.json.*
- **PR-A/B/C** Selvala's x_spell_outlet + mana-lifetime (phase) rule; Urza's
  restricted-mana accounting + ability-cost-reducer split; amplifier-aware
  lethality with multipliers-first pessimism. First trustworthy movement:
  Selvala off zero, mechanism-confirmed.
- **PR-D1/D2** Power Artifact binding modelled the wrong mechanic (cost
  reducer, not untapper) — fixed via goldfish test; full 42-combo audit,
  30 bound, 12 flagged honestly (COMBO-ACCOUNTING.md).
- **PR-68..77** The Heliod six-defect chain, each invisible until the prior
  fix: validation gate now explains refusals (68); X=0 assembly death → X≥2
  derived from cost parts (69/70/76 — the rendered-text-vs-structured-data
  bug, twice); grant proven on copy but never performed live (71); counter
  trigger mistargeting via chooseTargetsFor seam (72); last-counter suicide
  guard (73); LIFO stack ordering — yield so grants resolve first (74/77).
  Loop now sustains mechanically; remaining gap was the drill throttle.
  Result docs: PHASE-10-PLAN/RESULTS, GIADA-COMBO-RESULT.md, 120-game
  baseline (purph 25.8% / giada 20.8% / selvala 4.2% / urza 0, CI-backed).

## Phase 11 — compile, don't classify (current)
- **PR-alpha** ComboProgram schema + Heliod reference program
  (combo-program-1274-3693.json): Spellbook's verbatim steps compiled
  against script facts, all six failure modes encoded as structure. Plan:
  PHASE-11-PLAN.md — one path per combo, real iterations to a
  governor-computed target (no declared shortcuts), oracle text as compiler
  input, ship-flagged prep, fresh-evaluation interruption policy.
  Research: mtg-rules-summary.md (agent-built from official CR June 2026,
  26-keyword glossary).
- *Next: PR-beta StepInterpreter (five invariants, LifegainPingLoop deleted
  when green); spike on repeated same-ability activation; PR-gamma
  target-computed loop runner + exit-state governor; PR-delta prep goldfish
  gate emitting fixtures from programs; PR-epsilon execution-fidelity batch.*

## Artifact inventory (current)
**Per-deck dossier:** deck-cards, combos, advisory-combos, route-coverage,
tutor-priorities, paired-plays, lint-report, implementability-report,
spellbook-raw(+meta), dossier.json (sha256 integrity), capability-inventory,
discovered-synergies, proposed-vocabulary, win-plan, ingestion-report,
combo-program-&lt;id&gt;.json (Phase 11+).
**Global:** bindings/executor-bindings.json, bindings/capability-registry.json,
UPSTREAM-PATCHES.md (2 entries).
**Batch outputs:** runs/&lt;id&gt;/&lt;stamp&gt;/{game-records.jsonl, events/,
run.log, worker-*.out, run-manifest.json}, runs/&lt;id&gt;/batches.jsonl.
**Plans:** PHASE-6..11-PLAN.md, PROJECT-BRIEF.md, COMBO-ACCOUNTING.md, PR-LOG.md (this).
**Research:** combo-conversion-playbook, game-ai-architectures,
mtg-rules-digest-conversion, mtg-ai-survey, architecture-survey-2,
ingestion-findings, ingestion-trial-purphoros2, divergence-investigation,
mtg-rules-summary.

## PR-beta.1 — the trigger-targeting seam, traced and taken
Traced why Heliod's counter went to Lyra: Forge routes a queued (wrapped) trigger through `MagicStack.chooseOrderOfSimultaneousStackEntry` → the controller's `orderAndPlaySimultaneousSa` → `prepareSingleSa` → `brains.doTrigger()`, where `CountersPutAi` feeds `getBestAI()`; `chooseTargetsFor` is only invoked for scripted `TargetingPlayer` flows, so PR-72's override was never in the path at all. Fix: override `orderAndPlaySimultaneousSa` in ComboAwareController — while a program is live, a trigger whose source carries a declared obligation (`loop.trigger_obligations`, new `ProgramRunner.obligedTargetFor`) has its targets set to the obliged card and goes to the stack directly; everything else keeps stock behavior. No parent patch, no card names in code. GiadaHeliodLoopTest raised back to its hard bar (`drillSteps >= 5`) and passes: the loop sustains verified iterations on the live game. 236/236.

## PR-gamma — governor v0 formalized, tranches, drill deleted for program combos
Pre-gamma spike (measured, seed 42): the engine grants consecutive priority windows without limit — 39 verified iterations in ONE turn, suite time unmoved, and the program CONVERTED: engine WIN (AllOpponentsLost) on turn 5, the first program-driven win. One nuance: a lethal final iteration ends the game before program_complete can be emitted, so scoring must count engine wins, not completion events. PR-gamma formalizes the governor on that evidence: iterations are planned in tranches — at each boundary N = min(exit-state need measured from the live table, self-consumption cap from the program's declaration: none/library floor 5/life floor 10 vs live resources), emitted as governor_plan; a tranche exhausting with opponents alive replans; a floor breach (mid-tranche included) aborts self_floor for fresh evaluation. The legacy drill is deleted for program combos: the pilot reads every program's piece cards at load and a DRILL conversion plan on any of them is suppressed (drill_suppressed) — one execution path per combo, fresh evaluation re-enters the PROGRAM. GiadaHeliodLoopTest now asserts the plan (planned >= 5), the engine WIN for seat 0, and zero legacy drills on program pieces, alongside the sustain bar. 236/236.

## PR-delta — the program executability gate (Gate 4)
New prep gate: for every compiled program in a dossier, ProgramGate DERIVES a goldfish fixture from the program itself — pieces the setup casts go to HAND so the interpreter performs its own casts, the rest to the battlefield, basic lands computed from the cast cards' real mana costs (X at x_min) plus the program's declared activation costs — plays one headless game, and judges by what the engine says: seat-0 win or a sustained run of verified iterations is executable, anything else ships FLAGGED with the abort reason, and combos with no program ship no_program. The flag list IS the build backlog; the gate cannot fail prep. Artifacts: dossier/fixtures/fixture-<id>.json (arena.program-fixture/1) and program-backlog.json (arena.program-backlog/1), registered in dossier.json with sha256 plus a status.programs tally; wired into PrepMain as Gate 4 and runnable standalone. Engine internals stay behind the architecture wall via the new engine-side ProgramFixtureProbe (the ArchUnit rule caught the first draft). Run on all four dossiers: Giada 1 executable (engine win t5 — the gate's fixture casts BOTH pieces from hand, stronger than the loop test's board) + 1 no_program; Purphoros 6, Selvala 11, Urza 23 no_program — a 41-program build backlog, now a committed artifact. ProgramGateTest covers the gate end to end on a temp copy. 237/237.

## PR-epsilon — 30-game batch scored on execution fidelity; canary green
New scorer scripts/program-fidelity.py reads a batch run dir and reports, per deck: games where a program entered (governor_plan), verified iterations per entered game, governor plans, abort-reason histogram, drill suppressions, and conversions counted from ENGINE wins only (the spike's lesson). The 30-game batch (runs/pr-epsilon-config.json, seed_base 6200 — seed-paired with the July 20 rebaseline-det run): Purphoros canary EXACT — 8 wins on paired seeds in both runs, 26.7% vs the 120-game 25.8%. Giada 9/30. Execution fidelity, the number that matters: one organic program engagement converted PERFECTLY — game 9, turn 33: line_entered, lifelink granted+verified, governor planned need=35, 34 verified iterations plus the lethal 35th, engine win — planned 35, delivered exactly 35; a second engagement aborted clean at grant verification (grant_did_not_apply) and the legacy drill that then tried to arm on the Ballista was refused (drill_suppressed) — interruption policy and PR-gamma suppression both proven in the wild. Known crash class documented: 4 games died to stock Forge's OWN AI decision timeout (TimeoutException in AiController.chooseSpellAbilityToPlayFromList); the baseline carried the same class (2 recorded + 3 missing records) at different seeds — pre-existing, not a Phase 11 signature, not ours to patch. Entry rate (1 organic engagement in 30 games) is the next frontier: assembly, not execution.

## PR-zeta — backlog #1 compiled: Archangel of Thune + Walking Ballista (2919-3693)
First program produced by the compile PATH rather than alongside the reference: Spellbook's generic prerequisite ("a way to give Walking Ballista lifelink") resolved against the deck's capability inventory to TWO granters — Heliod, Sun-Crowned (repeatable activated grant; COMPILED as the granter piece) and Akroma's Will (one-of instant, team-wide lifelink; a self-contained Archangel+Ballista+Will kill that needs no Heliod, NOT compiled because the runner's per_turn grant path resolves battlefield activated abilities only — cast-type grants are a queued runner extension). An adversarial verify panel (3 refuting lenses: script fidelity, runner compatibility, plan compliance) REFUTED the first draft with a real blocker: compiling Heliod in as granter imports his own TARGETED LifeGained trigger, firing every iteration beside Archangel's untargeted PutCounterAll — the draft declared no trigger_obligations and its cross-check falsely said none existed. Fixed: obligation declared (must_target Walking Ballista, enforced at the proven orderAndPlaySimultaneousSa seam), deltas corrected to net +1, cross-check now names the correction. Panel defects recorded as backlog: mana_available_unrestricted preconditions are silently unenforced by the runner (both programs), and several program fields are contract-documentation the v0 runner hardcodes rather than reads. Gate result: BOTH programs executable — engine win, AllOpponentsLost t5, each; Giada's dossier now reads 2 executable, 0 flagged, 0 no_program (backlog 41 -> 40). ProgramGateTest updated to the two-program reality. 237/237.

## PR-eta — the first compiled pairing: Doomskar + Flawless Maneuver, respond-on-stack
New pairing pipeline, one pair end to end per Ben's build-slowly directive. Compiled program (arena.pairing-program/1) from card scripts + the paired-plays entry + Ben's fire policy verbatim (threat_gated: mana + opponents' combined creature power >= 6; assembly_gated queued for MLD); mechanism validity encoded (destroy vs indestructible — the artifact's four Farewell+indestructible pairs are invalid, exile ignores indestructible, only phasing survives it; phasing pairs are flagged un-runnable until a measure_at:next_untap runner exists). PairingRunner executes respond-on-stack — the designed exception to the yield invariant — with joint mana preflight choosing the protection's cheapest castable mode, stack-identity verification of BOTH casts, and measured completion (own creatures preserved, opponents reduced, full_sweep recorded not required). OpponentView gains creaturePower (public info). One path per pair: compiled pairs skip the legacy PairedPlay archetype, reserve their own cards, and the epsilon-measured legacy dangle (armed shield firing into unrelated stacks after its wipe's cast silently failed) is expired after its arming turn. The adversarial panel earned its keep AGAIN — 15 findings including a genuine blocker: independent preflight checks let the wipe eat the shield's mana (pilot counted the protection free on key-presence; the happy-path test masked it by force-placing Giada); fixed with the joint check + retryable zero-cost preflight aborts, and a second test drives the commander-absent retail path. Haiku-delegated file inventory appended to IMPLEMENTATION-PLAN.md (60 entries, reviewed, 5 tightened). 239/239.

## PR-theta — Armageddon + Teferi's Protection: protected MLD, deferred phasing measure
The first assembly_gated pairing (Ben: MLD fires as soon as assembled and affordable — the primer's caution expressly waved off). New engine fact, verified in parent code before building on it: Game.getCardsIn(Battlefield) filters phased-out cards, so DestroyAll structurally cannot see our phased lands — the pairing works in-engine exactly as on paper. PairingRunner v2: scope-aware counting (the wipe's declared scope decides whether creatures or lands are measured) and verify.measure_at: next_untap — a phasing shield makes OUR side invisible until phase-in, so the own measure defers to our next turn while opponents' losses are snapshotted at resolution (a land replayed during the deferral cannot launder the reduction). Test proves it end to end: entered on assembly, opponents' lands destroyed at resolution, our 8+ lands counted back post-untap, verdict on a later turn than entry. A focused single-agent verifier (proportionate under the model-tier rule — increment on twice-panel-hardened machinery) did NOT refute the state machine and verified the turn arithmetic, snapshot timing, and shield detection against PhaseHandler/Untap/MagicStack internals; its two real defects are fixed: seat elimination mid-deferral now aborts loudly instead of freezing silently, and program-fidelity.py scores pairings including entered-but-truncated-by-game-end as truncated, never clean. Known accepted costs, documented: the pilot freeze forfeits the casting turn's land drop, and preflight runs pre-drop (one-low mana → retryable next-turn aborts, self-healing). delta_mismatch aborts now name the failing side (own/opp/both). 240/240.

## Pairing audit — card-text reconfirmation of all 36 Giada pairs (doc-only)
Ben directed a full reconfirmation of the synergy pairs with an independent Gemini pass. Two audits, fully independent (Claude in-session; Gemini 3.1 Pro via API with a self-contained package of pairs + oracle texts + CR mechanism rules): verdicts agreed 36/36 — 32 VALID, 4 INVALID (all Farewell + indestructible-class; exile ignores indestructible, protection-from-color never applies untargeted; only phasing survives Farewell). Both audits independently surfaced the same missed class — Avacyn, Angel of Hope as STANDING protection (persistent all-permanent indestructible, lands included) pairing one-sidedly with all 8 destroy wipes, a new precondition-based runner shape with no shield cast — and rejected the same non-candidates (Runes mothers: single-target; The One Ring: player-protection). Gemini's distinct catch, rules-verified: Final Showdown's lose-all-abilities mode strips externally granted indestructible before its destroy mode resolves — compiled Final Showdown pairs must never pick that mode beside an indestructible shield (phasing immune). Full report: docs/PAIRING-AUDIT-GIADA.md; artifact untouched (paired-plays.json stays prep-generated), verdicts feed the compile sweep.

## PR-iota — the pairing compile sweep: 18 compiled, every deferral named
Sixteen new pairing programs generated from one audited table (script hashes computed per card, costs from scripts, verdicts from docs/PAIRING-AUDIT-GIADA.md), joining the two references: Doomskar/Vanquish creature wipes (threat_gated) and Armageddon/Ravages/Catastrophe MLD (assembly_gated) crossed with Teferi's Protection (phasing, next_untap measure), Flare of Fortitude, Grand Crescendo, and Flawless Maneuver; Hour of Revelation and Ondu Inversion (nonland scope) with the all-permanent shields. Modality checks reshaped the sweep honestly: Catastrophe's GenericChoice is safe ONLY because its compiled shields cover all own permanents under either mode (noted in-program); Akroma's Will's Charm (AI could pick the flying mode and let the board die) joins Final Showdown's Spree and modal Farewell+Teferi's in a 9-pair mode-control backlog; Clever Concealment's TargetMin$ 0 (AI could phase out nothing and self-wipe us) defers its 5 pairs to a pre-targeting backlog; the 4 Farewell+indestructible pairs stay rejected per the audit. Two guards landed with the sweep: cheapestCast skips sacrifice-alternative costs (Flare's free mode would eat an angel), and pairing specs order assembly_gated first (PR-49's lesson — cheapest-first once kept land destruction from firing in 300 games). 240/240; 30-game batch launched for in-the-wild evidence.

## PR-kappa — the Land Tax + Scroll Rack engine program, and the staleness bug that mattered
New program class arena.engine-program/1: a background card-advantage cycle with no exit state. The compiled Land Tax + Scroll Rack engine encodes the load-bearing interaction (Rack without a shuffle is worthless — the Tax fetch IS the shuffle, so the cycle gates on the Tax condition being live), early setup casts (stock's measured failure: Land Tax at turns 15/15/30, Scroll Rack NEVER — AI:RemoveDeck:All), a v1 exile policy (excess basics only, keep one for the drop), and measured engine_cycle events. Two seams were found the hard way: the multi-select exile callback NEVER fires for AI (allowMultiSelect excludes AI controllers — dead branch deleted, real seam is one-card-at-a-time chooseSingleCardForZoneChange), and pilot-sink tests cannot assert recorder events. Ben's weights-freshness directive flushed out a REAL regression: executorExists consulted bindings only, so since PR-beta the mulligan keep/protection, hasBoundCombo, and the tutor push were all blind to Giada's program-only combos — she assembled on natural draws alone; fixed, and TutorWeights now weights engine pieces at 0.9 (Land Tax/Scroll Rack are prime Enlightened Tutor targets), artifact regenerated + rehashed. The validation panel (Ben's ask) refuted the first draft with a genuine blocker — a gate-failed cycle dispatch returned null and silently forfeited the seat's ENTIRE MAIN1 every turn the pieces were out with a failed gate (invisible to the happy-path diagnostic) — fixed by handing the window back (drill precedence honored, super fallback), plus: the unimplemented rack-playability gate (false swap_mismatch aborts from tapped/mana-short racks) now real via canPayCost, honest abort taxonomy (activation_never_resolved vs cycle_disrupted), a library-floor gate, deterministic spec ordering, spec filtering of uncyclable programs, and derivation self-documentation. Known gaps recorded, not hidden: engineSetup shares preAssembly's color-blind estimate class; preAssembly/entryRunway remain binding-only; shuffleAvailable is a labeled point-in-time proxy. Diagnostic evidence: 4 measured cycles (swapped 1,2,2,2 — growing as Tax feeds the hand), win t13. 241/241.

## PR-kappa.1 — pip-aware joint preflight (the 60-game batch priced the color-blindness)
The kappa60 batch measured the accepted color-blind joint check failing twice: preflight counted sources colorlessly, the wipe's payment tapped the white sources, and the shield's {W}{W} went unpayable in response — Doomskar swept our own board (game 18, Grand Crescendo), Armageddon ate our own lands (game 39, Flare of Fortitude). The joint check now counts colored pips from the structured mana costs against untapped WHITE-CAPABLE sources (mana abilities' Produced$ containing W or Any) alongside the total — a failed check still aborts retryably pre-spend. Batch headlines recorded with the fix: Purphoros canary 15/60 = 25.0% (green vs 25.8%); Giada 13/60; Selvala off zero (3/60); pairing entries 4 in 60 (rate doubled vs iota), 1 completed + 1 honest interaction abort + the 2 now-fixed color casualties; combo-program entries up ~5x in attempts (11: 1 converted win, 10 setup_piece_unreachable fresh-evaluation retries — the executorExists fix generating assembly pressure that mana could not yet cash); Land Tax cast at turns 1/2/4/4 when drawn early (stock's t15/t30 fixed) with 14 casts across 60 games; the engine cycled once in the wild (Scroll Rack is a 1-of — cycles are tutor-dependent, which is what the 0.9 weights are for). 241/241.
