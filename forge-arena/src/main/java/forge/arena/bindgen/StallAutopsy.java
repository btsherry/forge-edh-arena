package forge.arena.bindgen;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import forge.arena.combo.SimResult;
import forge.arena.prep.ClaudeClient;
import forge.arena.prep.PayoffRules;
import forge.arena.prep.RouteLibrary;
import forge.arena.prep.RouteRules;

/**
 * Gate 3.6 — the stall autopsy repair pass (plan §3): the batch loop stays
 * LLM-free, but its failures feed the next prep cycle. Post-run, this scans
 * a batch for {@code combo_stalled} events, dedupes by state hash against a
 * GLOBAL ledger (one call per distinct failure mode — EVER), and sends each
 * new stall's evidence — the state dump, the fired binding, the planner's
 * route trace, the deck's oracle text — in ONE Claude call. Responses are
 * typed and gated exactly like Gate 3.5:
 *
 * <ul>
 *   <li>{@code binding_repair} — lint (the archetype constructor) + sandbox
 *       sim verification; only a PROVEN repair replaces the library binding
 *       (with stall-autopsy provenance);
 *   <li>{@code payoff_addition} — a card→payoff-class discovery, appended to
 *       the route library as a PROPOSAL (inert until human-approved — the
 *       PR-13 review gate);
 *   <li>{@code no_repair} — an honest diagnosis, recorded in the ledger.
 * </ul>
 *
 * The next batch converts repaired states deterministically; nothing here
 * runs during games.
 */
public final class StallAutopsy {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public record Result(int distinctStalls, int repairedBindings, int payoffProposals,
            int noRepair, int cachedSkips, int failures, List<String> notes) {
    }

    private StallAutopsy() {
    }

    /** Global ledger next to the binding library: processed state hashes never re-bill. */
    public static Path defaultLedger(Path bindingsFile) {
        return bindingsFile.resolveSibling("stall-autopsy-ledger.jsonl");
    }

    public static Result run(Path batchDir, Path bindingsFile, Path routeLibraryFile,
            ClaudeClient client, BindGen.Verifier verifier) throws IOException {
        Set<String> processed = loadLedger(defaultLedger(bindingsFile));
        JsonNode workerCfg = MAPPER.readTree(batchDir.resolve("worker-config.json").toFile());

        int repaired = 0;
        int proposals = 0;
        int noRepair = 0;
        int cached = 0;
        int failures = 0;
        Set<String> seenThisRun = new HashSet<>();
        List<String> notes = new ArrayList<>();

        try (var files = Files.list(batchDir.resolve("events"))) {
            for (Path eventFile : files.sorted().toList()) {
                List<JsonNode> events = new ArrayList<>();
                for (String line : Files.readAllLines(eventFile)) {
                    if (!line.isBlank()) {
                        events.add(MAPPER.readTree(line));
                    }
                }
                for (JsonNode event : events) {
                    if (!event.path("t").asText().equals("combo_stalled")) {
                        continue;
                    }
                    String stateHash = event.path("state_hash").asText();
                    if (processed.contains(stateHash) || !seenThisRun.add(stateHash)) {
                        cached++;
                        continue;
                    }
                    String outcome = autopsyOne(event, events, workerCfg, bindingsFile,
                            routeLibraryFile, client, verifier, notes);
                    switch (outcome) {
                        case "repaired" -> repaired++;
                        case "proposal" -> proposals++;
                        case "no_repair" -> noRepair++;
                        default -> failures++;
                    }
                    appendLedger(defaultLedger(bindingsFile), stateHash,
                            event.path("binding").asText(), outcome);
                }
            }
        }
        return new Result(seenThisRun.size(), repaired, proposals, noRepair, cached,
                failures, notes);
    }

    private static String autopsyOne(JsonNode stalled, List<JsonNode> gameEvents,
            JsonNode workerCfg, Path bindingsFile, Path routeLibraryFile, ClaudeClient client,
            BindGen.Verifier verifier, List<String> notes) throws IOException {
        String comboId = stalled.path("binding").asText();
        String stateHash = stalled.path("state_hash").asText();
        Path dumpPath = Path.of(stalled.path("dump_path").asText());
        if (!Files.exists(dumpPath)) {
            notes.add(stateHash + ": dump file missing — cannot autopsy");
            return "failed";
        }
        int seat = stalled.path("seat").asInt();
        JsonNode library = MAPPER.readTree(bindingsFile.toFile());
        JsonNode binding = findBinding(library, comboId);
        if (binding == null) {
            notes.add(stateHash + ": binding '" + comboId + "' not in library");
            return "failed";
        }
        String deckCardsBlock = deckCardsBlock(workerCfg, gameEvents, seat);

        String system = systemPrompt();
        String user = userPrompt(Files.readString(dumpPath), binding, gameEvents, seat,
                deckCardsBlock);
        String failure = null;
        for (int attempt = 0; attempt < 2; attempt++) {
            String prompt = failure == null ? user
                    : user + "\n\nYour previous response failed: " + failure
                            + "\nRespond again with ONLY the corrected JSON object.";
            JsonNode parsed = parseJson(client.complete(system, prompt));
            if (parsed == null) {
                failure = "not parseable as a JSON object";
                continue;
            }
            switch (parsed.path("kind").asText()) {
                case "binding_repair" -> {
                    ObjectNode candidate = BindGen.lint(parsed.path("binding"), comboId);
                    if (candidate == null) {
                        failure = "repair failed lint (unknown archetype / incomplete params)";
                        continue;
                    }
                    SimResult verdict = verifier.verify(BindGen.toBinding(candidate));
                    if (!verdict.isProfitable()) {
                        failure = "repair failed sim verification: " + verdict.status()
                                + (verdict.blockedBy() != null ? " " + verdict.blockedBy() : "");
                        continue;
                    }
                    ObjectNode provenance = candidate.putObject("provenance");
                    provenance.put("generated_by", "stall-autopsy/1");
                    provenance.put("model", client.model());
                    provenance.put("request_sha256", sha256(client.requestBody(system, user)));
                    provenance.put("sim_cycles", verdict.cycles());
                    replaceBinding(bindingsFile, comboId, candidate);
                    notes.add(stateHash + ": binding '" + comboId + "' REPAIRED + sim-verified");
                    return "repaired";
                }
                case "payoff_addition" -> {
                    String card = parsed.path("card").asText();
                    String payoffClass = parsed.path("payoff_class").asText();
                    if (!PayoffRules.ASSIGNABLE_CLASSES.contains(payoffClass)
                            || !deckCardsBlock.contains(card)) {
                        failure = "payoff_addition outside closed class set or card not in deck";
                        continue;
                    }
                    RouteLibrary.load(routeLibraryFile).appendProposals(List.of(),
                            List.of(new RouteLibrary.PayoffEntry(card, payoffClass,
                                    "proposed", RouteRules.VERSION)));
                    notes.add(stateHash + ": payoff proposal " + card + " -> " + payoffClass
                            + " (inert until approved)");
                    return "proposal";
                }
                case "no_repair" -> {
                    notes.add(stateHash + ": no repair — "
                            + parsed.path("diagnosis").asText("(no diagnosis)"));
                    return "no_repair";
                }
                default -> failure = "kind must be binding_repair | payoff_addition | no_repair";
            }
        }
        notes.add(stateHash + ": autopsy failed twice — " + failure);
        return "failed";
    }

    private static String systemPrompt() {
        return "You repair combo-execution failures for a Magic: The Gathering simulator. A"
                + " seat PROVED an infinite loop, injected its mana, and the game still did not"
                + " end. Respond with ONLY a JSON object, one of: {\"kind\": \"binding_repair\","
                + " \"binding\": {archetype, params, payoffs, entry_phase}} to fix the fired"
                + " binding (it will be SIM-VERIFIED; wrong repairs are discarded); {\"kind\":"
                + " \"payoff_addition\", \"card\", \"payoff_class\", \"rationale\"} when a card"
                + " in the deck serves a payoff class the rules missed (closed class set given);"
                + " or {\"kind\": \"no_repair\", \"diagnosis\": \"...\"} when the stall is not a"
                + " data problem (e.g. the route is inherently slow). Never invent card names.";
    }

    private static String userPrompt(String dump, JsonNode binding, List<JsonNode> gameEvents,
            int seat, String deckCardsBlock) {
        StringBuilder sb = new StringBuilder();
        sb.append("PAYOFF CLASSES (closed set): ")
                .append(String.join(", ", PayoffRules.ASSIGNABLE_CLASSES)).append('\n');
        sb.append("ROUTES (closed set): ").append(String.join(", ", RouteRules.ROUTES))
                .append("\n\nGAME STATE AT STALL:\n").append(dump);
        sb.append("\nFIRED BINDING:\n").append(binding.toString()).append('\n');
        sb.append("\nPLANNER TRACE (this seat's route/combo decisions):\n");
        for (JsonNode event : gameEvents) {
            String t = event.path("t").asText();
            if (event.path("seat").asInt(-1) == seat
                    && (t.startsWith("route_") || t.startsWith("combo_") || t.startsWith("line_"))) {
                sb.append(event.toString()).append('\n');
            }
        }
        sb.append("\nDECK (name | oracle text):\n").append(deckCardsBlock);
        return sb.toString();
    }

    /** The stalled seat's deck list with oracle text, from its dossier's deck-cards.json. */
    private static String deckCardsBlock(JsonNode workerCfg, List<JsonNode> gameEvents, int seat)
            throws IOException {
        String deckName = gameEvents.get(0).path("seats").path(seat).asText();
        for (JsonNode ws : workerCfg.path("seats")) {
            String file = ws.path("deck_file").asText();
            if (file.endsWith(deckName + ".dck") && ws.hasNonNull("dossier")) {
                JsonNode deckCards = MAPPER.readTree(
                        Path.of(ws.get("dossier").asText()).resolve("deck-cards.json").toFile());
                StringBuilder sb = new StringBuilder();
                for (JsonNode card : deckCards.get("cards")) {
                    sb.append(card.get("name").asText()).append(" | ")
                            .append(card.path("oracle_text").asText("").replace("\\n", " "))
                            .append('\n');
                }
                return sb.toString();
            }
        }
        return "(dossier not available for " + deckName + ")";
    }

    private static JsonNode findBinding(JsonNode library, String comboId) {
        for (JsonNode b : library.path("bindings")) {
            if (b.path("combo_id").asText().equals(comboId)) {
                return b;
            }
        }
        return null;
    }

    private static void replaceBinding(Path bindingsFile, String comboId, ObjectNode replacement)
            throws IOException {
        ObjectNode library = (ObjectNode) MAPPER.readTree(bindingsFile.toFile());
        ArrayNode bindings = (ArrayNode) library.withArray("bindings");
        for (int i = 0; i < bindings.size(); i++) {
            if (bindings.get(i).path("combo_id").asText().equals(comboId)) {
                bindings.set(i, replacement);
                MAPPER.writerWithDefaultPrettyPrinter().writeValue(bindingsFile.toFile(), library);
                return;
            }
        }
    }

    private static Set<String> loadLedger(Path ledger) throws IOException {
        Set<String> processed = new HashSet<>();
        if (Files.exists(ledger)) {
            for (String line : Files.readAllLines(ledger)) {
                if (!line.isBlank()) {
                    processed.add(MAPPER.readTree(line).path("state_hash").asText());
                }
            }
        }
        return processed;
    }

    private static void appendLedger(Path ledger, String stateHash, String binding, String outcome)
            throws IOException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("state_hash", stateHash);
        row.put("binding", binding);
        row.put("outcome", outcome);
        Files.writeString(ledger, MAPPER.writeValueAsString(row) + "\n", StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }

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

    private static String sha256(String body) {
        try {
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256")
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

    /**
     * CLI: {@code StallAutopsy <batchDir>} — needs ANTHROPIC_API_KEY and
     * bootstrap assets ({@code -Darena.assets.dir}) for sim verification of
     * repairs. The verified deck comes from the batch's first combo-aware
     * seat.
     */
    public static void main(String[] args) throws Exception {
        Path batchDir = Path.of(args[0]);
        String assets = System.getProperty("arena.assets.dir");
        forge.arena.bootstrap.ArenaBootstrap.initialize(
                new java.io.File(assets != null ? assets
                        : Files.exists(Path.of("forge-gui")) ? "forge-gui" : "../forge-gui"));
        JsonNode workerCfg = MAPPER.readTree(batchDir.resolve("worker-config.json").toFile());
        java.io.File deckFile = null;
        for (JsonNode ws : workerCfg.path("seats")) {
            if (ws.path("combo_aware").asBoolean(false)) {
                deckFile = new java.io.File(ws.get("deck_file").asText());
                break;
            }
        }
        if (deckFile == null) {
            System.out.println("stall autopsy: no combo-aware seats in this batch");
            return;
        }
        Result result = run(batchDir, forge.arena.combo.ExecutorBindings.defaultPath(),
                RouteLibrary.defaultPath(), ClaudeClient.fromEnvironment(),
                new forge.arena.engine.BindingVerifier(deckFile));
        System.out.printf("stall autopsy: %d distinct, %d repaired, %d proposals, %d no-repair,"
                + " %d cached, %d failed%n", result.distinctStalls(), result.repairedBindings(),
                result.payoffProposals(), result.noRepair(), result.cachedSkips(),
                result.failures());
        result.notes().forEach(n -> System.out.println("  " + n));
    }
}
