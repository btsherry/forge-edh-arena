package forge.arena.interactive;

import java.util.ArrayList;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.game.zone.ZoneType;

/**
 * Interactive plan item 4: a refused unaffordable cast must be VISIBLE to the
 * brain. Before, {@code playChosenSpellAbility} refused, printed to stderr,
 * returned "played", and the next window carried identical options and no
 * note — the brain re-picked the same spell (a model-call livelock).
 *
 * <p>Two spells of different kinds (a creature and a sorcery), neither
 * castable off two Swamps: each refusal must (a) put {@code lastRefused} in
 * the NEXT request's state with the engine's own numbers, (b) append the
 * feedback sentence to that prompt, and (c) omit the refused option from
 * that one window only — it returns the window after.
 */
public class RefusedCastFeedbackTest {

    private static final String CAST = "\"decisionType\":\"CAST_SPELL\"";

    @Test(timeOut = 240_000)
    public void refusalIsReportedAndTheOptionSkipsOneWindow() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Hand);   // {1}{G}
            MailboxTestKit.put("Divination", k.seat, ZoneType.Hand);      // {2}{U}
            for (int i = 0; i < 2; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Battlefield);
            }
            for (int i = 0; i < 3; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
                MailboxTestKit.put("Island", k.opp, ZoneType.Library);
            }
            List<String> casts = new ArrayList<>();
            k.startBrain(body -> {
                if (!body.contains(CAST)) {
                    return "{\"chosenId\": 0}";
                }
                synchronized (casts) {
                    casts.add(body);
                    int n = casts.size();
                    String pick = n == 1 ? MailboxTestKit.idOf(body, "Grizzly Bears")
                            : n == 2 ? MailboxTestKit.idOf(body, "Divination") : null;
                    return "{\"chosenId\": " + (pick != null ? pick : "0") + "}";
                }
            });
            k.run(() -> { synchronized (casts) { return casts.size() >= 3; } }, 300);
            k.stopBrain();

            List<String> seen;
            synchronized (casts) {
                seen = new ArrayList<>(casts);
            }
            Assert.assertTrue(seen.size() >= 3, "expected three cast windows, saw " + seen.size());
            String w1 = seen.get(0);
            String w2 = seen.get(1);
            String w3 = seen.get(2);

            Assert.assertFalse(w1.contains("lastRefused"), "nothing refused yet");
            Assert.assertNotNull(MailboxTestKit.idOf(w1, "Grizzly Bears"));

            Assert.assertTrue(w2.contains("\"lastRefused\":{"), "window 2 must report the refusal");
            Assert.assertTrue(w2.contains("\"name\":\"Grizzly Bears\""), "…naming the refused spell");
            Assert.assertTrue(w2.contains("\"payableNow\":"), "…with the engine's affordability number");
            Assert.assertTrue(w2.contains("was refused"), "…and the prompt sentence");
            Assert.assertNull(MailboxTestKit.idOf(w2, "Grizzly Bears"),
                    "the refused spell is not offered in the very next window");
            Assert.assertNotNull(MailboxTestKit.idOf(w2, "Divination"),
                    "other spells are still offered");

            Assert.assertTrue(w3.contains("\"name\":\"Divination\""),
                    "window 3 reports the second refusal");
            Assert.assertNull(MailboxTestKit.idOf(w3, "Divination"));
            Assert.assertNotNull(MailboxTestKit.idOf(w3, "Grizzly Bears"),
                    "the first refused spell is offered again after one window");
        }
    }
}
