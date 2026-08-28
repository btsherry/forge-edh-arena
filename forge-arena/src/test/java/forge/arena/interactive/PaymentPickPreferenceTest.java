package forge.arena.interactive;

import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.ai.AiCostDecision;
import forge.game.cost.PaymentDecision;
import forge.game.card.Card;
import forge.game.cost.Cost;
import forge.game.cost.CostDiscard;
import forge.game.cost.CostExile;
import forge.game.cost.CostReturn;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * Wave-2 (dual-audit consensus finding 3): pitch-cost payments are the
 * seat's pick. Drives {@code AiCostDecision.visit(CostExile/Discard/Return)}
 * with a mailbox player and asserts the brain-named card pays — including
 * the exact Force-of-Will shape ({@code ExileFromHand<1/Card.Blue+Other>},
 * where stock's chooseExileFromList sorts by power ascending). The vetting
 * negative proves an illegal pick degrades to stock, never to a bad payment.
 */
public class PaymentPickPreferenceTest {

    private static SpellAbility sa(MailboxTestKit k, String hostName, ZoneType z) {
        Card host = MailboxTestKit.put(hostName, k.seat, z);
        SpellAbility sa = host.getFirstSpellAbility();
        sa.setActivatingPlayer(k.seat);
        return sa;
    }

    @Test(timeOut = 240_000)
    public void forceOfWillPitchIsSeatChosen() throws Exception {
        MailboxTestKit k = new MailboxTestKit(false);
        k.startBrain(body -> {
            if (body.contains("EXILE PAYMENT")) {
                String id = MailboxTestKit.idOf(body, "Brainstorm");
                return id != null ? "{\"chosen\": [" + id + "]}" : null;
            }
            return null;
        });
        SpellAbility fow = sa(k, "Force of Will", ZoneType.Hand);
        MailboxTestKit.put("Brainstorm", k.seat, ZoneType.Hand);
        MailboxTestKit.put("Mana Drain", k.seat, ZoneType.Hand);
        MailboxTestKit.put("Swamp", k.seat, ZoneType.Hand);
        Cost cost = new Cost("ExileFromHand<1/Card.Blue+Other>", false);
        CostExile part = (CostExile) cost.getCostParts().get(0);
        PaymentDecision pd = new AiCostDecision(k.seat, fow, false).visit(part);
        Assert.assertNotNull(pd, "payment must succeed");
        Assert.assertEquals(pd.cards.size(), 1);
        Assert.assertEquals(pd.cards.get(0).getName(), "Brainstorm",
                "the seat spares Mana Drain; stock's power-sort could not know that");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void discardCostIsSeatChosen() throws Exception {
        MailboxTestKit k = new MailboxTestKit(false);
        k.startBrain(body -> {
            if (body.contains("DISCARD PAYMENT")) {
                String id = MailboxTestKit.idOf(body, "Swamp");
                return id != null ? "{\"chosen\": [" + id + "]}" : null;
            }
            return null;
        });
        SpellAbility host = sa(k, "Shock", ZoneType.Hand);
        MailboxTestKit.put("Swamp", k.seat, ZoneType.Hand);
        MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Hand);
        Cost cost = new Cost("Discard<1/Card>", true);
        CostDiscard part = (CostDiscard) cost.getCostParts().get(0);
        PaymentDecision pd = new AiCostDecision(k.seat, host, false).visit(part);
        Assert.assertNotNull(pd);
        Assert.assertEquals(pd.cards.get(0).getName(), "Swamp");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void returnCostIsSeatChosenAndVetted() throws Exception {
        final boolean[] answeredIllegal = {false};
        MailboxTestKit k = new MailboxTestKit(false);
        k.startBrain(body -> {
            if (body.contains("RETURN PAYMENT")) {
                if (!answeredIllegal[0]) {
                    answeredIllegal[0] = true;
                    return "{\"chosen\": [999999]}"; // illegal id → must degrade to stock
                }
                String id = MailboxTestKit.idOf(body, "Grizzly Bears");
                return id != null ? "{\"chosen\": [" + id + "]}" : null;
            }
            return null;
        });
        SpellAbility host = sa(k, "Shock", ZoneType.Hand);
        Card bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        MailboxTestKit.put("Gray Ogre", k.seat, ZoneType.Battlefield);
        MailboxTestKit.put("Swamp", k.seat, ZoneType.Battlefield);
        Cost cost = new Cost("Return<1/Creature>", true);
        CostReturn part = (CostReturn) cost.getCostParts().get(0);

        // 1st payment: illegal answer → stock decides, but NEVER the Swamp
        PaymentDecision pd1 = new AiCostDecision(k.seat, host, false).visit(part);
        Assert.assertNotNull(pd1, "vetting failure must fall to stock, not fail the payment");
        Assert.assertTrue(pd1.cards.get(0).isCreature(),
                "stock fallback still pays with a legal creature");

        // 2nd payment: legal answer → the seat's exact pick
        PaymentDecision pd2 = new AiCostDecision(k.seat, host, false).visit(part);
        Assert.assertEquals(pd2.cards.get(0), bears,
                "Temur-Sabertooth class: WHICH creature bounces is the line");
        k.stopBrain();
    }

    /** Forced payments (valid == amount) answer locally — zero model calls. */
    @Test(timeOut = 240_000)
    public void forcedPaymentNeverOpensAWindow() throws Exception {
        MailboxTestKit k = new MailboxTestKit(false);
        k.startBrain(body -> null);
        SpellAbility host = sa(k, "Shock", ZoneType.Hand);
        Card only = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        Cost cost = new Cost("Return<1/Creature>", true);
        CostReturn part = (CostReturn) cost.getCostParts().get(0);
        PaymentDecision pd = new AiCostDecision(k.seat, host, false).visit(part);
        Assert.assertEquals(pd.cards.get(0), only);
        Assert.assertEquals(k.seen.stream().filter(s2 -> s2.contains("RETURN PAYMENT")).count(),
                0L, "a forced payment must not burn a model call");
        k.stopBrain();
    }

    /** No-hook players keep the stock path byte-identical (contract). */
    @Test(timeOut = 240_000)
    public void stockPlayersAreUntouched() throws Exception {
        MailboxTestKit k = new MailboxTestKit(false);
        Card sh = MailboxTestKit.put("Shock", k.opp, ZoneType.Hand);
        SpellAbility host = sh.getFirstSpellAbility();
        host.setActivatingPlayer(k.opp);
        MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
        MailboxTestKit.put("Gray Ogre", k.opp, ZoneType.Battlefield);
        Cost cost = new Cost("Return<1/Creature>", true);
        CostReturn part = (CostReturn) cost.getCostParts().get(0);
        PaymentDecision pd = new AiCostDecision(k.opp, host, false).visit(part);
        Assert.assertNotNull(pd, "stock AI still pays exactly as before the hook");
        List<String> hooks = k.seen;
        Assert.assertTrue(hooks.isEmpty(), "no mailbox traffic for a stock player");
    }
}
