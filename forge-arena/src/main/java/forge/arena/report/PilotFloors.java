package forge.arena.report;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Gate 4 per-deck pilot-quality floors (plan §3 v3.2, PR-17): a bad pilot
 * must never silently read as a bad deck. For every combo-aware deck the
 * canary enforces, over the games it was seated in:
 *
 * <ul>
 *   <li><b>conversion-when-ready</b>: games with an attempt (line_entered or
 *       combo_shortcut) ≥ {@code floor} (default 0.5) of games with
 *       combo_ready;
 *   <li><b>telemetry completeness</b>: a ready game with no attempt MUST
 *       carry a combo_ignored (silence is never a decision record);
 *   <li><b>stall accounting</b>: every combo_stalled must reference an
 *       existing dump file (a stall without its autopsy input is a bug).
 * </ul>
 *
 * A failing deck is {@code pilot_invalid} with the failing metric named; the
 * batch's comparative stats must exclude it (plan Gate 4). Pure reducers
 * over parsed event lines — the same JSONL the §7 analytics read.
 */
public final class PilotFloors {

    public static final double DEFAULT_CONVERSION_FLOOR = 0.5;

    public record DeckFloors(String deck, int gamesSeated, int readyGames, int attemptedGames,
            List<String> violations) {
        public boolean pilotValid() {
            return violations.isEmpty();
        }
    }

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private PilotFloors() {
    }

    /** Evaluate one deck over per-game event lists (each list = one game's JSONL). */
    public static DeckFloors evaluate(String deck, List<List<JsonNode>> games, double floor) {
        int seated = 0;
        int readyGames = 0;
        int attemptedGames = 0;
        List<String> violations = new ArrayList<>();
        for (List<JsonNode> game : games) {
            if (game.isEmpty() || !game.get(0).path("t").asText().equals("game_start")) {
                continue;
            }
            int seat = seatOf(deck, game.get(0));
            if (seat < 0) {
                continue;
            }
            seated++;
            boolean ready = false;
            boolean attempted = false;
            boolean ignored = false;
            for (JsonNode event : game) {
                if (event.path("seat").asInt(-1) != seat) {
                    continue;
                }
                String t = event.path("t").asText();
                switch (t) {
                    case "combo_ready" -> ready = true;
                    case "line_entered", "combo_shortcut" -> attempted = true;
                    case "combo_ignored" -> ignored = true;
                    case "combo_stalled" -> {
                        String dump = event.path("dump_path").asText("");
                        if (dump.isEmpty() || !Files.exists(Path.of(dump))) {
                            violations.add("combo_stalled without its dump file: " + dump);
                        }
                    }
                    default -> {
                    }
                }
            }
            if (ready) {
                readyGames++;
                if (attempted) {
                    attemptedGames++;
                } else if (!ignored) {
                    violations.add("ready-with-no-attempt lacks combo_ignored (seed "
                            + game.get(0).path("seed").asText("?") + ")");
                }
            }
        }
        if (readyGames > 0 && (double) attemptedGames / readyGames < floor) {
            violations.add(String.format(
                    "conversion-when-ready %d/%d below floor %.2f", attemptedGames, readyGames, floor));
        }
        return new DeckFloors(deck, seated, readyGames, attemptedGames, violations);
    }

    private static int seatOf(String deck, JsonNode gameStart) {
        JsonNode seats = gameStart.path("seats");
        for (int i = 0; i < seats.size(); i++) {
            if (seats.get(i).asText().equals(deck)) {
                return i;
            }
        }
        return -1;
    }

    /**
     * CLI: {@code PilotFloors <batchDir> [floor]} — reads run-manifest.json,
     * enforces floors for every combo-aware deck, exit 1 on pilot_invalid.
     */
    public static void main(String[] args) throws IOException {
        Path batchDir = Path.of(args[0]);
        double floor = args.length > 1 ? Double.parseDouble(args[1]) : DEFAULT_CONVERSION_FLOOR;
        JsonNode manifest = MAPPER.readTree(batchDir.resolve("run-manifest.json").toFile());
        List<String> comboDecks = new ArrayList<>();
        for (JsonNode seat : manifest.get("seats")) {
            if (seat.path("ai").path("combo_aware").asBoolean(false)) {
                comboDecks.add(seat.get("deck").asText());
            }
        }
        if (comboDecks.isEmpty()) {
            System.out.println("pilot floors: no combo-aware seats — nothing to enforce");
            return;
        }
        List<List<JsonNode>> games = new ArrayList<>();
        try (var files = Files.list(batchDir.resolve("events"))) {
            for (Path file : files.sorted().toList()) {
                List<JsonNode> events = new ArrayList<>();
                for (String line : Files.readAllLines(file)) {
                    if (!line.isBlank()) {
                        events.add(MAPPER.readTree(line));
                    }
                }
                games.add(events);
            }
        }
        boolean invalid = false;
        for (String deck : comboDecks) {
            DeckFloors floors = evaluate(deck, games, floor);
            System.out.printf("pilot floors %-32s seated=%d ready=%d attempted=%d -> %s%n",
                    deck, floors.gamesSeated(), floors.readyGames(), floors.attemptedGames(),
                    floors.pilotValid() ? "valid" : "PILOT_INVALID");
            for (String v : floors.violations()) {
                System.out.println("  " + v);
            }
            invalid |= !floors.pilotValid();
        }
        if (invalid) {
            System.exit(1);
        }
    }

    /** Test seam mirroring main()'s per-deck loop without process exit. */
    public static Map<String, DeckFloors> evaluateAll(List<String> comboDecks,
            List<List<JsonNode>> games, double floor) {
        Map<String, DeckFloors> out = new java.util.LinkedHashMap<>();
        for (String deck : comboDecks) {
            out.put(deck, evaluate(deck, games, floor));
        }
        return out;
    }
}
