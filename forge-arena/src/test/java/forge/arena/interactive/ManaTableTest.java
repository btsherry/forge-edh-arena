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

    /** 2026-09-07: the human autopass ceiling treats a non-integer yield as
     *  unknown (-1 -> keep every stop). Selvala's X is Count$Valid
     *  Creature.YouCtrl$GreatestCardPower — the engine can evaluate it now,
     *  so the table must see the live number, not "unknown". */
    @Test(timeOut = 120_000)
    public void selvalaYieldIsTheGreatestPowerNow() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Selvala, Heart of the Wilds", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Battlefield); // 5/5
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> sources = (List<Map<String, Object>>) MailboxController.buildState(k.seat, k.seat.getId(), 3).get("manaSources");
            Map<String, Object> selvala = null;
            for (Map<String, Object> row : sources) {
                if ("Selvala, Heart of the Wilds".equals(row.get("name"))) {
                    selvala = row;
                }
            }
            Assert.assertNotNull(selvala, "Selvala row missing: " + sources);
            Assert.assertEquals(selvala.get("yield"), 5, "X = greatest power among creatures you control: " + selvala);
        }
    }

    /** Games 27-28: a mana ability whose activation restriction fails now
     *  (Mox Opal, metalcraft) is listed but flagged dormant and never summed
     *  into manaAvailableNow; with metalcraft it is a normal source. */
    @Test(timeOut = 120_000)
    public void conditionLockedManaSourceIsDormantNotAvailable() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Mox Opal", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> sources = (List<Map<String, Object>>) MailboxController.buildState(k.seat, k.seat.getId(), 3).get("manaSources");
            Map<String, Object> opal = null;
            for (Map<String, Object> row : sources) {
                if ("Mox Opal".equals(row.get("name"))) {
                    opal = row;
                }
            }
            Assert.assertNotNull(opal, "Mox Opal row: " + sources);
            Assert.assertEquals(opal.get("dormant"), Boolean.TRUE, "one artifact: no metalcraft, dormant: " + opal);
            Assert.assertEquals(MailboxController.manaAvailableNow(k.seat, sources), 1, "only the Forest counts");
            MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Lotus Petal", k.seat, ZoneType.Battlefield);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> after = (List<Map<String, Object>>) MailboxController.buildState(k.seat, k.seat.getId(), 3).get("manaSources");
            for (Map<String, Object> row : after) {
                if ("Mox Opal".equals(row.get("name"))) {
                    Assert.assertNull(row.get("dormant"), "three artifacts: metalcraft on, live source: " + row);
                }
            }
        }
    }

    /** Game 29 t7: a ready land-untapper (Arbor Elf) makes a deliberate land
     *  tap a real line; without one (or while the Elf is summoning sick) bare
     *  land taps stay hidden. */
    @Test(timeOut = 120_000)
    public void landUntapperReadyDetectsArborElf() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            Assert.assertFalse(MailboxController.landUntapperReady(k.seat), "no untapper");
            Card elf = MailboxTestKit.put("Arbor Elf", k.seat, ZoneType.Battlefield);
            Assert.assertFalse(MailboxController.landUntapperReady(k.seat), "a summoning-sick Elf cannot tap yet");
            elf.setSickness(false);
            Assert.assertTrue(MailboxController.landUntapperReady(k.seat), "untapped, unsick Arbor Elf");
            elf.tap(true, null, null);
            Assert.assertFalse(MailboxController.landUntapperReady(k.seat), "a tapped Elf is no enabler");
        }
    }
}
