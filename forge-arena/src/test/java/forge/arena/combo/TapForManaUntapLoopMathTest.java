package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.util.Map;

import org.testng.annotations.Test;

/**
 * Plan §8 SelvalaMantleMathTest + SelvalaStaffNeedsPowerSix, at the
 * arithmetic layer: net per cycle = yield − cycle cost, engine self-pump
 * compounds, negative floating means the loop can't pay for itself.
 */
public class TapForManaUntapLoopMathTest {

    private static final TapForManaUntapLoop MANTLE = new TapForManaUntapLoop(Map.of(
            "engine", "Selvala, Heart of the Wilds",
            "untapper", "Umbral Mantle",
            "activation_cost", "{G}",
            "untap_cost", "{3}",
            "untap_ability_host", "engine",
            "self_pump_per_cycle", "2"), "MAIN1");

    private static final TapForManaUntapLoop STAFF = new TapForManaUntapLoop(Map.of(
            "engine", "Selvala, Heart of the Wilds",
            "untapper", "Staff of Domination",
            "activation_cost", "{G}",
            "untap_cost", "{3}",
            "untap_targets_engine", "true",
            "untapper_reset_cost", "{1}",
            "self_pump_per_cycle", "0"), "MAIN1");

    @Test
    public void mantleNetPerCycleIsYieldMinusFour() {
        // starting power 4: cycle 1 breaks even, pump makes cycle 2 profitable
        SimResult power4 = MANTLE.mathProfitable(4, 0, 0);
        assertTrue(power4.isProfitable());
        assertEquals(2, power4.cycles());
        // power 5 opener (e.g. Craterhoof on board): profitable immediately
        assertEquals(1, MANTLE.mathProfitable(4, 5, 0).cycles());
    }

    @Test
    public void mantleAtPowerTwoRequiresTwoFloatedMana() {
        // without float the first cycle goes negative — costs unpayable
        SimResult broke = MANTLE.mathProfitable(2, 0, 0);
        assertFalse(broke.isProfitable());
        assertEquals("mana", broke.blockedBy());
        // with {2} floated the pump catches up by cycle 3 (plan §8)
        SimResult floated = MANTLE.mathProfitable(2, 0, 2);
        assertTrue(floated.isProfitable());
        assertEquals(3, floated.cycles());
    }

    @Test
    public void staffNeedsPowerSix() {
        // {G} + {3} untap-Selvala + {1} untap-Staff = 5/cycle, no pump: power 5 loops at zero
        SimResult power5 = STAFF.mathProfitable(5, 0, 0);
        assertFalse("net 0 must never validate (plan §8 SelvalaStaffNeedsPowerSix)",
                power5.isProfitable());
        assertEquals(SimResult.Status.UNPROFITABLE, power5.status());
        // power 6 nets +1 from the first cycle
        assertEquals(1, STAFF.mathProfitable(6, 0, 0).cycles());
    }

    @Test
    public void costParsingCountsDigitsAtFaceValueAndSymbolsAsOne() {
        assertEquals(1, TapForManaUntapLoop.cmc("{G}"));
        assertEquals(3, TapForManaUntapLoop.cmc("{3}"));
        assertEquals(4, TapForManaUntapLoop.cmc("{3}{G}"));
        assertEquals(2, TapForManaUntapLoop.cmc("{G}{G}"));
    }

    @Test(expectedExceptions = IllegalArgumentException.class,
            expectedExceptionsMessageRegExp = ".*missing param 'untap_cost'.*")
    public void incompleteBindingFailsAtConstructionNotMidGame() {
        new TapForManaUntapLoop(Map.of("engine", "X", "untapper", "Y",
                "activation_cost", "{G}"), "MAIN1");
    }

    @Test
    public void manaLoopStepsFollowTheCycleScript() {
        LineExecutor.LineState start = new LineExecutor.LineState(0, 0);
        LineExecutor.Step first = MANTLE.next(start, null);
        assertEquals("Selvala, Heart of the Wilds", first.card());
        assertEquals("{G}", first.costHint());
        LineExecutor.Step second = MANTLE.next(start.advance(), null);
        // Mantle's ability is granted TO the engine — the step activates on Selvala
        assertEquals("Selvala, Heart of the Wilds", second.card());
        assertEquals("{3}", second.costHint());
        assertTrue(second.targets().isEmpty());

        // Staff cycles are 3 steps, the untap step TARGETS the engine
        assertEquals(3, STAFF.cycleSteps().size());
        LineExecutor.Step untap = STAFF.cycleSteps().get(1);
        assertEquals("Staff of Domination", untap.card());
        assertEquals(java.util.List.of("Selvala, Heart of the Wilds"), untap.targets());
        assertEquals("{1}", STAFF.cycleSteps().get(2).costHint());
    }

    @Test
    public void bankCyclesEndTheLiveLineButNeverValidation() {
        // default 6 bank cycles x 2 steps: iteration 12 is done
        LineExecutor.LineState banked = new LineExecutor.LineState(0, 12);
        assertTrue(MANTLE.next(banked, null).isDone());
        assertFalse(MANTLE.next(new LineExecutor.LineState(0, 11), null).isDone());
    }
}
