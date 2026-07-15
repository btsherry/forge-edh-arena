package forge.arena.engine;

import java.util.function.Consumer;

import com.google.common.eventbus.Subscribe;

import forge.arena.report.ArenaEvent;
import forge.game.event.GameEventCardChangeZone;
import forge.game.event.GameEventLandPlayed;
import forge.game.event.GameEventPlayerLivesChanged;
import forge.game.event.GameEventSpellAbilityCast;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.PlayerView;

/**
 * Translates Forge game-bus events into {@link ArenaEvent}s (the report layer
 * may not import forge.game.* — ArchitectureTest). Register via
 * {@code EngineFacade.playCommanderGame(..., bridge)}.
 *
 * <p>Seat attribution parses the {@code seatN-<deck>} player names the facade
 * assigns. Runs synchronously on the game thread, so the turn counter needs no
 * synchronization.
 */
public final class GameEventBridge {

    private final Consumer<ArenaEvent> sink;
    private int currentTurn;

    public GameEventBridge(Consumer<ArenaEvent> sink) {
        this.sink = sink;
    }

    @Subscribe
    public void onTurnBegan(GameEventTurnBegan event) {
        currentTurn = event.turnNumber();
        sink.accept(ArenaEvent.of("turn_begin", currentTurn, seatOf(event.turnOwner())));
    }

    @Subscribe
    public void onLivesChanged(GameEventPlayerLivesChanged event) {
        sink.accept(ArenaEvent.of("life_change", currentTurn, seatOf(event.player()))
                .with("player", event.player() != null ? event.player().getName() : null)
                .with("old", event.oldLives())
                .with("new", event.newLives()));
    }

    @Subscribe
    public void onSpellCast(GameEventSpellAbilityCast event) {
        Integer seat = event.si() != null ? seatOf(event.si().getActivatingPlayer()) : null;
        sink.accept(ArenaEvent.of("spell_cast", currentTurn, seat)
                .with("desc", event.toString()));
    }

    @Subscribe
    public void onLandPlayed(GameEventLandPlayed event) {
        sink.accept(ArenaEvent.of("spell_cast", currentTurn, seatOf(event.player()))
                .with("desc", event.toString()));
    }

    @Subscribe
    public void onZoneChange(GameEventCardChangeZone event) {
        sink.accept(ArenaEvent.of("zone_change", currentTurn, null)
                .with("card", event.card() != null ? event.card().getName() : null)
                .with("from", event.from() != null ? String.valueOf(event.from().zoneType()) : "null")
                .with("to", event.to() != null ? String.valueOf(event.to().zoneType()) : "null"));
    }

    /** Facade names players {@code seatN-<deck>}; parse N back out. */
    static Integer seatOf(PlayerView player) {
        if (player == null) {
            return null;
        }
        String name = player.getName();
        if (name == null || !name.startsWith("seat")) {
            return null;
        }
        int dash = name.indexOf('-');
        if (dash <= 4) {
            return null;
        }
        try {
            return Integer.parseInt(name.substring(4, dash));
        } catch (NumberFormatException nfe) {
            return null;
        }
    }
}
