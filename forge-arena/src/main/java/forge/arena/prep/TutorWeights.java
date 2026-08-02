package forge.arena.prep;

import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * tutor-priorities.json (plan §5, v3.3): static tutor weights derived from
 * the combo list AND the win plan. The v3.3 rule this exists for: payoff and
 * enabler cards that appear in ~zero Spellbook combos (Concordant Crossroads,
 * Craterhoof Behemoth in the Selvala deck) get real weights from the
 * route-coverage deck layer, because the routes — not the combos — are what
 * win the game.
 *
 * <p>Static proxies for the plan's quality × scarcity × completion_leverage
 * (live completion leverage is a Phase-5 TutorRanker concern):
 * <ul>
 *   <li><b>quality</b> — log-normalized Spellbook popularity of the combo;
 *   <li><b>leverage</b> — fewer named pieces = each piece worth more
 *       (min(1, 2/pieces));
 *   <li><b>commander discount</b> — command-zone cards are always available,
 *       tutoring them is nearly worthless (×0.2);
 *   <li><b>payoff share</b> — enablers of expressible routes weighted by how
 *       many routes they serve (plan §5: "scaled by how many of the deck's
 *       routes require them").
 * </ul>
 * Combo pieces land in [0.5, 0.95], payoffs in [0.35, 0.7]; a card takes the
 * max of its contributions. Deterministic output: weights sorted descending,
 * ties by name.
 */
public final class TutorWeights {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Ceiling for a discovered-synergy HUB boost — deliberately below the
     * combo-piece band (0.85+) so folding the whole-deck synergy graph into
     * tutoring can order the synergy enablers among themselves but NEVER
     * out-rank assembling a real combo. */
    private static final double HUB_CAP = 0.5;

    public static final String DERIVATION =
            "combo pieces: (0.5 + 0.45*logNorm(popularity)) * min(1, 2/pieces), commanders x0.2; "
            + "route payoffs: 0.35 + 0.35*(routes served / expressible routes); "
            + "engine-program pieces: flat 0.9 (PR-kappa: compiled card-advantage "
            + "engines are prime tutor targets); "
            + "discovered-synergy hubs: HUB_CAP*logNorm(weighted synergy appearances), "
            + "capped 0.5 below the combo band (folds the whole-deck research graph "
            + "into tutoring without out-ranking combo assembly); "
            + "card weight = max over contributions (win-routes/4 static proxies for "
            + "quality * scarcity * completion_leverage)";

    public record Result(int weightedCards, Path file) {
    }

    private record Contribution(double weight, String why) {
    }

    private TutorWeights() {
    }

    public static Result run(Path dossierDir) throws IOException {
        JsonNode combos = MAPPER.readTree(dossierDir.resolve("combos.json").toFile());
        JsonNode coverage = MAPPER.readTree(dossierDir.resolve("route-coverage.json").toFile());
        JsonNode deckCards = MAPPER.readTree(dossierDir.resolve("deck-cards.json").toFile());

        Set<String> commanders = new HashSet<>();
        for (JsonNode c : deckCards.get("cards")) {
            if (c.get("zone").asText().equals("commander")) {
                commanders.add(c.get("name").asText());
            }
        }

        Map<String, Contribution> best = new HashMap<>();

        // --- combo-piece contributions ---
        long maxPopularity = 0;
        for (JsonNode combo : combos.get("combos")) {
            maxPopularity = Math.max(maxPopularity, combo.path("popularity").asLong(0));
        }
        for (JsonNode combo : combos.get("combos")) {
            long popularity = combo.path("popularity").asLong(0);
            double quality = maxPopularity > 0 && popularity > 0
                    ? Math.log1p(popularity) / Math.log1p(maxPopularity)
                    : 0.0;
            int pieces = combo.get("cards").size();
            double leverage = Math.min(1.0, 2.0 / Math.max(1, pieces));
            double weight = (0.5 + 0.45 * quality) * leverage;
            String why = "combo " + combo.get("id").asText()
                    + " (popularity " + popularity + ", " + pieces + " pieces)";
            for (JsonNode card : combo.get("cards")) {
                offer(best, card.get("name").asText(), weight, why);
            }
        }

        // --- discovered-combo pieces (cast_recur/PR): Ben's domain-knowledge
        // lines Spellbook omits (Birgi + Grinning Ignus) still deserve tutor
        // weight so the deck's tutors (Gamble, Reckless Handling) fetch them.
        // Flat 0.85 — real combo pieces, no Spellbook popularity to scale by.
        Path discovered = dossierDir.resolve("discovered-combos.json");
        if (java.nio.file.Files.exists(discovered)) {
            JsonNode disc = MAPPER.readTree(discovered.toFile());
            for (JsonNode combo : disc.path("combos")) {
                String why = "discovered combo " + combo.path("id").asText();
                for (JsonNode card : combo.path("cards")) {
                    offer(best, card.get("name").asText(), 0.85, why);
                }
            }
        }

        // --- discovered-synergy HUBS (whole-deck research): fold the ~200
        // discovered synergies into tutoring. A card in many high-value
        // synergies is a hub the pilot should fetch when NOT assembling a
        // specific combo; the boost is CAPPED (HUB_CAP) below the combo band,
        // so it only orders the synergy enablers (ramp, value engines) among
        // themselves. Weighted by confidence (high 1.0, else 0.6) and
        // log-normalised. Guarded on the artifact's presence, so decks without
        // a whole-deck catalog (and the unit fixture) are untouched. ---
        Path synergies = dossierDir.resolve("discovered-synergies-wholedeck.json");
        if (java.nio.file.Files.exists(synergies)) {
            JsonNode cat = MAPPER.readTree(synergies.toFile()).path("fable_catalog");
            Map<String, Double> hubScore = new LinkedHashMap<>();
            for (JsonNode rec : cat) {
                double conf = "high".equals(rec.path("confidence").asText()) ? 1.0 : 0.6;
                Set<String> cards = new java.util.LinkedHashSet<>();
                cards.add(rec.path("anchor").asText());
                for (JsonNode pc : rec.path("partner_cards")) {
                    cards.add(pc.asText());
                }
                for (String card : cards) {
                    hubScore.merge(card, conf, Double::sum);
                }
            }
            double maxScore = hubScore.values().stream()
                    .mapToDouble(Double::doubleValue).max().orElse(1.0);
            for (Map.Entry<String, Double> e : hubScore.entrySet()) {
                double boost = maxScore > 0
                        ? HUB_CAP * Math.log1p(e.getValue()) / Math.log1p(maxScore) : 0.0;
                offer(best, e.getKey(), boost, "discovered-synergy hub: "
                        + Math.round(e.getValue()) + " weighted synergies");
            }
        }

        // --- route-payoff contributions (the v3.3 Crossroads/Craterhoof rule) ---
        JsonNode routes = coverage.path("deck").path("routes");
        Map<String, List<String>> routesServed = new LinkedHashMap<>();
        int expressibleRoutes = 0;
        for (JsonNode route : routes) {
            if (route.get("support").asText().equals("unsupported")) {
                continue;
            }
            expressibleRoutes++;
            for (JsonNode enabler : iterable(route.get("enablers"))) {
                routesServed.computeIfAbsent(enabler.asText(), k -> new ArrayList<>())
                        .add(route.get("route").asText());
            }
        }
        for (Map.Entry<String, List<String>> e : routesServed.entrySet()) {
            double share = expressibleRoutes > 0
                    ? (double) e.getValue().size() / expressibleRoutes
                    : 0.0;
            offer(best, e.getKey(), 0.35 + 0.35 * share,
                    "route payoff: " + String.join(", ", e.getValue()));
        }

        // --- engine-program pieces (PR-kappa): a compiled card-advantage
        // engine's pieces are prime tutor targets — Land Tax and Scroll Rack
        // are exactly what Enlightened Tutor should fetch, and neither is a
        // combo piece nor a route payoff, so nothing above sees them ---
        try (java.util.stream.Stream<Path> files = java.nio.file.Files.list(dossierDir)) {
            for (Path f : files.sorted().filter(x -> x.getFileName().toString()
                            .startsWith("engine-program-")
                            && x.getFileName().toString().endsWith(".json")).toList()) {
                JsonNode program = MAPPER.readTree(f.toFile());
                for (JsonNode piece : program.path("pieces")) {
                    String card = piece.path("card").asText();
                    if (!card.isEmpty()) {
                        offer(best, card, 0.9,
                                "engine program piece: " + program.path("engine_id").asText("?"));
                    }
                }
            }
        }

        // --- assemble: commander discount, rounding, deterministic order ---
        List<Map.Entry<String, Contribution>> rows = new ArrayList<>();
        for (Map.Entry<String, Contribution> e : best.entrySet()) {
            Contribution c = e.getValue();
            if (commanders.contains(e.getKey())) {
                c = new Contribution(c.weight() * 0.2,
                        c.why() + " (commander: command zone always available, x0.2)");
            }
            rows.add(Map.entry(e.getKey(), c));
        }
        rows.sort((a, b) -> {
            int r = Double.compare(b.getValue().weight(), a.getValue().weight());
            return r != 0 ? r : a.getKey().compareTo(b.getKey());
        });

        Map<String, Object> weights = new LinkedHashMap<>();
        Map<String, Object> explanations = new LinkedHashMap<>();
        for (Map.Entry<String, Contribution> e : rows) {
            double rounded = Math.round(Math.min(1.0, e.getValue().weight()) * 1000.0) / 1000.0;
            if (rounded <= 0.0) {
                continue;
            }
            weights.put(e.getKey(), rounded);
            explanations.put(e.getKey(), e.getValue().why());
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("schema", "arena.tutor-priorities/1");
        out.put("deck_id", combos.get("deck_id").asText());
        out.put("deck_hash", combos.get("deck_hash").asText());
        out.put("win_routes_version", RouteRules.VERSION);
        out.put("derivation", DERIVATION);
        out.put("weights", weights);
        out.put("explanations", explanations);
        Path file = dossierDir.resolve("tutor-priorities.json");
        MAPPER.writerWithDefaultPrettyPrinter().writeValue(file.toFile(), out);
        return new Result(weights.size(), file);
    }

    private static void offer(Map<String, Contribution> best, String card, double weight, String why) {
        Contribution current = best.get(card);
        if (current == null || weight > current.weight()) {
            best.put(card, new Contribution(weight, why));
        }
    }

    private static Iterable<JsonNode> iterable(JsonNode node) {
        return node == null || node.isNull() || node.isMissingNode() ? List.of() : node;
    }
}
