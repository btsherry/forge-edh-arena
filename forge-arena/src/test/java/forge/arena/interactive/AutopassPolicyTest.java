package forge.arena.interactive;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;

import forge.arena.interactive.AutopassPolicy.Decision;
import forge.arena.interactive.AutopassPolicy.Play;
import forge.arena.interactive.AutopassPolicy.Stop;
import forge.arena.interactive.AutopassPolicy.Utility;
import forge.game.phase.PhaseType;

/**
 * The casts-mode autopass table (2026-09-07). Game 24: 51 priority prompts
 * reached the human, most with nothing affordable to do, because the old
 * rule kept every stop open while an opponent's item was on the stack and
 * Forge's actionable scan counts unaffordable spells as actions.
 */
public class AutopassPolicyTest {

    @BeforeClass
    public void boot() {
        // PhaseType's enum initializer reads the engine's resource bundle
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
    }

    private static final List<Play> NONE = Collections.emptyList();
    private static final List<String> NO_UTILITY = Collections.emptyList();

    private static Stop stop(final boolean myTurn, final PhaseType phase, final int pool, final int ceiling,
            final List<Play> plays, final List<String> utility, final boolean oppOnStack) {
        return new Stop(myTurn, phase, pool, ceiling, false, plays, utility, oppOnStack);
    }

    @Test
    public void noManaNoPlaysPassesEvenWithAnOpponentTriggerOnTheStack() {
        // the damage-ping case: Purphoros' trigger is on the stack, one Forest tapped, nothing castable
        final Decision d = AutopassPolicy.decide(stop(false, PhaseType.MAIN1, 0, 0, NONE, NO_UTILITY, true));
        Assert.assertTrue(d.pass, d.toString());
        Assert.assertEquals(d.reason, "nothing to respond with");
    }

    @Test
    public void unaffordableInstantPassesOnAnOpponentsTurn() {
        // Smuggler's Surprise (5 with a Spree mode) in hand, one untapped Forest
        final Decision d = AutopassPolicy.decide(stop(false, PhaseType.END_OF_TURN, 0, 1,
                Arrays.asList(new Play("Smuggler's Surprise", 5)), NO_UTILITY, false));
        Assert.assertTrue(d.pass, d.toString());
        Assert.assertEquals(d.reason, "cheapest play Smuggler's Surprise costs 5, you have 1");
    }

    @Test
    public void affordableInstantKeepsThePromptAndNamesIt() {
        final Decision d = AutopassPolicy.decide(stop(false, PhaseType.COMBAT_BEGIN, 0, 3,
                Arrays.asList(new Play("Heroic Intervention", 2), new Play("Craterhoof Behemoth", 8)), NO_UTILITY, true));
        Assert.assertFalse(d.pass, d.toString());
        Assert.assertEquals(d.reason, "castable: Heroic Intervention");
    }

    @Test
    public void freePlaysAlwaysKeep() {
        final Decision d = AutopassPolicy.decide(stop(false, PhaseType.UPKEEP, 0, 0,
                Arrays.asList(new Play("Force of Vigor (pitch)", 0)), NO_UTILITY, true));
        Assert.assertFalse(d.pass, d.toString());
        Assert.assertEquals(d.reason, "free play: Force of Vigor (pitch)");
    }

    @Test
    public void unknownManaCeilingStaysConservative() {
        // Selvala untapped: her yield scales with power, the ceiling is unknown (-1) → keep
        final Decision d = AutopassPolicy.decide(stop(false, PhaseType.END_OF_TURN, 0, -1,
                Arrays.asList(new Play("Finale of Devastation", 4)), NO_UTILITY, false));
        Assert.assertFalse(d.pass, d.toString());
        Assert.assertEquals(d.reason, "castable: Finale of Devastation");
    }

    @Test
    public void utilityOnlyPassesAndListsIt() {
        final Decision d = AutopassPolicy.decide(stop(false, PhaseType.COMBAT_BEGIN, 0, 4, NONE,
                Arrays.asList("Arbor Elf", "Magus of the Candelabra"), false));
        Assert.assertTrue(d.pass, d.toString());
        Assert.assertEquals(d.reason, "only utility activations available: Arbor Elf, Magus of the Candelabra");
    }

    private static Stop withUtility(final boolean myTurn, final PhaseType phase, final boolean oppOnStack, final Utility... u) {
        return new Stop(myTurn, phase, 0, 2, false, NONE, Arrays.asList(u[0].name), Arrays.asList(u), oppOnStack);
    }

    @Test
    public void aTargetedPermanentWithAnActivatedAbilityKeepsThePrompt() {
        // Swords to Plowshares on Sakura-Tribe Elder: the sacrifice is the response
        final Decision d = AutopassPolicy.decide(withUtility(false, PhaseType.MAIN1, true,
                new Utility("Sakura-Tribe Elder", true, false, true)));
        Assert.assertFalse(d.pass, d.toString());
        Assert.assertTrue(d.reason.startsWith("response available: Sakura-Tribe Elder"), d.reason);
    }

    @Test
    public void aSacrificeOutletKeepsWhileAnOpponentItemIsUp() {
        // a wipe on the stack targets nothing; the outlet still matters
        final Decision d = AutopassPolicy.decide(withUtility(false, PhaseType.MAIN2, true,
                new Utility("Viscera Seer", true, false, false)));
        Assert.assertFalse(d.pass, d.toString());
        Assert.assertEquals(d.reason, "response available: Viscera Seer (sacrifice outlet)");
    }

    @Test
    public void aTapperKeepsAtTheOpponentsBeginCombatOnly() {
        final Utility maze = new Utility("Maze of Ith", false, true, false);
        Assert.assertFalse(AutopassPolicy.decide(withUtility(false, PhaseType.COMBAT_BEGIN, false, maze)).pass,
                "tapper window at the opponent's begin combat");
        Assert.assertTrue(AutopassPolicy.decide(withUtility(false, PhaseType.END_OF_TURN, false, maze)).pass,
                "the same ability at end of turn is plain utility");
    }

    @Test
    public void plainUtilityStillPassesUnderAnOpponentPing() {
        // Arbor Elf's untap is not a response to a Purphoros trigger
        final Decision d = AutopassPolicy.decide(withUtility(false, PhaseType.MAIN1, true,
                new Utility("Arbor Elf", false, true, false)));
        Assert.assertTrue(d.pass, d.toString());
    }

    @Test
    public void theSacredStopsNeverPass() {
        Assert.assertEquals(AutopassPolicy.decide(stop(true, PhaseType.MAIN1, 0, 0, NONE, NO_UTILITY, false)).reason,
                "own main phase");
        Assert.assertEquals(AutopassPolicy.decide(stop(true, PhaseType.MAIN2, 0, 0, NONE, NO_UTILITY, false)).reason,
                "own main phase");
        Assert.assertEquals(AutopassPolicy.decide(stop(false, PhaseType.COMBAT_DECLARE_ATTACKERS, 0, 0, NONE, NO_UTILITY, false)).reason,
                "combat declare step");
        Assert.assertEquals(AutopassPolicy.decide(stop(true, PhaseType.COMBAT_DECLARE_BLOCKERS, 0, 0, NONE, NO_UTILITY, false)).reason,
                "combat declare step");
        Assert.assertEquals(AutopassPolicy.decide(stop(false, PhaseType.END_OF_TURN, 2, 5, NONE, NO_UTILITY, false)).reason,
                "mana floating");
        Assert.assertFalse(AutopassPolicy.decide(new Stop(false, PhaseType.END_OF_TURN, 0, 0, true, NONE, NO_UTILITY, false)).pass,
                "fresh equipment holds the turn open");
        // an opponent's main phase is NOT sacred: with nothing to do it passes
        Assert.assertTrue(AutopassPolicy.decide(stop(false, PhaseType.MAIN1, 0, 0, NONE, NO_UTILITY, false)).pass);
    }
}
