package forge.arena.interactive;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * One seat's open deal offer to the player, as the advisor runner publishes it
 * (plan docs/reviews/2026-09-16-offer-dialog-plan.md §2): a file per offer under
 * {@code logs/control/deal/questions/<offer_id>.json}, rewritten once Joshua's
 * assessment lands, deleted when the offer is answered, lapses, the Executive
 * takes the seat, or the game ends. Pure data + flat regex (this module carries
 * no JSON dependency, like {@link AiControlFile}); unit-tested without a display.
 */
public final class DealQuestion {

    public final String offerId;
    public final int seat;
    public final String who;
    public final String handle;
    public final String terms;
    public final String text;
    public final int turn;
    public final int lapsesAfterTurn;
    public final String assessment;   // null until Joshua has spoken
    public final long ts;
    public final File file;

    DealQuestion(final String offerId, final int seat, final String who, final String handle, final String terms,
                 final String text, final int turn, final int lapsesAfterTurn, final String assessment, final long ts,
                 final File file) {
        this.offerId = offerId;
        this.seat = seat;
        this.who = who;
        this.handle = handle;
        this.terms = terms;
        this.text = text;
        this.turn = turn;
        this.lapsesAfterTurn = lapsesAfterTurn;
        this.assessment = assessment;
        this.ts = ts;
        this.file = file;
    }

    /** The questions directory under the runner's logs. */
    public static File dir() {
        return new File(AiControlFile.logsDir(), "control/deal/questions");
    }

    /** Every readable question in {@code dir}, oldest first (by ts, then name). Malformed files are skipped. */
    public static List<DealQuestion> list(final File dir) {
        final List<DealQuestion> out = new ArrayList<>();
        final File[] files = dir == null ? null : dir.listFiles((d, n) -> n.endsWith(".json"));
        if (files == null) {
            return out;
        }
        for (final File f : files) {
            try {
                final DealQuestion q = parse(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8), f);
                if (q != null) {
                    out.add(q);
                }
            } catch (IOException | RuntimeException e) {
                // a file mid-write or malformed: not this poll's business
            }
        }
        out.sort(Comparator.comparingLong((DealQuestion q) -> q.ts).thenComparing(q -> q.file.getName()));
        return out;
    }

    /** Null when the offer id or the handle is missing — nothing to answer to. */
    public static DealQuestion parse(final String json, final File f) {
        final String offerId = str(json, "offer_id");
        final String handle = str(json, "handle");
        if (offerId == null || offerId.isEmpty() || handle == null || handle.isEmpty()) {
            return null;
        }
        final String who = str(json, "who");
        return new DealQuestion(offerId, num(json, "seat", -1), who == null || who.isEmpty() ? handle : who, handle,
                orEmpty(str(json, "terms")), orEmpty(str(json, "text")), num(json, "turn", 0),
                num(json, "lapses_after_turn", 0), emptyToNull(str(json, "assessment")), numLong(json, "ts", 0L), f);
    }

    public String headline() {
        return who + " offers you " + terms;
    }

    public String lapseLine() {
        return lapsesAfterTurn > 0 ? "lapses at the end of turn " + lapsesAfterTurn : "";
    }

    /** The chat message the Accept button sends — exactly what the player would type. */
    public String acceptAsk() {
        return "@" + handle + " accept";
    }

    public String refuseAsk() {
        return "@" + handle + " no";
    }

    /** What the Counter… button puts in the chat field for the player to finish. */
    public String counterPrefix() {
        return "@" + handle + " ";
    }

    // ---- flat JSON readers

    private static final java.util.concurrent.ConcurrentHashMap<String, Pattern> STR_RE = new java.util.concurrent.ConcurrentHashMap<>();
    private static final java.util.concurrent.ConcurrentHashMap<String, Pattern> NUM_RE = new java.util.concurrent.ConcurrentHashMap<>();

    private static String str(final String json, final String key) {
        final Matcher m = STR_RE.computeIfAbsent(key,
                k -> Pattern.compile("\"" + Pattern.quote(k) + "\"\\s*:\\s*(null|\"((?:[^\"\\\\]|\\\\.)*)\")")).matcher(json);
        if (!m.find()) {
            return null;
        }
        if (m.group(2) == null) {
            return null;   // null
        }
        return unescape(m.group(2));
    }

    private static int num(final String json, final String key, final int dflt) {
        final long v = numLong(json, key, dflt);
        return v > Integer.MAX_VALUE || v < Integer.MIN_VALUE ? dflt : (int) v;
    }

    private static long numLong(final String json, final String key, final long dflt) {
        final Matcher m = NUM_RE.computeIfAbsent(key,
                k -> Pattern.compile("\"" + Pattern.quote(k) + "\"\\s*:\\s*(-?\\d+)(?:\\.\\d+)?")).matcher(json);
        if (!m.find()) {
            return dflt;
        }
        try {
            return Long.parseLong(m.group(1));
        } catch (final NumberFormatException e) {
            return dflt;
        }
    }

    static String unescape(final String s) {
        final StringBuilder sb = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            final char c = s.charAt(i);
            if (c != '\\' || i + 1 >= s.length()) {
                sb.append(c);
                continue;
            }
            final char n = s.charAt(++i);
            switch (n) {
                case 'n': sb.append('\n'); break;
                case 't': sb.append('\t'); break;
                case 'r': sb.append('\r'); break;
                case 'u':
                    if (i + 4 < s.length()) {
                        try {
                            sb.append((char) Integer.parseInt(s.substring(i + 1, i + 5), 16));
                            i += 4;
                            break;
                        } catch (final NumberFormatException e) {
                            // fall through: keep the literal
                        }
                    }
                    sb.append('u');
                    break;
                default: sb.append(n);   // \" \\ \/
            }
        }
        return sb.toString();
    }

    private static String orEmpty(final String s) {
        return s == null ? "" : s;
    }

    private static String emptyToNull(final String s) {
        return s == null || s.trim().isEmpty() ? null : s;
    }
}
