package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

/**
 * Plan §8 SpellbookClientContractTest: recorded HTTP fixtures only (no
 * network in tests); cache hit produces ZERO calls; schema-version drift
 * fails loudly. Plus the Gate 3 transform + route coverage on the fixture.
 */
public class SpellbookClientContractTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private Path dossierWithFixture() throws Exception {
        Path dir = Files.createTempDirectory("combo-prep");
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
        return dir;
    }

    private String fixture() throws Exception {
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            return new String(in.readAllBytes());
        }
    }

    @Test
    public void transformAndCoverageFromRecordedFixture() throws Exception {
        Path dir = dossierWithFixture();
        AtomicInteger calls = new AtomicInteger();
        String recorded = fixture();
        ComboPrep.Result r = ComboPrep.run(dir, (url, body) -> {
            calls.incrementAndGet();
            assertTrue("request must carry the commander", body.contains("Selvala, Heart of the Wilds"));
            return recorded;
        });
        assertEquals(1, calls.get());
        assertEquals(3, r.included());
        assertEquals(1, r.almostIncluded());
        assertEquals("unroutable_flagged", r.coverageStatus()); // "Infinite gremlin polkas"
        assertEquals(List.of("Infinite gremlin polkas"), r.unroutableFeatures());

        // combos.json validates + carries the Mantle combo details
        JsonNode combos = MAPPER.readTree(dir.resolve("combos.json").toFile());
        assertTrue("combos.json schema errors: " + schema("arena.combos.1.schema.json").validate(combos),
                schema("arena.combos.1.schema.json").validate(combos).isEmpty());
        JsonNode mantle = combos.get("combos").get(0);
        assertEquals("527-2816", mantle.get("id").asText());
        assertEquals("battlefield", mantle.get("cards").get(0).get("zone_req").asText());
        assertEquals("{2}{G} at most", mantle.get("mana_needed").asText());
        assertTrue(mantle.get("steps").asText().contains("untapping"));
        // commander identity from THIS deck's list (post-review): Selvala is card index 1
        assertTrue(mantle.get("cards").get(1).get("commander").asBoolean());

        // urza-style variant (post-review): template requires, card states, multi-zone, PU feature
        JsonNode scepter = combos.get("combos").get(2);
        assertEquals("4821-5261", scepter.get("id").asText());
        assertEquals("exiled by Isochron Scepter", scepter.get("cards").get(0).get("state").asText());
        assertEquals("untapped", scepter.get("cards").get(1).get("state").asText());
        JsonNode nexus = scepter.get("cards").get(2);
        assertEquals("hand", nexus.get("zone_req").asText());
        assertEquals(3, nexus.get("zones").size());
        assertEquals("library", nexus.get("zones").get(2).asText());
        JsonNode template = scepter.get("template_requirements").get(0);
        assertEquals("Permanent that can be cast using {C}", template.get("name").asText());
        assertEquals("hand", template.get("zone_req").asText());
        assertEquals(1234, scepter.get("popularity").asInt());
        assertEquals("R", scepter.get("bracket_tag").asText());

        // PU-status feature classified CARD_CLASS, never UNROUTABLE (doc rule 30)
        JsonNode coverageScepter = MAPPER.readTree(dir.resolve("route-coverage.json").toFile())
                .get("combos").get(2);
        assertEquals("CARD_CLASS", coverageScepter.get("features").get(1).get("category").asText());

        // route coverage validates (v2); Mantle combo is resources-only, pinger is direct win
        JsonNode coverage = MAPPER.readTree(dir.resolve("route-coverage.json").toFile());
        assertTrue("route-coverage schema errors: "
                + schema("arena.route-coverage.2.schema.json").validate(coverage),
                schema("arena.route-coverage.2.schema.json").validate(coverage).isEmpty());
        assertEquals(false, coverage.get("combos").get(0).get("direct_win").asBoolean());
        assertEquals(true, coverage.get("combos").get(1).get("direct_win").asBoolean());
        // deck layer present: the fixture pinger's Infinite damage is a direct win path,
        // so this deck is unroutable_flagged (gremlin polkas) but NOT blocked
        assertEquals("direct", coverage.get("deck").get("routes").get(0).get("origin").asText());
        assertTrue(coverage.get("deck").get("win_paths").asInt() >= 1);

        // advisory stays out of runtime data
        JsonNode advisory = MAPPER.readTree(dir.resolve("advisory-combos.json").toFile());
        assertEquals(1, advisory.get("combos").size());

        // dossier updated
        JsonNode index = MAPPER.readTree(dir.resolve("dossier.json").toFile());
        assertEquals("unroutable_flagged", index.get("status").get("route_coverage").asText());
    }

    @Test
    public void cacheHitMakesZeroHttpCalls() throws Exception {
        Path dir = dossierWithFixture();
        Files.writeString(dir.resolve("spellbook-raw.json"), fixture());
        ComboPrep.Result r = ComboPrep.run(dir, (url, body) -> {
            throw new IOException("network hit on cache!");
        });
        assertEquals(3, r.included());
    }

    @Test
    public void cacheHitPreservesOriginalFetchDate() throws Exception {
        Path dir = dossierWithFixture();
        Files.writeString(dir.resolve("spellbook-raw.json"), fixture());
        Files.writeString(dir.resolve("spellbook-raw.meta.json"),
                "{\"fetched\": \"2026-01-01\", \"deck_hash\": \"d7498c0379debdfa\"}");
        ComboPrep.run(dir, (url, body) -> {
            throw new IOException("network hit on cache!");
        });
        JsonNode combos = MAPPER.readTree(dir.resolve("combos.json").toFile());
        assertEquals("W5: snapshot date must be the FETCH date, not the run date",
                "2026-01-01", combos.get("spellbook_snapshot").asText());
    }

    @Test
    public void deckHashMismatchRefetchesInsteadOfServingStaleCombos() throws Exception {
        Path dir = dossierWithFixture();
        Files.writeString(dir.resolve("spellbook-raw.json"), "{\"results\": {\"included\": []}}");
        Files.writeString(dir.resolve("spellbook-raw.meta.json"),
                "{\"fetched\": \"2026-01-01\", \"deck_hash\": \"aaaaaaaaaaaaaaaa\"}");
        AtomicInteger calls = new AtomicInteger();
        String recorded = fixture();
        ComboPrep.Result r = ComboPrep.run(dir, (url, body) -> {
            calls.incrementAndGet();
            return recorded;
        });
        assertEquals("changed deck must refetch", 1, calls.get());
        assertEquals(3, r.included());
    }

    @Test(expectedExceptions = IOException.class,
            expectedExceptionsMessageRegExp = ".*drift or corrupt cache.*")
    public void cachedSnapshotWithoutResultsFailsLoudlyNotNpe() throws Exception {
        Path dir = dossierWithFixture();
        Files.writeString(dir.resolve("spellbook-raw.json"), "{\"totally\": \"different\"}");
        Files.writeString(dir.resolve("spellbook-raw.meta.json"),
                "{\"fetched\": \"2026-01-01\", \"deck_hash\": \"d7498c0379debdfa\"}");
        SpellbookClient.fetchOrLoad(dir, (url, body) -> {
            throw new IOException("should not fetch");
        });
    }

    @Test
    public void partnerCommandersBothLandInCommandersArray() throws Exception {
        Path dir = Files.createTempDirectory("combo-prep-partners");
        Map<String, Object> deckCards = Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "p",
                "cards", List.of(
                        Map.of("name", "Thrasios, Triton Hero", "qty", 1, "zone", "commander"),
                        Map.of("name", "Tymna the Weaver", "qty", 1, "zone", "commander"),
                        Map.of("name", "Sol Ring", "qty", 1, "zone", "main")),
                "unresolved", List.of());
        MAPPER.writeValue(dir.resolve("deck-cards.json").toFile(), deckCards);
        Files.writeString(dir.resolve("dossier.json"),
                "{\"deck_id\":\"p\",\"deck_hash\":\"bbbbbbbbbbbbbbbb\",\"status\":{},\"versions\":{}}");
        SpellbookClient.fetchOrLoad(dir, (url, body) -> {
            JsonNode b = MAPPER.readTree(body);
            assertEquals(2, b.get("commanders").size());
            assertEquals(1, b.get("main").size());
            return "{\"results\": {\"included\": []}}";
        });
    }

    @Test(expectedExceptions = IOException.class,
            expectedExceptionsMessageRegExp = ".*schema-version drift.*")
    public void responseShapeDriftFailsLoudly() throws Exception {
        Path dir = dossierWithFixture();
        SpellbookClient.fetchOrLoad(dir, (url, body) -> "{\"totally\": \"different\"}");
    }

    private JsonSchema schema(String file) throws Exception {
        try (InputStream in = Files.newInputStream(Path.of("schemas", file))) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }
}
