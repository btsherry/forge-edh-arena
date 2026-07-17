package forge.arena.combo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

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
 * <p>PR-24 payoff visibility: the ranker additionally knows the deck's payoff
 * cards (route-coverage deck layer ∪ binding payoffs) and takes an
 * {@link Urgency} signal from the pilot. When conversion is pending (a
 * shortcut fired, pool floated), a payoff in the library IS the win — it
 * scores {@link #PAYOFF_CONVERSION}, strictly above the 1.0 maximum of
 * completion leverage, because casting Craterhoof now beats assembling a
 * second engine. When a bound line is imminent (distance ≤ 1), payoffs score
 * {@link #PAYOFF_IMMINENT} — below the finishing piece and the dossier's
 * piece-class statics (finish the hardware first), above every payoff-class
 * static (≤ 0.7 by the prep formula) — so the win condition arrives alongside
 * the last combo piece (the batch #5 finding: shortcuts fired with no payoff
 * in hand and SPREAD_COMBAT was rejected for it).
 *
 * <p>Score model (documented in every emitted why): completion leverage
 * {@code 1/distance} for pieces the tracker says are missing; static weight
 * otherwise; a card scores {@code max(leverage, payoff leverage, static)}.
 * Zero score = the ranker has no opinion and the stock heuristic decides
 * (§8 inertness: with empty artifacts the ordering is untouched — Urgency
 * NONE and an empty payoff set reproduce PR-17 behavior byte for byte).
 * Pure — SeatView + artifacts in, ranking out.
 */
public final class TutorRanker {

    /** How urgently the pilot needs win conversion, computed per search (PR-24). */
    public enum Urgency {
        /** No proven or imminent line — statics and completion leverage only. */
        NONE,
        /** A bound, fully-specified combo is at distance ≤ 1 (or ready). */
        IMMINENT,
        /** A shortcut fired or a line is deploying — the pool needs a payoff NOW. */
        CONVERSION
    }

    /** Conversion pending: above ANY completion leverage (max 1.0) — convert, don't re-assemble. */
    public static final double PAYOFF_CONVERSION = 1.2;

    /** Line imminent: below the finishing piece (1.0), above every payoff-class static. */
    public static final double PAYOFF_IMMINENT = 0.85;

    public record Ranked(String card, double score, String why) {
    }

    private final Map<String, Double> weights;
    private final ComboTracker tracker;
    private final Set<String> payoffCards;

    public TutorRanker(Map<String, Double> weights, ComboTracker tracker) {
        this(weights, tracker, Set.of());
    }

    public TutorRanker(Map<String, Double> weights, ComboTracker tracker,
            Set<String> payoffCards) {
        this.weights = Map.copyOf(weights);
        this.tracker = tracker;
        this.payoffCards = Set.copyOf(payoffCards);
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

    /** PR-17 form: no urgency signal — statics and completion leverage only. */
    public List<Ranked> rank(List<String> options, SeatView view) {
        return rank(options, view, Urgency.NONE);
    }

    /**
     * Rank the options, best first. Ties keep input order (stock's order is
     * the tie-break, so a no-opinion ranker is a no-op).
     */
    public List<Ranked> rank(List<String> options, SeatView view, Urgency urgency) {
        Map<String, Double> leverage = completionLeverage(view);
        double payoffLeverage = switch (urgency) {
            case CONVERSION -> PAYOFF_CONVERSION;
            case IMMINENT -> PAYOFF_IMMINENT;
            case NONE -> 0.0;
        };
        List<Ranked> ranked = new ArrayList<>();
        for (String card : options) {
            double live = leverage.getOrDefault(card, 0.0);
            double dossier = weights.getOrDefault(card, 0.0);
            double payoff = payoffCards.contains(card) ? payoffLeverage : 0.0;
            if (payoff > 0 && payoff >= live && payoff >= dossier) {
                ranked.add(new Ranked(card, payoff, urgency == Urgency.CONVERSION
                        ? "payoff converts the proven line"
                        : "payoff for the imminent line (distance<=1)"));
            } else if (live > 0 && live >= dossier) {
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
