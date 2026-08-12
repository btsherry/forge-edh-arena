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

    public static final String[] MODELS = {"haiku", "sonnet", "opus", "fable"};
    public static final String[] EFFORTS = {"low", "medium", "high", "xhigh", "max"};

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

    /** Cycle model (isModel=true) or effort by dir (+1/-1), clamped, and persist. */
    public static void step(final int seat, final boolean isModel, final int dir) {
        final File f = controlFile(seat);
        final String[] cycle = isModel ? MODELS : EFFORTS;
        final String cur = find(f, isModel ? MODEL_RE : EFFORT_RE,
                cycle[dir > 0 ? 0 : cycle.length - 1]);
        int idx = 0;
        for (int i = 0; i < cycle.length; i++) {
            if (cycle[i].equals(cur)) { idx = i; break; }
        }
        final String next = cycle[Math.max(0, Math.min(cycle.length - 1, idx + dir))];
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
        return String.format("%d calls · %s out · %s · ≈$%.2f API-equiv",
                calls, human(out), cacheStr, cost);
    }

    /** Table-wide totals across all four seats, or {@code null} if none live. */
    public static String tableTotals() {
        long calls = 0, out = 0;
        double cost = 0;
        boolean any = false;
        for (int n = 0; n < 4; n++) {
            final File u = usageFile(n);
            try {
                final String body = new String(Files.readAllBytes(u.toPath()), StandardCharsets.UTF_8);
                calls += usageLong(body, "calls");
                out += usageLong(body, "output_tokens");
                cost += usageDouble(body, "cost_usd");
                any = true;
            } catch (final IOException ignored) {
                // seat offline — skip
            }
        }
        return any ? String.format("TABLE: %d calls · %s out · ≈$%.2f API-equiv (subscription — $0 actual)",
                calls, human(out), cost) : null;
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
