package forge.arena.prep;

import java.util.List;
import java.util.regex.Pattern;

/**
 * win-routes/4 feature classification — the code form of WIN-ROUTES.md §2.
 * Ordered, first-match-wins, case-insensitive. Keep in lockstep with the doc;
 * a rules change bumps the version there and here together.
 *
 * <p>win-routes/4: each rule carries a stable {@code ruleId} so the deck-level
 * coverage layer (WIN-ROUTES §2b, {@link DeckCoverage}) can map RESOURCE
 * feature classes onto conversion routes. Feature patterns are unchanged
 * from win-routes/3; the version bump covers the new §2b payoff/conversion
 * rule family ({@link PayoffRules}).
 */
public final class RouteRules {

    public static final String VERSION = "win-routes/4";

    public record Verdict(String category, List<String> routes, String ruleId) {
    }

    private record Rule(String id, Pattern pattern, String category, List<String> routes) {
        Rule(String id, String regex, String category, String... routes) {
            this(id, Pattern.compile(regex, Pattern.CASE_INSENSITIVE), category, List.of(routes));
        }
    }

    private static final List<Rule> RULES = List.of(
            new Rule("cant-lose", "can't lose the game|can’t lose the game", "GUARD"),
            new Rule("draw-the-game", "^draw the game$", "GUARD"),
            // win-routes/2 (first Gate 3 feedback-loop amendment — flagged by the Urza dossier)
            new Rule("prevent-damage-to-you", "prevent all damage that would be dealt to you", "GUARD"),
            new Rule("protection-everything", "protection from everything", "GUARD"),
            new Rule("lock", "^lock$", "LOCK_DISRUPTION"),
            new Rule("table-symmetric", "damage to all players|lifeloss for all players|card draw for all players"
                    + "|draw triggers for all players|lifegain for all players", "TABLE_HAZARD"),
            new Rule("self-mill", "self-mill", "RESOURCE"),
            new Rule("wins-game", "win(s)? the game", "WIN_TRIGGER", "ORACLE_WIN", "STATIC_THRESHOLD"),
            new Rule("opponent-loses", "opponent(s)?.* loses the game", "WIN_TRIGGER", "SPELL_LOSE"),
            new Rule("poison", "poison|infect|toxic", "LETHAL", "POISON_LOOP"),
            new Rule("damage-to-creatures",
                    "damage to (all |most |some |each |any number of )?(target )?creatures?", "BOARD_CONTROL"),
            new Rule("combat-damage", "infinite combat damage", "LETHAL", "COMBAT_DAMAGE"),
            // anchored (win-routes/3): scoped damage to non-player objects must not match
            new Rule("direct-damage",
                    "infinite damage( to (one|most|each|all|target|any number of)? ?(opponent|player)s?)?$",
                    "LETHAL", "DIRECT_DAMAGE_LOOP"),
            new Rule("lifeloss", "infinite lifeloss", "LETHAL", "LIFELOSS_DRAIN"),
            new Rule("life-to-one", "life total becomes (0|1)", "LETHAL", "SETUP_LETHAL"),
            new Rule("mill", "(infinite|near-infinite) mill", "LETHAL", "MILL_OPPONENTS"),
            new Rule("exile-library", "exile each opponent's library", "LETHAL", "MILL_OPPONENTS"),
            new Rule("forced-draw", "(card draw|draw triggers) for .*opponent", "LETHAL", "FORCED_DRAW_OUT"),
            new Rule("turns", "infinite (extra )?turns", "LETHAL", "INFINITE_TURNS"),
            new Rule("extra-combats", "infinite combat (phase|step)s?", "LETHAL", "EXTRA_COMBATS"),
            new Rule("pump", "infinitely large|infinite (power|\\+1/\\+1 counters)", "RESOURCE",
                    "SPREAD_COMBAT", "COMMANDER_DMG_SEQUENCE"),
            // \b guards against 'nontoken' (win-routes/3)
            new Rule("tokens", "infinite .*\\b(tokens?|copies)\\b", "RESOURCE", "SPREAD_COMBAT"),
            new Rule("deck-access", "infinite card draw$|draw (all|your).*librar|exile your library.*play",
                    "RESOURCE", "DECK_ACCESS"),
            new Rule("draw-triggers", "infinite draw triggers$", "RESOURCE"),
            new Rule("mana", "(infinite|near-infinite) .*mana", "RESOURCE"),
            new Rule("untap", "infinite untap", "RESOURCE"),
            new Rule("etb-flicker", "infinite (etb|ltb|blinking|flicker)", "RESOURCE"),
            new Rule("death-sac-triggers", "(death|sacrifice) triggers", "RESOURCE"),
            new Rule("storm-magecraft", "storm count|magecraft", "RESOURCE"),
            new Rule("lifegain", "infinite lifegain", "RESOURCE"),
            new Rule("counters-misc", "infinite (scry|surveil|proliferat|energy|treasure|clue|food|blood|experience"
                    + "|charge|commander casts|landfall)", "RESOURCE"),
            new Rule("lock-disruption", "^(destroy|exile) (all|any number of|each|up to)|opponent(s)? sacrifice"
                    + "|counter the first|counter all|gain control of", "LOCK_DISRUPTION"));

    private RouteRules() {
    }

    public static Verdict classify(String featureName) {
        return classify(featureName, "");
    }

    /**
     * Status-aware form (doc rule 30, win-routes/3): Spellbook feature status
     * "PU" marks a card-class placeholder used for variant generation, not a
     * runtime result — classified CARD_CLASS regardless of name.
     */
    public static Verdict classify(String featureName, String featureStatus) {
        if ("PU".equals(featureStatus)) {
            return new Verdict("CARD_CLASS", List.of(), "card-class");
        }
        for (Rule rule : RULES) {
            if (rule.pattern().matcher(featureName).find()) {
                return new Verdict(rule.category(), rule.routes(), rule.id());
            }
        }
        return new Verdict("UNROUTABLE", List.of(), "unroutable");
    }
}
