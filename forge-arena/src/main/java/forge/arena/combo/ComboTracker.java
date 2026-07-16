package forge.arena.combo;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * Detection-only combo tracker (plan §6, Phase 3): consumes SeatView ONLY —
 * never the Game (W8). Pure function: {@code recompute(view)} returns a
 * snapshot; the engine-side bridge diffs snapshots and emits events.
 *
 * <p>Detection semantics (plan §6/§8 ComboDistanceTest): a piece is reachable
 * from battlefield, hand, or command zone; graveyard only with recursion
 * (Phase 4 — always false here); the unseen library is ABSENT. distance =
 * count of unreachable named pieces. Combos needing unnamed template pieces
 * are never {@code ready} in detection-only mode (validation-gated later).
 */
public final class ComboTracker {

    private final List<ComboDef> combos;
    private final boolean recursionAvailable = false; // Phase 4 knob

    public ComboTracker(List<ComboDef> combos) {
        this.combos = List.copyOf(combos);
    }

    public record ComboStatus(String id, int distance, boolean ready, boolean fullySpecified,
            Map<String, String> where) {
    }

    public record Snapshot(List<ComboStatus> statuses) {

        public ComboStatus byId(String id) {
            return statuses.stream().filter(s -> s.id().equals(id)).findFirst().orElse(null);
        }
    }

    public Snapshot recompute(SeatView view) {
        List<ComboStatus> out = new ArrayList<>(combos.size());
        for (ComboDef combo : combos) {
            int missing = 0;
            Map<String, String> where = new LinkedHashMap<>();
            for (ComboDef.Piece piece : combo.pieces()) {
                SeatView.Presence presence = view.locate(piece.name());
                where.put(piece.name(), presence.name());
                if (!presence.reachable(recursionAvailable)) {
                    missing++;
                }
            }
            boolean ready = missing == 0 && combo.fullySpecified();
            out.add(new ComboStatus(combo.id(), missing, ready, combo.fullySpecified(), where));
        }
        return new Snapshot(List.copyOf(out));
    }
}
