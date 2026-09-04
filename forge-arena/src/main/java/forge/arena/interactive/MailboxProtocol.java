package forge.arena.interactive;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The file bus for a mailbox seat (the "mailbox" transport). Each seat owns a
 * base directory with two subdirs:
 *
 * <pre>
 *   &lt;base&gt;/seat-&lt;id&gt;/inbox/   ← the ENGINE writes req-&lt;n&gt;.json here
 *   &lt;base&gt;/seat-&lt;id&gt;/outbox/  ← the BRAIN writes resp-&lt;n&gt;.json here
 * </pre>
 *
 * <p>The engine calls {@link #exchange(Request)}: it writes the request into
 * {@code inbox/} (atomically — temp file then rename, so a reader never sees a
 * half-written file), then block-polls {@code outbox/resp-&lt;n&gt;.json} every
 * {@link #pollMillis} ms until it parses as JSON or the timeout expires. On a
 * successful read the response file is deleted and the parsed node returned; on
 * timeout {@code null} is returned so the caller can fall back to stock AI. A
 * response that does not yet parse (a partial write) is treated as "not ready"
 * and polling continues.
 *
 * <p>Configuration (system properties):
 * <ul>
 *   <li>{@code arena.mailbox.dir} — base directory (default {@code forge-arena/mailbox}).</li>
 *   <li>{@code arena.mailbox.timeout.sec} — per-decision wait (default 300).</li>
 * </ul>
 *
 * <p>No Forge imports — this is pure transport, deliberately decoupled from the
 * game engine so the same bus could carry any decision protocol.
 */
public final class MailboxProtocol {

    /** System property naming the bus base directory. */
    public static final String DIR_PROPERTY = "arena.mailbox.dir";
    /** System property for the per-decision timeout, in seconds. */
    public static final String TIMEOUT_PROPERTY = "arena.mailbox.timeout.sec";

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final long DEFAULT_TIMEOUT_SEC = 300L;

    /** System property: heartbeat staleness (ms) beyond which the brain is
     *  treated as absent and stock plays at once (item 12). Default 15 s —
     *  well above the runner's 5 s beat and its 2 s restart loop. */
    public static final String HEARTBEAT_STALE_PROPERTY = "arena.mailbox.heartbeat.stale.ms";

    /** Age in ms of {@code <seatDir>/heartbeat}, or -1 when there is no file. */
    public static long heartbeatAgeMillis(Path seatDir) {
        try {
            Path hb = seatDir.resolve("heartbeat");
            if (!Files.exists(hb)) {
                return -1L;
            }
            return System.currentTimeMillis() - Files.getLastModifiedTime(hb).toMillis();
        } catch (IOException | RuntimeException e) {
            return -1L;
        }
    }

    /** Liveness verdict for a seat dir: TRUE fresh, FALSE stale, null unknown
     *  (no heartbeat file — a pre-item-12 runner, or none launched). */
    public static Boolean brainAlive(Path seatDir) {
        long age = heartbeatAgeMillis(seatDir);
        if (age < 0) {
            return null;
        }
        return age <= Long.getLong(HEARTBEAT_STALE_PROPERTY, 15_000L);
    }

    private final Path seatDir;
    private final Path inbox;
    private final Path outbox;
    private final long timeoutMillis;
    private boolean absentLogged = false;
    // Outbox pickup latency: how soon the engine notices the brain's written
    // response and unblocks. 75ms keeps the game feeling responsive without
    // meaningful CPU cost (the poll is a single file stat on a tiny dir).
    // Overridable via -Darena.mailbox.poll.ms (harness-boil B1, 2026-08-28):
    // the test suite sets 5ms so every mailbox exchange in an E2E test stops
    // paying live-game pacing; live launches never set it and keep 75.
    private final long pollMillis = Long.getLong("arena.mailbox.poll.ms", 75L);
    private final AtomicLong seq = new AtomicLong();
    /** Interactive plan item 8: the game this bus serves, stamped on every
     *  request so the brain resets on an id CHANGE, never on a seq guess. */
    private volatile String gameId;

    /** Set once by the controller when the in-game Player (and thus the Game) exists. */
    public void setGameId(String id) {
        this.gameId = id;
    }

    private MailboxProtocol(Path seatDir, long timeoutMillis) {
        this.seatDir = seatDir;
        this.inbox = seatDir.resolve("inbox");
        this.outbox = seatDir.resolve("outbox");
        this.timeoutMillis = timeoutMillis;
        try {
            Files.createDirectories(inbox);
            Files.createDirectories(outbox);
        } catch (IOException e) {
            throw new IllegalStateException("cannot create mailbox dirs under " + seatDir, e);
        }
        sweepOutbox();
    }

    /** BL-22: nothing legitimate can be in the outbox before this bus writes
     *  its first request, so a leftover {@code resp-N.json} (a crashed engine,
     *  a hand relaunch that skipped arena-stop) is deleted here rather than
     *  consumed as the answer to this game's request N. */
    private void sweepOutbox() {
        int n = 0;
        try (java.nio.file.DirectoryStream<Path> ds = Files.newDirectoryStream(outbox)) {
            for (Path p : ds) {
                String name = p.getFileName().toString();
                if (name.startsWith("resp-") || name.endsWith(".tmp")) {
                    deleteQuietly(p);
                    n++;
                }
            }
        } catch (IOException ignore) {
            // best effort — the sweep is protection, never a precondition
        }
        if (n > 0) {
            System.err.println("[mailbox " + seatDir.getFileName() + "] swept " + n
                    + " stale outbox file(s) at start");
        }
    }

    /** Resolve the bus base dir from {@link #DIR_PROPERTY} (default forge-arena/mailbox). */
    public static Path baseDir() {
        String prop = System.getProperty(DIR_PROPERTY);
        return prop != null ? Path.of(prop) : Path.of("forge-arena", "mailbox");
    }

    /** Per-decision timeout from {@link #TIMEOUT_PROPERTY} (default 300s). */
    public static long timeoutSeconds() {
        String prop = System.getProperty(TIMEOUT_PROPERTY);
        if (prop != null) {
            try {
                return Long.parseLong(prop.trim());
            } catch (NumberFormatException ignored) {
                // fall through to default
            }
        }
        return DEFAULT_TIMEOUT_SEC;
    }

    /** A protocol rooted at {@code <base>/seat-<id>} using the configured base + timeout. */
    public static MailboxProtocol forSeat(int seatId) {
        return forSeat(baseDir(), seatId);
    }

    /** One bus per seat directory (BL-05, 2026-09-04): the request sequence
     *  lives on the bus, so every controller that writes into a seat's inbox —
     *  the seat's own and a Mindslaver-class controller routed to it — must
     *  share ONE instance. A second instance restarted seq at 1 and reused
     *  names the runner had already answered, which it rightly skips. */
    private static final java.util.concurrent.ConcurrentMap<Path, MailboxProtocol> BUSES =
            new java.util.concurrent.ConcurrentHashMap<>();

    /** A protocol rooted at {@code <base>/seat-<id>} with an explicit base dir. */
    public static MailboxProtocol forSeat(Path base, int seatId) {
        Path dir = base.resolve("seat-" + seatId).toAbsolutePath().normalize();
        return BUSES.computeIfAbsent(dir, d -> new MailboxProtocol(d, timeoutSeconds() * 1000L));
    }

    /**
     * Write {@code request} to the inbox and block for the matching response.
     * Returns the parsed response node, or {@code null} on timeout / IO error
     * (the caller then falls back to stock behaviour). Never throws for a
     * missing or malformed brain — a silent brain must never hang the game.
     */
    public JsonNode exchange(Request request) {
        // Item 12: one stat before blocking. A stale heartbeat means nobody is
        // home — skip the wait, stock plays now, one log line per transition.
        // No file (older runner, or none) or an unreadable stat = unknown =
        // wait as always: the gate can only ever SHORTEN a wait.
        Boolean alive = brainAlive(seatDir);
        if (Boolean.FALSE.equals(alive)) {
            if (!absentLogged) {
                absentLogged = true;
                System.err.println("[mailbox " + seatDir.getFileName() + "] brain absent "
                        + "(heartbeat " + (heartbeatAgeMillis(seatDir) / 1000) + "s stale) — "
                        + "stock plays until it returns");
            }
            return null;
        }
        if (absentLogged) {
            absentLogged = false;
            System.err.println("[mailbox " + seatDir.getFileName() + "] brain back — "
                    + "resuming normal waits");
        }
        long n = seq.incrementAndGet();
        request.seq = n;
        request.gameId = gameId;
        // item 12: the engine's wait is the ONE timeout knob — publish it so
        // the runner derives its budget from what the engine will actually do
        request.timeoutSec = timeoutMillis / 1000L;
        Path reqFile = inbox.resolve("req-" + n + ".json");
        Path respFile = outbox.resolve("resp-" + n + ".json");
        try {
            writeAtomic(reqFile, MAPPER.writeValueAsBytes(request));
        } catch (IOException e) {
            System.err.println("mailbox: could not write " + reqFile + ": " + e.getMessage());
            return null;
        }
        long deadline = System.currentTimeMillis() + timeoutMillis;
        while (System.currentTimeMillis() < deadline) {
            if (Files.isReadable(respFile)) {
                try {
                    JsonNode node = MAPPER.readTree(respFile.toFile());
                    if (node != null && !node.isMissingNode()) {
                        deleteQuietly(respFile);
                        deleteQuietly(reqFile);
                        return node;
                    }
                } catch (IOException partialOrBad) {
                    // partial write or malformed — keep polling until timeout
                }
            }
            try {
                Thread.sleep(pollMillis);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return null;
            }
        }
        // timed out — clean up our request so a late answer is not mis-paired
        deleteQuietly(reqFile);
        return null;
    }

    private static void writeAtomic(Path target, byte[] bytes) throws IOException {
        Path tmp = target.resolveSibling(target.getFileName() + ".tmp");
        Files.write(tmp, bytes);
        try {
            Files.move(tmp, target, StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException atomicUnsupported) {
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    private static void deleteQuietly(Path p) {
        try {
            Files.deleteIfExists(p);
        } catch (IOException ignored) {
            // best effort
        }
    }

    // ---- wire records ------------------------------------------------------

    /** One selectable option offered to the brain (stable id + human label). */
    public static final class Option {
        public int id;
        public String label;
        public String cost;
        public String type;

        public Option() {
        }

        public Option(int id, String label, String cost, String type) {
            this.id = id;
            this.label = label;
            this.cost = cost;
            this.type = type;
        }
    }

    /**
     * A decision request. {@code state} is a hidden-info-safe projection built
     * by the controller (the acting seat's own zones + public board/life). The
     * response shape depends on {@code decisionType}:
     * <ul>
     *   <li>{@code CAST_SPELL} → {@code {"chosenId": &lt;int&gt;}} (id of an option; the
     *       pass option's id, or an absent/unknown id, means pass).</li>
     *   <li>{@code MULLIGAN} → {@code {"keep": true|false}}.</li>
     *   <li>{@code DECLARE_ATTACKERS} → {@code {"attackers":[{"attacker":&lt;cardId&gt;,
     *       "defender":&lt;entityId&gt;}, ...]}}.</li>
     *   <li>{@code DECLARE_BLOCKERS} → {@code {"blocks":[{"blocker":&lt;cardId&gt;,
     *       "attacker":&lt;cardId&gt;}, ...]}}.</li>
     * </ul>
     */
    public static final class Request {
        public long seq;
        /** Identity of the game this request belongs to (start millis + pid + a
         *  per-process serial, BL-28);
         *  null only from an engine that predates item 8. */
        public String gameId;
        /** Seconds the engine will wait for the answer before stock plays. */
        public long timeoutSec;
        public int seat;
        public int turn;
        public String phase;
        public String decisionType;
        public String prompt;
        public Object state;
        public List<Option> options = new ArrayList<>();

        public Request() {
        }

        public Request(int seat, int turn, String phase, String decisionType, String prompt) {
            this.seat = seat;
            this.turn = turn;
            this.phase = phase;
            this.decisionType = decisionType;
            this.prompt = prompt;
        }

        public Request state(Object s) {
            this.state = s;
            return this;
        }

        public Request option(int id, String label, String cost, String type) {
            this.options.add(new Option(id, label, cost, type));
            return this;
        }

        public Map<String, Object> stateMap() {
            return this.state instanceof Map ? castMap(this.state) : new LinkedHashMap<>();
        }

        @SuppressWarnings("unchecked")
        private static Map<String, Object> castMap(Object o) {
            return (Map<String, Object>) o;
        }
    }
}
