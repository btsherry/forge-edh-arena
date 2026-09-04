package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.card.CounterEnumType;
import forge.game.zone.ZoneType;

/**
 * Wave-3 reachability proofs (adversarial review error-pattern 1: a
 * direct-call test proves an override's LOGIC, never that the engine
 * REACHES it). Each test here drives a real cast/activation through the
 * seat's actual window flow and asserts the RESULTING GAME STATE
 * (error-pattern 2: return values lie; libraries don't).
 *
 * <p>Each method boots its own kit deliberately — these are the bounded
 * per-seam E2E proofs the harness boil kept.
 */
public class CastPathReachabilityTest {

    /** Zone moves in Forge can create a NEW Card instance (see
     *  handlePlayingSpellAbility's {@code sa.setHostCard(moveToStack(...))}),
     *  so a pre-cast reference goes stale the moment the spell is cast —
     *  final state must be looked up by NAME in the final zone. */
    private static Card find(MailboxTestKit k, forge.game.player.Player p,
            ZoneType z, String name) {
        for (Card c : p.getCardsIn(z)) {
            if (name.equals(c.getName())) {
                return c;
            }
        }
        return null;
    }

    /** F1/F5: Buyback is offered as a cast-window VARIANT (no extra window),
     *  and picking it actually buys the spell back. */
    @Test(timeOut = 240_000)
    public void buybackVariantCastsAndReturns() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 6; i++) MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Whispers of the Muse", k.seat, ZoneType.Hand);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Swamp", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    java.util.regex.Matcher m = java.util.regex.Pattern
                            .compile("\\{\"id\":(\\d+),\"label\":\"[^\"]*\\[\\+ Buyback")
                            .matcher(body);
                    if (m.find()) {
                        played[0] = true;
                        return "{\"chosenId\": " + m.group(1) + "}";
                    }
                }
                return null;
            });
            k.run(() -> played[0]
                    && find(k, k.seat, ZoneType.Hand, "Whispers of the Muse") != null, 200);
            boolean sawOptionalWindow = k.seen.stream().anyMatch(s ->
                    s.contains("OPTIONAL COSTS"));
            boolean backInHand = find(k, k.seat, ZoneType.Hand, "Whispers of the Muse") != null;
            boolean inGrave = find(k, k.seat, ZoneType.Graveyard, "Whispers of the Muse") != null;
            System.out.println("REACH-buyback: variantPicked=" + played[0]
                    + " backInHand=" + backInHand + " inGrave=" + inGrave
                    + " spamWindow=" + sawOptionalWindow);
            Assert.assertTrue(played[0], "the [+ Buyback] variant must be OFFERED in the window");
            Assert.assertTrue(backInHand && !inGrave,
                    "buyback must actually return the spell to hand on resolution");
            Assert.assertFalse(sawOptionalWindow,
                    "no separate optional-cost window may ever open (F1)");
        }
    }

    /** F2: a REAL additional-cost discard payment opens exactly one window,
     *  at execution time, and the seat's pick is what gets discarded. */
    @Test(timeOut = 240_000)
    public void additionalCostDiscardIsSeatPaid() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Tormenting Voice", k.seat, ZoneType.Hand);
            Card fodder = MailboxTestKit.put("Swamp", k.seat, ZoneType.Hand);
            Card keep = MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Hand);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Island", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Tormenting Voice");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                if (body.contains("DISCARD PAYMENT")) {
                    String id = MailboxTestKit.idOf(body, "Swamp");
                    return id != null ? "{\"chosen\": [" + id + "]}" : null;
                }
                return null;
            });
            k.run(() -> fodder.isInZone(ZoneType.Graveyard), 200);
            System.out.println("REACH-discardpay: fodderInGy="
                    + fodder.isInZone(ZoneType.Graveyard)
                    + " keepInHand=" + keep.isInZone(ZoneType.Hand));
            Assert.assertTrue(fodder.isInZone(ZoneType.Graveyard),
                    "the seat's named discard payment must be the card discarded");
            Assert.assertTrue(keep.isInZone(ZoneType.Hand),
                    "the high-value card must survive the payment");
        }
    }

    /** F4: the seat's stated order (FIRST = top) must be the order the
     *  LIBRARY actually ends in after Sensei's Top rearranges. */
    @Test(timeOut = 240_000)
    public void topOrderLandsAsStated() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Sensei's Divining Top", k.seat, ZoneType.Battlefield);
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Library);
            MailboxTestKit.put("Forest", k.seat, ZoneType.Library);
            MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Plains", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            final boolean[] ordered = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Sensei's Divining Top");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                if (body.contains("ORDER for your library")) {
                    String a = MailboxTestKit.idOf(body, "Craterhoof Behemoth");
                    String b = MailboxTestKit.idOf(body, "Forest");
                    String c = MailboxTestKit.idOf(body, "Swamp");
                    if (a != null && b != null && c != null) {
                        ordered[0] = true;
                        return "{\"chosen\": [" + a + "," + b + "," + c + "]}";
                    }
                }
                return null;
            });
            k.run(() -> ordered[0] && k.game.getStack().isEmpty(), 200);
            forge.game.card.CardCollectionView lib = k.seat.getCardsIn(ZoneType.Library);
            String top3 = lib.size() >= 3
                    ? lib.get(0).getName() + "," + lib.get(1).getName() + "," + lib.get(2).getName()
                    : "short";
            System.out.println("REACH-toporder: window=" + ordered[0] + " library=[" + top3 + "]");
            Assert.assertTrue(ordered[0], "the ORDER window must open for Top's rearrange");
            Assert.assertEquals(top3, "Craterhoof Behemoth,Forest,Swamp",
                    "FIRST in the seat's answer must physically end on TOP (F4 "
                    + "inversion: pre-fix this read Swamp,Forest,Craterhoof)");
        }
    }

    /** F6 (real surface): Multikicker flows through chooseNumberForKeywordCost
     *  on the AI cast path — the seat's kick count must land as counters. */
    @Test(timeOut = 240_000)
    public void multikickerKicksAsStated() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 5; i++) MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Everflowing Chalice", k.seat, ZoneType.Hand);
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Swamp", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            final boolean[] kicked = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Everflowing Chalice");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                if (body.contains("KEYWORD COST")) {
                    kicked[0] = true;
                    return "{\"chosen\": 2}";
                }
                return null;
            });
            k.run(() -> find(k, k.seat, ZoneType.Battlefield, "Everflowing Chalice") != null, 200);
            Card landed = find(k, k.seat, ZoneType.Battlefield, "Everflowing Chalice");
            int charges = landed != null ? landed.getCounters(CounterEnumType.CHARGE) : -1;
            System.out.println("REACH-multikicker: window=" + kicked[0]
                    + " onBattlefield=" + (landed != null)
                    + " charges=" + charges);
            Assert.assertTrue(kicked[0],
                    "THE LIVE GAP: the kick-count window must reach the seat "
                    + "(stock silently paid greedy-max; pre-wave it paid nothing "
                    + "on some paths and Chalice entered at 0)");
            Assert.assertEquals(charges, 2,
                    "the seat said kick twice — Chalice must enter with 2 charges");
        }
    }

    // ---- BL-11: a second card per seam (group extended) ----------------------

    /** Second Buyback card: Lab Rats — {@code K:Buyback:4} on an untargeted {B}
     *  sorcery, the same keyword line as Whispers of the Muse's
     *  {@code K:Buyback:5}. The variant must be offered, the Rat must be made,
     *  and the card must come back to hand. */
    @Test(groups = "extended", timeOut = 240_000)
    public void buybackVariantCastsAndReturnsLabRats() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 5; i++) MailboxTestKit.put("Swamp", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Lab Rats", k.seat, ZoneType.Hand);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Island", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    java.util.regex.Matcher m = java.util.regex.Pattern
                            .compile("\\{\"id\":(\\d+),\"label\":\"Lab Rats[^\"]*\\[\\+ Buyback")
                            .matcher(body);
                    if (m.find()) {
                        played[0] = true;
                        return "{\"chosenId\": " + m.group(1) + "}";
                    }
                }
                return null;
            });
            k.run(() -> played[0]
                    && find(k, k.seat, ZoneType.Hand, "Lab Rats") != null, 200);
            boolean sawOptionalWindow = k.seen.stream().anyMatch(s -> s.contains("OPTIONAL COSTS"));
            boolean backInHand = find(k, k.seat, ZoneType.Hand, "Lab Rats") != null;
            boolean inGrave = find(k, k.seat, ZoneType.Graveyard, "Lab Rats") != null;
            int rats = 0;
            for (Card c : k.seat.getCardsIn(ZoneType.Battlefield)) {
                if (c.isCreature() && c.isToken()) rats++;
            }
            System.out.println("REACH-buyback-rats: variantPicked=" + played[0]
                    + " backInHand=" + backInHand + " inGrave=" + inGrave + " rats=" + rats
                    + " spamWindow=" + sawOptionalWindow);
            Assert.assertTrue(played[0], "the [+ Buyback] variant must be OFFERED in the window");
            Assert.assertEquals(rats, 1, "the spell must still resolve (one Rat token)");
            Assert.assertTrue(backInHand && !inGrave,
                    "buyback must actually return the spell to hand on resolution");
            Assert.assertFalse(sawOptionalWindow,
                    "no separate optional-cost window may ever open (F1)");
        }
    }

    /** Second additional-cost card: Thrill of Possibility — {@code Cost$ 1 R
     *  Discard<1/Card>} in the spell's own Cost, Tormenting Voice's exact cost
     *  line on an INSTANT. One window, at execution time, seat's pick. */
    @Test(groups = "extended", timeOut = 240_000)
    public void additionalCostDiscardIsSeatPaidThrill() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Thrill of Possibility", k.seat, ZoneType.Hand);
            Card fodder = MailboxTestKit.put("Swamp", k.seat, ZoneType.Hand);
            Card keep = MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Hand);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Island", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Thrill of Possibility");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                if (body.contains("DISCARD PAYMENT")) {
                    String id = MailboxTestKit.idOf(body, "Swamp");
                    return id != null ? "{\"chosen\": [" + id + "]}" : null;
                }
                return null;
            });
            k.run(() -> fodder.isInZone(ZoneType.Graveyard), 200);
            long windows = k.seen.stream().filter(s -> s.contains("DISCARD PAYMENT")).count();
            System.out.println("REACH-discardpay-thrill: fodderInGy="
                    + fodder.isInZone(ZoneType.Graveyard)
                    + " keepInHand=" + keep.isInZone(ZoneType.Hand) + " windows=" + windows);
            Assert.assertTrue(fodder.isInZone(ZoneType.Graveyard),
                    "the seat's named discard payment must be the card discarded");
            Assert.assertTrue(keep.isInZone(ZoneType.Hand),
                    "the high-value card must survive the payment");
            Assert.assertEquals(windows, 1, "exactly one payment window, at execution time");
        }
    }

    /** Second order card: Index — {@code SP$ RearrangeTopOfLibrary | NumCards$
     *  5}, Sensei's Top's exact API as a {U} sorcery over five cards. The seat
     *  states the REVERSE of the current order so neither a no-op nor the
     *  pre-F4 inversion can pass. */
    @Test(groups = "extended", timeOut = 240_000)
    public void topOrderLandsAsStatedIndex() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Index", k.seat, ZoneType.Hand);
            final String[] initial = {"Craterhoof Behemoth", "Forest", "Swamp", "Mountain", "Plains"};
            for (String n : initial) MailboxTestKit.put(n, k.seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Plains", k.opp, ZoneType.Library);
            final String[] stated = {"Plains", "Mountain", "Swamp", "Forest", "Craterhoof Behemoth"};
            final boolean[] played = {false};
            final boolean[] ordered = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Index");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                if (body.contains("ORDER for your library")) {
                    StringBuilder ids = new StringBuilder();
                    for (String n : stated) {
                        String id = MailboxTestKit.idOf(body, n);
                        if (id == null) {
                            return null;
                        }
                        ids.append(ids.length() == 0 ? "" : ",").append(id);
                    }
                    ordered[0] = true;
                    return "{\"chosen\": [" + ids + "]}";
                }
                return null;
            });
            k.run(() -> ordered[0] && k.game.getStack().isEmpty(), 200);
            forge.game.card.CardCollectionView lib = k.seat.getCardsIn(ZoneType.Library);
            StringBuilder top = new StringBuilder();
            for (int i = 0; i < Math.min(5, lib.size()); i++) {
                top.append(i == 0 ? "" : ",").append(lib.get(i).getName());
            }
            System.out.println("REACH-toporder-index: window=" + ordered[0] + " library=[" + top + "]");
            Assert.assertTrue(ordered[0], "the ORDER window must open for Index's rearrange");
            Assert.assertEquals(top.toString(), String.join(",", stated),
                    "FIRST in the seat's answer must physically end on TOP (F4)");
        }
    }

    /** Second Multikicker card: Gnarlid Pack — {@code K:Multikicker:1 G} with
     *  {@code K:etbCounter:P1P1:XKicked}, Everflowing Chalice's exact keyword
     *  pair with a coloured kick on a creature. Two kicks = two +1/+1 counters. */
    @Test(groups = "extended", timeOut = 240_000)
    public void multikickerKicksAsStatedGnarlidPack() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            // {1}{G} + 2 x {1}{G} = 6
            for (int i = 0; i < 6; i++) MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Gnarlid Pack", k.seat, ZoneType.Hand);
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Swamp", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            final boolean[] kicked = {false};
            k.startBrain(body -> {
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Gnarlid Pack");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                if (body.contains("KEYWORD COST")) {
                    kicked[0] = true;
                    return "{\"chosen\": 2}";
                }
                return null;
            });
            k.run(() -> find(k, k.seat, ZoneType.Battlefield, "Gnarlid Pack") != null, 200);
            Card landed = find(k, k.seat, ZoneType.Battlefield, "Gnarlid Pack");
            int counters = landed != null ? landed.getCounters(CounterEnumType.P1P1) : -1;
            System.out.println("REACH-multikicker-gnarlid: window=" + kicked[0]
                    + " onBattlefield=" + (landed != null) + " p1p1=" + counters);
            Assert.assertTrue(kicked[0], "the kick-count window must reach the seat");
            Assert.assertEquals(counters, 2,
                    "the seat said kick twice — Gnarlid Pack must enter with two +1/+1 counters");
        }
    }
}
