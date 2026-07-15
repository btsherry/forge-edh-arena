package forge.arena.report;

import java.io.BufferedWriter;
import java.io.Closeable;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.function.Consumer;

import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.engine.ArenaGameResult;

/**
 * Dual-sink recorder (plan §5 v3.2): every {@link ArenaEvent} goes to the
 * per-game JSONL machine-of-record AND, rendered, to the shared run.log. Both
 * sinks consume the identical stream, so they structurally cannot drift.
 *
 * <p>Events carry no wall-clock data — a seeded game's JSONL is byte-identical
 * across runs (SeedDeterminismTest); durations live in the game record only.
 */
public final class EventRecorder implements Consumer<ArenaEvent>, Closeable {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final BufferedWriter jsonl;
    private final RunLog runLog;
    private final int gameIndex;
    private final Path jsonlPath;

    private EventRecorder(BufferedWriter jsonl, Path jsonlPath, RunLog runLog, int gameIndex) {
        this.jsonl = jsonl;
        this.jsonlPath = jsonlPath;
        this.runLog = runLog;
        this.gameIndex = gameIndex;
    }

    /** Opens {@code <eventsDir>/NNNNNN.jsonl} and writes the game_start event. */
    public static EventRecorder open(Path eventsDir, int gameIndex, long seed, List<String> seatNames,
            RunLog runLog) throws IOException {
        Files.createDirectories(eventsDir);
        Path file = eventsDir.resolve(String.format("%06d.jsonl", gameIndex));
        BufferedWriter writer = Files.newBufferedWriter(file, StandardCharsets.UTF_8);
        EventRecorder recorder = new EventRecorder(writer, file, runLog, gameIndex);
        recorder.accept(ArenaEvent.of("game_start", null, null)
                .with("seats", seatNames)
                .with("seed", seed));
        return recorder;
    }

    @Override
    public synchronized void accept(ArenaEvent event) {
        try {
            jsonl.write(MAPPER.writeValueAsString(event.toJsonMap()));
            jsonl.newLine();
        } catch (IOException ioe) {
            throw new UncheckedIOException("event log write failed: " + jsonlPath, ioe);
        }
        if (runLog != null) {
            runLog.event(gameIndex, event);
        }
    }

    /** Writes the game_end attribution from the harness-side result and closes. */
    public void finish(ArenaGameResult result) throws IOException {
        ArenaEvent end = ArenaEvent.of("game_end", result.turns(), null)
                .with("result", result.type().name().toLowerCase())
                .with("win_condition", result.winCondition())
                .with("turns", result.turns());
        if (result.winnerSeat() >= 0) {
            end.with("winner_seat", result.winnerSeat()).with("winner", result.winnerName());
        }
        if (result.limitingFactor() != null) {
            end.with("limiting_factor", result.limitingFactor().name().toLowerCase());
        }
        accept(end);
        close();
    }

    public Path jsonlPath() {
        return jsonlPath;
    }

    @Override
    public void close() throws IOException {
        jsonl.close();
    }
}
