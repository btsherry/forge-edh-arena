package forge.arena.interactive;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.player.PlayerController;

/**
 * Advisor Executive (2026-09-07): the toggle file installs a seat mailbox
 * controller over a player through Forge's own controller override and
 * removes it again; both read the file, neither throws.
 */
public class ExecutiveSwitchTest {

    @Test
    public void theFileAloneIsNotEnoughWithoutAnAttachedLiveAdvisor() throws Exception {
        final String prev = System.getProperty("arena.runner.logs.dir");
        final Path logs = Files.createTempDirectory("exec-logs2");
        System.setProperty("arena.runner.logs.dir", logs.toString());
        System.clearProperty("arena.executive.test");
        final String adv = System.getProperty("arena.advisor");
        System.clearProperty("arena.advisor");
        try {
            Files.createDirectories(ExecutiveSwitch.controlFile().getParent());
            Files.write(ExecutiveSwitch.controlFile(), "{\"on\": true}".getBytes(StandardCharsets.UTF_8));
            Assert.assertFalse(ExecutiveSwitch.wanted(), "no advisor attached: a stale file hands the seat to nobody");
            System.setProperty("arena.advisor", "1");
            Assert.assertFalse(ExecutiveSwitch.wanted(), "attached but no fresh heartbeat: still off");
        } finally {
            if (adv == null) {
                System.clearProperty("arena.advisor");
            } else {
                System.setProperty("arena.advisor", adv);
            }
            if (prev == null) {
                System.clearProperty("arena.runner.logs.dir");
            } else {
                System.setProperty("arena.runner.logs.dir", prev);
            }
        }
    }

    @Test(timeOut = 120_000)
    public void toggleFileInstallsAndReleasesTheOverride() throws Exception {
        final String prev = System.getProperty("arena.runner.logs.dir");
        final Path logs = Files.createTempDirectory("exec-logs");
        System.setProperty("arena.runner.logs.dir", logs.toString());
        System.setProperty("arena.executive.test", "1"); // wanted() otherwise needs a live advisor heartbeat
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Assert.assertFalse(ExecutiveSwitch.wanted(), "no file = off");
            final PlayerController before = k.opp.getController();
            // the file says on
            Files.createDirectories(ExecutiveSwitch.controlFile().getParent());
            Files.write(ExecutiveSwitch.controlFile(), "{\"on\": true}".getBytes(StandardCharsets.UTF_8));
            Assert.assertTrue(ExecutiveSwitch.wanted());
            ExecutiveSwitch.forget(k.opp);
            Assert.assertTrue(ExecutiveSwitch.install(k.opp, k.opp.getLobbyPlayer()));
            final PlayerController over = k.opp.getController();
            Assert.assertTrue(over instanceof MailboxController, "override is a mailbox controller: " + over);
            Assert.assertTrue(ExecutiveSwitch.isExecutive(over));
            Assert.assertFalse(ExecutiveSwitch.install(k.opp, k.opp.getLobbyPlayer()), "second install is a no-op");
            // the file says off -> release restores the original controller
            Files.write(ExecutiveSwitch.controlFile(), "{\"on\": false}".getBytes(StandardCharsets.UTF_8));
            Assert.assertFalse(ExecutiveSwitch.wanted());
            Assert.assertTrue(ExecutiveSwitch.release(k.opp));
            Assert.assertSame(k.opp.getController(), before, "the human's controller answers again");
            Assert.assertFalse(ExecutiveSwitch.release(k.opp), "release twice is a no-op");
        } finally {
            System.clearProperty("arena.executive.test");
            if (prev == null) {
                System.clearProperty("arena.runner.logs.dir");
            } else {
                System.setProperty("arena.runner.logs.dir", prev);
            }
        }
    }
}
