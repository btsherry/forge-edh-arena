package forge.arena.interactive;


import org.testng.Assert;
import org.testng.annotations.AfterClass;
import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.ai.AiCostDecision;
import forge.game.cost.PaymentDecision;
import forge.game.card.Card;
import forge.game.cost.CostPart;
import forge.game.cost.CostTapType;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * BL-46 (games 22 and 38): a "tap an untapped artifact you control" payment
 * with more candidates than the cost needs is the seat's choice through
 * {@link forge.ai.TapCostPreference}; a forced payment opens no window.
 */
public class TapPaymentSeatChoiceTest {
    private static MailboxTestKit k;

    @BeforeClass
    public static void boot() throws Exception {
        k = new MailboxTestKit(false);
        k.controller().paymentContextForTest(true);
        k.startBrain(body -> {
            if (body.contains("TAP PAYMENT")) {
                String id = MailboxTestKit.idOf(body, "Winter Orb");
                return id != null ? "{\"chosen\": [" + id + "]}" : null;
            }
            return null;
        });
    }

    @AfterClass
    public static void shutdown() {
        if (k != null) {
            k.close();
        }
    }

    private static SpellAbility urzaTapAbility(Card urza) {
        for (SpellAbility sa : urza.getManaAbilities()) {
            if (sa.getPayCosts() != null) {
                for (CostPart p : sa.getPayCosts().getCostParts()) {
                    if (p instanceof CostTapType) {
                        sa.setActivatingPlayer(k.seat);
                        return sa;
                    }
                }
            }
        }
        throw new AssertionError("Urza's tap-an-artifact mana ability not found: " + urza.getManaAbilities());
    }

    private static CostTapType tapPart(SpellAbility sa) {
        for (CostPart p : sa.getPayCosts().getCostParts()) {
            if (p instanceof CostTapType) {
                return (CostTapType) p;
            }
        }
        throw new AssertionError("no CostTapType on " + sa);
    }

    @Test(timeOut = 240_000)
    public void theSeatPicksWhichArtifactPaysAndAForcedPaymentOpensNoWindow() throws Exception {
        Card urza = MailboxTestKit.put("Urza, Lord High Artificer", k.seat, ZoneType.Battlefield);
        Card solRing = MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
        Card orb = MailboxTestKit.put("Winter Orb", k.seat, ZoneType.Battlefield);
        SpellAbility mana = urzaTapAbility(urza);
        int seenBefore = k.seen.size();
        PaymentDecision pd = new AiCostDecision(k.seat, mana, false).visit(tapPart(mana));
        Assert.assertNotNull(pd, "payment must succeed");
        Assert.assertEquals(pd.cards.size(), 1);
        Assert.assertEquals(pd.cards.get(0).getName(), "Winter Orb", "the seat's pick pays, not stock's");
        Assert.assertTrue(k.seen.stream().skip(seenBefore).anyMatch(b -> b.contains("TAP PAYMENT")),
                "a TAP PAYMENT window reached the seat");
        // forced: only one untapped candidate left -> no window, stock-identical result
        orb.setTapped(true);
        int seenMid = k.seen.size();
        PaymentDecision forced = new AiCostDecision(k.seat, mana, false).visit(tapPart(mana));
        Assert.assertNotNull(forced);
        Assert.assertEquals(forced.cards.get(0).getName(), "Sol Ring");
        Assert.assertFalse(k.seen.stream().skip(seenMid).anyMatch(b -> b.contains("TAP PAYMENT")),
                "forced payment: no window");
        Assert.assertNotNull(solRing);
    }
}
