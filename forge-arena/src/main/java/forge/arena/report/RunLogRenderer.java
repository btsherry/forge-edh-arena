package forge.arena.report;

import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Renders an {@link ArenaEvent} as one human-readable run.log line (plan §5
 * v3.2). This same renderer is reused post-hoc by the §7(a) auto-narrative
 * generator — one implementation, two moments of use.
 *
 * Default tier = game lifecycle + combo/route/tutor decisions; verbose adds
 * per-tick engine events.
 */
public final class RunLogRenderer {

    public enum Tier { DEFAULT, VERBOSE }

    /** Types shown at the default tier; everything else needs verbose. */
    private static final Set<String> DEFAULT_TIER_TYPES = Set.of(
            "game_start", "game_end",
            "combo_ready", "combo_ignored", "combo_shortcut", "combo_stalled",
            "line_entered", "line_aborted",
            "route_selected", "route_rejected",
            "tutor_decision", "mulligan_decision",
            "turn_summary",
            // Phase 6 observability: the default log is what a human reads
            // when asking "what happened in this game?" — the per-turn board
            // snapshot (life/hand/creatures/power for every seat) and the
            // conversion decisions belong there, not behind VERBOSE
            "turn_state", "conversion_step", "outlet_drill", "lethal_alpha",
            "distance_to_fire", "program_complete", "program_abort", "loop_prereq",
            "governor_plan", "drill_suppressed", "pairing_entered", "pairing_complete",
            "pairing_abort", "engine_cycle", "engine_abort", "storm_cast");

    private RunLogRenderer() {
    }

    public static Optional<String> render(ArenaEvent e, String workerId, int gameIndex, Tier tier) {
        return render(e, workerId, gameIndex, tier, null);
    }

    /**
     * @param seatNames deck id per seat for THIS game (seating rotates, so a
     *                  bare seat index is ambiguous across games), or null
     */
    public static Optional<String> render(ArenaEvent e, String workerId, int gameIndex, Tier tier,
            java.util.List<String> seatNames) {
        if (tier != Tier.VERBOSE && !DEFAULT_TIER_TYPES.contains(e.t())) {
            return Optional.empty();
        }
        StringBuilder sb = new StringBuilder();
        sb.append('[').append('w').append(workerId).append(" g").append(String.format("%04d", gameIndex));
        if (e.turn() != null) {
            sb.append(" t").append(e.turn());
        }
        if (e.seat() != null) {
            sb.append(' ').append(seatLabel(e.seat(), seatNames));
        }
        sb.append("] ").append(detail(e, seatNames));
        return Optional.of(sb.toString());
    }

    /** "s2/urza" when the seating is known, else plain "s2". */
    private static String seatLabel(Object seat, java.util.List<String> seatNames) {
        String label = "s" + seat;
        if (seatNames == null || !(seat instanceof Number n)) {
            return label;
        }
        int idx = n.intValue();
        if (idx < 0 || idx >= seatNames.size()) {
            return label;
        }
        return label + "/" + shortDeck(seatNames.get(idx));
    }

    /** "selvala-heart-of-the-wilds" -> "selvala": readable at a glance. */
    private static String shortDeck(String deckId) {
        int dash = deckId.indexOf('-');
        return dash > 0 ? deckId.substring(0, dash) : deckId;
    }

    private static String detail(ArenaEvent e, java.util.List<String> seatNames) {
        Map<String, Object> f = e.fields();
        switch (e.t()) {
            case "game_start":
                return "game start  seats: " + f.get("seats") + "  seed=" + f.get("seed");
            case "game_end": {
                Object result = f.get("result");
                if ("win".equals(result)) {
                    return "WIN    seat " + f.get("winner_seat") + " " + f.get("winner")
                            + "  (" + f.get("win_condition") + ", " + f.get("turns") + " turns)";
                }
                return String.valueOf(result).toUpperCase() + "  ("
                        + (f.get("limiting_factor") != null ? "limit: " + f.get("limiting_factor") + ", " : "")
                        + f.get("turns") + " turns)";
            }
            case "turn_begin":
                return "turn " + e.turn() + " begins";
            case "turn_state":
                return "state  " + seatRows(f, s -> stateRow(s, seatNames));
            case "turn_summary":
                return "flow   " + seatRows(f, s -> flowRow(s, seatNames));
            // Phase 6 conversion telemetry: WHY a banked engine did or did
            // not become a win — the question the long-200 post-mortem had
            // to infer from route names alone
            case "distance_to_fire":
                return "dist   " + f.get("distance") + " to fire";
            case "conversion_step":
                return "CONVERT " + f.get("kind") + "  " + f.get("card")
                        + "  (" + f.get("outlet_class")
                        + (f.get("x") != null ? ", X=" + f.get("x") : "") + ")";
            case "outlet_drill":
                return "drill  " + f.get("outlet") + " -> "
                        + seatLabel(f.get("target_seat"), seatNames)
                        + (f.get("outlet_counters") != null
                                ? "  [i" + f.get("iteration")
                                        + " counters=" + f.get("outlet_counters")
                                        + " life=" + f.get("own_life") + "]"
                                : "");
            case "lethal_alpha":
                return "ALPHA  " + f.get("guaranteed_damage") + " guaranteed -> "
                        + seatLabel(f.get("target_seat"), seatNames)
                        + " (" + f.get("target_life") + "hp)";
            case "land_played":
                return "land   " + f.get("desc");
            case "life_change":
                return "life   " + f.get("player") + " " + f.get("old") + " -> " + f.get("new");
            case "spell_cast":
                return "cast   " + f.get("desc");
            case "zone_change":
                return "zone   " + f.get("card") + "  " + f.get("from") + " -> " + f.get("to");
            case "combo_ready":
                return "READY  " + f.get("combo") + "  (" + f.get("window") + ")";
            case "combo_ignored":
                return "ignore " + f.get("combo") + "  (" + f.get("reason") + ")";
            case "line_entered":
                return "line   " + f.get("combo") + " via " + f.get("attempted_via") + "  entered " + f.get("entry_phase");
            case "line_aborted":
                return "ABORT  line (" + f.get("cause")
                        + (f.get("detail") != null ? ": " + f.get("detail") : "")
                        + (f.get("piece_lost") != null ? ", lost " + f.get("piece_lost") : "") + ")";
            case "combo_shortcut":
                return "loop   " + f.get("combo") + " proven x" + f.get("iterations_proven") + " -> " + f.get("bounded_product");
            case "route_selected":
                return "route  " + f.get("route") + " selected  " + f.get("predicates");
            case "route_rejected":
                return "route  " + f.get("route") + " rejected  (" + f.get("failed_predicate") + ")";
            case "combo_stalled":
                return "STALL  " + f.get("binding") + "  dump " + f.get("dump_path");
            case "tutor_decision":
                return "tutor  " + f.get("source") + " -> " + f.get("chosen");
            case "mulligan_decision":
                return "mull   " + f.get("decision") + "  (" + f.get("reason") + ")";
            default:
                return e.t() + "  " + f;
        }
    }

    @SuppressWarnings("unchecked")
    private static String seatRows(Map<String, Object> fields,
            java.util.function.Function<Map<String, Object>, String> row) {
        Object seats = fields.get("seats");
        if (!(seats instanceof java.util.List<?> list)) {
            return String.valueOf(seats);
        }
        StringBuilder sb = new StringBuilder();
        for (Object o : list) {
            if (o instanceof Map<?, ?> m) {
                if (sb.length() > 0) {
                    sb.append("  ");
                }
                sb.append(row.apply((Map<String, Object>) m));
            }
        }
        return sb.toString();
    }

    private static String stateRow(Map<String, Object> s, java.util.List<String> seatNames) {
        return seatLabel(s.get("seat"), seatNames) + ":" + s.get("life") + "hp/"
                + s.get("hand") + "h/" + s.get("creatures") + "cr/"
                + s.get("board_power") + "pw";
    }

    @SuppressWarnings("unchecked")
    private static String flowRow(Map<String, Object> s, java.util.List<String> seatNames) {
        Map<String, Object> dealt = s.get("damage_dealt") instanceof Map
                ? (Map<String, Object>) s.get("damage_dealt") : Map.of();
        int dmg = ((Number) dealt.getOrDefault("combat", 0)).intValue()
                + ((Number) dealt.getOrDefault("other", 0)).intValue();
        return seatLabel(s.get("seat"), seatNames) + ":" + dmg + "dmg/"
                + s.get("drawn") + "dr/" + s.get("spells") + "sp";
    }
}
