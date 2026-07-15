package forge.arena.harness;

/**
 * Documented, splittable seed derivation (plan §4): the per-game seed is the
 * splitmix64 finalizer applied to {@code seedBase XOR gameIndex * GOLDEN_GAMMA}.
 * Pure function of (seedBase, gameIndex) — a run manifest plus a game index
 * reproduces any game's seed forever. Never change these constants; bump a
 * schema version instead.
 */
public final class Seeds {

    private static final long GOLDEN_GAMMA = 0x9E3779B97F4A7C15L;

    private Seeds() {
    }

    public static long derive(long seedBase, int gameIndex) {
        long z = seedBase ^ (gameIndex * GOLDEN_GAMMA);
        z = (z ^ (z >>> 30)) * 0xBF58476D1CE4E5B9L;
        z = (z ^ (z >>> 27)) * 0x94D049BB133111EBL;
        return z ^ (z >>> 31);
    }
}
