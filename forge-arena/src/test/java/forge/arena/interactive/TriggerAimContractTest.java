package forge.arena.interactive;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.zone.ZoneType;

/**
 * Item 1 of the 2026-09-03 interactive plan: the trigger-aim contract.
 *
 * <p>Two cards, two trigger kinds, from ONE cast: Ravenous Chupacabra's ETB is
 * a MANDATORY targeted trigger ("destroy target creature an opponent
 * controls"); with Aura Shards on the battlefield the same ETB also fires an
 * OPTIONAL targeted trigger ("you may destroy target artifact or enchantment").
 * Both are aimed through the seat in the same simultaneous batch.
 *
 * <ul>
 *   <li>The optional trigger's aim window offers the id-0 DECLINE option; the
 *       mandatory trigger's window must NOT (it used to, and a "decline" then
 *       auto-aimed the first candidate and resolved anyway).</li>
 *   <li>A brain that answers 0 to both: the optional trigger is declined (Sol
 *       Ring survives); the mandatory trigger falls to STOCK aiming and
 *       resolves against its only legal target (Grizzly Bears dies).</li>
 *   <li>A brain that never answers the aim windows: BOTH fall to stock aiming
 *       (the mandatory kill still happens) and the log says so — a failed
 *       exchange is never a silent decline.</li>
 * </ul>
 */
public class TriggerAimContractTest {

    private static final String CAST = "\"decisionType\":\"CAST_SPELL\"";
    private static final String AIM = "\"decisionType\":\"CHOOSE_ENTITY\"";
    private static final String DECLINE_LABEL = "DECLINE this optional trigger";

    private static Card[] board(MailboxTestKit k) {
        MailboxTestKit.put("Aura Shards", k.seat, ZoneType.Battlefield);
        MailboxTestKit.put("Ravenous Chupacabra", k.seat, ZoneType.Hand);
        for (int i = 0; i < 4; i++) {
            MailboxTestKit.put("Swamp", k.seat, ZoneType.Battlefield);
        }
        for (int i = 0; i < 3; i++) {
            MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
        }
        Card ring = MailboxTestKit.put("Sol Ring", k.opp, ZoneType.Battlefield);
        Card bears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
        for (int i = 0; i < 3; i++) {
            MailboxTestKit.put("Island", k.opp, ZoneType.Library);
        }
        return new Card[] {ring, bears};
    }

    private static String castChupacabra(String body) {
        String id = MailboxTestKit.idOf(body, "Ravenous Chupacabra");
        return "{\"chosenId\": " + (id != null ? id : "0") + "}";
    }

    @Test(timeOut = 240_000)
    public void declineIsOfferedOnlyForOptionalTriggersAndMandatoryFallsToStock() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card[] cards = board(k);
            Card ring = cards[0];
            Card bears = cards[1];
            k.startBrain(body -> {
                if (body.contains(CAST)) {
                    return castChupacabra(body);
                }
                if (body.contains(AIM)) {
                    return "{\"chosenId\": 0}"; // "decline" both — legal only for the optional one
                }
                return "{\"chosenId\": 0}";
            });
            k.run(() -> !bears.isInZone(ZoneType.Battlefield), 400);

            boolean mandatoryAsked = false;
            boolean mandatoryOfferedDecline = false;
            boolean optionalAsked = false;
            boolean optionalOfferedDecline = false;
            for (String s : k.seen) {
                if (!s.contains(AIM)) {
                    continue;
                }
                if (s.contains("TARGET for Ravenous Chupacabra")) {
                    mandatoryAsked = true;
                    mandatoryOfferedDecline |= s.contains(DECLINE_LABEL);
                }
                if (s.contains("TARGET for Aura Shards")) {
                    optionalAsked = true;
                    optionalOfferedDecline |= s.contains(DECLINE_LABEL);
                }
            }
            System.out.println("AIM-CONTRACT decline: mandatoryAsked=" + mandatoryAsked
                    + " mandatoryOfferedDecline=" + mandatoryOfferedDecline
                    + " optionalAsked=" + optionalAsked
                    + " optionalOfferedDecline=" + optionalOfferedDecline
                    + " bearsAlive=" + bears.isInZone(ZoneType.Battlefield)
                    + " ringAlive=" + ring.isInZone(ZoneType.Battlefield));
            Assert.assertTrue(mandatoryAsked, "the mandatory trigger must be aimed through the seat");
            Assert.assertFalse(mandatoryOfferedDecline,
                    "a MANDATORY trigger's aim window must not offer DECLINE");
            Assert.assertTrue(optionalAsked, "the optional trigger must be aimed through the seat");
            Assert.assertTrue(optionalOfferedDecline,
                    "an OPTIONAL trigger's aim window must offer DECLINE");
            Assert.assertFalse(bears.isInZone(ZoneType.Battlefield),
                    "the mandatory trigger must resolve via stock aiming when the brain 'declines' it");
            Assert.assertTrue(ring.isInZone(ZoneType.Battlefield),
                    "the declined optional trigger must do nothing");
        }
    }

    @Test(timeOut = 240_000)
    public void silentBrainFallsToStockAimingForBothTriggerKinds() throws Exception {
        String prev = System.getProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, "1");
        PrintStream realErr = System.err;
        ByteArrayOutputStream errBuf = new ByteArrayOutputStream();
        System.setErr(new PrintStream(errBuf, true));
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card[] cards = board(k);
            Card bears = cards[1];
            k.startBrain(body -> {
                if (body.contains(CAST)) {
                    return castChupacabra(body);
                }
                if (body.contains(AIM)) {
                    return MailboxTestKit.SILENT; // dead brain at aim time
                }
                return "{\"chosenId\": 0}";
            });
            k.run(() -> !bears.isInZone(ZoneType.Battlefield), 400);

            String err = errBuf.toString();
            long aims = k.seen.stream().filter(s -> s.contains(AIM)).count();
            System.setErr(realErr);
            System.out.println("AIM-CONTRACT silent: aims=" + aims
                    + " bearsAlive=" + bears.isInZone(ZoneType.Battlefield)
                    + " stockFallbacks=" + count(err, "no usable answer at aim")
                    + " declinedAtAim=" + count(err, "declined at aim"));
            Assert.assertTrue(aims >= 2, "both triggers must have asked the seat (saw " + aims + ")");
            Assert.assertFalse(bears.isInZone(ZoneType.Battlefield),
                    "with a silent brain the mandatory trigger must still resolve via stock aiming");
            Assert.assertTrue(err.contains("no usable answer at aim"),
                    "a failed aim exchange must be logged as a stock fallback");
            Assert.assertFalse(err.contains("declined at aim"),
                    "a failed aim exchange must never be recorded as a decline");
        } finally {
            System.setErr(realErr);
            if (prev == null) {
                System.clearProperty(MailboxProtocol.TIMEOUT_PROPERTY);
            } else {
                System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, prev);
            }
        }
    }

    private static int count(String hay, String needle) {
        int n = 0;
        for (int i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, i + 1)) {
            n++;
        }
        return n;
    }
}
