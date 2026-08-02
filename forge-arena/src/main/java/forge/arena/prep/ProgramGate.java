package forge.arena.prep;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.ProgramFixtureProbe;
import forge.arena.engine.SeatSpec;
import forge.arena.report.ArenaEvent;

/**
 * Phase 11 PR-delta — the program executability gate. For every compiled
 * combo program in a dossier, DERIVE a goldfish fixture from the program
 * itself (pieces the setup casts go to HAND so the interpreter performs its
 * own casts; the rest to the battlefield; basic lands from the program's
 * declared costs plus the cast cards' real mana costs), play one headless
 * game, and judge by what the ENGINE says: a seat-0 win or a sustained run
 * of verified iterations is executable; anything else ships FLAGGED with the
 * abort reason. Combos with no program at all are flagged {@code no_program}.
 *
 * <p>The flag list IS the build backlog (Ben: prep iterates many times over
 * a deck; ship flagged, never hard-fail). This gate cannot fail prep — it
 * measures and records.
 */
public final class ProgramGate {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final long SEED = 42L;
    private static final int APPLY_TURN = 4;
    private static final int SUSTAIN_BAR = 5;

    public record Verdict(String comboId, String status, String reason,
            long iterations, boolean win) {
    }

    public record Report(List<Verdict> verdicts, int executable, int flagged, int noProgram) {
    }

    private ProgramGate() {
    }

    public static Report run(Path dossierDir) throws IOException {
        JsonNode index = MAPPER.readTree(dossierDir.resolve("dossier.json").toFile());
        File deckFile = dossierDir.resolve(
                index.get("artifacts").get("deck").get("path").asText()).toFile();

        Map<String, Path> programs = new LinkedHashMap<>();
        try (var files = Files.list(dossierDir)) {
            files.filter(p -> p.getFileName().toString().matches("combo-program-.*\\.json"))
                    .sorted()
                    .forEach(p -> {
                        String name = p.getFileName().toString();
                        programs.put(name.substring(14, name.length() - 5), p);
                    });
        }

        List<Verdict> verdicts = new ArrayList<>();
        for (JsonNode combo : MAPPER.readTree(dossierDir.resolve("combos.json").toFile())
                .path("combos")) {
            String id = combo.path("id").asText();
            if (!programs.containsKey(id)) {
                verdicts.add(new Verdict(id, "no_program",
                        "no compiled program — build backlog", 0, false));
            }
        }
        for (Map.Entry<String, Path> e : programs.entrySet()) {
            verdicts.add(playProgram(dossierDir, deckFile, e.getKey(), e.getValue()));
        }

        int executable = 0;
        int flagged = 0;
        int noProgram = 0;
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Verdict v : verdicts) {
            switch (v.status()) {
                case "executable" -> executable++;
                case "no_program" -> noProgram++;
                default -> flagged++;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("combo_id", v.comboId());
            row.put("status", v.status());
            row.put("reason", v.reason());
            row.put("iterations", v.iterations());
            row.put("win", v.win());
            rows.add(row);
        }
        Map<String, Object> backlog = new LinkedHashMap<>();
        backlog.put("schema", "arena.program-backlog/1");
        backlog.put("seed", SEED);
        backlog.put("sustain_bar", SUSTAIN_BAR);
        backlog.put("programs", rows);
        File backlogFile = dossierDir.resolve("program-backlog.json").toFile();
        MAPPER.writerWithDefaultPrettyPrinter().writeValue(backlogFile, backlog);

        // register + status — the gate leaves the dossier telling the truth
        // about itself, and DossierCheck will hold it to that hash
        ObjectNode artifact = MAPPER.createObjectNode();
        artifact.put("path", "program-backlog.json");
        artifact.put("sha256", sha256(backlogFile.toPath()));
        ((ObjectNode) index.get("artifacts")).set("program_backlog", artifact);
        ((ObjectNode) index.get("status")).put("programs",
                executable + " executable, " + flagged + " flagged, "
                        + noProgram + " no_program");
        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(dossierDir.resolve("dossier.json").toFile(), index);

        return new Report(verdicts, executable, flagged, noProgram);
    }

    private static Verdict playProgram(Path dossierDir, File deckFile, String comboId,
            Path programPath) throws IOException {
        JsonNode program = MAPPER.readTree(programPath.toFile());
        Fixture fixture = deriveFixture(program);
        Files.createDirectories(dossierDir.resolve("fixtures"));
        MAPPER.writerWithDefaultPrettyPrinter().writeValue(
                dossierDir.resolve("fixtures").resolve("fixture-" + comboId + ".json").toFile(),
                fixture.toJson(comboId, programPath.getFileName().toString()));

        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        java.util.function.Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result;
        try {
            result = EngineFacade.playCommanderGame(
                    List.of(SeatSpec.comboAware(deckFile, dossierDir),
                            SeatSpec.goldfish(deckFile)),
                    SEED, new ArenaLimits(12, 400, 2000), sink,
                    new ProgramFixtureProbe(APPLY_TURN, fixture.battlefield(),
                            fixture.hand(), fixture.basicLand(), fixture.landCount()));
        } catch (Exception crashed) {
            return new Verdict(comboId, "flagged", "engine_crash: " + rootMessage(crashed),
                    0, false);
        }

        long loopIters = events.stream().filter(e -> e.t().equals("outlet_drill")).count();
        // the newer shapes prove a MEASURED product without an outlet_drill:
        // a one-shot value burst (dreadnought_window) or a multi-turn engine
        // cycle (engine_cycle). Count them toward the verified total.
        long burstIters = events.stream()
                .filter(e -> e.t().equals("dreadnought_window") || e.t().equals("engine_cycle"))
                .count();
        long verified = loopIters + burstIters;
        boolean complete = events.stream()
                .anyMatch(e -> e.t().equals("program_complete")
                        && comboId.equals(String.valueOf(e.fields().get("combo"))));
        boolean win = result.type() == ArenaGameResult.ResultType.WIN
                && result.winnerSeat() == 0;
        // a loop proves out by a sustained run or a win; a one-shot burst /
        // engine proves out by a verified product plus a clean program_complete
        if (win || loopIters >= SUSTAIN_BAR || (verified >= 1 && complete)) {
            String reason = win
                    ? "engine win: " + result.winCondition() + " t" + result.turns()
                    : loopIters >= SUSTAIN_BAR
                            ? "sustained " + loopIters + " verified iterations"
                            : "verified " + verified
                                    + (burstIters > 0 ? " burst/cycle" : " iteration")
                                    + " to program_complete";
            return new Verdict(comboId, "executable", reason, verified, win);
        }
        long iterations = verified;
        String abort = events.stream()
                .filter(e -> e.t().equals("program_abort")
                        && comboId.equals(String.valueOf(e.fields().get("combo"))))
                .map(e -> String.valueOf(e.fields().get("reason")))
                .findFirst().orElse("never_entered");
        return new Verdict(comboId, "flagged", abort, iterations, false);
    }

    /** What the program says it needs, turned into a board. */
    private record Fixture(List<String> battlefield, List<String> hand,
            String basicLand, int landCount) {

        JsonNode toJson(String comboId, String derivedFrom) {
            ObjectNode n = MAPPER.createObjectNode();
            n.put("schema", "arena.program-fixture/1");
            n.put("combo_id", comboId);
            n.put("derived_from", derivedFrom);
            n.put("apply_turn", APPLY_TURN);
            n.set("battlefield", MAPPER.valueToTree(battlefield));
            n.set("hand", MAPPER.valueToTree(hand));
            n.putObject("lands").put(basicLand, landCount);
            return n;
        }
    }

    /**
     * Pieces the setup CASTS go to hand — the interpreter performs its own
     * casts, so the gate proves them too. Mana need sums the cast cards'
     * REAL mana costs (X at the program's x_min) plus the program's declared
     * activation costs; lands are basics of the costs' colors, need + margin.
     */
    private static Fixture deriveFixture(JsonNode program) {
        Set<String> castCards = new LinkedHashSet<>();
        int manaNeed = 0;
        Set<Character> colors = new LinkedHashSet<>();
        for (JsonNode step : program.path("setup")) {
            if ("cast".equals(step.path("action").asText())) {
                String card = step.path("card").asText();
                castCards.add(card);
                manaNeed += parseCost(ProgramFixtureProbe.manaCostOf(card),
                        step.path("x_min").asInt(0), colors);
            } else if (step.hasNonNull("cost")) {
                manaNeed += parseCost(step.path("cost").asText(), 0, colors);
            }
        }
        // Newer shapes carry their activation costs OUTSIDE setup: the
        // dreadnought window's exploit (and the body it casts from hand), and
        // the seedborn engine's producer/sink. Fold them into the mana need +
        // colours so the derived fixture actually funds them (task #65 — gate-4
        // derivation for the classes past mana_loop).
        JsonNode window = program.path("window");
        if (window.isObject()) {
            manaNeed += parseCost(ProgramFixtureProbe.manaCostOf(window.path("body").asText("")), 0, colors);
            JsonNode ex = window.path("exploit");
            if (ex.hasNonNull("cost")) {
                manaNeed += parseCost(ex.path("cost").asText(), 0, colors);
            }
            if (!ex.path("activate").asBoolean(false) && ex.hasNonNull("card")) {
                manaNeed += parseCost(ProgramFixtureProbe.manaCostOf(ex.path("card").asText()), 0, colors);
            }
        }
        JsonNode engine = program.path("engine");
        if (engine.isObject()) {
            JsonNode prod = engine.path("producer");
            if (prod.hasNonNull("activate_cost")) {
                manaNeed += parseCost(prod.path("activate_cost").asText(), 0, colors);
            }
            JsonNode sink = engine.path("sink");
            if (sink.hasNonNull("cost")) {
                manaNeed += parseCost(sink.path("cost").asText(), 0, colors) * 4; // several cycles
            }
        }
        List<String> battlefield = new ArrayList<>();
        List<String> hand = new ArrayList<>();
        for (JsonNode piece : program.path("pieces")) {
            String card = piece.path("card").asText();
            // an explicit requires:HAND (the runner casts it) goes to hand; a
            // setup-cast card goes to hand; everything else to the battlefield
            boolean toHand = "HAND".equalsIgnoreCase(piece.path("requires").asText(""))
                    || castCards.contains(card);
            (toHand ? hand : battlefield).add(card);
            // a mono-colour loop's pieces are the only colour signal — let them
            // pick the basic land when setup/window/engine costs were silent
            if (colors.isEmpty()) {
                for (char c : ProgramFixtureProbe.manaCostOf(card).toCharArray()) {
                    if ("WUBRG".indexOf(c) >= 0) {
                        colors.add(c);
                    }
                }
            }
        }
        String basic = colors.isEmpty() ? "Wastes" : switch (colors.iterator().next()) {
            case 'W' -> "Plains";
            case 'U' -> "Island";
            case 'B' -> "Swamp";
            case 'R' -> "Mountain";
            case 'G' -> "Forest";
            default -> "Wastes";
        };
        return new Fixture(battlefield, hand, basic, Math.max(10, manaNeed + 2));
    }

    /** Canonical brace cost string ("{2}{W}{W}", "{X}{X}") — structured, not prose. */
    private static int parseCost(String cost, int xValue, Set<Character> colors) {
        int total = 0;
        for (String sym : cost.replace("{", " ").replace("}", " ").trim().split("\\s+")) {
            if (sym.isEmpty()) {
                continue;
            }
            if (sym.chars().allMatch(Character::isDigit)) {
                total += Integer.parseInt(sym);
            } else if ("X".equals(sym)) {
                total += xValue;
            } else {
                total += 1;
                char c = sym.charAt(0);
                if ("WUBRG".indexOf(c) >= 0) {
                    colors.add(c);
                }
            }
        }
        return total;
    }

    private static String sha256(Path file) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(Files.readAllBytes(file));
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static String rootMessage(Throwable t) {
        Throwable root = t;
        while (root.getCause() != null) {
            root = root.getCause();
        }
        return root.toString();
    }

    /** CLI: {@code ProgramGate <dossier-dir>} (bootstrap via -Darena.assets.dir). */
    public static void main(String[] args) throws Exception {
        forge.arena.bootstrap.ArenaBootstrap.initialize();
        Report r = run(Path.of(args[0]));
        for (Verdict v : r.verdicts()) {
            System.out.println(v.comboId() + " " + v.status() + " — " + v.reason());
        }
        System.out.println("programs: " + r.executable() + " executable, "
                + r.flagged() + " flagged, " + r.noProgram() + " no_program");
    }
}
