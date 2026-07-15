package forge.arena.bootstrap;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertNotNull;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import org.testng.annotations.Test;

import forge.model.FModel;
import forge.util.MyRandom;

public class BootstrapTest {

    @Test
    public void initializeLoadsCardDatabaseFromExplicitPath() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        assertTrue(ArenaBootstrap.isInitialized());
        assertNotNull("card DB must resolve a known card",
                FModel.getMagicDb().getCommonCards().getCard("Grizzly Bears"));
        assertNotNull("commander staple must resolve",
                FModel.getMagicDb().getCommonCards().getCard("Selvala, Heart of the Wilds"));
    }

    @Test(dependsOnMethods = "initializeLoadsCardDatabaseFromExplicitPath")
    public void initializeIsIdempotent() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        assertTrue(ArenaBootstrap.isInitialized());
    }

    @Test
    public void seedRngIsDeterministicForIntsAndShuffles() {
        List<Integer> deck = new ArrayList<>();
        for (int i = 0; i < 100; i++) {
            deck.add(i);
        }

        ArenaBootstrap.seedRng(42L);
        int[] draws1 = new int[20];
        for (int i = 0; i < draws1.length; i++) {
            draws1[i] = MyRandom.getRandom().nextInt(1000);
        }
        List<Integer> shuffled1 = new ArrayList<>(deck);
        Collections.shuffle(shuffled1, MyRandom.getRandom());

        ArenaBootstrap.seedRng(42L);
        int[] draws2 = new int[20];
        for (int i = 0; i < draws2.length; i++) {
            draws2[i] = MyRandom.getRandom().nextInt(1000);
        }
        List<Integer> shuffled2 = new ArrayList<>(deck);
        Collections.shuffle(shuffled2, MyRandom.getRandom());

        for (int i = 0; i < draws1.length; i++) {
            assertEquals(draws1[i], draws2[i]);
        }
        assertEquals(shuffled1, shuffled2);

        ArenaBootstrap.seedRng(43L);
        List<Integer> shuffled3 = new ArrayList<>(deck);
        Collections.shuffle(shuffled3, MyRandom.getRandom());
        assertTrue("different seed must give a different shuffle", !shuffled1.equals(shuffled3));
    }
}
