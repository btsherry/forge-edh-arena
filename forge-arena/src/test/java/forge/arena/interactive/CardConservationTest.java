package forge.arena.interactive;

import java.util.Map;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.zone.ZoneType;

/**
 * Interactive plan item 7, the end invariant: every card a player brought is
 * found somewhere at game end — library, hand, battlefield, graveyard, exile
 * (face-down included), command, stack — attributed by OWNER, with tokens,
 * copies, emblems and effect pseudo-cards excluded.
 */
public class CardConservationTest {

    @Test(timeOut = 120_000)
    public void ownedCardsAreCountedAcrossZonesByOwnerWithoutTokens() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 4; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
            }
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Dark Ritual", k.seat, ZoneType.Graveyard);
            Card faceDown = MailboxTestKit.put("Island", k.seat, ZoneType.Exile);
            faceDown.turnFaceDown();
            MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Command);
            // a token and a stolen card: the token never counts; the stolen
            // card counts for its OWNER even while it sits on our battlefield
            Card token = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            token.setGamePieceType(forge.card.GamePieceType.TOKEN);
            Card stolen = MailboxTestKit.put("Llanowar Elves", k.opp, ZoneType.Battlefield);
            k.seat.getZone(ZoneType.Battlefield).add(stolen);
            k.opp.getZone(ZoneType.Battlefield).remove(stolen);
            MailboxTestKit.put("Forest", k.opp, ZoneType.Library);
            MailboxTestKit.put("Forest", k.opp, ZoneType.Hand);

            Map<Integer, Integer> counts = GameResultSpool.ownedCardCounts(k.game);
            Assert.assertEquals(counts.get(k.seat.getId()), Integer.valueOf(9),
                    "4 library + 1 hand + 1 battlefield + 1 graveyard + 1 face-down exile + 1 command; "
                    + "not the token, not the stolen Elves");
            Assert.assertEquals(counts.get(k.opp.getId()), Integer.valueOf(3),
                    "2 Forests + the Elves we control but they own");
        }
    }
}
