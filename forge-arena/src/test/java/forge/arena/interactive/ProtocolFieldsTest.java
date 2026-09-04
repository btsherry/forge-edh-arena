package forge.arena.interactive;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.player.PlayerActionConfirmMode;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * Interactive plan, engine-side protocol fields (items 8, 10, 11d, 12):
 * every request carries {@code gameId} (one value per Game) and
 * {@code timeoutSec} (the engine's wait); confirms carry {@code hasCost} and
 * {@code isMine} so the runner's punt rule can be structural; an untyped
 * confirm reaches the seat when its source is the seat's own ability (not
 * when the message contains "play"), and stays stock otherwise.
 */
public class ProtocolFieldsTest {

    private static final Pattern GAME_ID = Pattern.compile("\"gameId\":\"([0-9]+-[0-9]+-[0-9]+)\"");

    @Test(timeOut = 120_000)
    public void everyRequestCarriesGameIdAndTimeout() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            k.startBrain(body -> "{\"keep\": true}");
            for (int i = 0; i < 7; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Hand);
            }
            MailboxController c = k.controller();
            c.mulliganKeepHand(k.seat, 0);
            c.mulliganKeepHand(k.seat, 1);
            k.stopBrain();

            Assert.assertTrue(k.seen.size() >= 2, "two mulligan requests expected");
            String first = null;
            for (String body : k.seen) {
                Matcher m = GAME_ID.matcher(body);
                Assert.assertTrue(m.find(), "request lacks gameId: " + body.substring(0, 80));
                if (first == null) {
                    first = m.group(1);
                }
                Assert.assertEquals(m.group(1), first, "gameId must be stable within one game");
                Assert.assertTrue(body.contains("\"timeoutSec\":" + MailboxProtocol.timeoutSeconds()),
                        "request must publish the engine's own timeout");
            }
            Assert.assertEquals(first, MailboxController.gameIdFor(k.game),
                    "the stamped id is the Game's id");
        }
    }

    /** BL-28: two Games in one JVM (even in the same millisecond) never share an id. */
    @Test(timeOut = 120_000)
    public void distinctGamesGetDistinctIds() throws Exception {
        try (MailboxTestKit a = new MailboxTestKit(false); MailboxTestKit b = new MailboxTestKit(false)) {
            String ia = MailboxController.gameIdFor(a.game);
            String ib = MailboxController.gameIdFor(b.game);
            Assert.assertNotEquals(ia, ib, "ids must differ per Game");
            Assert.assertEquals(ia, MailboxController.gameIdFor(a.game), "and stay stable per Game");
            Assert.assertTrue(ia.matches("[0-9]+-[0-9]+-[0-9]+"), ia);
        }
    }

    @Test(timeOut = 120_000)
    public void untypedConfirmIsGatedBySourceAndCarriesPuntFacts() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            k.startBrain(body -> "{\"chosenId\": 1}");
            Card mine = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Hand);
            Card theirs = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Hand);
            SpellAbility mySa = mine.getSpellAbilities().get(0);
            mySa.setActivatingPlayer(k.seat);
            SpellAbility theirSa = theirs.getSpellAbilities().get(0);
            theirSa.setActivatingPlayer(k.opp);
            MailboxController c = k.controller();

            // own source, untyped, message without "play": must reach the seat
            boolean yes = c.confirmAction(mySa, null, "Return it to your hand?", null, null, null);
            int afterMine = k.seen.size();
            // opponent's source, untyped, message WITH "play": must stay stock
            c.confirmAction(theirSa, null, "Do you want to play it?", null, null, null);
            int afterTheirs = k.seen.size();
            // typed OptionalChoose from own source: reaches the seat with facts
            c.confirmAction(mySa, PlayerActionConfirmMode.OptionalChoose, "Each player draws?",
                    null, null, null);
            k.stopBrain();

            Assert.assertTrue(yes, "brain said yes");
            Assert.assertEquals(afterMine, 1, "own-source untyped confirm must be mailboxed");
            Assert.assertEquals(afterTheirs, 1,
                    "opponent-source untyped confirm must stay stock even if the message says 'play'");
            Assert.assertEquals(k.seen.size(), 2, "OptionalChoose from own source must be mailboxed");
            for (String body : k.seen) {
                Assert.assertTrue(body.contains("\"decisionType\":\"CONFIRM\""), body.substring(0, 80));
                Assert.assertTrue(body.contains("\"hasCost\":false"), "confirm must carry hasCost");
                Assert.assertTrue(body.contains("\"isMine\":true"), "confirm must carry isMine");
            }
        }
    }
}
