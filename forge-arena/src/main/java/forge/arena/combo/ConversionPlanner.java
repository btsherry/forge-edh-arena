package forge.arena.combo;

import java.util.List;
import java.util.Set;

import forge.arena.engine.SeatView;
import forge.arena.prep.PayoffRules;

/**
 * Phase 6 / PR-38 — the CONVERSION state machine (docs/PHASE-6-PLAN.md §2,
 * from docs/research/combo-conversion-playbook.md §3).
 *
 * <p>The measured problem this exists to fix: across 398 seed-paired games
 * (long-200 + pr34-validation) the pilot fired engines 40 times and won 10.
 * Selvala banked a thousand green mana 28 times and converted four. The
 * stall autopsy's verdict was unanimous and independent: the bindings are
 * correct, the FAILURE IS BEHAVIOURAL — an engine with no outlet used is
 * the same as no engine at all.
 *
 * <p>The playbook's first law is the invariant here: <b>never end a turn
 * with an unused engine and an unsearched library.</b> Given a banked pool
 * this planner picks, in strict preference order:
 *
 * <ol>
 * <li><b>TABLE_WIDE</b> — one resolution that ends all three opponents at
 *     once ({@code x_drain_each_opponent}: "each opponent loses X life").
 *     Life LOSS, not damage, so it dodges prevention/protection entirely;
 *     no combat, no target splitting. Always the best line when present.</li>
 * <li><b>DRILL</b> — a battlefield sink with a repeatable damaging
 *     activation ({@code ping_any_target}: the Walking Ballista class).
 *     Fires once per priority window until the table is dead (PR-37).</li>
 * <li><b>DIG</b> — no outlet reachable, so spend the pool on CARDS
 *     ({@code self_draw_engine}) and re-enter next priority with a bigger
 *     hand. This is what a human does with a stranded engine; a pilot that
 *     passes instead is the 25% conversion rate.</li>
 * <li><b>NONE</b> — the existing deploy path (mass-pump/haste payoffs into
 *     combat) keeps the turn, unchanged.</li>
 * </ol>
 *
 * <p>Everything here is artifact-driven: card names come from the deck's own
 * route-coverage payoff classes and the fired binding, never from a
 * hardcoded list, so a dropped-in deck gets the same treatment. Pure
 * decision logic — no engine types beyond the {@link SeatView} read-model.
 */
public final class ConversionPlanner {

    /** What to do with a banked pool this priority window. */
    public enum Kind {
        /** Cast a one-resolution table-killer at the scripted X. */
        TABLE_WIDE,
        /** Arm the loop-to-lethal drill on a battlefield sink (PR-37). */
        DRILL,
        /** Spend the pool on cards and re-enter with a bigger hand. */
        DIG,
        /** Nothing conversion-specific — the deploy path keeps the turn. */
        NONE
    }

    /**
     * The chosen conversion action. {@code x} is meaningful for TABLE_WIDE
     * (huge — the pool covers it) and DIG (bounded by the deck-out guard).
     */
    public record Plan(Kind kind, String card, int x, String outletClass) {
        public static final Plan NOTHING = new Plan(Kind.NONE, null, 0, null);
    }

    /**
     * Leave this many cards in the library when digging. Drawing the last
     * card loses the game at the next state-based check (CR 121.4 / 704.5b)
     * unless a draw-replacement win is already on the battlefield, and a
     * player who would simultaneously win and lose simply LOSES (CR
     * 104.3f) — so the floor is never traded away for one more card.
     */
    static final int LIBRARY_FLOOR = 5;

    /** A single dig is a big draw, not a deck-out: bounded per activation. */
    static final int DIG_CAP = 20;

    private ConversionPlanner() {
    }

    /**
     * Choose this window's conversion action.
     *
     * @param view      the seat's hidden-info read-model
     * @param routePlan the deck's route-coverage artifact (payoff classes)
     * @param bindingPayoffs the fired binding's own payoff cards
     * @param attempted cards already tried this turn (per-turn dedupe)
     */
    public static Plan choose(SeatView view, RoutePlan routePlan,
            Set<String> bindingPayoffs, Set<String> attempted) {
        // (1) TABLE_WIDE — the premium class. Deliberately ONLY
        // x_drain_each_opponent: it is the sole class that turns a pool into
        // a finished game in one resolution with no feeder and no combat.
        // ping_each_opponent (Purphoros class) also flags HITS_ALL_OPPONENTS
        // but is a static permanent that needs a creature-entry feeder — it
        // belongs to the deploy path, not to "cast this and win".
        String drain = firstReachable(view, routePlan.payoffCards(
                PayoffRules.X_DRAIN_EACH_OPPONENT), attempted, false);
        if (drain != null) {
            return new Plan(Kind.TABLE_WIDE, drain, ComboPilot.DEPLOY_X,
                    PayoffRules.X_DRAIN_EACH_OPPONENT);
        }

        // (2) DRILL — a repeatable single-target sink already on the
        // battlefield. The controller validates one activation on a game
        // copy before committing (an outlet that cannot actually drop a
        // life total must never arm the drill).
        for (String sink : routePlan.payoffCards(PayoffRules.PING_ANY_TARGET)) {
            if (view.cardsIn(SeatView.Zone.BATTLEFIELD).contains(sink)
                    && !attempted.contains(sink)) {
                return new Plan(Kind.DRILL, sink, 0, PayoffRules.PING_ANY_TARGET);
            }
        }

        // (3) DIG — no outlet reachable. Spend the pool on cards rather than
        // passing the turn with a live engine (the playbook's first law).
        // The deck-out guard is a hard floor, never a preference.
        if (view.librarySize() > LIBRARY_FLOOR) {
            String dig = firstReachable(view, routePlan.payoffCards(
                    PayoffRules.SELF_DRAW_ENGINE), attempted, true);
            if (dig != null) {
                int x = Math.max(1, Math.min(view.librarySize() - LIBRARY_FLOOR, DIG_CAP));
                return new Plan(Kind.DIG, dig, x, PayoffRules.SELF_DRAW_ENGINE);
            }
        }
        return Plan.NOTHING;
    }

    /**
     * The first card of {@code candidates} the seat can act on right now.
     * Hand and COMMAND zone are castable (Gemini review: a Commander pilot
     * that forgets the command zone is useless — the commander is very often
     * the deck's own outlet or dig engine, and the engine's own cost check
     * carries commander tax); {@code includeBattlefield} additionally
     * accepts an already-deployed permanent, for classes whose payoff is an
     * activation rather than a cast.
     */
    private static String firstReachable(SeatView view, List<String> candidates,
            Set<String> attempted, boolean includeBattlefield) {
        for (String card : candidates) {
            if (attempted.contains(card)) {
                continue;
            }
            if (view.cardsIn(SeatView.Zone.HAND).contains(card)
                    || view.cardsIn(SeatView.Zone.COMMAND).contains(card)
                    || (includeBattlefield
                            && view.cardsIn(SeatView.Zone.BATTLEFIELD).contains(card))) {
                return card;
            }
        }
        return null;
    }
}
