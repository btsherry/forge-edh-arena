package forge.arena.harness;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

/**
 * End-to-end worker pool: BatchMain writes a schema-valid manifest first,
 * spawns real worker JVMs, and every game lands in game-records.jsonl —
 * from BOTH workers, all schema-valid, with the shared run.log interleaved.
 */
public class BatchIntegrationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    public void twoWorkerPoolRunsFourGamesEndToEnd() throws Exception {
        Path tmp = Files.createTempDirectory("arena-batch");
        Path runDir = tmp.resolve("run");
        Map<String, Object> cfg = Map.of(
                "run_id", "batch-int-test",
                "seed_base", 42,
                "games", 4,
                "workers", 2,
                "worker_heap", "-Xmx1g",
                "out_dir", runDir.toString(),
                "assets_dir", Path.of("..", "forge-gui").toAbsolutePath().toString(),
                "limits", Map.of("turns", 3, "wall_clock_sec", 300, "priority_passes_per_turn", 2000),
                "seats", List.of(
                        Map.of("deck", Path.of("decks/giada-font-of-hope.dck").toAbsolutePath().toString()),
                        Map.of("deck", Path.of("decks/purphoros-god-of-the-forge.dck").toAbsolutePath().toString()),
                        Map.of("deck", Path.of("decks/selvala-heart-of-the-wilds.dck").toAbsolutePath().toString()),
                        Map.of("deck", Path.of("decks/urza-lord-high-artificer.dck").toAbsolutePath().toString())));
        Path cfgFile = tmp.resolve("config.json");
        Files.writeString(cfgFile, MAPPER.writeValueAsString(cfg));

        int exit = BatchMain.run(cfgFile);
        assertEquals("batch must exit clean", 0, exit);

        // manifest written and schema-valid
        JsonNode manifest = MAPPER.readTree(runDir.resolve("run-manifest.json").toFile());
        JsonSchema schema;
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.run-manifest.1.schema.json"))) {
            schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
        assertTrue("manifest must validate", schema.validate(manifest).isEmpty());
        assertEquals(4, manifest.get("seats").size());

        // all 4 games recorded, schema-valid, no crashes; both workers contributed
        List<String> records = Files.readAllLines(runDir.resolve("game-records.jsonl"));
        assertEquals(4, records.size());
        JsonSchema recSchema;
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.game-record.1.schema.json"))) {
            recSchema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
        boolean[] seen = new boolean[4];
        for (String line : records) {
            JsonNode r = MAPPER.readTree(line);
            assertTrue("record must validate: " + line, recSchema.validate(r).isEmpty());
            assertEquals("timeout_draw", r.get("result").asText());
            seen[r.get("game_index").asInt()] = true;
        }
        for (int i = 0; i < 4; i++) {
            assertTrue("game " + i + " must be recorded", seen[i]);
        }

        // per-game event logs exist; shared run.log has lines from both workers
        for (int i = 0; i < 4; i++) {
            assertTrue(Files.exists(runDir.resolve("events").resolve(String.format("%06d.jsonl", i))));
        }
        List<String> log = Files.readAllLines(runDir.resolve("run.log"));
        assertTrue(log.stream().anyMatch(l -> l.startsWith("[w0 ")));
        assertTrue(log.stream().anyMatch(l -> l.startsWith("[w1 ")));
    }
}
