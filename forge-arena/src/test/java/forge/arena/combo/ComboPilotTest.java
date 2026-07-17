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
