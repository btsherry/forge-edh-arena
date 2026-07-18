package forge.arena.ingest;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;

import org.testng.annotations.Test;

/**
 * Phase 6 / PR-45 — Moxfield ingestion, offline. The conversion is the part
 * that can silently rot (a schema change turning every deck into an empty
 * list), so it is tested against recorded shapes with no network.
 */
public class MoxfieldClientTest {

    private static final String V3 = """
            {"boards": {
               "commanders": {"cards": {
                 "aaa": {"quantity": 1, "card": {"name": "Giada, Font of Hope"}}}},
               "mainboard": {"cards": {
                 "bbb": {"quantity": 1, "card": {"name": "Walking Ballista"}},
                 "ccc": {"quantity": 8, "card": {"name": "Plains"}}}}}}""";

    private static final String LEGACY = """
            {"commanders": {"Urza, Lord High Artificer":
                 {"quantity": 1, "card": {"name": "Urza, Lord High Artificer"}}},
             "mainboard": {"Sol Ring":
                 {"quantity": 1, "card": {"name": "Sol Ring"}}}}""";

    @Test
    public void publicIdFromEveryUrlShapeAndBareId() {
        assertEquals("AbCd12", MoxfieldClient.publicId("https://moxfield.com/decks/AbCd12"));
        assertEquals("AbCd12", MoxfieldClient.publicId("https://www.moxfield.com/decks/AbCd12/"));
        assertEquals("AbCd12", MoxfieldClient.publicId("AbCd12"));
    }

    @Test
    public void v3ShapeBecomesParseableDeckListText() throws Exception {
        List<String> lines = MoxfieldClient.fetchDeckList("https://moxfield.com/decks/x",
                url -> V3);
        assertTrue("commander header present", lines.contains("Commander:"));
        assertTrue(lines.contains("1 Giada, Font of Hope"));
        assertTrue(lines.contains("8 Plains"));
        // the whole point: the output feeds the ORDINARY parser unchanged
        DeckListParser.Parsed parsed = DeckListParser.parse(lines);
        assertEquals(List.of("Giada, Font of Hope"),
                parsed.commanders().stream().map(DeckListParser.Entry::name).toList());
        assertEquals(9, parsed.main().stream().mapToInt(DeckListParser.Entry::qty).sum());
    }

    @Test
    public void legacyShapeStillReads() throws Exception {
        List<String> lines = MoxfieldClient.fetchDeckList("y", url -> LEGACY);
        assertTrue(lines.contains("1 Urza, Lord High Artificer"));
        assertTrue(lines.contains("1 Sol Ring"));
    }

    @Test
    public void anUnreadableDeckFailsLoudlyRatherThanSilentlyEmpty() {
        try {
            MoxfieldClient.fetchDeckList("z", url -> "{\"boards\":{}}");
            throw new AssertionError("must not accept an empty deck");
        } catch (Exception expected) {
            assertTrue(expected.getMessage(), expected.getMessage().contains("no readable"));
        }
    }
}
