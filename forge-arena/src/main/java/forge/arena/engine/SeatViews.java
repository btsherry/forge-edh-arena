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
        // PR-54: power that could actually be declared as attackers this
        // turn. isSick() already folds in haste (sickness && !HASTE), so an
        // untapped creature that is not sick can attack — no haste card
        // needed, and no haste card helps a creature that is merely tapped.
        int attackReadyPower = 0;
        for (Card c : player.getCreaturesInPlay()) {
            int power = Math.max(0, c.getNetPower());
            ownBoardPower += power;
            if (!c.isSick() && !c.isTapped()) {
                attackReadyPower += power;
            }
        }
        java.util.List<SeatView.OpponentView> opponents = new java.util.ArrayList<>();
        for (Player other : player.getGame().getPlayers()) {
            if (other == player || other.hasLost()) {
                continue;
            }
            int oppPower = 0;
            for (Card c : other.getCreaturesInPlay()) {
                oppPower += Math.max(0, c.getNetPower());
            }
            opponents.add(new SeatView.OpponentView(other.getId(), other.getLife(),
                    other.getPoisonCounters(), names(other, ZoneType.Battlefield), oppPower));
        }
        Map<String, String> attachments = new java.util.HashMap<>();
        int untappedManaSources = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isAttachedToEntity() && c.getEntityAttachedTo() instanceof Card host) {
                attachments.put(c.getName(), host.getName());
            }
            if (!c.isTapped() && !c.getManaAbilities().isEmpty()
                    && !(c.isCreature() && c.hasSickness())) {
                // PR-B: a source whose mana can only pay for a SUBSET of
                // spells is not general mana. Mishra's Workshop
                // (RestrictValid$ Spell.Artifact) and Throne of Eldraine
                // (Spell.ChosenColor+MonoColor) were counted as ordinary big
                // mana, so the blue deck believed it could activate its
                // commander's {5} off mana that legally cannot pay for it.
                boolean restricted = false;
                for (forge.game.spellability.SpellAbility ma : c.getManaAbilities()) {
                    if (ma.hasParam("RestrictValid")) {
                        restricted = true;
                        break;
                    }
                }
                if (!restricted) {
                    untappedManaSources++;
                }
            }
        }
        // PR-24: true hand counts (the name set collapses duplicate basics) —
        // own information, mulligan policy input
        int handSize = 0;
        int handLands = 0;
        for (Card c : player.getCardsIn(ZoneType.Hand)) {
            handSize++;
            if (c.isLand()) {
                handLands++;
            }
        }
        return new SeatView(seatIndex, turn, zones, librarySize, manaPool, ownBoardPower,
                opponents, attachments, untappedManaSources, handSize, handLands,
                attackReadyPower,
                player.getGame().getPhaseHandler().getPhase() == null ? ""
                        : player.getGame().getPhaseHandler().getPhase().name());
    }

    private static Set<String> names(Player player, ZoneType zone) {
        Set<String> names = new HashSet<>();
        for (Card c : player.getCardsIn(zone)) {
            names.add(c.getName());
        }
        return names;
    }
}
