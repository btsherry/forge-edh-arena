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
            "tutor_decision", "mulligan_decision");

    private RunLogRenderer() {
    }

    public static Optional<String> render(ArenaEvent e, String workerId, int gameIndex, Tier tier) {
        if (tier != Tier.VERBOSE && !DEFAULT_TIER_TYPES.contains(e.t())) {
            return Optional.empty();
        }
        StringBuilder sb = new StringBuilder();
        sb.append('[').append('w').append(workerId).append(" g").append(String.format("%04d", gameIndex));
        if (e.turn() != null) {
            sb.append(" t").append(e.turn());
        }
        if (e.seat() != null) {
            sb.append(" s").append(e.seat());
        }
        sb.append("] ").append(detail(e));
        return Optional.of(sb.toString());
    }

    private static String detail(ArenaEvent e) {
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
                return "ABORT  line (" + f.get("cause") + (f.get("piece_lost") != null ? ", lost " + f.get("piece_lost") : "") + ")";
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
}
