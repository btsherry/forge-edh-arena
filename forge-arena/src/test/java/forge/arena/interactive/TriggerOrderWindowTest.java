package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.zone.ZoneType;

/**
 * BL-02 (2026-09-04), CR 603.3b: when two or more of the seat's triggers go on
 * the stack at once, the SEAT orders them — through a {@code CHOOSE_MODE}
 * window with {@code state.purpose = "TRIGGER_ORDER"}, one option per
 * distinct trigger (grouped by host + text), answered in RESOLUTION order.
 * Identical triggers open no window; a silent brain falls to stock ordering.
 * Two pairs of death triggers on different cards; one kit game.
 */
public class TriggerOrderWindowTest {

    private static final String PURPOSE = "\"purpose\":\"TRIGGER_ORDER\"";

    /** Answer TRIGGER_ORDER windows with {@code first} resolving first, then the rest in offered order. */
    private static String orderAnswer(String body, String first) {
        java.util.List<Integer> ids = new java.util.ArrayList<>();
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("\\{\"id\":(\\d+),\"label\":\"([^\"]*)\"").matcher(body);
        Integer firstId = null;
        while (m.find()) {
            int id = Integer.parseInt(m.group(1));
            if (m.group(2).startsWith(first)) {
                firstId = id;
            } else {
                ids.add(id);
            }
        }
        Assert.assertNotNull(firstId, "option for " + first + " offered in: " + body);
        ids.add(0, firstId);
        return "{\"chosen\": " + ids + "}";
    }

    private static void clearBattlefield(MailboxTestKit k) {
        for (Card c : new java.util.ArrayList<>(k.seat.getCardsIn(ZoneType.Battlefield))) {
            k.seat.getZone(ZoneType.Battlefield).remove(c);
        }
    }

    private static long windows(MailboxTestKit k) {
        return k.seen.stream().filter(b -> b.contains(PURPOSE)).count();
    }

    /** A creature of the seat's dies; the death triggers wait for ordering. */
    private static void killABear(MailboxTestKit k) {
        Card bear = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        k.game.getAction().moveToGraveyard(bear, null);
        k.run(() -> !k.game.getStack().isEmpty(), 40);
    }

    @Test(timeOut = 180_000)
    public void seatOrdersDistinctTriggersAndIdenticalOnesNeverAsk() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            final String[] resolveFirst = {"Midnight Reaper"};
            k.startBrain(body -> body.contains(PURPOSE) ? orderAnswer(body, resolveFirst[0]) : null);
            for (int i = 0; i < 4; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
            }

            // pair A: Zulaport Cutthroat + Midnight Reaper — two different
            // death triggers from one death; the seat asks Reaper to resolve first
            MailboxTestKit.put("Zulaport Cutthroat", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Midnight Reaper", k.seat, ZoneType.Battlefield);
            killABear(k);
            Assert.assertEquals(windows(k), 1, "one TRIGGER_ORDER window for two distinct triggers");
            Assert.assertFalse(k.game.getStack().isEmpty(), "triggers are on the stack");
            Assert.assertEquals(k.game.getStack().peekAbility().getHostCard().getName(), "Midnight Reaper",
                    "the first to RESOLVE is on top of the stack");
            String w = k.seen.stream().filter(b -> b.contains(PURPOSE)).findFirst().get();
            Assert.assertTrue(w.contains("\"min\":2") && w.contains("\"max\":2"), "min = max = groups: " + w);
            // let them resolve
            k.run(() -> k.game.getStack().isEmpty(), 60);

            // pair B: Grim Haruspex + Cruel Celebrant, four distinct groups; Celebrant first
            resolveFirst[0] = "Cruel Celebrant";
            MailboxTestKit.put("Grim Haruspex", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Cruel Celebrant", k.seat, ZoneType.Battlefield);
            killABear(k);
            Assert.assertEquals(windows(k), 2);
            Assert.assertEquals(k.game.getStack().peekAbility().getHostCard().getName(), "Cruel Celebrant");
            k.run(() -> k.game.getStack().isEmpty(), 60);

            // identical triggers: two Zulaports only — no window, both on the stack
            clearBattlefield(k);
            MailboxTestKit.put("Zulaport Cutthroat", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Zulaport Cutthroat", k.seat, ZoneType.Battlefield);
            killABear(k);
            Assert.assertEquals(windows(k), 2, "identical triggers never open a window");
            Assert.assertEquals(k.game.getStack().size(), 2, "…and both still go on the stack");
            k.run(() -> k.game.getStack().isEmpty(), 60);
        }
    }

    @Test(timeOut = 180_000)
    public void silentBrainFallsToStockOrdering() throws Exception {
        String prev = System.getProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, "3");
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            k.startBrain(body -> body.contains(PURPOSE) ? MailboxTestKit.SILENT : null);
            MailboxTestKit.put("Zulaport Cutthroat", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Midnight Reaper", k.seat, ZoneType.Battlefield);
            for (int i = 0; i < 4; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
            }
            killABear(k);
            Assert.assertEquals(windows(k), 1, "the window was opened");
            Assert.assertEquals(k.game.getStack().size(), 2, "stock ordered both triggers onto the stack");
        } finally {
            if (prev == null) {
                System.clearProperty(MailboxProtocol.TIMEOUT_PROPERTY);
            } else {
                System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, prev);
            }
        }
    }
}
