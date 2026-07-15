package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

/** Plan §8 DeckLintTest — synthetic dossiers, no card DB needed. */
public class DeckLintTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private Path banlist;

    private Path dossier(List<Map<String, Object>> cards) throws Exception {
        Path dir = Files.createTempDirectory("lint");
        Map<String, Object> deckCards = Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "t", "cards", cards, "unresolved", List.of());
        MAPPER.writeValue(dir.resolve("deck-cards.json").toFile(), deckCards);
        Map<String, Object> index = new LinkedHashMap<>();
        index.put("schema", "arena.dossier/1");
        index.put("status", new LinkedHashMap<>(Map.of("lint", "not_run")));
        index.put("versions", new LinkedHashMap<>(Map.of("schemas", "1")));
        MAPPER.writeValue(dir.resolve("dossier.json").toFile(), index);
        if (banlist == null) {
            banlist = Files.createTempFile("banlist", ".txt");
            Files.write(banlist, List.of("# version: test-1", "Black Lotus"));
        }
        return dir;
    }

    private static Map<String, Object> card(String name, int qty, String zone, String identity, String type,
            String oracle) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", name);
        m.put("qty", qty);
        m.put("zone", zone);
        if (identity != null) {
            m.put("color_identity", identity);
        }
        m.put("type_line", type);
        m.put("oracle_text", oracle);
        return m;
    }

    private static List<Map<String, Object>> legalDeck() {
        List<Map<String, Object>> cards = new ArrayList<>();
        cards.add(card("Selvala, Heart of the Wilds", 1, "commander", "G", "Legendary Creature Elf", ""));
        cards.add(card("Umbral Mantle", 1, "main", "", "Artifact Equipment", ""));
        cards.add(card("Forest", 98, "main", "G", "Basic Land Forest", ""));
        return cards;
    }

    @Test
    public void legalDeckPassesAndUpdatesDossier() throws Exception {
        Path d = dossier(legalDeck());
        DeckLint.Report r = DeckLint.run(d, banlist);
        assertTrue("expected pass, errors: " + r.errors(), r.pass());
        assertEquals("test-1", r.banlistVersion());
        var index = MAPPER.readTree(d.resolve("dossier.json").toFile());
        assertEquals("pass", index.get("status").get("lint").asText());
        assertEquals("test-1", index.get("versions").get("banlist").asText());
        assertTrue(Files.exists(d.resolve("lint-report.json")));
    }

    @Test
    public void countSingletonIdentityAndBanViolationsAllCaught() throws Exception {
        List<Map<String, Object>> cards = new ArrayList<>();
        cards.add(card("Selvala, Heart of the Wilds", 1, "commander", "G", "Legendary Creature Elf", ""));
        cards.add(card("Black Lotus", 1, "main", "", "Artifact", ""));          // banned
        cards.add(card("Umbral Mantle", 2, "main", "", "Artifact Equipment", "")); // singleton violation
        cards.add(card("Mountain Goat", 1, "main", "R", "Creature Goat", ""));  // identity violation
        cards.add(card("Forest", 90, "main", "G", "Basic Land Forest", ""));    // total 95 != 100
        DeckLint.Report r = DeckLint.run(dossier(cards), banlist);
        assertFalse(r.pass());
        String all = String.join("\n", r.errors());
        assertTrue(all.contains("banned: Black Lotus"));
        assertTrue(all.contains("singleton violation: 2x Umbral Mantle"));
        assertTrue(all.contains("color identity: Mountain Goat"));
        assertTrue(all.contains("100 cards"));
    }

    @Test
    public void anyNumberCardsAndBasicsExemptFromSingleton() throws Exception {
        List<Map<String, Object>> cards = new ArrayList<>();
        cards.add(card("Selvala, Heart of the Wilds", 1, "commander", "G", "Legendary Creature Elf", ""));
        cards.add(card("Slime Against Humanity", 24, "main", "G", "Sorcery",
                "A deck can have any number of cards named Slime Against Humanity."));
        cards.add(card("Forest", 75, "main", "G", "Basic Land Forest", ""));
        DeckLint.Report r = DeckLint.run(dossier(cards), banlist);
        assertTrue("errors: " + r.errors(), r.pass());
    }

    @Test
    public void unresolvedCardIsWarningNotError() throws Exception {
        List<Map<String, Object>> cards = new ArrayList<>();
        cards.add(card("Selvala, Heart of the Wilds", 1, "commander", "G", "Legendary Creature Elf", ""));
        cards.add(card("Brand New Card", 1, "main", null, "", ""));
        cards.add(card("Forest", 98, "main", "G", "Basic Land Forest", ""));
        DeckLint.Report r = DeckLint.run(dossier(cards), banlist);
        assertTrue(r.pass());
        assertEquals(1, r.warnings().size());
    }
}
