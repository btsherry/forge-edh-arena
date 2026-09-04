package forge.arena.interactive;

import java.util.List;
import java.util.Map;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.zone.ZoneType;

/**
 * Interactive plan item 6: the mana tables in the seat's state. Detection is
 * mechanical (mana abilities, Mana-api spell chains, TapsForMana triggers,
 * ProduceMana replacements), never by card name; the cards below are just
 * one instance of each shape.
 *
 * <ul>
 *   <li>a scaling land (Gaea's Cradle: yield = creatures now),</li>
 *   <li>a restricted source (Mishra's Workshop: artifact-only),</li>
 *   <li>a summoning-sick creature source (Llanowar Elves),</li>
 *   <li>a colorless rock (Sol Ring) and two identical basics (collapsed),</li>
 *   <li>a tapped land (excluded),</li>
 *   <li>rituals in hand: a flat one (Dark Ritual) and a board-scaled one
 *       (Mana Geyser: tapped opponent lands),</li>
 *   <li>a multiplier in hand (High Tide) with no number.</li>
 * </ul>
 */
public class ManaTableTest {

    @SuppressWarnings("unchecked")
    @Test(timeOut = 120_000)
    public void sourcesRitualsAndTheSumMatchTheBoard() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Gaea's Cradle", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Mishra's Workshop", k.seat, ZoneType.Battlefield);
            Card elves = MailboxTestKit.put("Llanowar Elves", k.seat, ZoneType.Battlefield);
            elves.setSickness(true);
            MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            Card tapped = MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            tapped.setTapped(true);
            MailboxTestKit.put("Dark Ritual", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Mana Geyser", k.seat, ZoneType.Hand);
            MailboxTestKit.put("High Tide", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Hand); // not a mana card
            for (int i = 0; i < 3; i++) {
                Card m = MailboxTestKit.put("Mountain", k.opp, ZoneType.Battlefield);
                m.setTapped(true);
            }

            Map<String, Object> state = MailboxController.buildState(k.seat, k.seat.getId(), 3);
            List<Map<String, Object>> sources = (List<Map<String, Object>>) state.get("manaSources");
            Assert.assertNotNull(sources, "manaSources missing");

            Map<String, Object> cradle = row(sources, "Gaea's Cradle");
            Assert.assertEquals(cradle.get("yield"), 3, "Cradle counts creatures now (2 Bears + Elves)");
            Assert.assertEquals(cradle.get("colors"), "G");
            Assert.assertFalse(cradle.containsKey("restricted"));

            Map<String, Object> shop = row(sources, "Mishra's Workshop");
            Assert.assertEquals(shop.get("yield"), 3);
            Assert.assertEquals(shop.get("colors"), "colorless");
            Assert.assertTrue(String.valueOf(shop.get("restricted")).contains("Artifact"),
                    "Workshop mana is restricted to artifact spells");

            Map<String, Object> elf = row(sources, "Llanowar Elves");
            Assert.assertEquals(elf.get("sick"), Boolean.TRUE, "a summoning-sick dork cannot tap");

            Map<String, Object> ring = row(sources, "Sol Ring");
            Assert.assertEquals(ring.get("yield"), 2);
            Assert.assertEquals(ring.get("colors"), "colorless");

            Map<String, Object> forest = row(sources, "Forest");
            Assert.assertEquals(forest.get("count"), 2, "two untapped Forests collapse; the tapped one is absent");
            long forestRows = sources.stream().filter(r -> "Forest".equals(r.get("name"))).count();
            Assert.assertEquals(forestRows, 1);

            // pool 0 + Cradle 3 + Sol Ring 2 + Forests 2 = 7; Workshop (restricted) and Elves (sick) excluded
            Assert.assertEquals(state.get("manaAvailableNow"), 7);

            List<Map<String, Object>> rituals = (List<Map<String, Object>>) state.get("ritualsInHand");
            Assert.assertNotNull(rituals, "ritualsInHand missing");
            Assert.assertEquals(rituals.size(), 3, "Dark Ritual, Mana Geyser, High Tide; not the Bears");

            Map<String, Object> dark = row(rituals, "Dark Ritual");
            Assert.assertEquals(dark.get("kind"), "ritual");
            Assert.assertEquals(dark.get("yield"), 3);
            Assert.assertEquals(dark.get("net"), 2);
            Assert.assertEquals(dark.get("colors"), "B");

            Map<String, Object> geyser = row(rituals, "Mana Geyser");
            Assert.assertEquals(geyser.get("yield"), 3, "three tapped opponent lands");
            Assert.assertEquals(geyser.get("net"), -2);
            Assert.assertEquals(geyser.get("colors"), "R");

            Map<String, Object> tide = row(rituals, "High Tide");
            Assert.assertEquals(tide.get("kind"), "multiplier");
            Assert.assertFalse(tide.containsKey("yield"), "a multiplier carries no number");
        }
    }

    private static Map<String, Object> row(List<Map<String, Object>> rows, String name) {
        for (Map<String, Object> r : rows) {
            if (name.equals(r.get("name"))) {
                return r;
            }
        }
        Assert.fail("no row for " + name + " in " + rows);
        return null;
    }
}
