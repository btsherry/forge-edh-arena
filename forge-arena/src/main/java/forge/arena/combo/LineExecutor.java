package forge.arena.combo;

import java.util.List;

import forge.arena.engine.SeatView;

/**
 * A parameterized combo-line archetype (plan §6, v3.1 staged form). PR-14
 * ships the validation half: {@link #validate} proves the line on a game
 * COPY before it may ever run for real. The step half ({@link #next},
 * consumed by the PR-15 ComboAwareController line mode) is scripted per
 * stage; nothing in the harness drives it yet.
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

    /** The next scripted action for the controller (PR-15). */
    Step next(LineState state, SeatView view);

    /** One scripted action. {@code activate}: card + cost hint. */
    record Step(String action, String card, String costHint) {
        public static Step activate(String card, String costHint) {
            return new Step("activate", card, costHint);
        }

        public static Step done() {
            return new Step("done", null, null);
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
