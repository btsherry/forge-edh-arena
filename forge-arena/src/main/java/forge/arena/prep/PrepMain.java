package forge.arena.prep;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.ingest.Ingest;

/**
 * `arena prep <deck>` v1 — the dossier compiler (plan §3, v3.3): Gate 0
 * ingest → Gate 1 lint → Gate 2 implementability/goldfish → Gate 3 combos +
 * route coverage → tutor weights → finalized, content-addressed dossier
 * index. All gates run even when an earlier one fails (one complete report
 * per prep run); the exit code says whether the dossier is batch-ready.
 * Prep-time only — the only component allowed network (Spellbook,
 * cache-first by deck hash).
 *
 * <p>Usage: {@code PrepMain <input> --id <deck-id> [--commander <name>]...
 * [--out <dir>=decks] [--source homebrew|netdeck] [--bracket N]
 * [--name <display name>] [--notes <text>] [--banlist <file>]
 * [--goldfish-games N=3] [--offline]}, or {@code PrepMain --check
 * <dossier-dir>} for the freshness validation batches will rely on.
 * Assets dir via {@code -Darena.assets.dir}.
 */
public final class PrepMain {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Artifact key in dossier.json -> file name (deck resolved from the index). */
    private static final Map<String, String> ARTIFACT_FILES = new LinkedHashMap<>();
    static {
        ARTIFACT_FILES.put("deck_meta", "deck-meta.yaml");
        ARTIFACT_FILES.put("deck_cards", "deck-cards.json");
        ARTIFACT_FILES.put("lint_report", "lint-report.json");
        ARTIFACT_FILES.put("implementability_report", "implementability-report.json");
        ARTIFACT_FILES.put("unimplemented_cards", "unimplemented-cards.txt");
        ARTIFACT_FILES.put("spellbook_raw", "spellbook-raw.json");
        ARTIFACT_FILES.put("spellbook_raw_meta", "spellbook-raw.meta.json");
        ARTIFACT_FILES.put("combos", "combos.json");
        ARTIFACT_FILES.put("advisory_combos", "advisory-combos.json");
        ARTIFACT_FILES.put("route_coverage", "route-coverage.json");
        ARTIFACT_FILES.put("tutor_priorities", "tutor-priorities.json");
        ARTIFACT_FILES.put("autopsy_proposals", "autopsy-proposals.json");
        ARTIFACT_FILES.put("autopsy_raw", "autopsy-raw.json");
    }

    /**
     * {@code routeLibrary} null = the in-repo default; {@code autopsyClient}
     * null = no LLM calls ever (the default — autopsy is strictly opt-in).
     */
    public record Options(Ingest.Spec ingest, Path banlist, int goldfishGames,
            SpellbookClient.Fetcher fetcher, Path routeLibrary, ClaudeClient autopsyClient) {
        public Options(Ingest.Spec ingest, Path banlist, int goldfishGames,
                SpellbookClient.Fetcher fetcher) {
            this(ingest, banlist, goldfishGames, fetcher, null, null);
        }
    }

    public record GateOutcome(String gate, boolean ok, String detail) {
    }

    public record PrepResult(Path dossierDir, List<GateOutcome> gates, boolean ok) {
    }

    private PrepMain() {
    }

    /** The full gate chain; requires ArenaBootstrap (Gate 0 card DB, Gate 2 engine). */
    public static PrepResult prep(Options options) throws IOException {
        List<GateOutcome> gates = new ArrayList<>();
        RouteLibrary library = RouteLibrary.load(
                options.routeLibrary() != null ? options.routeLibrary() : RouteLibrary.defaultPath());

        // Gate 0 — ingest (a failure here is unrecoverable: no dossier skeleton)
        Ingest.Result ingest = Ingest.run(options.ingest());
        Path dossier = ingest.dossierDir();
        gates.add(new GateOutcome("0 ingest", ingest.unresolved().isEmpty(),
                ingest.cards() + " card rows (basics folded), " + ingest.unresolved().size()
                        + " unresolved, " + ingest.warnings().size() + " warnings"));

        // Gate 1 — legality lint
        DeckLint.Report lint = DeckLint.run(dossier, options.banlist());
        gates.add(new GateOutcome("1 lint", lint.pass(),
                lint.pass() ? "banlist " + lint.banlistVersion()
                        : lint.errors().size() + " errors (lint-report.json)"));

        // Gate 2 — implementability + goldfish compile
        GoldfishCompile.Report goldfish = GoldfishCompile.run(dossier, options.goldfishGames(), 12);
        gates.add(new GateOutcome("2 implementability", goldfish.pass(),
                !goldfish.unimplemented().isEmpty()
                        ? goldfish.unimplemented().size() + " cards not in Forge DB"
                        : goldfish.failure() != null ? goldfish.failure()
                        : options.goldfishGames() == 0 ? "card DB clean (goldfish SKIPPED)"
                        : goldfish.games().size() + " goldfish games clean"));

        // Gate 3 — combos + route coverage (deck layer)
        boolean comboOk = false;
        String coverageStatus = "not_run";
        try {
            ComboPrep.Result combos = ComboPrep.run(dossier, options.fetcher(), library);
            comboOk = !combos.coverageStatus().equals("blocked");
            coverageStatus = combos.coverageStatus();
            gates.add(new GateOutcome("3 combos+coverage", comboOk,
                    combos.included() + " combos, " + combos.almostIncluded()
                            + " advisory, coverage " + combos.coverageStatus()
                            + (combos.unroutableFeatures().isEmpty() ? ""
                                    : ", " + combos.unroutableFeatures().size() + " unroutable features")));
        } catch (IOException e) {
            gates.add(new GateOutcome("3 combos+coverage", false, e.getMessage()));
        }

        // tutor weights need Gate 3 artifacts
        if (coverageStatus.equals("not_run")) {
            gates.add(new GateOutcome("tutor weights", false, "skipped (Gate 3 failed)"));
        } else {
            TutorWeights.Result weights = TutorWeights.run(dossier);
            gates.add(new GateOutcome("tutor weights", true,
                    weights.weightedCards() + " weighted cards"));
        }

        // prep autopsy (PR-13): opt-in, fires only on blocked/flagged coverage
        if (options.autopsyClient() != null && !coverageStatus.equals("not_run")) {
            try {
                PrepAutopsy.Result autopsy = PrepAutopsy.run(dossier, library, options.autopsyClient());
                gates.add(new GateOutcome("autopsy", autopsy.ranOrCached(), autopsy.detail()));
            } catch (IOException e) {
                gates.add(new GateOutcome("autopsy", false, e.getMessage()));
            }
        }

        finalizeIndex(dossier, gates);
        boolean ok = gates.stream().allMatch(GateOutcome::ok);
        return new PrepResult(dossier, gates, ok);
    }

    /**
     * Content-address every artifact into dossier.json (the gates each wrote
     * their own status fields already) and record gate failures as warnings.
     */
    private static void finalizeIndex(Path dossier, List<GateOutcome> gates) throws IOException {
        ObjectNode index = (ObjectNode) MAPPER.readTree(dossier.resolve("dossier.json").toFile());
        ObjectNode artifacts = (ObjectNode) index.get("artifacts");
        for (Map.Entry<String, String> e : ARTIFACT_FILES.entrySet()) {
            Path file = dossier.resolve(e.getValue());
            if (Files.exists(file)) {
                ObjectNode ref = artifacts.putObject(e.getKey());
                ref.put("path", e.getValue());
                ref.put("sha256", sha256(file));
            }
        }
        // the .dck was registered by ingest; refresh its hash for symmetry
        if (artifacts.has("deck")) {
            Path dck = dossier.resolve(artifacts.get("deck").get("path").asText());
            ((ObjectNode) artifacts.get("deck")).put("sha256", sha256(dck));
        }
        for (GateOutcome gate : gates) {
            if (!gate.ok()) {
                index.withArray("warnings").add("gate " + gate.gate() + ": " + gate.detail());
            }
        }
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossier.resolve("dossier.json").toFile(), index);
    }

    private static String sha256(Path file) throws IOException {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            usage();
            System.exit(2);
        }

        if (args[0].equals("--check")) {
            if (args.length != 2) {
                usage();
                System.exit(2);
            }
            DossierCheck.Result check = DossierCheck.run(Path.of(args[1]));
            check.problems().forEach(p -> System.out.println("problem: " + p));
            check.warnings().forEach(w -> System.out.println("warning: " + w));
            System.out.println("dossier " + (check.ok() ? "FRESH" : "REFUSED") + ": " + args[1]);
            System.exit(check.ok() ? 0 : 1);
        }

        Path input = Path.of(args[0]);
        String id = null;
        Path out = Path.of("decks");
        String source = "homebrew";
        Integer bracket = null;
        String name = null;
        String notes = null;
        Path banlist = null;
        int goldfishGames = 3;
        boolean offline = false;
        boolean autopsy = false;
        List<String> commanders = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            switch (args[i]) {
                case "--id" -> id = args[++i];
                case "--commander" -> commanders.add(args[++i]);
                case "--out" -> out = Path.of(args[++i]);
                case "--source" -> source = args[++i];
                case "--bracket" -> bracket = Integer.parseInt(args[++i]);
                case "--name" -> name = args[++i];
                case "--notes" -> notes = args[++i];
                case "--banlist" -> banlist = Path.of(args[++i]);
                case "--goldfish-games" -> goldfishGames = Integer.parseInt(args[++i]);
                case "--offline" -> offline = true;
                case "--autopsy" -> autopsy = true;
                default -> {
                    System.err.println("unknown option: " + args[i]);
                    usage();
                    System.exit(2);
                }
            }
        }
        if (id == null) {
            System.err.println("--id <deck-id> is required");
            usage();
            System.exit(2);
        }
        if (banlist == null) {
            banlist = firstExisting(
                    Path.of("forge-arena", "banlists", "commander-banlist.txt"),
                    Path.of("banlists", "commander-banlist.txt"));
        }

        String assetsProp = System.getProperty(ArenaBootstrap.ASSETS_DIR_PROPERTY);
        File assets = assetsProp != null ? new File(assetsProp)
                : firstExisting(Path.of("forge-gui"), Path.of("..", "forge-gui")).toFile();
        ArenaBootstrap.initialize(assets);

        SpellbookClient.Fetcher fetcher = offline
                ? (url, body) -> {
                    throw new IOException("offline mode and no usable cached snapshot");
                }
                : SpellbookClient.httpFetcher();

        // fail fast on a missing API key BEFORE any gate runs, not after goldfish
        ClaudeClient autopsyClient = null;
        if (autopsy) {
            try {
                autopsyClient = ClaudeClient.fromEnvironment();
            } catch (IllegalStateException e) {
                System.err.println(e.getMessage());
                System.exit(2);
            }
        }

        PrepResult result = prep(new Options(
                new Ingest.Spec(input, id, out, source, bracket, name, notes,
                        commanders.isEmpty() ? null : commanders),
                banlist, goldfishGames, fetcher, null, autopsyClient));

        System.out.println();
        for (GateOutcome gate : result.gates()) {
            System.out.printf("%-22s %-4s %s%n", "gate " + gate.gate(),
                    gate.ok() ? "OK" : "FAIL", gate.detail());
        }
        System.out.println();
        System.out.println("dossier: " + result.dossierDir()
                + (result.ok() ? "  (batch-ready)" : "  (NOT batch-ready — see gate failures above)"));
        System.exit(result.ok() ? 0 : 1);
    }

    private static Path firstExisting(Path... candidates) {
        for (Path candidate : candidates) {
            if (Files.exists(candidate)) {
                return candidate;
            }
        }
        return candidates[candidates.length - 1];
    }

    private static void usage() {
        System.err.println("usage: PrepMain <input> --id <deck-id> [--commander <name>]..."
                + " [--out <dir>] [--source homebrew|netdeck] [--bracket N] [--name <n>]"
                + " [--notes <t>] [--banlist <file>] [--goldfish-games N] [--offline]"
                + " [--autopsy]");
        System.err.println("       PrepMain --check <dossier-dir>");
        System.err.println("--autopsy: on blocked/unroutable coverage, ONE Claude call proposes"
                + " classifications into the route library (needs " + ClaudeClient.API_KEY_ENV
                + "; proposals are inert until approved)");
    }
}
