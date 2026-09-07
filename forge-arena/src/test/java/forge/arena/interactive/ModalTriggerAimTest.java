package forge.arena.interactive;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.zone.ZoneType;

/**
 * BL-30 (game 23, 2026-09-06): a seat's own MODAL trigger whose chosen mode
 * has a target. The seat picked "fights up to one target creature you don't
 * control" for Kogla and Yidaro in the CHOOSE_MODE window, but
 * {@code prepareTriggerViaSeat} returned right after the mode choice, so the
 * mode reached the stack untargeted and Forge dropped it:
 * {@code [Couldn't add to stack, failed to target]}. The chosen chain must go
 * through the same CHOOSE_ENTITY aiming as any other own trigger, on two
 * cards (an opponent-targeting fight, an own-creature exile), and a silent
 * brain at aim time must fall to stock aiming, never to a dropped trigger.
 */
public class ModalTriggerAimTest {

    private static final String CAST = "\"decisionType\":\"CAST_SPELL\"";
    private static final String MODE = "\"decisionType\":\"CHOOSE_MODE\"";
    private static final String AIM = "\"decisionType\":\"CHOOSE_ENTITY\"";
    private static final String DROPPED = "Couldn't add to stack, failed to target";

    /** Index of the first CHOOSE_MODE option whose label contains {@code needle}. */
    private static String modeIndex(String body, String needle) {
        Matcher m = Pattern.compile("\"id\":(\\d+),\"label\":\"([^\"]*)\"").matcher(body);
        while (m.find()) {
            if (m.group(2).toLowerCase().contains(needle.toLowerCase())) {
                return m.group(1);
            }
        }
        return "0";
    }

    private static void lands(MailboxTestKit k, String name, int n) {
        for (int i = 0; i < n; i++) {
            MailboxTestKit.put(name, k.seat, ZoneType.Battlefield);
        }
    }

    private static void libraries(MailboxTestKit k) {
        for (int i = 0; i < 4; i++) {
            MailboxTestKit.put("Forest", k.seat, ZoneType.Library);
            MailboxTestKit.put("Island", k.opp, ZoneType.Library);
        }
    }

    private static String cast(String body, String name) {
        String id = MailboxTestKit.idOf(body, name);
        return "{\"chosenId\": " + (id != null ? id : "0") + "}";
    }

    private static boolean sawAimFor(MailboxTestKit k, String host) {
        for (String s : k.seen) {
            if (s.contains(AIM) && s.contains("TARGET for " + host)) {
                return true;
            }
        }
        return false;
    }

    @Test(timeOut = 240_000)
    public void koglaFightModeIsAimedBySeatAndResolves() throws Exception {
        PrintStream realErr = System.err;
        ByteArrayOutputStream errBuf = new ByteArrayOutputStream();
        System.setErr(new PrintStream(errBuf, true));
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Kogla and Yidaro", k.seat, ZoneType.Hand);
            lands(k, "Mountain", 4);
            lands(k, "Forest", 4);
            libraries(k);
            Card bears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
            k.startBrain(body -> {
                if (body.contains(CAST)) {
                    return cast(body, "Kogla and Yidaro");
                }
                if (body.contains(MODE)) {
                    return "{\"chosen\": [" + modeIndex(body, "fights") + "]}";
                }
                if (body.contains(AIM)) {
                    return "{\"chosenId\": " + MailboxTestKit.idOf(body, "Grizzly Bears") + "}";
                }
                return "{\"chosenId\": 0}";
            });
            k.run(() -> !bears.isInZone(ZoneType.Battlefield), 400);
            String err = errBuf.toString();
            System.setErr(realErr);
            System.out.println("MODAL-AIM kogla: aimAsked=" + sawAimFor(k, "Kogla and Yidaro")
                    + " bearsAlive=" + bears.isInZone(ZoneType.Battlefield)
                    + " dropped=" + err.contains(DROPPED));
            Assert.assertTrue(sawAimFor(k, "Kogla and Yidaro"),
                    "the chosen fight mode must open a CHOOSE_ENTITY aim window for the seat");
            Assert.assertFalse(err.contains(DROPPED),
                    "the modal trigger must never be dropped as 'failed to target'");
            Assert.assertFalse(bears.isInZone(ZoneType.Battlefield),
                    "the fight must resolve against the seat's chosen target");
        } finally {
            System.setErr(realErr);
        }
    }

    @Test(timeOut = 240_000)
    public void charmingPrinceExileModeIsAimedBySeatAndResolves() throws Exception {
        PrintStream realErr = System.err;
        ByteArrayOutputStream errBuf = new ByteArrayOutputStream();
        System.setErr(new PrintStream(errBuf, true));
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Charming Prince", k.seat, ZoneType.Hand);
            lands(k, "Plains", 3);
            libraries(k);
            Card own = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            k.startBrain(body -> {
                if (body.contains(CAST)) {
                    return cast(body, "Charming Prince");
                }
                if (body.contains(MODE)) {
                    return "{\"chosen\": [" + modeIndex(body, "exile") + "]}";
                }
                if (body.contains(AIM)) {
                    return "{\"chosenId\": " + MailboxTestKit.idOf(body, "Grizzly Bears") + "}";
                }
                return "{\"chosenId\": 0}";
            });
            k.run(() -> !own.isInZone(ZoneType.Battlefield), 400);
            String err = errBuf.toString();
            System.setErr(realErr);
            System.out.println("MODAL-AIM prince: aimAsked=" + sawAimFor(k, "Charming Prince")
                    + " bearsOnBattlefield=" + own.isInZone(ZoneType.Battlefield)
                    + " dropped=" + err.contains(DROPPED));
            Assert.assertTrue(sawAimFor(k, "Charming Prince"),
                    "the chosen exile mode must open a CHOOSE_ENTITY aim window for the seat");
            Assert.assertFalse(err.contains(DROPPED), "the modal trigger must never be dropped");
            Assert.assertFalse(own.isInZone(ZoneType.Battlefield),
                    "the exile must resolve against the seat's chosen creature");
        } finally {
            System.setErr(realErr);
        }
    }

    @Test(timeOut = 240_000)
    public void silentBrainAtAimFallsToStockNotToADroppedTrigger() throws Exception {
        String prev = System.getProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, "1");
        PrintStream realErr = System.err;
        ByteArrayOutputStream errBuf = new ByteArrayOutputStream();
        System.setErr(new PrintStream(errBuf, true));
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card kogla = MailboxTestKit.put("Kogla and Yidaro", k.seat, ZoneType.Hand);
            lands(k, "Mountain", 4);
            lands(k, "Forest", 4);
            libraries(k);
            MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
            k.startBrain(body -> {
                if (body.contains(CAST)) {
                    return cast(body, "Kogla and Yidaro");
                }
                if (body.contains(MODE)) {
                    return "{\"chosen\": [" + modeIndex(body, "fights") + "]}";
                }
                if (body.contains(AIM)) {
                    return MailboxTestKit.SILENT; // dead brain at aim time
                }
                return "{\"chosenId\": 0}";
            });
            k.run(() -> kogla.isInZone(ZoneType.Battlefield) && k.game.getStack().isEmpty()
                    && sawAimFor(k, "Kogla and Yidaro"), 400);
            String err = errBuf.toString();
            System.setErr(realErr);
            System.out.println("MODAL-AIM silent: aimAsked=" + sawAimFor(k, "Kogla and Yidaro")
                    + " stockFallback=" + err.contains("no usable answer at aim")
                    + " dropped=" + err.contains(DROPPED));
            Assert.assertTrue(sawAimFor(k, "Kogla and Yidaro"), "the seat must have been asked to aim");
            Assert.assertTrue(err.contains("no usable answer at aim"),
                    "a failed aim exchange on a modal trigger must be logged as a stock fallback");
            Assert.assertFalse(err.contains(DROPPED),
                    "stock aiming must stack the chosen mode; the trigger is never dropped");
        } finally {
            System.setErr(realErr);
            if (prev == null) {
                System.clearProperty(MailboxProtocol.TIMEOUT_PROPERTY);
            } else {
                System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, prev);
            }
        }
    }
}
