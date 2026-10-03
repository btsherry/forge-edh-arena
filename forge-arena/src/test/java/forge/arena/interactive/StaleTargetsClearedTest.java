package forge.arena.interactive;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * v4.3 acceptance game (2026-10-03, turn 28): Urza's REACT window offered
 * "Counterspell — Counter Vandalblast (265)" although Vandalblast had been exiled
 * turns earlier; the seat chose it to counter Razorkin Needlehead, no target
 * window opened, and the Counterspell went to the stack at the stale target and
 * fizzled. Stock's evaluation of the hand card in an earlier stock-decided window
 * (an overnight timeout) had left its targets set, and the aim gate trusted any
 * ability that already "held" a valid target.
 *
 * <p>Now: an offer's label never renders targets for a targeting part, and a
 * play the SEAT chose has its stale targets cleared before the aim, so the
 * target window opens and the spell hits what the seat names.
 */
public class StaleTargetsClearedTest {

    private static final String CAST = "\"decisionType\":\"CAST_SPELL\"";
    private static final String TARGET = "\"decisionType\":\"CHOOSE_ENTITY\"";

    @Test(timeOut = 240_000)
    public void aStaleTargetLeftOnAHandCardIsClearedAndTheSeatAimsAfresh() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            Card swords = MailboxTestKit.put("Swords to Plowshares", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Plains", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Plains", k.seat, ZoneType.Battlefield);
            Card gone = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Graveyard);   // the "Vandalblast": long gone
            Card giant = MailboxTestKit.put("Hill Giant", k.opp, ZoneType.Battlefield);
            for (int i = 0; i < 4; i++) {
                MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
                MailboxTestKit.put("Forest", k.opp, ZoneType.Library);
            }
            for (SpellAbility sa : swords.getSpells()) {
                sa.getTargets().add(gone);              // what stock's evaluation leaves behind
            }
            AtomicInteger casts = new AtomicInteger();
            AtomicReference<String> offer = new AtomicReference<>();
            AtomicReference<String> window = new AtomicReference<>();
            k.startBrain(body -> {
                if (body.contains(TARGET)) {
                    window.set(body);
                    return "{\"chosenId\": " + MailboxTestKit.idOf(body, "Hill Giant") + "}";
                }
                if (body.contains(CAST)) {
                    String id = MailboxTestKit.idOf(body, "Swords to Plowshares");
                    if (id != null && casts.getAndIncrement() == 0) {
                        offer.set(body);
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                return "{\"chosenId\": 0}";
            });
            k.run(() -> giant.isInZone(ZoneType.Exile) || !k.seat.getCardsIn(ZoneType.Hand).contains(swords)
                    && k.game.getStack().isEmpty() && casts.get() >= 1, 300);
            k.stopBrain();

            String o = offer.get();
            Assert.assertNotNull(o, "the spell was offered");
            int i = o.indexOf("\"label\":\"Swords to Plowshares");
            String label = o.substring(i, Math.min(o.length(), i + 160));
            Assert.assertFalse(label.contains("Grizzly Bears"), "the offer must not show the stale target: " + label);
            Assert.assertNotNull(window.get(), "the seat is asked for the target (before: none, the stale one was trusted)");
            Assert.assertTrue(giant.isInZone(ZoneType.Exile), "Swords hit what the seat named");
            Assert.assertFalse(gone.isInZone(ZoneType.Exile), "not the ghost");
        }
    }
}
