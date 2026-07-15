package forge.arena.harness;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;

import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.annotations.Test;

/** Plan §8 DeckHashTest: order-insensitive, count-sensitive, commander-inclusive. */
public class DeckHashTest {

    private Path dck(String... lines) throws Exception {
        Path f = Files.createTempFile("deck", ".dck");
        Files.write(f, java.util.List.of(lines));
        return f;
    }

    @Test
    public void orderInsensitive() throws Exception {
        Path a = dck("[Commander]", "1 Selvala, Heart of the Wilds", "[Main]", "1 Umbral Mantle", "1 Forest");
        Path b = dck("[Commander]", "1 Selvala, Heart of the Wilds", "[Main]", "1 Forest", "1 Umbral Mantle");
        assertEquals(DeckHash.of(a), DeckHash.of(b));
    }

    @Test
    public void countSensitive() throws Exception {
        Path a = dck("[Commander]", "1 Selvala, Heart of the Wilds", "[Main]", "10 Forest");
        Path b = dck("[Commander]", "1 Selvala, Heart of the Wilds", "[Main]", "11 Forest");
        assertFalse(DeckHash.of(a).equals(DeckHash.of(b)));
    }

    @Test
    public void commanderInclusive() throws Exception {
        Path a = dck("[Commander]", "1 Selvala, Heart of the Wilds", "[Main]", "10 Forest");
        Path b = dck("[Commander]", "1 Fanatic of Rhonas", "[Main]", "10 Forest");
        assertFalse(DeckHash.of(a).equals(DeckHash.of(b)));
    }

    @Test
    public void metadataAndSideboardExcluded() throws Exception {
        Path a = dck("[metadata]", "Name=Deck A", "[Commander]", "1 Selvala, Heart of the Wilds",
                "[Main]", "10 Forest", "[Sideboard]", "1 Craterhoof Behemoth");
        Path b = dck("[metadata]", "Name=Totally Different", "[Commander]", "1 Selvala, Heart of the Wilds",
                "[Main]", "10 Forest");
        assertEquals(DeckHash.of(a), DeckHash.of(b));
    }
}
