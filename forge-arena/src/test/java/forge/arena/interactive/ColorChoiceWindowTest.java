package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.card.ColorSet;
import forge.card.MagicColor;
import forge.game.card.Card;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * BL-03 (2026-09-04): a colour choice reaches the seat as a one-pick
 * {@code CHOOSE_MODE} window ({@code state.purpose = "COLOR"}) when two or
 * more colours are legal and the choice is NOT inside a payment context;
 * payment-context and single-colour consultations stay on stock, and a silent
 * brain falls to stock. Two colour-choosing cards (Voice of All, Story Circle),
 * direct calls on the controller, one kit.
 */
public class ColorChoiceWindowTest {

    private static final String PURPOSE = "\"purpose\":\"COLOR\"";

    private static String pick(String body, String colorName) {
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile("\\{\"id\":(\\d+),\"label\":\"" + colorName + "\"").matcher(body);
        Assert.assertTrue(m.find(), colorName + " offered in: " + body);
        return "{\"chosen\": [" + m.group(1) + "]}";
    }

    private static long windows(MailboxTestKit k) {
        return k.seen.stream().filter(b -> b.contains(PURPOSE)).count();
    }

    @Test(timeOut = 120_000)
    public void seatPicksTheColourOutsidePayment() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            final String[] want = {"green"};
            k.startBrain(body -> body.contains(PURPOSE) ? pick(body, want[0]) : null);
            MailboxController c = k.controller();
            Card voice = MailboxTestKit.put("Voice of All", k.seat, ZoneType.Hand);
            Card circle = MailboxTestKit.put("Story Circle", k.seat, ZoneType.Hand);
            SpellAbility voiceSa = voice.getSpellAbilities().get(0);
            ColorSet all = ColorSet.fromMask(MagicColor.ALL_COLORS);

            byte got = c.chooseColor("Choose a color for protection", voiceSa, all);
            Assert.assertEquals(got, MagicColor.GREEN, "the seat's colour is returned");
            Assert.assertEquals(windows(k), 1);
            String w = k.seen.stream().filter(b -> b.contains(PURPOSE)).findFirst().get();
            Assert.assertTrue(w.contains("Voice of All"), "prompt names the source: " + w);
            Assert.assertTrue(w.contains("\"min\":1") && w.contains("\"max\":1"));

            // colorless allowed: the option exists and can be chosen
            want[0] = "colorless";
            byte none = c.chooseColorAllowColorless("Choose a color", circle,
                    ColorSet.fromMask(MagicColor.WHITE | MagicColor.BLUE));
            Assert.assertEquals(none, MagicColor.COLORLESS);
            Assert.assertEquals(windows(k), 2);

            // one legal colour: no choice, no window
            byte only = c.chooseColor("msg", voiceSa, ColorSet.fromMask(MagicColor.RED));
            Assert.assertEquals(only, MagicColor.RED);
            Assert.assertEquals(windows(k), 2, "a single legal colour never asks");

            // inside a payment context: stock decides, no window
            c.paymentContextForTest(true);
            try {
                byte paid = c.chooseColor("msg", voiceSa, all);
                Assert.assertTrue(all.hasAnyColor(paid), "stock returned a legal colour");
            } finally {
                c.paymentContextForTest(false);
            }
            Assert.assertEquals(windows(k), 2, "payment-context consultations stay on stock");
        }
    }

    @Test(timeOut = 120_000)
    public void silentBrainFallsToStock() throws Exception {
        String prev = System.getProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, "3");
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            k.startBrain(body -> MailboxTestKit.SILENT);
            Card circle = MailboxTestKit.put("Story Circle", k.seat, ZoneType.Hand);
            ColorSet all = ColorSet.fromMask(MagicColor.ALL_COLORS);
            byte got = k.controller().chooseColor("msg", circle.getSpellAbilities().get(0), all);
            Assert.assertTrue(all.hasAnyColor(got), "stock's pick is legal");
            Assert.assertEquals(windows(k), 1, "the window was opened, then timed out to stock");
        } finally {
            if (prev == null) {
                System.clearProperty(MailboxProtocol.TIMEOUT_PROPERTY);
            } else {
                System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, prev);
            }
        }
    }
}
