package forge.arena.engine;

import java.util.Map;
import java.util.Set;

/**
 * The hidden-information read-model (plan §9 W8): the ONLY game-state surface
 * the combo/tutor/analytics layers may touch. Pure immutable data — no Forge
 * imports — and STRUCTURALLY incapable of expressing library order or
 * opponents' hands: it carries only this seat's visible zones by card name
 * and a library card count. Built per snapshot by {@link SeatViews} (engine
 * side); constructible directly in tests.
 */
public final class SeatView {

    /** Zones this seat can see its own cards in. The library is deliberately absent. */
    public enum Zone { BATTLEFIELD, HAND, COMMAND, GRAVEYARD, EXILE }

    /** Where a named card is, from this seat's legal viewpoint. */
    public enum Presence {
        BATTLEFIELD, HAND, COMMAND, GRAVEYARD, EXILE,
        /** Not visible to this seat — includes anywhere in the (unseen) library. */
        ABSENT;

        /** Detection reachability (plan §6): graveyard needs recursion; exile/absent never. */
        public boolean reachable(boolean recursionAvailable) {
            switch (this) {
                case BATTLEFIELD:
                case HAND:
                case COMMAND:
                    return true;
                case GRAVEYARD:
                    return recursionAvailable;
                default:
                    return false;
            }
        }
    }

    /**
     * PUBLIC information about one opponent (PR-16, for the LethalityPlanner):
     * life total, poison, and battlefield card names — all open information at
     * a real table. Structurally NO hands, NO libraries (W8 unchanged).
     */
    public record OpponentView(int seatIndex, int life, int poison, Set<String> battlefield) {
        public OpponentView {
            battlefield = Set.copyOf(battlefield);
        }
    }

    private final int seatIndex;
    private final int turn;
    private final Map<Zone, Set<String>> ownCards;
    private final int librarySize;
    private final int manaPool;
    private final int ownBoardPower;
    private final java.util.List<OpponentView> opponents;
    private final Map<String, String> ownAttachments;
    private final int untappedManaSources;
    private final int handSize;
    private final int handLands;

    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize) {
        this(seatIndex, turn, ownCards, librarySize, 0, 0, java.util.List.of(), Map.of(), 0, 0, 0);
    }

    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize,
            int manaPool, int ownBoardPower, java.util.List<OpponentView> opponents) {
        this(seatIndex, turn, ownCards, librarySize, manaPool, ownBoardPower, opponents,
                Map.of(), 0, 0, 0);
    }

    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize,
            int manaPool, int ownBoardPower, java.util.List<OpponentView> opponents,
            Map<String, String> ownAttachments) {
        this(seatIndex, turn, ownCards, librarySize, manaPool, ownBoardPower, opponents,
                ownAttachments, 0, 0, 0);
    }

    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize,
            int manaPool, int ownBoardPower, java.util.List<OpponentView> opponents,
            Map<String, String> ownAttachments, int untappedManaSources) {
        this(seatIndex, turn, ownCards, librarySize, manaPool, ownBoardPower, opponents,
                ownAttachments, untappedManaSources, 0, 0);
    }

    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize,
            int manaPool, int ownBoardPower, java.util.List<OpponentView> opponents,
            Map<String, String> ownAttachments, int untappedManaSources, int handSize,
            int handLands) {
        this.seatIndex = seatIndex;
        this.turn = turn;
        this.ownCards = Map.copyOf(ownCards);
        this.librarySize = librarySize;
        this.manaPool = manaPool;
        this.ownBoardPower = ownBoardPower;
        this.opponents = java.util.List.copyOf(opponents);
        this.ownAttachments = Map.copyOf(ownAttachments);
        this.untappedManaSources = untappedManaSources;
        this.handSize = handSize;
        this.handLands = handLands;
    }

    public int seatIndex() {
        return seatIndex;
    }

    public int turn() {
        return turn;
    }

    public Set<String> cardsIn(Zone zone) {
        return ownCards.getOrDefault(zone, Set.of());
    }

    /** Count only — never contents, never order. */
    public int librarySize() {
        return librarySize;
    }

    /** This seat's own floating mana (own information). */
    public int manaPool() {
        return manaPool;
    }

    /** Summed power of this seat's creatures (public information). */
    public int ownBoardPower() {
        return ownBoardPower;
    }

    /**
     * This seat's battlefield attachments: attachment name → host card name
     * (public information; PR-18 — "Mantle on the battlefield" is not
     * "Mantle equipped to Selvala", and executability needs the difference).
     */
    public Map<String, String> ownAttachments() {
        return ownAttachments;
    }

    /**
     * Untapped, usable mana producers this seat controls (public — a rough
     * affordability signal; PR-19: don't attempt a line whose first cast is
     * plainly unpayable).
     */
    public int untappedManaSources() {
        return untappedManaSources;
    }

    /**
     * True card count of this seat's hand (own information; PR-24). The name
     * set in {@link #cardsIn} collapses duplicate basics, so mulligan policy
     * needs the real count.
     */
    public int handSize() {
        return handSize;
    }

    /** Lands among this seat's hand cards (own information; PR-24 mulligan policy). */
    public int handLands() {
        return handLands;
    }

    /** Opponents' PUBLIC state (life/poison/battlefield) — planner input. */
    public java.util.List<OpponentView> opponents() {
        return opponents;
    }

    /** First visible location in priority order; ABSENT covers the unseen library. */
    public Presence locate(String cardName) {
        if (cardsIn(Zone.BATTLEFIELD).contains(cardName)) {
            return Presence.BATTLEFIELD;
        }
        if (cardsIn(Zone.HAND).contains(cardName)) {
            return Presence.HAND;
        }
        if (cardsIn(Zone.COMMAND).contains(cardName)) {
            return Presence.COMMAND;
        }
        if (cardsIn(Zone.GRAVEYARD).contains(cardName)) {
            return Presence.GRAVEYARD;
        }
        if (cardsIn(Zone.EXILE).contains(cardName)) {
            return Presence.EXILE;
        }
        return Presence.ABSENT;
    }
}
