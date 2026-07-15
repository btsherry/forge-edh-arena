package forge.arena.harness;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;

/**
 * Batch orchestrator (plan §3 Gate 5 + §4 worker pool): writes the
 * run-manifest FIRST (schema-validated, fail-fast), then spawns worker JVMs
 * ({@link WorkerMain}) over an interleaved index stride, waits, and prints an
 * aggregate summary from game-records.jsonl.
 *
 * <p>Usage: {@code BatchMain <batch-config.json>}. Worker JVMs inherit this
 * JVM's classpath and get {@code -Xmx2g} (plan W6 JVM flags; override via
 * config {@code worker_heap}).
 */
public final class BatchMain {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private BatchMain() {
    }

    public static void main(String[] args) throws Exception {
        int exit = run(Path.of(args[0]));
        if (exit != 0) {
            System.exit(exit);
        }
    }

    public static int run(Path configPath) throws Exception {
        JsonNode cfg = MAPPER.readTree(configPath.toFile());
        Path outDir = Path.of(cfg.get("out_dir").asText()).toAbsolutePath();
        Files.createDirectories(outDir);
        int games = cfg.get("games").asInt();
        int workers = Math.max(1, cfg.path("workers").asInt(4));
        long seedBase = cfg.get("seed_base").asLong();
        String workerHeap = cfg.path("worker_heap").asText("-Xmx2g");
        Path assetsDir = Path.of(cfg.path("assets_dir").asText("../forge-gui")).toAbsolutePath();

        // --- compose + validate + write the manifest FIRST (Gate 5) ---
        List<Map<String, Object>> manifestSeats = new ArrayList<>();
        List<Map<String, Object>> workerSeats = new ArrayList<>();
        for (JsonNode seat : cfg.get("seats")) {
            Path deckFile = Path.of(seat.get("deck").asText()).toAbsolutePath();
            String deckId = deckFile.getFileName().toString().replaceFirst("\\.dck$", "");
            Map<String, Object> ai = new LinkedHashMap<>();
            ai.put("profile", seat.path("profile").asText("Default"));
            ai.put("simulation_ai", seat.path("simulation_ai").asBoolean(false));
            Map<String, Object> ms = new LinkedHashMap<>();
            ms.put("deck", deckId);
            ms.put("deck_hash", DeckHash.of(deckFile));
            ms.put("ai", ai);
            manifestSeats.add(ms);
            Map<String, Object> ws = new LinkedHashMap<>();
            ws.put("deck_file", deckFile.toString());
            ws.put("profile", seat.path("profile").asText("Default"));
            ws.put("simulation_ai", seat.path("simulation_ai").asBoolean(false));
            workerSeats.add(ws);
        }

        Map<String, Object> limits = new LinkedHashMap<>();
        limits.put("turns", cfg.path("limits").path("turns").asInt(30));
        limits.put("wall_clock_sec", cfg.path("limits").path("wall_clock_sec").asInt(600));
        limits.put("priority_passes_per_turn", cfg.path("limits").path("priority_passes_per_turn").asInt(2000));

        Map<String, Object> manifest = new LinkedHashMap<>();
        manifest.put("schema", "arena.run-manifest/1");
        manifest.put("run_id", cfg.path("run_id").asText("run-" + seedBase + "-" + games));
        manifest.put("fork_commit", forkCommit());
        manifest.put("seed_base", seedBase);
        manifest.put("games", games);
        manifest.put("seats", manifestSeats);
        manifest.put("rotation", cfg.path("rotation").asText("latin_square_4"));
        manifest.put("limits", limits);

        Set<ValidationMessage> errors = manifestSchema().validate(
                MAPPER.readTree(MAPPER.writeValueAsString(manifest)));
        if (!errors.isEmpty()) {
            System.err.println("run manifest invalid — refusing to start: " + errors);
            return 2;
        }
        Files.writeString(outDir.resolve("run-manifest.json"),
                MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(manifest));

        Map<String, Object> workerCfg = new LinkedHashMap<>();
        workerCfg.put("assets_dir", assetsDir.toString());
        workerCfg.put("seed_base", seedBase);
        workerCfg.put("games", games);
        workerCfg.put("limits", limits);
        workerCfg.put("seats", workerSeats);
        Files.writeString(outDir.resolve("worker-config.json"),
                MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(workerCfg));

        // --- spawn the pool ---
        long started = System.currentTimeMillis();
        List<Process> pool = new ArrayList<>();
        String javaBin = Path.of(System.getProperty("java.home"), "bin", "java").toString();
        for (int w = 0; w < workers; w++) {
            List<String> cmd = List.of(javaBin, workerHeap, "-cp", System.getProperty("java.class.path"),
                    WorkerMain.class.getName(), outDir.toString(), String.valueOf(w), String.valueOf(workers));
            ProcessBuilder pb = new ProcessBuilder(cmd)
                    .redirectErrorStream(true)
                    .redirectOutput(outDir.resolve("worker-" + w + ".out").toFile());
            pool.add(pb.start());
            System.out.println("spawned worker " + w + " (pid " + pool.get(w).pid() + ")");
        }
        int failures = 0;
        for (int w = 0; w < pool.size(); w++) {
            int code = pool.get(w).waitFor();
            if (code != 0) {
                failures++;
                System.err.println("worker " + w + " exited " + code + " — see worker-" + w + ".out");
            }
        }
        long wallMs = System.currentTimeMillis() - started;

        summarize(outDir, games, workers, wallMs);
        return failures == 0 ? 0 : 1;
    }

    private static void summarize(Path outDir, int games, int workers, long wallMs) throws IOException {
        Map<String, Integer> byResult = new TreeMap<>();
        Map<String, Integer> winsByDeck = new TreeMap<>();
        long totalDur = 0;
        int n = 0;
        Path recordsFile = outDir.resolve("game-records.jsonl");
        if (Files.exists(recordsFile)) {
            for (String line : Files.readAllLines(recordsFile)) {
                if (line.isBlank()) {
                    continue;
                }
                JsonNode r = MAPPER.readTree(line);
                n++;
                byResult.merge(r.get("result").asText(), 1, Integer::sum);
                totalDur += r.path("duration_ms").asLong();
                if (r.has("winner_seat")) {
                    winsByDeck.merge(r.get("seats").get(r.get("winner_seat").asInt()).asText(), 1, Integer::sum);
                }
            }
        }
        System.out.println("=== batch complete ===");
        System.out.printf("records: %d/%d  results: %s%n", n, games, byResult);
        System.out.printf("wins by deck: %s%n", winsByDeck);
        if (n > 0) {
            System.out.printf("avg game: %.1fs  wall: %.1f min  throughput: %.0f games/hr on %d workers%n",
                    totalDur / 1000.0 / n, wallMs / 60000.0, n / (wallMs / 3600000.0), workers);
        }
        System.out.println("artifacts: " + outDir + "/{run-manifest.json,game-records.jsonl,events/,run.log}");
    }

    private static JsonSchema manifestSchema() throws IOException {
        try (InputStream in = Files.newInputStream(Path.of("forge-arena", "schemas", "arena.run-manifest.1.schema.json")
                .toFile().exists()
                        ? Path.of("forge-arena", "schemas", "arena.run-manifest.1.schema.json")
                        : Path.of("schemas", "arena.run-manifest.1.schema.json"))) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }

    private static String forkCommit() {
        try {
            Process p = new ProcessBuilder("git", "rev-parse", "HEAD").start();
            String out = new String(p.getInputStream().readAllBytes()).strip();
            if (p.waitFor() == 0 && out.matches("[0-9a-f]{7,40}")) {
                return out;
            }
        } catch (Exception ignored) {
            // fall through to placeholder
        }
        return "0000000";
    }
}
