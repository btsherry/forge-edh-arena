package forge.arena.interactive;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * One-way publisher for the seat-0 advisor shadow feed. The engine writes
 * decision requests ({@code req-<n>.json}, {@link MailboxProtocol.Request}
 * wire shape), the human's actual choices ({@code chosen-<n>.json}), and
 * free-text notes ({@code note-<n>.json}) into
 * {@code <mailbox-base>/seat-<id>-advisor/inbox/}.
 *
 * <p>There is deliberately NO outbox and no exchange(): the advisor process
 * only ever reads, so it is structurally incapable of stalling the game. All
 * writes happen on a single daemon thread behind a bounded queue — the game
 * thread never touches the filesystem, and when the queue overflows events
 * are dropped (advice is best-effort; the game is not).
 */
final class AdvisorFeed {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final Path inbox;
    private final AtomicLong seq = new AtomicLong();
    private final ThreadPoolExecutor writer;
    private volatile boolean overflowWarned;
    /** Item 8: stamped on every feed file so the advisor resets on an id
     *  change, never on the (non-monotonic) file numbers. */
    private volatile String gameId;

    void setGameId(String id) {
        this.gameId = id;
    }

    AdvisorFeed(Path base, int seatId) {
        this.inbox = base.resolve("seat-" + seatId + "-advisor").resolve("inbox");
        try {
            Files.createDirectories(inbox);
        } catch (IOException e) {
            throw new IllegalStateException("cannot create advisor inbox under " + inbox, e);
        }
        this.writer = new ThreadPoolExecutor(1, 1, 30, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(256), r -> {
                    Thread t = new Thread(r, "advisor-feed-writer");
                    t.setDaemon(true);
                    return t;
                });
    }

    /** Publish a decision request; returns its seq for pairing the outcome. */
    long publish(MailboxProtocol.Request request) {
        long n = seq.incrementAndGet();
        request.seq = n;
        request.gameId = gameId;
        enqueue("req-" + n + ".json", request);
        return n;
    }

    /** Publish what the human actually chose for request {@code n}. */
    void publishChosen(long n, String decisionType, Object chosen) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("gameId", gameId);
        body.put("seq", n);
        body.put("decisionType", decisionType);
        body.put("chosen", chosen);
        enqueue("chosen-" + n + ".json", body);
    }

    /**
     * Publish a completed turn's public game-log delta — the color-commentary
     * source. One event per turn (batched, never per-play).
     */
    void publishDigest(int completedTurn, java.util.List<String> logLines) {
        long n = seq.incrementAndGet();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("gameId", gameId);
        body.put("seq", n);
        body.put("turn", completedTurn);
        body.put("digest", logLines);
        enqueue("digest-" + n + ".json", body);
    }

    /** Publish a free-text note (e.g. auto-pass narration) outside any request. */
    void publishNote(int turn, String phase, String text) {
        long n = seq.incrementAndGet();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("gameId", gameId);
        body.put("seq", n);
        body.put("turn", turn);
        body.put("phase", phase);
        body.put("note", text);
        enqueue("note-" + n + ".json", body);
    }

    private void enqueue(String fileName, Object body) {
        try {
            writer.execute(() -> {
                try {
                    writeAtomic(inbox.resolve(fileName), MAPPER.writeValueAsBytes(body));
                } catch (IOException e) {
                    System.err.println("advisor-feed: could not write " + fileName + ": " + e.getMessage());
                }
            });
        } catch (java.util.concurrent.RejectedExecutionException overflow) {
            if (!overflowWarned) {
                overflowWarned = true;
                System.err.println("advisor-feed: write queue full — dropping events (advice is best-effort)");
            }
        }
    }

    // Same atomic-rename discipline as MailboxProtocol/ObserverSnapshot: a
    // reader must never see a half-written file.
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
}
