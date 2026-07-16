package forge.arena.prep;

import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
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
 * data) + route-coverage.json (arena.route-coverage/2: the v3.2 per-feature
 * classification via RouteRules plus the v3.3 deck-level layer via
 * DeckCoverage — expressible routes, payoff support from the 99, guards,
 * blocking status). Updates the dossier index. Post-review (2026-07-16) the
 * extraction carries template requirements, per-card states/zone
 * alternatives, commander identity, popularity/bracketTag, and
 * provenance-true snapshot dates.
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
        SpellbookClient.Snapshot snapshot = SpellbookClient.fetchOrLoad(dossierDir, fetcher);
        JsonNode results = snapshot.raw().get("results");

        // commander identity comes from the deck, not from Spellbook's mustBeCommander
        Set<String> commanderNames = new HashSet<>();
        JsonNode deckCards = MAPPER.readTree(dossierDir.resolve("deck-cards.json").toFile());
        for (JsonNode c : deckCards.get("cards")) {
            if (c.get("zone").asText().equals("commander")) {
                commanderNames.add(c.get("name").asText());
            }
        }

        // --- combos.json: included only ---
        List<Map<String, Object>> combos = new ArrayList<>();
        for (JsonNode v : iter(results.get("included"))) {
            Map<String, Object> combo = new LinkedHashMap<>();
            String id = requireText(v, "id", "variant");
            combo.put("id", id);
            combo.put("url", "https://commanderspellbook.com/combo/" + id + "/");
            List<Map<String, Object>> cards = new ArrayList<>();
            for (JsonNode use : iter(v.get("uses"))) {
                JsonNode card = use.get("card");
                if (card == null || !card.hasNonNull("name")) {
                    throw new IOException("spellbook variant " + id
                            + " uses[] entry lacks card.name (schema drift — W5)");
                }
                Map<String, Object> row = new LinkedHashMap<>();
                String name = card.get("name").asText();
                row.put("name", name);
                List<String> zones = zones(use.path("zoneLocations"));
                row.put("zone_req", zones.isEmpty() ? "unknown" : zones.get(0));
                if (zones.size() > 1) {
                    row.put("zones", zones);
                }
                String state = firstNonEmpty(use, "battlefieldCardState", "exileCardState",
                        "graveyardCardState", "libraryCardState");
                if (state != null) {
                    row.put("state", state);
                }
                if (commanderNames.contains(name)) {
                    row.put("commander", true);
                }
                if (use.path("mustBeCommander").asBoolean(false)) {
                    row.put("must_be_commander", true);
                }
                cards.add(row);
            }
            combo.put("cards", cards);

            // generic template pieces (e.g. "Permanent that can be cast using {C}")
            List<Map<String, Object>> templates = new ArrayList<>();
            for (JsonNode req : iter(v.get("requires"))) {
                Map<String, Object> t = new LinkedHashMap<>();
                JsonNode template = req.path("template");
                t.put("name", template.path("name").asText("unknown requirement"));
                if (template.hasNonNull("scryfallQuery")) {
                    t.put("scryfall_query", template.get("scryfallQuery").asText());
                }
                List<String> tz = zones(req.path("zoneLocations"));
                t.put("zone_req", tz.isEmpty() ? "unknown" : tz.get(0));
                if (tz.size() > 1) {
                    t.put("zones", tz);
                }
                t.put("quantity", req.path("quantity").asInt(1));
                templates.add(t);
            }
            if (!templates.isEmpty()) {
                combo.put("template_requirements", templates);
            }

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
            if (v.hasNonNull("popularity")) {
                combo.put("popularity", v.get("popularity").asInt());
            }
            if (v.hasNonNull("bracketTag") && !v.get("bracketTag").asText().isEmpty()) {
                combo.put("bracket_tag", v.get("bracketTag").asText());
            }
            combo.put("produces", featureList(v).stream().map(f -> f.name).toList());
            combos.add(combo);
        }

        Map<String, Object> combosJson = new LinkedHashMap<>();
        combosJson.put("schema", "arena.combos/1");
        combosJson.put("deck_id", index.get("deck_id").asText());
        combosJson.put("deck_hash", index.get("deck_hash").asText());
        combosJson.put("spellbook_snapshot", snapshot.fetchedDate());
        combosJson.put("combos", combos);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("combos.json").toFile(), combosJson);

        // --- advisory-combos.json: almost-included (missing pieces = deckbuilding advice) ---
        List<Map<String, Object>> advisory = new ArrayList<>();
        for (JsonNode v : iter(results.get("almostIncluded"))) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", v.path("id").asText("?"));
            List<String> cards = new ArrayList<>();
            iter(v.get("uses")).forEach(u -> cards.add(u.path("card").path("name").asText("?")));
            row.put("cards", cards);
            row.put("produces", featureList(v).stream().map(f -> f.name).toList());
            advisory.add(row);
        }
        Map<String, Object> advisoryJson = Map.of(
                "schema", "arena.advisory-combos/1",
                "note", "almost-included: at least one piece is NOT in the 99 — deckbuilding advice only, never runtime tutor/tracking data (plan §3 Gate 3 semantic rule)",
                "combos", advisory);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("advisory-combos.json").toFile(), advisoryJson);

        // --- route-coverage.json (v3.2 per-feature layer + v3.3 deck layer) ---
        Set<String> unroutable = new LinkedHashSet<>();
        List<Map<String, Object>> coverageRows = new ArrayList<>();
        List<DeckCoverage.ComboFeatures> comboFeatures = new ArrayList<>();
        for (JsonNode v : iter(results.get("included"))) {
            List<Map<String, Object>> features = new ArrayList<>();
            List<DeckCoverage.Classified> classified = new ArrayList<>();
            boolean directWin = false;
            for (Feature feature : featureList(v)) {
                RouteRules.Verdict verdict = RouteRules.classify(feature.name, feature.status);
                classified.add(new DeckCoverage.Classified(feature.name, verdict));
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", feature.name);
                row.put("category", verdict.category());
                if (!verdict.routes().isEmpty()) {
                    row.put("routes", verdict.routes());
                }
                features.add(row);
                if (verdict.category().equals("LETHAL") || verdict.category().equals("WIN_TRIGGER")) {
                    directWin = true;
                }
                if (verdict.category().equals("UNROUTABLE")) {
                    unroutable.add(feature.name);
                }
            }
            Map<String, Object> cRow = new LinkedHashMap<>();
            String comboId = requireText(v, "id", "variant");
            cRow.put("id", comboId);
            cRow.put("features", features);
            cRow.put("direct_win", directWin);
            coverageRows.add(cRow);
            comboFeatures.add(new DeckCoverage.ComboFeatures(comboId, classified));
        }
        Map<String, Object> deck = DeckCoverage.analyze(comboFeatures,
                DeckCoverage.payoffs(deckCards), new ArrayList<>(unroutable));
        // single source of truth: the deck-level verdict IS the artifact status
        String status = (String) deck.remove("status");
        Map<String, Object> coverageJson = new LinkedHashMap<>();
        coverageJson.put("schema", "arena.route-coverage/2");
        coverageJson.put("deck_id", index.get("deck_id").asText());
        coverageJson.put("deck_hash", index.get("deck_hash").asText());
        coverageJson.put("win_routes_version", RouteRules.VERSION);
        coverageJson.put("combos", coverageRows);
        coverageJson.put("deck", deck);
        coverageJson.put("unroutable_features", new ArrayList<>(unroutable));
        coverageJson.put("status", status);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("route-coverage.json").toFile(), coverageJson);

        // --- dossier index ---
        ((ObjectNode) index.get("status")).put("route_coverage", status);
        ((ObjectNode) index.get("versions")).put("spellbook_snapshot", snapshot.fetchedDate());
        ((ObjectNode) index.get("versions")).put("win_routes", RouteRules.VERSION);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("dossier.json").toFile(), index);

        return new Result(combos.size(), advisory.size(), status, new ArrayList<>(unroutable));
    }

    private record Feature(String name, String status) {
    }

    private static List<Feature> featureList(JsonNode variant) {
        List<Feature> features = new ArrayList<>();
        for (JsonNode p : iter(variant.get("produces"))) {
            JsonNode f = p.get("feature");
            if (f != null && f.hasNonNull("name")) {
                features.add(new Feature(f.get("name").asText(), f.path("status").asText("")));
            } else if (p.hasNonNull("name")) {
                features.add(new Feature(p.get("name").asText(), ""));
            }
        }
        return features;
    }

    private static String requireText(JsonNode node, String field, String what) throws IOException {
        if (!node.hasNonNull(field)) {
            throw new IOException("spellbook " + what + " lacks '" + field + "' (schema drift — W5)");
        }
        return node.get(field).asText();
    }

    private static String firstNonEmpty(JsonNode node, String... fields) {
        for (String f : fields) {
            String v = node.path(f).asText("");
            if (!v.isEmpty()) {
                return v;
            }
        }
        return null;
    }

    private static List<String> zones(JsonNode zoneLocations) {
        List<String> out = new ArrayList<>();
        if (zoneLocations != null && zoneLocations.isArray()) {
            for (JsonNode z : zoneLocations) {
                switch (z.asText()) {
                    case "B": out.add("battlefield"); break;
                    case "H": out.add("hand"); break;
                    case "C": out.add("command"); break;
                    case "G": out.add("graveyard"); break;
                    case "L": out.add("library"); break;
                    case "E": out.add("exile"); break;
                    default: out.add("unknown"); break;
                }
            }
        }
        return out;
    }

    private static Iterable<JsonNode> iter(JsonNode node) {
        return node == null || node.isNull() ? List.of() : node;
    }

    /** CLI: {@code ComboPrep <dossier-dir> [--offline]} — offline requires an existing snapshot. */
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("usage: ComboPrep <dossier-dir> [--offline]");
            System.exit(2);
        }
        boolean offline = false;
        for (int i = 1; i < args.length; i++) {
            if (args[i].equals("--offline")) {
                offline = true;
            } else {
                System.err.println("unknown option: " + args[i]);
                System.exit(2);
            }
        }
        SpellbookClient.Fetcher fetcher = offline
                ? (url, body) -> { throw new IOException("offline mode and no usable cached snapshot"); }
                : SpellbookClient.httpFetcher();
        Result r = run(Path.of(args[0]), fetcher);
        System.out.println("combos: " + r.included() + " included, " + r.almostIncluded()
                + " advisory  route-coverage: " + r.coverageStatus());
        r.unroutableFeatures().forEach(f -> System.out.println("unroutable: " + f));
    }
}
