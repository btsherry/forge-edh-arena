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
}
