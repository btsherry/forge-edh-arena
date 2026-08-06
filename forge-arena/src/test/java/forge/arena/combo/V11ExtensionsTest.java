package forge.arena.combo;

import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
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
 * Isolated gates for the v1.1 compile-pass runner extensions (2026-08-05):
 * <ul>
 *   <li><b>bounce_recast refresh</b> (SelvalaManaLoopRunner) — the
 *       equipment-free Selvala loop: tap for X, Sabertooth bounces her,
 *       recast from hand (no commander tax), Surrak's ETB haste+counter
 *       cures sickness and ramps the next X. Program
 *       syn-selvala-surrak-sabertooth.</li>
 *   <li><b>transform_sac_engine</b> (TransformSacEngineRunner) — the lossless
 *       Greater Good + Ojer Kaslem engine: steered sac (+3 cards), the death
 *       trigger returns Temple of Cultivation, the {2}{G} flip re-creates the
 *       body next turn. Program syn-greater-good-ojer-kaslem.</li>
 * </ul>
 * Uses the same probe/fixture harness as SelvalaManaLoopTest.
 */
public class V11ExtensionsTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    private List<ArenaEvent> runGate(String label,
            SelvalaManaLoopTest.SelvalaBoardProbe probe) throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("v11-" + label + "-stalls").toString());
        Path dossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        List<ArenaEvent> events =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                            new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 4000), sink, probe);
        System.out.println("[" + label + "] result=" + result.type()
                + " winnerSeat=" + result.winnerSeat());
        java.util.Set<String> keep = java.util.Set.of("governor_plan", "outlet_fired",
                "outlet_drill", "program_complete", "program_abort", "program_deferred",
                "line_step");
        for (ArenaEvent e : events) {
            if (keep.contains(e.t())) {
                System.out.println("[" + label + "-ev] T" + e.turn() + " " + e.t()
                        + " " + e.fields());
            }
        }
        return events;
    }

    /** The refresh loop must PLAN on its program and complete measured cycles
     * (tap -> steered bounce -> no-tax recast), proving the bounce re-ready
     * actually works end to end. Surrak (6 power) seeds the X read; forests
     * fund the {G}+{1}{G}+{1}{G}{G} cycle until the pool carries it. */
    @Test
    public void refreshLoopSelvalaSurrakSabertoothRunsMeasuredCycles() throws Exception {
        List<ArenaEvent> events = runGate("refresh", new SelvalaManaLoopTest.SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Temur Sabertooth", "Surrak and Goreclaw"),
                List.of(),
                List.of("Genesis Wave"),
                12));
        boolean planned = events.stream().anyMatch(e -> e.t().equals("governor_plan")
                && "syn-selvala-surrak-sabertooth".equals(String.valueOf(e.fields().get("combo"))));
        long cycles = events.stream().filter(e -> e.t().equals("outlet_drill")
                && "mana_pair".equals(String.valueOf(e.fields().get("kind")))).count();
        List<String> aborts = events.stream().filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        assertTrue("refresh program must plan (governor_plan syn-selvala-surrak-sabertooth); "
                + "aborts=" + aborts, planned);
        assertTrue("refresh loop must complete >=2 MEASURED cycles, got " + cycles
                + "; aborts=" + aborts, cycles >= 2);
    }

    /** The transform-sac engine must complete at least one measured cycle:
     * steered sac (+>=1 net cards) AND the Temple back on the battlefield.
     * 8 forests keep the Temple's 10-permanent flip legal on later turns. */
    @Test
    public void transformSacEngineDrawsAndReturnsTemple() throws Exception {
        List<ArenaEvent> events = runGate("ojer", new SelvalaManaLoopTest.SelvalaBoardProbe(
                null,
                List.of("Ojer Kaslem, Deepest Growth", "Greater Good"),
                List.of(),
                List.of(),
                8));
        long drills = events.stream().filter(e -> e.t().equals("outlet_drill")
                && "transform_sac".equals(String.valueOf(e.fields().get("kind")))).count();
        List<String> aborts = events.stream().filter(e -> e.t().equals("program_abort")
                && "syn-greater-good-ojer-kaslem".equals(
                        String.valueOf(e.fields().get("combo"))))
                .map(e -> String.valueOf(e.fields().get("reason"))).toList();
        assertTrue("engine must NOT abort broken, aborts=" + aborts,
                aborts.stream().noneMatch(r -> r.contains("engine_broken")));
        assertTrue("transform-sac engine must complete >=1 measured cycle (sac -> +cards "
                + "-> Temple returned), got " + drills + "; aborts=" + aborts, drills >= 1);
    }

    /** COMMANDER SMASH gate: the ramping loop with NO outlet reachable must
     * pump Selvala past 21 power, arm the commander-damage sequence on the
     * outlet-less defer, and steer combat (COMMANDER_DMG_SEQUENCE). Surrak's
     * static grants her trample so the swing converts through chumps —
     * one connected hit at 21+ is a kill via CR 903.10a. */
    @Test
    public void commanderSmashConvertsOutletlessLoop() throws Exception {
        List<ArenaEvent> events = runGate("smash", new SelvalaManaLoopTest.SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Umbral Mantle", "Surrak and Goreclaw"),
                List.<String[]>of(new String[] {"Umbral Mantle", "Selvala, Heart of the Wilds"}),
                List.of(),
                8));
        var smash = events.stream()
                .filter(e -> e.t().equals("line_step")
                        && "COMMANDER_SMASH".equals(String.valueOf(e.fields().get("stage"))))
                .findFirst();
        List<String> defers = events.stream().filter(e -> e.t().equals("program_deferred"))
                .map(e -> String.valueOf(e.fields())).toList();
        assertTrue("the outlet-less loop must ARM the smash (COMMANDER_SMASH); defers="
                + defers, smash.isPresent());
        long power = Long.parseLong(String.valueOf(smash.get().fields().get("power")));
        assertTrue("smash must arm on a combat-lethal body, got power " + power, power >= 21);
        String armedRoute = String.valueOf(smash.get().fields().get("route"));
        boolean steered = events.stream().anyMatch(e -> e.t().equals("line_step")
                && "FORCED_ATTACK".equals(String.valueOf(e.fields().get("stage")))
                && armedRoute.equals(String.valueOf(e.fields().get("route"))));
        assertTrue("combat must steer the armed route (" + armedRoute + ")", steered);
    }

    /** Map view of the first governor_plan for a combo (or empty). */
    static Map<String, Object> firstPlan(List<ArenaEvent> events, String comboId) {
        return events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && comboId.equals(String.valueOf(e.fields().get("combo"))))
                .findFirst().map(ArenaEvent::fields).orElse(Map.of());
    }
}
