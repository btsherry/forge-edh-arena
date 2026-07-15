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

        // artifacts live in a per-batch subdir (no clobbering batch to batch)
        List<Path> batchDirs;
        try (var stream = Files.list(runDir)) {
            batchDirs = stream.filter(Files::isDirectory).toList();
        }
        assertEquals("exactly one batch dir", 1, batchDirs.size());
        assertTrue("batch dir named <run_id>-<stamp>",
                batchDirs.get(0).getFileName().toString().startsWith("batch-int-test-"));
        Path batchDir = batchDirs.get(0);

        // ledger records start (all inputs) + end (outcome)
        List<String> ledger = Files.readAllLines(runDir.resolve("batches.jsonl"));
        assertEquals(2, ledger.size());
        JsonNode start = MAPPER.readTree(ledger.get(0));
        assertEquals("batch_start", start.get("t").asText());
        assertEquals(42, start.get("inputs").get("seed_base").asInt());
        assertEquals(4, start.get("inputs").get("seats").size());
        assertEquals(3, start.get("inputs").get("limits").get("turns").asInt());
        JsonNode end = MAPPER.readTree(ledger.get(1));
        assertEquals("batch_end", end.get("t").asText());
        assertEquals(4, end.get("records").asInt());
        assertEquals(start.get("batch_id").asText(), end.get("batch_id").asText());

        // manifest written and schema-valid, carries the batch id
        JsonNode manifest = MAPPER.readTree(batchDir.resolve("run-manifest.json").toFile());
        assertEquals(start.get("batch_id").asText(), manifest.get("batch_id").asText());
        JsonSchema schema;
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.run-manifest.1.schema.json"))) {
            schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
        assertTrue("manifest must validate", schema.validate(manifest).isEmpty());
        assertEquals(4, manifest.get("seats").size());

        // all 4 games recorded, schema-valid, no crashes; both workers contributed
        List<String> records = Files.readAllLines(batchDir.resolve("game-records.jsonl"));
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
            assertTrue(Files.exists(batchDir.resolve("events").resolve(String.format("%06d.jsonl", i))));
        }
        List<String> log = Files.readAllLines(batchDir.resolve("run.log"));
        assertTrue(log.stream().anyMatch(l -> l.startsWith("[w0 ")));
        assertTrue(log.stream().anyMatch(l -> l.startsWith("[w1 ")));
    }
}
