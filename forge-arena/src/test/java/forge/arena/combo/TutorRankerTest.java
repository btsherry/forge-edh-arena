package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.testng.annotations.Test;

import forge.arena.engine.SeatView;
import forge.arena.report.ArenaEvent;

/**
 * Plan §8 TutorRankerTest: line-completing targets outrank generic value,
 * empty artifacts leave the ordering untouched (inertness), and a real
 * opinion is recorded as a schema-shaped tutor_decision.
 */
public class TutorRankerTest {

    private static final ComboDef MANTLE_DEF = new ComboDef("527-2816", List.of(
            new ComboDef.Piece("Selvala, Heart of the Wilds", true),
            new ComboDef.Piece("Umbral Mantle", false)), 0);

    private static SeatView selvalaOnBoardMantleMissing() {
        return new SeatView(0, 5, Map.of(
                SeatView.Zone.BATTLEFIELD, Set.of("Selvala, Heart of the Wilds"),
                SeatView.Zone.HAND, Set.of(),
                SeatView.Zone.COMMAND, Set.of(),
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80);
    }

    @Test
    public void lineCompletingTargetOutranksDossierWeightAndStock() {
        TutorRanker ranker = new TutorRanker(
                Map.of("Craterhoof Behemoth", 0.47, "Umbral Mantle", 0.93),
                new ComboTracker(List.of(MANTLE_DEF)));
        List<TutorRanker.Ranked> ranked = ranker.rank(
                List.of("Reclamation Sage", "Craterhoof Behemoth", "Umbral Mantle"),
                selvalaOnBoardMantleMissing());
        // Mantle completes a distance-1 combo: leverage 1.0 beats its own 0.93
        assertEquals("Umbral Mantle", ranked.get(0).card());
        assertEquals(1.0, ranked.get(0).score(), 1e-9);
        assertTrue(ranked.get(0).why().contains("completes"));
        assertEquals("Craterhoof Behemoth", ranked.get(1).card());
        assertEquals("dossier tutor weight", ranked.get(1).why());
        assertEquals("stock_heuristic", ranked.get(2).why());
        assertEquals(0.0, ranked.get(2).score(), 1e-9);
    }

    @Test
    public void emptyArtifactsAreInert() {
        // §8 inertness: no weights, no combos -> every score 0, input order kept
        TutorRanker ranker = new TutorRanker(Map.of(), new ComboTracker(List.of()));
        List<TutorRanker.Ranked> ranked = ranker.rank(
                List.of("Card A", "Card B", "Card C"), selvalaOnBoardMantleMissing());
        assertEquals(List.of("Card A", "Card B", "Card C"),
                ranked.stream().map(TutorRanker.Ranked::card).toList());
        assertTrue(ranked.stream().allMatch(r -> r.score() == 0.0));
    }

    @Test
    public void pilotRecordsARealOpinionAndStaysSilentWithoutOne() throws Exception {
        List<ArenaEvent> events = new ArrayList<>();
        ComboTracker tracker = new ComboTracker(List.of(MANTLE_DEF));
        ComboPilot pilot = new ComboPilot(tracker, ExecutorBindings.load(
                java.nio.file.Path.of("/nonexistent")), RoutePlan.empty(),
                new TutorRanker(Map.of(), tracker), 0.0, 0, events::add);

        // opinion: Mantle completes -> tutor_decision with full ranking
        List<TutorRanker.Ranked> ranked = pilot.rankTutor("Green Sun's Zenith",
                List.of("Umbral Mantle", "Llanowar Elves"), selvalaOnBoardMantleMissing());
        assertEquals("Umbral Mantle", ranked.get(0).card());
        assertEquals(1, events.size());
        ArenaEvent decision = events.get(0);
        assertEquals("tutor_decision", decision.t());
        assertEquals("Green Sun's Zenith", decision.fields().get("source"));
        assertEquals("Umbral Mantle", decision.fields().get("chosen"));

        // no opinion: nothing rankable -> stock decides, NO event (the
        // situation carried no combo information — not a decision point)
        assertTrue(pilot.rankTutor("Green Sun's Zenith",
                List.of("Llanowar Elves", "Reclamation Sage"),
                selvalaOnBoardMantleMissing()).isEmpty());
        assertEquals(1, events.size());

        // and the recorded decision validates against the taxonomy
        try (var in = java.nio.file.Files.newInputStream(
                java.nio.file.Path.of("schemas", "arena.events.1.schema.json"))) {
            var schema = com.networknt.schema.JsonSchemaFactory
                    .getInstance(com.networknt.schema.SpecVersion.VersionFlag.V202012).getSchema(in);
            var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            var errors = schema.validate(mapper.readTree(
                    mapper.writeValueAsString(decision.toJsonMap())));
            assertTrue("invalid tutor_decision: " + errors, errors.isEmpty());
        }
    }
}
