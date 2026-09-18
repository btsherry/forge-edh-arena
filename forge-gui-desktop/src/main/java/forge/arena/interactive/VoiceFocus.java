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
 * (Ben, 2026-09-16) — unless the player clicked elsewhere in the meantime. On the HUMAN'S OWN TURN the
 * tabs never move (Ben, 2026-09-18: a seat speaking while the player casts pulled the board away
 * mid-payment, game 59). This class holds the parsing and the rules so they can be tested without
 * Swing; the tab work lives in the panel.
 */
public final class VoiceFocus {

    /** Silence this long after the last seat line = the exchange is over: restore. */
    public static final long QUIET_MS = 1500;
    /** A speaking record this far past its own end is stale (the runner died mid-line). */
    public static final long STALE_MS = 1500;

    /** A seat's field tab reads "Purphoros, God of the Forge-S3 Field" (2026-09-10 naming);
     *  the older "mailbox-seat3-…" form is still recognised. */
    private static final Pattern TAB_SEAT = Pattern.compile("-S(\\d)\\b");
    private static final Pattern TAB_SEAT_OLD = Pattern.compile("mailbox-seat(\\d)-");

    private VoiceFocus() {
    }

    /** {@code {seat, until}} from the speaking file, or {@code {-1, 0}} when nobody is talking or the text is unreadable. */
    public static long[] parseSpeaking(final String json) {
        final long seat = FlatJson.numLong(json, "seat", -1);
        if (seat < 0) {
            return new long[] {-1, 0};
        }
        return new long[] {seat, FlatJson.numLong(json, "until", 0)};
    }

    /** The active player's seat from the speaking file ({@code "active": N}, written whether or not anyone
     *  is talking — Ben, 2026-09-16: the screen goes back to the active player's board, not to wherever the
     *  player had been), or -1 when the file does not say. */
    public static int parseActive(final String json) {
        return FlatJson.num(json, "active", -1);
    }

    /** Whether the tabs may follow a speaking seat right now: never during the human's own turn at a human
     *  table (seat 0 active), always on an all-AI table, where seat 0 is a brain like the others. */
    public static boolean followsNow(final int activeSeat, final boolean humanGame) {
        return !(humanGame && activeSeat == 0);
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
