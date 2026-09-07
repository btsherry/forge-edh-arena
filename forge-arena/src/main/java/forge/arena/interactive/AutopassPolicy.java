package forge.arena.interactive;

import java.util.Collections;
import java.util.List;

import forge.game.phase.PhaseType;

/**
 * The casts-mode autopass decision as a pure table (Ben, 2026-09-07: "make the
 * auto pass more aggressive when I have no mana and no plays, or am just
 * acknowledging damage pings"). {@link AdvisorControllerHuman} adapts the live
 * board into a {@link Stop} and applies the {@link Decision}; the rules live
 * here so they can be tested without a display.
 *
 * <p>Order of rules (first match wins):
 * <ol>
 *   <li>mana floating in the pool → keep (unspent mana signals intent);</li>
 *   <li>declare attackers / declare blockers → keep (combat is sacred) unless
 *       nothing at all is possible: no free or affordable play with a known
 *       ceiling and no activated ability — then pass;</li>
 *   <li>own main phase → keep (mains are sacred by any layer, ever); the one
 *       opt-in exception is {@code ARENA_AUTOPASS_RESOLVE_OWN=on}: with only
 *       your own items on the stack, one pass lets your spell resolve;</li>
 *   <li>an equipment that entered this turn → keep (the drop turn is when
 *       equipping is the natural play);</li>
 *   <li>a real play that costs nothing (0-mana spell, pitch/alternative
 *       cost) → keep, naming it;</li>
 *   <li>a utility ability that can be the response → keep: its permanent is
 *       targeted by the opponent's stack item, it has a sacrifice cost while
 *       an opponent's item is up, or it targets at an opponent's begin-combat
 *       (tappers, Maze of Ith);</li>
 *   <li>no real play at all → pass ("only utility: …" or "nothing available")
 *       — this now applies with an opponent's spell or trigger on the stack
 *       too, which is the damage-ping case;</li>
 *   <li>real plays exist, the mana ceiling is known and even the cheapest
 *       costs more than the ceiling → pass ("cheapest play costs N, you have
 *       M");</li>
 *   <li>otherwise keep, naming the cheapest castable play (the receipt says
 *       what held the prompt open).</li>
 * </ol>
 * A variable or unknown mana ceiling (Selvala-class producers, power-scaled
 * sources) reads as unbounded: with real plays in hand the prompt stays open,
 * because the AI payer that would estimate them is blind to that mana
 * (game-4 MAIN2 incident).
 */
public final class AutopassPolicy {

    private AutopassPolicy() {
    }

    /** One priority stop, reduced to what the policy needs. */
    public static final class Stop {
        public final boolean myTurn;
        public final PhaseType phase;
        public final int poolMana;
        /** Pool plus every untapped source's yield; {@code -1} = unknown/unbounded. */
        public final int manaCeiling;
        public final boolean freshEquipment;
        /** Real plays (spells, planeswalker abilities, land drops) with their mana cost. */
        public final List<Play> realPlays;
        /** Names of utility activations (tap abilities and the like). */
        public final List<String> utilityOnly;
        /** The same utilities with the facts that can make one a response. */
        public final List<Utility> utilities;
        public final boolean opponentItemOnStack;
        /** The stack is non-empty and every item on it is the human's own. */
        public final boolean onlyOwnItemsOnStack;
        /** ARENA_AUTOPASS_RESOLVE_OWN=on: one pass lets your own spell resolve in your main phase. */
        public final boolean resolveOwnEnabled;

        public Stop(final boolean myTurn, final PhaseType phase, final int poolMana, final int manaCeiling,
                final boolean freshEquipment, final List<Play> realPlays, final List<String> utilityOnly,
                final boolean opponentItemOnStack) {
            this(myTurn, phase, poolMana, manaCeiling, freshEquipment, realPlays, utilityOnly, null, opponentItemOnStack,
                    false, false);
        }

        public Stop(final boolean myTurn, final PhaseType phase, final int poolMana, final int manaCeiling,
                final boolean freshEquipment, final List<Play> realPlays, final List<String> utilityOnly,
                final List<Utility> utilities, final boolean opponentItemOnStack) {
            this(myTurn, phase, poolMana, manaCeiling, freshEquipment, realPlays, utilityOnly, utilities, opponentItemOnStack,
                    false, false);
        }

        public Stop(final boolean myTurn, final PhaseType phase, final int poolMana, final int manaCeiling,
                final boolean freshEquipment, final List<Play> realPlays, final List<String> utilityOnly,
                final List<Utility> utilities, final boolean opponentItemOnStack,
                final boolean onlyOwnItemsOnStack, final boolean resolveOwnEnabled) {
            this.onlyOwnItemsOnStack = onlyOwnItemsOnStack;
            this.resolveOwnEnabled = resolveOwnEnabled;
            this.myTurn = myTurn;
            this.phase = phase;
            this.poolMana = poolMana;
            this.manaCeiling = manaCeiling;
            this.freshEquipment = freshEquipment;
            this.realPlays = realPlays == null ? Collections.<Play>emptyList() : realPlays;
            this.utilityOnly = utilityOnly == null ? Collections.<String>emptyList() : utilityOnly;
            this.utilities = utilities == null ? Collections.<Utility>emptyList() : utilities;
            this.opponentItemOnStack = opponentItemOnStack;
        }
    }

    /** A non-mana activated ability and the two facts that can make it a response. */
    public static final class Utility {
        public final String name;
        /** Its cost sacrifices something (a sac outlet answers removal and wipes). */
        public final boolean sacCost;
        /** It targets (a tapper / Maze of Ith fires at an opponent's begin-combat). */
        public final boolean targets;
        /** Its permanent is targeted by an opponent's item on the stack right now. */
        public final boolean targetedByOpponent;

        public Utility(final String name, final boolean sacCost, final boolean targets, final boolean targetedByOpponent) {
            this.name = name;
            this.sacCost = sacCost;
            this.targets = targets;
            this.targetedByOpponent = targetedByOpponent;
        }
    }

    /** A real play and its total mana cost ({@code 0} = free / pitch / alternative). */
    public static final class Play {
        public final String name;
        public final int manaCost;

        public Play(final String name, final int manaCost) {
            this.name = name;
            this.manaCost = manaCost;
        }
    }

    public static final class Decision {
        public final boolean pass;
        public final String reason;

        Decision(final boolean pass, final String reason) {
            this.pass = pass;
            this.reason = reason;
        }

        static Decision keep(final String why) {
            return new Decision(false, why);
        }

        static Decision pass(final String why) {
            return new Decision(true, why);
        }

        @Override
        public String toString() {
            return (pass ? "PASS: " : "KEEP: ") + reason;
        }
    }

    /** No free play, no play within a KNOWN ceiling, no activated ability at all. */
    static boolean nothingPossible(final Stop s) {
        if (s.freshEquipment || !s.utilities.isEmpty() || !s.utilityOnly.isEmpty() || s.manaCeiling < 0) {
            return false;
        }
        for (final Play p : s.realPlays) {
            if (p.manaCost <= s.manaCeiling) {
                return false;
            }
        }
        return true;
    }

    public static Decision decide(final Stop s) {
        if (s.poolMana > 0) {
            return Decision.keep("mana floating");
        }
        if (s.phase == PhaseType.COMBAT_DECLARE_ATTACKERS || s.phase == PhaseType.COMBAT_DECLARE_BLOCKERS) {
            // Ben (2026-09-07, "pass with no action where sensical"): a declare
            // step where NOTHING is possible — no free or affordable play, no
            // activated ability of any kind, ceiling known — may pass. Any
            // doubt keeps it, as before.
            if (nothingPossible(s)) {
                return Decision.pass("declare step, nothing possible");
            }
            return Decision.keep("combat declare step");
        }
        if (s.myTurn && s.phase != null && s.phase.isMain()) {
            if (s.resolveOwnEnabled && s.onlyOwnItemsOnStack) {
                return Decision.pass("letting your own spell resolve (ARENA_AUTOPASS_RESOLVE_OWN)");
            }
            return Decision.keep("own main phase");
        }
        if (s.freshEquipment) {
            return Decision.keep("equipment entered this turn");
        }
        Play cheapest = null;
        for (final Play p : s.realPlays) {
            if (p.manaCost <= 0) {
                return Decision.keep("free play: " + p.name);
            }
            if (cheapest == null || p.manaCost < cheapest.manaCost) {
                cheapest = p;
            }
        }
        // Ben (2026-09-07): tapping or sacrificing a permanent can BE the response.
        // Three narrow keeps ahead of the utility-only pass.
        for (final Utility u : s.utilities) {
            if (s.opponentItemOnStack && u.targetedByOpponent) {
                return Decision.keep("response available: " + u.name + " is targeted");
            }
            if (s.opponentItemOnStack && u.sacCost) {
                return Decision.keep("response available: " + u.name + " (sacrifice outlet)");
            }
            if (!s.myTurn && s.phase == PhaseType.COMBAT_BEGIN && u.targets) {
                return Decision.keep("tapper window: " + u.name);
            }
        }
        if (cheapest == null) {
            if (!s.utilityOnly.isEmpty()) {
                return Decision.pass("only utility activations available: " + String.join(", ", s.utilityOnly));
            }
            return Decision.pass(s.opponentItemOnStack ? "nothing to respond with" : "nothing available");
        }
        if (s.manaCeiling >= 0 && cheapest.manaCost > s.manaCeiling) {
            return Decision.pass("cheapest play " + cheapest.name + " costs " + cheapest.manaCost
                    + ", you have " + s.manaCeiling);
        }
        return Decision.keep("castable: " + cheapest.name);
    }
}
