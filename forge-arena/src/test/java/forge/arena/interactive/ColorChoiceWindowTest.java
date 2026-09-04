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
 * more colours are legal and the choice is not a payment-context pick; a
 * silent brain falls to stock. The engine reaches the seat through the
 * PLURAL hook ({@code chooseColors}, used by every ChooseColor effect —
 * review 2026-09-04), so the primary test goes through the engine: two
 * "as it enters, choose a color" cards (Story Circle, Voice of All) moved
 * onto the battlefield, the seat's colour landing on the permanent.
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

    private static String chosen(Card c) {
        Iterable<String> it = c.getChosenColors();
        return it == null || !it.iterator().hasNext() ? null : it.iterator().next();
    }

    @Test(timeOut = 120_000)
    public void enteringPermanentsTakeTheSeatsColour() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            final String[] want = {"green"};
            k.startBrain(body -> body.contains(PURPOSE) ? pick(body, want[0]) : null);
            // through the engine: the ETB replacement's ChooseColor effect
            Card circle = MailboxTestKit.put("Story Circle", k.seat, ZoneType.Hand);
            k.game.getAction().moveToPlay(circle, null, null);
            Assert.assertEquals(windows(k), 1, "one COLOR window for Story Circle");
            Card onField = k.seat.getCardsIn(ZoneType.Battlefield).stream()
                    .filter(c -> c.getName().equals("Story Circle")).findFirst().orElse(null);
            Assert.assertNotNull(onField, "Story Circle entered");
            Assert.assertEquals(chosen(onField), "green", "the seat's colour is the chosen colour");
            String w = k.seen.stream().filter(b -> b.contains(PURPOSE)).findFirst().get();
            Assert.assertTrue(w.contains("Story Circle") && w.contains("\"min\":1") && w.contains("\"max\":1"), w);

            want[0] = "red";
            Card voice = MailboxTestKit.put("Voice of All", k.seat, ZoneType.Hand);
            k.game.getAction().moveToPlay(voice, null, null);
            Assert.assertEquals(windows(k), 2, "one COLOR window for Voice of All");
            Card voiceOn = k.seat.getCardsIn(ZoneType.Battlefield).stream()
                    .filter(c -> c.getName().equals("Voice of All")).findFirst().orElse(null);
            Assert.assertNotNull(voiceOn);
            Assert.assertEquals(chosen(voiceOn), "red");
        }
    }

    @Test(timeOut = 120_000)
    public void directHooksGateOnChoiceAndContext() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            final String[] want = {"green"};
            k.startBrain(body -> body.contains(PURPOSE) ? pick(body, want[0]) : null);
            MailboxController c = k.controller();
            Card voice = MailboxTestKit.put("Voice of All", k.seat, ZoneType.Hand);
            SpellAbility voiceSa = voice.getSpellAbilities().get(0);
            ColorSet all = ColorSet.fromMask(MagicColor.ALL_COLORS);

            Assert.assertEquals(c.chooseColor("Choose a color", voiceSa, all), MagicColor.GREEN);
            Assert.assertEquals(windows(k), 1);

            want[0] = "colorless";
            Assert.assertEquals(c.chooseColorAllowColorless("Choose a color", voice,
                    ColorSet.fromMask(MagicColor.WHITE | MagicColor.BLUE)), MagicColor.COLORLESS);
            Assert.assertEquals(windows(k), 2);

            // one legal colour: no choice, no window
            Assert.assertEquals(c.chooseColor("msg", voiceSa, ColorSet.fromMask(MagicColor.RED)), MagicColor.RED);
            Assert.assertEquals(windows(k), 2, "a single legal colour never asks");

            // a payment-context pick for a NON-mana ability stays on stock
            c.paymentContextForTest(true);
            try {
                Assert.assertTrue(all.hasAnyColor(c.chooseColor("msg", voiceSa, all)), "stock returned a legal colour");
            } finally {
                c.paymentContextForTest(false);
            }
            Assert.assertEquals(windows(k), 2, "payment-context consultations stay on stock");

            // the plural hook with a range: 2 of 5 -> the seat's two colours
            k.startBrain(body -> body.contains(PURPOSE) ? "{\"chosen\": [0, 4]}" : null);
            ColorSet two = c.chooseColors("Choose two colors", voiceSa, 2, 2, all);
            Assert.assertTrue(two.hasWhite() && two.hasGreen() && two.countColors() == 2, two.toString());
        }
    }

    @Test(timeOut = 120_000)
    public void silentBrainFallsToStock() throws Exception {
        String prev = System.getProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, "3");
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            k.startBrain(body -> MailboxTestKit.SILENT);
            Card circle = MailboxTestKit.put("Story Circle", k.seat, ZoneType.Hand);
            k.game.getAction().moveToPlay(circle, null, null);
            Card onField = k.seat.getCardsIn(ZoneType.Battlefield).stream()
                    .filter(c -> c.getName().equals("Story Circle")).findFirst().orElse(null);
            Assert.assertNotNull(onField);
            Assert.assertNotNull(chosen(onField), "stock chose a colour when the brain was silent");
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
