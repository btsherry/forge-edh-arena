package forge.arena.interactive;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;

import org.testng.Assert;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Interactive plan item 12: a dead brain must not cost the game a full
 * timeout per decision. The runner touches {@code <seat-dir>/heartbeat}
 * every 5 s; the engine stats it once before blocking. Stale → stock plays
 * at once. Fresh or absent (older runner, or none) → wait as always: the
 * gate can only shorten a wait. This is also the suite's dead-brain test:
 * a silent brain yields null on time, never a hang.
 */
public class HeartbeatGateTest {

    private static MailboxProtocol.Request req() {
        return new MailboxProtocol.Request(7, 1, "MAIN1", "CONFIRM", "x")
                .option(0, "No", null, "NO").option(1, "Yes", null, "YES");
    }

    @Test(timeOut = 60_000)
    public void staleHeartbeatSkipsTheWaitFreshOrAbsentWaits() throws Exception {
        String prev = System.getProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, "2");
        try {
            Path base = Files.createTempDirectory("hbgate");
            MailboxProtocol bus = MailboxProtocol.forSeat(base, 7);
            Path seatDir = base.resolve("seat-7");
            Path hb = seatDir.resolve("heartbeat");

            // no heartbeat file: unknown -> wait the full (2 s) timeout
            Assert.assertNull(MailboxProtocol.brainAlive(seatDir));
            long t0 = System.currentTimeMillis();
            JsonNode r = bus.exchange(req());
            long waited = System.currentTimeMillis() - t0;
            Assert.assertNull(r);
            Assert.assertTrue(waited >= 1_800, "absent heartbeat must wait as before (waited " + waited + "ms)");

            // stale heartbeat: nobody home -> immediate null, no request written
            Files.writeString(hb, "");
            Files.setLastModifiedTime(hb, FileTime.fromMillis(System.currentTimeMillis() - 60_000));
            Assert.assertEquals(MailboxProtocol.brainAlive(seatDir), Boolean.FALSE);
            t0 = System.currentTimeMillis();
            r = bus.exchange(req());
            waited = System.currentTimeMillis() - t0;
            Assert.assertNull(r);
            Assert.assertTrue(waited < 500, "stale heartbeat must not wait (waited " + waited + "ms)");
            try (java.util.stream.Stream<Path> files = Files.list(seatDir.resolve("inbox"))) {
                Assert.assertEquals(files.count(), 0L, "no request is written for an absent brain");
            }

            // fresh heartbeat: somebody home -> full wait again
            Files.setLastModifiedTime(hb, FileTime.fromMillis(System.currentTimeMillis()));
            Assert.assertEquals(MailboxProtocol.brainAlive(seatDir), Boolean.TRUE);
            t0 = System.currentTimeMillis();
            r = bus.exchange(req());
            waited = System.currentTimeMillis() - t0;
            Assert.assertNull(r);
            Assert.assertTrue(waited >= 1_800, "fresh heartbeat must wait the timeout (waited " + waited + "ms)");
        } finally {
            if (prev == null) {
                System.clearProperty(MailboxProtocol.TIMEOUT_PROPERTY);
            } else {
                System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, prev);
            }
        }
    }
}
