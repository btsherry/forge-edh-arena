package forge.arena.engine;

/**
 * Outcome of one arena game, expressed without Forge types so nothing outside
 * {@code forge.arena.engine} needs to import engine internals. Timeouts are
 * data (plan §4): a limit hit yields {@link ResultType#TIMEOUT_DRAW} with the
 * {@link LimitingFactor} recorded — never a dropped game.
 */
public record ArenaGameResult(
        ResultType type,
        int winnerSeat,
        String winnerName,
        String winCondition,
        int turns,
        long durationMs,
        LimitingFactor limitingFactor) {

    public enum ResultType { WIN, DRAW, TIMEOUT_DRAW }

    public enum LimitingFactor { TURNS, WALL_CLOCK, PRIORITY_PASSES }

    public ArenaGameResult {
        if (type == ResultType.TIMEOUT_DRAW && limitingFactor == null) {
            throw new IllegalArgumentException("timeout_draw requires its limiting factor (schema rule)");
        }
    }
}
