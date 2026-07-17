package forge.arena.combo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.engine.SeatView;

/**
 * TutorRanker v1 (plan §6, PR-17): ranks a search effect's choices by the
 * dossier's static tutor weights (tutor-priorities.json — combo pieces by
 * popularity/leverage, route payoffs by route share) PLUS live completion
 * leverage from the tracker: a missing piece of a distance-1 combo outranks
 * everything static (finishing a line now beats deckbuilding theory).
 *
 * <p>Score model (documented in every emitted why): completion leverage
 * {@code 1/distance} for pieces the tracker says are missing; static weight
 * otherwise; a card scores {@code max(leverage, static)}. Zero score = the
 * ranker has no opinion and the stock heuristic decides (§8 inertness: with
 * empty artifacts the ordering is untouched). Pure — SeatView + artifacts in,
 * ranking out.
 */
public final class TutorRanker {

    public record Ranked(String card, double score, String why) {
    }

    private final Map<String, Double> weights;
    private final ComboTracker tracker;

    public TutorRanker(Map<String, Double> weights, ComboTracker tracker) {
        this.weights = Map.copyOf(weights);
        this.tracker = tracker;
    }

    /** Load static weights from a dossier's tutor-priorities.json (missing = empty). */
    public static Map<String, Double> loadWeights(Path tutorPrioritiesJson) throws IOException {
        if (!Files.exists(tutorPrioritiesJson)) {
            return Map.of();
        }
        JsonNode root = new ObjectMapper().readTree(tutorPrioritiesJson.toFile());
        Map<String, Double> weights = new LinkedHashMap<>();
        for (Iterator<Map.Entry<String, JsonNode>> it = root.path("weights").fields(); it.hasNext();) {
            Map.Entry<String, JsonNode> e = it.next();
            weights.put(e.getKey(), e.getValue().asDouble());
        }
        return weights;
    }

    /**
     * Rank the options, best first. Ties keep input order (stock's order is
     * the tie-break, so a no-opinion ranker is a no-op).
     */
    public List<Ranked> rank(List<String> options, SeatView view) {
        Map<String, Double> leverage = completionLeverage(view);
        List<Ranked> ranked = new ArrayList<>();
        for (String card : options) {
            double live = leverage.getOrDefault(card, 0.0);
            double dossier = weights.getOrDefault(card, 0.0);
            if (live > 0 && live >= dossier) {
                ranked.add(new Ranked(card, live, "completes a combo (leverage 1/distance)"));
            } else if (dossier > 0) {
                ranked.add(new Ranked(card, dossier, "dossier tutor weight"));
            } else {
                ranked.add(new Ranked(card, 0.0, "stock_heuristic"));
            }
        }
        ranked.sort((a, b) -> Double.compare(b.score(), a.score()));
        return ranked;
    }

    /** Missing combo pieces -> 1/distance of their best combo. */
    private Map<String, Double> completionLeverage(SeatView view) {
        Map<String, Double> leverage = new LinkedHashMap<>();
        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (status.distance() == 0 || !status.fullySpecified()) {
                continue;
            }
            double value = 1.0 / status.distance();
            for (Map.Entry<String, String> piece : status.where().entrySet()) {
                SeatView.Presence presence = SeatView.Presence.valueOf(piece.getValue());
                if (!presence.reachable(false)) {
                    leverage.merge(piece.getKey(), value, Math::max);
                }
            }
        }
        return leverage;
    }
}
