package forge.arena.interactive;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import org.testng.Assert;
import org.testng.annotations.Test;

/**
 * Engine-side auto-yield mirror (2026-09-07): the pure rule and the file
 * parser. Every guard the runner applies must hold, or the window opens.
 */
public class YieldMirrorTest {

    private static Set<String> opts(String... names) {
        return new HashSet<>(Arrays.asList(names));
    }

    private List<YieldMirror.Entry> published() throws Exception {
        Path f = Files.createTempFile("yield", ".json");
        Files.write(f, ("{\"seat\": 2, \"items\": [{\"turn\": 23, \"name\": \"Staff of Domination\", \"owner\": 0,"
                + " \"kind\": \"ability\", \"options\": [\"The One Ring\"], \"life\": 21, \"pool\": 0, \"untapped\": 0}]}")
                .getBytes(StandardCharsets.UTF_8));
        return YieldMirror.read(f);
    }

    @Test
    public void matchesOnlyWhenEveryGuardHolds() throws Exception {
        List<YieldMirror.Entry> e = published();
        Assert.assertEquals(e.size(), 1);
        Assert.assertTrue(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring"),
                21, 0, 0, false, false), "the exact yielded shape");
        Assert.assertTrue(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring"),
                25, 0, 0, false, false), "life UP is fine");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring"),
                19, 0, 0, false, false), "life down re-opens");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring"),
                21, 0, 2, false, false), "more untapped mana re-opens");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring"),
                21, 1, 0, false, false), "floating mana re-opens");
        Assert.assertFalse(YieldMirror.matches(e, 24, "Staff of Domination", 0, "ability", opts("The One Ring"),
                21, 0, 0, false, false), "next turn");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Selvala, Heart of the Wilds", 0, "ability", opts("The One Ring"),
                21, 0, 0, false, false), "a different top item");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 3, "ability", opts("The One Ring"),
                21, 0, 0, false, false), "a different owner");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring", "Chaos Warp"),
                21, 0, 0, false, false), "a new option");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring"),
                21, 0, 0, true, false), "a spell anywhere on the stack");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 0, "ability", opts("The One Ring"),
                21, 0, 0, false, true), "an item aimed at the seat");
        Assert.assertFalse(YieldMirror.matches(e, 23, "Staff of Domination", 0, "spell", opts("The One Ring"),
                21, 0, 0, false, false), "a spell on top never yields");
    }

    @Test
    public void missingOrBrokenFileYieldsNothing() throws Exception {
        Assert.assertTrue(YieldMirror.read(Path.of("/nonexistent/yield.json")).isEmpty());
        Path f = Files.createTempFile("yield", ".json");
        Files.write(f, "{not json".getBytes(StandardCharsets.UTF_8));
        Assert.assertTrue(YieldMirror.read(f).isEmpty());
        Assert.assertFalse(YieldMirror.matches(YieldMirror.read(f), 1, "X", 0, "ability", opts(), 40, 0, 0, false, false));
    }

    @Test
    public void optionNameIsTheLabelBeforeTheDoubleSpace() {
        Assert.assertEquals(YieldMirror.optionName("The One Ring  {T} — draw"), "The One Ring");
        Assert.assertEquals(YieldMirror.optionName("Pass (do nothing)"), "Pass (do nothing)");
        Assert.assertEquals(YieldMirror.optionName(null), "");
    }
}
