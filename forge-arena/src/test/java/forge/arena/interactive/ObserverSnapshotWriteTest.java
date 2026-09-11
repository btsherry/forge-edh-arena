package forge.arena.interactive;

import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.Assert;
import org.testng.annotations.Test;

/**
 * BL-07 (2026-09-04): the observer snapshot has no debounce timer. Every
 * event serializes the state and writes when it changed, so the LAST event of
 * a burst is always on disk; an event that changes nothing visible writes
 * nothing. Uses the kit's game (the mailbox lobby player registers the
 * snapshot under the kit's base dir).
 */
public class ObserverSnapshotWriteTest {

    @Test(timeOut = 120_000)
    public void lastEventOfABurstLandsAndIdenticalStateDoesNotRewrite() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Path snap = k.base.resolve("observer-state.json");
            Assert.assertTrue(Files.exists(snap), "initial snapshot written at registration");
            // a burst of life changes well inside the old 200 ms window
            k.seat.setLife(33, null);
            k.seat.setLife(31, null);
            k.seat.setLife(29, null);
            String body = Files.readString(snap);
            Assert.assertTrue(body.contains("\"life\":29"), "the LAST change is on disk: " + body);
            int writes = ObserverSnapshot.WRITES.get();
            // the same life again: an event, but no visible change -> no write
            k.seat.setLife(29, null);
            k.seat.setLife(29, null);
            Assert.assertEquals(ObserverSnapshot.WRITES.get(), writes, "identical state never rewrites");
            k.seat.setLife(27, null);
            Assert.assertEquals(ObserverSnapshot.WRITES.get(), writes + 1);
            Assert.assertTrue(Files.readString(snap).contains("\"life\":27"));
        }
    }

    /** 2026-09-07 (Ben: "shouldn't the imprint on Isochron Scepter be public
     *  knowledge?"): the snapshot carries every public zone and what each
     *  permanent holds; a face-down exiled card stays nameless. */
    @Test(timeOut = 120_000)
    public void publicZonesAndImprintsAreInTheSnapshot() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Path snap = k.base.resolve("observer-state.json");
            forge.game.card.Card scepter = MailboxTestKit.put("Isochron Scepter", k.opp, forge.game.zone.ZoneType.Battlefield);
            forge.game.card.Card pact = MailboxTestKit.put("Pact of Negation", k.opp, forge.game.zone.ZoneType.Exile);
            scepter.addImprintedCard(pact);
            MailboxTestKit.put("Beast Within", k.seat, forge.game.zone.ZoneType.Graveyard);
            forge.game.card.Card hidden = MailboxTestKit.put("Craterhoof Behemoth", k.seat, forge.game.zone.ZoneType.Exile);
            hidden.turnFaceDown();
            k.seat.setLife(35, null);   // an event, so the snapshot rewrites
            String body = Files.readString(snap);
            Assert.assertTrue(body.contains("\"imprinted\":[\"Pact of Negation\"]"), body);
            Assert.assertTrue(body.contains("\"graveyard\":[\"Beast Within\"]"), body);
            Assert.assertTrue(body.contains("\"exile\":[\"Pact of Negation\"]"), body);
            Assert.assertTrue(body.contains("\"commandZone\":["), body);
            Assert.assertTrue(body.contains("(face-down card)"), "face-down exile is a count, not a name: " + body);
            Assert.assertFalse(body.contains("Craterhoof Behemoth"), "a face-down card is never named: " + body);
            Assert.assertTrue(body.contains("\"stackDetail\":[]"), body);
        }
    }

    /** 2026-09-10 (seat barks): the snapshot carries a ring of public notable
     *  events — an attack with its total power and defenders, combat damage
     *  coalesced per step, and a spell countered (removed without resolving) —
     *  and a spell that resolved and then left the stack is NOT a counter. */
    @Test(timeOut = 120_000)
    public void attackDamageAndCounterEventsAreRecordedInTheRing() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Path snap = k.base.resolve("observer-state.json");
            forge.game.card.Card bear = MailboxTestKit.put("Grizzly Bears", k.opp, forge.game.zone.ZoneType.Battlefield);
            forge.game.card.Card hoof = MailboxTestKit.put("Craterhoof Behemoth", k.opp, forge.game.zone.ZoneType.Battlefield);
            com.google.common.collect.Multimap<forge.game.GameEntity, forge.game.card.Card> map =
                    com.google.common.collect.HashMultimap.create();
            map.put(k.seat, bear);
            map.put(k.seat, hoof);
            k.game.fireEvent(new forge.game.event.GameEventAttackersDeclared(k.opp, map));
            String body = Files.readString(snap);
            Assert.assertTrue(body.contains("\"kind\":\"attack\""), body);
            Assert.assertTrue(body.contains("\"attackers\":2"), body);
            Assert.assertTrue(body.contains("\"power\":7"), "2/2 + 5/5: " + body);
            Assert.assertTrue(body.contains("\"defenders\":[" + k.seat.getId() + "]"), body);
            // two attackers connect in one damage step: one coalesced event of 7
            k.game.fireEvent(new forge.game.event.GameEventPlayerDamaged(
                    forge.game.player.PlayerView.get(k.seat), forge.game.card.CardView.get(bear), 2, true, false));
            k.game.fireEvent(new forge.game.event.GameEventPlayerDamaged(
                    forge.game.player.PlayerView.get(k.seat), forge.game.card.CardView.get(hoof), 5, true, false));
            body = Files.readString(snap);
            Assert.assertTrue(body.contains("\"kind\":\"damage\",\"turn\""), body);
            Assert.assertTrue(body.contains("\"amount\":7"), "coalesced: " + body);
            Assert.assertFalse(body.contains("\"amount\":2"), "not two events: " + body);
            Assert.assertTrue(body.contains("\"from\":[" + k.opp.getId() + "]"), body);
            // a spell leaving the stack WITHOUT having resolved = countered
            forge.game.card.Card bw = MailboxTestKit.put("Beast Within", k.seat, forge.game.zone.ZoneType.Hand);
            forge.game.spellability.SpellAbility sa = bw.getFirstSpellAbility();
            k.game.fireEvent(new forge.game.event.GameEventSpellRemovedFromStack(
                    forge.game.spellability.SpellAbilityView.get(sa)));
            body = Files.readString(snap);
            Assert.assertTrue(body.contains("\"kind\":\"countered\""), body);
            Assert.assertTrue(body.contains("\"spell\":\"Beast Within\""), body);
            Assert.assertTrue(body.contains("\"seat\":" + k.seat.getId() + ",\"by\":"), body);
            // resolved, then removed: merely leaving — no second counter
            forge.game.card.Card bw2 = MailboxTestKit.put("Beast Within", k.opp, forge.game.zone.ZoneType.Hand);
            forge.game.spellability.SpellAbility sa2 = bw2.getFirstSpellAbility();
            k.game.fireEvent(new forge.game.event.GameEventSpellResolved(sa2, false));
            k.game.fireEvent(new forge.game.event.GameEventSpellRemovedFromStack(
                    forge.game.spellability.SpellAbilityView.get(sa2)));
            body = Files.readString(snap);
            Assert.assertEquals(body.split("\"kind\":\"countered\"", -1).length - 1, 1, "still exactly one counter: " + body);
        }
    }
}
