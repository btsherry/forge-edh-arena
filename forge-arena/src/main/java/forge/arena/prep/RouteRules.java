package forge.arena.prep;

import java.util.List;
import java.util.regex.Pattern;

/**
 * win-routes/1 feature classification — the code form of WIN-ROUTES.md §2.
 * Ordered, first-match-wins, case-insensitive. Keep in lockstep with the doc;
 * a rules change bumps the version there and here together.
 */
public final class RouteRules {

    public static final String VERSION = "win-routes/2";

    public record Verdict(String category, List<String> routes) {
    }

    private record Rule(Pattern pattern, String category, List<String> routes) {
        Rule(String regex, String category, String... routes) {
            this(Pattern.compile(regex, Pattern.CASE_INSENSITIVE), category, List.of(routes));
        }
    }

    private static final List<Rule> RULES = List.of(
            new Rule("can't lose the game|can’t lose the game", "GUARD"),
            new Rule("^draw the game$", "GUARD"),
            // win-routes/2 (first Gate 3 feedback-loop amendment — flagged by the Urza dossier)
            new Rule("prevent all damage that would be dealt to you", "GUARD"),
            new Rule("protection from everything", "GUARD"),
            new Rule("^lock$", "LOCK_DISRUPTION"),
            new Rule("damage to all players|lifeloss for all players|card draw for all players"
                    + "|draw triggers for all players|lifegain for all players", "TABLE_HAZARD"),
            new Rule("self-mill", "RESOURCE"),
            new Rule("win(s)? the game", "WIN_TRIGGER", "ORACLE_WIN", "STATIC_THRESHOLD"),
            new Rule("opponent(s)?.* loses the game", "WIN_TRIGGER", "SPELL_LOSE"),
            new Rule("poison|infect|toxic", "LETHAL", "POISON_LOOP"),
            new Rule("damage to (all |most |some )?creatures", "BOARD_CONTROL"),
            new Rule("infinite combat damage", "LETHAL", "COMBAT_DAMAGE"),
            new Rule("infinite damage", "LETHAL", "DIRECT_DAMAGE_LOOP"),
            new Rule("infinite lifeloss", "LETHAL", "LIFELOSS_DRAIN"),
            new Rule("life total becomes (0|1)", "LETHAL", "SETUP_LETHAL"),
            new Rule("(infinite|near-infinite) mill", "LETHAL", "MILL_OPPONENTS"),
            new Rule("exile each opponent's library", "LETHAL", "MILL_OPPONENTS"),
            new Rule("(card draw|draw triggers) for .*opponent", "LETHAL", "FORCED_DRAW_OUT"),
            new Rule("infinite (extra )?turns", "LETHAL", "INFINITE_TURNS"),
            new Rule("infinite combat (phase|step)s?", "LETHAL", "EXTRA_COMBATS"),
            new Rule("infinitely large|infinite (power|\\+1/\\+1 counters)", "RESOURCE",
                    "SPREAD_COMBAT", "COMMANDER_DMG_SEQUENCE"),
            new Rule("infinite .*(token|copies)", "RESOURCE", "SPREAD_COMBAT"),
            new Rule("infinite card draw$|draw (all|your).*librar|exile your library.*play",
                    "RESOURCE", "DECK_ACCESS"),
            new Rule("infinite draw triggers$", "RESOURCE"),
            new Rule("(infinite|near-infinite) .*mana", "RESOURCE"),
            new Rule("infinite untap", "RESOURCE"),
            new Rule("infinite (etb|ltb|blinking|flicker)", "RESOURCE"),
            new Rule("(death|sacrifice) triggers", "RESOURCE"),
            new Rule("storm count|magecraft", "RESOURCE"),
            new Rule("infinite lifegain", "RESOURCE"),
            new Rule("infinite (scry|surveil|proliferat|energy|treasure|clue|food|blood|experience"
                    + "|charge|commander casts|landfall)", "RESOURCE"),
            new Rule("^(destroy|exile) (all|any number of|each|up to)|opponent(s)? sacrifice"
                    + "|counter the first|counter all|gain control of", "LOCK_DISRUPTION"));

    private RouteRules() {
    }

    public static Verdict classify(String featureName) {
        for (Rule rule : RULES) {
            if (rule.pattern().matcher(featureName).find()) {
                return new Verdict(rule.category(), rule.routes());
            }
        }
        return new Verdict("UNROUTABLE", List.of());
    }
}
