# Phase 11 — compile, don't classify (APPROVED)

Ben-approved plan. One execution path per combo, no fallback tier: a combo
runs ONLY through its compiled program; uncompiled combos stay on the old
path until compiled (sequential migration, never dual-path for one combo).

## Core decisions (Ben)
1. NO partial fallback method. Simplify runtime; move correctness into
   prep/ingestion, built per combo. FULL ORACLE TEXT is a compiler input
   alongside Spellbook steps, Forge scripts, and the capability inventory —
   oracle<->script divergence is itself a flag (buggy/partial script).
2. NO declared loop shortcuts (CR 727-style jumps rejected). Loops run REAL
   iterations to create genuine in-engine state; wins must be
   engine-recognized exit states reached by engine-legal actions, or batch
   logs stop being evidence. This also indicts SHORTCUT_POOL injection —
   retired as combos migrate to programs.
3. THE SYNTHESIS: loops run to a COMPUTED TARGET, not toward infinity. The
   governor enumerates engine exit states (life<=0 per opponent, empty-draw,
   poison, alt-win), costs each against the loop's MEASURED per-iteration
   delta, picks the cheapest reachable, computes N, and the interpreter runs
   exactly N verified real iterations. Demonstration and conversion are the
   same act. Kills the drill throttle, the injection hacks, and the
   10^4-pool clock burn at once.
4. Heliod + Walking Ballista first (reference program; its six known failure
   modes map one-to-one onto the interpreter invariants).
5. Prep gate ships FLAGGED, never hard-fails a deck: the flag list is the
   build backlog. Prep may iterate over a deck many times. Programs cached
   by combo_id + script hashes => cross-deck reuse for free. Acceptable
   floor: one step beyond stock Forge (basic combos + pairings; no
   combos-of-combos).
6. INTERRUPTION POLICY (Ben): when interaction breaks a running loop, do a
   FRESH EVALUATION for next-best execution — same combo if pieces still
   available, else a different combo or pairing. Board states change at
   instant speed or faster (split second forbids responses entirely — see
   rules summary); the executor re-evaluates rather than resuming blindly.
   Metric: execution fidelity (fires/game, sustained iterations, abort
   causes), NOT wins. Winning and general play quality are revisited later.

## PR sequence
- PR-alpha: ComboProgram schema + Heliod program artifact (THIS COMMIT).
- PR-beta: StepInterpreter, five invariants (usability precondition;
  one-stack-object-then-yield; per-step measured-delta verification;
  structured-cost sustain guard; setup performed in the LIVE game).
  LifegainPingLoop deleted when green.
- SPIKE before gamma: measure repeated same-ability activation across
  consecutive priority grants in one turn (engine behavior + cost).
- PR-gamma: target-computed loop runner + exit-state governor v0. Drill
  deleted for program combos.
- PR-delta: prep goldfish gate, fixture emitted from the program itself;
  unexecutable ships flagged.
- PR-epsilon: 30-game batch scored on execution fidelity; Purphoros canary
  (~25.8%) within noise.

## Interpreter invariants <- bug classes they encode
1. Precondition vs LIVE state, presence AND usability   (PR-54, tapped-Weaver)
2. One stack object at a time, yield until resolved      (PR-74 LIFO)
3. Post-step measured delta must match expectation       (loop-health telemetry)
4. Sustain guard from structured cost parts              (PR-73/76)
5. Sandbox proves; the LIVE game performs                (PR-71)
