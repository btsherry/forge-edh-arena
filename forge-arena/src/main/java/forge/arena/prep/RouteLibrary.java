package forge.arena.prep;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The global feature→route mapping library (plan §3 Gate 3, WIN-ROUTES §5) —
 * the curated overlay consulted AFTER {@link RouteRules} returns UNROUTABLE,
 * plus card→payoff-class overrides for {@link PayoffRules} regex misses.
 *
 * <p>Lives in-repo ({@code forge-arena/route-library/classifications.json}),
 * human-editable. Entries carry {@code status}: <b>proposed</b> (written by
 * {@link PrepAutopsy}, LLM output, inert) or <b>approved</b> (human-promoted
 * — the ONLY entries coverage consumes). That split is the review gate the
 * plan requires: LLM classifications are schema-validated and
 * human-reviewable, and can never silently change batch behavior.
 *
 * <p><b>Effective version</b> = content hash over approved entries for the
 * current rules version (or {@link #NO_LIBRARY} when there are none).
 * Dossiers pin it; DossierCheck refuses mismatches. Proposals therefore
 * invalidate nothing, while an approval automatically stales every dossier
 * prepped without it — no hand-maintained version field to forget.
 *
 * <p>Keying is (name, win-routes version): a rules bump orphans old entries
 * on purpose — reclassify under the new rules or re-approve.
 */
public final class RouteLibrary {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Effective version when no approved entries exist for the current rules. */
    public static final String NO_LIBRARY = "none";

    public record FeatureEntry(String feature, String category, List<String> routes,
            String status, String winRoutesVersion) {
    }

    public record PayoffEntry(String card, String payoffClass, String status,
            String winRoutesVersion) {
    }

    private final List<FeatureEntry> features;
    private final List<PayoffEntry> payoffs;
    private final Path file;

    private RouteLibrary(List<FeatureEntry> features, List<PayoffEntry> payoffs, Path file) {
        this.features = features;
        this.payoffs = payoffs;
        this.file = file;
    }

    /** Default in-repo location, resolved from either repo root or module dir. */
    public static Path defaultPath() {
        Path fromRoot = Path.of("forge-arena", "route-library", "classifications.json");
        return Files.exists(fromRoot) ? fromRoot
                : Path.of("route-library", "classifications.json");
    }

    /** Missing file = empty library. Malformed = loud failure, never a silent skip. */
    public static RouteLibrary load(Path file) throws IOException {
        if (!Files.exists(file)) {
            return new RouteLibrary(List.of(), List.of(), file);
        }
        JsonNode root = MAPPER.readTree(file.toFile());
        if (!root.has("features") || !root.has("payoffs")) {
            throw new IOException("route library malformed (want features/payoffs arrays): " + file);
        }
        List<FeatureEntry> features = new ArrayList<>();
        for (JsonNode e : root.get("features")) {
            List<String> routes = new ArrayList<>();
            e.path("routes").forEach(r -> routes.add(r.asText()));
            features.add(new FeatureEntry(req(e, "feature", file), req(e, "category", file),
                    routes, req(e, "status", file), req(e, "win_routes_version", file)));
        }
        List<PayoffEntry> payoffs = new ArrayList<>();
        for (JsonNode e : root.get("payoffs")) {
            payoffs.add(new PayoffEntry(req(e, "card", file), req(e, "payoff_class", file),
                    req(e, "status", file), req(e, "win_routes_version", file)));
        }
        return new RouteLibrary(features, payoffs, file);
    }

    private static String req(JsonNode e, String field, Path file) throws IOException {
        if (!e.hasNonNull(field)) {
            throw new IOException("route library entry missing '" + field + "': " + file);
        }
        return e.get(field).asText();
    }

    /**
     * Content hash over the approved entries that can affect coverage under
     * the CURRENT rules version — the value dossiers pin as
     * {@code versions.route_library}.
     */
    public String effectiveVersion() {
        // TreeMap canonicalizes ordering so hand-editing entry order never
        // changes the version — only approved content does
        TreeMap<String, String> canonical = new TreeMap<>();
        for (FeatureEntry e : features) {
            if (e.status().equals("approved") && e.winRoutesVersion().equals(RouteRules.VERSION)) {
                canonical.put("f:" + e.feature().toLowerCase(),
                        e.category() + "|" + String.join(",", e.routes()));
            }
        }
        for (PayoffEntry e : payoffs) {
            if (e.status().equals("approved") && e.winRoutesVersion().equals(RouteRules.VERSION)) {
                canonical.merge("p:" + e.card().toLowerCase(), e.payoffClass(),
                        (a, b) -> a + "," + b);
            }
        }
        if (canonical.isEmpty()) {
            return NO_LIBRARY;
        }
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(canonical.toString().getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (int i = 0; i < 6; i++) {
                hex.append(String.format("%02x", digest[i]));
            }
            return hex.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** APPROVED classification for an otherwise-unroutable feature, current rules only. */
    public Optional<RouteRules.Verdict> lookupFeature(String featureName) {
        for (FeatureEntry e : features) {
            if (e.status().equals("approved")
                    && e.winRoutesVersion().equals(RouteRules.VERSION)
                    && e.feature().equalsIgnoreCase(featureName)) {
                return Optional.of(new RouteRules.Verdict(e.category(), e.routes(), "library"));
            }
        }
        return Optional.empty();
    }

    /** APPROVED payoff overrides (card -> classes), current rules only. */
    public Map<String, List<String>> payoffOverrides() {
        Map<String, List<String>> out = new LinkedHashMap<>();
        for (PayoffEntry e : payoffs) {
            if (e.status().equals("approved") && e.winRoutesVersion().equals(RouteRules.VERSION)) {
                out.computeIfAbsent(e.card(), k -> new ArrayList<>()).add(e.payoffClass());
            }
        }
        return out;
    }

    /** True when ANY entry (proposed or approved) already covers this feature. */
    public boolean knowsFeature(String featureName) {
        return features.stream().anyMatch(e ->
                e.winRoutesVersion().equals(RouteRules.VERSION)
                        && e.feature().equalsIgnoreCase(featureName));
    }

    /** True when ANY entry (proposed or approved) already covers this card. */
    public boolean knowsPayoffCard(String card) {
        return payoffs.stream().anyMatch(e ->
                e.winRoutesVersion().equals(RouteRules.VERSION)
                        && e.card().equalsIgnoreCase(card));
    }

    /**
     * Append PROPOSED entries (autopsy output). Duplicates (same key + rules
     * version) are skipped; approved entries are never touched; the effective
     * version is unchanged by construction (proposals are inert).
     */
    public void appendProposals(List<FeatureEntry> newFeatures, List<PayoffEntry> newPayoffs)
            throws IOException {
        List<FeatureEntry> mergedFeatures = new ArrayList<>(features);
        for (FeatureEntry e : newFeatures) {
            if (!knowsFeature(e.feature())) {
                mergedFeatures.add(e);
            }
        }
        List<PayoffEntry> mergedPayoffs = new ArrayList<>(payoffs);
        for (PayoffEntry e : newPayoffs) {
            if (!knowsPayoffCard(e.card())) {
                mergedPayoffs.add(e);
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("schema", "arena.route-library/1");
        List<Map<String, Object>> featureRows = new ArrayList<>();
        for (FeatureEntry e : mergedFeatures) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("feature", e.feature());
            row.put("category", e.category());
            row.put("routes", e.routes());
            row.put("status", e.status());
            row.put("win_routes_version", e.winRoutesVersion());
            featureRows.add(row);
        }
        List<Map<String, Object>> payoffRows = new ArrayList<>();
        for (PayoffEntry e : mergedPayoffs) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("card", e.card());
            row.put("payoff_class", e.payoffClass());
            row.put("status", e.status());
            row.put("win_routes_version", e.winRoutesVersion());
            payoffRows.add(row);
        }
        out.put("features", featureRows);
        out.put("payoffs", payoffRows);
        if (file.getParent() != null) {
            Files.createDirectories(file.getParent());
        }
        MAPPER.writerWithDefaultPrettyPrinter().writeValue(file.toFile(), out);
    }
}
