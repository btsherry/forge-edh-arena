package forge.arena.report;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Arena's own event model — the single stream both log sinks consume (plan §5
 * v3.2 dual-sink rule). Engine events are translated to this by
 * {@code forge.arena.engine.GameEventBridge}; combo/route/tutor events will be
 * emitted directly by the combo layer. Field order is stable (insertion order)
 * so serialized logs are byte-deterministic under a fixed seed.
 */
public record ArenaEvent(String t, Integer turn, Integer seat, Map<String, Object> fields) {

    public static ArenaEvent of(String t, Integer turn, Integer seat) {
        return new ArenaEvent(t, turn, seat, new LinkedHashMap<>());
    }

    public ArenaEvent with(String key, Object value) {
        if (value != null) {
            fields.put(key, value);
        }
        return this;
    }

    /** Stable-ordered map for JSONL serialization: t, turn, seat, then fields. */
    public Map<String, Object> toJsonMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("t", t);
        if (turn != null) {
            map.put("turn", turn);
        }
        if (seat != null) {
            map.put("seat", seat);
        }
        map.putAll(fields);
        return map;
    }
}
