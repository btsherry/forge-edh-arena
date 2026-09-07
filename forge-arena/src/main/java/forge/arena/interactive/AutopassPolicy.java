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
 *   <li>declare attackers / declare blockers → keep (combat is sacred);</li>
 *   <li>own main phase → keep (mains are sacred by any layer, ever);</li>
 *   <li>an equipment that entered this turn → keep (the drop turn is when
 *       equipping is the natural play);</li>
 *   <li>a real play that costs nothing (0-mana spell, pitch/alternative
 *       cost) → keep, naming it;</li>
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
        public final boolean opponentItemOnStack;

        public Stop(final boolean myTurn, final PhaseType phase, final int poolMana, final int manaCeiling,
                final boolean freshEquipment, final List<Play> realPlays, final List<String> utilityOnly,
                final boolean opponentItemOnStack) {
            this.myTurn = myTurn;
            this.phase = phase;
            this.poolMana = poolMana;
            this.manaCeiling = manaCeiling;
            this.freshEquipment = freshEquipment;
            this.realPlays = realPlays == null ? Collections.<Play>emptyList() : realPlays;
            this.utilityOnly = utilityOnly == null ? Collections.<String>emptyList() : utilityOnly;
            this.opponentItemOnStack = opponentItemOnStack;
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

    public static Decision decide(final Stop s) {
        if (s.poolMana > 0) {
            return Decision.keep("mana floating");
        }
        if (s.phase == PhaseType.COMBAT_DECLARE_ATTACKERS || s.phase == PhaseType.COMBAT_DECLARE_BLOCKERS) {
            return Decision.keep("combat declare step");
        }
        if (s.myTurn && s.phase != null && s.phase.isMain()) {
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
