package forge.arena.interactive;

import java.util.ArrayList;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.GameEntity;
import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.card.CardCollectionView;
import forge.game.cost.Cost;
import forge.game.spellability.OptionalCost;
import forge.game.spellability.OptionalCostValue;
import forge.game.spellability.SpellAbility;
import forge.game.spellability.TargetChoices;
import forge.game.zone.ZoneType;
import forge.util.collect.FCollection;

/**
 * Wave-2 seat-owned surfaces (2026-08-28 dual audit, note 52), direct-call
 * style on the shared {@link MailboxTestKit}: each test drives ONE new
 * override through the mailbox with a scripted brain and asserts the seat's
 * pick — not stock's — is what the engine receives. Sacrifice-style
 * anti-stock picks are used wherever stock has a known heuristic.
 */
public class SeatWaveSurfacesTest {

    private MailboxTestKit kit;

    private MailboxTestKit kit(java.util.function.Function<String, String> responder)
            throws Exception {
        kit = new MailboxTestKit(false);
        kit.startBrain(responder);
        return kit;
    }

    @Test(timeOut = 240_000)
    public void cleanupDiscardIsSeatChosen() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("DISCARD to maximum hand size")) {
                String a = MailboxTestKit.idOf(body, "Colossal Dreadmaw");
                String b = MailboxTestKit.idOf(body, "Craterhoof Behemoth");
                return a != null && b != null ? "{\"chosen\": [" + a + "," + b + "]}" : null;
            }
            return null;
        });
        for (String n : new String[]{"Colossal Dreadmaw", "Craterhoof Behemoth",
                "Llanowar Elves", "Forest", "Swamp"}) {
            MailboxTestKit.put(n, k.seat, ZoneType.Hand);
        }
        CardCollectionView picked = k.controller().chooseCardsToDiscardToMaximumHandSize(2);
        List<String> names = names(picked);
        System.out.println("WAVE-cleanup: " + names);
        Assert.assertTrue(names.contains("Colossal Dreadmaw")
                && names.contains("Craterhoof Behemoth") && picked.size() == 2,
                "cleanup discard must be the seat's anti-stock pick (big cards)");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void mulliganBottomIsSeatChosen() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("BOTTOM for London mulligan")) {
                String a = MailboxTestKit.idOf(body, "Forest");
                return a != null ? "{\"chosen\": [" + a + "]}" : null;
            }
            return null;
        });
        CardCollection hand = new CardCollection();
        for (String n : new String[]{"Forest", "Llanowar Elves", "Craterhoof Behemoth"}) {
            hand.add(MailboxTestKit.put(n, k.seat, ZoneType.Hand));
        }
        CardCollectionView picked = k.controller().tuckCardsViaMulligan(hand, 1);
        System.out.println("WAVE-mullbottom: " + names(picked));
        Assert.assertEquals(picked.size(), 1);
        Assert.assertEquals(picked.get(0).getName(), "Forest",
                "the seat named the Forest to bottom; stock's max-CMC rule would "
                + "have bottomed Craterhoof");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void scryBottomIsSeatChosen() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("SCRY")) {
                String a = MailboxTestKit.idOf(body, "Swamp");
                return a != null ? "{\"chosen\": [" + a + "]}" : null;
            }
            return null;
        });
        CardCollection top = new CardCollection();
        for (String n : new String[]{"Craterhoof Behemoth", "Swamp", "Forest"}) {
            top.add(MailboxTestKit.put(n, k.seat, ZoneType.Library));
        }
        org.apache.commons.lang3.tuple.ImmutablePair<CardCollection, CardCollection> pair =
                k.controller().arrangeForScry(top);
        System.out.println("WAVE-scry: top=" + names(pair.getLeft())
                + " bottom=" + names(pair.getRight()));
        Assert.assertEquals(names(pair.getRight()), List.of("Swamp"));
        Assert.assertEquals(names(pair.getLeft()), List.of("Craterhoof Behemoth", "Forest"),
                "kept cards stay on top in shown order");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void surveilGraveIsSeatChosen() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("SURVEIL")) {
                String a = MailboxTestKit.idOf(body, "Craterhoof Behemoth");
                return a != null ? "{\"chosen\": [" + a + "]}" : null;
            }
            return null;
        });
        CardCollection top = new CardCollection();
        for (String n : new String[]{"Craterhoof Behemoth", "Forest"}) {
            top.add(MailboxTestKit.put(n, k.seat, ZoneType.Library));
        }
        org.apache.commons.lang3.tuple.ImmutablePair<CardCollection, CardCollection> pair =
                k.controller().arrangeForSurveil(top);
        System.out.println("WAVE-surveil: top=" + names(pair.getLeft())
                + " grave=" + names(pair.getRight()));
        Assert.assertEquals(names(pair.getRight()), List.of("Craterhoof Behemoth"),
                "a reanimator-style self-mill is exactly what stock's scry logic never does");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void libraryOrderIsSeatOrder() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("ORDER for your library")) {
                String a = MailboxTestKit.idOf(body, "Swamp");
                String b = MailboxTestKit.idOf(body, "Craterhoof Behemoth");
                String c = MailboxTestKit.idOf(body, "Forest");
                return a != null && b != null && c != null
                        ? "{\"chosen\": [" + a + "," + b + "," + c + "]}" : null;
            }
            return null;
        });
        CardCollection cards = new CardCollection();
        for (String n : new String[]{"Craterhoof Behemoth", "Forest", "Swamp"}) {
            cards.add(MailboxTestKit.put(n, k.seat, ZoneType.Hand));
        }
        CardCollectionView ordered =
                k.controller().orderMoveToZoneList(cards, ZoneType.Library, null);
        System.out.println("WAVE-order: " + names(ordered));
        Assert.assertEquals(names(ordered), List.of("Swamp", "Craterhoof Behemoth", "Forest"),
                "answer order must be preserved verbatim (first = top)");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void clashTopIsSeatConfirmed() throws Exception {
        MailboxTestKit k = kit(body ->
                body.contains("TOP OR BOTTOM") ? "{\"chosenId\": 1}" : null);
        Card c = MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Library);
        Assert.assertTrue(k.controller().willPutCardOnTop(c),
                "seat said yes; must land on top");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void genericNumberAndValueListAreSeatChosen() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("CHOOSE A NUMBER")) {
                return "{\"chosen\": 7}";
            }
            if (body.contains("CHOOSE A VALUE")) {
                return "{\"chosen\": [1]}";
            }
            return null;
        });
        Card host = MailboxTestKit.put("Shock", k.seat, ZoneType.Hand);
        SpellAbility sa = host.getFirstSpellAbility();
        Assert.assertEquals(k.controller().chooseNumber(sa, "secretly choose", 0, 20), 7,
                "Wheel-of-Misfortune-class number is the seat's");
        Assert.assertEquals(k.controller().chooseNumber(sa, "pick", List.of(2, 5, 9), null), 5);
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void announceNonManaVarIsSeatChosen() throws Exception {
        MailboxTestKit k = kit(body ->
                body.contains("ANNOUNCE Multikicker") ? "{\"chosen\": 3}" : null);
        Card host = MailboxTestKit.put("Shock", k.seat, ZoneType.Hand);
        SpellAbility sa = host.getFirstSpellAbility();
        Assert.assertEquals(k.controller().announceRequirements(sa, 0, 5, "Multikicker"),
                Integer.valueOf(3), "note 15b's sibling: non-X announces reach the seat");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void redirectIsSeatAimed() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("Choose the TARGET for Shock")) {
                String id = MailboxTestKit.idOf(body, "Gray Ogre");
                return id != null ? "{\"chosenId\": " + id + "}" : null;
            }
            return null;
        });
        Card bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        Card ogre = MailboxTestKit.put("Gray Ogre", k.opp, ZoneType.Battlefield);
        Card shock = MailboxTestKit.put("Shock", k.opp, ZoneType.Hand);
        SpellAbility sa = shock.getFirstSpellAbility();
        sa.setActivatingPlayer(k.opp);
        sa.getTargets().add(bears);
        TargetChoices next = k.controller().chooseNewTargetsFor(sa, null, false);
        System.out.println("WAVE-redirect: newTarget="
                + (sa.getTargetCard() != null ? sa.getTargetCard().getName() : "null"));
        Assert.assertNotNull(next, "THE LIVE GAP: stock returns null and the "
                + "redirect silently no-ops");
        Assert.assertEquals(sa.getTargetCard(), ogre,
                "the changing SA must now aim at the seat's pick");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void optionalCostsAreSeatChosen() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("OPTIONAL COSTS")) {
                return "{\"chosen\": [0]}"; // pay the Buyback
            }
            return null;
        });
        Card host = MailboxTestKit.put("Shock", k.seat, ZoneType.Hand);
        SpellAbility sa = host.getFirstSpellAbility();
        List<OptionalCostValue> offers = new ArrayList<>();
        offers.add(new OptionalCostValue(OptionalCost.Buyback, new Cost("3", false)));
        List<OptionalCostValue> chosen = k.controller().chooseOptionalCosts(sa, offers);
        Assert.assertEquals(chosen.size(), 1);
        Assert.assertEquals(chosen.get(0).getType(), OptionalCost.Buyback,
                "the Reiterate loop's Buyback is the seat's call, not a heuristic's");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void protectionVoteAndPileAreSeatChosen() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("PROTECTION")) {
                return "{\"chosen\": [2]}";
            }
            if (body.contains("VOTE")) {
                return "{\"chosen\": [1]}";
            }
            if (body.contains("CHOOSE A PILE")) {
                return "{\"chosen\": [1]}";
            }
            return null;
        });
        Card host = MailboxTestKit.put("Shock", k.seat, ZoneType.Hand);
        SpellAbility sa = host.getFirstSpellAbility();
        Assert.assertEquals(k.controller().chooseProtectionType(sa,
                List.of("green", "white", "blue")), "blue",
                "Mother-of-Runes color is the seat's read of the stack");
        Assert.assertEquals(k.controller().vote(sa, "feather or bone?",
                List.of((Object) "feather", (Object) "bone"),
                com.google.common.collect.ArrayListMultimap.create(), k.seat, false),
                "bone");
        CardCollection p1 = new CardCollection(
                MailboxTestKit.put("Forest", k.seat, ZoneType.Library));
        CardCollection p2 = new CardCollection(
                MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Library));
        Assert.assertFalse(k.controller().chooseCardsPile(sa, p1, p2, "False"),
                "seat took pile 2 (the good pile stock's size-comparison skips)");
        // Hidden-pile fairness (review catch): with FaceDown=One, pile 1's
        // CONTENTS must not appear in the request — only its count.
        boolean leaked = k.seen.stream().anyMatch(b -> b.contains("CHOOSE A PILE")
                && b.contains("Pile 1: Forest"));
        boolean counted = k.seen.stream().anyMatch(b -> b.contains("CHOOSE A PILE")
                && b.contains("face-down card"));
        k.controller().chooseCardsPile(sa, p1, p2, "One");
        leaked |= k.seen.stream().anyMatch(b -> b.contains("CHOOSE A PILE")
                && b.contains("Pile 1: Forest") && b.contains("face-down"));
        boolean oneHidden = k.seen.stream().anyMatch(b -> b.contains("CHOOSE A PILE")
                && b.contains("Pile 1: 1 face-down card")
                && b.contains("Pile 2: Craterhoof Behemoth"));
        Assert.assertTrue(oneHidden && !counted,
                "FaceDown=One: pile 1 hidden (count only), pile 2 visible");
        k.stopBrain();
    }

    @Test(timeOut = 240_000)
    public void mixedCardPlayerChoiceReachesSeat() throws Exception {
        MailboxTestKit k = kit(body -> {
            if (body.contains("drain target")) {
                String id = MailboxTestKit.idOf(body, "opp");
                return id != null ? "{\"chosenId\": " + id + "}" : null;
            }
            return null;
        });
        Card bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        FCollection<GameEntity> opts = new FCollection<>();
        opts.add(bears);
        opts.add(k.opp);
        GameEntity picked = k.controller().chooseSingleEntityForEffect(
                opts, null, null, "drain target", false, null, null);
        Assert.assertEquals(picked, k.opp,
                "a creature-or-player choice must reach the seat (old allCards "
                + "gate silently fell to stock)");
        k.stopBrain();
    }

    private static List<String> names(Iterable<Card> cards) {
        List<String> out = new ArrayList<>();
        if (cards != null) {
            for (Card c : cards) {
                out.add(c.getName());
            }
        }
        return out;
    }
}
