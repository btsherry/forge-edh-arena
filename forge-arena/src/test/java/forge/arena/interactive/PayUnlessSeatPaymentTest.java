package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.cost.Cost;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * Interactive plan item 11b: when the brain says "pay" to a pay-or-else
 * cost, WHICH permanent or card pays is the seat's choice too. The payment
 * ran outside the controller's payment context, so the sacrifice/discard
 * hooks answered null and stock heuristics picked. Two cost kinds
 * (sacrifice a creature; discard a card), two different payers.
 */
public class PayUnlessSeatPaymentTest {

    private static final String PAY = "\"decisionType\":\"PAY_UNLESS\"";
    private static final String PICK = "\"decisionType\":\"CHOOSE_ENTITIES\"";

    @Test(timeOut = 120_000)
    public void sacrificeUnlessPaymentIsSeatChosen() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            Card elves = MailboxTestKit.put("Llanowar Elves", k.seat, ZoneType.Battlefield);
            Card src = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Hand);
            SpellAbility sa = src.getSpellAbilities().get(0);
            sa.setActivatingPlayer(k.opp);
            k.startBrain(body -> {
                if (body.contains(PAY)) {
                    return "{\"chosenId\": 1}";
                }
                if (body.contains(PICK) && body.contains("SACRIFICE PAYMENT")) {
                    return "{\"chosen\": [" + elves.getId() + "]}";
                }
                return "{\"chosenId\": 0}";
            });
            boolean paid = k.controller().payCostToPreventEffect(
                    new Cost("Sac<1/Creature>", false), sa, false, null);
            k.stopBrain();

            Assert.assertTrue(paid, "the seat chose to pay");
            Assert.assertTrue(k.seen.stream().anyMatch(s -> s.contains(PICK) && s.contains("SACRIFICE PAYMENT")),
                    "the sacrifice payment must be offered to the seat (payment context was open)");
            Assert.assertTrue(elves.isInZone(ZoneType.Graveyard), "the seat's pick paid");
            Assert.assertTrue(bears.isInZone(ZoneType.Battlefield), "the other creature stayed");
        }
    }

    @Test(timeOut = 120_000)
    public void discardUnlessPaymentIsSeatChosen() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card keep = MailboxTestKit.put("Counterspell", k.seat, ZoneType.Hand);
            Card toss = MailboxTestKit.put("Island", k.seat, ZoneType.Hand);
            Card src = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Hand);
            SpellAbility sa = src.getSpellAbilities().get(0);
            sa.setActivatingPlayer(k.opp);
            k.startBrain(body -> {
                if (body.contains(PAY)) {
                    return "{\"chosenId\": 1}";
                }
                if (body.contains(PICK) && body.contains("DISCARD PAYMENT")) {
                    return "{\"chosen\": [" + toss.getId() + "]}";
                }
                return "{\"chosenId\": 0}";
            });
            boolean paid = k.controller().payCostToPreventEffect(
                    new Cost("Discard<1/Card>", false), sa, false, null);
            k.stopBrain();

            Assert.assertTrue(paid, "the seat chose to pay");
            Assert.assertTrue(k.seen.stream().anyMatch(s -> s.contains(PICK) && s.contains("DISCARD PAYMENT")),
                    "the discard payment must be offered to the seat");
            Assert.assertTrue(toss.isInZone(ZoneType.Graveyard), "the seat's pick was discarded");
            Assert.assertTrue(keep.isInZone(ZoneType.Hand), "the spell stayed in hand");
        }
    }
}
