package forge.arena.engine;

/**
 * Arena-side game limits. T0 verified the engine has NO built-in turn cap —
 * only an external wall clock — so turn and priority caps are enforced here
 * via the game event bus. A value of {@code 0} disables that limit.
 */
public record ArenaLimits(int turns, int wallClockSec, int priorityPassesPerTurn) {

    /** Plan §3 run-manifest defaults. */
    public static ArenaLimits defaults() {
        return new ArenaLimits(30, 600, 2000);
    }

    public ArenaLimits {
        if (wallClockSec <= 0) {
            throw new IllegalArgumentException("wallClockSec must be positive (the last-resort limit)");
        }
    }
}
