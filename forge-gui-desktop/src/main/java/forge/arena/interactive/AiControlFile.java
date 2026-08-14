package forge.arena.interactive;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Pure (Swing-free) read/write of the seatd control files that the AI dock
 * tab and {@code arena-ctl.py} share:
 * {@code <logsDir>/control/seat-N.json = {"model":..,"effort":..}}.
 *
 * The runner is the reconciler; writers here just publish desired values,
 * atomically (temp + ATOMIC_MOVE) in the exact shape the runner honors. Kept
 * out of the view class so the logic is unit-testable without a display.
 */
public final class AiControlFile {

    private static final String[] DEFAULT_MODELS = {"haiku", "sonnet", "opus", "fable"};
    public static final String[] EFFORTS = {"low", "medium", "high", "xhigh", "max"};

    /**
     * Dial cycle: the four Claude names plus any {@code -Darena.extra.models}
     * entries (comma-separated backend model strings, whitelisted upstream by
     * run-pilot-match.sh so {@link #write} can never be fed a quote).
     * Recomputed per call — like {@link #logsDir()} — so headless tests can
     * inject the property at runtime.
     */
    public static String[] models() {
        final String extra = System.getProperty("arena.extra.models", "");
        if (extra.isEmpty()) {
            return DEFAULT_MODELS.clone();
        }
        final java.util.LinkedHashSet<String> out =
                new java.util.LinkedHashSet<>(java.util.Arrays.asList(DEFAULT_MODELS));
        for (final String s : extra.split(",")) {
            if (s.matches("[A-Za-z0-9._:/-]+")) {
                out.add(s);
            }
        }
        return out.toArray(new String[0]);
    }

    /**
     * Display form for the AI panel's narrow model column: backend strings
     * shorten to {@code or:<last-segment>} / {@code oai:<last-segment>} so
     * or/ and oai/ variants of one model stay distinguishable; Claude names
     * pass through untouched. The full string belongs in the tooltip.
     */
    public static String displayModel(final String raw) {
        if (raw == null || !(raw.startsWith("or/") || raw.startsWith("oai/"))) {
            return raw;
        }
        final String prefix = raw.startsWith("or/") ? "or:" : "oai:";
        return prefix + raw.substring(raw.lastIndexOf('/') + 1);
    }

    private static final Pattern MODEL_RE = Pattern.compile("\"model\"\\s*:\\s*\"([^\"]+)\"");
    private static final Pattern EFFORT_RE = Pattern.compile("\"effort\"\\s*:\\s*\"([^\"]+)\"");

    private AiControlFile() {
    }

    /** Runner logs dir: {@code -Darena.runner.logs.dir}, else &lt;cwd&gt;/../forge-arena/runner/logs. */
    public static File logsDir() {
        final String prop = System.getProperty("arena.runner.logs.dir");
        if (prop != null && !prop.isEmpty()) {
            return new File(prop);
        }
        return new File(new File(System.getProperty("user.dir")).getParentFile(),
                "forge-arena/runner/logs");
    }

    public static File controlFile(final int seat) {
        return new File(logsDir(), "control/seat-" + seat + ".json");
    }

    public static File usageFile(final int seat) {
        return new File(logsDir(), "seat-" + seat + ".usage.json");
    }

    public static String model(final int seat, final String dflt) {
        return find(controlFile(seat), MODEL_RE, dflt);
    }

    public static String effort(final int seat, final String dflt) {
        return find(controlFile(seat), EFFORT_RE, dflt);
    }

    /**
     * Index a step would land on, or -1 when the click would be a no-op:
     * current value out-of-cycle (e.g. a backend model this JVM wasn't told
     * about — plan F-11), or already clamped at the cycle end. The panel uses
     * the same predicate to HIDE no-op buttons instead of rendering dead ones.
     */
    private static int stepIndex(final String[] cycle, final String cur, final int dir) {
        int idx = -1;
        for (int i = 0; i < cycle.length; i++) {
            if (cycle[i].equals(cur)) { idx = i; break; }
        }
        if (idx < 0) {
            return -1;
        }
        final int next = Math.max(0, Math.min(cycle.length - 1, idx + dir));
        return next == idx ? -1 : next;
    }

    /** Would a step actually change the value? (false = the button is dead) */
    public static boolean canStep(final int seat, final boolean isModel, final int dir) {
        final String[] cycle = isModel ? models() : EFFORTS;
        final String cur = find(controlFile(seat), isModel ? MODEL_RE : EFFORT_RE,
                cycle[dir > 0 ? 0 : cycle.length - 1]);
        return stepIndex(cycle, cur, dir) >= 0;
    }

    /** Cycle model (isModel=true) or effort by dir (+1/-1), clamped, and persist. */
    public static void step(final int seat, final boolean isModel, final int dir) {
        final File f = controlFile(seat);
        final String[] cycle = isModel ? models() : EFFORTS;
        final String cur = find(f, isModel ? MODEL_RE : EFFORT_RE,
                cycle[dir > 0 ? 0 : cycle.length - 1]);
        final int nextIdx = stepIndex(cycle, cur, dir);
        if (nextIdx < 0) {
            return; // no-op click: out-of-cycle value or clamped end
        }
        final String next = cycle[nextIdx];
        final String model = isModel ? next : find(f, MODEL_RE, "sonnet");
        final String effort = isModel ? find(f, EFFORT_RE, "low") : next;
        write(seat, model, effort);
    }

    public static void write(final int seat, final String model, final String effort) {
        final File f = controlFile(seat);
        try {
            f.getParentFile().mkdirs();
            final File tmp = new File(f.getParentFile(), f.getName() + ".tmp");
            Files.write(tmp.toPath(), String.format(
                    "{\"model\": \"%s\", \"effort\": \"%s\"}", model, effort)
                    .getBytes(StandardCharsets.UTF_8));
            Files.move(tmp.toPath(), f.toPath(), StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE);
        } catch (final IOException ignored) {
            // runner absent / dir unwritable — the tab's refresh will show offline
        }
    }

    // ---- advisor on/off toggle (plan §13b) ---------------------------------

    /** logs/control/advisor.json — written by the Advisor tab's button,
     *  honored by advisor_runner at its next poll. Missing file = enabled
     *  (the launch default; arena-stop clears control/, so every session
     *  starts enabled). */
    public static File advisorToggleFile() {
        return new File(logsDir(), "control/advisor.json");
    }

    public static boolean advisorEnabled() {
        final File f = advisorToggleFile();
        if (!f.exists()) {
            return true;
        }
        try {
            final String s = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
            return !s.contains("false");
        } catch (final IOException e) {
            return true;
        }
    }

    public static void setAdvisorEnabled(final boolean enabled) {
        final File f = advisorToggleFile();
        try {
            f.getParentFile().mkdirs();
            final File tmp = new File(f.getParentFile(), f.getName() + ".tmp");
            Files.write(tmp.toPath(),
                    ("{\"enabled\": " + enabled + "}").getBytes(StandardCharsets.UTF_8));
            Files.move(tmp.toPath(), f.toPath(), StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE);
        } catch (final IOException ignored) {
            // runner absent / dir unwritable — button click shows no effect
        }
    }

    // ---- ELO digest line (plan §13.4; flat regex only — no JSON dependency) --

    /** Per-seat ELO line from logs/elo/seat-N.json, or {@code null} if the
     *  applier has not rated a game for this seat yet. */
    public static String eloSummary(final int seat) {
        final File f = new File(logsDir(), "elo/seat-" + seat + ".json");
        final String body;
        try {
            body = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
        } catch (final IOException e) {
            return null;
        }
        final double m = usageDouble(body, "m");
        final double d = usageDouble(body, "d");
        final double md = usageDouble(body, "md");
        final long n = usageLong(body, "n");
        final Matcher pm = Pattern.compile("\"pilot\"\\s*:\\s*\"([^\"]+)\"").matcher(body);
        final String pilot = pm.find() ? pm.group(1) : "?";
        return String.format("ELO  pilot %.0f · deck %.0f · pair %.0f · n=%d (%s)",
                m, d, md, n, displayModel(pilot));
    }

    /** Age in ms of the seat's usage snapshot (Long.MAX_VALUE if none) — liveness. */
    public static long usageAgeMillis(final int seat) {
        final File u = usageFile(seat);
        return u.exists() ? System.currentTimeMillis() - u.lastModified() : Long.MAX_VALUE;
    }

    // ---- token/cost telemetry (from seat-N.usage.json) ---------------------

    private static long usageLong(final String body, final String key) {
        final Matcher m = Pattern.compile("\"" + key + "\"\\s*:\\s*(-?\\d+)").matcher(body);
        return m.find() ? Long.parseLong(m.group(1)) : 0L;
    }

    private static double usageDouble(final String body, final String key) {
        final Matcher m = Pattern.compile("\"" + key + "\"\\s*:\\s*(-?[\\d.]+)").matcher(body);
        return m.find() ? Double.parseDouble(m.group(1)) : 0.0;
    }

    /** Compact per-seat usage line, or {@code null} if no snapshot yet. */
    public static String usageSummary(final int seat) {
        final File u = usageFile(seat);
        final String body;
        try {
            body = new String(Files.readAllBytes(u.toPath()), StandardCharsets.UTF_8);
        } catch (final IOException e) {
            return null;
        }
        final long calls = usageLong(body, "calls");
        final long out = usageLong(body, "output_tokens");
        final long read = usageLong(body, "cache_read_input_tokens");
        final long write = usageLong(body, "cache_creation_input_tokens");
        final double cost = usageDouble(body, "cost_usd");
        final long cacheDenom = read + write;
        final String cacheStr = cacheDenom > 0
                ? Math.round(100.0 * read / cacheDenom) + "% cache" : "—";
        // Backend seats bill real dollars — never relabel them as
        // subscription-equivalent (plan F-35). Claude seats keep the exact
        // wording they have always had.
        final String costWord = body.contains("\"backend\"")
                ? "API-BILLED" : "API-equiv";
        return String.format("%d calls · %s out · %s · ≈$%.2f %s",
                calls, human(out), cacheStr, cost, costWord);
    }

    /** Table-wide totals across all four seats, or {@code null} if none live. */
    public static String tableTotals() {
        long calls = 0, out = 0;
        double covered = 0, billed = 0;
        boolean any = false;
        for (int n = 0; n < 4; n++) {
            final File u = usageFile(n);
            try {
                final String body = new String(Files.readAllBytes(u.toPath()), StandardCharsets.UTF_8);
                calls += usageLong(body, "calls");
                out += usageLong(body, "output_tokens");
                if (body.contains("\"backend\"")) {
                    billed += usageDouble(body, "cost_usd");
                } else {
                    covered += usageDouble(body, "cost_usd");
                }
                any = true;
            } catch (final IOException ignored) {
                // seat offline — skip
            }
        }
        if (!any) {
            return null;
        }
        // All-Claude tables keep the exact historical wording; mixed tables
        // split real dollars out so they are never shown as "$0 actual".
        final String costStr = billed > 0
                ? String.format("≈$%.2f subscription + $%.2f API-BILLED", covered, billed)
                : String.format("≈$%.2f API-equiv (subscription — $0 actual)", covered);
        return String.format("TABLE: %d calls · %s out · %s",
                calls, human(out), costStr);
    }

    private static String human(final long n) {
        return n >= 1000 ? String.format("%.1fk", n / 1000.0) : String.valueOf(n);
    }

    private static String find(final File f, final Pattern p, final String dflt) {
        try {
            final String s = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
            final Matcher m = p.matcher(s);
            return m.find() ? m.group(1) : dflt;
        } catch (final IOException | RuntimeException e) {
            return dflt;
        }
    }
}
