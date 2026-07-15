package forge.arena.harness;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import forge.arena.engine.ArenaGameResult;

/**
 * One game's result row, shaped exactly like {@code arena.game-record/1}.
 * Crashes and timeouts are records too — never dropped (plan §4).
 */
public record GameRecord(
        int gameIndex,
        long seed,
        List<String> seats,
        String result,
        Integer winnerSeat,
        String winCondition,
        String limitingFactor,
        int turns,
        long durationMs,
        String crashMessage,
        String crashStackHash,
        String eventLog) {

    public static GameRecord from(int gameIndex, long seed, List<String> seats, ArenaGameResult r,
            String eventLog) {
        return new GameRecord(
                gameIndex,
                seed,
                seats,
                r.type().name().toLowerCase(),
                r.winnerSeat() >= 0 ? r.winnerSeat() : null,
                r.type() == ArenaGameResult.ResultType.WIN ? r.winCondition() : null,
                r.limitingFactor() != null ? r.limitingFactor().name().toLowerCase() : null,
                r.turns(),
                r.durationMs(),
                null,
                null,
                eventLog);
    }

    public static GameRecord crashed(int gameIndex, long seed, List<String> seats, Throwable cause,
            long durationMs, String eventLog) {
        return new GameRecord(
                gameIndex,
                seed,
                seats,
                "crash",
                null,
                null,
                null,
                0,
                durationMs,
                String.valueOf(cause),
                stackHash(cause),
                eventLog);
    }

    /** Stable-ordered map matching arena.game-record/1 for JSONL serialization. */
    public Map<String, Object> toJsonMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("schema", "arena.game-record/1");
        map.put("game_index", gameIndex);
        map.put("seed", seed);
        map.put("seats", seats);
        map.put("result", result);
        if (winnerSeat != null) {
            map.put("winner_seat", winnerSeat);
        }
        if (winCondition != null) {
            map.put("win_condition", winCondition);
        }
        if (limitingFactor != null) {
            map.put("limiting_factor", limitingFactor);
        }
        map.put("turns", turns);
        map.put("duration_ms", durationMs);
        if (crashMessage != null) {
            Map<String, Object> crash = new LinkedHashMap<>();
            crash.put("message", crashMessage);
            crash.put("stack_hash", crashStackHash);
            map.put("crash", crash);
        }
        if (eventLog != null) {
            map.put("event_log", eventLog);
        }
        return map;
    }

    /** Short content hash of the full stack trace — clusters identical crashes. */
    static String stackHash(Throwable t) {
        StringBuilder sb = new StringBuilder();
        for (Throwable c = t; c != null; c = c.getCause()) {
            sb.append(c.getClass().getName());
            for (StackTraceElement el : c.getStackTrace()) {
                sb.append('|').append(el);
            }
        }
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(sb.toString().getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (int i = 0; i < 8; i++) {
                hex.append(String.format("%02x", digest[i]));
            }
            return hex.toString();
        } catch (Exception e) {
            return "nohash";
        }
    }
}
