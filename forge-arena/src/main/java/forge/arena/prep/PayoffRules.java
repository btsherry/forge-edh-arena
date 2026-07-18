package forge.arena.prep;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * WIN-ROUTES §2b (win-routes/4) — payoff/enabler classification of the deck's
 * own cards. Where {@link RouteRules} classifies what a combo *produces*,
 * these rules classify what the 99 can *convert with*: the deck-level
 * coverage layer needs to know whether the payoff a route requires actually
 * exists in the deck (plan §3 Gate 3: "required payoff support from the 99").
 *
 * <p>Matching is against normalized oracle text (lowercased, newlines
 * flattened); a card may hit any number of classes (Finale of Devastation is
 * both mass_pump and haste_oneshot). Deterministic, versioned with
 * {@link RouteRules#VERSION}, amended through the same feedback loop.
 */
public final class PayoffRules {

    /** Payoff classes, in doc order. A card may belong to several. */
    public static final String ORACLE_WIN = "oracle_win";        // Thassa's Oracle / Lab Man class
    public static final String ALT_WIN = "alt_win";              // other "you win the game" cards
    public static final String CANT_LOSE = "cant_lose";          // Platinum Angel class
    public static final String HASTE_STATIC = "haste_static";    // Concordant Crossroads / Fervor
    public static final String HASTE_ONESHOT = "haste_oneshot";  // Finale / Overrun-with-haste class
    public static final String HASTE_TARGETED = "haste_targeted"; // Lightning Greaves class
    public static final String MASS_PUMP = "mass_pump";          // Craterhoof / Finale / Stampede
    public static final String PING_EACH_OPPONENT = "ping_each_opponent"; // Purphoros / Impact Tremors
    public static final String PING_ANY_TARGET = "ping_any_target";       // Walking Ballista / Niv-Mizzet
    public static final String X_DAMAGE = "x_damage";            // Fireball class (infinite-mana sink)
    public static final String DRAIN_ON_TRIGGER = "drain_on_trigger";     // Blood Artist / Zulaport class
    // win-routes/5 (Phase 6, the conversion-playbook outlet taxonomy):
    /** Exsanguinate/Torment class — ONE resolution ends the whole table. */
    public static final String X_DRAIN_EACH_OPPONENT = "x_drain_each_opponent";
    /** Blue Sun's / Stroke class — a CASTABLE X-draw spell (the dig, §1.11). */
    public static final String SELF_DRAW_ENGINE = "self_draw_engine";
    /**
     * The same dig, but hosted on a PERMANENT with an activated draw ability
     * (Sensei's Divining Top, Staff of Domination, The One Ring). Split from
     * {@link #SELF_DRAW_ENGINE} because the conversion module reaches them
     * differently — one is cast with a big X, the other is activated
     * repeatedly on the battlefield — and the first live conversion batch
     * proved the distinction matters: every dig engine in all four decks
     * turned out to be a permanent, so a cast-only dig path was dead code.
     */
    public static final String DRAW_ENGINE_PERMANENT = "draw_engine_permanent";
    /** Mill-out class — a DELAYED win (they lose on their next draw). */
    public static final String MILL_OPPONENTS = "mill_opponents";
    /** Pseudo-class injected by DeckCoverage when a commander is a creature. */
    public static final String COMMANDER_CREATURE = "commander_creature";

    /**
     * Classes an autopsy/library entry may assign (COMMANDER_CREATURE is
     * excluded — that's a computed type-line fact, never a classification).
     */
    public static final java.util.List<String> ASSIGNABLE_CLASSES = java.util.List.of(
            ORACLE_WIN, ALT_WIN, CANT_LOSE, HASTE_STATIC, HASTE_ONESHOT, HASTE_TARGETED,
            MASS_PUMP, PING_EACH_OPPONENT, PING_ANY_TARGET, X_DAMAGE, DRAIN_ON_TRIGGER,
            X_DRAIN_EACH_OPPONENT, SELF_DRAW_ENGINE, DRAW_ENGINE_PERMANENT, MILL_OPPONENTS);

    /**
     * Phase-6 conversion flags, CLASS-level facts the ConversionPlanner
     * reads (playbook §6): does one resolution clear the table, does the
     * win need combat, does it resolve a turn later. Deterministic
     * constants — never per-card analysis.
     */
    public enum ConversionFlag { HITS_ALL_OPPONENTS, NEEDS_COMBAT, RESOLVES_DELAYED }

    private static final Map<String, java.util.Set<ConversionFlag>> FLAGS = Map.of(
            X_DRAIN_EACH_OPPONENT, java.util.Set.of(ConversionFlag.HITS_ALL_OPPONENTS),
            PING_EACH_OPPONENT, java.util.Set.of(ConversionFlag.HITS_ALL_OPPONENTS),
            DRAIN_ON_TRIGGER, java.util.Set.of(ConversionFlag.HITS_ALL_OPPONENTS),
            MASS_PUMP, java.util.Set.of(ConversionFlag.NEEDS_COMBAT),
            HASTE_STATIC, java.util.Set.of(ConversionFlag.NEEDS_COMBAT),
            HASTE_ONESHOT, java.util.Set.of(ConversionFlag.NEEDS_COMBAT),
            HASTE_TARGETED, java.util.Set.of(ConversionFlag.NEEDS_COMBAT),
            MILL_OPPONENTS, java.util.Set.of(ConversionFlag.RESOLVES_DELAYED));

    /** The class's conversion flags (empty for single-target/utility classes). */
    public static java.util.Set<ConversionFlag> flags(String payoffClass) {
        return FLAGS.getOrDefault(payoffClass, java.util.Set.of());
    }

    private record Rule(String payoffClass, Pattern pattern) {
        Rule(String payoffClass, String regex) {
            this(payoffClass, Pattern.compile(regex));
        }
    }

    private static final List<Rule> RULES = List.of(
            new Rule(ORACLE_WIN, "you win the game instead"
                    + "|no cards in it, you win the game"
                    + "|equal to the number of cards in your library, you win the game"),
            new Rule(ALT_WIN, "you win the game"),
            new Rule(CANT_LOSE, "you can't lose the game|you can’t lose the game"),
            new Rule(HASTE_STATIC, "all creatures have haste|creatures you control have haste"),
            new Rule(HASTE_ONESHOT, "creatures you control [^.]*gain haste"),
            new Rule(HASTE_TARGETED, "equipped creature has haste"
                    + "|target creature [^.]*gains? haste"
                    + "|it gains haste"),
            new Rule(MASS_PUMP, "creatures you control [^.]*get \\+"),
            new Rule(PING_EACH_OPPONENT, "deals? (\\d+|x) damage to each opponent"),
            new Rule(PING_ANY_TARGET, "deals? (\\d+|x) damage to any target"),
            // player-capable X damage only: Polukranos-class creature-scoped X
            // damage must NOT read as a DIRECT_DAMAGE_LOOP payoff
            new Rule(X_DAMAGE, "deals? x damage to (any target|target player|target opponent|each opponent)"
                    + "|deals? x damage divided [^.]*among any number of targets"),
            new Rule(DRAIN_ON_TRIGGER,
                    "whenever [^.]*(dies|enters|leaves the battlefield|is put into a graveyard)"
                    + "[^.]*loses? (\\d+|x) life"),
            // win-routes/5 — the playbook taxonomy's premium class: one
            // resolution, no combat, no prevention (life LOSS, not damage);
            // the second alternation catches Torment's repeat-X structure
            new Rule(X_DRAIN_EACH_OPPONENT, "each opponent loses x life"
                    + "|repeat the following process x times\\. each opponent loses \\d+ life"),
            // the DIG: X-draw pointable at self, or a repeatable activated
            // draw ("{cost}: draw a card" — the colon guards against
            // triggered/static draw text matching)
            new Rule(SELF_DRAW_ENGINE, "(target player|you) draws? x cards"
                    + "|draw x cards"
                    + "|: [^.]*draws? (a|one|two|three) cards?"),
            new Rule(MILL_OPPONENTS, "(target player|each opponent) mills x"
                    + "|target opponent mills x"));

    private PayoffRules() {
    }

    /**
     * Type-aware classification (PR-39 live find). {@link #SELF_DRAW_ENGINE}
     * is the conversion module's DIG class and the module converts it by
     * CASTING it with a big X, so it must be a one-shot X-draw spell.
     * Oracle text alone cannot tell those from permanents whose activated
     * ability happens to draw — the first live batch classified a creature
     * ("{T}, Sacrifice another creature: ... draw X cards") as a dig engine
     * and the pilot tried to cast a 4-drop creature at X=20. Permanent-based
     * dig engines are real, but they need an ACTIVATION path the module does
     * not have yet; until then they must not masquerade as castable digs.
     */
    public static List<String> classifyCard(String oracleText, String typeLine) {
        List<String> hits = classifyCard(oracleText);
        if (hits.contains(SELF_DRAW_ENGINE) && typeLine != null && !typeLine.isBlank()) {
            String types = typeLine.toLowerCase();
            if (!types.contains("instant") && !types.contains("sorcery")) {
                // a permanent's draw is reached by ACTIVATION, not by casting
                // it with a big X — reclassify rather than discard, so the
                // deck keeps its dig engines
                hits = new ArrayList<>(hits);
                hits.remove(SELF_DRAW_ENGINE);
                hits.add(DRAW_ENGINE_PERMANENT);
            }
        }
        return hits;
    }

    /** Classes hit by one card's oracle text (ALT_WIN suppressed when ORACLE_WIN hits). */
    public static List<String> classifyCard(String oracleText) {
        // Forge card text separates lines with a LITERAL backslash-n; flatten
        // both forms so patterns never straddle an invisible line break
        String text = oracleText == null ? ""
                : oracleText.replace("\\n", " ").replace('\n', ' ').toLowerCase();
        List<String> hits = new ArrayList<>();
        for (Rule rule : RULES) {
            if (rule.pattern().matcher(text).find()) {
                // ALT_WIN is the "other win cards" remainder class, not a second
                // label for oracle-win cards
                if (rule.payoffClass().equals(ALT_WIN) && hits.contains(ORACLE_WIN)) {
                    continue;
                }
                hits.add(rule.payoffClass());
            }
        }
        return hits;
    }

    /**
     * Classify every card of a deck-cards.json document. Returns payoff class
     * -> card names (deck order preserved, no duplicates); only non-empty
     * classes appear. Unresolved cards (no oracle text) never match.
     */
    public static Map<String, List<String>> classifyDeck(JsonNode deckCards) {
        Map<String, List<String>> found = new LinkedHashMap<>();
        for (JsonNode card : deckCards.get("cards")) {
            String name = card.get("name").asText();
            for (String payoffClass : classifyCard(card.path("oracle_text").asText(""),
                    card.path("type_line").asText(""))) {
                List<String> names = found.computeIfAbsent(payoffClass, k -> new ArrayList<>());
                if (!names.contains(name)) {
                    names.add(name);
                }
            }
        }
        return found;
    }
}
