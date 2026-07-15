package forge.arena.prep;

import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Gate 3 orchestration: raw Spellbook snapshot → combos.json (included only)
 * + advisory-combos.json (almost-included: deckbuilding advice, never runtime
 * data) + route-coverage.json (v3.2, per-deck classification via RouteRules).
 * Updates the dossier index.
 */
public final class ComboPrep {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public record Result(int included, int almostIncluded, String coverageStatus,
            List<String> unroutableFeatures) {
    }

    private ComboPrep() {
    }

    public static Result run(Path dossierDir, SpellbookClient.Fetcher fetcher) throws IOException {
        ObjectNode index = (ObjectNode) MAPPER.readTree(dossierDir.resolve("dossier.json").toFile());
        JsonNode raw = SpellbookClient.fetchOrLoad(dossierDir, fetcher);
        JsonNode results = raw.get("results");
        String snapshotDate = LocalDate.now().toString();

        // --- combos.json: included only ---
        List<Map<String, Object>> combos = new ArrayList<>();
        for (JsonNode v : iter(results.get("included"))) {
            Map<String, Object> combo = new LinkedHashMap<>();
            String id = v.get("id").asText();
            combo.put("id", id);
            combo.put("url", "https://commanderspellbook.com/combo/" + id + "/");
            List<Map<String, Object>> cards = new ArrayList<>();
            for (JsonNode use : iter(v.get("uses"))) {
                Map<String, Object> card = new LinkedHashMap<>();
                card.put("name", use.get("card").get("name").asText());
                card.put("zone_req", zone(use.path("zoneLocations")));
                if (use.path("mustBeCommander").asBoolean(false)) {
                    card.put("must_be_commander", true);
                }
                cards.add(card);
            }
            combo.put("cards", cards);
            if (v.hasNonNull("manaNeeded") && !v.get("manaNeeded").asText().isEmpty()) {
                combo.put("mana_needed", v.get("manaNeeded").asText());
            }
            Map<String, Object> prereqs = new LinkedHashMap<>();
            if (v.hasNonNull("easyPrerequisites") && !v.get("easyPrerequisites").asText().isEmpty()) {
                prereqs.put("easy", v.get("easyPrerequisites").asText());
            }
            if (v.hasNonNull("notablePrerequisites") && !v.get("notablePrerequisites").asText().isEmpty()) {
                prereqs.put("notable", v.get("notablePrerequisites").asText());
            }
            if (!prereqs.isEmpty()) {
                combo.put("prerequisites", prereqs);
            }
            if (v.hasNonNull("description")) {
                combo.put("steps", v.get("description").asText());
            }
            combo.put("produces", featureNames(v));
            combos.add(combo);
        }

        Map<String, Object> combosJson = new LinkedHashMap<>();
        combosJson.put("schema", "arena.combos/1");
        combosJson.put("deck_id", index.get("deck_id").asText());
        combosJson.put("deck_hash", index.get("deck_hash").asText());
        combosJson.put("spellbook_snapshot", snapshotDate);
        combosJson.put("combos", combos);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("combos.json").toFile(), combosJson);

        // --- advisory-combos.json: almost-included (missing pieces = deckbuilding advice) ---
        List<Map<String, Object>> advisory = new ArrayList<>();
        for (JsonNode v : iter(results.get("almostIncluded"))) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", v.get("id").asText());
            List<String> cards = new ArrayList<>();
            iter(v.get("uses")).forEach(u -> cards.add(u.get("card").get("name").asText()));
            row.put("cards", cards);
            row.put("produces", featureNames(v));
            advisory.add(row);
        }
        Map<String, Object> advisoryJson = Map.of(
                "schema", "arena.advisory-combos/1",
                "note", "almost-included: at least one piece is NOT in the 99 — deckbuilding advice only, never runtime tutor/tracking data (plan §3 Gate 3 semantic rule)",
                "combos", advisory);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("advisory-combos.json").toFile(), advisoryJson);

        // --- route-coverage.json (v3.2) ---
        Set<String> unroutable = new LinkedHashSet<>();
        List<Map<String, Object>> coverageRows = new ArrayList<>();
        for (Map<String, Object> combo : combos) {
            List<Map<String, Object>> features = new ArrayList<>();
            boolean directWin = false;
            @SuppressWarnings("unchecked")
            List<String> produces = (List<String>) combo.get("produces");
            for (String feature : produces) {
                RouteRules.Verdict verdict = RouteRules.classify(feature);
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", feature);
                row.put("category", verdict.category());
                if (!verdict.routes().isEmpty()) {
                    row.put("routes", verdict.routes());
                }
                features.add(row);
                if (verdict.category().equals("LETHAL") || verdict.category().equals("WIN_TRIGGER")) {
                    directWin = true;
                }
                if (verdict.category().equals("UNROUTABLE")) {
                    unroutable.add(feature);
                }
            }
            Map<String, Object> cRow = new LinkedHashMap<>();
            cRow.put("id", combo.get("id"));
            cRow.put("features", features);
            cRow.put("direct_win", directWin);
            coverageRows.add(cRow);
        }
        String status = unroutable.isEmpty() ? "clean" : "unroutable_flagged";
        Map<String, Object> coverageJson = new LinkedHashMap<>();
        coverageJson.put("schema", "arena.route-coverage/1");
        coverageJson.put("deck_id", index.get("deck_id").asText());
        coverageJson.put("win_routes_version", RouteRules.VERSION);
        coverageJson.put("combos", coverageRows);
        coverageJson.put("unroutable_features", new ArrayList<>(unroutable));
        coverageJson.put("status", status);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("route-coverage.json").toFile(), coverageJson);

        // --- dossier index ---
        ((ObjectNode) index.get("status")).put("route_coverage", status);
        ((ObjectNode) index.get("versions")).put("spellbook_snapshot", snapshotDate);
        ((ObjectNode) index.get("versions")).put("win_routes", RouteRules.VERSION);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("dossier.json").toFile(), index);

        return new Result(combos.size(), advisory.size(), status, new ArrayList<>(unroutable));
    }

    private static List<String> featureNames(JsonNode variant) {
        List<String> names = new ArrayList<>();
        for (JsonNode p : iter(variant.get("produces"))) {
            JsonNode f = p.get("feature");
            names.add(f != null && f.has("name") ? f.get("name").asText() : p.path("name").asText());
        }
        return names;
    }

    private static String zone(JsonNode zoneLocations) {
        if (zoneLocations != null && zoneLocations.isArray() && zoneLocations.size() > 0) {
            switch (zoneLocations.get(0).asText()) {
                case "B": return "battlefield";
                case "H": return "hand";
                case "C": return "command";
                case "G": return "graveyard";
                case "L": return "library";
                case "E": return "exile";
                default: break;
            }
        }
        return "unknown";
    }

    private static Iterable<JsonNode> iter(JsonNode node) {
        return node == null || node.isNull() ? List.of() : node;
    }

    /** CLI: {@code ComboPrep <dossier-dir> [--offline]} — offline requires an existing snapshot. */
    public static void main(String[] args) throws Exception {
        boolean offline = args.length > 1 && args[1].equals("--offline");
        SpellbookClient.Fetcher fetcher = offline
                ? (url, body) -> { throw new IOException("offline mode and no cached snapshot"); }
                : SpellbookClient.httpFetcher();
        Result r = run(Path.of(args[0]), fetcher);
        System.out.println("combos: " + r.included() + " included, " + r.almostIncluded()
                + " advisory  route-coverage: " + r.coverageStatus());
        r.unroutableFeatures().forEach(f -> System.out.println("unroutable: " + f));
    }
}
