package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

/**
 * PR-13 prep autopsy on recorded fixtures — zero network, ever. Budget
 * proofs: clean coverage and known features cost no calls; one call plus at
 * most one repair retry otherwise; failed validation never corrupts the
 * library.
 */
public class PrepAutopsyTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Messages-API response wrapper around a text payload. */
    private static String apiResponse(String text) throws Exception {
        return MAPPER.writeValueAsString(java.util.Map.of(
                "content", List.of(java.util.Map.of("type", "text", "text", text)),
                "stop_reason", "end_turn"));
    }

    private static ClaudeClient client(AtomicInteger calls, List<String> cannedTexts) {
        return new ClaudeClient((url, body) -> {
            int n = calls.getAndIncrement();
            try {
                return apiResponse(cannedTexts.get(Math.min(n, cannedTexts.size() - 1)));
            } catch (Exception e) {
                throw new java.io.IOException(e);
            }
        }, "test-model");
    }

    /** Dossier dir with a blocked route-coverage + tiny deck-cards. */
    private Path blockedDossier() throws Exception {
        Path dir = Files.createTempDirectory("autopsy");
        MAPPER.writeValue(dir.resolve("route-coverage.json").toFile(), java.util.Map.of(
                "schema", "arena.route-coverage/2",
                "deck_id", "t", "deck_hash", "aabbccdd11223344",
                "win_routes_version", RouteRules.VERSION,
                "combos", List.of(),
                "deck", java.util.Map.of(
                        "payoffs", java.util.Map.of(),
                        "routes", List.of(java.util.Map.of(
                                "route", "DIRECT_DAMAGE_LOOP", "origin", "conversion",
                                "support", "unsupported", "from_combos", List.of("c1"),
                                "missing", List.of("x_damage"))),
                        "guards", List.of(java.util.Map.of(
                                "id", "no_expressible_win_path", "severity", "blocking",
                                "detail", "combos produce only resources")),
                        "win_paths", 0),
                "unroutable_features", List.of("Infinite gremlin polkas"),
                "status", "blocked"));
        MAPPER.writeValue(dir.resolve("deck-cards.json").toFile(), java.util.Map.of(
                "cards", List.of(
                        java.util.Map.of("name", "Rolling Earthquake", "qty", 1, "zone", "main",
                                "type_line", "Sorcery",
                                "oracle_text", "Rolling Earthquake deals X damage to each creature"
                                        + " without horsemanship and each player."))));
        return dir;
    }

    private Path emptyLibrary() throws Exception {
        return Files.createTempDirectory("autopsy-lib").resolve("classifications.json");
    }

    @Test
    public void cleanCoverageCostsNoCalls() throws Exception {
        Path dir = Files.createTempDirectory("autopsy-clean");
        MAPPER.writeValue(dir.resolve("route-coverage.json").toFile(),
                java.util.Map.of("status", "clean"));
        AtomicInteger calls = new AtomicInteger();
        PrepAutopsy.Result r = PrepAutopsy.run(dir,
                RouteLibrary.load(emptyLibrary()), client(calls, List.of("unused")));
        assertEquals("not_needed", r.status());
        assertEquals(0, calls.get());
    }

    @Test
    public void oneBatchedCallProposesFeaturesAndPayoffsWithProvenance() throws Exception {
        Path dir = blockedDossier();
        Path libFile = emptyLibrary();
        AtomicInteger calls = new AtomicInteger();
        String good = """
                {"features": [{"feature": "Infinite gremlin polkas", "category": "RESOURCE",
                               "routes": [], "rationale": "novelty token dance, no game effect"}],
                 "payoffs": [{"card": "Rolling Earthquake", "payoff_class": "x_damage",
                              "rationale": "X damage hits each player"},
                             {"card": "Not In Deck", "payoff_class": "x_damage",
                              "rationale": "hallucinated"}]}""";
        PrepAutopsy.Result r = PrepAutopsy.run(dir, RouteLibrary.load(libFile),
                client(calls, List.of(good)));

        assertEquals("proposed", r.status());
        assertEquals(1, calls.get());
        assertEquals(1, r.featureProposals());
        assertEquals(1, r.payoffProposals());
        // hallucinated card dropped, recorded, never silent
        assertEquals(1, r.dropped().size());
        assertTrue(r.dropped().get(0).contains("Not In Deck"));

        // artifact validates against its schema
        JsonNode proposals = MAPPER.readTree(dir.resolve("autopsy-proposals.json").toFile());
        try (InputStream in = Files.newInputStream(
                Path.of("schemas", "arena.autopsy-proposals.1.schema.json"))) {
            var errors = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
                    .getSchema(in).validate(proposals);
            assertTrue("schema errors: " + errors, errors.isEmpty());
        }
        assertEquals("test-model", proposals.get("model").asText());
        assertEquals(64, proposals.get("request_sha256").asText().length());
        // verbatim response preserved for reproducibility
        assertTrue(Files.readString(dir.resolve("autopsy-raw.json")).contains("gremlin"));

        // library gained PROPOSED (inert) entries; effective version unmoved
        RouteLibrary lib = RouteLibrary.load(libFile);
        assertTrue(lib.knowsFeature("Infinite gremlin polkas"));
        assertTrue(lib.lookupFeature("Infinite gremlin polkas").isEmpty());
        assertEquals(RouteLibrary.NO_LIBRARY, lib.effectiveVersion());
    }

    @Test
    public void knownFeaturesAndPriorAutopsyMakeItACacheHit() throws Exception {
        Path dir = blockedDossier();
        Path libFile = emptyLibrary();
        AtomicInteger calls = new AtomicInteger();
        String good = """
                {"features": [{"feature": "Infinite gremlin polkas", "category": "RESOURCE",
                               "routes": [], "rationale": "r"}], "payoffs": []}""";
        assertEquals("proposed", PrepAutopsy.run(dir, RouteLibrary.load(libFile),
                client(calls, List.of(good))).status());
        assertEquals(1, calls.get());
        // second run: feature known to library + payoff question already asked
        PrepAutopsy.Result again = PrepAutopsy.run(dir, RouteLibrary.load(libFile),
                client(calls, List.of(good)));
        assertEquals("cached", again.status());
        assertEquals("no repeat calls, ever", 1, calls.get());
    }

    @Test
    public void invalidResponseGetsExactlyOneRepairRetry() throws Exception {
        Path dir = blockedDossier();
        Path libFile = emptyLibrary();
        AtomicInteger calls = new AtomicInteger();
        String bad = "{\"features\": [{\"feature\": \"Infinite gremlin polkas\","
                + " \"category\": \"NOT_A_CATEGORY\", \"routes\": [], \"rationale\": \"\"}],"
                + " \"payoffs\": []}";
        String good = "```json\n{\"features\": [{\"feature\": \"Infinite gremlin polkas\","
                + " \"category\": \"RESOURCE\", \"routes\": [], \"rationale\": \"fenced but valid\"}],"
                + " \"payoffs\": []}\n```";
        PrepAutopsy.Result r = PrepAutopsy.run(dir, RouteLibrary.load(libFile),
                client(calls, List.of(bad, good)));
        assertEquals("proposed", r.status());
        assertEquals(2, calls.get());

        // both attempts preserved verbatim
        JsonNode raw = MAPPER.readTree(dir.resolve("autopsy-raw.json").toFile());
        assertEquals(2, raw.get("responses_verbatim").size());
    }

    @Test
    public void twoInvalidResponsesFailGracefullyWithoutTouchingTheLibrary() throws Exception {
        Path dir = blockedDossier();
        Path libFile = emptyLibrary();
        AtomicInteger calls = new AtomicInteger();
        PrepAutopsy.Result r = PrepAutopsy.run(dir, RouteLibrary.load(libFile),
                client(calls, List.of("not json at all")));
        assertEquals("failed", r.status());
        assertEquals(2, calls.get());
        assertFalse(r.ranOrCached());
        // library untouched, no proposals artifact claiming success
        assertFalse(Files.exists(libFile));
        assertFalse(Files.exists(dir.resolve("autopsy-proposals.json")));
        // raw responses still written for debugging
        assertTrue(Files.exists(dir.resolve("autopsy-raw.json")));
    }

    @Test
    public void promptCarriesTheClosedSetsAndTheDeck() throws Exception {
        Path dir = blockedDossier();
        List<String> bodies = new ArrayList<>();
        ClaudeClient spy = new ClaudeClient((url, body) -> {
            bodies.add(body);
            try {
                return apiResponse("{\"features\": [], \"payoffs\": []}");
            } catch (Exception e) {
                throw new java.io.IOException(e);
            }
        }, "test-model");
        PrepAutopsy.run(dir, RouteLibrary.load(emptyLibrary()), spy);
        String body = bodies.get(0);
        JsonNode request = MAPPER.readTree(body);
        assertEquals("test-model", request.get("model").asText());
        assertEquals(0, request.get("temperature").asInt());
        String user = request.get("messages").get(0).get("content").asText();
        assertTrue(user.contains("SPREAD_COMBAT"));            // closed route set
        assertTrue(user.contains("drain_on_trigger"));         // closed payoff classes
        assertTrue(user.contains("Infinite gremlin polkas"));  // the unknowns
        assertTrue(user.contains("Rolling Earthquake"));       // the deck, oracle text included
        assertTrue(request.get("system").asText().contains("CLOSED"));
    }
}
