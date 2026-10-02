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

    /** W-16 (game 37 t19): Cavern of Souls carries a plain {C} tap and a
     *  type-restricted colour tap; the row must take the UNRESTRICTED one so
     *  the sum counts the Cavern, and note the restricted twin for the brain. */
    @Test(timeOut = 120_000)
    public void cavernOfSoulsCountsAsAPlainSource() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Cavern of Souls", k.seat, ZoneType.Battlefield);
            Map<String, Object> state = MailboxController.buildState(k.seat, k.seat.getId(), 3);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> sources = (List<Map<String, Object>>) state.get("manaSources");
            Map<String, Object> cavern = null;
            for (Map<String, Object> row : sources) {
                if ("Cavern of Souls".equals(row.get("name"))) {
                    cavern = row;
                }
            }
            Assert.assertNotNull(cavern, sources.toString());
            Assert.assertNull(cavern.get("restricted"), "the plain {C} tap is the row: " + cavern);
            Assert.assertNotNull(cavern.get("alsoRestricted"), "the typed colour tap is noted: " + cavern);
            Assert.assertEquals(state.get("manaAvailableNow"), 1, "the Cavern counts once");
        }
    }

    /** BL-43 (game 31 t22): Selvala needs {G} to activate, so she is listed
     *  but not summed into manaAvailableNow; manaReach funds her from the
     *  summed mana and adds her NET yield — the ceiling the payer can reach.
     *  With no plain mana to pay her {G}, the reach stays at the sum. */
    @Test(timeOut = 120_000)
    public void manaReachFundsSelvalaFromPlainMana() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card selvalaCard = MailboxTestKit.put("Selvala, Heart of the Wilds", k.seat, ZoneType.Battlefield);
            selvalaCard.setSickness(false);   // a sick Selvala is listed but never reached (the gate's first run: reach 2)
            MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Battlefield); // 5/5
            Map<String, Object> state = MailboxController.buildState(k.seat, k.seat.getId(), 3);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> sources = (List<Map<String, Object>>) state.get("manaSources");
            Map<String, Object> selvala = null;
            for (Map<String, Object> row : sources) {
                if ("Selvala, Heart of the Wilds".equals(row.get("name"))) {
                    selvala = row;
                }
            }
            Assert.assertNotNull(selvala, sources.toString());
            Assert.assertEquals(selvala.get("costMana"), 1, "her {G} is a mana-only extra cost: " + selvala);
            Assert.assertEquals(state.get("manaAvailableNow"), 0, "nothing bare-tap untapped");
            Assert.assertEquals(state.get("manaReach"), 0, "no mana to pay her {G}: the reach is the sum");
            MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            Map<String, Object> after = MailboxController.buildState(k.seat, k.seat.getId(), 3);
            Assert.assertEquals(after.get("manaAvailableNow"), 2);
            Assert.assertEquals(after.get("manaReach"), 2 + 5 - 1, "two Forests, one pays Selvala's {G}, she adds 5");
        }
    }

    @Test
    public void manaReachIgnoresSequencesWithNonManaCosts() {
        List<Map<String, Object>> rows = new java.util.ArrayList<>();
        java.util.Map<String, Object> led = new java.util.LinkedHashMap<>();
        led.put("name", "Lion's Eye Diamond"); led.put("yield", 3); led.put("cost", "Discard your hand"); // no costMana
        rows.add(led);
        java.util.Map<String, Object> nyk = new java.util.LinkedHashMap<>();
        nyk.put("name", "Nykthos, Shrine to Nyx"); nyk.put("yield", 6); nyk.put("costMana", 2);
        rows.add(nyk);
        java.util.Map<String, Object> sick = new java.util.LinkedHashMap<>();
        sick.put("name", "Selvala, Heart of the Wilds"); sick.put("yield", 8); sick.put("costMana", 1); sick.put("sick", true);
        rows.add(sick);
        Assert.assertEquals(MailboxController.manaReach(1, rows), 1, "Nykthos needs 2, LED is not mana-only, Selvala is sick");
        Assert.assertEquals(MailboxController.manaReach(2, rows), 6, "2 pays Nykthos: 2 + (6 - 2)");
        Assert.assertEquals(MailboxController.manaReach(0, java.util.Collections.emptyList()), 0);
    }

    /** BL-45 (game 37 t27): Tezzeret the Seeker's −X is a LOYALTY X — the
     *  mana affordability ceiling must not apply; Walking Ballista's X is a
     *  mana X and must. */
    @Test(timeOut = 120_000)
    public void loyaltyXIsNotAManaX() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card tez = MailboxTestKit.put("Tezzeret the Seeker", k.seat, ZoneType.Battlefield);
            boolean sawMinusX = false;
            for (forge.game.spellability.SpellAbility sa : tez.getSpellAbilities()) {
                String d = String.valueOf(sa.getDescription());
                if (d.startsWith("-X")) {
                    sawMinusX = true;
                    Assert.assertTrue(sa.getPayCosts().hasXInAnyCostPart(), "Forge sees an X in the cost: " + d);
                    Assert.assertFalse(MailboxController.xPaidWithMana(sa.getPayCosts()), "but it is loyalty, not mana: " + d);
                }
            }
            Assert.assertTrue(sawMinusX, "Tezzeret's −X ability not found: " + tez.getSpellAbilities());
            Card ballista = MailboxTestKit.put("Walking Ballista", k.seat, ZoneType.Hand);
            boolean sawCast = false;
            for (forge.game.spellability.SpellAbility sa : ballista.getSpells()) {
                sawCast = true;
                Assert.assertTrue(MailboxController.xPaidWithMana(sa.getPayCosts()), "Ballista's {X}{X} is mana");
            }
            Assert.assertTrue(sawCast);
            Assert.assertFalse(MailboxController.xPaidWithMana(null));
        }
    }

    /** W-4, proven on game 64 (2026-10-02): Gemstone Caverns is scripted as two
     *  mana parts with opposite conditions ({C} without a luck counter, any
     *  colour with one). The yield summed both — the seat was told "yield 2",
     *  "[currently adds 2 mana]" and one mana too many payable now; Giada
     *  planned a seven-mana Final Showdown on six. One part is live at a time. */
    @Test(timeOut = 120_000)
    public void aManaPartWhoseConditionIsUnmetAddsNothing() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card caverns = MailboxTestKit.put("Gemstone Caverns", k.seat, ZoneType.Battlefield);
            String[] colours = {"colorless", "any"};
            for (int luck = 0; luck <= 1; luck++) {
                caverns.setCounters(forge.game.card.CounterEnumType.LUCK, luck);
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> rows = (List<Map<String, Object>>) MailboxController.buildState(k.seat, k.seat.getId(), 3).get("manaSources");
                Assert.assertEquals(rows.size(), 1, String.valueOf(rows));
                Assert.assertEquals(rows.get(0).get("yield"), Integer.valueOf(1), "luck " + luck + ": one mana per tap — " + rows);
                Assert.assertEquals(rows.get(0).get("colors"), colours[luck], String.valueOf(rows));
                Assert.assertEquals(MailboxController.manaAvailableNow(k.seat, rows), 1, "luck " + luck);
            }
            // a plain multi-mana source still counts every part it produces
            MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows = (List<Map<String, Object>>) MailboxController.buildState(k.seat, k.seat.getId(), 3).get("manaSources");
            Assert.assertEquals(MailboxController.manaAvailableNow(k.seat, rows), 3, "Caverns 1 + Sol Ring 2: " + rows);
        }
    }

    /** …and the stock payer taps a luck-counter Caverns for coloured mana on its
     *  own (the seat's "float Caverns first; the auto-payer skips it" was a habit
     *  the misread yield taught it): one spell is paid, the second is refused. */
    @Test(timeOut = 240_000)
    public void thePayerTapsALuckCounterCavernsOnce() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card caverns = MailboxTestKit.put("Gemstone Caverns", k.seat, ZoneType.Battlefield);
            caverns.setCounters(forge.game.card.CounterEnumType.LUCK, 1);
            MailboxTestKit.put("Savannah Lions", k.seat, ZoneType.Hand);    // {W}
            MailboxTestKit.put("Llanowar Elves", k.seat, ZoneType.Hand);    // {G}
            for (int i = 0; i < 4; i++) {
                MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
                MailboxTestKit.put("Forest", k.opp, ZoneType.Library);
            }
            java.util.concurrent.atomic.AtomicInteger casts = new java.util.concurrent.atomic.AtomicInteger();
            List<String> windows = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
            k.startBrain(body -> {
                if (!body.contains("\"decisionType\":\"CAST_SPELL\"")) {
                    return "{\"chosenId\": 0}";
                }
                int n = casts.incrementAndGet();
                windows.add(body);
                String id = n == 1 ? MailboxTestKit.idOf(body, "Savannah Lions")
                        : n == 2 ? MailboxTestKit.idOf(body, "Llanowar Elves") : null;
                return "{\"chosenId\": " + (id != null ? id : "0") + "}";
            });
            k.run(() -> casts.get() >= 3, 200);
            k.stopBrain();
            Assert.assertTrue(windows.size() >= 3, "three cast windows, saw " + windows.size());
            Assert.assertNull(MailboxTestKit.idOf(windows.get(0), "Gemstone Caverns"),
                    "a one-mana land is not a float option, like every other land");
            boolean lions = false;
            boolean elves = false;
            for (Card c : k.seat.getCardsIn(ZoneType.Battlefield)) {
                lions |= c.getName().equals("Savannah Lions");
                elves |= c.getName().equals("Llanowar Elves");
            }
            Assert.assertTrue(lions, "the payer tapped Caverns for {W} without the seat floating it");
            Assert.assertFalse(elves, "one land, one mana: the second spell is not paid");
            Assert.assertTrue(windows.get(2).contains("\"lastRefused\":{"), "and its refusal is reported");
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
