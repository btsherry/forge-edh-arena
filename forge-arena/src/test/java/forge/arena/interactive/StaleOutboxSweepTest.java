package forge.arena.interactive;

import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.Assert;
import org.testng.annotations.Test;

/**
 * BL-22 / BL-05 (2026-09-04): a bus sweeps stale {@code resp-*.json} and
 * {@code *.tmp} from its outbox when it is created, and there is exactly one
 * bus per seat directory (so a second controller on the same seat continues
 * the request sequence instead of restarting it).
 */
public class StaleOutboxSweepTest {

    @Test
    public void staleResponsesAreSweptAtConstructionAndTheBusIsShared() throws Exception {
        Path base = Files.createTempDirectory("sweep");
        Path out = base.resolve("seat-4").resolve("outbox");
        Files.createDirectories(out);
        Files.writeString(out.resolve("resp-1.json"), "{\"chosenId\": 1}");
        Files.writeString(out.resolve("resp-2.json.tmp"), "{");
        Files.writeString(out.resolve("keep.txt"), "not ours");

        MailboxProtocol a = MailboxProtocol.forSeat(base, 4);
        Assert.assertFalse(Files.exists(out.resolve("resp-1.json")), "stale response swept");
        Assert.assertFalse(Files.exists(out.resolve("resp-2.json.tmp")), "stale temp swept");
        Assert.assertTrue(Files.exists(out.resolve("keep.txt")), "unrelated files untouched");

        MailboxProtocol b = MailboxProtocol.forSeat(base, 4);
        Assert.assertSame(a, b, "one bus per seat directory");
        Assert.assertNotSame(a, MailboxProtocol.forSeat(base, 5));
    }
}
