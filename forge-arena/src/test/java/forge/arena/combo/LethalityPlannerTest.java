package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

import forge.arena.engine.SeatView;
import forge.arena.report.ArenaEvent;

/**
 * Plan §8 MultiplayerLethalityTest (v1 predicates) + the route telemetry
 * contract: every considered route records selected/rejected with predicate
 * values, every event validates, BANK_AND_HOLD only after real rejections.
 */
public class LethalityPlannerTest {

    private static final RoutePlan SELVALA_PLAN = new RoutePlan(
            List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                            List.of("Concordant Crossroads", "Craterhoof Behemoth")),
                    new RoutePlan.PlannedRoute("COMMANDER_DMG_SEQUENCE", "conversion", "supported",
                            List.of("Selvala, Heart of the Wilds")),
                    new RoutePlan.PlannedRoute("ORACLE_WIN", "conversion", "unsupported", List.of()),
                    new RoutePlan.PlannedRoute("DIRECT_DAMAGE_LOOP", "conversion", "unsupported",
                            List.of())),
            Map.of("haste_static", List.of("Concordant Crossroads"),
                    "mass_pump", List.of("Craterhoof Behemoth", "Finale of Devastation"),
                    "commander_creature", List.of("Selvala, Heart of the Wilds")));

    private JsonSchema eventsSchema;

    @BeforeClass
    public void schema() throws Exception {
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.events.1.schema.json"))) {
            eventsSchema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }

    private static SeatView view(Set<String> battlefield, Set<String> hand, int boardPower,
            int oppLife) {
        return new SeatView(0, 7, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, Set.of(),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 60, 10000, boardPower,
                List.of(new SeatView.OpponentView(1, oppLife, 0, Set.of()),
                        new SeatView.OpponentView(2, oppLife, 0, Set.of()),
                        new SeatView.OpponentView(3, oppLife, 0, Set.of())));
    }

    private void assertAllValid(List<ArenaEvent> events) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        for (ArenaEvent e : events) {
            var errors = eventsSchema.validate(mapper.readTree(mapper.writeValueAsString(e.toJsonMap())));
            assertTrue("invalid event " + e.toJsonMap() + " -> " + errors, errors.isEmpty());
        }
    }

    @Test
    public void selvalaBoardWithCrossroadsAndCraterhoofSpreadsCombat() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(SELVALA_PLAN,
                view(Set.of("Concordant Crossroads", "Selvala, Heart of the Wilds"),
                        Set.of("Craterhoof Behemoth"), 8, 40),
                events::add);
        assertEquals("SPREAD_COMBAT", verdict.route());
        // unsupported routes were never live decisions — no phantom rejections
        assertTrue(events.stream().noneMatch(e -> "ORACLE_WIN".equals(e.fields().get("route"))));
        ArenaEvent selected = events.get(events.size() - 1);
        assertEquals("route_selected", selected.t());
        @SuppressWarnings("unchecked")
        Map<String, Object> predicates = (Map<String, Object>) selected.fields().get("predicates");
        assertEquals("Concordant Crossroads", predicates.get("haste_source"));
        assertEquals("Craterhoof Behemoth", predicates.get("mass_pump"));
        assertEquals(120L, predicates.get("table_life"));
        assertAllValid(events);
    }

    @Test
    public void alphaBelowTableLifeWithoutPumpIsRejectedNotAttempted() throws Exception {
        // plan §8 MultiplayerLethalityTest: never a losing SPREAD_COMBAT
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(SELVALA_PLAN,
                view(Set.of("Concordant Crossroads", "Selvala, Heart of the Wilds"),
                        Set.of(), 8, 40), // no pump visible, 8 power vs 120 life
                events::add);
        assertEquals("COMMANDER_DMG_SEQUENCE", verdict.route()); // Selvala on battlefield
        ArenaEvent rejected = events.stream()
                .filter(e -> e.t().equals("route_rejected")).findFirst().orElseThrow();
        assertEquals("SPREAD_COMBAT", rejected.fields().get("route"));
        assertEquals("projected_alpha_below_table_life", rejected.fields().get("failed_predicate"));
        assertAllValid(events);
    }

    @Test
    public void everythingRejectedBanksAndHolds() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        // commander stuck in the command zone, no haste source visible
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(SELVALA_PLAN,
                new SeatView(0, 7, Map.of(
                        SeatView.Zone.BATTLEFIELD, Set.of("Forest"),
                        SeatView.Zone.HAND, Set.of(),
                        SeatView.Zone.COMMAND, Set.of("Selvala, Heart of the Wilds"),
                        SeatView.Zone.GRAVEYARD, Set.of(),
                        SeatView.Zone.EXILE, Set.of()), 60, 10000, 0,
                        List.of(new SeatView.OpponentView(1, 40, 0, Set.of()))),
                events::add);
        assertEquals("BANK_AND_HOLD", verdict.route());
        assertEquals("both real routes must record their rejections first", 2,
                events.stream().filter(e -> e.t().equals("route_rejected")).count());
        assertAllValid(events);
    }

    @Test
    public void directDamageOutranksCombatWhenASinkIsVisible() throws Exception {
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("DIRECT_DAMAGE_LOOP", "conversion", "supported",
                                List.of("Fireball")),
                        new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                                List.of("Concordant Crossroads"))),
                Map.of("x_damage", List.of("Fireball"),
                        "haste_static", List.of("Concordant Crossroads")));
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(plan,
                view(Set.of("Concordant Crossroads"), Set.of("Fireball"), 5, 40), events::add);
        assertEquals("least interactable same-turn route wins", "DIRECT_DAMAGE_LOOP",
                verdict.route());
        assertAllValid(events);
    }

    @Test
    public void emptyPlanBanksImmediately() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(RoutePlan.empty(),
                view(Set.of(), Set.of(), 0, 40), events::add);
        assertEquals("BANK_AND_HOLD", verdict.route());
        assertEquals(1, events.size());
        assertAllValid(events);
    }
}
