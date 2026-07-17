package forge.arena.combo;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
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

    /** One pilot output: either a scripted step to play, or a shortcut order. */
    public record Action(LineExecutor.Step step, ShortcutOrder shortcut) {
        public boolean isStep() {
            return step != null;
        }

        static Action play(LineExecutor.Step step) {
            return new Action(step, null);
        }

        static Action shortcut(ShortcutOrder order) {
            return new Action(null, order);
        }
    }

    /**
     * PR-16 loop shortcut (plan §5/§6): the proven loop compresses to a
     * bounded pool injection; the planner already chose the route.
     */
    public record ShortcutOrder(String comboId, String engineCard, String color, int amount,
            String route) {
    }

    /** Bounded product of a proven-infinite loop (plan: large, engine-safe). */
    public static final int SHORTCUT_POOL = 10_000;

    private final ComboTracker tracker;
    private final ExecutorBindings bindings;
    private final RoutePlan routePlan;
    private final TutorRanker tutorRanker;
    private final double patience;
    private final int seat;
    private final Consumer<ArenaEvent> events;

    private String activeComboId;
    private LineExecutor activeExecutor;
    private ExecutorBindings.Binding activeBinding;
    private LineExecutor.LineState lineState;
    private final Map<String, Integer> firstReadyTurn = new HashMap<>();
    private final Map<String, Integer> lastIgnoredTurn = new HashMap<>();
    private final Set<String> attemptedThisTurn = new HashSet<>();
    private final Set<String> firedShortcuts = new HashSet<>();
    private int seenTurn = -1;
    private String lastAssemblySignature;
    private int assemblyRepeats;

    public ComboPilot(ComboTracker tracker, ExecutorBindings bindings, double patience,
            int seat, Consumer<ArenaEvent> events) {
        this(tracker, bindings, RoutePlan.empty(), null, patience, seat, events);
    }

    public ComboPilot(ComboTracker tracker, ExecutorBindings bindings, RoutePlan routePlan,
            double patience, int seat, Consumer<ArenaEvent> events) {
        this(tracker, bindings, routePlan, null, patience, seat, events);
    }

    public ComboPilot(ComboTracker tracker, ExecutorBindings bindings, RoutePlan routePlan,
            TutorRanker tutorRanker, double patience, int seat, Consumer<ArenaEvent> events) {
        this.tracker = tracker;
        this.bindings = bindings;
        this.routePlan = routePlan;
        this.tutorRanker = tutorRanker != null ? tutorRanker
                : new TutorRanker(Map.of(), tracker);
        this.patience = patience;
        this.seat = seat;
        this.events = events;
    }

    /**
     * Rank a search effect's options (PR-17): empty list = the ranker has no
     * opinion, stock heuristics decide (and no event — the situation carried
     * no combo information). A real opinion is RECORDED: tutor_decision with
     * the full ranking and per-candidate why (plan §5 / §7 tutor audit).
     */
    public List<TutorRanker.Ranked> rankTutor(String source, List<String> options, SeatView view) {
        List<TutorRanker.Ranked> ranked = tutorRanker.rank(options, view);
        if (ranked.isEmpty() || ranked.get(0).score() <= 0) {
            return List.of();
        }
        List<Map<String, Object>> rankedRows = new java.util.ArrayList<>();
        for (TutorRanker.Ranked r : ranked.subList(0, Math.min(8, ranked.size()))) {
            Map<String, Object> row = new java.util.LinkedHashMap<>();
            row.put("c", r.card());
            row.put("score", Math.round(r.score() * 1000.0) / 1000.0);
            row.put("why", r.why());
            rankedRows.add(row);
        }
        events.accept(ArenaEvent.of("tutor_decision", view.turn(), seat)
                .with("source", source)
                .with("chosen", ranked.get(0).card())
                .with("ranked", rankedRows));
        return ranked;
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
    public Optional<Action> nextAction(SeatView view, boolean entryWindowOpen,
            Function<LineExecutor, SimResult> validator) {
        if (view.turn() != seenTurn) {
            seenTurn = view.turn();
            attemptedThisTurn.clear();
        }

        if (lineActive()) {
            // ASSEMBLY and DEPLOY are sorcery-speed stages (casts, equips):
            // outside the window the engine refuses them silently and the
            // line would spin — wait for our next main phase instead
            if ((lineState.stage() == 0 || lineState.stage() == 2) && !entryWindowOpen) {
                return Optional.empty();
            }
            if (lineState.stage() == 0) {
                return assemblyAction(view, validator);
            }
            if (lineState.stage() == 2) {
                return deployAction(view);
            }
            LineExecutor.Step step = activeExecutor.next(lineState, view);
            if (step.isDone()) {
                exitLine();
                return Optional.empty();
            }
            events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                    .with("stage", activeExecutor.stages().get(lineState.stage()))
                    .with("iteration", lineState.iteration()));
            lineState = lineState.advance();
            return Optional.of(Action.play(step));
        }

        if (!entryWindowOpen) {
            return Optional.empty(); // not a decision point — no phantom events
        }

        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (!status.ready() || !status.fullySpecified()
                    || attemptedThisTurn.contains(status.id())) {
                continue;
            }
            if (firedShortcuts.contains(status.id())) {
                // pool already ordered — conversion is pending and the stall
                // watchdog owns the window; re-firing would just be noise
                ignore(status.id(), view.turn(), "mana_reserved");
                continue;
            }
            Optional<ExecutorBindings.Binding> binding = bindings.forCombo(status.id());
            Optional<LineExecutor> executor = binding.flatMap(ExecutorBindings::executorFor);
            if (executor.isEmpty()) {
                // no binding / unknown archetype: detection-only until a
                // generic fallback can convert proven resources
                ignore(status.id(), view.turn(), "no_viable_route");
                continue;
            }
            // PR-18 (first e2e finding): tracker readiness is REACHABILITY;
            // an unassemblable line (piece in graveyard/unseen) is no route
            if (executor.get().assemblySteps(view) == null) {
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
            activeComboId = status.id();
            activeExecutor = executor.get();
            activeBinding = binding.get();
            lineState = new LineExecutor.LineState(0, 0);
            events.accept(ArenaEvent.of("line_entered", view.turn(), seat)
                    .with("combo", status.id())
                    .with("binding", binding.get().comboId())
                    .with("attempted_via", "binding")
                    .with("entry_phase", executor.get().entryPhase()));
            return assemblyAction(view, validator);
        }
        return Optional.empty();
    }

    /**
     * The ASSEMBLY stage (PR-18): deploy reachable pieces until the line is
     * executable, THEN prove it on a copy. Validation failure after assembly
     * is a line abort (the attempt happened and is recorded), not an ignore.
     */
    private Optional<Action> assemblyAction(SeatView view,
            Function<LineExecutor, SimResult> validator) {
        List<LineExecutor.Step> assembly = activeExecutor.assemblySteps(view);
        if (assembly == null) {
            abortLine(view.turn(), "validation", null);
            return Optional.empty();
        }
        if (!assembly.isEmpty()) {
            // no-progress watchdog: a step that plays but changes nothing
            // (silent engine refusal) must abort, never spin priorities away
            String signature = assembly.toString();
            if (signature.equals(lastAssemblySignature)) {
                if (++assemblyRepeats > 8) {
                    abortLine(view.turn(), "engine_error", assembly.get(0).card());
                    return Optional.empty();
                }
            } else {
                lastAssemblySignature = signature;
                assemblyRepeats = 0;
            }
            events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                    .with("stage", "ASSEMBLY")
                    .with("iteration", lineState.iteration()));
            lineState = lineState.advance();
            return Optional.of(Action.play(assembly.get(0)));
        }

        // assembled — the engine proves the loop before anything fires
        SimResult proof = validator.apply(activeExecutor);
        if (!proof.isProfitable()) {
            abortLine(view.turn(), "validation", null);
            return Optional.empty();
        }
        if (activeExecutor instanceof TapForManaUntapLoop loop && loop.shortcutEligible()) {
            String comboId = activeComboId;
            String engineCard = activeBinding.params().get("engine");
            LethalityPlanner.Verdict verdict = LethalityPlanner.choose(routePlan, view, events);
            Map<String, Object> boundedProduct = new HashMap<>();
            boundedProduct.put("mana_" + loop.poolColor(), SHORTCUT_POOL);
            firedShortcuts.add(comboId);
            events.accept(ArenaEvent.of("combo_shortcut", view.turn(), seat)
                    .with("combo", comboId)
                    .with("iterations_proven", proof.cycles())
                    .with("bounded_product", boundedProduct));
            // PR-18 (second e2e finding): stock AI's DECISION layer never sees
            // floating mana (only battlefield sources) — the pool must be
            // SPENT by script. DEPLOY follows: cast the binding's payoffs.
            lineState = new LineExecutor.LineState(2, 0);
            return Optional.of(Action.shortcut(new ShortcutOrder(comboId, engineCard,
                    loop.poolColor(), SHORTCUT_POOL, verdict.route())));
        }
        lineState = lineState.nextStage(); // MANA_LOOP stepping (banking path)
        return nextAction(view, true, validator);
    }

    /**
     * The DEPLOY stage (PR-18): convert the injected pool by casting the
     * binding's payoff cards from hand, one per priority — Craterhoof,
     * Finale, Crossroads class. Hand exhausted = line complete; combat
     * conversion is the stock attack logic's job (haste creatures attack).
     */
    private Optional<Action> deployAction(SeatView view) {
        for (String payoff : activeBinding.payoffs()) {
            if (view.cardsIn(SeatView.Zone.HAND).contains(payoff)) {
                events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                        .with("stage", "DEPLOY")
                        .with("iteration", lineState.iteration()));
                lineState = lineState.advance();
                return Optional.of(Action.play(LineExecutor.Step.cast(payoff)));
            }
        }
        exitLine();
        return Optional.empty();
    }

    /** Gate 3.6 logging half: the controller's stall watchdog reports through the pilot. */
    public void reportStalled(int turn, String binding, String stateHash, String dumpPath) {
        events.accept(ArenaEvent.of("combo_stalled", turn, seat)
                .with("binding", binding)
                .with("state_hash", stateHash)
                .with("dump_path", dumpPath));
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
        activeBinding = null;
        lineState = null;
        lastAssemblySignature = null;
        assemblyRepeats = 0;
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
