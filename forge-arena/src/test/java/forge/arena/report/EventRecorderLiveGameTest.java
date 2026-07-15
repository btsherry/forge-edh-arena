package forge.arena.report;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameEventBridge;
import forge.arena.engine.SeatSpec;

/**
 * Integration: a real pod game recorded through both sinks — every JSONL line
 * must validate against arena.events/1, game_start first, game_end last, and
 * the run.log must carry correctly prefixed lines.
 */
public class EventRecorderLiveGameTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void liveGameProducesSchemaValidDualSinkLogs() throws Exception {
        Path runDir = Files.createTempDirectory("arena-run");
        List<SeatSpec> seats = List.of(
                SeatSpec.of(new File("decks/giada-font-of-hope.dck")),
                SeatSpec.of(new File("decks/purphoros-god-of-the-forge.dck")),
                SeatSpec.of(new File("decks/selvala-heart-of-the-wilds.dck")),
                SeatSpec.of(new File("decks/urza-lord-high-artificer.dck")));

        ArenaGameResult result;
        try (RunLog runLog = new RunLog(runDir.resolve("run.log"), "0", RunLogRenderer.Tier.VERBOSE)) {
            EventRecorder recorder = EventRecorder.open(
                    runDir.resolve("events"), 7, 42L,
                    List.of("giada", "purphoros", "selvala", "urza"), runLog);
            GameEventBridge bridge = new GameEventBridge(recorder);
            result = EngineFacade.playCommanderGame(seats, 42L, new ArenaLimits(4, 300, 0), bridge);
            recorder.finish(result);
        }

        // --- JSONL sink ---
        List<String> lines = Files.readAllLines(runDir.resolve("events").resolve("000007.jsonl"));
        assertTrue("expected a real event stream, got " + lines.size() + " lines", lines.size() > 20);

        JsonSchema schema;
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.events.1.schema.json"))) {
            schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
        for (String line : lines) {
            JsonNode node = MAPPER.readTree(line);
            Set<ValidationMessage> errors = schema.validate(node);
            assertTrue("invalid event line: " + line + " -> " + errors, errors.isEmpty());
        }

        JsonNode first = MAPPER.readTree(lines.get(0));
        assertEquals("game_start", first.get("t").asText());
        assertEquals(42L, first.get("seed").asLong());

        JsonNode last = MAPPER.readTree(lines.get(lines.size() - 1));
        assertEquals("game_end", last.get("t").asText());
        assertEquals("timeout_draw", last.get("result").asText());
        assertEquals("turns", last.get("limiting_factor").asText());

        boolean sawTurnThree = lines.stream().anyMatch(l -> l.contains("\"t\":\"turn_begin\"") && l.contains("\"turn\":3"));
        assertTrue("turn_begin events must be bridged", sawTurnThree);

        // --- human sink ---
        List<String> human = Files.readAllLines(runDir.resolve("run.log"));
        assertTrue("run.log must have lines", !human.isEmpty());
        assertTrue("every line carries the [w0 g0007 ...] prefix",
                human.stream().allMatch(l -> l.startsWith("[w0 g0007")));
        assertTrue("game_end must render at any tier",
                human.get(human.size() - 1).contains("TIMEOUT_DRAW"));
    }
}
