package forge.arena.combo;

import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * A combo as the tracker sees it, loaded from the dossier's combos.json
 * (arena.combos/1). Pure data — this package may never touch Forge internals
 * (ArchitectureTest), only SeatView.
 */
public record ComboDef(String id, List<Piece> pieces, int templateRequirements) {

    /** {@code fullySpecified} is false when the combo needs unnamed template pieces. */
    public boolean fullySpecified() {
        return templateRequirements == 0;
    }

    public record Piece(String name, boolean commander) {
    }

    public static List<ComboDef> load(Path combosJson) throws IOException {
        JsonNode root = new ObjectMapper().readTree(combosJson.toFile());
        if (!"arena.combos/1".equals(root.path("schema").asText())) {
            throw new IOException("not an arena.combos/1 artifact: " + combosJson);
        }
        List<ComboDef> defs = new ArrayList<>();
        for (JsonNode c : root.get("combos")) {
            List<Piece> pieces = new ArrayList<>();
            for (JsonNode card : c.get("cards")) {
                pieces.add(new Piece(card.get("name").asText(),
                        card.path("commander").asBoolean(false)));
            }
            defs.add(new ComboDef(c.get("id").asText(), pieces,
                    c.has("template_requirements") ? c.get("template_requirements").size() : 0));
        }
        return defs;
    }

    /**
     * The Spellbook combos PLUS the deck's DISCOVERED combos — Ben's
     * domain-knowledge lines (arena.discovered-combos/1) that Spellbook omits
     * because the pair alone produces no lethal feature (the open-payoff-slot
     * problem). Same ComboDef shape, listed in a separate file so the
     * prep-generated combos.json stays pristine. Absent file = no additions.
     */
    public static List<ComboDef> loadWithDiscovered(Path dossierDir) throws IOException {
        List<ComboDef> defs = new ArrayList<>(load(dossierDir.resolve("combos.json")));
        Path discovered = dossierDir.resolve("discovered-combos.json");
        if (java.nio.file.Files.exists(discovered)) {
            JsonNode root = new ObjectMapper().readTree(discovered.toFile());
            if (!"arena.discovered-combos/1".equals(root.path("schema").asText())) {
                throw new IOException("not an arena.discovered-combos/1 artifact: " + discovered);
            }
            for (JsonNode c : root.path("combos")) {
                List<Piece> pieces = new ArrayList<>();
                for (JsonNode card : c.get("cards")) {
                    pieces.add(new Piece(card.get("name").asText(),
                            card.path("commander").asBoolean(false)));
                }
                defs.add(new ComboDef(c.get("id").asText(), pieces,
                        c.has("template_requirements") ? c.get("template_requirements").size() : 0));
            }
        }
        return defs;
    }
}
