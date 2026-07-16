package forge.arena.ingest;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLMapper;

import forge.arena.engine.CardCatalog;
import forge.arena.engine.CardInfo;
import forge.arena.harness.DeckHash;

/**
 * Gate 0 (v3.3): normalize an input deck list into the dossier skeleton —
 * normalized .dck, deck-meta.yaml, deck-cards.json (the full-oracle-text LLM
 * handoff package), and a schema-shaped dossier.json index. Offline; card
 * resolution against the local DB only (unresolved names become warnings —
 * Gate 2 formalizes implementability later).
 */
public final class Ingest {

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final YAMLMapper YAML = new YAMLMapper();

    public record Spec(Path input, String deckId, Path outRoot, String source, Integer expectedBracket,
            String name, String notes, List<String> commanderOverride) {
    }

    public record Result(Path dossierDir, int cards, List<String> unresolved, List<String> warnings) {
    }

    private Ingest() {
    }

    public static Result run(Spec spec) throws IOException {
        DeckListParser.Parsed parsed = DeckListParser.parse(Files.readAllLines(spec.input()));
        List<DeckListParser.Entry> commanders = new ArrayList<>(parsed.commanders());
        List<DeckListParser.Entry> main = new ArrayList<>(parsed.main());
        List<String> warnings = new ArrayList<>(parsed.warnings());

        // --commander override: pull named cards out of main (or add outright)
        if (spec.commanderOverride() != null) {
            for (String cmdr : spec.commanderOverride()) {
                boolean moved = main.removeIf(e -> e.name().equalsIgnoreCase(cmdr));
                commanders.removeIf(e -> e.name().equalsIgnoreCase(cmdr));
                commanders.add(new DeckListParser.Entry(cmdr, 1));
                if (!moved) {
                    warnings.add("commander override not found in list, added: " + cmdr);
                }
            }
        }
        if (commanders.isEmpty()) {
            throw new IllegalArgumentException(
                    "no commander identified — use a [Commander] section, 'Commander:' header, "
                            + "*CMDR* marker, Archidekt [Commander] tag, or --commander <name>");
        }

        Path dossier = spec.outRoot().resolve(spec.deckId()).resolve("dossier");
        Files.createDirectories(dossier);

        // 1. normalized .dck
        StringBuilder dck = new StringBuilder("[metadata]\n");
        dck.append("Name=").append(spec.name() != null ? spec.name() : spec.deckId()).append('\n');
        dck.append("[Commander]\n");
        commanders.forEach(e -> dck.append(e.qty()).append(' ').append(e.name()).append('\n'));
        dck.append("[Main]\n");
        main.forEach(e -> dck.append(e.qty()).append(' ').append(e.name()).append('\n'));
        Path dckFile = dossier.resolve(spec.deckId() + ".dck");
        Files.writeString(dckFile, dck.toString());

        // 2. deck-meta.yaml (plan §3 Gate 0 example)
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("name", spec.name() != null ? spec.name() : spec.deckId());
        meta.put("source", spec.source() != null ? spec.source() : "homebrew");
        meta.put("source_url", null);
        meta.put("archetype_tags", List.of());
        meta.put("expected_bracket", spec.expectedBracket());
        meta.put("author_notes", spec.notes());
        Path metaFile = dossier.resolve("deck-meta.yaml");
        YAML.writeValue(metaFile.toFile(), meta);

        // 3. deck-cards.json — full oracle-text card list (LLM handoff package)
        List<Map<String, Object>> cards = new ArrayList<>();
        List<String> unresolved = new ArrayList<>();
        describeInto(commanders, "commander", cards, unresolved);
        describeInto(main, "main", cards, unresolved);
        Map<String, Object> deckCards = new LinkedHashMap<>();
        deckCards.put("schema", "arena.deck-cards/1");
        deckCards.put("deck_id", spec.deckId());
        deckCards.put("cards", cards);
        deckCards.put("unresolved", unresolved);
        Path cardsFile = dossier.resolve("deck-cards.json");
        JSON.writerWithDefaultPrettyPrinter().writeValue(cardsFile.toFile(), deckCards);
        unresolved.forEach(u -> warnings.add("card not in Forge DB: " + u));

        // 4. dossier.json index
        Map<String, Object> index = new LinkedHashMap<>();
        index.put("schema", "arena.dossier/1");
        index.put("deck_id", spec.deckId());
        index.put("deck_hash", DeckHash.of(dckFile));
        index.put("created", Instant.now().toString());
        // pin the CURRENT rules version, not a literal — a hardcoded string here
        // shipped stale once already (win-routes/1 while the rules were at /3)
        index.put("versions", Map.of("schemas", "1", "win_routes", forge.arena.prep.RouteRules.VERSION));
        Map<String, Object> artifacts = new LinkedHashMap<>();
        artifacts.put("deck", fileRef(dossier, dckFile));
        artifacts.put("deck_meta", fileRef(dossier, metaFile));
        artifacts.put("deck_cards", fileRef(dossier, cardsFile));
        index.put("artifacts", artifacts);
        Map<String, Object> status = new LinkedHashMap<>();
        status.put("lint", "not_run");
        status.put("implementability", "not_run");
        status.put("route_coverage", "not_run");
        status.put("sim_verified", "not_run");
        status.put("goldfish", "not_run");
        index.put("status", status);
        index.put("warnings", warnings);
        JSON.writerWithDefaultPrettyPrinter().writeValue(dossier.resolve("dossier.json").toFile(), index);

        return new Result(dossier, cards.size(), unresolved, warnings);
    }

    private static void describeInto(List<DeckListParser.Entry> entries, String zone,
            List<Map<String, Object>> cards, List<String> unresolved) {
        for (DeckListParser.Entry e : entries) {
            Map<String, Object> row = new LinkedHashMap<>();
            Optional<CardInfo> info = CardCatalog.describe(e.name());
            row.put("name", info.map(CardInfo::name).orElse(e.name()));
            row.put("qty", e.qty());
            row.put("zone", zone);
            if (info.isPresent()) {
                CardInfo c = info.get();
                row.put("mana_cost", c.manaCost());
                row.put("type_line", c.typeLine());
                row.put("color_identity", c.colorIdentity());
                row.put("oracle_text", c.oracleText());
            } else {
                unresolved.add(e.name());
            }
            cards.add(row);
        }
    }

    private static Map<String, Object> fileRef(Path dossier, Path file) throws IOException {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) {
                hex.append(String.format("%02x", b));
            }
            Map<String, Object> ref = new LinkedHashMap<>();
            ref.put("path", dossier.relativize(file).toString());
            ref.put("sha256", hex.toString());
            return ref;
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

}
