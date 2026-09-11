package forge.arena.interactive;

import org.testng.Assert;
import org.testng.annotations.Test;

/** 2026-09-10: the match tabs follow the seat that is talking (VoiceFocus parsing). */
public class VoiceFocusTest {

    @Test(groups = "extended", timeOut = 30_000)
    public void speakingFileAndTabTitlesParse() {
        Assert.assertEquals(VoiceFocus.parseSpeaking("{\"seat\": 3, \"library\": \"harry\", \"stock\": \"big-swing\", \"until\": 1789099999123}"),
                new long[] {3, 1789099999123L});
        Assert.assertEquals(VoiceFocus.parseSpeaking("{}"), new long[] {-1, 0}, "nobody talking");
        Assert.assertEquals(VoiceFocus.parseSpeaking(null), new long[] {-1, 0});
        Assert.assertEquals(VoiceFocus.parseSpeaking("garbage"), new long[] {-1, 0});
        Assert.assertEquals(VoiceFocus.seatOfTab("Purphoros, God of the Forge-S3 Field"), 3);
        Assert.assertEquals(VoiceFocus.seatOfTab("Urza, Lord High Artificer-S1 Field"), 1);
        Assert.assertEquals(VoiceFocus.seatOfTab("mailbox-seat3-Purphoros, God of the Forge Field"), 3, "the old naming still parses");
        Assert.assertEquals(VoiceFocus.seatOfTab("Player One Field"), -1, "the human's field is never followed");
        Assert.assertEquals(VoiceFocus.seatOfTab("Human Field"), -1);
        Assert.assertEquals(VoiceFocus.seatOfTab(null), -1);
    }

    @Test(groups = "extended", timeOut = 30_000)
    public void staleRecordsAndTheKnob() {
        final long[] rec = {2, 10_000};
        Assert.assertTrue(VoiceFocus.speakingNow(rec, 9_000));
        Assert.assertTrue(VoiceFocus.speakingNow(rec, 10_000 + VoiceFocus.STALE_MS), "a grace after the line ends");
        Assert.assertFalse(VoiceFocus.speakingNow(rec, 10_000 + VoiceFocus.STALE_MS + 1), "then the record is stale (runner died mid-line)");
        Assert.assertFalse(VoiceFocus.speakingNow(new long[] {-1, 0}, 5));
        Assert.assertTrue(VoiceFocus.enabled(null)); Assert.assertTrue(VoiceFocus.enabled("on")); Assert.assertTrue(VoiceFocus.enabled(""));
        Assert.assertFalse(VoiceFocus.enabled("off")); Assert.assertFalse(VoiceFocus.enabled(" OFF "));
    }
}
