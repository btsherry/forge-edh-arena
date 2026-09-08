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
}
