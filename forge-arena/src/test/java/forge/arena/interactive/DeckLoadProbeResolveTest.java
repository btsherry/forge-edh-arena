package forge.arena.interactive;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;

/**
 * Interactive plan item 7: Forge's name for a Scryfall card comes from Forge's
 * own database — the PRINTING (set + collector number → edition entry) first,
 * name forms second — never from a layout whitelist. Two multi-face shapes
 * that a whitelist got wrong in opposite directions: a Room (Forge keeps the
 * combined name) and a modal DFC (Forge keeps the front face).
 *
 * <p>Also the start invariant's predicate: a deck line in the wrong form
 * resolves to a placeholder the match would drop, and
 * {@link DeckLoadProbe#playabilityProblems} says so by name.
 */
public class DeckLoadProbeResolveTest {

    private static void boot() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test(timeOut = 120_000)
    public void printingJoinResolvesRoomsAndModalDfcsToForgeNames() {
        boot();
        Map<String, Object> room = DeckLoadProbe.resolve("Secret Arcade // Dusty Parlor", "dsc", "10");
        Assert.assertEquals(room.get("forge_name"), "Secret Arcade // Dusty Parlor",
                "a Room keeps the combined name in Forge");
        Assert.assertEquals(room.get("method"), "printing");

        Map<String, Object> mdfc = DeckLoadProbe.resolve(
                "Katilda, Dawnhart Martyr // Katilda's Rising Dawn", "vow", "21");
        Assert.assertEquals(mdfc.get("forge_name"), "Katilda, Dawnhart Martyr",
                "a modal DFC is named by its front face in Forge");
        Assert.assertEquals(mdfc.get("method"), "printing");
    }

    @Test(timeOut = 120_000)
    public void nameFormsAreTheFallbackAndUnknownCardsStayUnresolved() {
        boot();
        Map<String, Object> front = DeckLoadProbe.resolve(
                "Katilda, Dawnhart Martyr // Katilda's Rising Dawn", "zzz", null);
        Assert.assertEquals(front.get("forge_name"), "Katilda, Dawnhart Martyr");
        Assert.assertEquals(front.get("method"), "front", "unknown printing: the front face resolves");

        Map<String, Object> plain = DeckLoadProbe.resolve("Grizzly Bears", null, null);
        Assert.assertEquals(plain.get("forge_name"), "Grizzly Bears");
        Assert.assertEquals(plain.get("method"), "name");

        Map<String, Object> none = DeckLoadProbe.resolve("Totally Made Up Card // Nope", "zzz", "1");
        Assert.assertNull(none.get("forge_name"));
        Assert.assertEquals(none.get("method"), "unresolved", "a named failure, never a guess");
    }

    @Test(timeOut = 120_000)
    public void playabilityProblemsNameTheDroppedCard() throws Exception {
        boot();
        Path good = Path.of("decks", "sythis-harvests-hand.dck");
        Deck clean = DeckSerializer.fromFile(good.toFile());
        Assert.assertTrue(DeckLoadProbe.playabilityProblems(clean).isEmpty(),
                "the shipped deck loads at 100 with no placeholder");

        String text = Files.readString(good);
        Assert.assertTrue(text.contains("1 Katilda, Dawnhart Martyr\n"), "fixture assumption");
        Path bad = Files.createTempFile("bad-mdfc", ".dck");
        Files.writeString(bad, text.replace("1 Katilda, Dawnhart Martyr\n",
                "1 Katilda, Dawnhart Martyr // Katilda's Rising Dawn\n"));
        List<String> problems = DeckLoadProbe.playabilityProblems(DeckSerializer.fromFile(bad.toFile()));
        Assert.assertFalse(problems.isEmpty(), "the wrong DFC form must be a problem");
        Assert.assertTrue(String.join(" ", problems).contains("Katilda"),
                "…and the card is named: " + problems);
    }
}
