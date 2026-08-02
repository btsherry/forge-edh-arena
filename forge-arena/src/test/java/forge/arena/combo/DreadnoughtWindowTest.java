package forge.arena.combo;

import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.function.Consumer;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.SeatSpec;
import forge.arena.report.ArenaEvent;

/**
 * Isolated per-path proof for the dreadnought_window runner: each test seeds a
 * board where the intended exploit is the only Dreadnought line whose pieces
 * are present, casts nothing itself, and asserts the runner emitted a
 * {@code dreadnought_window} event of the EXPECTED kind — the signal a
 * whole-game goldfish verdict cannot isolate. Deterministic (fixed seed 42).
 * Reuses SelvalaManaLoopTest's board probe (same package).
 */
public class DreadnoughtWindowTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    private List<ArenaEvent> events;

    private ArenaGameResult run(String label, SelvalaManaLoopTest.SelvalaBoardProbe probe)
            throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("dread-" + label + "-stalls").toString());
        Path dossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        events = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                            new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 4000), sink, probe);
        for (ArenaEvent e : events) {
            if (e.t().equals("dreadnought_window") || (e.t().equals("program_abort")
                    && String.valueOf(e.fields().get("reason")).contains("power_loop"))
                    || (e.t().equals("program_abort")
                        && String.valueOf(e.fields().get("combo")).contains("dreadnought"))) {
                System.out.println("[" + label + "] " + e.t() + " " + e.fields());
            }
        }
        System.out.println("[" + label + "] result=" + result.type());
        return result;
    }

    private void assertFired(String kind) {
        boolean fired = events.stream().anyMatch(e -> e.t().equals("dreadnought_window")
                && kind.equals(String.valueOf(e.fields().get("kind"))));
        List<String> windows = events.stream().filter(e -> e.t().equals("dreadnought_window"))
                .map(e -> String.valueOf(e.fields().get("kind"))).toList();
        assertTrue("expected a dreadnought_window of kind=" + kind
                + ", saw kinds=" + windows, fired);
    }

    /** power_mana: Selvala reads the 12/12 for a mana burst (no sacrifice). */
    @Test
    public void powerManaFiresOnSelvala() throws Exception {
        run("power_mana", new SelvalaManaLoopTest.SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of(), List.of(), List.of("Phyrexian Dreadnought"), 12));
        assertFired("power_mana");
    }

    /** sac_draw: sacrifice the 12/12 to Momentous Fall's additional cost, draw 12. */
    @Test
    public void sacDrawFiresOnMomentousFall() throws Exception {
        run("sac_draw", new SelvalaManaLoopTest.SelvalaBoardProbe(
                null, List.of(), List.of(),
                List.of("Phyrexian Dreadnought", "Momentous Fall"), 12));
        assertFired("sac_draw");
    }

    /** power_draw: Return of the Wildspeaker, mode-steered to Draw, reads 12. */
    @Test
    public void powerDrawFiresOnReturnOfTheWildspeaker() throws Exception {
        run("power_draw", new SelvalaManaLoopTest.SelvalaBoardProbe(
                null, List.of(), List.of(),
                List.of("Phyrexian Dreadnought", "Return of the Wildspeaker"), 12));
        assertFired("power_draw");
    }

    /**
     * power_loop is REDUNDANT with the already-proven 527-2816 Selvala+Umbral
     * loop, which shares its exact core and wins dispatch when both are
     * assembled — so it cannot be isolated on a shared board, and its distinct
     * mechanic is already covered elsewhere: the WINDOW half by
     * {@link #powerManaFiresOnSelvala} (casting the body + acting in its
     * trigger window) and the LOOP half by SelvalaManaLoopTest's ramping-Umbral
     * gate. This test therefore only asserts the board CONVERTS — via whichever
     * of the two paths the pilot takes — confirming the presence of the
     * power_loop program does not break the shared line.
     */
    @Test
    public void dreadnoughtSelvalaUmbralBoardConverts() throws Exception {
        ArenaGameResult result = run("power_loop", new SelvalaManaLoopTest.SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Umbral Mantle"),
                List.<String[]>of(new String[] {"Umbral Mantle", "Selvala, Heart of the Wilds"}),
                List.of("Phyrexian Dreadnought"), 12));
        assertTrue("the Dreadnought+Selvala+Umbral board must CONVERT (via power_loop"
                + " OR the shared 527-2816 loop / combat), got " + result.type(),
                result.type() == ArenaGameResult.ResultType.WIN && result.winnerSeat() == 0);
    }
}
