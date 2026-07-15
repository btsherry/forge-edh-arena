package forge.arena.harness;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.List;

import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.EngineCrashException;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameEventBridge;
import forge.arena.engine.SeatSpec;
import forge.arena.report.EventRecorder;

/**
 * Single-game core (plan §4): derive the seed, rotate the seats, record the
 * event stream through both sinks, play under limits, and return a
 * {@link GameRecord} — crashed games included, never dropped. Workers call
 * {@code runOne} from separate JVM processes (the MyRandom global-seam rule).
 */
public final class ArenaRunner {

    private ArenaRunner() {
    }

    public static GameRecord runOne(RunConfig cfg, int gameIndex) {
        long seed = Seeds.derive(cfg.seedBase(), gameIndex);
        List<SeatSpec> seated = Rotation.latinSquare(cfg.seats(), gameIndex);
        List<String> deckNames = seated.stream().map(ArenaRunner::deckName).toList();
        String eventLogRel = String.format("events/%06d.jsonl", gameIndex);

        EventRecorder recorder;
        try {
            recorder = EventRecorder.open(cfg.outDir().resolve("events"), gameIndex, seed, deckNames,
                    cfg.runLog());
        } catch (IOException ioe) {
            throw new UncheckedIOException("cannot open event log for game " + gameIndex, ioe);
        }

        long started = System.currentTimeMillis();
        try {
            GameEventBridge bridge = new GameEventBridge(recorder);
            ArenaGameResult result = EngineFacade.playCommanderGame(seated, seed, cfg.limits(), bridge);
            recorder.finish(result);
            return GameRecord.from(gameIndex, seed, deckNames, result, eventLogRel);
        } catch (EngineCrashException crash) {
            closeQuietly(recorder);
            return GameRecord.crashed(gameIndex, seed, deckNames, crash.getCause() != null ? crash.getCause() : crash,
                    System.currentTimeMillis() - started, eventLogRel);
        } catch (IOException ioe) {
            closeQuietly(recorder);
            return GameRecord.crashed(gameIndex, seed, deckNames, ioe,
                    System.currentTimeMillis() - started, eventLogRel);
        }
    }

    private static String deckName(SeatSpec seat) {
        String name = seat.deckFile().getName();
        return name.endsWith(".dck") ? name.substring(0, name.length() - 4) : name;
    }

    private static void closeQuietly(EventRecorder recorder) {
        try {
            recorder.close();
        } catch (IOException ignored) {
            // the crash record is the primary artifact; a lost trailing event is acceptable
        }
    }
}
