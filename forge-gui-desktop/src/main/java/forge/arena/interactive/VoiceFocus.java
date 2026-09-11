package forge.arena.interactive;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The match screen follows the voices (Ben, 2026-09-10: "can the focus of the
 * upper three tabs change as the voices activate and then return to whatever
 * it was on?"). The voice runner writes {@code logs/voice-speaking.json} —
 * {@code {"seat": N, "until": epochMillis, ...}} while one of the AI seats is
 * talking, {@code {}} otherwise. {@code VAdvisor} polls it four times a second,
 * brings that seat's field tab forward, and once the table has been quiet for
 * {@link #QUIET_MS} puts the tab the player had been looking at back — unless
 * they clicked elsewhere in the meantime. Joshua and the human never move the
 * tabs (the runner writes nothing for them). This class holds the parsing so it
 * can be tested without Swing; the tab work lives in the panel.
 */
public final class VoiceFocus {

    /** Silence this long after the last seat line = the exchange is over: restore. */
    public static final long QUIET_MS = 1500;
    /** A speaking record this far past its own end is stale (the runner died mid-line). */
    public static final long STALE_MS = 1500;

    private static final Pattern SEAT = Pattern.compile("\"seat\"\\s*:\\s*(\\d+)");
    private static final Pattern UNTIL = Pattern.compile("\"until\"\\s*:\\s*(\\d+)");
    /** A mailbox seat's field tab reads "mailbox-seat3-Purphoros, God of the Forge Field". */
    private static final Pattern TAB_SEAT = Pattern.compile("mailbox-seat(\\d)-");

    private VoiceFocus() {
    }

    /** {@code {seat, until}} from the speaking file, or {@code {-1, 0}} when nobody is talking or the text is unreadable. */
    public static long[] parseSpeaking(final String json) {
        if (json == null) {
            return new long[] {-1, 0};
        }
        final Matcher s = SEAT.matcher(json);
        final Matcher u = UNTIL.matcher(json);
        if (!s.find()) {
            return new long[] {-1, 0};
        }
        try {
            return new long[] {Long.parseLong(s.group(1)), u.find() ? Long.parseLong(u.group(1)) : 0};
        } catch (final NumberFormatException e) {
            return new long[] {-1, 0};
        }
    }

    /** The seat a field tab belongs to, read off its title; -1 for the human's field or anything else. */
    public static int seatOfTab(final String tabTitle) {
        if (tabTitle == null) {
            return -1;
        }
        final Matcher m = TAB_SEAT.matcher(tabTitle);
        return m.find() ? Integer.parseInt(m.group(1)) : -1;
    }

    /** A line still counts as playing until {@code until} plus a grace; after that the record is stale. */
    public static boolean speakingNow(final long[] speaking, final long nowMillis) {
        return speaking[0] >= 0 && nowMillis <= speaking[1] + STALE_MS;
    }

    /** The follow feature is on unless ARENA_VOICE_FOCUS=off. */
    public static boolean enabled(final String envValue) {
        return !"off".equalsIgnoreCase(String.valueOf(envValue == null ? "" : envValue).trim());
    }
}
