package forge.arena.engine;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import com.google.common.eventbus.Subscribe;

import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.event.GameEventCardChangeZone;
import forge.game.event.GameEventLandPlayed;
import forge.game.event.GameEventPlayerDamaged;
import forge.game.event.GameEventPlayerLivesChanged;
import forge.game.event.GameEventSpellAbilityCast;
import forge.game.event.GameEventTurnBegan;
import forge.game.event.GameEventTurnEnded;
import forge.game.player.Player;
import forge.game.player.PlayerView;
import forge.game.zone.ZoneType;

/**
 * Translates Forge game-bus events into {@link ArenaEvent}s (the report layer
 * may not import forge.game.* — ArchitectureTest). Register via
 * {@code EngineFacade.playCommanderGame(..., bridge)}.
 *
 * <p>PR-22 play-pattern telemetry (plan §7 raw material), two structured
 * events per turn:
 * <ul>
 *   <li>{@code turn_state} at turn begin — WHERE THINGS STAND, per seat:
 *       life, poison, hand/library/graveyard sizes, creatures + board power,
 *       lands, cumulative commander casts (read from live game state);
 *   <li>{@code turn_summary} at turn end — WHAT HAPPENED, per seat: damage
 *       dealt (combat/other split) and taken, cards drawn (counts — drawn
 *       identity stays unlogged), discards (names — public in the
 *       graveyard), spells, lands, creatures entered/died.
 * </ul>
 * Flow counters are accumulated HERE from the events themselves rather than
 * read from Forge's own per-turn trackers, which reset during cleanup and
 * would race the turn-end event. Everything is game-state-derived — the
 * per-seed byte-determinism contract (SeedDeterminismTest) is unaffected.
 *
 * <p>Seat attribution parses the {@code seatN-<deck>} player names the facade
 * assigns. Runs synchronously on the game thread, so no synchronization.
 */
public final class GameEventBridge implements GameAware {

    private static final int MAX_SEATS = 4;

    private final Consumer<ArenaEvent> sink;
    private Game game;
    private int currentTurn;

    // per-seat flow counters, reset after each turn_summary
    private final int[] combatDealt = new int[MAX_SEATS];
    private final int[] otherDealt = new int[MAX_SEATS];
    private final int[] taken = new int[MAX_SEATS];
    private final int[] drawn = new int[MAX_SEATS];
    private final int[] spells = new int[MAX_SEATS];
    private final int[] lands = new int[MAX_SEATS];
    private final int[] creaturesEntered = new int[MAX_SEATS];
    private final int[] creaturesDied = new int[MAX_SEATS];
    @SuppressWarnings("unchecked")
    private final List<String>[] discarded = new List[] {
            new ArrayList<String>(), new ArrayList<String>(),
            new ArrayList<String>(), new ArrayList<String>() };

    public GameEventBridge(Consumer<ArenaEvent> sink) {
        this.sink = sink;
    }

    @Override
    public void onGameCreated(Game game) {
        this.game = game;
    }

    @Subscribe
    public void onTurnBegan(GameEventTurnBegan event) {
        currentTurn = event.turnNumber();
        sink.accept(ArenaEvent.of("turn_begin", currentTurn, seatOf(event.turnOwner())));
        if (game != null) {
            List<Map<String, Object>> seats = new ArrayList<>();
            for (Player p : game.getPlayers()) {
                Integer seat = seatOfName(p.getName());
                if (seat == null) {
                    continue;
                }
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("seat", seat);
                row.put("life", p.getLife());
                row.put("poison", p.getPoisonCounters());
                row.put("hand", p.getCardsIn(ZoneType.Hand).size());
                row.put("library", p.getCardsIn(ZoneType.Library).size());
                int creatures = 0;
                int power = 0;
                int landCount = 0;
                for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
                    if (c.isCreature()) {
                        creatures++;
                        power += Math.max(0, c.getNetPower());
                    }
                    if (c.isLand()) {
                        landCount++;
                    }
                }
                row.put("creatures", creatures);
                row.put("board_power", power);
                row.put("lands", landCount);
                row.put("graveyard", p.getCardsIn(ZoneType.Graveyard).size());
                int commanderCasts = 0;
                for (Card commander : p.getCommanders()) {
                    commanderCasts += p.getCommanderCast(commander);
                }
                row.put("commander_casts", commanderCasts);
                row.put("lost", p.hasLost());
                seats.add(row);
            }
            sink.accept(ArenaEvent.of("turn_state", currentTurn, null)
                    .with("active_seat", seatOf(event.turnOwner()))
                    .with("seats", seats));
        }
    }

    @Subscribe
    public void onTurnEnded(GameEventTurnEnded event) {
        List<Map<String, Object>> seats = new ArrayList<>();
        for (int s = 0; s < MAX_SEATS; s++) {
            if (combatDealt[s] == 0 && otherDealt[s] == 0 && taken[s] == 0 && drawn[s] == 0
                    && spells[s] == 0 && lands[s] == 0 && creaturesEntered[s] == 0
                    && creaturesDied[s] == 0 && discarded[s].isEmpty()) {
                continue; // quiet seat, quiet record
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("seat", s);
            row.put("damage_dealt", Map.of("combat", combatDealt[s], "other", otherDealt[s]));
            row.put("damage_taken", taken[s]);
            row.put("drawn", drawn[s]);
            row.put("discarded", List.copyOf(discarded[s]));
            row.put("spells", spells[s]);
            row.put("lands", lands[s]);
            row.put("creatures_entered", creaturesEntered[s]);
            row.put("creatures_died", creaturesDied[s]);
            seats.add(row);
        }
        sink.accept(ArenaEvent.of("turn_summary", currentTurn, null).with("seats", seats));
        for (int s = 0; s < MAX_SEATS; s++) {
            combatDealt[s] = 0;
            otherDealt[s] = 0;
            taken[s] = 0;
            drawn[s] = 0;
            spells[s] = 0;
            lands[s] = 0;
            creaturesEntered[s] = 0;
            creaturesDied[s] = 0;
            discarded[s].clear();
        }
    }

    @Subscribe
    public void onPlayerDamaged(GameEventPlayerDamaged event) {
        Integer target = seatOf(event.target());
        if (target != null) {
            taken[target] += event.amount();
        }
        Integer source = event.source() != null ? seatOf(event.source().getController()) : null;
        if (source != null) {
            if (event.combat()) {
                combatDealt[source] += event.amount();
            } else {
                otherDealt[source] += event.amount();
            }
        }
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
        if (seat != null) {
            spells[seat]++;
        }
        sink.accept(ArenaEvent.of("spell_cast", currentTurn, seat)
                .with("desc", event.toString()));
    }

    @Subscribe
    public void onLandPlayed(GameEventLandPlayed event) {
        Integer seat = seatOf(event.player());
        if (seat != null) {
            lands[seat]++;
        }
        sink.accept(ArenaEvent.of("land_played", currentTurn, seat)
                .with("desc", event.toString()));
    }

    @Subscribe
    public void onZoneChange(GameEventCardChangeZone event) {
        String from = event.from() != null ? String.valueOf(event.from().zoneType()) : "null";
        String to = event.to() != null ? String.valueOf(event.to().zoneType()) : "null";
        Integer seat = event.card() != null ? seatOf(event.card().getController()) : null;
        if (seat != null && event.card() != null) {
            boolean creature = event.card().getCurrentState() != null
                    && event.card().getCurrentState().isCreature();
            if ("Library".equals(from) && "Hand".equals(to)) {
                drawn[seat]++;
            } else if ("Hand".equals(from) && "Graveyard".equals(to)) {
                discarded[seat].add(event.card().getName());
            } else if ("Battlefield".equals(to) && creature) {
                creaturesEntered[seat]++;
            } else if ("Battlefield".equals(from) && "Graveyard".equals(to) && creature) {
                creaturesDied[seat]++;
            }
        }
        sink.accept(ArenaEvent.of("zone_change", currentTurn, seat)
                .with("card", event.card() != null ? event.card().getName() : null)
                .with("from", from)
                .with("to", to));
    }

    /** Facade names players {@code seatN-<deck>}; parse N back out. */
    static Integer seatOf(PlayerView player) {
        return player == null ? null : seatOfName(player.getName());
    }

    static Integer seatOfName(String name) {
        if (name == null || !name.startsWith("seat")) {
            return null;
        }
        int dash = name.indexOf('-');
        if (dash <= 4) {
            return null;
        }
        try {
            int seat = Integer.parseInt(name.substring(4, dash));
            return seat >= 0 && seat < MAX_SEATS ? seat : null;
        } catch (NumberFormatException nfe) {
            return null;
        }
    }
}
