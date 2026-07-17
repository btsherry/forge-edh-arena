package forge.arena.report;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Plan §8 PilotQualityFloorsTest: below-floor conversion marks the deck
 * pilot_invalid naming the metric; above-floor is admitted; silent
 * ready-with-no-attempt games are violations even when the rate passes.
 */
public class PilotQualityFloorsTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static List<JsonNode> game(String json) throws Exception {
        List<JsonNode> events = new ArrayList<>();
        for (String line : json.strip().split("\n")) {
            events.add(MAPPER.readTree(line));
        }
        return events;
    }

    /**
     * One game: selvala seat 0; ready at turn 3 with the game running to
     * turn 9 (so a later decision point existed — the PR-18 completeness
     * refinement only demands a record when the pilot had a next turn).
     */
    private static List<JsonNode> selvalaGame(boolean ready, boolean attempted, boolean ignored)
            throws Exception {
        StringBuilder sb = new StringBuilder(
                "{\"t\":\"game_start\",\"seats\":[\"selvala\",\"purphoros\"],\"seed\":1}\n");
        if (ready) {
            sb.append("{\"t\":\"combo_ready\",\"turn\":3,\"seat\":0,\"combo\":\"c1\","
                    + "\"window\":\"MAIN1\"}\n");
        }
        if (attempted) {
            sb.append("{\"t\":\"combo_shortcut\",\"turn\":3,\"seat\":0,\"combo\":\"c1\","
                    + "\"iterations_proven\":3,\"bounded_product\":{\"mana_G\":10000}}\n");
        }
        if (ignored) {
            sb.append("{\"t\":\"combo_ignored\",\"turn\":3,\"seat\":0,\"combo\":\"c1\","
                    + "\"reason\":\"threat_assessment\"}\n");
        }
        sb.append("{\"t\":\"game_end\",\"turn\":9,\"win_condition\":\"Draw\"}");
        return game(sb.toString());
    }

    @Test
    public void readyAtGameEndWithoutADecisionPointIsNotAViolation() throws Exception {
        // ready on the game's LAST turn: the pilot never had a next turn,
        // silence is the absence of a decision point, not a missing record
        List<List<JsonNode>> games = List.of(
                game("{\"t\":\"game_start\",\"seats\":[\"selvala\"],\"seed\":7}\n"
                        + "{\"t\":\"combo_ready\",\"turn\":9,\"seat\":0,\"combo\":\"c1\","
                        + "\"window\":\"MAIN1\"}\n"
                        + "{\"t\":\"game_end\",\"turn\":9,\"win_condition\":\"Draw\"}"),
                game("{\"t\":\"game_start\",\"seats\":[\"selvala\"],\"seed\":8}\n"
                        + "{\"t\":\"combo_ready\",\"turn\":3,\"seat\":0,\"combo\":\"c1\","
                        + "\"window\":\"MAIN1\"}\n"
                        + "{\"t\":\"combo_shortcut\",\"turn\":3,\"seat\":0,\"combo\":\"c1\","
                        + "\"iterations_proven\":3,\"bounded_product\":{}}\n"
                        + "{\"t\":\"game_end\",\"turn\":9,\"win_condition\":\"Draw\"}"));
        PilotFloors.DeckFloors floors = PilotFloors.evaluate("selvala", games, 0.5);
        assertTrue("violations: " + floors.violations(), floors.pilotValid());
    }

    @Test
    public void lateReadyWithNoSubsequentOwnTurnIsNotAViolation() throws Exception {
        // PR-28 (found live): a 4-seat pod's seat gets a turn every 4 global
        // turns — ready at t24 with the game ending t26 means the seat NEVER
        // got another MAIN1; silence is the absence of a decision point
        List<List<JsonNode>> games = List.of(
                game("{\"t\":\"game_start\",\"seats\":[\"a\",\"selvala\",\"b\",\"c\"],\"seed\":5}\n"
                        + "{\"t\":\"combo_ready\",\"turn\":24,\"seat\":1,\"combo\":\"c1\","
                        + "\"window\":\"MAIN1\"}\n"
                        + "{\"t\":\"game_end\",\"turn\":26,\"win_condition\":\"Draw\"}"),
                game("{\"t\":\"game_start\",\"seats\":[\"a\",\"selvala\",\"b\",\"c\"],\"seed\":6}\n"
                        + "{\"t\":\"combo_ready\",\"turn\":3,\"seat\":1,\"combo\":\"c1\","
                        + "\"window\":\"MAIN1\"}\n"
                        + "{\"t\":\"combo_shortcut\",\"turn\":7,\"seat\":1,\"combo\":\"c1\","
                        + "\"iterations_proven\":3,\"bounded_product\":{}}\n"
                        + "{\"t\":\"game_end\",\"turn\":30,\"win_condition\":\"Draw\"}"));
        PilotFloors.DeckFloors floors = PilotFloors.evaluate("selvala", games, 0.5);
        assertTrue("violations: " + floors.violations(), floors.pilotValid());
    }

    @Test
    public void aboveFloorWithCompleteTelemetryIsValid() throws Exception {
        List<List<JsonNode>> games = List.of(
                selvalaGame(true, true, false),
                selvalaGame(true, true, false),
                selvalaGame(true, false, true),   // declined, but RECORDED
                selvalaGame(false, false, false));
        PilotFloors.DeckFloors floors = PilotFloors.evaluate("selvala", games, 0.5);
        assertTrue("violations: " + floors.violations(), floors.pilotValid());
        assertEquals(4, floors.gamesSeated());
        assertEquals(3, floors.readyGames());
        assertEquals(2, floors.attemptedGames());
    }

    @Test
    public void belowFloorIsPilotInvalidNamingTheMetric() throws Exception {
        List<List<JsonNode>> games = List.of(
                selvalaGame(true, true, false),
                selvalaGame(true, false, true),
                selvalaGame(true, false, true),
                selvalaGame(true, false, true));
        PilotFloors.DeckFloors floors = PilotFloors.evaluate("selvala", games, 0.5);
        assertFalse(floors.pilotValid());
        assertTrue(floors.violations().toString(),
                floors.violations().get(0).contains("conversion-when-ready 1/4 below floor"));
    }

    @Test
    public void silentReadyGameIsAViolationEvenWhenTheRatePasses() throws Exception {
        List<List<JsonNode>> games = List.of(
                selvalaGame(true, true, false),
                selvalaGame(true, true, false),
                selvalaGame(true, false, false)); // ready, no attempt, NO record
        PilotFloors.DeckFloors floors = PilotFloors.evaluate("selvala", games, 0.5);
        assertFalse("silence is never a valid record of a decision", floors.pilotValid());
        assertTrue(floors.violations().get(0).contains("lacks combo_ignored"));
    }

    @Test
    public void stallWithoutItsDumpFileIsAViolationAndWithItIsNot() throws Exception {
        Path dump = Files.createTempFile("stall", ".txt");
        List<List<JsonNode>> good = List.of(game(
                "{\"t\":\"game_start\",\"seats\":[\"selvala\"],\"seed\":1}\n"
                + "{\"t\":\"combo_ready\",\"seat\":0,\"combo\":\"c1\",\"window\":\"MAIN1\"}\n"
                + "{\"t\":\"combo_shortcut\",\"seat\":0,\"combo\":\"c1\",\"iterations_proven\":3,"
                + "\"bounded_product\":{}}\n"
                + "{\"t\":\"combo_stalled\",\"seat\":0,\"binding\":\"c1\",\"state_hash\":\"ab\","
                + "\"dump_path\":\"" + dump + "\"}\n"
                + "{\"t\":\"game_end\",\"win_condition\":\"Draw\"}"));
        assertTrue(PilotFloors.evaluate("selvala", good, 0.5).pilotValid());

        List<List<JsonNode>> bad = List.of(game(
                "{\"t\":\"game_start\",\"seats\":[\"selvala\"],\"seed\":1}\n"
                + "{\"t\":\"combo_ready\",\"seat\":0,\"combo\":\"c1\",\"window\":\"MAIN1\"}\n"
                + "{\"t\":\"combo_shortcut\",\"seat\":0,\"combo\":\"c1\",\"iterations_proven\":3,"
                + "\"bounded_product\":{}}\n"
                + "{\"t\":\"combo_stalled\",\"seat\":0,\"binding\":\"c1\",\"state_hash\":\"ab\","
                + "\"dump_path\":\"/nonexistent/stall.txt\"}\n"
                + "{\"t\":\"game_end\",\"win_condition\":\"Draw\"}"));
        PilotFloors.DeckFloors floors = PilotFloors.evaluate("selvala", bad, 0.5);
        assertFalse(floors.pilotValid());
        assertTrue(floors.violations().get(0).contains("without its dump file"));
    }

    @Test
    public void rotationIsRespectedSeatIndexComesFromEachGame() throws Exception {
        // same deck, different seat per game (latin square) — events at other
        // seats must never count for it
        List<List<JsonNode>> games = List.of(
                game("{\"t\":\"game_start\",\"seats\":[\"selvala\",\"purphoros\"],\"seed\":1}\n"
                        + "{\"t\":\"combo_ready\",\"seat\":0,\"combo\":\"c1\",\"window\":\"M\"}\n"
                        + "{\"t\":\"combo_shortcut\",\"seat\":0,\"combo\":\"c1\","
                        + "\"iterations_proven\":3,\"bounded_product\":{}}\n"
                        + "{\"t\":\"game_end\",\"win_condition\":\"Draw\"}"),
                game("{\"t\":\"game_start\",\"seats\":[\"purphoros\",\"selvala\"],\"seed\":2}\n"
                        + "{\"t\":\"combo_ready\",\"seat\":0,\"combo\":\"c9\",\"window\":\"M\"}\n"
                        + "{\"t\":\"game_end\",\"win_condition\":\"Draw\"}"));
        PilotFloors.DeckFloors floors = PilotFloors.evaluate("selvala", games, 0.5);
        assertEquals(2, floors.gamesSeated());
        assertEquals("seat-0 ready in game 2 belongs to purphoros, not selvala",
                1, floors.readyGames());
        assertTrue(floors.pilotValid());
    }
}
