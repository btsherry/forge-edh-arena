package forge.arena.ingest;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;

import org.testng.annotations.Test;

public class DeckListParserTest {

    @Test
    public void plainListWithCommanderHeader() {
        var p = DeckListParser.parse(List.of(
                "Commander:", "1 Selvala, Heart of the Wilds", "", "Deck", "1 Umbral Mantle", "30 Forest"));
        assertEquals(List.of(new DeckListParser.Entry("Selvala, Heart of the Wilds", 1)), p.commanders());
        assertEquals(2, p.main().size());
        assertEquals(30, p.main().get(1).qty());
        assertTrue(p.warnings().isEmpty());
    }

    @Test
    public void moxfieldExportStripsSetAndFoilSuffixes() {
        var p = DeckListParser.parse(List.of(
                "1 Umbral Mantle (SHM) 260 *F*", "1 Craterhoof Behemoth (AVR) 172"));
        assertEquals("Umbral Mantle", p.main().get(0).name());
        assertEquals("Craterhoof Behemoth", p.main().get(1).name());
    }

    @Test
    public void archidektCommanderTagAndCategories() {
        var p = DeckListParser.parse(List.of(
                "1x Selvala, Heart of the Wilds (cmm) [Commander{top}]",
                "1x Umbral Mantle (shm) [Combo]",
                "1x Forest (blb) [Land]"));
        assertEquals("Selvala, Heart of the Wilds", p.commanders().get(0).name());
        assertEquals(2, p.main().size());
    }

    @Test
    public void dckSectionsAndSideboardExcluded() {
        var p = DeckListParser.parse(List.of(
                "[metadata]", "Name=Test", "[Commander]", "1 Selvala, Heart of the Wilds",
                "[Main]", "1 Forest", "[Sideboard]", "1 Craterhoof Behemoth"));
        assertEquals(1, p.commanders().size());
        assertEquals(1, p.main().size());
    }

    @Test
    public void cmdrMarkerAndUnparsedWarning() {
        var p = DeckListParser.parse(List.of(
                "1 Selvala, Heart of the Wilds *CMDR*", "1 Forest", "not a card line"));
        assertEquals(1, p.commanders().size());
        assertEquals(1, p.main().size());
        assertEquals(1, p.warnings().size());
    }
}
