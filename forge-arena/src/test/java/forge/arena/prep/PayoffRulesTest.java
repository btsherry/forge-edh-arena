package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;
import java.util.Map;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * WIN-ROUTES §2b payoff classification against real oracle wordings —
 * including Forge's literal-backslash-n line separators.
 */
public class PayoffRulesTest {

    private void hits(String oracle, String... expected) {
        List<String> got = PayoffRules.classifyCard(oracle);
        for (String e : expected) {
            assertTrue(oracle + " -> " + got + " (missing " + e + ")", got.contains(e));
        }
        assertEquals(oracle + " -> " + got, expected.length, got.size());
    }

    @Test
    public void oracleWinClass() {
        // Thassa's Oracle
        hits("When Thassa's Oracle enters, look at the top X cards of your library, where X is "
                + "your devotion to blue. Put up to one of them on top of your library and the rest "
                + "on the bottom of your library in a random order. If X is greater than or equal to "
                + "the number of cards in your library, you win the game.", PayoffRules.ORACLE_WIN);
        // Laboratory Maniac / Jace, Wielder of Mysteries
        hits("If you would draw a card while your library has no cards in it, "
                + "you win the game instead.", PayoffRules.ORACLE_WIN);
    }

    @Test
    public void altWinIsTheRemainderClassNotASecondLabel() {
        // Simic Ascendancy: a win condition, but not an oracle-class one
        hits("{1}{G}{U}: Put a growth counter on Simic Ascendancy.\\nWhenever a creature you "
                + "control gets one or more +1/+1 counters, put that many growth counters on Simic "
                + "Ascendancy.\\nAt the beginning of your upkeep, if Simic Ascendancy has twenty or "
                + "more growth counters on it, you win the game.", PayoffRules.ALT_WIN);
        // oracle-win cards must NOT also be alt_win
        assertFalse(PayoffRules.classifyCard("you win the game instead.")
                .contains(PayoffRules.ALT_WIN));
    }

    @Test
    public void hasteClassesDistinguishStaticOneshotTargeted() {
        hits("All creatures have haste.", PayoffRules.HASTE_STATIC);        // Concordant Crossroads
        hits("Creatures you control have haste.", PayoffRules.HASTE_STATIC); // Fervor
        // Finale of Devastation: one-shot haste AND mass pump
        hits("Search your library and/or graveyard for a creature card with mana value X or less "
                + "and put it onto the battlefield. If you search your library this way, shuffle. "
                + "If X is 10 or more, creatures you control get +X/+X and gain haste until end of turn.",
                PayoffRules.HASTE_ONESHOT, PayoffRules.MASS_PUMP);
        // Lightning Greaves
        hits("Equipped creature has haste and shroud. (It can't be the target of spells or "
                + "abilities.)\\nEquip {0}", PayoffRules.HASTE_TARGETED);
    }

    @Test
    public void craterhoofIsMassPumpButGrantsNoHaste() {
        // its own Haste keyword (literal \n separator) must not read as a grant
        List<String> got = PayoffRules.classifyCard("Haste\\nWhen Craterhoof Behemoth enters, "
                + "creatures you control gain trample and get +X/+X until end of turn, where X is "
                + "the number of creatures you control.");
        assertEquals(List.of(PayoffRules.MASS_PUMP), got);
    }

    @Test
    public void damageAndDrainPayoffs() {
        // Purphoros / Impact Tremors
        hits("Whenever another creature you control enters, Purphoros, God of the Forge deals "
                + "2 damage to each opponent.", PayoffRules.PING_EACH_OPPONENT);
        // Walking Ballista
        hits("Walking Ballista enters with X +1/+1 counters on it.\\n{4}: Put a +1/+1 counter on "
                + "Walking Ballista.\\nRemove a +1/+1 counter from Walking Ballista: It deals "
                + "1 damage to any target.", PayoffRules.PING_ANY_TARGET);
        // Fireball class: the infinite-mana sink (players are legal targets)
        hits("Fireball deals X damage divided evenly, rounded down, among any number of targets.",
                PayoffRules.X_DAMAGE);
        hits("Banefire deals X damage to any target. If X is 5 or more, this spell can't be "
                + "countered, and the damage can't be prevented.",
                PayoffRules.X_DAMAGE, PayoffRules.PING_ANY_TARGET);
        // Polukranos-class creature-scoped X damage is board control, not a player kill
        hits("{X}{X}{G}: Monstrosity X.\\nWhen Polukranos, World Eater becomes monstrous, "
                + "it deals X damage divided among any number of target creatures. Each of those "
                + "creatures deals damage equal to its power to Polukranos.");
        // Blood Artist / Zulaport Cutthroat
        hits("Whenever Blood Artist or another creature dies, target player loses 1 life and "
                + "you gain 1 life.", PayoffRules.DRAIN_ON_TRIGGER);
        hits("Whenever Zulaport Cutthroat or another creature you control dies, each opponent "
                + "loses 1 life and you gain 1 life.", PayoffRules.DRAIN_ON_TRIGGER);
    }

    @Test
    public void cantLoseGuard() {
        hits("You can't lose the game and your opponents can't win the game.", PayoffRules.CANT_LOSE);
    }

    @Test
    public void nonPayoffTextMatchesNothing() {
        hits("{T}: Add {G}.");
        hits("Whenever another creature enters, its controller may draw a card if its power is "
                + "greater than each other creature's power.\\n{G}, {T}: Add X mana in any "
                + "combination of colors, where X is the greatest power among creatures you control.");
        hits(""); // and the degenerate cases
        assertTrue(PayoffRules.classifyCard(null).isEmpty());
    }

    @Test
    public void deckClassificationCollectsByClassWithoutDuplicates() throws Exception {
        var deckCards = new ObjectMapper().valueToTree(Map.of("cards", List.of(
                Map.of("name", "Concordant Crossroads", "zone", "main",
                        "oracle_text", "All creatures have haste."),
                Map.of("name", "Fervor", "zone", "main",
                        "oracle_text", "Creatures you control have haste."),
                Map.of("name", "Unresolved Card", "zone", "main"))));
        Map<String, List<String>> found = PayoffRules.classifyDeck(deckCards);
        assertEquals(List.of("Concordant Crossroads", "Fervor"), found.get(PayoffRules.HASTE_STATIC));
        assertEquals(1, found.size());
    }

    @Test
    public void v5OutletClasses() {
        // Exsanguinate — the playbook's premium class: one resolution, whole
        // table, life LOSS (dodges damage prevention)
        hits("Each opponent loses X life. You gain life equal to the life lost this way.",
                PayoffRules.X_DRAIN_EACH_OPPONENT);
        // Torment of Hailfire — repeat-X structure, fixed per-iteration loss
        hits("Repeat the following process X times. Each opponent loses 3 life unless "
                + "that player sacrifices a nonland permanent or discards a card.",
                PayoffRules.X_DRAIN_EACH_OPPONENT);
        // Blue Sun's Zenith — the DIG (self-targetable X draw)
        hits("Target player draws X cards. Shuffle Blue Sun's Zenith into its owner's library.",
                PayoffRules.SELF_DRAW_ENGINE);
        // Staff of Domination's activated draw
        hits("{5}, {T}: Draw a card.\\n{1}: Untap Staff of Domination.",
                PayoffRules.SELF_DRAW_ENGINE);
        // mill-out is DELAYED, not a same-turn kill
        hits("Target player mills X cards.", PayoffRules.MILL_OPPONENTS);
    }

    @Test
    public void digClassIsRestrictedToCastableXDrawSpells() {
        // PR-39 live find: the first conversion batch classified a CREATURE
        // ("{T}, Sacrifice another creature: You gain X life and draw X
        // cards") as a dig engine, and the pilot tried to CAST it at X=20.
        // The dig path converts by casting, so only instants/sorceries
        // qualify until an activation path exists.
        String disciple = "{T}, Sacrifice another creature: You gain X life and draw X cards, "
                + "where X is the sacrificed creature's toughness.";
        assertTrue("text alone still matches",
                PayoffRules.classifyCard(disciple).contains(PayoffRules.SELF_DRAW_ENGINE));
        assertFalse("a creature is not a castable dig",
                PayoffRules.classifyCard(disciple, "Creature — Elf Druid")
                        .contains(PayoffRules.SELF_DRAW_ENGINE));
        assertTrue("an X-draw instant is",
                PayoffRules.classifyCard("Target player draws X cards.", "Instant")
                        .contains(PayoffRules.SELF_DRAW_ENGINE));
    }

    @Test
    public void v5ConversionFlags() {
        assertTrue(PayoffRules.flags(PayoffRules.X_DRAIN_EACH_OPPONENT)
                .contains(PayoffRules.ConversionFlag.HITS_ALL_OPPONENTS));
        assertTrue(PayoffRules.flags(PayoffRules.PING_EACH_OPPONENT)
                .contains(PayoffRules.ConversionFlag.HITS_ALL_OPPONENTS));
        assertTrue(PayoffRules.flags(PayoffRules.MASS_PUMP)
                .contains(PayoffRules.ConversionFlag.NEEDS_COMBAT));
        assertTrue(PayoffRules.flags(PayoffRules.MILL_OPPONENTS)
                .contains(PayoffRules.ConversionFlag.RESOLVES_DELAYED));
        // single-target sinks carry no table-wide claim
        assertTrue(PayoffRules.flags(PayoffRules.PING_ANY_TARGET).isEmpty());
        assertTrue(PayoffRules.flags("unknown_class").isEmpty());
    }
}
