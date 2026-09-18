package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

/** 2026-09-18: the one flat-JSON reader behind DealQuestion, AiControlFile and VoiceFocus. */
public class FlatJsonTest {

    @Test
    public void readsStringsNumbersAndNulls() {
        final String j = "{\"handle\": \"urza\", \"who\": \"Urza, Lord High \\\"Artificer\\\"\", \"n\": 12, \"m\": 1523.75, \"seat\": -1, "
                + "\"assessment\": null, \"text\": \"line one\\nline two \\u00e9\", \"until\": 1789099999123}";
        Assert.assertEquals(FlatJson.str(j, "handle"), "urza");
        Assert.assertEquals(FlatJson.str(j, "who"), "Urza, Lord High \"Artificer\"", "escaped quotes are read through");
        Assert.assertEquals(FlatJson.str(j, "text"), "line one\nline two \u00e9", "\\n and \\uXXXX unescape");
        Assert.assertNull(FlatJson.str(j, "assessment"), "a JSON null is null");
        Assert.assertNull(FlatJson.str(j, "missing"));
        Assert.assertEquals(FlatJson.numLong(j, "n", 0), 12);
        Assert.assertEquals(FlatJson.numLong(j, "m", 0), 1523, "the integer part of a decimal");
        Assert.assertEquals(FlatJson.numLong(j, "seat", 7), -1, "negatives read");
        Assert.assertEquals(FlatJson.numLong(j, "until", 0), 1789099999123L);
        Assert.assertEquals(FlatJson.numLong(j, "absent", 5), 5);
        Assert.assertEquals(FlatJson.num(j, "n", 0), 12);
        Assert.assertEquals(FlatJson.num(j, "until", 0), 0, "outside the int range: the default");
        Assert.assertEquals(FlatJson.dbl(j, "m", 0.0), 1523.75, 1e-9);
        Assert.assertEquals(FlatJson.dbl(j, "absent", 2.5), 2.5, 1e-9);
        Assert.assertNull(FlatJson.str(null, "x"));
        Assert.assertEquals(FlatJson.numLong(null, "x", 3), 3);
    }

    @Test
    public void aKeyInsideAStringValueCannotSpoofAField() {
        final String j = "{\"text\": \"say \\\"handle\\\": \\\"evil\\\" now\", \"handle\": \"rev\"}";
        Assert.assertEquals(FlatJson.str(j, "handle"), "rev");
    }

    @Test
    public void quoteRoundTripsThroughUnescape() {
        final String raw = "a \"quoted\" back\\slash\ttab\nnewline \u0001";
        final String q = FlatJson.quote(raw);
        Assert.assertTrue(q.startsWith("\"") && q.endsWith("\""));
        Assert.assertEquals(FlatJson.str("{\"v\": " + q + "}", "v"), raw);
    }
}
