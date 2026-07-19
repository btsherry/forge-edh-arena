package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertNull;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * PR-48 — paired plays read out of card text, with SCOPE as the load-bearing
 * rule. These pairings are invisible to a combo database (nothing about them
 * is infinite or deterministic), so the reasoning has to be right here.
 */
public class PairedPlayFinderTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static com.fasterxml.jackson.databind.JsonNode deck(Map<String, ?>... cards) {
        return MAPPER.valueToTree(Map.of("cards", List.of(cards)));
    }

    private static Map<String, Object> card(String name, String type, String oracle, int mv) {
        // the real dossier carries a printed cost string, so fixtures do too
        return Map.of("name", name, "type_line", type, "oracle_text", oracle,
                "mana_cost", "{" + mv + "}");
    }

    @Test
    public void scopesAreReadFromText() {
        assertEquals(PairedPlayFinder.Scope.LANDS,
                PairedPlayFinder.wipeScope("Destroy all lands."));
        assertEquals(PairedPlayFinder.Scope.CREATURES,
                PairedPlayFinder.wipeScope("Destroy all creatures."));
        assertEquals(PairedPlayFinder.Scope.NONLAND_PERMANENTS,
                PairedPlayFinder.wipeScope("Destroy all nonland permanents."));
        // a modal sweeper can choose, so it counts as the broader option
        assertEquals(PairedPlayFinder.Scope.ALL_PERMANENTS,
                PairedPlayFinder.wipeScope(
                        "Destroy all lands or all creatures. Creatures destroyed this way "
                        + "can't be regenerated."));
        assertNull(PairedPlayFinder.wipeScope("Draw a card."));

        assertEquals(PairedPlayFinder.Scope.ALL_PERMANENTS,
                PairedPlayFinder.shieldScope("Until your next turn, your life total can't change "
                        + "and you gain protection from everything. All permanents you control "
                        + "phase out."));
        assertEquals(PairedPlayFinder.Scope.CREATURES,
                PairedPlayFinder.shieldScope("Creatures you control gain indestructible "
                        + "until end of turn."));
        assertNull(PairedPlayFinder.shieldScope("Counter target spell."));
    }

    @Test
    public void aCreatureShieldNeverPairsWithALandWipe() {
        // THE bug this class exists to prevent: "creatures you control gain
        // indestructible" saves nothing whatsoever from Armageddon, so
        // pairing them would tell the pilot to blow up its own mana base
        assertFalse(PairedPlayFinder.Scope.CREATURES.covers(PairedPlayFinder.Scope.LANDS));
        assertTrue(PairedPlayFinder.Scope.CREATURES.covers(PairedPlayFinder.Scope.CREATURES));
        assertTrue(PairedPlayFinder.Scope.ALL_PERMANENTS.covers(PairedPlayFinder.Scope.LANDS));

        var pairs = PairedPlayFinder.find(deck(
                card("Armageddon", "Sorcery", "Destroy all lands.", 4),
                card("Grand Crescendo", "Instant",
                        "Create X 1/1 Citizen creature tokens. Creatures you control gain "
                        + "indestructible until end of turn.", 1)));
        assertTrue("a creature shield must not answer a land wipe: " + pairs, pairs.isEmpty());
    }

    @Test
    public void landWipePairsOnlyWithAnAllPermanentShield() {
        var pairs = PairedPlayFinder.find(deck(
                card("Armageddon", "Sorcery", "Destroy all lands.", 4),
                card("Teferi's Protection", "Instant",
                        "Until your next turn, your life total can't change and you gain "
                        + "protection from everything. All permanents you control phase out.", 3),
                card("Grand Crescendo", "Instant",
                        "Creatures you control gain indestructible until end of turn.", 1)));
        assertEquals(1, pairs.size());
        assertEquals("Armageddon", pairs.get(0).wipe());
        assertEquals("Teferi's Protection", pairs.get(0).protection());
        assertEquals(7, pairs.get(0).combinedManaValue());
        assertEquals("pp-armageddon-teferi-s-protection", pairs.get(0).id());
    }

    @Test
    public void aSorceryShieldCannotAnswerAWipeOnTheStack() {
        // the protection must resolve while the wipe waits — a sorcery
        // cannot be cast in response to anything
        var pairs = PairedPlayFinder.find(deck(
                card("Doomskar", "Sorcery", "Destroy all creatures.", 4),
                card("Slow Shield", "Sorcery",
                        "Creatures you control gain indestructible until end of turn.", 2)));
        assertTrue(pairs.isEmpty());
    }

    @Test
    public void aNonlandPhaseOutDoesNotSaveLands() {
        // Found by running the real deck: Clever Concealment phases out
        // "any number of target NONLAND permanents you control", and its text
        // contains "permanents you control" as a substring — so a naive check
        // read it as a blanket shield and happily paired it with Armageddon,
        // i.e. told the pilot to destroy its own mana base.
        String cleverConcealment = "Convoke. Any number of target nonland permanents "
                + "you control phase out.";
        assertEquals(PairedPlayFinder.Scope.NONLAND_PERMANENTS,
                PairedPlayFinder.shieldScope(cleverConcealment));
        assertFalse(PairedPlayFinder.Scope.NONLAND_PERMANENTS
                .covers(PairedPlayFinder.Scope.LANDS));
        assertTrue(PairedPlayFinder.Scope.NONLAND_PERMANENTS
                .covers(PairedPlayFinder.Scope.CREATURES));

        var pairs = PairedPlayFinder.find(deck(
                card("Armageddon", "Sorcery", "Destroy all lands.", 4),
                card("Clever Concealment", "Instant", cleverConcealment, 4)));
        assertTrue("nonland phasing must not answer a land wipe: " + pairs, pairs.isEmpty());
    }

    @Test
    public void manaValueComesFromThePrintedCost() {
        // the dossier stores "{3}{W}", not a number
        assertEquals(4, PairedPlayFinder.manaValue("{3}{W}"));
        assertEquals(2, PairedPlayFinder.manaValue("{W}{W}"));
        assertEquals(0, PairedPlayFinder.manaValue("{X}"));
        assertEquals(0, PairedPlayFinder.manaValue(""));
    }

    @Test
    public void cheapestPairSortsFirst() {
        var pairs = PairedPlayFinder.find(deck(
                card("Doomskar", "Sorcery", "Destroy all creatures.", 4),
                card("Flawless Maneuver", "Instant",
                        "Creatures you control gain indestructible until end of turn.", 3),
                card("Free Shield", "Instant",
                        "Creatures you control gain indestructible until end of turn.", 0)));
        assertEquals(2, pairs.size());
        assertEquals("Free Shield", pairs.get(0).protection());
    }
}
