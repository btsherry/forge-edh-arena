package forge.arena.prep;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Deck-level route coverage (plan §3 Gate 3, v3.2/v3.3; WIN-ROUTES §2b/§3) —
 * the layer above per-feature classification: given every combo's classified
 * features and the 99's payoff classes, compute which win routes are actually
 * expressible for THIS deck.
 *
 * <p>Two ways a route becomes expressible: <b>direct</b> — a LETHAL or
 * WIN_TRIGGER feature names it (the combo itself is the payoff, support is
 * intrinsic); <b>conversion</b> — a RESOURCE feature class maps onto it via
 * payoff support from the 99 (the Selvala shape: DECK_ACCESS + Craterhoof +
 * Concordant Crossroads → SPREAD_COMBAT). A deck with included combos and
 * ZERO expressible routes is <b>blocked</b>: its win path cannot be expressed
 * to the LethalityPlanner, so batch results would understate it (plan §3).
 *
 * <p>Pure data in/out — no Forge imports, no I/O. Versioned with
 * {@link RouteRules#VERSION}.
 */
public final class DeckCoverage {

    /** One combo's classified produces-features (from the Gate 3 pass). */
    public record ComboFeatures(String comboId, List<Classified> features) {
    }

    public record Classified(String name, RouteRules.Verdict verdict) {
    }

    /** A support requirement group: satisfied fully, partially, or not at all. */
    private record Group(Set<String> full, Set<String> partial) {
        static Group of(String... fullClasses) {
            return new Group(Set.of(fullClasses), Set.of());
        }

        static Group withPartial(Set<String> full, Set<String> partial) {
            return new Group(full, partial);
        }
    }

    /** A conversion: RESOURCE rule id -> route, gated by requirement groups. */
    private record Conversion(String route, List<Group> groups) {
    }

    private static final Set<String> HASTE_FULL = Set.of(PayoffRules.HASTE_STATIC, PayoffRules.HASTE_ONESHOT);
    private static final Set<String> HASTE_PARTIAL = Set.of(PayoffRules.HASTE_TARGETED);

    /**
     * WIN-ROUTES §2b conversion table: which routes a RESOURCE feature class
     * can reach, and the payoff classes the 99 must supply. Keyed by
     * {@link RouteRules} rule id.
     */
    private static final Map<String, List<Conversion>> CONVERSIONS = Map.of(
            "pump", List.of(
                    new Conversion("SPREAD_COMBAT",
                            List.of(Group.withPartial(HASTE_FULL, HASTE_PARTIAL))),
                    new Conversion("COMMANDER_DMG_SEQUENCE",
                            List.of(Group.of(PayoffRules.COMMANDER_CREATURE)))),
            "tokens", List.of(
                    new Conversion("SPREAD_COMBAT",
                            List.of(new Group(HASTE_FULL, Set.of())))),
            "deck-access", List.of(
                    new Conversion("ORACLE_WIN",
                            List.of(Group.of(PayoffRules.ORACLE_WIN))),
                    new Conversion("SPREAD_COMBAT",
                            List.of(Group.of(PayoffRules.MASS_PUMP),
                                    Group.withPartial(HASTE_FULL, HASTE_PARTIAL)))),
            "mana", List.of(
                    new Conversion("DIRECT_DAMAGE_LOOP",
                            List.of(Group.withPartial(Set.of(PayoffRules.X_DAMAGE),
                                    Set.of(PayoffRules.PING_ANY_TARGET)))),
                    new Conversion("STATIC_THRESHOLD",
                            List.of(Group.of(PayoffRules.ALT_WIN)))),
            "etb-flicker", List.of(
                    new Conversion("DIRECT_DAMAGE_LOOP",
                            List.of(Group.withPartial(Set.of(PayoffRules.PING_EACH_OPPONENT),
                                    Set.of(PayoffRules.PING_ANY_TARGET)))),
                    new Conversion("LIFELOSS_DRAIN",
                            List.of(Group.of(PayoffRules.DRAIN_ON_TRIGGER)))),
            "death-sac-triggers", List.of(
                    new Conversion("LIFELOSS_DRAIN",
                            List.of(Group.of(PayoffRules.DRAIN_ON_TRIGGER))),
                    new Conversion("DIRECT_DAMAGE_LOOP",
                            List.of(Group.withPartial(Set.of(PayoffRules.PING_EACH_OPPONENT),
                                    Set.of(PayoffRules.PING_ANY_TARGET))))),
            "draw-triggers", List.of(
                    new Conversion("DIRECT_DAMAGE_LOOP",
                            List.of(Group.of(PayoffRules.PING_EACH_OPPONENT, PayoffRules.PING_ANY_TARGET)))));

    private static final int RANK_INTRINSIC = 3;
    private static final int RANK_SUPPORTED = 2;
    private static final int RANK_PARTIAL = 1;
    private static final int RANK_UNSUPPORTED = 0;

    /** Mutable per-route accumulator while merging origins. */
    private static final class RouteState {
        int rank = -1;
        boolean direct;
        final Set<String> fromCombos = new LinkedHashSet<>();
        final Set<String> enablers = new LinkedHashSet<>();
        Set<String> missing = Set.of();
    }

    private DeckCoverage() {
    }

    /**
     * Payoff classification of the 99 plus the {@code commander_creature}
     * pseudo-class (COMMANDER_DMG_SEQUENCE needs a combat-capable commander;
     * that is a type-line fact, not an oracle-text pattern).
     */
    public static Map<String, List<String>> payoffs(JsonNode deckCards) {
        Map<String, List<String>> found = PayoffRules.classifyDeck(deckCards);
        for (JsonNode card : deckCards.get("cards")) {
            if (card.get("zone").asText().equals("commander")
                    && card.path("type_line").asText("").contains("Creature")) {
                found.computeIfAbsent(PayoffRules.COMMANDER_CREATURE, k -> new ArrayList<>())
                        .add(card.get("name").asText());
            }
        }
        return found;
    }

    /**
     * The deck-level coverage report (the route-coverage/2 {@code deck}
     * section, JSON-shaped). {@code unroutableFeatures} comes from the
     * per-feature pass; combos and payoffs as documented above.
     */
    public static Map<String, Object> analyze(List<ComboFeatures> combos,
            Map<String, List<String>> payoffs, List<String> unroutableFeatures) {
        Map<String, RouteState> routes = new TreeMap<>();

        for (ComboFeatures combo : combos) {
            for (Classified feature : combo.features()) {
                String category = feature.verdict().category();
                if (category.equals("LETHAL") || category.equals("WIN_TRIGGER")) {
                    for (String route : feature.verdict().routes()) {
                        RouteState state = routes.computeIfAbsent(route, r -> new RouteState());
                        if (RANK_INTRINSIC > state.rank) {
                            state.rank = RANK_INTRINSIC;
                            state.missing = Set.of();
                        }
                        state.direct = true;
                        state.fromCombos.add(combo.comboId());
                    }
                } else if (category.equals("RESOURCE")) {
                    for (Conversion conversion : CONVERSIONS.getOrDefault(
                            feature.verdict().ruleId(), List.of())) {
                        applyConversion(routes, combo.comboId(), conversion, payoffs);
                    }
                }
            }
        }

        List<Map<String, Object>> routeRows = new ArrayList<>();
        int winPaths = 0;
        for (Map.Entry<String, RouteState> e : routes.entrySet()) {
            RouteState state = e.getValue();
            String support = switch (state.rank) {
                case RANK_INTRINSIC -> "intrinsic";
                case RANK_SUPPORTED -> "supported";
                case RANK_PARTIAL -> "partial";
                default -> "unsupported";
            };
            if (state.rank > RANK_UNSUPPORTED) {
                winPaths++;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("route", e.getKey());
            row.put("origin", state.direct ? "direct" : "conversion");
            row.put("support", support);
            row.put("from_combos", new ArrayList<>(state.fromCombos));
            if (!state.enablers.isEmpty()) {
                row.put("enablers", new ArrayList<>(state.enablers));
            }
            if (!state.missing.isEmpty()) {
                row.put("missing", new ArrayList<>(state.missing));
            }
            routeRows.add(row);
        }
        // most viable first, then alphabetical — deterministic, diff-friendly
        routeRows.sort((a, b) -> {
            int r = Integer.compare(supportRank((String) b.get("support")),
                    supportRank((String) a.get("support")));
            return r != 0 ? r : ((String) a.get("route")).compareTo((String) b.get("route"));
        });

        List<Map<String, Object>> guards = guards(combos, payoffs, winPaths);
        boolean blocked = guards.stream().anyMatch(g -> g.get("severity").equals("blocking"));
        String status = blocked ? "blocked"
                : !unroutableFeatures.isEmpty() ? "unroutable_flagged" : "clean";

        Map<String, Object> deck = new LinkedHashMap<>();
        deck.put("payoffs", payoffs);
        deck.put("routes", routeRows);
        deck.put("guards", guards);
        deck.put("win_paths", winPaths);
        deck.put("status", status);
        return deck;
    }

    private static void applyConversion(Map<String, RouteState> routes, String comboId,
            Conversion conversion, Map<String, List<String>> payoffs) {
        boolean allFull = true;
        boolean allHit = true;
        Set<String> enablers = new LinkedHashSet<>();
        Set<String> missing = new LinkedHashSet<>();
        for (Group group : conversion.groups()) {
            boolean fullHit = false;
            boolean partialHit = false;
            for (String payoffClass : group.full()) {
                if (payoffs.containsKey(payoffClass)) {
                    fullHit = true;
                    enablers.addAll(payoffs.get(payoffClass));
                }
            }
            for (String payoffClass : group.partial()) {
                if (payoffs.containsKey(payoffClass)) {
                    partialHit = true;
                    enablers.addAll(payoffs.get(payoffClass));
                }
            }
            if (!fullHit) {
                allFull = false;
                missing.addAll(group.full());
                if (!partialHit) {
                    allHit = false;
                }
            }
        }
        int rank = allFull ? RANK_SUPPORTED : allHit ? RANK_PARTIAL : RANK_UNSUPPORTED;

        RouteState state = routes.computeIfAbsent(conversion.route(), r -> new RouteState());
        state.fromCombos.add(comboId);
        state.enablers.addAll(enablers);
        if (rank > state.rank) {
            state.rank = rank;
            state.missing = missing;
        }
    }

    private static int supportRank(String support) {
        return switch (support) {
            case "intrinsic" -> RANK_INTRINSIC;
            case "supported" -> RANK_SUPPORTED;
            case "partial" -> RANK_PARTIAL;
            default -> RANK_UNSUPPORTED;
        };
    }

    /** WIN-ROUTES §3 guards, evaluated at prep time. */
    private static List<Map<String, Object>> guards(List<ComboFeatures> combos,
            Map<String, List<String>> payoffs, int winPaths) {
        List<Map<String, Object>> guards = new ArrayList<>();
        if (combos.isEmpty()) {
            guards.add(guard("no_included_combos", "info",
                    "deck has no included Spellbook combos — the combo-aware layer is inert"
                            + " for this deck (stock AI only); this is not a defect"));
            return guards;
        }

        boolean deckAccess = false;
        boolean tableHazard = false;
        boolean lock = false;
        boolean anyRoutable = false;
        for (ComboFeatures combo : combos) {
            for (Classified feature : combo.features()) {
                String category = feature.verdict().category();
                deckAccess |= feature.verdict().ruleId().equals("deck-access");
                tableHazard |= category.equals("TABLE_HAZARD");
                lock |= category.equals("LOCK_DISRUPTION");
                anyRoutable |= !category.equals("UNROUTABLE") && !category.equals("CARD_CLASS");
            }
        }

        if (deckAccess && !payoffs.containsKey(PayoffRules.ORACLE_WIN)) {
            guards.add(guard("oracle_guard", "info",
                    "DECK_ACCESS present but no Thassa's Oracle/Laboratory Maniac class effect"
                            + " in the 99 — ORACLE_WIN is not expressible; self-draw must stop"
                            + " short of the library (WIN-ROUTES §3)"));
        }
        if (tableHazard && !payoffs.containsKey(PayoffRules.CANT_LOSE)) {
            guards.add(guard("table_hazard_without_guard", "warning",
                    "symmetric TABLE_HAZARD features with no \"can't lose\" guard in the 99 —"
                            + " routes using them are self-lethal (WIN-ROUTES §3)"));
        }
        if (winPaths == 0) {
            guards.add(guard("no_expressible_win_path", "blocking",
                    anyRoutable
                            ? "combos produce only resources and the 99 lacks every required"
                                    + " payoff — no route is expressible to the planner; batch"
                                    + " results would understate this deck (plan §3 Gate 3)"
                            : "every produces-feature is UNROUTABLE or CARD_CLASS — the deck's"
                                    + " win path is not expressible to the planner (plan §3 Gate 3)"));
            if (lock) {
                guards.add(guard("lock_without_clock", "warning",
                        "LOCK_DISRUPTION features with no lethal route in the deck — games end"
                                + " in timeout_draw, not wins; batch stats would silently punish"
                                + " this archetype (WIN-ROUTES §3)"));
            }
        }
        return guards;
    }

    private static Map<String, Object> guard(String id, String severity, String detail) {
        Map<String, Object> g = new LinkedHashMap<>();
        g.put("id", id);
        g.put("severity", severity);
        g.put("detail", detail);
        return g;
    }
}
