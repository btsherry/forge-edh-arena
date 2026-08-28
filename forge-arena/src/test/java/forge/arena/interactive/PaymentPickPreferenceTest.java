package forge.arena.interactive;

import java.util.ArrayList;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.AfterClass;
import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.ai.AiCostDecision;
import forge.game.card.Card;
import forge.game.cost.Cost;
import forge.game.cost.CostDiscard;
import forge.game.cost.CostExile;
import forge.game.cost.CostReturn;
import forge.game.cost.PaymentDecision;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * Wave-2 (dual-audit consensus finding 3): pitch-cost payments are the
 * seat's pick — including the exact Force-of-Will shape
 * ({@code ExileFromHand<1/Card.Blue+Other>}, where stock's
 * chooseExileFromList sorts by power ascending). The vetting negative
 * proves an illegal pick degrades to stock, never to a bad payment.
 *
 * <p>Harness boil: ONE shared kit (cost visits are direct calls). The two
 * battlefield-sensitive RETURN tests reset the seat's creatures first, so
 * methods stay order-independent.
 */
public class PaymentPickPreferenceTest {

    private static MailboxTestKit k;
    private static final int[] RETURN_CALLS = {0};

    @BeforeClass
    public static void boot() throws Exception {
        k = new MailboxTestKit(false);
        k.startBrain(body -> {
            if (body.contains("EXILE PAYMENT")) {
                String id = MailboxTestKit.idOf(body, "Brainstorm");
                return id != null ? "{\"chosen\": [" + id + "]}" : null;
            }
            if (body.contains("DISCARD PAYMENT")) {
                String id = MailboxTestKit.idOf(body, "Swamp");
                return id != null ? "{\"chosen\": [" + id + "]}" : null;
            }
            if (body.contains("RETURN PAYMENT")) {
                RETURN_CALLS[0]++;
                if (RETURN_CALLS[0] == 1) {
                    return "{\"chosen\": [999999]}"; // illegal id → must degrade to stock
                }
                String id = MailboxTestKit.idOf(body, "Grizzly Bears");
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

    private static SpellAbility sa(String hostName, ZoneType z) {
        Card host = MailboxTestKit.put(hostName, k.seat, z);
        SpellAbility sa = host.getFirstSpellAbility();
        sa.setActivatingPlayer(k.seat);
        return sa;
    }

    /** Remove every creature the seat controls (RETURN tests own the board). */
    private static void clearSeatCreatures() {
        List<Card> bf = new ArrayList<>(k.seat.getCardsIn(ZoneType.Battlefield));
        for (Card c : bf) {
            if (c.isCreature()) {
                k.seat.getZone(ZoneType.Battlefield).remove(c);
            }
        }
    }

    @Test(timeOut = 240_000)
    public void forceOfWillPitchIsSeatChosen() throws Exception {
        SpellAbility fow = sa("Force of Will", ZoneType.Hand);
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
    }

    @Test(timeOut = 240_000)
    public void discardCostIsSeatChosen() throws Exception {
        SpellAbility host = sa("Shock", ZoneType.Hand);
        MailboxTestKit.put("Swamp", k.seat, ZoneType.Hand);
        MailboxTestKit.put("Ghalta, Primal Hunger", k.seat, ZoneType.Hand);
        Cost cost = new Cost("Discard<1/Card>", true);
        CostDiscard part = (CostDiscard) cost.getCostParts().get(0);
        PaymentDecision pd = new AiCostDecision(k.seat, host, false).visit(part);
        Assert.assertNotNull(pd);
        Assert.assertEquals(pd.cards.get(0).getName(), "Swamp");
    }

    @Test(timeOut = 240_000)
    public void returnCostIsSeatChosenAndVetted() throws Exception {
        clearSeatCreatures();
        RETURN_CALLS[0] = 0;
        SpellAbility host = sa("Shock", ZoneType.Hand);
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
    }

    /** Forced payments (valid == amount) answer locally — zero model calls. */
    @Test(timeOut = 240_000)
    public void forcedPaymentNeverOpensAWindow() throws Exception {
        clearSeatCreatures();
        SpellAbility host = sa("Shock", ZoneType.Hand);
        Card only = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        Cost cost = new Cost("Return<1/Creature>", true);
        CostReturn part = (CostReturn) cost.getCostParts().get(0);
        long before = k.seen.stream().filter(s2 -> s2.contains("RETURN PAYMENT")).count();
        PaymentDecision pd = new AiCostDecision(k.seat, host, false).visit(part);
        long after = k.seen.stream().filter(s2 -> s2.contains("RETURN PAYMENT")).count();
        Assert.assertEquals(pd.cards.get(0), only);
        Assert.assertEquals(after, before, "a forced payment must not burn a model call");
    }

    /** No-hook players keep the stock path byte-identical (contract). */
    @Test(timeOut = 240_000)
    public void stockPlayersAreUntouched() throws Exception {
        Card sh = MailboxTestKit.put("Shock", k.opp, ZoneType.Hand);
        SpellAbility host = sh.getFirstSpellAbility();
        host.setActivatingPlayer(k.opp);
        MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
        MailboxTestKit.put("Gray Ogre", k.opp, ZoneType.Battlefield);
        Cost cost = new Cost("Return<1/Creature>", true);
        CostReturn part = (CostReturn) cost.getCostParts().get(0);
        long before = k.seen.size();
        PaymentDecision pd = new AiCostDecision(k.opp, host, false).visit(part);
        Assert.assertNotNull(pd, "stock AI still pays exactly as before the hook");
        Assert.assertEquals(k.seen.size(), before, "no mailbox traffic for a stock player");
    }
}
