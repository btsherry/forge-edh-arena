package forge.arena.harness;

import java.util.ArrayList;
import java.util.List;

/**
 * Seat-position fairness (plan §4): cyclic Latin square — in game g, seat s
 * holds deck (s + g) mod n, so over ANY window of n·k consecutive games every
 * deck occupies every seat exactly k times.
 */
public final class Rotation {

    private Rotation() {
    }

    public static <T> List<T> latinSquare(List<T> decks, int gameIndex) {
        int n = decks.size();
        int offset = Math.floorMod(gameIndex, n);
        List<T> seated = new ArrayList<>(n);
        for (int seat = 0; seat < n; seat++) {
            seated.add(decks.get(Math.floorMod(seat + offset, n)));
        }
        return seated;
    }
}
