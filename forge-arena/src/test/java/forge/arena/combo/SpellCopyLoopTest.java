package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertNull;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;

import org.testng.annotations.Test;

import forge.arena.engine.SeatView;
import forge.arena.report.ArenaEvent;

/**
 * PR-27b: the Dualcaster family — assembly semantics (pieces stay in hand,
 * an engine must be down), the consequence-chain validation contract, and
 * the pilot's TOKEN_FLOOD compression.
 */
public class SpellCopyLoopTest {

    private static SpellCopyLoop twinflame() {
        return new SpellCopyLoop(Map.of(
                "copy_spell", "Twinflame",
                "copier", "Dualcaster Mage",
                "damage_engines",
                "Purphoros, God of the Forge; Agate Instigator; Terror of the Peaks",
                "engine_mana_value", "4",
                "flood_count", "30"), null);
    }

    private static SeatView view(Set<String> battlefield, Set<String> hand, Set<String> command) {
        return new SeatView(0, 5, Map.of(
                SeatView.Zone.BATTLEFIELD, battlefield,
                SeatView.Zone.HAND, hand,
                SeatView.Zone.COMMAND, command,
                SeatView.Zone.GRAVEYARD, Set.of(),
                SeatView.Zone.EXILE, Set.of()), 80, 0, 0,
                List.of(new SeatView.OpponentView(1, 40, 0, Set.of())), Map.of(), 8);
    }

    @Test
    public void assemblyNeedsHandPiecesAndABattlefieldEngine() {
        SpellCopyLoop loop = twinflame();
        // engine down + both pieces in hand: executable, nothing to deploy
        assertTrue(loop.assemblySteps(view(
                Set.of("Purphoros, God of the Forge"),
                Set.of("Twinflame", "Dualcaster Mage"), Set.of())).isEmpty());
        // semicolon parsing: comma-bearing names resolve as ONE engine
        assertEquals(4, loop.castCostEstimate("Purphoros, God of the Forge"));
        // engine reachable but not down: assembly casts it (commander)
        List<LineExecutor.Step> steps = loop.assemblySteps(view(
                Set.of(), Set.of("Twinflame", "Dualcaster Mage"),
                Set.of("Purphoros, God of the Forge")));
        assertEquals(1, steps.size());
        assertEquals("Purphoros, God of the Forge", steps.get(0).card());
        // a loop piece missing from hand: not this line
        assertNull(loop.assemblySteps(view(
                Set.of("Purphoros, God of the Forge"), Set.of("Twinflame"), Set.of())));
        // no engine reachable: entries would ping nothing
        assertNull(loop.assemblySteps(view(
                Set.of(), Set.of("Twinflame", "Dualcaster Mage"), Set.of())));
    }

    @Test
    public void validationDemandsARealLifeDrop() {
        SpellCopyLoop loop = twinflame();
        // sim stub: one injected entry costs opponents 2 life -> proven
        assertTrue(loop.validate(new StubSim(42, 40)).isProfitable());
        // no damage (no engine on the copy): refused
        assertEquals(false, loop.validate(new StubSim(40, 40)).isProfitable());
        // no surviving opponents: blocked, never fired
        assertEquals("no_opponents", loop.validate(new StubSim(0, 0)).blockedBy());
    }

    /** Minimal SimHandle: scripted opponents-life before/after injectCopy. */
    private static final class StubSim implements SimHandle {
        private int life;
        private final int after;

        StubSim(int before, int after) {
            this.life = before;
            this.after = after;
        }

        @Override
        public boolean activate(String card, String costHint, List<String> targets) {
            return false;
        }

        @Override
        public int manaPoolTotal() {
            return 0;
        }

        @Override
        public int greatestOwnPower() {
            return 0;
        }

        @Override
        public boolean untapped(String card) {
            return false;
        }

        @Override
        public boolean injectCopy(String card) {
            life = after;
            return true;
        }

        @Override
        public int opponentsLifeTotal() {
            return life;
        }
    }

    @Test
    public void provenLoopCompressesToATokenFloodOrder() throws Exception {
        java.nio.file.Path dir = java.nio.file.Files.createTempDirectory("copyloop-bind");
        java.nio.file.Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "147-1235", "archetype": "SpellCopyLoop",
                   "params": {"copy_spell": "Twinflame", "copier": "Dualcaster Mage",
                              "damage_engines": "Purphoros, God of the Forge",
                              "flood_count": "30"}}],
                 "unbound": []}""");
        ExecutorBindings bindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        ComboDef def = new ComboDef("147-1235", List.of(
                new ComboDef.Piece("Dualcaster Mage", false),
                new ComboDef.Piece("Twinflame", false)), 0);
        RoutePlan plan = new RoutePlan(
                List.of(new RoutePlan.PlannedRoute("DIRECT_DAMAGE_LOOP", "direct", "intrinsic",
                        List.of())),
                Map.of("ping_each_opponent", List.of("Purphoros, God of the Forge")));
        java.util.List<ArenaEvent> events = new java.util.ArrayList<>();
        ComboPilot pilot = new ComboPilot(new ComboTracker(List.of(def)), bindings, plan, null,
                0.0, 0, events::add);

        SeatView ready = view(Set.of("Purphoros, God of the Forge"),
                Set.of("Twinflame", "Dualcaster Mage"), Set.of());
        ComboPilot.Action action = pilot.nextAction(ready, true,
                executor -> SimResult.profitable(1)).orElseThrow();
        assertTrue("a flood order, not a step", action.flood() != null);
        assertEquals("Dualcaster Mage", action.flood().copier());
        assertEquals(30, action.flood().count());
        assertTrue(events.stream().anyMatch(e -> e.t().equals("route_selected")
                && "DIRECT_DAMAGE_LOOP".equals(e.fields().get("route"))));
        ArenaEvent shortcut = events.stream()
                .filter(e -> e.t().equals("combo_shortcut")).findFirst().orElseThrow();
        @SuppressWarnings("unchecked")
        Map<String, Object> product = (Map<String, Object>) shortcut.fields().get("bounded_product");
        assertEquals(30, product.get("token_entries"));
        // the line exited cleanly — the flood is one order, never stepped
        assertEquals(false, pilot.lineActive());
    }
}
