package forge.arena.prep;

import java.io.IOException;
import java.nio.file.Files;
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
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Gate 1 — legality lint (plan §3). Operates purely on the dossier's
 * deck-cards.json (no Forge imports): 100 cards including commander(s),
 * singleton (basics and "a deck can have any number" cards exempt), every
 * card's color identity ⊆ the commanders' union identity, and a pinned,
 * versioned banlist. Errors block; warnings annotate. Writes
 * lint-report.json and updates dossier.json status.lint.
 */
public final class DeckLint {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public record Report(String banlistVersion, List<String> errors, List<String> warnings) {
        public boolean pass() {
            return errors.isEmpty();
        }
    }

    private DeckLint() {
    }

    public static Report run(Path dossierDir, Path banlistFile) throws IOException {
        JsonNode deckCards = MAPPER.readTree(dossierDir.resolve("deck-cards.json").toFile());
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();

        // banlist: pinned + versioned
        String banlistVersion = "unversioned";
        Set<String> banned = new HashSet<>();
        for (String raw : Files.readAllLines(banlistFile)) {
            String line = raw.strip();
            if (line.toLowerCase().startsWith("# version:")) {
                banlistVersion = line.substring(line.indexOf(':') + 1).strip();
            } else if (!line.isEmpty() && !line.startsWith("#")) {
                banned.add(line.toLowerCase());
            }
        }

        int total = 0;
        int commanders = 0;
        Set<String> commanderIdentity = new HashSet<>();
        Map<String, Integer> counts = new HashMap<>();
        for (JsonNode c : deckCards.get("cards")) {
            int qty = c.get("qty").asInt();
            total += qty;
            counts.merge(c.get("name").asText().toLowerCase(), qty, Integer::sum);
            if (c.get("zone").asText().equals("commander")) {
                commanders += qty;
                for (char ch : c.path("color_identity").asText("").toCharArray()) {
                    commanderIdentity.add(String.valueOf(ch));
                }
            }
        }

        if (total != 100) {
            errors.add("deck must be exactly 100 cards including commander(s), found " + total);
        }
        if (commanders < 1 || commanders > 2) {
            errors.add("expected 1-2 commanders, found " + commanders);
        }

        for (JsonNode c : deckCards.get("cards")) {
            String name = c.get("name").asText();
            String type = c.path("type_line").asText("");
            String oracle = c.path("oracle_text").asText("");
            boolean resolved = c.has("color_identity");

            if (banned.contains(name.toLowerCase())) {
                errors.add("banned: " + name);
            }
            int count = counts.get(name.toLowerCase());
            boolean anyNumber = oracle.toLowerCase().contains("a deck can have any number");
            if (count > 1 && !type.contains("Basic") && !anyNumber) {
                errors.add("singleton violation: " + count + "x " + name);
                counts.put(name.toLowerCase(), 1); // report once
            }
            if (resolved) {
                for (char ch : c.get("color_identity").asText().toCharArray()) {
                    if (!commanderIdentity.contains(String.valueOf(ch))) {
                        errors.add("color identity: " + name + " (" + c.get("color_identity").asText()
                                + ") outside commander identity (" + String.join("", commanderIdentity) + ")");
                        break;
                    }
                }
            } else if (!c.get("zone").asText().equals("commander")) {
                warnings.add("identity unverifiable (card not in DB): " + name);
            }
        }

        Report report = new Report(banlistVersion, errors, warnings);

        Map<String, Object> reportJson = new LinkedHashMap<>();
        reportJson.put("schema", "arena.lint-report/1");
        reportJson.put("banlist_version", banlistVersion);
        reportJson.put("pass", report.pass());
        reportJson.put("errors", errors);
        reportJson.put("warnings", warnings);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("lint-report.json").toFile(), reportJson);

        // update the dossier index in place
        ObjectNode index = (ObjectNode) MAPPER.readTree(dossierDir.resolve("dossier.json").toFile());
        ((ObjectNode) index.get("status")).put("lint", report.pass() ? "pass" : "fail");
        ((ObjectNode) index.get("versions")).put("banlist", banlistVersion);
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("dossier.json").toFile(), index);

        return report;
    }

    /** CLI: {@code DeckLint <dossier-dir> [banlist-file]} — exits 1 on lint failure. */
    public static void main(String[] args) throws Exception {
        Path banlist = args.length > 1 ? Path.of(args[1])
                : Path.of("forge-arena", "banlists", "commander-banlist.txt");
        Report r = run(Path.of(args[0]), banlist);
        System.out.println("lint " + (r.pass() ? "PASS" : "FAIL") + "  (banlist " + r.banlistVersion() + ")");
        r.errors().forEach(e -> System.out.println("error:   " + e));
        r.warnings().forEach(w -> System.out.println("warning: " + w));
        if (!r.pass()) {
            System.exit(1);
        }
    }
}
