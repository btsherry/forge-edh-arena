package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertNull;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;

import org.testng.annotations.Test;

import forge.arena.engine.SeatView;
import forge.arena.prep.PayoffRules;

/**
 * Phase 6 / PR-38 — the conversion state machine's decision order and its
 * hard guards. Every case is artifact-driven (payoff classes from a
 * route-coverage plan), so the same logic serves any dropped-in deck.
 */
public class ConversionPlannerTest {

    private static final RoutePlan PLAN = new RoutePlan(List.of(), Map.of(
            PayoffRules.X_DRAIN_EACH_OPPONENT, List.of("Exsanguinate"),
            PayoffRules.PING_ANY_TARGET, List.of("Walking Ballista"),
            PayoffRules.SELF_DRAW_ENGINE, List.of("Blue Sun's Zenith")));

    private static SeatView view(Set<String> hand, Set<String> battlefield,
            Set<String> command, int librarySize) {
        return new SeatView(0, 5, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, command,
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), librarySize);
    }

    @Test
    public void tableWideOutletOutranksEverythingElse() {
        // all three classes available at once: the one-resolution table
        // killer must win — no combat, no splitting, life loss dodges
        // prevention (playbook §1.2)
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view(Set.of("Exsanguinate", "Blue Sun's Zenith"), Set.of("Walking Ballista"),
                        Set.of(), 60),
                PLAN, Set.of(), Set.of());
        assertEquals(ConversionPlanner.Kind.TABLE_WIDE, plan.kind());
        assertEquals("Exsanguinate", plan.card());
        assertEquals(ComboPilot.DEPLOY_X, plan.x());
    }

    @Test
    public void singleTargetSinkArmsTheDrillWhenNoTableWideExists() {
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view(Set.of("Blue Sun's Zenith"), Set.of("Walking Ballista"), Set.of(), 60),
                PLAN, Set.of(), Set.of());
        assertEquals(ConversionPlanner.Kind.DRILL, plan.kind());
        assertEquals("Walking Ballista", plan.card());
    }

    @Test
    public void noOutletDigsRatherThanPassingTheTurn() {
        // the playbook's first law: never end a turn with an unused engine
        // and an unsearched library
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view(Set.of("Blue Sun's Zenith"), Set.of(), Set.of(), 60),
                PLAN, Set.of(), Set.of());
        assertEquals(ConversionPlanner.Kind.DIG, plan.kind());
        assertEquals(ConversionPlanner.DIG_CAP, plan.x());
    }

    @Test
    public void digIsBoundedByTheLibraryFloorAndNeverDecksTheSeat() {
        // 8 cards left: draw at most 8 - floor(5) = 3. Drawing the last card
        // LOSES at the next state-based check (CR 121.4/704.5b) and a
        // simultaneous win-and-lose is still a loss (CR 104.3f)
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view(Set.of("Blue Sun's Zenith"), Set.of(), Set.of(), 8),
                PLAN, Set.of(), Set.of());
        assertEquals(ConversionPlanner.Kind.DIG, plan.kind());
        assertEquals(3, plan.x());

        // at the floor itself, digging stops entirely
        ConversionPlanner.Plan starved = ConversionPlanner.choose(
                view(Set.of("Blue Sun's Zenith"), Set.of(), Set.of(),
                        ConversionPlanner.LIBRARY_FLOOR),
                PLAN, Set.of(), Set.of());
        assertEquals(ConversionPlanner.Kind.NONE, starved.kind());
    }

    @Test
    public void commandZoneCountsAsReachable() {
        // a Commander pilot that forgets the command zone is useless: the
        // commander is very often the deck's own outlet or dig engine
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view(Set.of(), Set.of(), Set.of("Exsanguinate"), 60),
                PLAN, Set.of(), Set.of());
        assertEquals(ConversionPlanner.Kind.TABLE_WIDE, plan.kind());
    }

    @Test
    public void perTurnDedupeStopsTheSameCardRetryingForever() {
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view(Set.of("Exsanguinate"), Set.of(), Set.of(), 60),
                PLAN, Set.of(), Set.of("Exsanguinate"));
        assertEquals(ConversionPlanner.Kind.NONE, plan.kind());
        assertNull(plan.card());
    }

    @Test
    public void aDeckWithNoOutletArtifactsIsInert() {
        // inertness: no payoff classes -> no conversion decisions at all,
        // the deploy path keeps the turn exactly as before
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view(Set.of("Forest"), Set.of("Llanowar Elves"), Set.of(), 60),
                RoutePlan.empty(), Set.of(), Set.of());
        assertEquals(ConversionPlanner.Kind.NONE, plan.kind());
        assertTrue(ConversionPlanner.Plan.NOTHING.kind() == ConversionPlanner.Kind.NONE);
    }
}
