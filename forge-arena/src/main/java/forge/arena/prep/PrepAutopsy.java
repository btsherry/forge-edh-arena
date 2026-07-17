package forge.arena.prep;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Prep autopsy (PR-13; plan §3 Gate 3 LLM fallback): when — and only when —
 * a dossier lands {@code blocked} or {@code unroutable_flagged}, ONE batched
 * Claude call proposes classifications for the unknowns: unroutable features
 * → (category, routes), and for blocked decks, cards the PayoffRules regexes
 * missed → payoff classes. Proposals are schema-validated (closed category /
 * route / class enums — the model structurally cannot invent a route),
 * recorded with provenance, and appended to the {@link RouteLibrary} as
 * {@code proposed}: INERT until a human flips them to {@code approved} and
 * re-runs prep. Clean decks never cost a call; known features never cost a
 * repeat call (cache-first, keyed by rules version).
 *
 * <p>Budget: at most 2 requests per problem deck (one call + one
 * schema-repair retry), ever — the same amortization argument as Gate 3.5.
 */
public final class PrepAutopsy {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public record Result(String status, int featureProposals, int payoffProposals,
            List<String> dropped, String detail) {
        public boolean ranOrCached() {
            return status.equals("proposed") || status.equals("cached") || status.equals("not_needed");
        }
    }

    private PrepAutopsy() {
    }

    public static Result run(Path dossierDir, RouteLibrary library, ClaudeClient client)
            throws IOException {
        JsonNode coverage = MAPPER.readTree(dossierDir.resolve("route-coverage.json").toFile());
        String status = coverage.get("status").asText();
        if (status.equals("clean")) {
            return new Result("not_needed", 0, 0, List.of(), "coverage clean");
        }

        // cache-first: only never-seen features go into the prompt
        List<String> unknownFeatures = new ArrayList<>();
        for (JsonNode f : coverage.get("unroutable_features")) {
            if (!library.knowsFeature(f.asText())) {
                unknownFeatures.add(f.asText());
            }
        }
        boolean blocked = "blocked".equals(status);
        boolean askPayoffs = blocked && !alreadyAutopsied(dossierDir, coverage);
        if (unknownFeatures.isEmpty() && !askPayoffs) {
            return new Result("cached", 0, 0, List.of(),
                    "every unknown already has a library entry (approve + re-run prep)");
        }

        JsonNode deckCards = MAPPER.readTree(dossierDir.resolve("deck-cards.json").toFile());
        String system = systemPrompt();
        String user = userPrompt(coverage, deckCards, unknownFeatures, askPayoffs);
        String requestSha = sha256(client.requestBody(system, user));

        // one call, one schema-repair retry — never more
        List<String> attempts = new ArrayList<>();
        JsonNode proposals = null;
        String problems = null;
        for (int attempt = 0; attempt < 2 && proposals == null; attempt++) {
            String prompt = problems == null ? user
                    : user + "\n\nYour previous response failed validation:\n" + problems
                            + "\nRespond again with ONLY the corrected JSON object.";
            String text = client.complete(system, prompt);
            attempts.add(text);
            JsonNode parsed = parseJson(text);
            problems = parsed == null ? "not parseable as a JSON object" : validate(parsed);
            if (problems == null) {
                proposals = parsed;
            }
        }
        writeRaw(dossierDir, client.model(), requestSha, attempts);
        if (proposals == null) {
            return new Result("failed", 0, 0, List.of(),
                    "response failed validation twice (see autopsy-raw.json): " + problems);
        }

        // semantic gates the schema can't express: features must be ones we
        // asked about; payoff cards must be in this deck
        Set<String> asked = new HashSet<>();
        unknownFeatures.forEach(f -> asked.add(f.toLowerCase()));
        Set<String> deckNames = new HashSet<>();
        deckCards.get("cards").forEach(c -> deckNames.add(c.get("name").asText().toLowerCase()));

        List<String> dropped = new ArrayList<>();
        List<RouteLibrary.FeatureEntry> featureEntries = new ArrayList<>();
        List<Map<String, Object>> featureRows = new ArrayList<>();
        for (JsonNode f : proposals.get("features")) {
            String name = f.get("feature").asText();
            if (!asked.contains(name.toLowerCase())) {
                dropped.add("feature not in the asked set: " + name);
                continue;
            }
            List<String> routes = new ArrayList<>();
            f.get("routes").forEach(r -> routes.add(r.asText()));
            featureEntries.add(new RouteLibrary.FeatureEntry(name, f.get("category").asText(),
                    routes, "proposed", RouteRules.VERSION));
            featureRows.add(row(f, "feature", "category", "routes", "rationale"));
        }
        List<RouteLibrary.PayoffEntry> payoffEntries = new ArrayList<>();
        List<Map<String, Object>> payoffRows = new ArrayList<>();
        for (JsonNode p : proposals.get("payoffs")) {
            String card = p.get("card").asText();
            if (!deckNames.contains(card.toLowerCase())) {
                dropped.add("payoff card not in this deck: " + card);
                continue;
            }
            payoffEntries.add(new RouteLibrary.PayoffEntry(card, p.get("payoff_class").asText(),
                    "proposed", RouteRules.VERSION));
            payoffRows.add(row(p, "card", "payoff_class", null, "rationale"));
        }

        Map<String, Object> artifact = new LinkedHashMap<>();
        artifact.put("schema", "arena.autopsy-proposals/1");
        artifact.put("deck_id", coverage.get("deck_id").asText());
        artifact.put("deck_hash", coverage.get("deck_hash").asText());
        artifact.put("win_routes_version", RouteRules.VERSION);
        artifact.put("model", client.model());
        artifact.put("request_sha256", requestSha);
        artifact.put("features", featureRows);
        artifact.put("payoffs", payoffRows);
        artifact.put("dropped", dropped);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("autopsy-proposals.json").toFile(), artifact);

        library.appendProposals(featureEntries, payoffEntries);
        return new Result("proposed", featureEntries.size(), payoffEntries.size(), dropped,
                featureEntries.size() + " feature + " + payoffEntries.size()
                        + " payoff proposals -> review the route library, approve, re-run prep");
    }

    /** A prior autopsy for this exact deck+rules already covered the payoff question. */
    private static boolean alreadyAutopsied(Path dossierDir, JsonNode coverage) throws IOException {
        Path prior = dossierDir.resolve("autopsy-proposals.json");
        if (!Files.exists(prior)) {
            return false;
        }
        JsonNode p = MAPPER.readTree(prior.toFile());
        return p.path("deck_hash").asText().equals(coverage.get("deck_hash").asText())
                && p.path("win_routes_version").asText().equals(RouteRules.VERSION);
    }

    private static String systemPrompt() {
        return "You classify Commander (EDH) combo result features and payoff cards for a"
                + " headless Magic: The Gathering simulator's win-route planner. You respond with"
                + " ONLY a JSON object — no prose, no markdown fences. The category, route, and"
                + " payoff-class vocabularies are CLOSED sets given in the request; never invent"
                + " a value outside them. If a feature is genuinely unclassifiable, return it with"
                + " category UNROUTABLE and say why in the rationale — honesty beats guessing."
                + " A feature is only LETHAL or WIN_TRIGGER if it reaches an engine-enforced end"
                + " state by itself; resources that need a payoff are RESOURCE.";
    }

    private static String userPrompt(JsonNode coverage, JsonNode deckCards,
            List<String> unknownFeatures, boolean askPayoffs) {
        StringBuilder sb = new StringBuilder();
        sb.append("CATEGORIES: ").append(String.join(", ", RouteRules.CATEGORIES)).append('\n');
        sb.append("ROUTES (closed set): ").append(String.join(", ", RouteRules.ROUTES)).append('\n');
        sb.append("PAYOFF CLASSES (closed set): ")
                .append(String.join(", ", PayoffRules.ASSIGNABLE_CLASSES)).append("\n\n");
        sb.append("Respond with a JSON object: {\"features\": [{\"feature\", \"category\","
                + " \"routes\", \"rationale\"}], \"payoffs\": [{\"card\", \"payoff_class\","
                + " \"rationale\"}]}. Both arrays are required (use [] when empty).\n\n");

        if (!unknownFeatures.isEmpty()) {
            sb.append("Classify these Commander Spellbook produces-features that our versioned"
                    + " rules could not match:\n");
            unknownFeatures.forEach(f -> sb.append("- ").append(f).append('\n'));
            sb.append('\n');
        }
        if (askPayoffs) {
            sb.append("This deck's route coverage is BLOCKED: its combos produce only resources"
                    + " and our oracle-text patterns found no payoff support in the 99. Guards:\n");
            for (JsonNode g : coverage.path("deck").path("guards")) {
                sb.append("- [").append(g.path("severity").asText()).append("] ")
                        .append(g.path("id").asText()).append(": ")
                        .append(g.path("detail").asText()).append('\n');
            }
            sb.append("Routes evaluated with their missing payoff classes:\n");
            for (JsonNode r : coverage.path("deck").path("routes")) {
                if (r.has("missing")) {
                    sb.append("- ").append(r.path("route").asText()).append(" missing: ");
                    List<String> missing = new ArrayList<>();
                    r.get("missing").forEach(m -> missing.add(m.asText()));
                    sb.append(String.join(", ", missing)).append('\n');
                }
            }
            sb.append("\nIdentify any cards in this deck that genuinely serve one of the missing"
                    + " payoff classes (only real matches — an empty payoffs array is a valid"
                    + " answer). Full deck list with oracle text:\n\n");
            for (JsonNode c : deckCards.get("cards")) {
                sb.append(c.get("name").asText()).append(" | ")
                        .append(c.path("type_line").asText("?")).append(" | ")
                        .append(c.path("oracle_text").asText("").replace("\\n", " ")
                                .replace('\n', ' '))
                        .append('\n');
            }
        } else {
            sb.append("Return an empty payoffs array — only feature classification is needed.\n");
        }
        return sb.toString();
    }

    /** Parse the model's text as JSON, tolerating accidental markdown fences. */
    private static JsonNode parseJson(String text) {
        String candidate = text.strip();
        if (candidate.startsWith("```")) {
            int start = candidate.indexOf('\n');
            int end = candidate.lastIndexOf("```");
            if (start >= 0 && end > start) {
                candidate = candidate.substring(start + 1, end).strip();
            }
        }
        try {
            JsonNode parsed = MAPPER.readTree(candidate);
            return parsed.isObject() ? parsed : null;
        } catch (IOException e) {
            return null;
        }
    }

    /** Structural + closed-enum validation; returns null when valid, else the problems. */
    private static String validate(JsonNode proposals) {
        List<String> problems = new ArrayList<>();
        JsonNode features = proposals.get("features");
        JsonNode payoffs = proposals.get("payoffs");
        if (features == null || !features.isArray() || payoffs == null || !payoffs.isArray()) {
            return "top-level 'features' and 'payoffs' arrays are required";
        }
        for (JsonNode f : features) {
            if (!f.hasNonNull("feature") || !f.hasNonNull("category") || !f.has("routes")
                    || !f.get("routes").isArray()) {
                problems.add("feature entry needs feature/category/routes[]: " + f);
                continue;
            }
            if (!RouteRules.CATEGORIES.contains(f.get("category").asText())) {
                problems.add("category outside the closed set: " + f.get("category").asText());
            }
            for (JsonNode r : f.get("routes")) {
                if (!RouteRules.ROUTES.contains(r.asText())) {
                    problems.add("route outside the closed set: " + r.asText());
                }
            }
        }
        for (JsonNode p : payoffs) {
            if (!p.hasNonNull("card") || !p.hasNonNull("payoff_class")) {
                problems.add("payoff entry needs card/payoff_class: " + p);
                continue;
            }
            if (!PayoffRules.ASSIGNABLE_CLASSES.contains(p.get("payoff_class").asText())) {
                problems.add("payoff_class outside the closed set: "
                        + p.get("payoff_class").asText());
            }
        }
        return problems.isEmpty() ? null : String.join("; ", problems);
    }

    private static Map<String, Object> row(JsonNode node, String key, String classKey,
            String routesKey, String rationaleKey) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put(key, node.get(key).asText());
        row.put(classKey, node.get(classKey).asText());
        if (routesKey != null) {
            List<String> routes = new ArrayList<>();
            node.get(routesKey).forEach(r -> routes.add(r.asText()));
            row.put(routesKey, routes);
        }
        row.put("rationale", node.path(rationaleKey).asText(""));
        return row;
    }

    private static void writeRaw(Path dossierDir, String model, String requestSha,
            List<String> attempts) throws IOException {
        Map<String, Object> raw = new LinkedHashMap<>();
        raw.put("model", model);
        raw.put("request_sha256", requestSha);
        raw.put("responses_verbatim", attempts);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("autopsy-raw.json").toFile(), raw);
    }

    private static String sha256(String body) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(body.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
