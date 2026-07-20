package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertNull;
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

    /**
     * A board that owns power but cannot swing with ANY of it — every
     * creature summoning-sick or tapped. This is the only state in which a
     * haste source is what stands between the seat and an attack, so the
     * haste-classification tests use it to isolate that question (PR-54).
     */
    private static SeatView sickView(Set<String> battlefield, Set<String> hand, int boardPower,
            int oppLife) {
        return new SeatView(0, 7, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, Set.of(),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 60, 10000, boardPower,
                List.of(new SeatView.OpponentView(1, oppLife, 0, Set.of()),
                        new SeatView.OpponentView(2, oppLife, 0, Set.of()),
                        new SeatView.OpponentView(3, oppLife, 0, Set.of())),
                Map.of(), 0, 0, 0, /* attackReadyPower */ 0);
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
    public void finaleInHandSatisfiesHasteAsOneshot() throws Exception {
        // PR-25 haste v2 — game 78's exact shape: no static haste anywhere,
        // but Finale in hand is castable off the proven pool and grants haste
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                        List.of("Finale of Devastation"))),
                Map.of("haste_oneshot", List.of("Finale of Devastation"),
                        "mass_pump", List.of("Finale of Devastation")));
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(plan,
                view(Set.of("Selvala, Heart of the Wilds"),
                        Set.of("Finale of Devastation"), 9, 33),
                events::add);
        assertEquals("SPREAD_COMBAT", verdict.route());
        @SuppressWarnings("unchecked")
        Map<String, Object> predicates = (Map<String, Object>)
                events.get(events.size() - 1).fields().get("predicates");
        assertEquals("Finale of Devastation", predicates.get("haste_source"));
        assertEquals("oneshot_in_hand", predicates.get("haste_kind"));
        assertAllValid(events);
    }

    @Test
    public void oneshotHasteOutsideHandDoesNotCount() throws Exception {
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                        List.of("Finale of Devastation"))),
                Map.of("haste_oneshot", List.of("Finale of Devastation"),
                        "mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        // Finale already spent (graveyard is not a castable zone), and every
        // creature is sick or tapped — so haste is genuinely the blocker
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(plan,
                sickView(Set.of("Selvala, Heart of the Wilds"),
                        Set.of("Craterhoof Behemoth"), 9, 40),
                events::add);
        assertEquals("BANK_AND_HOLD", verdict.route());
        ArenaEvent rejected = events.stream()
                .filter(e -> e.t().equals("route_rejected")).findFirst().orElseThrow();
        assertEquals("no_attack_ready_creatures_and_no_haste",
                rejected.fields().get("failed_predicate"));
        assertAllValid(events);
    }

    @Test
    public void aDeployedBoardAttacksWithoutAnyHasteSource() throws Exception {
        // PR-54, the rules bug that cost the green deck 99 of 125 combat
        // evaluations: haste is only needed by creatures that arrived THIS
        // turn. A board deployed on earlier turns swings without it (CR
        // 302.6), so an untapped, unsick board must never be rejected for
        // "no haste source" — the deck owns no haste card in this plan at all.
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                        List.of("Craterhoof Behemoth"))),
                Map.of("mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(plan,
                view(Set.of("Selvala, Heart of the Wilds"),
                        Set.of("Craterhoof Behemoth"), 9, 40),
                events::add);
        assertEquals("SPREAD_COMBAT", verdict.route());
        @SuppressWarnings("unchecked")
        Map<String, Object> predicates = (Map<String, Object>)
                events.get(events.size() - 1).fields().get("predicates");
        // "absent" is the telemetry rendering of a null predicate — the route
        // was selected with NO haste source of any kind, which is the point
        assertEquals("absent", predicates.get("haste_source"));
        assertEquals(9, predicates.get("attack_ready_power"));

        // and the same board, all of it sick or tapped, is correctly rejected
        List<ArenaEvent> sick = new ArrayList<>();
        assertEquals("BANK_AND_HOLD", LethalityPlanner.choose(plan,
                sickView(Set.of("Selvala, Heart of the Wilds"),
                        Set.of("Craterhoof Behemoth"), 9, 40),
                sick::add).route());
        assertAllValid(events);
        assertAllValid(sick);
    }

    @Test
    public void surrakOnBattlefieldCountsAsHasteForDeployedAttackers() throws Exception {
        // PR-25 haste v2: an ETB-haste permanent already on the battlefield
        // makes every DEPLOYED attacker hasty (the Surrak class)
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                        List.of("Surrak and Goreclaw"))),
                Map.of("haste_targeted", List.of("Surrak and Goreclaw"),
                        "mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(plan,
                view(Set.of("Surrak and Goreclaw"), Set.of("Craterhoof Behemoth"), 6, 30),
                events::add);
        assertEquals("SPREAD_COMBAT", verdict.route());
        @SuppressWarnings("unchecked")
        Map<String, Object> predicates = (Map<String, Object>)
                events.get(events.size() - 1).fields().get("predicates");
        assertEquals("targeted_on_battlefield", predicates.get("haste_kind"));

        // in HAND it grants nothing this turn — an ETB-trigger granter only
        // hastens creatures that enter AFTER it, so an army already on the
        // battlefield gains nothing (this is why haste_equip had to split
        // out of this class: an equipment in hand IS usable, a Surrak is not).
        // Shown on a board that cannot swing on its own, so the Surrak is the
        // only thing that could have enabled the attack.
        List<ArenaEvent> events2 = new ArrayList<>();
        assertEquals("BANK_AND_HOLD", LethalityPlanner.choose(plan,
                sickView(Set.of(), Set.of("Surrak and Goreclaw", "Craterhoof Behemoth"), 6, 30),
                events2::add).route());
        assertAllValid(events);
        assertAllValid(events2);
    }

    @Test
    public void equipmentHasteInHandCountsBecauseThePoolCanCastIt() throws Exception {
        // PR-41 / win-routes/6, straight from the 300-game funnel: the green
        // deck had SPREAD_COMBAT rejected 99 times against 26 selections,
        // every rejection haste_source_not_visible, with Lightning Greaves in
        // hand and a thousand floating mana. Cast it, equip it, the creature
        // already on board swings — that is what banking a loop is FOR.
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("SPREAD_COMBAT", "conversion", "supported",
                        List.of("Lightning Greaves"))),
                Map.of("haste_equip", List.of("Lightning Greaves"),
                        "mass_pump", List.of("Craterhoof Behemoth")));
        List<ArenaEvent> events = new ArrayList<>();
        LethalityPlanner.Verdict verdict = LethalityPlanner.choose(plan,
                view(Set.of(), Set.of("Lightning Greaves", "Craterhoof Behemoth"), 6, 30),
                events::add);
        assertEquals("SPREAD_COMBAT", verdict.route());
        @SuppressWarnings("unchecked")
        Map<String, Object> predicates = (Map<String, Object>)
                events.get(events.size() - 1).fields().get("predicates");
        assertEquals("equip_castable", predicates.get("haste_kind"));
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
