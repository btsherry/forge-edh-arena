package forge.arena.harness;

import static org.testng.AssertJUnit.assertEquals;

import java.util.HashSet;
import java.util.Set;

import org.testng.annotations.Test;

public class SeedsTest {

    /** The derivation is load-bearing for reproducibility: pin golden values. */
    @Test
    public void goldenValuesNeverChange() {
        assertEquals(-6387817139659442654L, Seeds.derive(42L, 0));
        assertEquals(-4767286540954276203L, Seeds.derive(42L, 1));
    }

    @Test
    public void noCollisionsAcrossALargeRun() {
        Set<Long> seen = new HashSet<>();
        for (int i = 0; i < 100_000; i++) {
            seen.add(Seeds.derive(42L, i));
        }
        assertEquals(100_000, seen.size());
    }

    @Test
    public void differentBasesDiverge() {
        Set<Long> seen = new HashSet<>();
        for (long base = 0; base < 1000; base++) {
            seen.add(Seeds.derive(base, 0));
        }
        assertEquals(1000, seen.size());
    }
}
