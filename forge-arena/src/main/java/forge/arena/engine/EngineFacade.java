package forge.arena.engine;

import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import com.google.common.eventbus.Subscribe;

import forge.ai.AIOption;
import forge.arena.bootstrap.ArenaBootstrap;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.Game;
import forge.game.GameEndReason;
import forge.game.GameOutcome;
import forge.game.GameRules;
import forge.game.GameType;
import forge.game.Match;
import forge.game.event.GameEventPlayerPriority;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.RegisteredPlayer;
import forge.player.GamePlayerUtil;
import forge.view.TimeLimitedCodeBlock;

/**
 * The ONLY class in forge-arena allowed to import Forge game internals for
 * game setup/teardown (plan §4, W2 remediation; enforced by ArchitectureTest).
 * When a rebase renames engine classes, the blast radius is this file.
 */
public final class EngineFacade {

    private EngineFacade() {
    }

    /**
     * Play one 4-player (2–4 seat) Commander game headless, seeded, under
     * arena-side limits. Blocks until the game ends. Extra subscribers are
     * registered on the game event bus before start (the PR-3 EventRecorder
     * plugs in here).
     *
     * @throws EngineCrashException on any engine failure — callers record it
     *         as a crash GameRecord, never drop it.
     */
    public static ArenaGameResult playCommanderGame(List<SeatSpec> seats, long seed, ArenaLimits limits,
            Object... extraSubscribers) {
        if (!ArenaBootstrap.isInitialized()) {
            throw new IllegalStateException("ArenaBootstrap.initialize() must run before playing games");
        }
        if (seats.size() < 2 || seats.size() > 4) {
            throw new IllegalArgumentException("commander pod needs 2-4 seats, got " + seats.size());
        }

        // combo-aware seats emit decision telemetry to the first event sink
        // among the subscribers (EventRecorder implements Consumer<ArenaEvent>)
        java.util.function.Consumer<forge.arena.report.ArenaEvent> eventSink = null;
        for (Object subscriber : extraSubscribers) {
            if (subscriber instanceof java.util.function.Consumer) {
                @SuppressWarnings("unchecked")
                java.util.function.Consumer<forge.arena.report.ArenaEvent> sink =
                        (java.util.function.Consumer<forge.arena.report.ArenaEvent>) subscriber;
                eventSink = sink;
                break;
            }
        }

        List<RegisteredPlayer> players = new ArrayList<>();
        List<Object> autoSubscribers = new ArrayList<>();
        int seatIndex = 0;
        for (SeatSpec seat : seats) {
            Deck deck = DeckSerializer.fromFile(seat.deckFile());
            if (deck == null || deck.getCommanders().isEmpty()) {
                throw new IllegalArgumentException("not a loadable Commander deck: " + seat.deckFile());
            }
            RegisteredPlayer rp = RegisteredPlayer.forCommander(deck);
            String name = "seat" + seatIndex + "-" + deck.getName();
            if (seat.goldfish()) {
                rp.setPlayer(new GoldfishLobbyPlayer(name));
            } else if (seat.comboAware()) {
                rp.setPlayer(comboAwareLobbyPlayer(name, seat, seatIndex, eventSink));
                // observation side (combo_state/combo_ready) rides along in
                // batches too — the canary's conversion-when-ready floor is
                // attempted/ready and needs both halves of the telemetry
                autoSubscribers.add(comboDetectionBridge(seat, seatIndex, eventSink));
            } else {
                Set<AIOption> options = seat.simulationAi()
                        ? Collections.singleton(AIOption.USE_SIMULATION)
                        : Collections.emptySet();
                rp.setPlayer(GamePlayerUtil.createAiPlayer(name, seatIndex, seatIndex, options, seat.aiProfile()));
            }
            players.add(rp);
            seatIndex++;
        }

        GameRules rules = new GameRules(GameType.Commander);
        rules.setAppliedVariants(EnumSet.of(GameType.Commander));

        Match match = new Match(rules, players, "forge-arena");
        Game game = match.createGame();
        LimitEnforcer enforcer = new LimitEnforcer(game, limits);
        game.subscribeToEvents(enforcer);
        for (Object subscriber : extraSubscribers) {
            if (subscriber instanceof GameAware aware) {
                aware.onGameCreated(game);
            }
            game.subscribeToEvents(subscriber);
        }
        for (Object subscriber : autoSubscribers) {
            if (subscriber instanceof GameAware aware) {
                aware.onGameCreated(game);
            }
            game.subscribeToEvents(subscriber);
        }

        ArenaBootstrap.seedRng(seed);
        long started = System.currentTimeMillis();
        ArenaGameResult.LimitingFactor limiting = null;
        try {
            runGameOnDeepStack(() -> match.startGame(game), limits.wallClockSec());
        } catch (TimeoutException te) {
            limiting = ArenaGameResult.LimitingFactor.WALL_CLOCK;
            game.setGameOver(GameEndReason.Draw);
            awaitOutcome(game);
        } catch (Exception e) {
            throw new EngineCrashException("engine failure seed=" + seed, e);
        }
        long durationMs = System.currentTimeMillis() - started;
        if (limiting == null) {
            limiting = enforcer.tripped();
        }

        GameOutcome outcome = game.getOutcome();
        int winnerSeat = -1;
        String winnerName = null;
        // a limit hit is a timeout_draw by harness-side definition — never report
        // a "winner" the outcome object may claim after a wall-clock interrupt
        if (limiting == null && outcome != null && !outcome.isDraw()) {
            RegisteredPlayer winner = outcome.getWinningPlayer();
            if (winner != null) {
                winnerSeat = players.indexOf(winner);
                winnerName = winner.getPlayer() != null ? winner.getPlayer().getName() : null;
            }
        }
        String winCondition = outcome != null && outcome.getWinCondition() != null
                ? outcome.getWinCondition().name()
                : "Draw";
        int turns = outcome != null ? outcome.getLastTurnNumber() : enforcer.lastTurn();

        ArenaGameResult.ResultType type;
        if (limiting != null) {
            type = ArenaGameResult.ResultType.TIMEOUT_DRAW;
        } else if (outcome == null || outcome.isDraw() || winnerSeat < 0) {
            type = ArenaGameResult.ResultType.DRAW;
        } else {
            type = ArenaGameResult.ResultType.WIN;
        }
        return new ArenaGameResult(type, winnerSeat, winnerName, winCondition, turns, durationMs, limiting);
    }

    /**
     * Thread stack for the game loop. Forge checks target legality by
     * walking every card in the game, and that walk recurses deeply once a
     * board is large — which a combo harness GUARANTEES, because bounded
     * loop products are exactly how this project converts (token floods,
     * huge pools, wide boards). On the JVM's default stack that overflows:
     * 16 of 183 games in the last batch died with StackOverflowError, and
     * one worker took a JVM-level SIGSEGV, costing about a sixth of every
     * batch's sample.
     *
     * <p>The size is EMPIRICAL, not decorative. A code review argued it
     * should shrink now that the infinite-recursion cycle is patched
     * (PR-49), since an abandoned timed-out thread retains its stack. That
     * was tried at 8MB and the test JVM died with SIGSEGV — a stack
     * overflow deep enough in native frames that the VM cannot unwind it.
     * Forge's target-legality walk really does need this much room on a
     * large board, so the reservation stays and the leak is mitigated
     * instead (daemon thread, interrupt grace, and a warning when a game
     * loop refuses to stop).
     */
    private static final int GAME_THREAD_STACK_BYTES = 64 * 1024 * 1024;

    /**
     * Run the game on a deep-stack thread with the same timeout contract
     * {@code TimeLimitedCodeBlock} provided (interrupt on expiry, propagate
     * the cause otherwise), because a single-thread executor gives no way
     * to size the stack.
     */
    /** How long to let an interrupted game loop actually stop. */
    private static final long INTERRUPT_GRACE_MS = 5_000;

    private static void runGameOnDeepStack(Runnable body, long timeoutSec) throws Exception {
        java.util.concurrent.atomic.AtomicReference<Throwable> failure =
                new java.util.concurrent.atomic.AtomicReference<>();
        Thread gameThread = new Thread(null, () -> {
            try {
                body.run();
            } catch (Throwable t) {
                failure.set(t);
            }
        }, "arena-game", GAME_THREAD_STACK_BYTES);
        gameThread.setDaemon(true);
        gameThread.start();
        gameThread.join(TimeUnit.SECONDS.toMillis(timeoutSec));
        if (gameThread.isAlive()) {
            // Review find: a game loop deep in engine work may not observe an
            // interrupt, and an abandoned thread keeps its whole Game object
            // graph reachable. Roughly a quarter of games end on the wall
            // clock, so across a 300-game batch that retention is the
            // difference between a healthy worker and an OOM. Give the
            // interrupt a moment to land and report honestly if it does not.
            gameThread.interrupt();
            gameThread.join(INTERRUPT_GRACE_MS);
            if (gameThread.isAlive()) {
                System.err.println("warning: game thread did not stop after interrupt"
                        + " — its heap stays reachable until the worker exits");
            }
            throw new TimeoutException("wall clock " + timeoutSec + "s");
        }
        Throwable t = failure.get();
        if (t instanceof Exception e) {
            throw e;
        }
        if (t != null) {
            // StackOverflowError and friends are Errors, not Exceptions —
            // wrap so the harness records a crash instead of killing the JVM
            throw new IllegalStateException("game thread died: " + t, t);
        }
    }

    /**
     * Build the PR-15 combo-aware seat: pilot artifacts load once here
     * (combos.json from the seat's dossier, the global executor bindings),
     * events flow to the batch's recorder. Missing artifacts fail loudly at
     * setup — a combo-aware seat silently running stock would corrupt A/B
     * comparisons.
     */
    private static ComboAwareLobbyPlayer comboAwareLobbyPlayer(String name, SeatSpec seat,
            int seatIndex, java.util.function.Consumer<forge.arena.report.ArenaEvent> eventSink) {
        if (seat.dossierDir() == null) {
            throw new IllegalArgumentException("combo-aware seat " + seatIndex + " needs a dossierDir");
        }
        final java.util.List<forge.arena.combo.ComboDef> defs;
        final forge.arena.combo.ExecutorBindings bindings;
        final forge.arena.combo.RoutePlan routePlan;
        final java.util.Map<String, Double> tutorWeights;
        try {
            defs = forge.arena.combo.ComboDef.loadWithDiscovered(seat.dossierDir());
            bindings = forge.arena.combo.ExecutorBindings.load(
                    forge.arena.combo.ExecutorBindings.defaultPath())
                    // PR-48: the deck's own generated wipe+shield pairs
                    .withPairedPlays(seat.dossierDir().resolve("paired-plays.json"));
            routePlan = forge.arena.combo.RoutePlan.load(
                    seat.dossierDir().resolve("route-coverage.json"));
            tutorWeights = forge.arena.combo.TutorRanker.loadWeights(
                    seat.dossierDir().resolve("tutor-priorities.json"));
        } catch (java.io.IOException e) {
            throw new IllegalArgumentException("combo-aware seat " + seatIndex
                    + ": artifacts unreadable (run arena prep): " + e.getMessage(), e);
        }
        java.util.function.Consumer<forge.arena.report.ArenaEvent> sink =
                eventSink != null ? eventSink : event -> {
                };
        // PR-24: the ranker knows the deck's payoff cards (route-coverage deck
        // layer ∪ binding payoffs — the DEPLOY breadth set) so a proven line
        // can tutor toward conversion, not just assembly
        java.util.Set<String> payoffCards = new java.util.LinkedHashSet<>();
        routePlan.payoffs().values().forEach(payoffCards::addAll);
        for (forge.arena.combo.ComboDef def : defs) {
            bindings.forCombo(def.id()).ifPresent(b -> payoffCards.addAll(b.payoffs()));
        }
        // Phase 11: compiled combo programs, discovered from the dossier.
        // A combo with a program runs ONLY through it.
        java.util.Map<String, String> programPaths = new java.util.LinkedHashMap<>();
        try (java.util.stream.Stream<java.nio.file.Path> files =
                java.nio.file.Files.list(seat.dossierDir())) {
            files.filter(f -> f.getFileName().toString().startsWith("combo-program-")
                            && f.getFileName().toString().endsWith(".json"))
                    .forEach(f -> {
                        String n = f.getFileName().toString();
                        programPaths.put(n.substring(14, n.length() - 5),
                                f.toAbsolutePath().toString());
                    });
        } catch (java.io.IOException ignored) {
        }
        // PR-eta: compiled pairing programs (wipe + shield), same discovery
        // pattern — a pair with a program runs ONLY through it.
        java.util.Map<String, String> pairingPaths = new java.util.LinkedHashMap<>();
        try (java.util.stream.Stream<java.nio.file.Path> files =
                java.nio.file.Files.list(seat.dossierDir())) {
            files.filter(f -> f.getFileName().toString().startsWith("pairing-program-")
                            && f.getFileName().toString().endsWith(".json"))
                    .forEach(f -> {
                        String n = f.getFileName().toString();
                        pairingPaths.put(n.substring(16, n.length() - 5),
                                f.toAbsolutePath().toString());
                    });
        } catch (java.io.IOException ignored) {
        }
        // PR-kappa: compiled engine programs, same discovery pattern
        java.util.Map<String, String> enginePaths = new java.util.LinkedHashMap<>();
        try (java.util.stream.Stream<java.nio.file.Path> files =
                java.nio.file.Files.list(seat.dossierDir())) {
            files.filter(x -> x.getFileName().toString().startsWith("engine-program-")
                            && x.getFileName().toString().endsWith(".json"))
                    .forEach(x -> {
                        String n = x.getFileName().toString();
                        enginePaths.put(n.substring(15, n.length() - 5),
                                x.toAbsolutePath().toString());
                    });
        } catch (java.io.IOException ignored) {
        }
        return new ComboAwareLobbyPlayer(name, player -> {
            forge.arena.combo.ComboTracker tracker = new forge.arena.combo.ComboTracker(defs);
            forge.arena.combo.ComboPilot p = new forge.arena.combo.ComboPilot(tracker, bindings,
                    routePlan, new forge.arena.combo.TutorRanker(tutorWeights, tracker, payoffCards),
                    0.0, seatIndex, sink);
            p.setProgramPaths(programPaths);
            p.setPairingPrograms(pairingPaths);
            p.setEnginePrograms(enginePaths);
            p.setProtection(loadProtection(seat.dossierDir().resolve("protection-priorities.json")));
            return p;
        });
    }

    /** Load the deck's reactive protection covers (protection-priorities.json).
     *  Missing/unreadable = no covers (a deck may hold none), never fatal. */
    private static java.util.List<forge.arena.combo.ComboPilot.ProtectionSpec> loadProtection(
            java.nio.file.Path path) {
        java.util.List<forge.arena.combo.ComboPilot.ProtectionSpec> specs =
                new java.util.ArrayList<>();
        try {
            com.fasterxml.jackson.databind.JsonNode root =
                    new com.fasterxml.jackson.databind.ObjectMapper().readTree(path.toFile());
            for (com.fasterxml.jackson.databind.JsonNode c : root.path("covers")) {
                specs.add(new forge.arena.combo.ComboPilot.ProtectionSpec(
                        c.path("card").asText(),
                        forge.arena.prep.ProtectionFinder.Scope.valueOf(
                                c.path("scope").asText("ALL_PERMANENTS")),
                        c.path("mana_value").asInt(0)));
            }
        } catch (Exception noneOrUnreadable) {
            // no protection artifact for this deck — inert, like an empty pairing set
        }
        return specs;
    }

    /** The detection-only observation bridge for a combo-aware seat (PR-11 machinery). */
    private static ComboDetectionBridge comboDetectionBridge(SeatSpec seat, int seatIndex,
            java.util.function.Consumer<forge.arena.report.ArenaEvent> eventSink) {
        try {
            java.util.List<forge.arena.combo.ComboDef> defs =
                    forge.arena.combo.ComboDef.loadWithDiscovered(seat.dossierDir());
            java.util.function.Consumer<forge.arena.report.ArenaEvent> sink =
                    eventSink != null ? eventSink : event -> {
                    };
            return new ComboDetectionBridge(seatIndex,
                    new forge.arena.combo.ComboTracker(defs), sink);
        } catch (java.io.IOException e) {
            throw new IllegalArgumentException("combo-aware seat " + seatIndex
                    + ": combos.json unreadable: " + e.getMessage(), e);
        }
    }

    /** After a wall-clock interrupt the game thread may need a moment to unwind. */
    private static void awaitOutcome(Game game) {
        for (int i = 0; i < 100 && game.getOutcome() == null; i++) {
            try {
                Thread.sleep(100);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    /**
     * Enforces the limits the engine lacks (T0 §3: no turn cap exists). Runs
     * synchronously on the game thread via the Guava event bus; ending the game
     * from inside event dispatch mirrors the engine's own MagicStack stack-depth
     * guard.
     */
    static final class LimitEnforcer {
        private final Game game;
        private final ArenaLimits limits;
        private volatile ArenaGameResult.LimitingFactor tripped;
        private volatile int lastTurn;
        private int prioritiesThisTurn;

        LimitEnforcer(Game game, ArenaLimits limits) {
            this.game = game;
            this.limits = limits;
        }

        @Subscribe
        public void onTurnBegan(GameEventTurnBegan event) {
            lastTurn = event.turnNumber();
            prioritiesThisTurn = 0;
            if (tripped == null && limits.turns() > 0 && event.turnNumber() > limits.turns()) {
                trip(ArenaGameResult.LimitingFactor.TURNS);
            }
        }

        @Subscribe
        public void onPriority(GameEventPlayerPriority event) {
            if (tripped == null && limits.priorityPassesPerTurn() > 0
                    && ++prioritiesThisTurn > limits.priorityPassesPerTurn()) {
                trip(ArenaGameResult.LimitingFactor.PRIORITY_PASSES);
            }
        }

        private void trip(ArenaGameResult.LimitingFactor factor) {
            tripped = factor;
            // Mirror the engine's own MagicStack stack-depth guard: without a
            // per-player intentionalDraw, surviving players read as "winners"
            // and GameOutcome.isDraw() is false.
            for (forge.game.player.Player p : game.getPlayers()) {
                p.intentionalDraw();
            }
            game.setGameOver(GameEndReason.Draw);
        }

        ArenaGameResult.LimitingFactor tripped() {
            return tripped;
        }

        int lastTurn() {
            return lastTurn;
        }
    }
}
