package forge.arena.prep;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineCrashException;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.SeatSpec;

/**
 * Gate 2 — implementability preflight (plan §3). Two stages: every card must
 * resolve in Forge's card DB (emits unimplemented-cards.txt; any miss blocks),
 * then the goldfish compile — solo games against the non-interactive goldfish
 * seat under a turn cap, asserting no engine crash. Catches broken/missing
 * card scripts before they poison a batch. Requires ArenaBootstrap.
 */
public final class GoldfishCompile {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final long[] SEEDS = { 101, 102, 103 };

    public record Report(boolean pass, List<String> unimplemented, List<Map<String, Object>> games,
            String failure) {
    }

    private GoldfishCompile() {
    }

    public static Report run(Path dossierDir) throws IOException {
        return run(dossierDir, 3, 12);
    }

    public static Report run(Path dossierDir, int games, int turnCap) throws IOException {
        JsonNode index = MAPPER.readTree(dossierDir.resolve("dossier.json").toFile());
        JsonNode deckCards = MAPPER.readTree(dossierDir.resolve("deck-cards.json").toFile());

        // stage 1: card-DB resolution (script existence)
        List<String> unimplemented = new ArrayList<>();
        deckCards.get("unresolved").forEach(u -> unimplemented.add(u.asText()));
        Files.write(dossierDir.resolve("unimplemented-cards.txt"), unimplemented);

        List<Map<String, Object>> gameRows = new ArrayList<>();
        String failure = null;
        boolean pass = unimplemented.isEmpty();

        // stage 2: goldfish compile (script runtime) — only when stage 1 is clean
        if (pass) {
            File deckFile = dossierDir.resolve(index.get("artifacts").get("deck").get("path").asText()).toFile();
            List<SeatSpec> seats = List.of(SeatSpec.of(deckFile), SeatSpec.goldfish(deckFile));
            ArenaLimits limits = new ArenaLimits(turnCap, 300, 2000);
            for (int i = 0; i < games; i++) {
                long seed = SEEDS[i % SEEDS.length] + (i / SEEDS.length);
                try {
                    ArenaGameResult r = EngineFacade.playCommanderGame(seats, seed, limits);
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("seed", seed);
                    row.put("result", r.type().name().toLowerCase());
                    row.put("turns", r.turns());
                    row.put("duration_ms", r.durationMs());
                    gameRows.add(row);
                } catch (EngineCrashException e) {
                    pass = false;
                    failure = "goldfish game seed=" + seed + " crashed: " + rootMessage(e);
                    break;
                }
            }
        }

        Map<String, Object> report = new LinkedHashMap<>();
        report.put("schema", "arena.implementability-report/1");
        report.put("pass", pass);
        report.put("unimplemented", unimplemented);
        report.put("goldfish_games", gameRows);
        if (failure != null) {
            report.put("failure", failure);
        }
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("implementability-report.json").toFile(), report);

        ((ObjectNode) index.get("status")).put("implementability", pass ? "pass" : "fail");
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("dossier.json").toFile(), index);

        return new Report(pass, unimplemented, gameRows, failure);
    }

    private static String rootMessage(Throwable t) {
        Throwable root = t;
        while (root.getCause() != null) {
            root = root.getCause();
        }
        return root.toString();
    }

    /** CLI: {@code GoldfishCompile <dossier-dir>} (bootstrap via -Darena.assets.dir). */
    public static void main(String[] args) throws Exception {
        forge.arena.bootstrap.ArenaBootstrap.initialize();
        Report r = run(Path.of(args[0]));
        System.out.println("implementability " + (r.pass() ? "PASS" : "FAIL"));
        r.unimplemented().forEach(u -> System.out.println("unimplemented: " + u));
        if (r.failure() != null) {
            System.out.println(r.failure());
        }
        if (!r.pass()) {
            System.exit(1);
        }
    }
}
