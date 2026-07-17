package forge.arena.engine;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.util.List;
import java.util.Map;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.combo.ExecutorBindings;
import forge.arena.combo.SimResult;

/**
 * The Gate 3.5 oracle, live: the verifier builds the binding's board inside
 * a real disposable game and the engine proves or refuses the loop. The
 * shipped Mantle binding verifies; a wrong-cost variant and a hallucinated
 * card name are BLOCKED.
 */
public class BindingVerifierIntegrationTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    private static ExecutorBindings.Binding mantle(String untapCost, String engineName) {
        return new ExecutorBindings.Binding("527-2816", "TapForManaUntapLoop", Map.of(
                "engine", engineName,
                "untapper", "Umbral Mantle",
                "activation_cost", "{G}",
                "untap_cost", untapCost,
                "untap_ability_host", "engine",
                "attach_cost", "{0}",
                "self_pump_per_cycle", "2"), List.of(), "MAIN1", List.of());
    }

    @Test
    public void realBindingVerifiesWrongCostAndHallucinationAreBlocked() {
        BindingVerifier verifier = new BindingVerifier(
                new File("decks/selvala-heart-of-the-wilds.dck"));

        SimResult real = verifier.verify(mantle("{3}", "Selvala, Heart of the Wilds"));
        assertTrue("the true binding must verify, got " + real, real.isProfitable());

        SimResult wrongCost = verifier.verify(mantle("{9}", "Selvala, Heart of the Wilds"));
        assertEquals(SimResult.Status.BLOCKED, wrongCost.status());

        SimResult hallucinated = verifier.verify(mantle("{3}", "Selvala, Definitely Real Card"));
        assertEquals(SimResult.Status.BLOCKED, hallucinated.status());
        assertTrue(hallucinated.blockedBy().contains("verifier_board_failed"));
    }
}
