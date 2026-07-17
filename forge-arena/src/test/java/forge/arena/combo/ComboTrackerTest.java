package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;

import org.testng.annotations.Test;

import forge.arena.engine.SeatView;

/** Plan §8 ComboDistanceTest semantics + HiddenInfo behavior, no engine needed. */
public class ComboTrackerTest {

    private static SeatView view(Set<String> battlefield, Set<String> hand, Set<String> command,
            Set<String> graveyard) {
        return new SeatView(0, 3, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, command,
                SeatView.Zone.GRAVEYARD, graveyard,
                SeatView.Zone.EXILE, Set.of()), 90);
    }

    private static final ComboDef MANTLE = new ComboDef("csb-1", List.of(
            new ComboDef.Piece("Selvala, Heart of the Wilds", true),
            new ComboDef.Piece("Umbral Mantle", false)), 0);
    private static final ComboDef TEMPLATED = new ComboDef("csb-2", List.of(
            new ComboDef.Piece("Isochron Scepter", false)), 1);

    @Test
    public void commandZoneCountsAsReachableAndDistanceIsMonotonic() {
        ComboTracker tracker = new ComboTracker(List.of(MANTLE));
        // both pieces invisible (library = ABSENT)
        assertEquals(2, tracker.recompute(view(Set.of(), Set.of(), Set.of(), Set.of()))
                .byId("csb-1").distance());
        // commander in command zone: reachable
        assertEquals(1, tracker.recompute(view(Set.of(), Set.of(), Set.of("Selvala, Heart of the Wilds"), Set.of()))
                .byId("csb-1").distance());
        // Mantle drawn: distance 0, ready
        ComboTracker.ComboStatus s = tracker.recompute(view(
                Set.of(), Set.of("Umbral Mantle"), Set.of("Selvala, Heart of the Wilds"), Set.of()))
                .byId("csb-1");
        assertEquals(0, s.distance());
        assertTrue(s.ready());
        assertEquals("COMMAND", s.where().get("Selvala, Heart of the Wilds"));
    }

    @Test
    public void graveyardIsNotReachableWithoutRecursion() {
        ComboTracker tracker = new ComboTracker(List.of(MANTLE));
        ComboTracker.ComboStatus s = tracker.recompute(view(
                Set.of("Selvala, Heart of the Wilds"), Set.of(), Set.of(), Set.of("Umbral Mantle")))
                .byId("csb-1");
        assertEquals(1, s.distance());
        assertFalse(s.ready());
        assertEquals("GRAVEYARD", s.where().get("Umbral Mantle"));
    }

    @Test
    public void templateRequirementCombosAreNeverReadyInDetectionOnlyMode() {
        ComboTracker tracker = new ComboTracker(List.of(TEMPLATED));
        ComboTracker.ComboStatus s = tracker.recompute(view(
                Set.of("Isochron Scepter"), Set.of(), Set.of(), Set.of())).byId("csb-2");
        assertEquals(0, s.distance());
        assertFalse("unnamed template piece missing -> validation-gated, never auto-ready", s.ready());
        assertFalse(s.fullySpecified());
    }

    @Test
    public void seatViewHidesTheLibraryStructurally() {
        SeatView v = view(Set.of(), Set.of(), Set.of(), Set.of());
        // a card that exists only in the library is ABSENT to the view
        assertEquals(SeatView.Presence.ABSENT, v.locate("Craterhoof Behemoth"));
        assertEquals(90, v.librarySize());
        // API whitelist: no public method may expose card lists beyond the visible
        // zones (PR-16 adds own manaPool + opponents' PUBLIC state — life/poison/
        // battlefield; still structurally no hands, no libraries)
        Set<String> allowed = Set.of("seatIndex", "turn", "cardsIn", "librarySize", "locate",
                "manaPool", "ownBoardPower", "opponents",
                "equals", "hashCode", "toString", "getClass", "notify", "notifyAll", "wait");
        for (var m : SeatView.class.getMethods()) {
            assertTrue("unexpected public API on SeatView (W8): " + m.getName(),
                    allowed.contains(m.getName()));
        }
    }
}
