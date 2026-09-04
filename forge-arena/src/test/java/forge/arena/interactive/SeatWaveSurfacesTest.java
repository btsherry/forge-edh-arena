package forge.arena.interactive;

import java.util.ArrayList;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.AfterClass;
import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.game.GameEntity;
import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.card.CardCollectionView;
import forge.game.spellability.SpellAbility;
import forge.game.spellability.TargetChoices;
import forge.game.zone.ZoneType;
import forge.util.collect.FCollection;

/**
 * Wave-2 seat-owned surfaces (2026-08-28 dual audit, note 52), direct-call
 * style: each test drives ONE override through the mailbox with a scripted
 * brain and asserts the seat's pick — not stock's — is what the engine
 * receives.
 *
 * <p>Harness boil (same day): ONE shared kit serves every method — direct
 * calls never advance the game, so twelve separate boots bought nothing.
 * Order-independence rule: each test uses card names no other test's
 * responder branch matches on, so methods can run in any order.
 */
public class SeatWaveSurfacesTest {

    private static MailboxTestKit k;

    @BeforeClass
    public static void boot() throws Exception {
        k = new MailboxTestKit(false);
        k.startBrain(SeatWaveSurfacesTest::respond);
    }

    @AfterClass
    public static void shutdown() {
        if (k != null) {
            k.close();
        }
    }

    /** Composite responder — branches are disjoint by prompt text. */
    private static String respond(String body) {
        if (body.contains("DISCARD to maximum hand size")) {
            String a = MailboxTestKit.idOf(body, "Colossal Dreadmaw");
            String b = MailboxTestKit.idOf(body, "Craterhoof Behemoth");
            return a != null && b != null ? "{\"chosen\": [" + a + "," + b + "]}" : null;
        }
        if (body.contains("BOTTOM for London mulligan")) {
            String a = MailboxTestKit.idOf(body, "Snow-Covered Forest");
            return a != null ? "{\"chosen\": [" + a + "]}" : null;
        }
        if (body.contains("SCRY")) {
            String a = MailboxTestKit.idOf(body, "Mountain");
            return a != null ? "{\"chosen\": [" + a + "]}" : null;
        }
        if (body.contains("SURVEIL")) {
            String a = MailboxTestKit.idOf(body, "Air Elemental");
            return a != null ? "{\"chosen\": [" + a + "]}" : null;
        }
        if (body.contains("ORDER for your library")) {
            String a = MailboxTestKit.idOf(body, "Wall of Wood");
            String b = MailboxTestKit.idOf(body, "Pearled Unicorn");
            String c = MailboxTestKit.idOf(body, "Scathe Zombies");
            return a != null && b != null && c != null
                    ? "{\"chosen\": [" + a + "," + b + "," + c + "]}" : null;
        }
        if (body.contains("TOP OR BOTTOM")) {
            return "{\"chosenId\": 1}";
        }
        if (body.contains("CHOOSE A NUMBER")) {
            return "{\"chosen\": 7}";
        }
        if (body.contains("CHOOSE A VALUE")) {
            return "{\"chosen\": [1]}";
        }
        if (body.contains("ANNOUNCE Multikicker")) {
            return "{\"chosen\": 3}";
        }
        if (body.contains("Choose the TARGET for Shock")) {
            String id = MailboxTestKit.idOf(body, "Gray Ogre");
            return id != null ? "{\"chosenId\": " + id + "}" : null;
        }
        if (body.contains("PROTECTION")) {
            return "{\"chosen\": [2]}";
        }
        if (body.contains("VOTE")) {
            return "{\"chosen\": [1]}";
        }
        if (body.contains("CHOOSE A PILE")) {
            return "{\"chosen\": [1]}";
        }
        if (body.contains("drain target")) {
            String id = MailboxTestKit.idOf(body, "opp");
            return id != null ? "{\"chosenId\": " + id + "}" : null;
        }
        return null;
    }

    @Test(timeOut = 240_000)
    public void cleanupDiscardIsSeatChosen() throws Exception {
        for (String n : new String[]{"Colossal Dreadmaw", "Craterhoof Behemoth",
                "Llanowar Elves", "Forest", "Swamp"}) {
            MailboxTestKit.put(n, k.seat, ZoneType.Hand);
        }
        CardCollectionView picked = k.controller().chooseCardsToDiscardToMaximumHandSize(2);
        List<String> names = names(picked);
        Assert.assertTrue(names.contains("Colossal Dreadmaw")
                && names.contains("Craterhoof Behemoth") && picked.size() == 2,
                "cleanup discard must be the seat's anti-stock pick (big cards)");
    }

    @Test(timeOut = 240_000)
    public void mulliganBottomIsSeatChosen() throws Exception {
        CardCollection hand = new CardCollection();
        for (String n : new String[]{"Snow-Covered Forest", "Elvish Mystic",
                "Ghalta, Primal Hunger"}) {
            hand.add(MailboxTestKit.put(n, k.seat, ZoneType.Hand));
        }
        CardCollectionView picked = k.controller().tuckCardsViaMulligan(hand, 1);
        Assert.assertEquals(picked.size(), 1);
        Assert.assertEquals(picked.get(0).getName(), "Snow-Covered Forest",
                "the seat named the land to bottom; stock's max-CMC rule would "
                + "have bottomed Ghalta");
    }

    @Test(timeOut = 240_000)
    public void scryBottomIsSeatChosen() throws Exception {
        CardCollection top = new CardCollection();
        for (String n : new String[]{"Serra Angel", "Mountain", "Shivan Dragon"}) {
            top.add(MailboxTestKit.put(n, k.seat, ZoneType.Library));
        }
        org.apache.commons.lang3.tuple.ImmutablePair<CardCollection, CardCollection> pair =
                k.controller().arrangeForScry(top);
        Assert.assertEquals(names(pair.getRight()), List.of("Mountain"));
        Assert.assertEquals(names(pair.getLeft()), List.of("Serra Angel", "Shivan Dragon"),
                "kept cards stay on top in shown order");
    }

    @Test(timeOut = 240_000)
    public void surveilGraveIsSeatChosen() throws Exception {
        CardCollection top = new CardCollection();
        for (String n : new String[]{"Air Elemental", "Plains"}) {
            top.add(MailboxTestKit.put(n, k.seat, ZoneType.Library));
        }
        org.apache.commons.lang3.tuple.ImmutablePair<CardCollection, CardCollection> pair =
                k.controller().arrangeForSurveil(top);
        Assert.assertEquals(names(pair.getRight()), List.of("Air Elemental"),
                "a reanimator-style self-mill is exactly what stock's scry logic never does");
    }

    @Test(timeOut = 240_000)
    public void libraryOrderIsSeatOrder() throws Exception {
        CardCollection cards = new CardCollection();
        for (String n : new String[]{"Pearled Unicorn", "Scathe Zombies", "Wall of Wood"}) {
            cards.add(MailboxTestKit.put(n, k.seat, ZoneType.Hand));
        }
        CardCollectionView ordered =
                k.controller().orderMoveToZoneList(cards, ZoneType.Library, null);
        // Wave-3 (F4): the controller now returns ENGINE order — reversed for
        // top-of-library, because consumers stack one card at a time and the
        // LAST element ends on top (stock parity). The seat's stated order is
        // proven end-to-end in CastPathReachabilityTest.topOrderLandsAsStated.
        Assert.assertEquals(names(ordered),
                List.of("Scathe Zombies", "Pearled Unicorn", "Wall of Wood"),
                "top-of-library answers must be reversed to engine order");
    }

    @Test(timeOut = 240_000)
    public void clashTopIsSeatConfirmed() throws Exception {
        Card c = MailboxTestKit.put("Rock Hydra", k.seat, ZoneType.Library);
        Assert.assertTrue(k.controller().willPutCardOnTop(c),
                "seat said yes; must land on top");
    }

    @Test(timeOut = 240_000)
    public void genericNumberAndValueListAreSeatChosen() throws Exception {
        Card host = MailboxTestKit.put("Shock", k.seat, ZoneType.Hand);
        SpellAbility sa = host.getFirstSpellAbility();
        Assert.assertEquals(k.controller().chooseNumber(sa, "secretly choose", 0, 20), 7,
                "Wheel-of-Misfortune-class number is the seat's");
        Assert.assertEquals(k.controller().chooseNumber(sa, "pick", List.of(2, 5, 9), null), 5);
    }

    @Test(timeOut = 240_000)
    public void announceNonManaVarIsSeatChosen() throws Exception {
        Card host = MailboxTestKit.put("Shock", k.seat, ZoneType.Hand);
        SpellAbility sa = host.getFirstSpellAbility();
        Assert.assertEquals(k.controller().announceRequirements(sa, 0, 5, "Multikicker"),
                Integer.valueOf(3), "note 15b's sibling: non-X announces reach the seat");
    }

    @Test(timeOut = 240_000)
    public void redirectIsSeatAimed() throws Exception {
        Card bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        Card ogre = MailboxTestKit.put("Gray Ogre", k.opp, ZoneType.Battlefield);
        Card shock = MailboxTestKit.put("Shock", k.opp, ZoneType.Hand);
        SpellAbility sa = shock.getFirstSpellAbility();
        sa.setActivatingPlayer(k.opp);
        sa.getTargets().add(bears);
        TargetChoices next = k.controller().chooseNewTargetsFor(sa, null, false);
        Assert.assertNotNull(next, "THE LIVE GAP: stock returns null and the "
                + "redirect silently no-ops");
        Assert.assertEquals(sa.getTargetCard(), ogre,
                "the changing SA must now aim at the seat's pick");
    }

    @Test(timeOut = 240_000)
    public void protectionVoteAndPileAreSeatChosen() throws Exception {
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
                MailboxTestKit.put("Shivan Dragon", k.seat, ZoneType.Library));
        Assert.assertFalse(k.controller().chooseCardsPile(sa, p1, p2, "False"),
                "seat took pile 2 (the good pile stock's size-comparison skips)");
        // Hidden-pile fairness (review catch): with FaceDown=One, pile 1's
        // CONTENTS must not appear in the request — only its count.
        k.controller().chooseCardsPile(sa, p1, p2, "One");
        boolean oneHidden = k.seen.stream().anyMatch(b -> b.contains("CHOOSE A PILE")
                && b.contains("Pile 1: 1 face-down card")
                && b.contains("Pile 2: Shivan Dragon"));
        boolean leaked = k.seen.stream().anyMatch(b -> b.contains("CHOOSE A PILE")
                && b.contains("face-down") && b.contains("Pile 1: Forest"));
        Assert.assertTrue(oneHidden && !leaked,
                "FaceDown=One: pile 1 hidden (count only), pile 2 visible");
    }

    @Test(timeOut = 240_000)
    public void mixedCardPlayerChoiceReachesSeat() throws Exception {
        Card bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        FCollection<GameEntity> opts = new FCollection<>();
        opts.add(bears);
        opts.add(k.opp);
        GameEntity picked = k.controller().chooseSingleEntityForEffect(
                opts, null, null, "drain target", false, null, null);
        Assert.assertEquals(picked, k.opp,
                "a creature-or-player choice must reach the seat (old allCards "
                + "gate silently fell to stock)");
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
