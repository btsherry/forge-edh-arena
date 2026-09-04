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

    /** Resolution order is the contract ("first listed resolves FIRST"): the
     *  kit's loop step can resolve the top of the stack inside the very step
     *  that pushed it, so the stack itself is not a reliable witness. */
    static final class Resolved {
        final java.util.List<String> hosts = java.util.Collections.synchronizedList(new java.util.ArrayList<>());

        @com.google.common.eventbus.Subscribe
        public void on(forge.game.event.GameEventSpellResolved e) {
            try {
                hosts.add(e.spell().getHostCard().getName());
            } catch (RuntimeException ignore) {
                // a view without a host: not one of ours
            }
        }
    }

    private static java.util.List<String> ours(Resolved r, String... names) {
        java.util.Set<String> want = new java.util.HashSet<>(java.util.Arrays.asList(names));
        java.util.List<String> out = new java.util.ArrayList<>();
        for (String h : r.hosts) {
            if (want.contains(h)) {
                out.add(h);
            }
        }
        return out;
    }

    /** Cards placed straight into a zone have no ACTIVE triggers until the
     *  engine's next state check re-registers them (GameAction does that on
     *  its own zone moves; the kit's put() bypasses it). */
    private static void settle(MailboxTestKit k) {
        k.game.getAction().checkStateEffects(true);
    }

    /** Step the phase loop until {@code done}, WITHOUT the kit's stack-empty
     *  requirement — we need to stop while the ordered triggers sit on the stack. */
    private static void stepUntil(MailboxTestKit k, java.util.function.BooleanSupplier done, int max) {
        for (int i = 0; i < max && !done.getAsBoolean() && !k.game.isGameOver(); i++) {
            k.game.getPhaseHandler().mainLoopStep();
        }
    }

    /** A creature of the seat's dies; the death triggers are ordered, pushed
     *  and resolved. */
    private static void killABear(MailboxTestKit k) {
        settle(k);
        Card bear = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        settle(k);
        k.game.getAction().moveToGraveyard(bear, null);
        stepUntil(k, () -> !k.game.getStack().isEmpty(), 40);
        k.run(() -> k.game.getStack().isEmpty(), 60);
    }

    @Test(timeOut = 180_000)
    public void seatOrdersDistinctTriggersAndIdenticalOnesNeverAsk() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            final String[] resolveFirst = {"Midnight Reaper"};
            k.startBrain(body -> body.contains(PURPOSE) ? orderAnswer(body, resolveFirst[0]) : null);
            Resolved resolved = new Resolved();
            k.game.subscribeToEvents(resolved);
            for (int i = 0; i < 8; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
            }

            // pair A: Zulaport Cutthroat + Midnight Reaper — two different
            // death triggers from one death; the seat asks Reaper to resolve first
            MailboxTestKit.put("Zulaport Cutthroat", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Midnight Reaper", k.seat, ZoneType.Battlefield);
            killABear(k);
            Assert.assertEquals(windows(k), 1, "one TRIGGER_ORDER window for two distinct triggers");
            Assert.assertEquals(ours(resolved, "Midnight Reaper", "Zulaport Cutthroat"),
                    java.util.List.of("Midnight Reaper", "Zulaport Cutthroat"),
                    "the seat's order IS the resolution order");
            String w = k.seen.stream().filter(b -> b.contains(PURPOSE)).findFirst().get();
            Assert.assertTrue(w.contains("\"min\":2") && w.contains("\"max\":2"), "min = max = groups: " + w);
            Assert.assertFalse(w.contains("Zone Changer"),
                    "groups are keyed by the trigger's own text, never the dying creature: " + w);

            // pair B: Grim Haruspex + Cruel Celebrant join — four distinct groups; Celebrant first
            resolved.hosts.clear();
            resolveFirst[0] = "Cruel Celebrant";
            MailboxTestKit.put("Grim Haruspex", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Cruel Celebrant", k.seat, ZoneType.Battlefield);
            killABear(k);
            Assert.assertEquals(windows(k), 2);
            java.util.List<String> order = ours(resolved, "Midnight Reaper", "Zulaport Cutthroat",
                    "Grim Haruspex", "Cruel Celebrant");
            Assert.assertEquals(order.size(), 4, "all four triggers resolved: " + order);
            Assert.assertEquals(order.get(0), "Cruel Celebrant", "the first listed resolves first: " + order);

            // identical triggers: two Zulaports only — no window, both still resolve
            clearBattlefield(k);
            resolved.hosts.clear();
            MailboxTestKit.put("Zulaport Cutthroat", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Zulaport Cutthroat", k.seat, ZoneType.Battlefield);
            killABear(k);
            Assert.assertEquals(windows(k), 2, "identical triggers never open a window");
            Assert.assertEquals(ours(resolved, "Zulaport Cutthroat").size(), 2, "…and both still resolved");

            // the sacrifice deck's normal batch: several creatures die AT ONCE, so
            // each Zulaport fires once per death with a different "zone changer" —
            // still ONE group (review 2026-09-04), still no window
            resolved.hosts.clear();
            settle(k);
            Card b1 = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            Card b2 = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            Card b3 = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            settle(k);
            k.game.getAction().moveToGraveyard(b1, null);
            k.game.getAction().moveToGraveyard(b2, null);
            k.game.getAction().moveToGraveyard(b3, null);
            stepUntil(k, () -> !k.game.getStack().isEmpty(), 40);
            k.run(() -> k.game.getStack().isEmpty(), 80);
            Assert.assertEquals(windows(k), 2, "six copies of one trigger from three deaths never open a window");
            Assert.assertEquals(ours(resolved, "Zulaport Cutthroat").size(), 6, "…and all six resolved");
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
            Resolved resolved = new Resolved();
            k.game.subscribeToEvents(resolved);
            killABear(k);
            Assert.assertEquals(windows(k), 1, "the window was opened");
            Assert.assertEquals(ours(resolved, "Midnight Reaper", "Zulaport Cutthroat").size(), 2,
                    "stock ordered and resolved both triggers");
        } finally {
            if (prev == null) {
                System.clearProperty(MailboxProtocol.TIMEOUT_PROPERTY);
            } else {
                System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, prev);
            }
        }
    }
}
