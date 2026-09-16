package forge.arena.interactive;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The match screen follows the voices (Ben, 2026-09-10: "can the focus of the
 * upper three tabs change as the voices activate and then return to whatever
 * it was on?"). The voice runner writes {@code logs/voice-speaking.json} —
 * {@code {"seat": N, "until": epochMillis, ...}} while one of the AI seats is
 * saying something worth looking at, {@code {"active": A}} otherwise (the runner
 * writes nothing for filler, atoms, Joshua or the human). {@code VAdvisor} polls
 * it four times a second, brings that seat's field tab forward, and once the
 * table has been quiet for {@link #QUIET_MS} shows the ACTIVE player's field
 * (Ben, 2026-09-16) — unless the player clicked elsewhere in the meantime. This class holds the parsing so it
 * can be tested without Swing; the tab work lives in the panel.
 */
public final class VoiceFocus {

    /** Silence this long after the last seat line = the exchange is over: restore. */
    public static final long QUIET_MS = 1500;
    /** A speaking record this far past its own end is stale (the runner died mid-line). */
    public static final long STALE_MS = 1500;

    private static final Pattern SEAT = Pattern.compile("\"seat\"\\s*:\\s*(\\d+)");
    private static final Pattern UNTIL = Pattern.compile("\"until\"\\s*:\\s*(\\d+)");
    private static final Pattern ACTIVE = Pattern.compile("\"active\"\\s*:\\s*(\\d+)");
    /** A seat's field tab reads "Purphoros, God of the Forge-S3 Field" (2026-09-10 naming);
     *  the older "mailbox-seat3-…" form is still recognised. */
    private static final Pattern TAB_SEAT = Pattern.compile("-S(\\d)\\b");
    private static final Pattern TAB_SEAT_OLD = Pattern.compile("mailbox-seat(\\d)-");

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

    /** The active player's seat from the speaking file ({@code "active": N}, written whether or not anyone
     *  is talking — Ben, 2026-09-16: the screen goes back to the active player's board, not to wherever the
     *  player had been), or -1 when the file does not say. */
    public static int parseActive(final String json) {
        if (json == null) {
            return -1;
        }
        final Matcher a = ACTIVE.matcher(json);
        try {
            return a.find() ? Integer.parseInt(a.group(1)) : -1;
        } catch (final NumberFormatException e) {
            return -1;
        }
    }

    /** The seat a field tab belongs to, read off its title; -1 for the human's field or anything else. */
    public static int seatOfTab(final String tabTitle) {
        if (tabTitle == null) {
            return -1;
        }
        final Matcher m = TAB_SEAT.matcher(tabTitle);
        if (m.find()) {
            return Integer.parseInt(m.group(1));
        }
        final Matcher old = TAB_SEAT_OLD.matcher(tabTitle);
        return old.find() ? Integer.parseInt(old.group(1)) : -1;
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
