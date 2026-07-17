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

        ArenaBootstrap.seedRng(seed);
        long started = System.currentTimeMillis();
        ArenaGameResult.LimitingFactor limiting = null;
        try {
            TimeLimitedCodeBlock.runWithTimeout(() -> match.startGame(game), limits.wallClockSec(), TimeUnit.SECONDS);
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
        try {
            defs = forge.arena.combo.ComboDef.load(seat.dossierDir().resolve("combos.json"));
            bindings = forge.arena.combo.ExecutorBindings.load(
                    forge.arena.combo.ExecutorBindings.defaultPath());
        } catch (java.io.IOException e) {
            throw new IllegalArgumentException("combo-aware seat " + seatIndex
                    + ": artifacts unreadable (run arena prep): " + e.getMessage(), e);
        }
        java.util.function.Consumer<forge.arena.report.ArenaEvent> sink =
                eventSink != null ? eventSink : event -> {
                };
        return new ComboAwareLobbyPlayer(name, player -> new forge.arena.combo.ComboPilot(
                new forge.arena.combo.ComboTracker(defs), bindings, 0.0, seatIndex, sink));
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
