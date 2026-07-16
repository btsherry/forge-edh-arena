package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Plan §8 RouteCoverageTest (deck-level layer, v3.3): all-unroutable decks
 * are BLOCKED; fully-mapped decks expose ≥1 reachable route per included
 * combo; resource-only decks convert through 99-payoff support (the Selvala
 * shape); WIN-ROUTES §3 guards fire at prep time.
 */
public class DeckCoverageTest {

    private static DeckCoverage.ComboFeatures combo(String id, String... features) {
        List<DeckCoverage.Classified> classified = new ArrayList<>();
        for (String f : features) {
            classified.add(new DeckCoverage.Classified(f, RouteRules.classify(f)));
        }
        return new DeckCoverage.ComboFeatures(id, classified);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> route(Map<String, Object> deck, String name) {
        for (Map<String, Object> row : (List<Map<String, Object>>) deck.get("routes")) {
            if (row.get("route").equals(name)) {
                return row;
            }
        }
        throw new AssertionError("route " + name + " not in " + deck.get("routes"));
    }

    @SuppressWarnings("unchecked")
    private static List<String> guardIds(Map<String, Object> deck) {
        return ((List<Map<String, Object>>) deck.get("guards")).stream()
                .map(g -> (String) g.get("id")).toList();
    }

    @Test
    public void allUnroutableDeckIsBlocked() {
        Map<String, Object> deck = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite gremlin polkas")),
                Map.of(), List.of("Infinite gremlin polkas"));
        assertEquals("blocked", deck.get("status"));
        assertEquals(0, deck.get("win_paths"));
        assertTrue(guardIds(deck).contains("no_expressible_win_path"));
    }

    @Test
    public void directWinFeatureIsIntrinsic() {
        Map<String, Object> deck = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite damage")), Map.of(), List.of());
        assertEquals("clean", deck.get("status"));
        assertEquals(1, deck.get("win_paths"));
        Map<String, Object> row = route(deck, "DIRECT_DAMAGE_LOOP");
        assertEquals("direct", row.get("origin"));
        assertEquals("intrinsic", row.get("support"));
        assertEquals(List.of("c1"), row.get("from_combos"));
    }

    @Test
    public void selvalaShapeConvertsResourcesThroughThe99() {
        // resource-only combos + Crossroads/Craterhoof/creature-commander in the 99
        Map<String, List<String>> payoffs = Map.of(
                PayoffRules.HASTE_STATIC, List.of("Concordant Crossroads"),
                PayoffRules.MASS_PUMP, List.of("Craterhoof Behemoth"),
                PayoffRules.COMMANDER_CREATURE, List.of("Selvala, Heart of the Wilds"));
        Map<String, Object> deck = DeckCoverage.analyze(List.of(
                combo("c1", "Infinite card draw", "Infinite green mana"),
                combo("c2", "Infinitely large creature until end of turn")),
                payoffs, List.of());

        assertEquals("clean", deck.get("status"));
        // draw-the-deck deploy line AND the pump alpha both land on SPREAD_COMBAT
        Map<String, Object> spread = route(deck, "SPREAD_COMBAT");
        assertEquals("conversion", spread.get("origin"));
        assertEquals("supported", spread.get("support"));
        assertTrue(((List<?>) spread.get("from_combos")).containsAll(List.of("c1", "c2")));
        assertTrue(((List<?>) spread.get("enablers")).contains("Concordant Crossroads"));
        assertTrue(((List<?>) spread.get("enablers")).contains("Craterhoof Behemoth"));
        // creature commander makes the 21-damage sequence expressible
        assertEquals("supported", route(deck, "COMMANDER_DMG_SEQUENCE").get("support"));
        // no oracle effect: ORACLE_WIN listed but unsupported, with the guard note
        Map<String, Object> oracle = route(deck, "ORACLE_WIN");
        assertEquals("unsupported", oracle.get("support"));
        assertEquals(List.of(PayoffRules.ORACLE_WIN), oracle.get("missing"));
        assertTrue(guardIds(deck).contains("oracle_guard"));
        assertTrue((int) deck.get("win_paths") >= 2);
    }

    @Test
    public void resourceOnlyComboWithNoPayoffsIsBlocked() {
        Map<String, Object> deck = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite green mana", "Infinite untap of creatures you control")),
                Map.of(), List.of());
        assertEquals("blocked", deck.get("status"));
        assertTrue(guardIds(deck).contains("no_expressible_win_path"));
    }

    @Test
    public void tokensNeedMassHasteButBigCreatureCanRideGreaves() {
        Map<String, List<String>> greavesOnly = Map.of(
                PayoffRules.HASTE_TARGETED, List.of("Lightning Greaves"));
        // fresh tokens with only targeted haste: not expressible
        Map<String, Object> tokens = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite creature tokens")), greavesOnly, List.of());
        assertEquals("unsupported", route(tokens, "SPREAD_COMBAT").get("support"));
        // one infinitely large creature CAN wear Greaves: partial (usable, hazards priced)
        Map<String, Object> pump = DeckCoverage.analyze(
                List.of(combo("c1", "Infinitely large creature until end of turn")),
                greavesOnly, List.of());
        assertEquals("partial", route(pump, "SPREAD_COMBAT").get("support"));
        assertTrue((int) pump.get("win_paths") >= 1);
    }

    @Test
    public void manaConvertsThroughXDamage() {
        Map<String, Object> deck = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite colorless mana")),
                Map.of(PayoffRules.X_DAMAGE, List.of("Fireball")), List.of());
        Map<String, Object> row = route(deck, "DIRECT_DAMAGE_LOOP");
        assertEquals("supported", row.get("support"));
        assertEquals(List.of("Fireball"), row.get("enablers"));
        assertEquals("clean", deck.get("status"));
    }

    @Test
    public void lockWithoutClockIsNamedNotSilentlyPunished() {
        Map<String, Object> deck = DeckCoverage.analyze(
                List.of(combo("c1", "Destroy all permanents opponents control each turn")),
                Map.of(), List.of());
        assertEquals("blocked", deck.get("status"));
        List<String> guards = guardIds(deck);
        assertTrue(guards.contains("no_expressible_win_path"));
        assertTrue(guards.contains("lock_without_clock"));
    }

    @Test
    public void tableHazardWithoutGuardWarns() {
        // symmetric hazard + a real win path: warned, not blocked
        Map<String, Object> deck = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite damage to all players", "Infinite damage")),
                Map.of(), List.of());
        assertEquals("clean", deck.get("status"));
        assertTrue(guardIds(deck).contains("table_hazard_without_guard"));
        // with a Platinum Angel class guard in the 99: no warning
        Map<String, Object> guarded = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite damage to all players", "Infinite damage")),
                Map.of(PayoffRules.CANT_LOSE, List.of("Platinum Angel")), List.of());
        assertFalse(guardIds(guarded).contains("table_hazard_without_guard"));
    }

    @Test
    public void deckWithNoCombosIsCleanAndInert() {
        Map<String, Object> deck = DeckCoverage.analyze(List.of(), Map.of(), List.of());
        assertEquals("clean", deck.get("status"));
        assertEquals(0, deck.get("win_paths"));
        assertEquals(List.of("no_included_combos"), guardIds(deck));
    }

    @Test
    public void unroutableFeaturesFlagWithoutBlockingWhenAWinPathExists() {
        Map<String, Object> deck = DeckCoverage.analyze(
                List.of(combo("c1", "Infinite damage", "Infinite gremlin polkas")),
                Map.of(), List.of("Infinite gremlin polkas"));
        assertEquals("unroutable_flagged", deck.get("status"));
        assertTrue((int) deck.get("win_paths") >= 1);
    }

    @Test
    public void payoffsHelperInjectsCommanderCreature() throws Exception {
        var deckCards = new ObjectMapper().valueToTree(Map.of("cards", List.of(
                Map.of("name", "Selvala, Heart of the Wilds", "zone", "commander",
                        "type_line", "Legendary Creature - Elf Scout",
                        "oracle_text", "{G}, {T}: Add X mana."),
                Map.of("name", "Concordant Crossroads", "zone", "main",
                        "type_line", "World Enchantment",
                        "oracle_text", "All creatures have haste."))));
        Map<String, List<String>> payoffs = DeckCoverage.payoffs(deckCards);
        assertEquals(List.of("Selvala, Heart of the Wilds"),
                payoffs.get(PayoffRules.COMMANDER_CREATURE));
        assertEquals(List.of("Concordant Crossroads"), payoffs.get(PayoffRules.HASTE_STATIC));
    }
}
