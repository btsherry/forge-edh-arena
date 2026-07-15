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

    public RunLog(Path file, String workerId, RunLogRenderer.Tier tier) throws IOException {
        this.out = new FileOutputStream(file.toFile(), true);
        this.workerId = workerId;
        this.tier = tier;
    }

    public void event(int gameIndex, ArenaEvent e) {
        RunLogRenderer.render(e, workerId, gameIndex, tier).ifPresent(this::writeLine);
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
