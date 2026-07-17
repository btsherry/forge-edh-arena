package forge.arena.combo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The deck's win plan, as prep computed it (PR-16): the route-coverage/2
 * {@code deck} section parsed into pure data — expressible routes with their
 * support status and enabler cards, plus the payoff-class map (which card
 * serves which WIN-ROUTES §2b class). The LethalityPlanner evaluates THESE
 * routes against the live board; it never invents one (closed set, plan §1).
 * Missing artifact = empty plan = the planner banks and says why.
 */
public record RoutePlan(List<PlannedRoute> routes, Map<String, List<String>> payoffs) {

    public record PlannedRoute(String route, String origin, String support,
            List<String> enablers) {
        public boolean expressible() {
            return !"unsupported".equals(support);
        }
    }

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static RoutePlan empty() {
        return new RoutePlan(List.of(), Map.of());
    }

    /** Load from a dossier's route-coverage.json; missing file = empty plan. */
    public static RoutePlan load(Path routeCoverageJson) throws IOException {
        if (!Files.exists(routeCoverageJson)) {
            return empty();
        }
        JsonNode coverage = MAPPER.readTree(routeCoverageJson.toFile());
        JsonNode deck = coverage.path("deck");
        List<PlannedRoute> routes = new ArrayList<>();
        for (JsonNode r : deck.path("routes")) {
            List<String> enablers = new ArrayList<>();
            r.path("enablers").forEach(e -> enablers.add(e.asText()));
            routes.add(new PlannedRoute(r.path("route").asText(), r.path("origin").asText(),
                    r.path("support").asText(), enablers));
        }
        Map<String, List<String>> payoffs = new LinkedHashMap<>();
        for (Iterator<Map.Entry<String, JsonNode>> it = deck.path("payoffs").fields(); it.hasNext();) {
            Map.Entry<String, JsonNode> e = it.next();
            List<String> cards = new ArrayList<>();
            e.getValue().forEach(c -> cards.add(c.asText()));
            payoffs.put(e.getKey(), cards);
        }
        return new RoutePlan(routes, payoffs);
    }

    public Optional<PlannedRoute> route(String name) {
        return routes.stream().filter(r -> r.route().equals(name)).findFirst();
    }

    /** Cards of one payoff class (WIN-ROUTES §2b), empty when the class is absent. */
    public List<String> payoffCards(String payoffClass) {
        return payoffs.getOrDefault(payoffClass, List.of());
    }
}
