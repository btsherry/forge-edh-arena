package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.ingest.Ingest;

/**
 * `arena prep` v1 end-to-end (plan §3 v3.3): a real deck list compiles
 * through Gates 0-3 into a batch-ready dossier — real card DB, real goldfish
 * game, recorded Spellbook fixture (no network) — and DossierCheck accepts
 * the fresh dossier while refusing tampered or stale ones.
 */
public class PrepMainIntegrationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void prepCompilesABatchReadyDossierAndDossierCheckGuardsIt() throws Exception {
        Path out = Files.createTempDirectory("prep-e2e");
        String recorded;
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            recorded = new String(in.readAllBytes());
        }

        PrepMain.PrepResult result = PrepMain.prep(new PrepMain.Options(
                new Ingest.Spec(Path.of("decks", "selvala-heart-of-the-wilds.dck"),
                        "selvala-e2e", out, "homebrew", 3, null, null, null),
                Path.of("banlists", "commander-banlist.txt"),
                1, (url, body) -> recorded));

        assertTrue("gates: " + result.gates(), result.ok());
        Path dossier = result.dossierDir();

        // --- dossier index: gates recorded, versions pinned, artifacts content-addressed ---
        JsonNode index = MAPPER.readTree(dossier.resolve("dossier.json").toFile());
        assertTrue("dossier schema errors: " + schema("arena.dossier.1.schema.json").validate(index),
                schema("arena.dossier.1.schema.json").validate(index).isEmpty());
        assertEquals("pass", index.get("status").get("lint").asText());
        assertEquals("pass", index.get("status").get("implementability").asText());
        // the fixture's "Infinite gremlin polkas" keeps this flagged — and honest
        assertEquals("unroutable_flagged", index.get("status").get("route_coverage").asText());
        assertEquals(RouteRules.VERSION, index.get("versions").get("win_routes").asText());
        for (String artifact : new String[] { "deck", "deck_meta", "deck_cards", "lint_report",
                "implementability_report", "spellbook_raw", "combos", "advisory_combos",
                "route_coverage", "tutor_priorities" }) {
            assertTrue("artifact missing from index: " + artifact, index.get("artifacts").has(artifact));
        }

        // --- goldfish actually ran ---
        JsonNode implementability = MAPPER.readTree(
                dossier.resolve("implementability-report.json").toFile());
        assertEquals(1, implementability.get("goldfish_games").size());

        // --- route coverage v2: payoffs found in the REAL card DB text ---
        JsonNode coverage = MAPPER.readTree(dossier.resolve("route-coverage.json").toFile());
        assertTrue("route-coverage schema errors: "
                + schema("arena.route-coverage.2.schema.json").validate(coverage),
                schema("arena.route-coverage.2.schema.json").validate(coverage).isEmpty());
        JsonNode payoffs = coverage.get("deck").get("payoffs");
        assertTrue(contains(payoffs.get("haste_static"), "Concordant Crossroads"));
        assertTrue(contains(payoffs.get("mass_pump"), "Craterhoof Behemoth"));
        assertTrue(contains(payoffs.get("commander_creature"), "Selvala, Heart of the Wilds"));
        assertEquals("supported", route(coverage, "SPREAD_COMBAT").get("support").asText());
        assertEquals("intrinsic", route(coverage, "DIRECT_DAMAGE_LOOP").get("support").asText());
        assertTrue(coverage.get("deck").get("win_paths").asInt() >= 3);
        // mono-green, no oracle effect: ORACLE_WIN stays unexpressed and the guard says so
        assertEquals("unsupported", route(coverage, "ORACLE_WIN").get("support").asText());
        boolean oracleGuard = false;
        for (JsonNode guard : coverage.get("deck").get("guards")) {
            oracleGuard |= guard.get("id").asText().equals("oracle_guard");
        }
        assertTrue("oracle_guard must be recorded (WIN-ROUTES §3)", oracleGuard);

        // --- tutor weights: the Crossroads/Craterhoof v3.3 rule, live ---
        JsonNode priorities = MAPPER.readTree(dossier.resolve("tutor-priorities.json").toFile());
        assertTrue("tutor-priorities schema errors: "
                + schema("arena.tutor-priorities.1.schema.json").validate(priorities),
                schema("arena.tutor-priorities.1.schema.json").validate(priorities).isEmpty());
        JsonNode weights = priorities.get("weights");
        assertTrue(weights.get("Concordant Crossroads").asDouble() > 0);
        assertTrue(weights.get("Craterhoof Behemoth").asDouble() > 0);
        assertTrue(weights.get("Umbral Mantle").asDouble() >= 0.5);
        assertTrue("commander must be discounted below its combo partner",
                weights.get("Selvala, Heart of the Wilds").asDouble()
                        < weights.get("Umbral Mantle").asDouble());

        // --- DossierCheck: fresh passes (with the unroutable warning) ---
        DossierCheck.Result fresh = DossierCheck.run(dossier);
        assertTrue("problems: " + fresh.problems(), fresh.ok());
        assertFalse(fresh.warnings().isEmpty());

        // stale win-routes version -> refused
        byte[] original = Files.readAllBytes(dossier.resolve("dossier.json"));
        ObjectNode stale = (ObjectNode) MAPPER.readTree(dossier.resolve("dossier.json").toFile());
        ((ObjectNode) stale.get("versions")).put("win_routes", "win-routes/1");
        MAPPER.writeValue(dossier.resolve("dossier.json").toFile(), stale);
        DossierCheck.Result staleCheck = DossierCheck.run(dossier);
        assertFalse(staleCheck.ok());
        assertTrue(staleCheck.problems().toString(),
                staleCheck.problems().stream().anyMatch(p -> p.contains("stale win-routes")));
        Files.write(dossier.resolve("dossier.json"), original);

        // an approval AFTER this prep must stale the dossier (library version pin)
        Path libFile = out.resolve("lib").resolve("classifications.json");
        Files.createDirectories(libFile.getParent());
        Files.writeString(libFile, ("{\"schema\": \"arena.route-library/1\","
                + " \"features\": [{\"feature\": \"Newly Approved Feature\", \"category\": \"GUARD\","
                + " \"routes\": [], \"status\": \"approved\", \"win_routes_version\": \"%s\"}],"
                + " \"payoffs\": []}").formatted(RouteRules.VERSION));
        DossierCheck.Result staleLib = DossierCheck.run(dossier, libFile);
        assertFalse(staleLib.ok());
        assertTrue(staleLib.problems().toString(),
                staleLib.problems().stream().anyMatch(p -> p.contains("stale route-library")));

        // tampered artifact -> refused
        Files.writeString(dossier.resolve("deck-cards.json"), "{\"cards\":[]}");
        DossierCheck.Result tampered = DossierCheck.run(dossier);
        assertFalse(tampered.ok());
        assertTrue(tampered.problems().toString(),
                tampered.problems().stream().anyMatch(p -> p.contains("sha256 mismatch")));

        // missing dossier -> refused, not crashed
        assertFalse(DossierCheck.run(out.resolve("no-such-deck")).ok());
    }

    private static JsonNode route(JsonNode coverage, String name) {
        for (JsonNode row : coverage.get("deck").get("routes")) {
            if (row.get("route").asText().equals(name)) {
                return row;
            }
        }
        throw new AssertionError("route " + name + " not present");
    }

    private static boolean contains(JsonNode array, String value) {
        if (array == null) {
            return false;
        }
        for (JsonNode n : array) {
            if (n.asText().equals(value)) {
                return true;
            }
        }
        return false;
    }

    private JsonSchema schema(String file) throws Exception {
        try (InputStream in = Files.newInputStream(Path.of("schemas", file))) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }
}
