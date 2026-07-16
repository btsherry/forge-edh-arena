package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import org.testng.annotations.Test;

/** win-routes/1 classification — representative rows from WIN-ROUTES.md §2. */
public class RouteRulesTest {

    private void check(String feature, String category, String... expectRoute) {
        RouteRules.Verdict v = RouteRules.classify(feature);
        assertEquals(feature, category, v.category());
        for (String r : expectRoute) {
            assertTrue(feature + " -> " + v.routes(), v.routes().contains(r));
        }
    }

    @Test
    public void classificationTable() {
        check("Each opponent loses the game", "WIN_TRIGGER", "SPELL_LOSE");
        check("Win the game", "WIN_TRIGGER", "ORACLE_WIN");
        check("Infinite damage", "LETHAL", "DIRECT_DAMAGE_LOOP");
        check("Infinite combat damage", "LETHAL", "COMBAT_DAMAGE");
        check("Infinite lifeloss for each opponent", "LETHAL", "LIFELOSS_DRAIN");
        check("Infinite turns", "LETHAL", "INFINITE_TURNS");
        check("Infinite combat phases", "LETHAL", "EXTRA_COMBATS");
        check("Infinite mill", "LETHAL", "MILL_OPPONENTS");
        check("Infinite poison counters", "LETHAL", "POISON_LOOP");
        check("Infinite green mana", "RESOURCE");
        check("Infinite colored mana", "RESOURCE");
        check("Infinite untap of creatures you control", "RESOURCE");
        check("Infinite card draw", "RESOURCE", "DECK_ACCESS");
        check("Infinite lifegain", "RESOURCE"); // never a win-trigger (anti-catalog)
        check("Infinite ETB", "RESOURCE");
        check("Infinite storm count", "RESOURCE");
        check("Infinitely large creature until end of turn", "RESOURCE", "SPREAD_COMBAT");
        check("Infinite damage to all creatures", "BOARD_CONTROL");
        check("Infinite damage to all players", "TABLE_HAZARD");
        check("You can't lose the game", "GUARD");
        check("Destroy all permanents opponents control each turn", "LOCK_DISRUPTION");
        check("Infinite self-mill", "RESOURCE");
        check("Infinite gremlin polkas", "UNROUTABLE");
        // win-routes/2 additions (from the Urza dossier's unroutable flags)
        check("Prevent all damage that would be dealt to you", "GUARD");
        check("You have protection from everything", "GUARD");
        check("Lock", "LOCK_DISRUPTION");
        // win-routes/3: real vocab coverage widened
        check("Infinite damage to one opponent", "LETHAL", "DIRECT_DAMAGE_LOOP");
        check("Infinite damage to most opponents", "LETHAL", "DIRECT_DAMAGE_LOOP");
        check("Near-infinite mill", "LETHAL", "MILL_OPPONENTS");
        check("Infinite tapped creature tokens", "RESOURCE", "SPREAD_COMBAT");
    }

    @Test
    public void winRoutes3RegressionFixes() {
        // 'nontoken' must NOT hit the token rule (word boundary): untap rule wins, no SPREAD_COMBAT
        RouteRules.Verdict v = RouteRules.classify("Infinite untap of nontoken creatures you control");
        assertEquals("RESOURCE", v.category());
        assertTrue("nontoken must not gain SPREAD_COMBAT via the token rule: " + v.routes(),
                !v.routes().contains("SPREAD_COMBAT"));
        // anchored damage rule: scoped non-player damage is BOARD_CONTROL, not player-lethal
        assertEquals("BOARD_CONTROL",
                RouteRules.classify("Infinite damage to each creature an opponent controls").category());
        // doc rule 30: PU status = card-class placeholder regardless of name
        assertEquals("CARD_CLASS", RouteRules.classify("Extra Turn Spell", "PU").category());
        assertEquals("CARD_CLASS", RouteRules.classify("Infinite damage", "PU").category());
    }

    @Test
    public void orderMatters() {
        // "damage to all players" must hit TABLE_HAZARD before the generic damage rule
        assertEquals("TABLE_HAZARD", RouteRules.classify("Infinite damage to all players").category());
        // creature damage must hit BOARD_CONTROL before generic LETHAL damage
        assertEquals("BOARD_CONTROL", RouteRules.classify("Infinite damage to creatures").category());
    }
}
