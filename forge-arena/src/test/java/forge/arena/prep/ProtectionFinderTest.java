package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertNull;

import org.testng.annotations.Test;

/** ProtectionFinder classifies reactive INSTANT covers by scope from card text. */
public class ProtectionFinderTest {

    @Test
    public void heroicInterventionIsAllPermanentsInstant() {
        ProtectionFinder.Cover c = ProtectionFinder.coverOf(
                "Heroic Intervention",
                "Permanents you control gain hexproof and indestructible until end of turn.",
                "Instant", "{1}{G}");
        assertEquals("Heroic Intervention", c.card());
        assertEquals(ProtectionFinder.Scope.ALL_PERMANENTS, c.scope());
        assertEquals(2, c.manaValue());
    }

    @Test
    public void creatureOnlyGrantIsCreatureScope() {
        ProtectionFinder.Cover c = ProtectionFinder.coverOf(
                "Flawless Maneuver",
                "Creatures you control gain indestructible until end of turn.",
                "Instant", "{2}{W}");
        assertEquals(ProtectionFinder.Scope.CREATURES, c.scope());
    }

    @Test
    public void staticEnchantmentProtectionIsNotAReactiveCover() {
        // Asceticism grants hexproof but is an enchantment — a proactive deploy,
        // not something you can cast in response to removal on the stack
        assertNull(ProtectionFinder.coverOf(
                "Asceticism",
                "Creatures you control have hexproof. {2}{G}{G}: Regenerate all creatures you control.",
                "Enchantment", "{3}{G}{G}"));
    }

    @Test
    public void anUnrelatedInstantIsNotACover() {
        assertNull(ProtectionFinder.coverOf(
                "Giant Growth", "Target creature gets +3/+3 until end of turn.",
                "Instant", "{G}"));
    }

    @Test
    public void scopeCoverageMatchesPieceKind() {
        // ALL_PERMANENTS saves an artifact piece (Umbral); CREATURES does not
        assertEquals(true, ProtectionFinder.Scope.ALL_PERMANENTS.covers(false));
        assertEquals(true, ProtectionFinder.Scope.ALL_PERMANENTS.covers(true));
        assertEquals(false, ProtectionFinder.Scope.CREATURES.covers(false));
        assertEquals(true, ProtectionFinder.Scope.CREATURES.covers(true));
    }
}
