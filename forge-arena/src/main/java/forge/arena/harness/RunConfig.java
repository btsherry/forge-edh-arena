package forge.arena.harness;

import java.nio.file.Path;
import java.util.List;

import forge.arena.engine.ArenaLimits;
import forge.arena.engine.SeatSpec;

/**
 * Configuration for one worker's slice of a run. {@code seats} is the pod in
 * canonical (manifest) order — {@link Rotation} derives per-game seating.
 * {@code runLog} may be null (no human sink, e.g. unit tests).
 */
public record RunConfig(
        long seedBase,
        List<SeatSpec> seats,
        ArenaLimits limits,
        Path outDir,
        forge.arena.report.RunLog runLog) {
}
