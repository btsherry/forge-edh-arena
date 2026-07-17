package forge.arena.engine;

import java.util.HashMap;
import java.util.Map;
import java.util.function.Consumer;

import com.google.common.eventbus.Subscribe;

import forge.arena.combo.ComboTracker;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.event.GameEventCardChangeZone;
import forge.game.event.GameEventTurnBegan;
import forge.game.event.GameEventTurnPhase;
import forge.game.player.Player;

/**
 * Detection-only wiring (Phase 3): on zone changes and turn boundaries,
 * snapshot the tracked seat's SeatView, recompute the tracker, and emit
 * combo_state (on distance/ready change) and combo_ready (on the
 * false→true transition) events. Lives in the engine package because it
 * touches Game/Player; the tracker itself sees only SeatView.
 */
public final class ComboDetectionBridge implements GameAware {

    private final int seatIndex;
    private final ComboTracker tracker;
    private final Consumer<ArenaEvent> sink;

    private Player player;
    private int turn;
    private String phase = "unknown";
    private final Map<String, ComboTracker.ComboStatus> last = new HashMap<>();

    public ComboDetectionBridge(int seatIndex, ComboTracker tracker, Consumer<ArenaEvent> sink) {
        this.seatIndex = seatIndex;
        this.tracker = tracker;
        this.sink = sink;
    }

    @Override
    public void onGameCreated(Game game) {
        String prefix = "seat" + seatIndex + "-";
        for (Player p : game.getPlayers()) {
            if (p.getName().startsWith(prefix)) {
                player = p;
                return;
            }
        }
        throw new IllegalStateException("no player named " + prefix + "* in game");
    }

    @Subscribe
    public void onTurnBegan(GameEventTurnBegan event) {
        turn = event.turnNumber();
        recompute();
    }

    @Subscribe
    public void onPhase(GameEventTurnPhase event) {
        phase = String.valueOf(event.phase());
    }

    @Subscribe
    public void onZoneChange(GameEventCardChangeZone event) {
        recompute();
    }

    private void recompute() {
        if (player == null || turn == 0) {
            // PR-24: pre-game hand selection is not an observation window —
            // mulligan draws churn Library↔Hand and would emit phantom
            // combo_ready for hands that get tucked straight back (the pilot's
            // dig policy makes that churn routine). The first TurnBegan does
            // the first real recompute, so a KEPT piece-hand still fires
            // ready at turn 1; §5 readiness is per-turn and turn 0 has none.
            return;
        }
        SeatView view = SeatViews.of(player, seatIndex, turn);
        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            ComboTracker.ComboStatus prev = last.put(status.id(), status);
            boolean changed = prev == null || prev.distance() != status.distance()
                    || prev.ready() != status.ready();
            if (changed) {
                sink.accept(ArenaEvent.of("combo_state", turn, seatIndex)
                        .with("combo", status.id())
                        .with("distance", status.distance())
                        .with("ready", status.ready())
                        .with("fully_specified", status.fullySpecified() ? null : false)
                        .with("where", status.where().entrySet().stream()
                                .map(e -> e.getKey() + ":" + e.getValue()).toList()));
            }
            if (status.ready() && (prev == null || !prev.ready())) {
                sink.accept(ArenaEvent.of("combo_ready", turn, seatIndex)
                        .with("combo", status.id())
                        .with("window", "phase:" + phase));
            }
        }
    }
}
