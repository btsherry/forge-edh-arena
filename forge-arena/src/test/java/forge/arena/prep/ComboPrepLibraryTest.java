package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * PR-13: APPROVED route-library entries change Gate 3 coverage — the
 * unroutable tail becomes classified (marked source=library for
 * transparency) and payoff overrides unlock conversion routes — while the
 * dossier pins the library's effective version for DossierCheck.
 */
public class ComboPrepLibraryTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private Path dossierWithFixture() throws Exception {
        Path dir = Files.createTempDirectory("combo-prep-lib");
        Map<String, Object> deckCards = Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "t",
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1, "zone", "commander"),
                        Map.of("name", "Umbral Mantle", "qty", 1, "zone", "main")),
                "unresolved", List.of());
        MAPPER.writeValue(dir.resolve("deck-cards.json").toFile(), deckCards);
        Map<String, Object> index = new LinkedHashMap<>();
        index.put("schema", "arena.dossier/1");
        index.put("deck_id", "t");
        index.put("deck_hash", "d7498c0379debdfa");
        index.put("status", new LinkedHashMap<>(Map.of("route_coverage", "not_run")));
        index.put("versions", new LinkedHashMap<>(Map.of("schemas", "1")));
        MAPPER.writeValue(dir.resolve("dossier.json").toFile(), index);
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            Files.write(dir.resolve("spellbook-raw.json"), in.readAllBytes());
        }
        return dir;
    }

    private RouteLibrary library(String json) throws Exception {
        Path file = Files.createTempDirectory("lib").resolve("classifications.json");
        Files.writeString(file, json.replace("%V%", RouteRules.VERSION));
        return RouteLibrary.load(file);
    }

    @Test
    public void approvedFeatureEntryClassifiesTheUnroutableTail() throws Exception {
        Path dir = dossierWithFixture();
        RouteLibrary lib = library("""
                {"schema": "arena.route-library/1",
                 "features": [{"feature": "Infinite gremlin polkas", "category": "RESOURCE",
                    "routes": [], "status": "approved", "win_routes_version": "%V%"}],
                 "payoffs": []}""");
        ComboPrep.Result r = ComboPrep.run(dir, (url, body) -> {
            throw new java.io.IOException("cache expected");
        }, lib);

        // the fixture's only unroutable feature is now classified -> clean
        assertEquals("clean", r.coverageStatus());
        assertTrue(r.unroutableFeatures().isEmpty());

        // transparency: the overlaid feature row says where it came from
        JsonNode coverage = MAPPER.readTree(dir.resolve("route-coverage.json").toFile());
        JsonNode polkas = coverage.get("combos").get(1).get("features").get(1);
        assertEquals("Infinite gremlin polkas", polkas.get("name").asText());
        assertEquals("RESOURCE", polkas.get("category").asText());
        assertEquals("library", polkas.get("source").asText());

        // dossier pins the library's effective version
        JsonNode index = MAPPER.readTree(dir.resolve("dossier.json").toFile());
        assertEquals(lib.effectiveVersion(),
                index.get("versions").get("route_library").asText());
        assertTrue(!RouteLibrary.NO_LIBRARY.equals(lib.effectiveVersion()));
    }

    @Test
    public void approvedPayoffOverrideUnlocksAConversionRoute() throws Exception {
        Path dir = dossierWithFixture();
        // pretend Umbral Mantle grants mass haste — mechanics test, not card lore
        RouteLibrary lib = library("""
                {"schema": "arena.route-library/1",
                 "features": [],
                 "payoffs": [{"card": "umbral mantle", "payoff_class": "haste_static",
                    "status": "approved", "win_routes_version": "%V%"}]}""");
        ComboPrep.run(dir, (url, body) -> {
            throw new java.io.IOException("cache expected");
        }, lib);

        JsonNode coverage = MAPPER.readTree(dir.resolve("route-coverage.json").toFile());
        JsonNode payoffs = coverage.get("deck").get("payoffs");
        // canonical deck spelling wins over the library's casing
        assertEquals("Umbral Mantle", payoffs.get("haste_static").get(0).asText());
        boolean spreadSupported = false;
        for (JsonNode route : coverage.get("deck").get("routes")) {
            if (route.get("route").asText().equals("SPREAD_COMBAT")) {
                spreadSupported = route.get("support").asText().equals("supported");
                assertTrue(contains(route.get("enablers"), "Umbral Mantle"));
            }
        }
        assertTrue("pump feature + approved haste override => SPREAD_COMBAT supported",
                spreadSupported);
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
}
