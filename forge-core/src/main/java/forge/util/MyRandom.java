/*
 * Forge: Play Magic: the Gathering.
 * Copyright (C) 2011  Forge Team
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 * 
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 * 
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */
package forge.util;

import java.security.SecureRandom;
import java.util.Random;

/**
 * <p>
 * MyRandom class.<br>
 * Preferably all Random numbers should be retrieved using this wrapper class
 * </p>
 * 
 * @author Forge
 * @version $Id$
 */
public class MyRandom {
    /*
     * ARENA-PATCH (forge-edh-arena, upstream patch 2 of 2).
     *
     * The provider was a single process-wide static. Any thread that drew a
     * random number shifted the sequence every other thread saw, so a headless
     * batch that ran ANY work on a second thread - a lookahead copy, a
     * background evaluation - silently perturbed the live game. Measured
     * effect: 15 of 30 games diverged on identical seeds (different winner,
     * different length), which makes seeded reproduction impossible and every
     * seed-paired comparison meaningless.
     *
     * The provider is now per-thread. setSeed() gives every thread its own
     * generator from the same seed, so a game thread's sequence depends only
     * on its own draws. Unseeded behaviour is unchanged: each thread lazily
     * gets a SecureRandom exactly as before.
     */
    private static volatile Long deterministicSeed = null;

    private static final ThreadLocal<Random> RANDOM = ThreadLocal.withInitial(() -> {
        Long seed = deterministicSeed;
        return seed == null ? new SecureRandom() : new Random(seed);
    });

    /**
     * <p>
     * percentTrue.<br>
     * If percent is like 30, then 30% of the time it will be true.
     * </p>
     * 
     * @param percent an int.
     * @return a boolean.
     */
    public static boolean percentTrue(final int percent) {
        return percent > MyRandom.getRandom().nextInt(100);
    }

    /**
     * Gets the random.
     * 
     * @return the random
     */
    public static Random getRandom() {
        return RANDOM.get();
    }

    /**
     * Sets this THREAD's random provider. Used for deterministic simulation.
     * @param random the random
     */
    public static void setRandom(Random random) {
        RANDOM.set(random);
    }

    /**
     * ARENA-PATCH: seed every thread deterministically. Each thread gets its
     * OWN generator from this seed, so concurrent work cannot consume another
     * thread's sequence - which is what made seeded batches irreproducible.
     */
    public static void setSeed(final long seed) {
        deterministicSeed = seed;
        RANDOM.remove();
    }

    public static int[] splitIntoRandomGroups(final int value, final int numGroups) {
        int[] groups = new int[numGroups];

        for (int i = 0; i < value; i++) {
            groups[getRandom().nextInt(numGroups)]++;
        }

        return groups;
    }
}
