package forge.arena.interactive;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.card.CounterEnumType;
import forge.game.zone.ZoneType;

/**
 * BL-61 (game 64, 2026-10-02): a root spell or ability whose targets are
 * OPTIONAL ("up to N target …", TargetMin 0) was never aimed — the cast path
 * asked for targets only when one was required — so it resolved at nothing,
 * with no window and no log line. Urza's Tezzeret the Seeker "+1: Untap up to
 * two target artifacts" left Grim Monolith and Mox Amber tapped (turn 15);
 * Purphoros's Shatterskull Smashing, X = 3 at the only blocker, did nothing
 * (turn 36). Behind that gate every part with more than one target went to
 * the stock heuristics.
 *
 * <p>Live-shaped, through the real cast path, on four different cards (a
 * spell, a planeswalker ability, a divided spell, a divided trigger): the
 * seat is asked in ONE CHOOSE_ENTITIES window (purpose TARGETS, min..max),
 * may answer {@code []} when the minimum is 0, and splits a divided amount
 * itself. A punt is handed to stock, never aimed at the first options.
 */
public class OptionalAndMultiTargetTest {

    private static final String CAST = "\"decisionType\":\"CAST_SPELL\"";
    private static final String NUMBER = "\"decisionType\":\"CHOOSE_NUMBER\"";
    private static final String TARGETS = "\"purpose\":\"TARGETS\"";

    private static void library(MailboxTestKit k, String seatLand) {
        for (int i = 0; i < 4; i++) {
            MailboxTestKit.put(seatLand, k.seat, ZoneType.Library);
            MailboxTestKit.put("Forest", k.opp, ZoneType.Library);
        }
    }

    private static boolean inGraveyard(forge.game.player.Player p, String name) {
        for (Card c : p.getCardsIn(ZoneType.Graveyard)) {
            if (c.getName().startsWith(name)) {
                return true;
            }
        }
        return false;
    }

    /** One cast of {@code spell}: the first CAST window picks it, later ones pass. */
    private static String castOnce(String body, AtomicInteger casts, String spell, String extra) {
        String id = extra == null ? MailboxTestKit.idOf(body, spell)
                : MailboxTestKit.idOfWhere(body, spell, extra);
        if (id != null && casts.getAndIncrement() == 0) {
            return "{\"chosenId\": " + id + "}";
        }
        return "{\"chosenId\": 0}";
    }

    @Test(timeOut = 240_000)
    public void upToTwoTargetsReachTheSeatAndBothAreHit() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Frost Breath", k.seat, ZoneType.Hand);        // {2}{U}: tap up to two target creatures
            for (int i = 0; i < 3; i++) {
                MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            }
            Card bears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
            Card giant = MailboxTestKit.put("Hill Giant", k.opp, ZoneType.Battlefield);
            Card ogre = MailboxTestKit.put("Gray Ogre", k.opp, ZoneType.Battlefield);
            library(k, "Island");
            AtomicInteger casts = new AtomicInteger();
            AtomicReference<String> window = new AtomicReference<>();
            k.startBrain(body -> {
                if (body.contains(TARGETS)) {
                    window.set(body);
                    return "{\"chosen\": [" + MailboxTestKit.idOf(body, "Grizzly Bears") + ", "
                            + MailboxTestKit.idOf(body, "Hill Giant") + "]}";
                }
                return body.contains(CAST) ? castOnce(body, casts, "Frost Breath", null) : "{\"chosenId\": 0}";
            });
            k.run(() -> inGraveyard(k.seat, "Frost Breath"), 300);
            k.stopBrain();

            String w = window.get();
            Assert.assertNotNull(w, "the optional root target must open a window (before: none, the spell resolved at nothing)");
            Assert.assertTrue(w.contains("\"decisionType\":\"CHOOSE_ENTITIES\""), w);
            Assert.assertTrue(w.contains("\"min\":0") && w.contains("\"max\":2"), "up to two: 0..2 — " + w);
            Assert.assertTrue(w.contains("[] = no targets"), "the prompt says an empty pick is legal");
            Assert.assertNotNull(MailboxTestKit.idOf(w, "Gray Ogre"), "every legal creature is offered");
            Assert.assertTrue(inGraveyard(k.seat, "Frost Breath"), "the spell resolved");
            Assert.assertTrue(bears.isTapped() && giant.isTapped(), "both picks are tapped");
            Assert.assertFalse(ogre.isTapped(), "the creature the seat did not pick is untouched");
        }
    }

    @Test(timeOut = 240_000)
    public void anEmptyPickIsALegalAnswerAndNothingIsTargeted() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Frost Breath", k.seat, ZoneType.Hand);
            for (int i = 0; i < 3; i++) {
                MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            }
            Card bears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
            library(k, "Island");
            AtomicInteger casts = new AtomicInteger();
            AtomicInteger windows = new AtomicInteger();
            k.startBrain(body -> {
                if (body.contains(TARGETS)) {
                    windows.incrementAndGet();
                    return "{\"chosen\": []}";
                }
                return body.contains(CAST) ? castOnce(body, casts, "Frost Breath", null) : "{\"chosenId\": 0}";
            });
            k.run(() -> inGraveyard(k.seat, "Frost Breath"), 300);
            k.stopBrain();
            Assert.assertEquals(windows.get(), 1, "asked once");
            Assert.assertTrue(inGraveyard(k.seat, "Frost Breath"), "cast and resolved with no targets, as the seat chose");
            Assert.assertFalse(bears.isTapped(), "stock did not aim it behind the seat's back");
        }
    }

    /** The game-64 turn-15 play: a planeswalker's optional two-target ability. */
    @Test(timeOut = 240_000)
    public void tezzeretPlusOneUntapsTheTwoArtifactsTheSeatNames() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card tez = MailboxTestKit.put("Tezzeret the Seeker", k.seat, ZoneType.Battlefield);
            tez.setCounters(CounterEnumType.LOYALTY, 4);
            Card monolith = MailboxTestKit.put("Grim Monolith", k.seat, ZoneType.Battlefield);
            Card stone = MailboxTestKit.put("Mind Stone", k.seat, ZoneType.Battlefield);
            Card ring = MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
            monolith.setTapped(true);
            stone.setTapped(true);
            ring.setTapped(true);
            library(k, "Island");
            AtomicInteger casts = new AtomicInteger();
            AtomicReference<String> window = new AtomicReference<>();
            k.startBrain(body -> {
                if (body.contains(TARGETS)) {
                    window.set(body);
                    return "{\"chosen\": [" + MailboxTestKit.idOf(body, "Grim Monolith") + ", "
                            + MailboxTestKit.idOf(body, "Mind Stone") + "]}";
                }
                return body.contains(CAST) ? castOnce(body, casts, "Tezzeret the Seeker", "Untap up to two")
                        : "{\"chosenId\": 0}";
            });
            k.run(() -> !monolith.isTapped() && !stone.isTapped(), 300);
            k.stopBrain();
            Assert.assertNotNull(window.get(), "Tezzeret's +1 must ask for its artifacts (game 64: it never did)");
            Assert.assertFalse(monolith.isTapped(), "Grim Monolith untapped");
            Assert.assertFalse(stone.isTapped(), "Mind Stone untapped");
            Assert.assertTrue(ring.isTapped(), "the artifact the seat did not name stays tapped");
            Assert.assertEquals(tez.getCounters(CounterEnumType.LOYALTY), 5, "the +1 was paid");
        }
    }

    /** The game-64 turn-36 play, with a split stock would never make: X = 3
     *  divided 1 and 2, so neither creature dies (stock kills the 2/2). */
    @Test(timeOut = 240_000)
    public void shatterskullSmashingIsAimedAndSplitByTheSeat() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Shatterskull Smashing", k.seat, ZoneType.Hand);   // {X}{R}{R}, up to two targets, divided
            for (int i = 0; i < 5; i++) {
                MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);
            }
            Card bears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);   // 2/2
            Card giant = MailboxTestKit.put("Hill Giant", k.opp, ZoneType.Battlefield);      // 3/3
            library(k, "Mountain");
            AtomicInteger casts = new AtomicInteger();
            AtomicReference<String> window = new AtomicReference<>();
            AtomicReference<String> split = new AtomicReference<>();
            k.startBrain(body -> {
                if (body.contains(TARGETS)) {
                    window.set(body);
                    return "{\"chosen\": [" + MailboxTestKit.idOf(body, "Grizzly Bears") + ", "
                            + MailboxTestKit.idOf(body, "Hill Giant") + "]}";
                }
                if (body.contains(NUMBER)) {
                    if (body.contains("DIVIDE 3")) {
                        split.set(body);
                        return "{\"chosen\": 1}";
                    }
                    return "{\"chosen\": 3}";                                          // X
                }
                return body.contains(CAST) ? castOnce(body, casts, "Shatterskull Smashing", "{X}")
                        : "{\"chosenId\": 0}";
            });
            k.run(() -> inGraveyard(k.seat, "Shatterskull Smashing"), 300);
            k.stopBrain();

            String w = window.get();
            Assert.assertNotNull(w, "the divided spell must ask for its targets (game 64 t36: no window, no damage)");
            Assert.assertTrue(w.contains("\"min\":0") && w.contains("\"max\":2"), w);
            Assert.assertTrue(w.contains("\"divide\":3"), "the amount to divide is in the state: " + w);
            String s = split.get();
            Assert.assertNotNull(s, "two targets: the seat is asked the split for the first");
            Assert.assertTrue(s.contains("how much goes to Grizzly Bears"), s);
            Assert.assertTrue(s.contains("\"min\":1") && s.contains("\"max\":2"), "1..2: the second target keeps at least 1 — " + s);
            Assert.assertEquals(bears.getDamage(), 1, "the seat's 1 to the first pick");
            Assert.assertEquals(giant.getDamage(), 2, "the rest to the second");
            Assert.assertFalse(inGraveyard(k.opp, "Grizzly Bears"), "the seat's split, not stock's: the 2/2 lives");
        }
    }

    /** A triggered ability with a divided amount and players among the targets. */
    @Test(timeOut = 240_000)
    public void aDividedTriggerIsAimedAndSplitByTheSeat() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Bogardan Hellkite", k.seat, ZoneType.Hand);   // ETB: 5 damage divided among any number of targets
            for (int i = 0; i < 8; i++) {
                MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);
            }
            Card bears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
            library(k, "Mountain");
            int life = k.opp.getLife();
            AtomicInteger casts = new AtomicInteger();
            AtomicReference<String> window = new AtomicReference<>();
            k.startBrain(body -> {
                if (body.contains(TARGETS)) {
                    window.set(body);
                    return "{\"chosen\": [" + MailboxTestKit.idOf(body, "opp") + ", "
                            + MailboxTestKit.idOf(body, "Grizzly Bears") + "]}";
                }
                if (body.contains(NUMBER) && body.contains("DIVIDE 5")) {
                    return "{\"chosen\": 4}";
                }
                return body.contains(CAST) ? castOnce(body, casts, "Bogardan Hellkite", null) : "{\"chosenId\": 0}";
            });
            k.run(() -> k.opp.getLife() < life, 400);
            k.stopBrain();
            Assert.assertNotNull(window.get(), "the trigger's targets are the seat's (before: the stock heuristics aimed and split)");
            Assert.assertTrue(window.get().contains("\"divide\":5"), window.get());
            Assert.assertEquals(k.opp.getLife(), life - 4, "4 to the player, as the seat split it");
            Assert.assertEquals(bears.getDamage(), 1, "1 to the 2/2 — it lives (stock would have killed it)");
        }
    }

    /** A punt on an OPTIONAL aim ("punt": true, rules.safe_default) proceeds
     *  untargeted — never "the first options", and never stock's mandatory aim,
     *  which can turn the spell on the seat's own permanents. */
    @Test(timeOut = 240_000)
    public void aPuntOnAnOptionalAimProceedsUntargeted() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Frost Breath", k.seat, ZoneType.Hand);
            for (int i = 0; i < 3; i++) {
                MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            }
            Card own = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);   // option 1 would be the seat's own creature
            Card giant = MailboxTestKit.put("Hill Giant", k.opp, ZoneType.Battlefield);
            library(k, "Island");
            AtomicInteger casts = new AtomicInteger();
            String log = captureErr(() -> {
                k.startBrain(body -> {
                    if (body.contains(TARGETS)) {
                        return "{\"chosen\": [], \"punt\": true}";
                    }
                    return body.contains(CAST) ? castOnce(body, casts, "Frost Breath", null) : "{\"chosenId\": 0}";
                });
                k.run(() -> inGraveyard(k.seat, "Frost Breath"), 300);
                k.stopBrain();
            });
            Assert.assertTrue(inGraveyard(k.seat, "Frost Breath"), "the cast completes");
            Assert.assertTrue(log.contains("optional targets for Frost Breath: the seat punted"), "the outcome is logged: " + log);
            Assert.assertFalse(own.isTapped(), "not the first option");
            Assert.assertFalse(giant.isTapped(), "and not a stock aim either");
        }
    }

    /** A punt on a REQUIRED aim goes to stock, and the result is checked: the
     *  divided amount is fully dealt (stock's own split, or an even one). */
    @Test(timeOut = 240_000)
    public void aPuntOnARequiredAimGoesToStockAndStaysLegal() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Electrolyze", k.seat, ZoneType.Hand);        // {1}{U}{R}: 2 damage divided among one or two targets
            MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);
            Card giant = MailboxTestKit.put("Hill Giant", k.opp, ZoneType.Battlefield);
            library(k, "Island");
            int oppLife = k.opp.getLife();
            int seatLife = k.seat.getLife();
            AtomicInteger casts = new AtomicInteger();
            AtomicReference<String> window = new AtomicReference<>();
            String log = captureErr(() -> {
                k.startBrain(body -> {
                    if (body.contains(TARGETS)) {
                        window.set(body);
                        return "{\"chosen\": [1], \"punt\": true}";
                    }
                    return body.contains(CAST) ? castOnce(body, casts, "Electrolyze", null) : "{\"chosenId\": 0}";
                });
                k.run(() -> inGraveyard(k.seat, "Electrolyze"), 300);
                k.stopBrain();
            });
            Assert.assertNotNull(window.get(), "the seat was asked first; log: " + log + " seen: " + k.seen);
            Assert.assertTrue(window.get().contains("\"min\":1") && window.get().contains("\"divide\":2"), window.get());
            Assert.assertTrue(log.contains("chooseTargetsFor(multi: punt)"), "the hand-off to stock is logged: " + log);
            Assert.assertTrue(inGraveyard(k.seat, "Electrolyze"), "the cast completes on the stock floor");
            int dealt = (oppLife - k.opp.getLife()) + giant.getDamage() + (seatLife - k.seat.getLife());
            Assert.assertEquals(dealt, 2, "every point of the divided amount lands somewhere");
        }
    }

    private interface Body {
        void run() throws Exception;
    }

    /** Runs {@code body} with System.err teed into a buffer; returns what was written. */
    private static String captureErr(Body body) throws Exception {
        java.io.PrintStream err = System.err;
        java.io.ByteArrayOutputStream captured = new java.io.ByteArrayOutputStream();
        System.setErr(new java.io.PrintStream(new java.io.OutputStream() {
            @Override
            public void write(int b) {
                captured.write(b);
                err.write(b);
            }
        }, true));
        try {
            body.run();
        } finally {
            System.setErr(err);
        }
        return captured.toString();
    }
}
