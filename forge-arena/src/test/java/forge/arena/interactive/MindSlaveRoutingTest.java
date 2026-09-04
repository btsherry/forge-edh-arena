package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.player.PlayerController;
import forge.game.zone.ZoneType;

/**
 * Interactive plan item 11a: under Mindslaver-class control the MASTER's
 * brain decides (CR 721). The slave's controller must route to the master's
 * mailbox, carry {@code controllingSeat}, and say so in the prompt. Before,
 * it was built on the slave's own bus, so the slave kept playing itself.
 */
public class MindSlaveRoutingTest {

    @Test(timeOut = 120_000)
    public void slaveDecisionsGoToTheMastersMailbox() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            // the kit's brain reads the SEAT's inbox only — if it sees the
            // request, the request went to the master (= seat), not the slave (= opp)
            k.startBrain(body -> body.contains("\"decisionType\":\"MULLIGAN\"")
                    ? "{\"keep\": false}" : "{\"chosenId\": 0}");
            for (int i = 0; i < 7; i++) {
                MailboxTestKit.put("Swamp", k.opp, ZoneType.Hand);
            }
            // the MASTER's own hand: must be visible to the master's brain in
            // the controlled request (BL-05, CR 721.3), never to anyone else
            MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Hand);
            // the master's own controller has already used seq 1 on this bus
            k.controller().mulliganKeepHand(k.seat, 0);
            MailboxLobbyPlayer master = (MailboxLobbyPlayer) k.seat.getLobbyPlayer();
            PlayerController slaveCtl = master.createMindSlaveController(k.seat, k.opp);
            Assert.assertTrue(slaveCtl instanceof MailboxController);

            boolean keep = ((MailboxController) slaveCtl).mulliganKeepHand(k.opp, 0);
            k.stopBrain();

            Assert.assertFalse(keep, "the master's brain answered (mulligan)");
            Assert.assertEquals(k.seen.size(), 2, "master's own request, then the slave's, in ONE inbox");
            Assert.assertTrue(k.seen.get(0).contains("\"seq\":1,") && k.seen.get(1).contains("\"seq\":2,"),
                    "BL-05: the slave's controller continues the master bus's sequence (a fresh bus "
                    + "restarted at 1 and the runner skipped the reused name)");
            String body = k.seen.get(1);
            int cb = body.indexOf("\"controllerBoard\":{");
            Assert.assertTrue(cb > 0, "the controlled request carries the master's board");
            String board = body.substring(cb);
            Assert.assertTrue(board.contains("Sol Ring"), "…including the master's own hand");
            Assert.assertTrue(board.contains("\"life\":"), "…and life/mana summary");
            Assert.assertFalse(k.seen.get(0).contains("controllerBoard"),
                    "a seat playing itself carries no controllerBoard");
            Assert.assertTrue(body.contains("\"seat\":" + k.opp.getId()),
                    "the request is about the SLAVE's seat");
            Assert.assertTrue(body.contains("\"controllingSeat\":" + k.seat.getId()),
                    "…and names the controlling seat");
            Assert.assertTrue(body.contains("YOU ARE CONTROLLING SEAT " + k.opp.getId()),
                    "…and the prompt says so");
        }
    }
}
