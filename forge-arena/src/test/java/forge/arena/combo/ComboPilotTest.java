package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

import forge.arena.engine.SeatView;
import forge.arena.report.ArenaEvent;

/**
 * Every pilot decision path, engine-free (plan §5 v3.2: silence is never a
 * valid record of a decision — and every record must validate against the
 * events schema).
 */
public class ComboPilotTest {

    private static final ComboDef MANTLE_DEF = new ComboDef("527-2816", List.of(
            new ComboDef.Piece("Selvala, Heart of the Wilds", true),
            new ComboDef.Piece("Umbral Mantle", false)), 0);

    private ExecutorBindings bindings;
    private JsonSchema eventsSchema;

    @BeforeClass
    public void fixtures() throws Exception {
        Path dir = Files.createTempDirectory("pilot-bindings");
        // shortcut=false pins the stepping/banking path most tests exercise;
        // the shortcut path has its own test below
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "527-2816", "archetype": "TapForManaUntapLoop",
                   "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                              "activation_cost": "{G}", "untap_cost": "{3}",
                              "untap_ability_host": "engine", "self_pump_per_cycle": "2",
                              "bank_cycles": "2", "shortcut": "false"}}],
                 "unbound": []}""");
        bindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.events.1.schema.json"))) {
            eventsSchema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }

    private static SeatView ready(int turn) {
        return new SeatView(0, turn, Map.of(
                SeatView.Zone.BATTLEFIELD, Set.of("Selvala, Heart of the Wilds", "Umbral Mantle"),
                SeatView.Zone.HAND, Set.of(),
                SeatView.Zone.COMMAND, Set.of(),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80);
    }

    private static SeatView view(Set<String> battlefield, Set<String> hand, Set<String> command,
            Map<String, String> attachments) {
        return new SeatView(0, 3, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, command,
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80, 0, 0, List.of(), attachments);
    }

    private static final Function<LineExecutor, SimResult> PROFITABLE =
            executor -> SimResult.profitable(3);
    private static final Function<LineExecutor, SimResult> UNPROFITABLE =
            executor -> SimResult.unprofitable();

    private void assertAllValid(List<ArenaEvent> events) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        for (ArenaEvent e : events) {
            var errors = eventsSchema.validate(mapper.readTree(mapper.writeValueAsString(e.toJsonMap())));
            assertTrue("invalid event " + e.toJsonMap() + " -> " + errors, errors.isEmpty());
        }
    }

    @Test
    public void readyBoundComboEntersStepsAndBanks() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);

        Optional<ComboPilot.Action> first = pilot.nextAction(ready(3), true, PROFITABLE);
        assertTrue(pilot.lineActive());
        assertEquals("{G}", first.orElseThrow().step().costHint());
        assertEquals("527-2816", pilot.activeComboId());

        // bank_cycles=2, 2 steps per cycle: 3 more steps, then done
        for (int i = 0; i < 3; i++) {
            assertTrue(pilot.nextAction(ready(3), true, PROFITABLE).isPresent());
        }
        assertTrue(pilot.nextAction(ready(3), true, PROFITABLE).isEmpty());
        assertFalse("line banked -> back to stock AI", pilot.lineActive());

        List<String> kinds = events.stream().map(ArenaEvent::t).toList();
        assertEquals(1, kinds.stream().filter("line_entered"::equals).count());
        assertEquals(4, kinds.stream().filter("line_step"::equals).count());
        ArenaEvent entered = events.get(0);
        assertEquals("line_entered", entered.t());
        assertEquals("binding", entered.fields().get("attempted_via"));
        assertEquals("MAIN1", entered.fields().get("entry_phase"));
        assertAllValid(events);
    }

    @Test
    public void validationFailureAbortsTheEnteredLineOncePerTurn() throws Exception {
        // PR-18: assembly-first flow — the attempt HAPPENED (assembly ran/was
        // empty), so a post-assembly refusal is line_aborted, not an ignore
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);
        AtomicInteger validations = new AtomicInteger();
        Function<LineExecutor, SimResult> failing = executor -> {
            validations.incrementAndGet();
            return SimResult.unprofitable();
        };
        assertTrue(pilot.nextAction(ready(3), true, failing).isEmpty());
        assertTrue(pilot.nextAction(ready(3), true, failing).isEmpty());
        assertTrue(pilot.nextAction(ready(3), true, failing).isEmpty());
        assertEquals("one validation per combo per turn", 1, validations.get());
        assertEquals(List.of("line_entered", "line_aborted"),
                events.stream().map(ArenaEvent::t).toList());
        assertEquals("validation", events.get(1).fields().get("cause"));
        assertFalse(pilot.lineActive());
        // a NEW turn is a new decision point
        assertTrue(pilot.nextAction(ready(4), true, failing).isEmpty());
        assertEquals(2, validations.get());
        assertEquals(4, events.size());
        assertAllValid(events);
    }

    @Test
    public void assemblyDeploysCastsThenAttachesThenProves() throws Exception {
        Path dir = Files.createTempDirectory("pilot-assembly");
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "527-2816", "archetype": "TapForManaUntapLoop",
                   "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                              "activation_cost": "{G}", "untap_cost": "{3}",
                              "untap_ability_host": "engine", "attach_cost": "{0}"}}],
                 "unbound": []}""");
        ExecutorBindings assemblyBindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        List<ArenaEvent> events = new ArrayList<>();
        AtomicInteger validations = new AtomicInteger();
        Function<LineExecutor, SimResult> proving = executor -> {
            validations.incrementAndGet();
            return SimResult.profitable(3);
        };
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), assemblyBindings,
                0.0, 0, events::add);

        // Selvala in command, Mantle in hand: reachable-ready, NOT executable
        SeatView start = view(Set.of(), Set.of("Umbral Mantle"),
                Set.of("Selvala, Heart of the Wilds"), Map.of());
        ComboPilot.Action cast1 = pilot.nextAction(start, true, proving).orElseThrow();
        assertTrue(cast1.step().isCast());
        assertEquals("Selvala, Heart of the Wilds", cast1.step().card());
        assertTrue(pilot.lineActive());
        assertEquals(0, validations.get()); // no proof until assembled

        // Selvala landed; Mantle still in hand
        SeatView selvalaDown = view(Set.of("Selvala, Heart of the Wilds"),
                Set.of("Umbral Mantle"), Set.of(), Map.of());
        ComboPilot.Action cast2 = pilot.nextAction(selvalaDown, true, proving).orElseThrow();
        assertTrue(cast2.step().isCast());
        assertEquals("Umbral Mantle", cast2.step().card());

        // both down, unattached: the equip step targets the engine
        SeatView unattached = view(Set.of("Selvala, Heart of the Wilds", "Umbral Mantle"),
                Set.of(), Set.of(), Map.of());
        ComboPilot.Action equip = pilot.nextAction(unattached, true, proving).orElseThrow();
        assertEquals("Umbral Mantle", equip.step().card());
        assertEquals("{0}", equip.step().costHint());
        assertEquals(List.of("Selvala, Heart of the Wilds"), equip.step().targets());

        // attached: NOW the engine proves it, the planner runs, the pool fires
        SeatView attached = view(Set.of("Selvala, Heart of the Wilds", "Umbral Mantle"),
                Set.of(), Set.of(), Map.of("Umbral Mantle", "Selvala, Heart of the Wilds"));
        ComboPilot.Action shortcut = pilot.nextAction(attached, true, proving).orElseThrow();
        assertFalse(shortcut.isStep());
        assertEquals(1, validations.get());
        assertTrue("DEPLOY follows the shortcut", pilot.lineActive());
        assertTrue(pilot.nextAction(attached, true, proving).isEmpty());
        assertFalse(pilot.lineActive());

        List<String> kinds = events.stream().map(ArenaEvent::t).toList();
        assertEquals(List.of("line_entered", "line_step", "line_step", "line_step",
                "route_selected", "combo_shortcut"), kinds);
        assertAllValid(events);
    }

    @Test
    public void patienceHoldsThenFires() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                1.0, 0, events::add); // hold 3 turns
        assertTrue(pilot.nextAction(ready(3), true, PROFITABLE).isEmpty());
        assertTrue(pilot.nextAction(ready(4), true, PROFITABLE).isEmpty());
        assertTrue(pilot.nextAction(ready(5), true, PROFITABLE).isEmpty());
        assertEquals(3, events.stream().filter(e -> "patience_gate".equals(
                e.fields().get("reason"))).count());
        assertTrue("held long enough — fire", pilot.nextAction(ready(6), true, PROFITABLE).isPresent());
        assertAllValid(events);
    }

    @Test
    public void unboundComboIsIgnoredAsNoViableRoute() throws Exception {
        ComboDef unbound = new ComboDef("999-999", List.of(
                new ComboDef.Piece("Umbral Mantle", false)), 0);
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(unbound)), bindings,
                0.0, 0, events::add);
        assertTrue(pilot.nextAction(ready(3), true, PROFITABLE).isEmpty());
        assertEquals("combo_ignored", events.get(0).t());
        assertEquals("no_viable_route", events.get(0).fields().get("reason"));
        assertAllValid(events);
    }

    @Test
    public void closedEntryWindowIsNotADecisionPoint() {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);
        assertTrue(pilot.nextAction(ready(3), false, PROFITABLE).isEmpty());
        assertTrue("no phantom events outside decision points (plan §5)", events.isEmpty());
    }

    @Test
    public void abortRecordsCauseAndPieceAndExitsLine() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);
        pilot.nextAction(ready(3), true, PROFITABLE);
        assertTrue(pilot.lineActive());
        pilot.abortLine(3, "interaction", "Umbral Mantle");
        assertFalse(pilot.lineActive());
        ArenaEvent aborted = events.get(events.size() - 1);
        assertEquals("line_aborted", aborted.t());
        assertEquals("interaction", aborted.fields().get("cause"));
        assertEquals("Umbral Mantle", aborted.fields().get("piece_lost"));
        assertAllValid(events);
    }

    @Test
    public void shortcutEligibleLinePlansRoutesAndOrdersThePool() throws Exception {
        Path dir = Files.createTempDirectory("pilot-shortcut");
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "527-2816", "archetype": "TapForManaUntapLoop",
                   "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                              "activation_cost": "{G}", "untap_cost": "{3}",
                              "untap_ability_host": "engine", "pool_color": "G"}}],
                 "unbound": []}""");
        ExecutorBindings shortcutBindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), shortcutBindings,
                0.0, 0, events::add);

        ComboPilot.Action action = pilot.nextAction(ready(3), true, PROFITABLE).orElseThrow();
        assertFalse("shortcut, not a step", action.isStep());
        assertEquals("527-2816", action.shortcut().comboId());
        assertEquals("Selvala, Heart of the Wilds", action.shortcut().engineCard());
        assertEquals("G", action.shortcut().color());
        assertEquals(ComboPilot.SHORTCUT_POOL, action.shortcut().amount());
        assertEquals("empty route plan -> explicit bank", "BANK_AND_HOLD", action.shortcut().route());
        // PR-18: the line survives the shortcut in DEPLOY; a binding with no
        // payoffs (this fixture) exits on the next decision
        assertTrue(pilot.lineActive());
        assertTrue(pilot.nextAction(ready(3), true, PROFITABLE).isEmpty());
        assertFalse("deploy exhausted -> line complete", pilot.lineActive());

        List<String> kinds = events.stream().map(ArenaEvent::t).toList();
        assertEquals(List.of("line_entered", "route_selected", "combo_shortcut"), kinds);
        ArenaEvent shortcut = events.get(2);
        assertEquals(Integer.valueOf(3), shortcut.fields().get("iterations_proven"));
        assertAllValid(events);
    }

    @Test
    public void unaffordableFirstCastIsManaReservedNotAnAbortSpam() throws Exception {
        Path dir = Files.createTempDirectory("pilot-afford");
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "527-2816", "archetype": "TapForManaUntapLoop",
                   "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                              "activation_cost": "{G}", "untap_cost": "{3}",
                              "untap_ability_host": "engine", "attach_cost": "{0}",
                              "engine_mana_value": "3", "untapper_mana_value": "3"}}],
                 "unbound": []}""");
        ExecutorBindings gated = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), gated,
                0.0, 0, events::add);

        // 1 untapped source, first cast needs 3: wait, recorded, no line
        SeatView poor = new SeatView(0, 2, Map.of(
                SeatView.Zone.BATTLEFIELD, Set.of("Forest"),
                SeatView.Zone.HAND, Set.of("Umbral Mantle"),
                SeatView.Zone.COMMAND, Set.of("Selvala, Heart of the Wilds"),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80, 0, 0, List.of(), Map.of(), 1);
        assertTrue(pilot.nextAction(poor, true, PROFITABLE).isEmpty());
        assertFalse(pilot.lineActive());
        assertEquals(1, events.size());
        assertEquals("combo_ignored", events.get(0).t());
        assertEquals("mana_reserved", events.get(0).fields().get("reason"));

        // 4 sources: the line enters and the first cast goes out
        SeatView funded = new SeatView(0, 3, Map.of(
                SeatView.Zone.BATTLEFIELD, Set.of("Forest"),
                SeatView.Zone.HAND, Set.of("Umbral Mantle"),
                SeatView.Zone.COMMAND, Set.of("Selvala, Heart of the Wilds"),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80, 0, 0, List.of(), Map.of(), 4);
        ComboPilot.Action action = pilot.nextAction(funded, true, PROFITABLE).orElseThrow();
        assertTrue(action.step().isCast());
        assertEquals("Selvala, Heart of the Wilds", action.step().card());
        assertAllValid(events);
    }

    @Test
    public void deployReachesRoutePlanPayoffsBeyondTheBinding() throws Exception {
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("DIRECT_DAMAGE_LOOP", "conversion", "supported",
                        List.of("Fireball"))),
                Map.of("x_damage", List.of("Fireball")));
        Path dir = Files.createTempDirectory("pilot-deploy");
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "527-2816", "archetype": "TapForManaUntapLoop",
                   "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                              "activation_cost": "{G}", "untap_cost": "{3}",
                              "untap_ability_host": "engine"}}],
                 "unbound": []}""");
        ExecutorBindings noPayoffBindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), noPayoffBindings,
                plan, null, 0.0, 0, events::add);

        SeatView board = new SeatView(0, 5, Map.of(
                SeatView.Zone.BATTLEFIELD, Set.of("Selvala, Heart of the Wilds", "Umbral Mantle"),
                SeatView.Zone.HAND, Set.of("Fireball"),
                SeatView.Zone.COMMAND, Set.of(),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80, 0, 0, List.of(), Map.of(), 9);
        ComboPilot.Action shortcut = pilot.nextAction(board, true, PROFITABLE).orElseThrow();
        assertFalse(shortcut.isStep());
        // DEPLOY: the binding lists no payoffs, but the route plan knows Fireball
        ComboPilot.Action deploy = pilot.nextAction(board, true, PROFITABLE).orElseThrow();
        assertTrue(deploy.step().isCast());
        assertEquals("Fireball", deploy.step().card());
        // PR-25: conversion casts pin X — the AI's own choice is pool-blind
        assertEquals(Integer.valueOf(ComboPilot.DEPLOY_X), deploy.step().x());
        assertAllValid(events);
    }

    // ---- PR-25: conversion — re-plan, late deploys, forced combat ----

    private static SeatView convertView(Set<String> battlefield, Set<String> hand, int turn) {
        return new SeatView(0, turn, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, Set.of(),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 70, 10000, 9,
                List.of(new SeatView.OpponentView(1, 40, 0, Set.of()),
                        new SeatView.OpponentView(2, 26, 0, Set.of()),
                        new SeatView.OpponentView(3, 31, 0, Set.of())),
                Map.of(), 9);
    }

    private ComboPilot firedPilot(RoutePlan plan, List<ArenaEvent> events) throws Exception {
        Path dir = Files.createTempDirectory("pilot-convert");
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "527-2816", "archetype": "TapForManaUntapLoop",
                   "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                              "activation_cost": "{G}", "untap_cost": "{3}",
                              "untap_ability_host": "engine", "pool_color": "G"}}],
                 "unbound": []}""");
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)),
                ExecutorBindings.load(dir.resolve("executor-bindings.json")), plan, null,
                0.0, 0, events::add);
        // fire with an empty hand: nothing to deploy, line exits, pool banked
        SeatView atFire = convertView(
                Set.of("Selvala, Heart of the Wilds", "Umbral Mantle"), Set.of(), 3);
        assertFalse(pilot.nextAction(atFire, true, PROFITABLE).orElseThrow().isStep());
        assertTrue(pilot.nextAction(atFire, true, PROFITABLE).isEmpty());
        assertFalse(pilot.lineActive());
        return pilot;
    }

    @Test
    public void replanDeploysLatePayoffsWithScriptedX() throws Exception {
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                        List.of("Concordant Crossroads", "Craterhoof Behemoth"))),
                Map.of("haste_static", List.of("Concordant Crossroads"),
                        "mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = firedPilot(plan, events);

        // next turn: Crossroads landed, Craterhoof drawn — the re-plan flips
        // BANK_AND_HOLD into SPREAD_COMBAT and the payoff still gets cast
        SeatView later = convertView(
                Set.of("Selvala, Heart of the Wilds", "Umbral Mantle", "Concordant Crossroads"),
                Set.of("Craterhoof Behemoth"), 7);
        ComboPilot.Action deploy = pilot.nextAction(later, true, PROFITABLE).orElseThrow();
        assertTrue(deploy.step().isCast());
        assertEquals("Craterhoof Behemoth", deploy.step().card());
        assertEquals(Integer.valueOf(ComboPilot.DEPLOY_X), deploy.step().x());
        long spreadSelected = events.stream().filter(e -> e.t().equals("route_selected")
                && "SPREAD_COMBAT".equals(e.fields().get("route"))).count();
        assertEquals(1, spreadSelected);
        long deployWin = events.stream().filter(e -> e.t().equals("line_step")
                && "DEPLOY_WIN".equals(e.fields().get("stage"))).count();
        assertEquals(1, deployWin);

        // same turn, same card: deduped — and the planner ran ONCE this turn
        assertTrue(pilot.nextAction(later, true, PROFITABLE).isEmpty());
        assertEquals("route evaluation is once per turn", 1,
                events.stream().filter(e -> e.t().equals("route_selected")
                        && "SPREAD_COMBAT".equals(e.fields().get("route"))).count());
        assertAllValid(events);
    }

    @Test
    public void combatOrderSteersOnlyCombatRoutesAndSortsByLife() throws Exception {
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                        List.of("Concordant Crossroads"))),
                Map.of("haste_static", List.of("Concordant Crossroads"),
                        "mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = firedPilot(plan, events);

        // banked verdict (nothing visible at fire): no combat directive
        assertTrue(pilot.combatOrder(convertView(
                Set.of("Selvala, Heart of the Wilds", "Umbral Mantle"), Set.of(), 3)).isEmpty());

        // SPREAD becomes live on a later turn: directive with lowest-life-first
        SeatView later = convertView(
                Set.of("Selvala, Heart of the Wilds", "Umbral Mantle", "Concordant Crossroads"),
                Set.of("Craterhoof Behemoth"), 7);
        pilot.nextAction(later, true, PROFITABLE); // re-plan runs here
        ComboPilot.CombatOrder order = pilot.combatOrder(later).orElseThrow();
        assertEquals("SPREAD_COMBAT", order.route());
        assertEquals("kill order is lowest life first (26, 31, 40)",
                List.of(2, 3, 1), order.killOrder());
        assertTrue(events.stream().anyMatch(e -> e.t().equals("line_step")
                && "FORCED_ATTACK".equals(e.fields().get("stage"))));
        assertAllValid(events);
    }

    @Test
    public void combatOrderIsInertWithoutAFiredShortcut() {
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, e -> {
                });
        assertTrue("no fire -> stock combat untouched (inertness)",
                pilot.combatOrder(convertView(Set.of(), Set.of(), 5)).isEmpty());
    }

    // ---- PR-24: payoff visibility — mulligan policy + tutor urgency ----

    /** A mulligan-time view: hand + command names, plus TRUE hand counts. */
    private static SeatView mullView(Set<String> hand, Set<String> command, int handSize,
            int handLands) {
        return new SeatView(0, 0, Map.of(
                SeatView.Zone.BATTLEFIELD, Set.of(),
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, command,
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 92, 0, 0, List.of(), Map.of(), 0,
                handSize, handLands);
    }

    private static final Set<String> SELVALA_CMD = Set.of("Selvala, Heart of the Wilds");

    @Test
    public void mulliganKeepsAPieceHandEvenWhenStockWouldNot() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);
        SeatView hand = mullView(Set.of("Umbral Mantle", "Forest", "Llanowar Elves"),
                SELVALA_CMD, 7, 3);
        assertTrue("piece + playable lands = keep", pilot.mulliganKeep(hand, 0, true, false));
        assertEquals(1, events.size());
        ArenaEvent decision = events.get(0);
        assertEquals("mulligan_decision", decision.t());
        assertEquals("keep", decision.fields().get("decision"));
        assertEquals("combo_piece_hand", decision.fields().get("reason"));
        @SuppressWarnings("unchecked")
        Map<String, Object> summary = (Map<String, Object>) decision.fields().get("hand_distance");
        assertEquals(List.of("Umbral Mantle"), summary.get("pieces"));
        assertEquals(3, summary.get("lands"));
        assertEquals(7, summary.get("hand_size"));
        assertEquals("Mantle in hand + Selvala in command -> distance 0",
                0, summary.get("best_bound_distance"));
        assertAllValid(events);
    }

    @Test
    public void mulliganKeepsAPayoffBehindRealLands() throws Exception {
        RoutePlan plan = new RoutePlan(List.of(),
                Map.of("mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                plan, null, 0.0, 0, events::add);
        SeatView hand = mullView(Set.of("Craterhoof Behemoth", "Forest", "Rampant Growth"),
                SELVALA_CMD, 7, 4);
        assertTrue(pilot.mulliganKeep(hand, 0, true, false));
        assertEquals("payoff_with_lands", events.get(0).fields().get("reason"));
        assertAllValid(events);
    }

    @Test
    public void mulliganSpendsTheFreeMullDiggingThenDefersToStock() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);
        SeatView dead = mullView(Set.of("Forest", "Rampant Growth", "Llanowar Elves"),
                SELVALA_CMD, 7, 3);
        // free 4-player mulligan: a hand with no piece and no payoff digs,
        // overriding a stock keep
        assertFalse(pilot.mulliganKeep(dead, 0, true, true));
        assertEquals("dig_for_pieces", events.get(0).fields().get("reason"));
        // the dig spent: same dead hand at depth 1 is stock's call again
        assertTrue(pilot.mulliganKeep(dead, 1, true, true));
        assertEquals("stock_keep", events.get(1).fields().get("reason"));
        // and without a free mull (2-player goldfish), never dig
        assertTrue(pilot.mulliganKeep(dead, 0, false, true));
        assertEquals("stock_keep", events.get(2).fields().get("reason"));
        assertAllValid(events);
    }

    @Test
    public void mulliganLandScrewedPieceHandStaysStocksCall() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);
        // Mantle + 1 land: the piece rule demands >=2 lands, no dig (a piece
        // is present), so stock's mulligan verdict stands
        SeatView screwed = mullView(Set.of("Umbral Mantle", "Forest"), SELVALA_CMD, 7, 1);
        assertFalse(pilot.mulliganKeep(screwed, 0, true, false));
        assertEquals("stock_mulligan", events.get(0).fields().get("reason"));
        assertAllValid(events);
    }

    @Test
    public void mulliganWithNoComboAssetsIsPureStockAndSilent() throws Exception {
        // inertness: unbound combo + empty route plan = no assets, no events
        ExecutorBindings empty = ExecutorBindings.load(Path.of("/nonexistent"));
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), empty,
                0.0, 0, events::add);
        SeatView hand = mullView(Set.of("Umbral Mantle", "Forest"), SELVALA_CMD, 7, 3);
        assertTrue(pilot.mulliganKeep(hand, 0, true, true));
        assertFalse(pilot.mulliganKeep(hand, 0, true, false));
        assertTrue("no combo information -> no phantom events (plan §5)", events.isEmpty());
    }

    @Test
    public void protectedMulliganCardsCoverBoundPiecesAndPayoffs() {
        RoutePlan plan = new RoutePlan(List.of(),
                Map.of("mass_pump", List.of("Craterhoof Behemoth")));
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                plan, null, 0.0, 0, e -> {
                });
        Set<String> shielded = pilot.protectedMulliganCards(
                mullView(Set.of(), SELVALA_CMD, 0, 0));
        assertTrue(shielded.contains("Umbral Mantle"));
        assertTrue(shielded.contains("Selvala, Heart of the Wilds"));
        assertTrue(shielded.contains("Craterhoof Behemoth"));
        assertFalse(shielded.contains("Forest"));
    }

    @Test
    public void tutorUrgencyEscalatesFromImminentToConversion() throws Exception {
        Path dir = Files.createTempDirectory("pilot-urgency");
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "527-2816", "archetype": "TapForManaUntapLoop",
                   "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                              "activation_cost": "{G}", "untap_cost": "{3}",
                              "untap_ability_host": "engine", "pool_color": "G"}}],
                 "unbound": []}""");
        ExecutorBindings shortcutBindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        RoutePlan plan = new RoutePlan(List.of(),
                Map.of("mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        ComboTracker tracker = new ComboTracker(List.of(MANTLE_DEF));
        ComboPilot pilot = new ComboPilot(tracker, shortcutBindings, plan,
                new TutorRanker(Map.of(), tracker, Set.of("Craterhoof Behemoth")),
                0.0, 0, events::add);

        // combo ready (distance 0, bound) but nothing fired: IMMINENT — the
        // payoff already carries an opinion, below a finishing piece
        var beforeFire = pilot.rankTutor("Green Sun's Zenith",
                List.of("Llanowar Elves", "Craterhoof Behemoth"), ready(3));
        assertEquals("Craterhoof Behemoth", beforeFire.get(0).card());
        assertEquals(TutorRanker.PAYOFF_IMMINENT, beforeFire.get(0).score(), 1e-9);

        // shortcut fires: CONVERSION — the floated pool needs the payoff NOW
        assertFalse(pilot.nextAction(ready(3), true, PROFITABLE).orElseThrow().isStep());
        var afterFire = pilot.rankTutor("Green Sun's Zenith",
                List.of("Llanowar Elves", "Craterhoof Behemoth"), ready(3));
        assertEquals("Craterhoof Behemoth", afterFire.get(0).card());
        assertEquals(TutorRanker.PAYOFF_CONVERSION, afterFire.get(0).score(), 1e-9);
        assertTrue(afterFire.get(0).why().contains("converts"));
        assertEquals(2, events.stream().filter(e -> "tutor_decision".equals(e.t())).count());
        assertAllValid(events);
    }

    @Test
    public void notReadyMeansNoEventsAtAll() {
        List<ArenaEvent> events = new ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(MANTLE_DEF)), bindings,
                0.0, 0, events::add);
        SeatView missingPiece = new SeatView(0, 3, Map.of(
                SeatView.Zone.BATTLEFIELD, Set.of("Selvala, Heart of the Wilds"),
                SeatView.Zone.HAND, Set.of(),
                SeatView.Zone.COMMAND, Set.of(),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80);
        assertTrue(pilot.nextAction(missingPiece, true, PROFITABLE).isEmpty());
        assertTrue("the situation never arose — no events (plan §5)", events.isEmpty());
    }
}
