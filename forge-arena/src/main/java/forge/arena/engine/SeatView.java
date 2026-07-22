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
     * life total, poison, battlefield card names, and total creature power
     * (PR-eta: the pairing fire policy's "significant threats" measure) — all
     * open information at a real table. Structurally NO hands, NO libraries
     * (W8 unchanged).
     */
    public record OpponentView(int seatIndex, int life, int poison, Set<String> battlefield,
            int creaturePower) {
        public OpponentView {
            battlefield = Set.copyOf(battlefield);
        }

        /** Pre-PR-eta shape; power 0. Existing planner tests build with this. */
        public OpponentView(int seatIndex, int life, int poison, Set<String> battlefield) {
            this(seatIndex, life, poison, battlefield, 0);
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
    private final int attackReadyPower;
    /** Current phase name (PR-A): mana has a lifetime and it is this. */
    private final String phase;

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

    /**
     * Convenience overload: with no sickness information supplied, the whole
     * board is assumed able to attack. Callers that know better (the engine
     * adapter, which reads real sickness) pass the value explicitly; a test
     * that says "8 power" and nothing about sickness means a board that can
     * swing, so defaulting to 0 here would quietly invert its intent.
     */
    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize,
            int manaPool, int ownBoardPower, java.util.List<OpponentView> opponents,
            Map<String, String> ownAttachments, int untappedManaSources, int handSize,
            int handLands) {
        this(seatIndex, turn, ownCards, librarySize, manaPool, ownBoardPower, opponents,
                ownAttachments, untappedManaSources, handSize, handLands, ownBoardPower);
    }

    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize,
            int manaPool, int ownBoardPower, java.util.List<OpponentView> opponents,
            Map<String, String> ownAttachments, int untappedManaSources, int handSize,
            int handLands, int attackReadyPower) {
        this(seatIndex, turn, ownCards, librarySize, manaPool, ownBoardPower, opponents,
                ownAttachments, untappedManaSources, handSize, handLands, attackReadyPower, "");
    }

    public SeatView(int seatIndex, int turn, Map<Zone, Set<String>> ownCards, int librarySize,
            int manaPool, int ownBoardPower, java.util.List<OpponentView> opponents,
            Map<String, String> ownAttachments, int untappedManaSources, int handSize,
            int handLands, int attackReadyPower, String phase) {
        this.phase = phase == null ? "" : phase;
        this.attackReadyPower = attackReadyPower;
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
     * Summed power of only those creatures that could be declared as
     * attackers RIGHT NOW — untapped and not summoning-sick (PR-54).
     *
     * <p>This is the difference between owning a board and being able to
     * swing with it, and conflating the two cost the green deck 99 of its
     * 125 combat evaluations across a 300-game batch. Haste matters only for
     * creatures that arrived THIS turn; a board deployed on earlier turns
     * attacks perfectly well without any haste source at all (CR 302.6).
     * The planner asks this question instead of hunting for a haste card.
     */
    public int attackReadyPower() {
        return attackReadyPower;
    }

    /**
     * The phase this view was taken in (PR-A). Mana empties as each step and
     * phase ends, so a pool banked in one phase is gone in the next unless
     * an unspent-mana permanent says otherwise. Without this the pilot
     * floats a pool in a main phase and tries to spend it in combat, and the
     * engine simply refuses.
     */
    public String phase() {
        return phase;
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
