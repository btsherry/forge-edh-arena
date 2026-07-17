package forge.arena.combo;

import java.util.List;

import forge.arena.engine.SeatView;

/**
 * A parameterized combo-line archetype (plan §6, v3.1 staged form).
 * {@link #validate} proves the line on a game COPY before it may ever run
 * for real; {@link #next} scripts the live steps the PR-15
 * ComboAwareController plays one priority at a time. Validation drives the
 * SAME step script, so what was proven is exactly what gets executed.
 */
public interface LineExecutor {

    /** Stable archetype id — the executor-bindings.json dispatch key. */
    String archetype();

    /** Stage names in order (v3.1: Staff = MANA_LOOP → DRAW_LOOP → DEPLOY_WIN). */
    List<String> stages();

    /** Phase the line must enter in (default MAIN1 — combat stays available). */
    String entryPhase();

    /** Prove the full chain on a sandbox copy; the engine is the oracle. */
    SimResult validate(SimHandle sim);

    /**
     * Rough mana value of casting a named piece (PR-19 affordability gate,
     * from binding params). 0 = unknown, never gates.
     */
    default int castCostEstimate(String card) {
        return 0;
    }

    /** The next scripted action; {@code Step.done()} ends the line. */
    Step next(LineState state, SeatView view);

    /**
     * PR-29: what makes this line's yield profitable, or null. A line that
     * validates UNPROFITABLE with a declared prerequisite asks the pilot to
     * DEPLOY toward it (the gauntlet finding: Staff and Sabertooth lines are
     * correct but need a big body the pilot never provided — the deck has
     * fatties in hand; cast them). v1 vocabulary: {@code board_power}.
     */
    default String yieldPrereq() {
        return null;
    }

    /**
     * The steps that make this line EXECUTABLE from the current board
     * (PR-18: tracker readiness is reachability — hand and command zone
     * count — but activation needs pieces deployed and attached). Recomputed
     * every priority as the board changes; empty = executable now; null =
     * not assemblable from here.
     */
    default List<Step> assemblySteps(SeatView view) {
        return List.of();
    }

    /**
     * One scripted action. {@code activate}: battlefield card + cost hint +
     * explicit targets (v3.1 lesson: unscripted targets are nondeterministic
     * — a step that needs targets names them). {@code cast}: play the named
     * card from hand or the command zone (PR-18 assembly). {@code x}
     * (PR-25): explicit X for X-cost casts — the AI's own X choice is
     * pool-blind (game 78: Finale cast at small X with 10^4 floating), so
     * conversion casts pin it; null = no opinion, applied only when the
     * resolved spell actually has X in its cost. {@code choice} (PR-27a):
     * a RESOLUTION-TIME choice hint — Sabertooth's bounce is a Hidden
     * ChangeZone choice, not a cast-time target, so the step names the card
     * the controller must pick when the engine asks; null = no hint.
     */
    record Step(String action, String card, String costHint, List<String> targets, Integer x,
            String choice) {
        public Step(String action, String card, String costHint, List<String> targets) {
            this(action, card, costHint, targets, null, null);
        }

        public Step(String action, String card, String costHint, List<String> targets, Integer x) {
            this(action, card, costHint, targets, x, null);
        }

        public static Step activate(String card, String costHint) {
            return new Step("activate", card, costHint, List.of());
        }

        public static Step activateTargeting(String card, String costHint, String... targets) {
            return new Step("activate", card, costHint, List.of(targets));
        }

        public static Step activateChoosing(String card, String costHint, String choice) {
            return new Step("activate", card, costHint, List.of(), null, choice);
        }

        public static Step cast(String card) {
            return new Step("cast", card, null, List.of());
        }

        public static Step castX(String card, int x) {
            return new Step("cast", card, null, List.of(), x);
        }

        public static Step done() {
            return new Step("done", null, null, List.of());
        }

        /**
         * PR-29: deploy toward the line's yield prerequisite — the
         * controller resolves it with engine data (the biggest affordable
         * creature in hand for {@code board_power}).
         */
        public static Step prereqDeploy() {
            return new Step("prereq_deploy", null, null, List.of());
        }

        public boolean isDone() {
            return "done".equals(action);
        }

        public boolean isCast() {
            return "cast".equals(action);
        }
    }

    /** Where the line is: current stage index + iterations within it. */
    record LineState(int stage, int iteration) {
        public LineState advance() {
            return new LineState(stage, iteration + 1);
        }

        public LineState nextStage() {
            return new LineState(stage + 1, 0);
        }
    }
}
