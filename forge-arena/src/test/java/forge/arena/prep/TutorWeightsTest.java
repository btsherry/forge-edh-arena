package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

/**
 * Plan §5 tutor-priorities (v3.3): combo pieces top the list, commanders are
 * discounted (command zone is always available), and route payoffs in ~zero
 * combos — the Crossroads/Craterhoof rule — get real weights.
 */
public class TutorWeightsTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private Path dossier() throws Exception {
        Path dir = Files.createTempDirectory("tutor-weights");
        MAPPER.writeValue(dir.resolve("combos.json").toFile(), Map.of(
                "schema", "arena.combos/1", "deck_id", "t", "deck_hash", "aabbccdd11223344",
                "combos", List.of(
                        Map.of("id", "c1", "popularity", 13010, "cards", List.of(
                                Map.of("name", "Selvala, Heart of the Wilds", "commander", true),
                                Map.of("name", "Umbral Mantle"))),
                        Map.of("id", "c2", "popularity", 120, "cards", List.of(
                                Map.of("name", "Umbral Mantle"),
                                Map.of("name", "Wirewood Channeler"),
                                Map.of("name", "Third Piece"),
                                Map.of("name", "Fourth Piece"))))));
        MAPPER.writeValue(dir.resolve("route-coverage.json").toFile(), Map.of(
                "deck", Map.of("routes", List.of(
                        Map.of("route", "SPREAD_COMBAT", "support", "supported",
                                "enablers", List.of("Concordant Crossroads", "Craterhoof Behemoth")),
                        Map.of("route", "COMMANDER_DMG_SEQUENCE", "support", "supported",
                                "enablers", List.of("Concordant Crossroads")),
                        Map.of("route", "ORACLE_WIN", "support", "unsupported")))));
        MAPPER.writeValue(dir.resolve("deck-cards.json").toFile(), Map.of(
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1, "zone", "commander"),
                        Map.of("name", "Umbral Mantle", "qty", 1, "zone", "main"))));
        return dir;
    }

    @Test
    public void weightsCombineComboQualityLeverageAndRoutePayoffs() throws Exception {
        Path dir = dossier();
        TutorWeights.Result result = TutorWeights.run(dir);
        JsonNode out = MAPPER.readTree(dir.resolve("tutor-priorities.json").toFile());
        JsonNode weights = out.get("weights");

        // top combo piece: max-popularity 2-piece combo -> (0.5 + 0.45) * 1
        assertEquals(0.95, weights.get("Umbral Mantle").asDouble(), 1e-9);
        // commander discount: same combo, x0.2
        assertEquals(0.19, weights.get("Selvala, Heart of the Wilds").asDouble(), 1e-9);
        assertTrue(out.get("explanations").get("Selvala, Heart of the Wilds").asText()
                .contains("commander"));
        // the v3.3 rule: payoffs in ZERO combos still carry weight, by route share
        assertEquals(0.70, weights.get("Concordant Crossroads").asDouble(), 1e-9); // 2/2 routes
        assertEquals(0.525, weights.get("Craterhoof Behemoth").asDouble(), 1e-9);  // 1/2 routes
        assertEquals("route payoff: SPREAD_COMBAT, COMMANDER_DMG_SEQUENCE",
                out.get("explanations").get("Concordant Crossroads").asText());
        // low-popularity 4-piece combo: piece leverage halves the base
        double wirewood = weights.get("Wirewood Channeler").asDouble();
        assertTrue("0 < wirewood < craterhoof, got " + wirewood,
                wirewood > 0 && wirewood < 0.525);

        // deterministic descending order
        List<String> names = new ArrayList<>();
        weights.fieldNames().forEachRemaining(names::add);
        assertEquals("Umbral Mantle", names.get(0));
        assertEquals("Concordant Crossroads", names.get(1));
        double previous = 1.0;
        for (String name : names) {
            double w = weights.get(name).asDouble();
            assertTrue("descending order broken at " + name, w <= previous);
            assertTrue("weight out of [0,1]: " + name, w >= 0 && w <= 1);
            previous = w;
        }
        assertEquals(names.size(), result.weightedCards());

        // artifact validates against its schema
        try (InputStream in = Files.newInputStream(
                Path.of("schemas", "arena.tutor-priorities.1.schema.json"))) {
            var errors = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
                    .getSchema(in).validate(out);
            assertTrue("schema errors: " + errors, errors.isEmpty());
        }
    }

    @Test
    public void secondRunIsByteIdentical() throws Exception {
        Path dir = dossier();
        TutorWeights.run(dir);
        byte[] first = Files.readAllBytes(dir.resolve("tutor-priorities.json"));
        TutorWeights.run(dir);
        assertEquals(new String(first),
                new String(Files.readAllBytes(dir.resolve("tutor-priorities.json"))));
    }
}
