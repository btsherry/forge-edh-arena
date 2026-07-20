package forge.arena.engine;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;

/**
 * Phase 7 step 1 (docs/PHASE-7-PLAN.md): prove the prediction primitive is
 * safe BEFORE anything depends on its answers. No behaviour change is gated
 * on this class — it exists to retire two risks that a single-threaded spike
 * cannot speak to.
 *
 * <p><b>Concurrency.</b> The cost spike ran 24 copies on one thread. Batches
 * run 6 workers. Forge's engine internals are a plausible home for mutable
 * statics and shared caches, and we have been bitten by exactly this class of
 * thing once already (PR-49: infinite mutual recursion through
 * StaticAbilityTurnPhaseReversed, fixed with a ThreadLocal reentrancy guard).
 *
 * <p><b>Hangs.</b> These decks exist to assemble infinite loops. A simulation
 * of a board carrying a live loop has no reason to terminate, and an
 * unbounded prediction in a batch worker is an unbounded outage.
 */
public class KillPredictorTest {

    @BeforeClass
    public void bootstrap() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    /**
     * Runs {@code work} against a board that is genuinely MID-GAME.
     *
     * <p>The obvious fixture — play a game, keep the Game object, predict
     * afterwards — is worthless here: by then the game is over, combat has
     * nothing to advance, and every prediction trivially answers "nobody
     * dies". The work has to happen inside the turn event, on the game
     * thread, against a live board, because that is the only state the
     * predictor will ever actually be asked about.
     */
    private void onLiveBoard(int atTurn, java.util.function.BiConsumer<Game, Player> work)
            throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("predict-stalls").toString());
        Path dossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        AtomicInteger ran = new AtomicInteger();
        List<String> failures = new CopyOnWriteArrayList<>();

        class Probe implements GameAware {
            private volatile Game game;

            @Override
            public void onGameCreated(Game g) {
                this.game = g;
            }

            @Subscribe
            public void onTurn(GameEventTurnBegan event) {
                if (event.turnNumber() != atTurn || game == null || game.isGameOver()) {
                    return;
                }
                try {
                    work.accept(game, game.getPlayers().get(0));
                    ran.incrementAndGet();
                } catch (Throwable t) {
                    failures.add(t.toString());
                }
            }
        }
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks", "selvala-heart-of-the-wilds.dck"),
                                dossier),
                        SeatSpec.goldfish(new File("decks", "purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(atTurn + 2, 300, 2000), new Probe());
        assertEquals("the probe must not have thrown: " + failures, 0, failures.size());
        assertEquals("the fixture must reach turn " + atTurn + " and run the work",
                1, ran.get());
    }

    @Test
    public void predictionSurvivesSixConcurrentWorkers() throws Exception {
        // The bet-money risk (Gemini review): 6 workers predicting at once.
        // If Forge carries mutable shared state through GameCopier or the
        // phase advance, this is where it surfaces — as a thrown exception,
        // a corrupted verdict, or a hang.
        int workers = 6;
        int perWorker = 5;
        onLiveBoard(8, (game, me) -> {
        CountDownLatch startTogether = new CountDownLatch(1);
        CountDownLatch finished = new CountDownLatch(workers);
        List<String> failures = new CopyOnWriteArrayList<>();
        AtomicInteger completed = new AtomicInteger();
        AtomicInteger abandoned = new AtomicInteger();

        for (int w = 0; w < workers; w++) {
            Thread t = new Thread(() -> {
                try {
                    startTogether.await();
                    for (int i = 0; i < perWorker; i++) {
                        KillPredictor.Prediction p = KillPredictor.predictCombat(
                                game, me, pl -> game.getPlayers().indexOf(pl));
                        if (p.timedOut()) {
                            abandoned.incrementAndGet();
                        } else {
                            completed.incrementAndGet();
                        }
                    }
                } catch (Throwable e) {
                    failures.add(e.toString());
                } finally {
                    finished.countDown();
                }
            }, "predict-worker-" + w);
            t.setDaemon(true);
            t.start();
        }
        startTogether.countDown();
        try {
            assertTrue("6 concurrent predictors must all finish (no deadlock)",
                    finished.await(120, TimeUnit.SECONDS));
        } catch (InterruptedException ie) {
            throw new AssertionError(ie);
        }
        assertEquals("no worker may throw: " + failures, 0, failures.size());
        assertEquals("every prediction must be accounted for", workers * perWorker,
                completed.get() + abandoned.get());
        System.out.println("CONCURRENCY: " + completed.get() + " completed, "
                + abandoned.get() + " abandoned, of " + (workers * perWorker));
        });
    }

    @Test
    public void aPredictionThatCannotFinishIsAbandonedNotWaitedOn() throws Exception {
        // The hang guard, forced rather than hoped for: a timeout so small no
        // real copy can finish inside it stands in for the simulation that
        // never terminates. The contract under test is that the CALLER gets
        // control back on the deadline.
        onLiveBoard(8, (game, me) -> {
        long deadline = 5;

        long t0 = System.currentTimeMillis();
        KillPredictor.Prediction p = KillPredictor.predictCombat(
                game, me, pl -> game.getPlayers().indexOf(pl), deadline);
        long elapsed = System.currentTimeMillis() - t0;

        assertTrue("an unfinished prediction must report timedOut", p.timedOut());
        assertTrue("timedOut is UNKNOWN, never a kill claim", p.deadSeats().isEmpty());
        assertFalse("and never a kill", p.killsSomeone());
        // generous ceiling: what matters is that it returns near the deadline
        // rather than blocking for the full simulation
        assertTrue("caller must regain control near the deadline, took " + elapsed + "ms",
                elapsed < 2000);
        });
    }

    @Test
    public void aRealPredictionAnswersFromTheEngineNotAHeuristic() throws Exception {
        // The primitive itself: it runs, it is bounded, and it returns a
        // verdict the engine produced. (Whether that verdict is a kill
        // depends on the board; what is asserted here is that we got a real
        // answer within budget, not a guess.)
        onLiveBoard(8, (game, me) -> {
        KillPredictor.Prediction p = KillPredictor.predictCombat(
                game, me, pl -> game.getPlayers().indexOf(pl));
        assertFalse("a live board must predict within the default budget", p.timedOut());
        assertTrue("elapsed must be recorded for budget telemetry", p.elapsedMs() >= 0);
        assertEquals("kill claim and dead seats must agree",
                p.killsSomeone(), !p.deadSeats().isEmpty());
        System.out.println("PREDICT (live board): kills=" + p.killsSomeone()
                + " deadSeats=" + p.deadSeats() + " in " + p.elapsedMs() + "ms");
        });
    }
}
