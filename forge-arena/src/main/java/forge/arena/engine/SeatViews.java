package forge.arena.engine;

import java.util.EnumMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * Engine-side factory for {@link SeatView} snapshots. This is the single
 * point where Forge zone state is projected into the hidden-info-safe
 * read-model — only visible-to-owner zones are read, and the library
 * contributes a count alone.
 */
public final class SeatViews {

    private SeatViews() {
    }

    public static SeatView of(Player player, int seatIndex, int turn) {
        Map<SeatView.Zone, Set<String>> zones = new EnumMap<>(SeatView.Zone.class);
        zones.put(SeatView.Zone.BATTLEFIELD, names(player, ZoneType.Battlefield));
        zones.put(SeatView.Zone.HAND, names(player, ZoneType.Hand));
        zones.put(SeatView.Zone.COMMAND, names(player, ZoneType.Command));
        zones.put(SeatView.Zone.GRAVEYARD, names(player, ZoneType.Graveyard));
        zones.put(SeatView.Zone.EXILE, names(player, ZoneType.Exile));
        int librarySize = player.getCardsIn(ZoneType.Library).size();
        // PR-16: own pool + board power, opponents' PUBLIC state (life/poison/battlefield)
        int manaPool = player.getManaPool().totalMana();
        int ownBoardPower = 0;
        for (Card c : player.getCreaturesInPlay()) {
            ownBoardPower += Math.max(0, c.getNetPower());
        }
        java.util.List<SeatView.OpponentView> opponents = new java.util.ArrayList<>();
        for (Player other : player.getGame().getPlayers()) {
            if (other == player || other.hasLost()) {
                continue;
            }
            opponents.add(new SeatView.OpponentView(other.getId(), other.getLife(),
                    other.getPoisonCounters(), names(other, ZoneType.Battlefield)));
        }
        Map<String, String> attachments = new java.util.HashMap<>();
        int untappedManaSources = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isAttachedToEntity() && c.getEntityAttachedTo() instanceof Card host) {
                attachments.put(c.getName(), host.getName());
            }
            if (!c.isTapped() && !c.getManaAbilities().isEmpty()
                    && !(c.isCreature() && c.hasSickness())) {
                untappedManaSources++;
            }
        }
        return new SeatView(seatIndex, turn, zones, librarySize, manaPool, ownBoardPower,
                opponents, attachments, untappedManaSources);
    }

    private static Set<String> names(Player player, ZoneType zone) {
        Set<String> names = new HashSet<>();
        for (Card c : player.getCardsIn(zone)) {
            names.add(c.getName());
        }
        return names;
    }
}
