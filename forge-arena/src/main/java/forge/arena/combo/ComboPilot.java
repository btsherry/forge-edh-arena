package forge.arena.combo;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Consumer;
import java.util.function.Function;

import forge.arena.engine.SeatView;
import forge.arena.report.ArenaEvent;

/**
 * The pure decision core behind the PR-15 ComboAwareController (plan §6):
 * given the tracker's view of the world, decide — and RECORD — whether to
 * enter a combo line, keep stepping one, ignore a ready combo, or abort.
 * Engine-free by construction (SeatView + injected validator only), so every
 * decision path is unit-testable without a game.
 *
 * <p>Telemetry contract (plan §5 v3.2 — "silence is never a valid record of
 * a decision"): a ready combo that is not attempted emits {@code
 * combo_ignored} with a reason, at most once per combo per turn (the per-turn
 * main-phase opportunity is the decision point); entering emits {@code
 * line_entered}; every step emits {@code line_step}; a line that cannot
 * continue emits {@code line_aborted}. Detection events (combo_state /
 * combo_ready) belong to ComboDetectionBridge — the pilot records decisions,
 * the bridge records observations, and they never double-report.
 *
 * <p>The patience knob (0 = fire asap .. 1 = hold) is a deterministic
 * primitive here: hold {@code round(patience * 3)} turns after first seeing
 * a combo ready, recording {@code patience_gate} each held turn. The PR-16
 * LethalityPlanner replaces holding-by-count with holding-for-protection.
 */
public final class ComboPilot {

    private final ComboTracker tracker;
    private final ExecutorBindings bindings;
    private final double patience;
    private final int seat;
    private final Consumer<ArenaEvent> events;

    private String activeComboId;
    private LineExecutor activeExecutor;
    private LineExecutor.LineState lineState;
    private final Map<String, Integer> firstReadyTurn = new HashMap<>();
    private final Map<String, Integer> lastIgnoredTurn = new HashMap<>();
    private final Set<String> attemptedThisTurn = new HashSet<>();
    private int seenTurn = -1;

    public ComboPilot(ComboTracker tracker, ExecutorBindings bindings, double patience,
            int seat, Consumer<ArenaEvent> events) {
        this.tracker = tracker;
        this.bindings = bindings;
        this.patience = patience;
        this.seat = seat;
        this.events = events;
    }

    /** True while a line is being stepped (the controller is in line mode). */
    public boolean lineActive() {
        return activeExecutor != null;
    }

    /**
     * The pilot's one decision entry, called each time the seat has priority.
     * Returns the next scripted step to play, or empty = no combo action
     * (stock AI decides). {@code validator} runs the executor against a fresh
     * game copy — injected so this class never touches the engine.
     */
    public Optional<LineExecutor.Step> nextAction(SeatView view, boolean entryWindowOpen,
            Function<LineExecutor, SimResult> validator) {
        if (view.turn() != seenTurn) {
            seenTurn = view.turn();
            attemptedThisTurn.clear();
        }

        if (lineActive()) {
            LineExecutor.Step step = activeExecutor.next(lineState, view);
            if (step.isDone()) {
                exitLine();
                return Optional.empty();
            }
            events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                    .with("stage", activeExecutor.stages().get(lineState.stage()))
                    .with("iteration", lineState.iteration()));
            lineState = lineState.advance();
            return Optional.of(step);
        }

        if (!entryWindowOpen) {
            return Optional.empty(); // not a decision point — no phantom events
        }

        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (!status.ready() || !status.fullySpecified()
                    || attemptedThisTurn.contains(status.id())) {
                continue;
            }
            Optional<ExecutorBindings.Binding> binding = bindings.forCombo(status.id());
            Optional<LineExecutor> executor = binding.flatMap(ExecutorBindings::executorFor);
            if (executor.isEmpty()) {
                // no binding / unknown archetype: detection-only until the
                // PR-16 generic fallback can convert proven resources
                ignore(status.id(), view.turn(), "no_viable_route");
                continue;
            }
            firstReadyTurn.putIfAbsent(status.id(), view.turn());
            int holdTurns = (int) Math.round(patience * 3);
            if (view.turn() - firstReadyTurn.get(status.id()) < holdTurns) {
                ignore(status.id(), view.turn(), "patience_gate");
                continue;
            }
            attemptedThisTurn.add(status.id());
            SimResult proof = validator.apply(executor.get());
            if (!proof.isProfitable()) {
                ignore(status.id(), view.turn(), "validation_failed");
                continue;
            }
            activeComboId = status.id();
            activeExecutor = executor.get();
            lineState = new LineExecutor.LineState(0, 0);
            events.accept(ArenaEvent.of("line_entered", view.turn(), seat)
                    .with("combo", status.id())
                    .with("binding", binding.get().comboId())
                    .with("attempted_via", "binding")
                    .with("entry_phase", executor.get().entryPhase()));
            return nextAction(view, true, validator); // first step, same window
        }
        return Optional.empty();
    }

    /** The controller couldn't produce a step's ability — the line ends here. */
    public void abortLine(int turn, String cause, String pieceLost) {
        ArenaEvent event = ArenaEvent.of("line_aborted", turn, seat).with("cause", cause);
        if (pieceLost != null) {
            event.with("piece_lost", pieceLost);
        }
        events.accept(event);
        exitLine();
    }

    private void exitLine() {
        activeComboId = null;
        activeExecutor = null;
        lineState = null;
    }

    private void ignore(String comboId, int turn, String reason) {
        if (Integer.valueOf(turn).equals(lastIgnoredTurn.get(comboId))) {
            return; // one decision record per combo per turn, not per priority
        }
        lastIgnoredTurn.put(comboId, turn);
        events.accept(ArenaEvent.of("combo_ignored", turn, seat)
                .with("combo", comboId)
                .with("reason", reason));
    }

    public String activeComboId() {
        return activeComboId;
    }
}
