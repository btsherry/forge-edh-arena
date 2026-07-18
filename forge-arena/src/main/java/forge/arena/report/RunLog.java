package forge.arena.report;

import java.io.Closeable;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;

/**
 * The human-tailable sink (plan §5 v3.2): a single append-only run.log shared
 * by all workers. Each line is written with ONE {@code write()} call on an
 * O_APPEND stream so concurrent worker processes never tear lines.
 */
public final class RunLog implements Closeable {

    private final FileOutputStream out;
    private final String workerId;
    private final RunLogRenderer.Tier tier;
    /**
     * Phase 6 observability: seat index -> deck label, per game, learned
     * from each game's own {@code game_start}. Seating ROTATES between
     * games, so a bare "s0" means a different deck in every game — the
     * exact trap that produced a wrong per-deck win table when the
     * long-200 batch was first analysed. Every seat reference in the log
     * now carries its deck.
     */
    private final java.util.Map<Integer, java.util.List<String>> seatsByGame =
            new java.util.concurrent.ConcurrentHashMap<>();

    public RunLog(Path file, String workerId, RunLogRenderer.Tier tier) throws IOException {
        this.out = new FileOutputStream(file.toFile(), true);
        this.workerId = workerId;
        this.tier = tier;
    }

    public void event(int gameIndex, ArenaEvent e) {
        if ("game_start".equals(e.t()) && e.fields().get("seats") instanceof java.util.List<?> l) {
            java.util.List<String> names = new java.util.ArrayList<>();
            l.forEach(s -> names.add(String.valueOf(s)));
            seatsByGame.put(gameIndex, names);
        }
        RunLogRenderer.render(e, workerId, gameIndex, tier, seatsByGame.get(gameIndex))
                .ifPresent(this::writeLine);
        if ("game_end".equals(e.t())) {
            seatsByGame.remove(gameIndex); // a worker runs hundreds of games
        }
    }

    /** One write() call per line: atomic under O_APPEND across processes. */
    private synchronized void writeLine(String line) {
        try {
            out.write((line + "\n").getBytes(StandardCharsets.UTF_8));
            out.flush();
        } catch (IOException ioe) {
            throw new UncheckedIOException("run.log write failed", ioe);
        }
    }

    @Override
    public void close() throws IOException {
        out.close();
    }
}
