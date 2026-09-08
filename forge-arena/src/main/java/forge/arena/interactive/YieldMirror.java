package forge.arena.interactive;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Engine-side mirror of the seat runner's auto-yield (Ben's step 3,
 * 2026-09-07). The runner publishes the yields it has decided this turn to
 * {@code mailbox/seat-N/yield.json}: one entry per (turn, top-of-stack item
 * name, owner seat, kind, option-name set) with the seat's life, mana pool
 * and untapped-source count at the yield. When the engine is about to open a
 * REACTIVE window whose top item matches an entry and every guard the runner
 * would apply still holds — same turn, no spell anywhere on the stack, no
 * opponent item aimed at this seat, life not down, pool and untapped sources
 * not up, identical option names — the runner would answer "pass" without a
 * model call anyway. The engine passes directly and saves the mailbox round
 * trip (request file, poll, answer file: ~0.3 s).
 *
 * <p>Conservative by construction: any missing file, parse problem, extra
 * option, or failed guard opens the window as before. Every mirrored pass is
 * logged to stderr and appended to {@code runner/logs/engine-events.jsonl}
 * ({@code kind: "yield-mirror"}) so the count is visible in
 * {@code scripts/arena-status.py}. {@link #matches} is the pure rule, tested
 * without an engine.
 */
public final class YieldMirror {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    /** Mirrored passes this JVM (tests, dashboards). */
    public static final AtomicInteger MIRRORED = new AtomicInteger();

    private YieldMirror() {
    }

    /** One published yield. */
    public static final class Entry {
        public final int turn;
        public final String name;
        public final int owner;
        public final String kind;
        public final Set<String> options;
        public final int life;
        public final int pool;
        public final int untapped;

        Entry(int turn, String name, int owner, String kind, Set<String> options, int life, int pool, int untapped) {
            this.turn = turn;
            this.name = name;
            this.owner = owner;
            this.kind = kind;
            this.options = options;
            this.life = life;
            this.pool = pool;
            this.untapped = untapped;
        }
    }

    /** Parse {@code yield.json}; empty on any problem. */
    public static List<Entry> read(Path yieldFile) {
        List<Entry> out = new ArrayList<>();
        try {
            if (yieldFile == null || !Files.exists(yieldFile)) {
                return out;
            }
            JsonNode root = MAPPER.readTree(Files.readAllBytes(yieldFile));
            JsonNode items = root == null ? null : root.get("items");
            if (items == null || !items.isArray()) {
                return out;
            }
            for (JsonNode it : items) {
                Set<String> opts = new HashSet<>();
                JsonNode o = it.get("options");
                if (o != null && o.isArray()) {
                    for (JsonNode s : o) {
                        opts.add(s.asText());
                    }
                }
                if (!it.hasNonNull("turn") || !it.hasNonNull("name") || !it.hasNonNull("owner")
                        || !it.hasNonNull("kind") || !it.hasNonNull("life")) {
                    continue;
                }
                out.add(new Entry(it.get("turn").asInt(), it.get("name").asText(), it.get("owner").asInt(),
                        it.get("kind").asText(), opts, it.get("life").asInt(),
                        it.path("pool").asInt(0), it.path("untapped").asInt(0)));
            }
        } catch (IOException | RuntimeException e) {
            return Collections.emptyList();
        }
        return out;
    }

    /**
     * The pure rule. True iff some entry matches this window and every guard
     * holds. {@code optionNames} are the window's non-pass option names (the
     * label before the double space), {@code anySpellOnStack} and
     * {@code threatened} are computed by the caller from the live stack.
     */
    public static boolean matches(List<Entry> entries, int turn, String topName, int topOwner, String topKind,
            Set<String> optionNames, int life, int pool, int untapped, boolean anySpellOnStack, boolean threatened) {
        if (entries == null || entries.isEmpty() || topName == null || anySpellOnStack || threatened) {
            return false;
        }
        if ("spell".equals(topKind)) {
            return false;
        }
        for (Entry e : entries) {
            if (e.turn != turn || e.owner != topOwner || !e.name.equals(topName) || !e.kind.equals(topKind)) {
                continue;
            }
            if (!e.options.equals(optionNames)) {
                continue;
            }
            if (life < e.life || pool > e.pool || untapped > e.untapped) {
                continue;
            }
            return true;
        }
        return false;
    }

    /** The option name the runner keys on: the label before the double space. */
    public static String optionName(String label) {
        if (label == null) {
            return "";
        }
        int i = label.indexOf("  ");
        return i >= 0 ? label.substring(0, i) : label;
    }

    /** Record one mirrored pass: counter, stderr, engine-events.jsonl. */
    public static void note(int seat, int turn, String topName, String gameId) {
        MIRRORED.incrementAndGet();
        System.err.println("yield-mirror: seat " + seat + " t" + turn + " passed on " + topName
                + " without a window (runner had yielded it)");
        try {
            Path log = ExecutiveSwitch.logsDir().resolve("engine-events.jsonl");
            Files.createDirectories(log.getParent());
            String line = "{\"ts\":" + System.currentTimeMillis() + ",\"kind\":\"yield-mirror\",\"seat\":" + seat
                    + ",\"turn\":" + turn + ",\"top\":" + MAPPER.writeValueAsString(topName)
                    + ",\"gameId\":" + MAPPER.writeValueAsString(gameId) + "}\n";
            Files.write(log, line.getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException | RuntimeException ignored) {
            // visibility only
        }
    }
}
