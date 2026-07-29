package forge.arena.harness;

import java.io.File;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.SeatSpec;
import forge.arena.report.RunLog;
import forge.arena.report.RunLogRenderer;

/**
 * One worker JVM: bootstraps the card DB, then plays its stride of game
 * indices (workerId, workerId+numWorkers, …) sequentially — one game at a
 * time per JVM, which is what keeps MyRandom seeding deterministic. Crashed
 * games become crash records; the worker exits nonzero only on fatal setup
 * failures.
 *
 * <p>Usage: {@code WorkerMain <runDir> <workerId> <numWorkers>} — reads
 * {@code <runDir>/worker-config.json} written by BatchMain.
 *
 * <p>RESUME-SAFE (the omega100 lesson): a worker JVM killed by a host-level
 * fault (the measured Homebrew-JDK GC crash family) used to take its whole
 * remaining stride of games with it — a 100-game batch could only finish
 * short. On start the worker now reads the shared game-records ledger and
 * SKIPS every game_index already recorded, so BatchMain can respawn a dead
 * worker and the replacement replays only what is genuinely missing
 * (including the one game in flight at the crash — its partial event file
 * is not a record, so it is replayed).
 */
public final class WorkerMain {

    private WorkerMain() {
    }

    /** game_index values already in the shared ledger (crash-respawn resume). */
    static java.util.Set<Integer> recordedGames(Path runDir) {
        java.util.Set<Integer> done = new java.util.HashSet<>();
        File ledger = runDir.resolve("game-records.jsonl").toFile();
        if (!ledger.exists()) {
            return done;
        }
        ObjectMapper mapper = new ObjectMapper();
        try {
            for (String line : java.nio.file.Files.readAllLines(ledger.toPath())) {
                if (line.isBlank()) {
                    continue;
                }
                try {
                    JsonNode row = mapper.readTree(line);
                    if (row.has("game_index")) {
                        done.add(row.get("game_index").asInt());
                    }
                } catch (Exception torn) {
                    // a torn tail line from the crashed writer is not a record
                }
            }
        } catch (java.io.IOException unreadable) {
            // no resume info — replaying a stride only duplicates records,
            // so fail loudly rather than guess
            throw new IllegalStateException("resume scan failed: " + ledger, unreadable);
        }
        return done;
    }

    public static void main(String[] args) throws Exception {
        Path runDir = Path.of(args[0]);
        int workerId = Integer.parseInt(args[1]);
        int numWorkers = Integer.parseInt(args[2]);

        JsonNode cfg = new ObjectMapper().readTree(runDir.resolve("worker-config.json").toFile());
        ArenaBootstrap.initialize(new File(cfg.get("assets_dir").asText()));

        List<SeatSpec> seats = new ArrayList<>();
        for (JsonNode seat : cfg.get("seats")) {
            seats.add(new SeatSpec(
                    new File(seat.get("deck_file").asText()),
                    seat.get("profile").asText("Default"),
                    seat.path("simulation_ai").asBoolean(false),
                    seat.path("goldfish").asBoolean(false),
                    seat.path("combo_aware").asBoolean(false),
                    seat.hasNonNull("dossier") ? Path.of(seat.get("dossier").asText()) : null));
        }
        JsonNode lim = cfg.get("limits");
        ArenaLimits limits = new ArenaLimits(
                lim.path("turns").asInt(BatchMain.DEFAULT_TURN_CAP),
                lim.path("wall_clock_sec").asInt(600),
                lim.path("priority_passes_per_turn").asInt(2000));
        long seedBase = cfg.get("seed_base").asLong();
        int games = cfg.get("games").asInt();

        try (RunLog runLog = new RunLog(runDir.resolve("run.log"), String.valueOf(workerId),
                RunLogRenderer.Tier.DEFAULT);
                RecordWriter records = new RecordWriter(runDir.resolve("game-records.jsonl"))) {
            RunConfig runConfig = new RunConfig(seedBase, seats, limits, runDir, runLog);
            java.util.Set<Integer> done = recordedGames(runDir);
            for (int i = workerId; i < games; i += numWorkers) {
                if (done.contains(i)) {
                    continue; // recorded before a respawn — never replayed
                }
                GameRecord record = ArenaRunner.runOne(runConfig, i);
                records.write(record.toJsonMap());
            }
        }
    }
}
