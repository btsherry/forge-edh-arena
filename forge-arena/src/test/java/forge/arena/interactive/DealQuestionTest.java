package forge.arena.interactive;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

/** The offer pane's data (plan 2026-09-16-offer-dialog-plan.md): the advisor runner's question files, parsed flat. */
public class DealQuestionTest {

    private static final String FULL = "{\"offer_id\": \"1789607879844-3-0\", \"seat\": 3, \"who\": \"Purphoros\", "
            + "\"handle\": \"purphoros\", \"terms\": \"alliance until turn 10\", \"text\": \"Urza is the \\\"real\\\" threat\", "
            + "\"turn\": 7, \"lapses_after_turn\": 8, \"assessment\": null, \"ts\": 1789607879.9}";

    @Test
    public void parsesEveryFieldAndTheEscapedQuote() {
        final DealQuestion q = DealQuestion.parse(FULL, new File("x.json"));
        Assert.assertNotNull(q);
        Assert.assertEquals(q.offerId, "1789607879844-3-0");
        Assert.assertEquals(q.seat, 3);
        Assert.assertEquals(q.who, "Purphoros");
        Assert.assertEquals(q.handle, "purphoros");
        Assert.assertEquals(q.terms, "alliance until turn 10");
        Assert.assertEquals(q.text, "Urza is the \"real\" threat");
        Assert.assertEquals(q.turn, 7);
        Assert.assertEquals(q.lapsesAfterTurn, 8);
        Assert.assertNull(q.assessment, "null until Joshua speaks");
        Assert.assertEquals(q.ts, 1789607879L, "seconds, the fraction dropped");
        Assert.assertEquals(q.headline(), "Purphoros offers you alliance until turn 10");
        Assert.assertEquals(q.lapseLine(), "lapses at the end of turn 8");
        Assert.assertEquals(q.acceptAsk(), "@purphoros accept", "exactly what the player would type");
        Assert.assertEquals(q.refuseAsk(), "@purphoros no");
        Assert.assertEquals(q.counterPrefix(), "@purphoros ");
    }

    @Test
    public void theAssessmentLandsOnARewrite() {
        final DealQuestion q = DealQuestion.parse(FULL.replace("\"assessment\": null",
                "\"assessment\": \"Take it: he cannot race you.\\nWatch Urza.\""), new File("x.json"));
        Assert.assertEquals(q.assessment, "Take it: he cannot race you.\nWatch Urza.");
    }

    @Test
    public void noOfferIdOrHandleIsNoQuestion() {
        Assert.assertNull(DealQuestion.parse("{\"who\": \"Urza\", \"handle\": \"urza\"}", new File("a.json")));
        Assert.assertNull(DealQuestion.parse("{\"offer_id\": \"1-1-0\", \"who\": \"Urza\"}", new File("a.json")));
        Assert.assertNull(DealQuestion.parse("{not json", new File("a.json")));
    }

    @Test
    public void listsOldestFirstAndSkipsMalformedFiles() throws Exception {
        final File dir = Files.createTempDirectory("questions").toFile();
        Files.write(new File(dir, "b-2-0.json").toPath(), FULL.replace("1789607879844-3-0", "b-2-0").replace("1789607879.9", "200").getBytes(StandardCharsets.UTF_8));
        Files.write(new File(dir, "a-1-0.json").toPath(), FULL.replace("1789607879844-3-0", "a-1-0").replace("1789607879.9", "100").getBytes(StandardCharsets.UTF_8));
        Files.write(new File(dir, "bad.json").toPath(), "{\"offer_id\": \"x\"".getBytes(StandardCharsets.UTF_8));
        Files.write(new File(dir, "note.txt").toPath(), FULL.getBytes(StandardCharsets.UTF_8));
        final List<DealQuestion> qs = DealQuestion.list(dir);
        Assert.assertEquals(qs.size(), 2);
        Assert.assertEquals(qs.get(0).offerId, "a-1-0", "the older offer is asked first");
        Assert.assertEquals(qs.get(1).offerId, "b-2-0");
        Assert.assertEquals(DealQuestion.list(new File(dir, "missing")).size(), 0, "no directory: no questions, no error");
    }
}
