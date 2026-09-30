package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.card.MagicColor;
import forge.game.card.Card;
import forge.game.zone.ZoneType;

/** Game 63 (2026-09-25): the human's any-colour auto-pick (mono commander) must yield to the dialog the moment a
 *  permanent outside the commander's colour is controlled — Tergrid handed Ben a white Weathered Wayfarer, he sacrificed
 *  a Treasure for its {W}, and the auto-pick floated black. */
public class OffColorControlTest {

    @Test(timeOut = 120_000)
    public void aStolenOffColourPermanentBringsTheDialogBack() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Swamp", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Gray Merchant of Asphodel", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
            Assert.assertFalse(AdvisorControllerHuman.controlsOffColor(k.seat.getCardsIn(ZoneType.Battlefield), MagicColor.BLACK),
                    "swamps, a black creature and a colourless rock: nothing off-colour, the auto-pick may stand");
            Card wayfarer = MailboxTestKit.put("Weathered Wayfarer", k.seat, ZoneType.Battlefield);
            Assert.assertNotNull(wayfarer);
            Assert.assertTrue(AdvisorControllerHuman.controlsOffColor(k.seat.getCardsIn(ZoneType.Battlefield), MagicColor.BLACK),
                    "a white permanent under his control: the dialog decides the colour");
            Assert.assertFalse(AdvisorControllerHuman.controlsOffColor(k.seat.getCardsIn(ZoneType.Battlefield), (byte) (MagicColor.WHITE | MagicColor.BLACK)),
                    "inside a two-colour identity it would not count");
            Assert.assertFalse(AdvisorControllerHuman.controlsOffColor(null, MagicColor.BLACK));
        }
    }
}
