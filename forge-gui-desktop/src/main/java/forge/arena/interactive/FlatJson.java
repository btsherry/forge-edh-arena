package forge.arena.interactive;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The one flat-JSON reader for the arena's file protocol on the GUI side. The runners write small,
 * flat JSON objects (control files, the offer pane's questions, the voice's speaking file, the
 * per-seat usage and ELO digests); this package deliberately carries no JSON dependency, so the
 * fields are read by anchored regular expressions on the raw text. Until 2026-09-18 three classes
 * each carried their own copy of these readers ({@code DealQuestion}, {@code AiControlFile},
 * {@code VoiceFocus}); the hygiene pass folded them here, behaviour unchanged, the string reader
 * being the only one of the three that understood escapes and {@code null}.
 *
 * <p>A key is matched as a top-level-looking {@code "key": value} pair. A key that appears inside
 * a string value cannot spoof a field, because the writer escapes the quote that the pattern
 * needs bare. Patterns are compiled once per key.
 */
final class FlatJson {

    private static final Map<String, Pattern> STR = new ConcurrentHashMap<>();
    private static final Map<String, Pattern> INT = new ConcurrentHashMap<>();
    private static final Map<String, Pattern> DBL = new ConcurrentHashMap<>();

    private FlatJson() {
    }

    /** The string value of {@code key}, unescaped; {@code null} for a missing key or a JSON {@code null}. */
    static String str(final String json, final String key) {
        if (json == null) {
            return null;
        }
        final Matcher m = STR.computeIfAbsent(key,
                k -> Pattern.compile("\"" + Pattern.quote(k) + "\"\\s*:\\s*(null|\"((?:[^\"\\\\]|\\\\.)*)\")")).matcher(json);
        if (!m.find() || m.group(2) == null) {
            return null;
        }
        return unescape(m.group(2));
    }

    /** The integer part of the number at {@code key}, or {@code dflt} when missing or unparseable. */
    static long numLong(final String json, final String key, final long dflt) {
        if (json == null) {
            return dflt;
        }
        final Matcher m = INT.computeIfAbsent(key,
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

    /** {@link #numLong} narrowed to an int; a value outside the int range yields {@code dflt}. */
    static int num(final String json, final String key, final int dflt) {
        final long v = numLong(json, key, dflt);
        return v > Integer.MAX_VALUE || v < Integer.MIN_VALUE ? dflt : (int) v;
    }

    /** The number at {@code key} as a double, or {@code dflt} when missing or unparseable. */
    static double dbl(final String json, final String key, final double dflt) {
        if (json == null) {
            return dflt;
        }
        final Matcher m = DBL.computeIfAbsent(key,
                k -> Pattern.compile("\"" + Pattern.quote(k) + "\"\\s*:\\s*(-?[\\d.]+)")).matcher(json);
        if (!m.find()) {
            return dflt;
        }
        try {
            return Double.parseDouble(m.group(1));
        } catch (final NumberFormatException e) {
            return dflt;
        }
    }

    /** JSON string escapes undone: {@code \\n \\t \\r \\uXXXX} and the pass-through pairs ({@code \" \\ \/}). */
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

    /** A minimal JSON string literal: quotes and backslashes escaped, control characters as {@code \\uXXXX}. */
    static String quote(final String s) {
        final StringBuilder sb = new StringBuilder(s.length() + 2).append('"');
        for (int i = 0; i < s.length(); i++) {
            final char c = s.charAt(i);
            if (c == '"') {
                sb.append("\\\"");
            } else if (c == '\\') {
                sb.append("\\\\");
            } else if (c < 0x20) {
                sb.append(String.format("\\u%04x", (int) c));
            } else {
                sb.append(c);
            }
        }
        return sb.append('"').toString();
    }
}
