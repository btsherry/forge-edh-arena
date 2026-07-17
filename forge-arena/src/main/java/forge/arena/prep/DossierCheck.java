package forge.arena.prep;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.harness.DeckHash;

/**
 * Dossier freshness validation (plan §3, v3.3): "batch start does no prep
 * work — it validates dossier freshness and refuses stale or missing
 * dossiers." This is that check, shipped with prep v1 so `prep.sh --check`
 * works today; BatchMain wires it in when seats start referencing dossiers
 * (Phase 4, combo-aware seats).
 *
 * <p>Problems (refuse the dossier): missing/unreadable index, deck-hash
 * mismatch against the .dck, artifact content-hash mismatch or missing file,
 * stale win-routes version, failed or never-run gates, blocked route
 * coverage, missing required artifacts. Warnings (usable, flagged):
 * unroutable-flagged coverage.
 */
public final class DossierCheck {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Artifacts prep v1 must have registered in the index. */
    private static final List<String> REQUIRED_ARTIFACTS = List.of(
            "deck", "deck_cards", "lint_report", "implementability_report",
            "combos", "route_coverage", "tutor_priorities");

    public record Result(Path dossierDir, List<String> problems, List<String> warnings) {
        public boolean ok() {
            return problems.isEmpty();
        }
    }

    private DossierCheck() {
    }

    public static Result run(Path dossierDir) {
        return run(dossierDir, RouteLibrary.defaultPath());
    }

    public static Result run(Path dossierDir, Path libraryPath) {
        List<String> problems = new ArrayList<>();
        List<String> warnings = new ArrayList<>();

        JsonNode index;
        try {
            index = MAPPER.readTree(dossierDir.resolve("dossier.json").toFile());
        } catch (IOException e) {
            problems.add("dossier.json missing or unreadable: " + e.getMessage());
            return new Result(dossierDir, problems, warnings);
        }

        // artifact integrity: every registered file exists with matching content hash
        JsonNode artifacts = index.path("artifacts");
        for (Iterator<Map.Entry<String, JsonNode>> it = artifacts.fields(); it.hasNext();) {
            Map.Entry<String, JsonNode> e = it.next();
            Path file = dossierDir.resolve(e.getValue().path("path").asText());
            String expected = e.getValue().path("sha256").asText();
            if (!Files.exists(file)) {
                problems.add("artifact '" + e.getKey() + "' missing: " + file.getFileName());
            } else if (!sha256(file).equals(expected)) {
                problems.add("artifact '" + e.getKey() + "' modified since prep (sha256 mismatch): "
                        + file.getFileName());
            }
        }
        for (String required : REQUIRED_ARTIFACTS) {
            if (!artifacts.has(required)) {
                problems.add("required artifact not in index: " + required + " (re-run prep)");
            }
        }

        // deck identity: the hash the dossier claims must be the deck on disk
        if (artifacts.has("deck")) {
            Path dck = dossierDir.resolve(artifacts.get("deck").path("path").asText());
            if (Files.exists(dck)) {
                try {
                    String actual = DeckHash.of(dck);
                    if (!actual.equals(index.path("deck_hash").asText())) {
                        problems.add("deck_hash mismatch: deck list changed since prep (re-run prep)");
                    }
                } catch (IOException e) {
                    problems.add("deck file unreadable for hashing: " + e.getMessage());
                }
            }
        }

        // version pins
        String winRoutes = index.path("versions").path("win_routes").asText("");
        if (!winRoutes.equals(RouteRules.VERSION)) {
            problems.add("stale win-routes version: dossier has '" + winRoutes + "', current is '"
                    + RouteRules.VERSION + "' (re-run prep)");
        }
        // route library: an approval after this prep must stale the dossier
        String pinnedLibrary = index.path("versions").path("route_library")
                .asText(RouteLibrary.NO_LIBRARY);
        try {
            String currentLibrary = RouteLibrary.load(libraryPath).effectiveVersion();
            if (!pinnedLibrary.equals(currentLibrary)) {
                problems.add("stale route-library version: dossier prepped under '" + pinnedLibrary
                        + "', current approved library is '" + currentLibrary + "' (re-run prep)");
            }
        } catch (IOException e) {
            problems.add("route library unreadable: " + e.getMessage());
        }

        // gate statuses
        JsonNode status = index.path("status");
        expectStatus(problems, status, "lint", "pass");
        expectStatus(problems, status, "implementability", "pass");
        String coverage = status.path("route_coverage").asText("not_run");
        switch (coverage) {
            case "clean" -> { }
            case "unroutable_flagged" -> warnings.add(
                    "route coverage has unroutable features — usable, but the planner cannot"
                            + " express every combo win path");
            case "blocked" -> problems.add(
                    "route coverage BLOCKED: no expressible win path — batch results would"
                            + " understate this deck");
            default -> problems.add("gate route_coverage: " + coverage);
        }

        return new Result(dossierDir, problems, warnings);
    }

    private static void expectStatus(List<String> problems, JsonNode status, String gate, String want) {
        String got = status.path(gate).asText("not_run");
        if (!got.equals(want)) {
            problems.add("gate " + gate + ": " + got + " (want " + want + ")");
        }
    }

    private static String sha256(Path file) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (IOException | java.security.NoSuchAlgorithmException e) {
            return "unreadable:" + e.getMessage();
        }
    }
}
