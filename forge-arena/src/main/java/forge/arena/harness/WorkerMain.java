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
 */
public final class WorkerMain {

    private WorkerMain() {
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
                    seat.path("goldfish").asBoolean(false)));
        }
        JsonNode lim = cfg.get("limits");
        ArenaLimits limits = new ArenaLimits(
                lim.path("turns").asInt(30),
                lim.path("wall_clock_sec").asInt(600),
                lim.path("priority_passes_per_turn").asInt(2000));
        long seedBase = cfg.get("seed_base").asLong();
        int games = cfg.get("games").asInt();

        try (RunLog runLog = new RunLog(runDir.resolve("run.log"), String.valueOf(workerId),
                RunLogRenderer.Tier.DEFAULT);
                RecordWriter records = new RecordWriter(runDir.resolve("game-records.jsonl"))) {
            RunConfig runConfig = new RunConfig(seedBase, seats, limits, runDir, runLog);
            for (int i = workerId; i < games; i += numWorkers) {
                GameRecord record = ArenaRunner.runOne(runConfig, i);
                records.write(record.toJsonMap());
            }
        }
    }
}
