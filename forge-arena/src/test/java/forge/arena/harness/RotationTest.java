package forge.arena.harness;

import static org.testng.AssertJUnit.assertEquals;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

/** Plan §8 RotationTest: each deck sits each seat equally over any 4k games. */
public class RotationTest {

    @Test
    public void everyDeckHoldsEverySeatEquallyOverAnyWindow() {
        List<String> decks = List.of("A", "B", "C", "D");
        int k = 7;
        // arbitrary window starts, not just 0 — "ANY 4k games"
        for (int start : new int[] { 0, 1, 5, 42, 999 }) {
            Map<String, Map<Integer, Integer>> counts = new HashMap<>();
            for (int g = start; g < start + 4 * k; g++) {
                List<String> seated = Rotation.latinSquare(decks, g);
                for (int seat = 0; seat < 4; seat++) {
                    counts.computeIfAbsent(seated.get(seat), d -> new HashMap<>())
                            .merge(seat, 1, Integer::sum);
                }
            }
            for (String deck : decks) {
                for (int seat = 0; seat < 4; seat++) {
                    assertEquals("window@" + start + " deck " + deck + " seat " + seat,
                            k, (int) counts.get(deck).get(seat));
                }
            }
        }
    }

    @Test
    public void rotationIsAPermutationEveryGame() {
        List<String> decks = List.of("A", "B", "C", "D");
        for (int g = 0; g < 12; g++) {
            List<String> seated = Rotation.latinSquare(decks, g);
            assertEquals(4, seated.stream().distinct().count());
        }
    }
}
