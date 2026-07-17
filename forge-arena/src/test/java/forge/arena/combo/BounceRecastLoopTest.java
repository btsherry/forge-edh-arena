package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertNull;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;

import org.testng.annotations.Test;

import forge.arena.engine.SeatView;

/**
 * PR-27a: the Sabertooth-family archetype — cycle arithmetic, the
 * resolution-choice hint, per-variant step shapes, and assembly semantics.
 */
public class BounceRecastLoopTest {

    private static BounceRecastLoop selvalaCrossroads() {
        return new BounceRecastLoop(Map.of(
                "tapper", "Selvala, Heart of the Wilds",
                "tapper_cost", "{G}",
                "bouncer", "Temur Sabertooth",
                "bounce_cost", "{1}{G}",
                "recast_mana_value", "3",
                "haste_piece", "Concordant Crossroads",
                "haste_mode", "static"), null);
    }

    private static BounceRecastLoop selvalaGreaves() {
        return new BounceRecastLoop(Map.of(
                "tapper", "Selvala, Heart of the Wilds",
                "tapper_cost", "{G}",
                "bouncer", "Temur Sabertooth",
                "bounce_cost", "{1}{G}",
                "recast_mana_value", "3",
                "haste_piece", "Lightning Greaves",
                "haste_mode", "equip",
                "equip_cost", "{0}"), null);
    }

    @Test
    public void cycleCostAndProfitArithmetic() {
        BounceRecastLoop loop = selvalaCrossroads();
        // {G}=1 + {1}{G}=2 + recast 3 = 6
        assertEquals(6, loop.cycleCost());
        // Selvala tapping for greatest power: X=6 (Surrak-sized) is break-even
        assertTrue(loop.mathProfitable(7, 0).isProfitable());
        assertEquals("X=6 nets zero — not profitable", false,
                loop.mathProfitable(6, 0).isProfitable());
        // unpayable from zero floating: blocked, never attempted
        assertEquals("mana", loop.mathProfitable(3, 0).blockedBy());
        // equip variant costs the same ({0} equip)
        assertEquals(6, selvalaGreaves().cycleCost());
    }

    @Test
    public void cycleStepsCarryTheBounceChoiceAndEquipVariantReattaches() {
        List<LineExecutor.Step> steps = selvalaCrossroads().cycleSteps();
        assertEquals(3, steps.size());
        assertEquals("Selvala, Heart of the Wilds", steps.get(0).card());
        assertEquals("Temur Sabertooth", steps.get(1).card());
        assertEquals("the bounce is a resolution CHOICE, not a target",
                "Selvala, Heart of the Wilds", steps.get(1).choice());
        assertTrue(steps.get(1).targets().isEmpty());
        assertTrue(steps.get(2).isCast());
        assertEquals("Selvala, Heart of the Wilds", steps.get(2).card());

        List<LineExecutor.Step> equip = selvalaGreaves().cycleSteps();
        assertEquals(4, equip.size());
        assertEquals("Lightning Greaves", equip.get(3).card());
        assertEquals(List.of("Selvala, Heart of the Wilds"), equip.get(3).targets());
    }

    private static SeatView view(Set<String> battlefield, Set<String> hand, Set<String> command,
            Map<String, String> attachments) {
        return new SeatView(0, 4, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, command,
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80, 0, 0, List.of(), attachments, 6);
    }

    @Test
    public void assemblyCastsMissingPiecesAndEquipVariantAttaches() {
        BounceRecastLoop loop = selvalaGreaves();
        // all reachable: two casts pending
        List<LineExecutor.Step> steps = loop.assemblySteps(view(
                Set.of("Lightning Greaves"),
                Set.of("Temur Sabertooth"),
                Set.of("Selvala, Heart of the Wilds"), Map.of()));
        assertEquals(2, steps.size());
        // all deployed but Greaves unattached: the attach step remains
        List<LineExecutor.Step> attach = loop.assemblySteps(view(
                Set.of("Selvala, Heart of the Wilds", "Temur Sabertooth", "Lightning Greaves"),
                Set.of(), Set.of(), Map.of()));
        assertEquals(1, attach.size());
        assertEquals("Lightning Greaves", attach.get(0).card());
        // attached: executable
        assertTrue(loop.assemblySteps(view(
                Set.of("Selvala, Heart of the Wilds", "Temur Sabertooth", "Lightning Greaves"),
                Set.of(), Set.of(),
                Map.of("Lightning Greaves", "Selvala, Heart of the Wilds"))).isEmpty());
        // a piece in the graveyard: not assemblable
        assertNull(loop.assemblySteps(view(
                Set.of("Selvala, Heart of the Wilds"), Set.of(), Set.of(), Map.of())));
    }

    @Test
    public void shortcutRidesTheGeneralizedSeam() throws Exception {
        // the pilot fires ANY ShortcutSource — the PR-27a generalization
        java.nio.file.Path dir = java.nio.file.Files.createTempDirectory("bounce-bind");
        java.nio.file.Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "215-527-1322", "archetype": "BounceRecastLoop",
                   "params": {"tapper": "Selvala, Heart of the Wilds", "tapper_cost": "{G}",
                              "bouncer": "Temur Sabertooth", "bounce_cost": "{1}{G}",
                              "recast_mana_value": "3",
                              "haste_piece": "Concordant Crossroads", "haste_mode": "static",
                              "pool_color": "G"}}],
                 "unbound": []}""");
        ExecutorBindings bindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        ComboDef def = new ComboDef("215-527-1322", List.of(
                new ComboDef.Piece("Temur Sabertooth", false),
                new ComboDef.Piece("Selvala, Heart of the Wilds", true),
                new ComboDef.Piece("Concordant Crossroads", false)), 0);
        java.util.List<forge.arena.report.ArenaEvent> events = new java.util.ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(def)), bindings,
                0.0, 0, events::add);
        SeatView ready = view(
                Set.of("Selvala, Heart of the Wilds", "Temur Sabertooth", "Concordant Crossroads"),
                Set.of(), Set.of(), Map.of());
        ComboPilot.Action action = pilot.nextAction(ready, true,
                executor -> SimResult.profitable(1)).orElseThrow();
        assertEquals("proven BounceRecast compresses like TapForMana",
                false, action.isStep());
        assertEquals("G", action.shortcut().color());
        assertEquals("215-527-1322", action.shortcut().comboId());
        assertTrue(events.stream().anyMatch(e -> e.t().equals("combo_shortcut")));
    }
}
