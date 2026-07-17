# PR-16 design — LethalityPlanner v1 + loop shortcut + route telemetry

> Working handoff note (2026-07-16). Deleted/absorbed into IMPLEMENTATION-PLAN.md §6
> when PR-16 lands. Written so a fresh session can implement without prior context.
> Prereqs all committed: PR-14 (sim seam, `3f4ade70739`), PR-15 (pilot/controller,
> `fb7933242da`). Tests at 127 green. Build: `JAVA_HOME=/usr/local/opt/openjdk@17/...`
> `mvn -pl forge-arena -am install -Dcheckstyle.skip=true` from repo root.

## Goal

Replace PR-15's banking primitive (run 6 cycles, dump pool on stock AI) with
deliberate conversion: after a line's MANA_LOOP validates, the planner picks a win
route from the dossier's route-coverage **deck layer** (built in PR-12 for exactly
this) plus live public information, records `route_selected` / `route_rejected`
with predicate values (plan §5 v3.2 — silence is never a decision record), fires
the **loop shortcut** (`combo_shortcut`), and watches for stalls (`combo_stalled`
+ state dump — the Gate 3.6 logging half).

## Scope decisions (made deliberately, revisit only with new information)

1. **Shortcut = pool injection.** Per plan §6 (generic fallback text): after the
   sandbox proves the loop, the controller sets a large floating pool
   (bounded_product, default 10^4 of the engine's color) instead of physically
   looping, emits `combo_shortcut` (iterations_proven=3 from validate, bounded
   product recorded). Engine seam: `player.getManaPool()` add — engine-side in
   ComboAwareController (grep `ManaPool.addMana` / `forge.game.mana.Mana` for the
   exact call; check how the engine itself adds mana in AbilityManaPart).
2. **Conversion v1 is stock-AI-with-infinite-mana**, not a scripted DEPLOY/alpha
   executor. The planner selects the route and hands the pool to stock AI (the
   plan's own bet: "stock heuristics reliably cast Finale/X-spells with 10^6
   available"). The scripted DEPLOY_WIN stage (count haste'd power, assign attacks)
   is the NEXT PR. combo_stalled telemetry tells us how often stock conversion
   fails — data before code.
3. **SeatView grows a public-info opponent view** (W8-safe: life totals, battlefield
   card names, poison — all public):
   `record OpponentView(int seat, int life, Set<String> battlefield)`,
   `List<OpponentView> opponents()`, plus own `manaPool()` int. Update SeatViews
   projection, ComboTrackerTest view helper (ctor change), and the
   `seatViewHidesTheLibraryStructurally` whitelist (add `opponents`, `manaPool`).
   NO opponent hands/libraries — ArchUnit/HiddenInfo stance unchanged.
4. **Planner inputs**: `RoutePlan` (combo/, parsed from route-coverage.json `deck`
   section: routes with support status + enablers) + SeatView + the fired binding's
   payoffs list. Loaded in EngineFacade next to combos.json; SeatSpec unchanged
   (dossierDir already there).

## LethalityPlanner v1 (combo/, pure)

Selection order (plan §1 WIN-ROUTES: same-turn terminal first, least interactable):
evaluate every route in the RoutePlan with support ∈ {intrinsic, supported, partial};
emit route_rejected (with the failing predicate + live values) or route_selected.

v1 predicates (all computable from SeatView + RoutePlan):
- ORACLE_WIN: oracle enabler card in own battlefield/hand → selected (rare; Selvala: rejected `oracle_guard`).
- DIRECT_DAMAGE_LOOP: x_damage/ping enabler in HAND or battlefield → selected
  (stock AI will cast it with the pool). Predicate values: enabler location, pool.
- SPREAD_COMBAT: haste enabler (static preferred) + pump enabler in hand/battlefield
  AND own creature count ≥ 1. Records projected_alpha = sum own creature power
  (approximation, noted) vs table_life = sum opponent life. alpha < table → rejected
  with both numbers (BANK_AND_HOLD fallback), else selected.
- COMMANDER_DMG_SEQUENCE: commander on battlefield → selectable last (slowest).
- Fallback: BANK_AND_HOLD — shortcut still fires (pool for interaction), telemetry
  says why everything else was rejected.

Planner runs ONCE per line completion (when pilot's executor returns done() — which
in PR-16 means "validated, shortcut now" not "banked 6 cycles": TapForManaUntapLoop
`next()` returns done() immediately once a new `shortcut=true` param is set; keep
bank_cycles path for executors without shortcut).

## Stall watchdog (Gate 3.6 logging half)

Engine-side (ComboAwareLobbyPlayer or a GameAware subscriber the facade wires):
after a seat's combo_shortcut, if the game reaches (shortcut_turn + 2) turn-begins
and is not over → emit `combo_stalled` (binding, rejected routes recap, state hash)
+ dump `game.toString()`-level state to `<runDir>/stalls/<hash>.txt` (schema: event
requires binding, state hash, dump path — check arena.events.1 for combo_stalled
required fields before emitting). Post-run autopsy consumes dumps (Gate 3.6 proper,
later).

## Telemetry (schema arena.events.1 — check exact required fields before emitting)

- route_selected: route + predicate values (projected_alpha, table_life, …)
- route_rejected: route + failed predicate + values (one per evaluated route)
- combo_shortcut: combo, iterations_proven, bounded product
- combo_stalled: binding, state hash, dump path

## Test plan

- LethalityPlannerTest (pure): each route's select/reject paths with fixture
  RoutePlan + SeatViews; rejection carries predicate values; ordering (same-turn
  first); everything-rejected → BANK_AND_HOLD; all events schema-valid.
- TapForManaUntapLoop: shortcut param → done() at once after entry.
- ComboPilot: on line done → planner invoked once, directive SHORTCUT(target) —
  pilot API grows a PlannerDirective return or a second callback; keep pilot pure.
- Integration (extend ComboPilotIntegrationTest or new): scripted Selvala board +
  Craterhoof/Crossroads in HAND (addCard to hand zone) → expect combo_shortcut +
  route_selected SPREAD_COMBAT (or DIRECT_DAMAGE rejection trace), pool actually
  injected (assert via event or game outcome), game continues; stall test: strip
  payoffs → combo_stalled emitted + dump file exists.
- Events schema may need combo_stalled/route fields verified — SchemaValidationTest
  fixtures for the new events if not already covered by events-valid.jsonl.

## Order of work (commit after each compilable slice)

1. SeatView + SeatViews + test updates (opponents, manaPool). COMMIT.
2. RoutePlan loader (combo/, parses route-coverage deck section). COMMIT.
3. LethalityPlanner + LethalityPlannerTest (pure). COMMIT.
4. Pilot directive plumbing + TapForManaUntapLoop shortcut param + tests. COMMIT.
5. Controller: pool injection + shortcut/stall events + stall dump. COMMIT.
6. Integration test + plan-doc §6 as-built + delete this file. FINAL COMMIT.
