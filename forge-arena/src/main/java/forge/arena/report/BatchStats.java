package forge.arena.report;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The §7 statistical + funnel + fingerprint reducers (PR-23): pure functions
 * over the batch's game records and event streams — no engine, no state, so
 * notebooks and future tooling can reuse them on any JSONL. One CLI:
 *
 * <pre>
 *   BatchStats &lt;batchDir&gt;            per-deck report
 *   BatchStats &lt;batchDirA&gt; &lt;batchDirB&gt;  paired-seed A/B (same seed_base)
 * </pre>
 *
 * Wilson 95% intervals on win rates (n is small in canaries — the CI says
 * so honestly). The combo funnel reads the decision taxonomy; fingerprints
 * read PR-22's turn_summary rows and degrade gracefully on older batches
 * that lack them. TrueSkill and auto-narratives are deferred (documented).
 */
public final class BatchStats {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final double Z = 1.959964; // 95%

    /** Per-deck statistical row. */
    public static final class DeckStats {
        public int games;
        public int wins;
        public int timeouts;
        public int crashes;
        public final List<Integer> winTurns = new ArrayList<>();
        public final Map<String, Integer> winConditions = new TreeMap<>();
        public final int[] winsBySeat = new int[4];
        public final int[] gamesBySeat = new int[4];
        // fingerprints (turn_summary sums; turns counted where the deck was seated)
        public long dmgDealt;
        public long drawn;
        public long spells;
        public long landDrops;
        public long summaryTurns;
        // funnel
        public int readyGames;
        public int attemptedGames;
        public int shortcutGames;
        public int convertedGames;
        public final List<Integer> hesitations = new ArrayList<>();
        public final Map<String, Integer> ignoredReasons = new TreeMap<>();
        public final Map<String, Integer> routesSelected = new TreeMap<>();
        public final Map<String, Integer> routesRejected = new TreeMap<>();

        public double winRate() {
            return games == 0 ? 0 : (double) wins / games;
        }

        public double[] wilson() {
            return BatchStats.wilson(wins, games);
        }
    }

    private BatchStats() {
    }

    /** Wilson 95% interval for a proportion — the plan §7 confidence measure. */
    public static double[] wilson(int successes, int n) {
        if (n == 0) {
            return new double[] { 0, 1 };
        }
        double p = (double) successes / n;
        double z2 = Z * Z;
        double denom = 1 + z2 / n;
        double center = (p + z2 / (2 * n)) / denom;
        double half = Z * Math.sqrt(p * (1 - p) / n + z2 / (4.0 * n * n)) / denom;
        return new double[] { Math.max(0, center - half), Math.min(1, center + half) };
    }

    /** Reduce one batch directory into per-deck stats (insertion = manifest order). */
    public static Map<String, DeckStats> reduce(Path batchDir) throws IOException {
        Map<String, DeckStats> decks = new LinkedHashMap<>();
        JsonNode manifest = MAPPER.readTree(batchDir.resolve("run-manifest.json").toFile());
        for (JsonNode seat : manifest.get("seats")) {
            decks.put(seat.get("deck").asText(), new DeckStats());
        }

        for (String line : Files.readAllLines(batchDir.resolve("game-records.jsonl"))) {
            if (line.isBlank()) {
                continue;
            }
            JsonNode record = MAPPER.readTree(line);
            List<String> seats = new ArrayList<>();
            record.get("seats").forEach(s -> seats.add(s.asText()));
            String result = record.path("result").asText();
            int winnerSeat = record.path("winner_seat").asInt(-1);
            for (int s = 0; s < seats.size(); s++) {
                DeckStats deck = decks.get(seats.get(s));
                if (deck == null) {
                    continue;
                }
                deck.games++;
                deck.gamesBySeat[s]++;
                switch (result) {
                    case "win" -> {
                        if (winnerSeat == s) {
                            deck.wins++;
                            deck.winsBySeat[s]++;
                            deck.winTurns.add(record.path("turns").asInt());
                            deck.winConditions.merge(
                                    record.path("win_condition").asText("?"), 1, Integer::sum);
                        }
                    }
                    case "timeout_draw" -> deck.timeouts++;
                    case "crash" -> deck.crashes++;
                    default -> {
                    }
                }
            }
            Path eventLog = batchDir.resolve(record.path("event_log").asText(""));
            if (Files.exists(eventLog)) {
                reduceGameEvents(eventLog, seats, winnerSeat, decks);
            }
        }
        return decks;
    }

    private static void reduceGameEvents(Path eventLog, List<String> seats, int winnerSeat,
            Map<String, DeckStats> decks) throws IOException {
        Map<String, Integer> firstReady = new LinkedHashMap<>();
        Map<String, Integer> entered = new LinkedHashMap<>();
        for (String line : Files.readAllLines(eventLog)) {
            if (line.isBlank()) {
                continue;
            }
            JsonNode e = MAPPER.readTree(line);
            String t = e.path("t").asText();
            int seat = e.path("seat").asInt(-1);
            DeckStats deck = seat >= 0 && seat < seats.size() ? decks.get(seats.get(seat)) : null;

            if (t.equals("turn_summary")) {
                for (JsonNode row : e.path("seats")) {
                    int s = row.path("seat").asInt(-1);
                    DeckStats d = s >= 0 && s < seats.size() ? decks.get(seats.get(s)) : null;
                    if (d == null) {
                        continue;
                    }
                    d.summaryTurns++;
                    d.dmgDealt += row.path("damage_dealt").path("combat").asLong()
                            + row.path("damage_dealt").path("other").asLong();
                    d.drawn += row.path("drawn").asLong();
                    d.spells += row.path("spells").asLong();
                    d.landDrops += row.path("lands").asLong();
                }
                continue;
            }
            if (deck == null) {
                continue;
            }
            String deckName = seats.get(seat);
            switch (t) {
                case "combo_ready" -> firstReady.putIfAbsent(deckName, e.path("turn").asInt());
                case "line_entered" -> entered.putIfAbsent(deckName, e.path("turn").asInt());
                case "combo_shortcut" -> entered.putIfAbsent(deckName, e.path("turn").asInt());
                case "combo_ignored" -> deck.ignoredReasons
                        .merge(e.path("reason").asText("?"), 1, Integer::sum);
                case "route_selected" -> deck.routesSelected
                        .merge(e.path("route").asText("?"), 1, Integer::sum);
                case "route_rejected" -> deck.routesRejected
                        .merge(e.path("route").asText("?"), 1, Integer::sum);
                default -> {
                }
            }
            if (t.equals("combo_shortcut")) {
                deck.shortcutGames++;
                if (winnerSeat == seat) {
                    deck.convertedGames++; // shortcut fired AND the seat won
                }
            }
        }
        for (Map.Entry<String, Integer> ready : firstReady.entrySet()) {
            DeckStats deck = decks.get(ready.getKey());
            if (deck == null) {
                continue;
            }
            deck.readyGames++;
            Integer enteredTurn = entered.get(ready.getKey());
            if (enteredTurn != null) {
                deck.attemptedGames++;
                deck.hesitations.add(Math.max(0, enteredTurn - ready.getValue()));
            }
        }
    }

    /** Render the per-deck report as text. */
    public static String render(Map<String, DeckStats> decks) {
        StringBuilder sb = new StringBuilder();
        sb.append(String.format("%-34s %5s %5s %8s %-17s %5s %5s%n",
                "deck", "games", "wins", "rate", "wilson95", "t/out", "crash"));
        for (Map.Entry<String, DeckStats> entry : decks.entrySet()) {
            DeckStats d = entry.getValue();
            double[] ci = d.wilson();
            sb.append(String.format("%-34s %5d %5d %7.1f%% [%5.1f%%,%5.1f%%] %5d %5d%n",
                    entry.getKey(), d.games, d.wins, d.winRate() * 100,
                    ci[0] * 100, ci[1] * 100, d.timeouts, d.crashes));
        }
        for (Map.Entry<String, DeckStats> entry : decks.entrySet()) {
            DeckStats d = entry.getValue();
            if (d.summaryTurns > 0) {
                sb.append(String.format(
                        "%nfingerprint %-24s dmg/turn=%.2f draw/turn=%.2f spells/turn=%.2f"
                                + " landdrop/turn=%.2f",
                        entry.getKey(), (double) d.dmgDealt / d.summaryTurns,
                        (double) d.drawn / d.summaryTurns, (double) d.spells / d.summaryTurns,
                        (double) d.landDrops / d.summaryTurns));
            }
            if (d.readyGames > 0 || !d.ignoredReasons.isEmpty()) {
                double hesitation = d.hesitations.isEmpty() ? 0
                        : d.hesitations.stream().mapToInt(Integer::intValue).average().orElse(0);
                sb.append(String.format(
                        "%nfunnel      %-24s ready=%d attempted=%d shortcut=%d converted=%d"
                                + " hesitation=%.1f ignored=%s routes+=%s routes-=%s",
                        entry.getKey(), d.readyGames, d.attemptedGames, d.shortcutGames,
                        d.convertedGames, hesitation, d.ignoredReasons, d.routesSelected,
                        d.routesRejected));
            }
            if (d.wins > 0) {
                sb.append(String.format("%nwins        %-24s turns=%s conditions=%s seatWins=%s",
                        entry.getKey(), d.winTurns, d.winConditions,
                        java.util.Arrays.toString(d.winsBySeat)));
            }
        }
        return sb.toString();
    }

    /**
     * Paired-seed A/B (plan §7): same seed_base + rotation, one flag flipped.
     * Pairs games by index and reports per-deck win flips — the paired design
     * detects small lifts that unpaired comparison would drown in variance.
     */
    public static String compare(Path batchA, Path batchB) throws IOException {
        Map<Integer, JsonNode> a = recordsByIndex(batchA);
        Map<Integer, JsonNode> b = recordsByIndex(batchB);
        Map<String, int[]> flips = new LinkedHashMap<>(); // deck -> [aOnlyWins, bOnlyWins, bothWin]
        int paired = 0;
        for (Map.Entry<Integer, JsonNode> e : a.entrySet()) {
            JsonNode ra = e.getValue();
            JsonNode rb = b.get(e.getKey());
            if (rb == null) {
                continue;
            }
            if (ra.path("seed").asLong() != rb.path("seed").asLong()) {
                return "NOT PAIRED: game " + e.getKey() + " seeds differ — same seed_base required";
            }
            paired++;
            String winA = winner(ra);
            String winB = winner(rb);
            for (String deck : List.of(winA == null ? "" : winA, winB == null ? "" : winB)) {
                if (!deck.isEmpty()) {
                    flips.putIfAbsent(deck, new int[3]);
                }
            }
            if (winA != null && winA.equals(winB)) {
                flips.get(winA)[2]++;
            } else {
                if (winA != null) {
                    flips.get(winA)[0]++;
                }
                if (winB != null) {
                    flips.get(winB)[1]++;
                }
            }
        }
        StringBuilder sb = new StringBuilder("paired games: " + paired + "\n");
        sb.append(String.format("%-34s %8s %8s %8s%n", "deck", "A-only", "B-only", "both"));
        for (Map.Entry<String, int[]> e : flips.entrySet()) {
            sb.append(String.format("%-34s %8d %8d %8d%n", e.getKey(),
                    e.getValue()[0], e.getValue()[1], e.getValue()[2]));
        }
        sb.append("(B-only > A-only = the B configuration converts games A could not)");
        return sb.toString();
    }

    private static String winner(JsonNode record) {
        if (!"win".equals(record.path("result").asText())) {
            return null;
        }
        int seat = record.path("winner_seat").asInt(-1);
        return seat >= 0 ? record.path("seats").path(seat).asText() : null;
    }

    private static Map<Integer, JsonNode> recordsByIndex(Path batchDir) throws IOException {
        Map<Integer, JsonNode> byIndex = new LinkedHashMap<>();
        for (String line : Files.readAllLines(batchDir.resolve("game-records.jsonl"))) {
            if (!line.isBlank()) {
                JsonNode record = MAPPER.readTree(line);
                byIndex.put(record.path("game_index").asInt(), record);
            }
        }
        return byIndex;
    }

    public static void main(String[] args) throws IOException {
        if (args.length == 2) {
            System.out.println(compare(Path.of(args[0]), Path.of(args[1])));
            return;
        }
        System.out.println(render(reduce(Path.of(args[0]))));
    }
}
