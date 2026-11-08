package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * W-14 watch condition, built after game 20261107-184934 t33: seat 3 cast
 * Devastating Onslaught meaning to copy it with Flare of Duplication, and the
 * gate passed its own priority (only the seat's own non-trigger object on the
 * stack), so the spell resolved and the combo died. A SELF-SPELL window now
 * opens when the stack holds only the seat's own spell/ability AND the seat
 * holds an affordable COPY effect whose target restriction reaches it — a copy
 * spell, a flash creature whose ETB copies (Dualcaster Mage), Lithoform-class
 * abilities. A counter or a redirect does not count (no line at cast time,
 * and it would open on every cast). Without a copy answer the window stays
 * the clean pass W-14 chose. Decided from the effect class and target
 * restrictions, never by name. One kit, direct controller calls.
 */
public class SelfSpellWindowTest {

    private static long windows(MailboxTestKit k) {
        return k.seen.stream().filter(b -> b.contains("\"decisionType\":\"REACT\"")).count();
    }

    private static void mountains(MailboxTestKit k, int n) {
        for (int i = 0; i < n; i++) {
            MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);
        }
    }

    private static void clearHand(MailboxTestKit k) {
        for (Card c : new java.util.ArrayList<>(k.seat.getCardsIn(ZoneType.Hand))) {
            k.seat.getZone(ZoneType.Hand).remove(c);
        }
    }

    @Test(timeOut = 240_000)
    public void ownSpellWindowOpensOnlyForAStackTargetingAnswer() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {   // the seat's own main phase
            k.startBrain(body -> null);                          // every window: pass
            mountains(k, 3);
            // the seat's own instant sits on the stack, aimed at the opponent
            Card bolt = MailboxTestKit.put("Lightning Bolt", k.seat, ZoneType.Hand);
            SpellAbility boltSa = bolt.getFirstSpellAbility();
            boltSa.setActivatingPlayer(k.seat);
            boltSa.getTargets().add(k.opp);
            k.game.getAction().moveToStack(bolt, boltSa);
            k.game.getStack().add(boltSa);
            Assert.assertEquals(k.game.getStack().size(), 1, "own spell on the stack");

            // 1) a copy spell in hand: the window opens and offers it
            MailboxTestKit.put("Flare of Duplication", k.seat, ZoneType.Hand);
            long before = windows(k);
            k.controller().chooseSpellAbilityToPlay();
            Assert.assertEquals(windows(k), before + 1, "a self-spell window opened for Flare");
            String body = k.seen.get(k.seen.size() - 1);
            Assert.assertNotNull(MailboxTestKit.idOf(body, "Flare of Duplication"),
                    "Flare is offered: " + body);
            Assert.assertTrue(body.contains("you hold something that can COPY it"),
                    "the prompt says what the window is for: " + body);

            // 2) nothing that can copy a spell: the clean pass of old, no window.
            //    A counter and a redirect CAN target the spell and still do not
            //    count — countering or re-aiming your own spell as you cast it is
            //    no line, and such a window would open on every cast.
            clearHand(k);
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Shock", k.seat, ZoneType.Hand);          // an instant that aims at creatures/players
            MailboxTestKit.put("Counterspell", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Deflecting Swat", k.seat, ZoneType.Hand);
            for (int i = 0; i < 2; i++) {
                MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            }
            before = windows(k);
            Assert.assertNull(k.controller().chooseSpellAbilityToPlay(), "a clean pass");
            Assert.assertEquals(windows(k), before, "no window without a copy answer");

            // 3) a flash creature whose ETB copies a spell: the trigger's restriction counts
            clearHand(k);
            MailboxTestKit.put("Dualcaster Mage", k.seat, ZoneType.Hand);
            before = windows(k);
            k.controller().chooseSpellAbilityToPlay();
            Assert.assertEquals(windows(k), before + 1, "a self-spell window opened for Dualcaster Mage");
            Assert.assertNotNull(MailboxTestKit.idOf(k.seen.get(k.seen.size() - 1), "Dualcaster Mage"));

            // 3b) a "spell you control" copy trigger (Naru Meha): the trigger's
            //     ability is probed with the seat as activator, so YouCtrl reads
            clearHand(k);
            for (int i = 0; i < 4; i++) {
                MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            }
            MailboxTestKit.put("Naru Meha, Master Wizard", k.seat, ZoneType.Hand);
            before = windows(k);
            k.controller().chooseSpellAbilityToPlay();
            Assert.assertEquals(windows(k), before + 1, "a self-spell window opened for Naru Meha");
            Assert.assertNotNull(MailboxTestKit.idOf(k.seen.get(k.seen.size() - 1), "Naru Meha, Master Wizard"));

            // 3c) the copy rides a redirect root (Wild Ricochet) or a Charm mode
            //     (Return the Favor): the chain, not the root API, decides
            clearHand(k);
            MailboxTestKit.put("Mountain", k.seat, ZoneType.Battlefield);   // four Mountains for Ricochet
            MailboxTestKit.put("Wild Ricochet", k.seat, ZoneType.Hand);
            before = windows(k);
            k.controller().chooseSpellAbilityToPlay();
            Assert.assertEquals(windows(k), before + 1, "a self-spell window opened for Wild Ricochet");
            Assert.assertNotNull(MailboxTestKit.idOf(k.seen.get(k.seen.size() - 1), "Wild Ricochet"));
            clearHand(k);
            MailboxTestKit.put("Return the Favor", k.seat, ZoneType.Hand);
            before = windows(k);
            k.controller().chooseSpellAbilityToPlay();
            Assert.assertEquals(windows(k), before + 1, "a self-spell window opened for Return the Favor");
            Assert.assertNotNull(MailboxTestKit.idOf(k.seen.get(k.seen.size() - 1), "Return the Favor"));

            // 3d) an own ACTIVATION on the stack with a copy ability on the board
            //     (Lithoform Engine): the W-14 line itself — and the flood path
            //     the hygiene count measures (every own activation while it is up)
            clearHand(k);
            k.game.getStack().clear();
            Card top = MailboxTestKit.put("Sensei's Divining Top", k.seat, ZoneType.Battlefield);
            SpellAbility spin = null;
            for (SpellAbility a : top.getSpellAbilities()) {
                if (a.isActivatedAbility() && a.getPayCosts() != null && !a.getPayCosts().hasTapCost()) {
                    spin = a;   // {1}: look at the top three cards
                }
            }
            Assert.assertNotNull(spin, "Top's {1} ability");
            spin.setActivatingPlayer(k.seat);
            k.game.getStack().add(spin);
            MailboxTestKit.put("Lithoform Engine", k.seat, ZoneType.Battlefield);
            k.game.getAction().checkStateEffects(true);
            before = windows(k);
            k.controller().chooseSpellAbilityToPlay();
            Assert.assertEquals(windows(k), before + 1, "a self-spell window opened for Lithoform over an own activation");
            Assert.assertNotNull(MailboxTestKit.idOf(k.seen.get(k.seen.size() - 1), "Lithoform Engine"));
            for (Card c : new java.util.ArrayList<>(k.seat.getCardsIn(ZoneType.Battlefield))) {
                if (c.getName().equals("Lithoform Engine") || c.getName().equals("Sensei's Divining Top")) {
                    k.seat.getZone(ZoneType.Battlefield).remove(c);
                }
            }
            k.game.getStack().clear();
            k.game.getStack().add(boltSa);          // back to the own Bolt alone

            // 3e) an OPPONENT object on the stack as well: that is a reactive window,
            //     never a self-spell one (its prompt differs), and the copy is still offered
            MailboxTestKit.put("Flare of Duplication", k.seat, ZoneType.Hand);
            Card oppBolt = MailboxTestKit.put("Lightning Bolt", k.opp, ZoneType.Hand);
            SpellAbility oppSa = oppBolt.getFirstSpellAbility();
            oppSa.setActivatingPlayer(k.opp);
            oppSa.getTargets().add(k.seat);
            k.game.getAction().moveToStack(oppBolt, oppSa);
            k.game.getStack().add(oppSa);
            before = windows(k);
            k.controller().chooseSpellAbilityToPlay();
            Assert.assertEquals(windows(k), before + 1, "a reactive window opened");
            body = k.seen.get(k.seen.size() - 1);
            Assert.assertFalse(body.contains("you hold something that can COPY it"), "reactive, not self-spell: " + body);
            Assert.assertNotNull(MailboxTestKit.idOf(body, "Flare of Duplication"));
            k.game.getStack().clear();
            k.game.getStack().add(boltSa);          // the own Bolt alone again
            clearHand(k);

            // 4) the answer must be affordable now: tapped out, no window
            clearHand(k);
            MailboxTestKit.put("Dualcaster Mage", k.seat, ZoneType.Hand);
            for (Card c : k.seat.getCardsIn(ZoneType.Battlefield)) {
                c.setTapped(true);
            }
            before = windows(k);
            Assert.assertNull(k.controller().chooseSpellAbilityToPlay());
            Assert.assertEquals(windows(k), before, "no window for an answer the seat cannot pay");
        }
    }
}
