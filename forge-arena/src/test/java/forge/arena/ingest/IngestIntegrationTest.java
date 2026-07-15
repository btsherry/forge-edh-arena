package forge.arena.ingest;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

import forge.arena.bootstrap.ArenaBootstrap;

/** Gate 0 end-to-end: real deck in, schema-valid dossier skeleton out. */
public class IngestIntegrationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    private JsonSchema schema(String file) throws Exception {
        try (InputStream in = Files.newInputStream(Path.of("schemas", file))) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }

    @Test
    public void selvalaDckProducesSchemaValidDossier() throws Exception {
        Path out = Files.createTempDirectory("arena-ingest");
        Ingest.Result result = Ingest.run(new Ingest.Spec(
                Path.of("decks", "selvala-heart-of-the-wilds.dck"), "selvala-b3", out,
                "homebrew", 3, "Selvala Heart of the Wilds — Bracket 3", "smoke", null));

        Path dossier = out.resolve("selvala-b3").resolve("dossier");
        assertEquals(dossier, result.dossierDir());
        assertTrue("baseline deck must fully resolve, got unresolved: " + result.unresolved(),
                result.unresolved().isEmpty());

        // dossier index validates
        JsonNode index = MAPPER.readTree(dossier.resolve("dossier.json").toFile());
        assertTrue(schema("arena.dossier.1.schema.json").validate(index).isEmpty());
        assertEquals("not_run", index.get("status").get("lint").asText());

        // deck-cards validates, totals 100 cards (rows stack basics), real oracle text
        JsonNode cards = MAPPER.readTree(dossier.resolve("deck-cards.json").toFile());
        assertTrue(schema("arena.deck-cards.1.schema.json").validate(cards).isEmpty());
        int totalQty = 0;
        for (JsonNode c : cards.get("cards")) {
            totalQty += c.get("qty").asInt();
        }
        assertEquals(100, totalQty);
        JsonNode selvala = null;
        for (JsonNode c : cards.get("cards")) {
            if (c.get("name").asText().equals("Selvala, Heart of the Wilds")) {
                selvala = c;
            }
        }
        assertEquals("commander", selvala.get("zone").asText());
        assertTrue("oracle text must be present",
                selvala.get("oracle_text").asText().toLowerCase().contains("draw"));

        // normalized .dck round-trips through the parser with same counts
        var reparsed = DeckListParser.parse(Files.readAllLines(dossier.resolve("selvala-b3.dck")));
        assertEquals(1, reparsed.commanders().size());
        assertEquals(99, reparsed.main().stream().mapToInt(DeckListParser.Entry::qty).sum());
    }

    @Test
    public void plainListWithCommanderFlagIngests() throws Exception {
        Path out = Files.createTempDirectory("arena-ingest2");
        Path list = out.resolve("list.txt");
        Files.write(list, java.util.List.of("1 Selvala, Heart of the Wilds", "1 Umbral Mantle", "30 Forest"));
        Ingest.Result r = Ingest.run(new Ingest.Spec(
                list, "mini", out, "homebrew", null, null, null,
                java.util.List.of("Selvala, Heart of the Wilds")));
        JsonNode cards = MAPPER.readTree(r.dossierDir().resolve("deck-cards.json").toFile());
        assertEquals("commander", cards.get("cards").get(0).get("zone").asText());
        assertTrue(schema("arena.deck-cards.1.schema.json").validate(cards).isEmpty());
    }
}
