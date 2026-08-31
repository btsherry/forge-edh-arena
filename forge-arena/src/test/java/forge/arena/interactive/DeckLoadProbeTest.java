package forge.arena.interactive;

import java.io.File;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.deck.DeckSection;

/**
 * Every SHIPPED .dck must load through the real loader (2026-09-01): the
 * y-shtola raw-export and the Sheoldred transform-name bugs each reached a
 * live launch because nothing loaded the decks before the GUI did. This is
 * the net: commanders resolve, and exactly 100 cards survive resolution
 * (the loader silently DROPS unresolvable names).
 */
public class DeckLoadProbeTest {

    @Test(timeOut = 240_000)
    public void everyShippedDeckLoads() {
        forge.arena.bootstrap.ArenaBootstrap.initialize(new File("..", "forge-gui"));
        File decksDir = new File("decks");
        File[] dcks = decksDir.listFiles((d, n) -> n.endsWith(".dck"));
        Assert.assertNotNull(dcks, "decks dir missing");
        Assert.assertTrue(dcks.length >= 10, "expected the bundled decks, found " + dcks.length);
        StringBuilder bad = new StringBuilder();
        for (File f : dcks) {
            Deck deck = DeckSerializer.fromFile(f);
            int commanders = deck != null ? deck.getCommanders().size() : 0;
            int main = deck != null && deck.get(DeckSection.Main) != null
                    ? deck.get(DeckSection.Main).countAll() : 0;
            if (deck == null || commanders < 1 || commanders + main != 100) {
                bad.append("\n  ").append(f.getName())
                        .append(": commanders=").append(commanders)
                        .append(" total=").append(commanders + main);
            }
        }
        Assert.assertEquals(bad.length(), 0,
                "unloadable or lossy shipped decks:" + bad);
    }
}
