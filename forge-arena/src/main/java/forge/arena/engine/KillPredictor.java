package forge.arena.engine;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import forge.ai.simulation.GameCopier;
import forge.game.Game;
import forge.game.phase.PhaseType;
import forge.game.player.Player;

/**
 * Phase 7 — a REAL prediction, not a proxy (docs/PHASE-7-PLAN.md).
 *
 * <p>Asks the rules engine a question instead of approximating it: copy the
 * live game, advance the copy through combat, and read off who died. No
 * heuristic score, no weights, no haste-card hunting — the engine declares
 * the attackers, the engine declares the blockers, the engine assigns the
 * damage, and the answer is whatever actually happened.
 *
 * <p>This generalizes the one part of the pilot that already works: the
 * loop-to-lethal drill proves an activation on a {@code GameCopier} copy
 * before arming, and the drill converts. Everything built on hand-written
 * predicates converts worse in direct proportion to how many predicates sit
 * between the combo firing and the opponent dying.
 *
 * <p><b>Who declares blockers?</b> The opponents do — inside the copy, via
 * their own controllers. In a batch arena those controllers are the same
 * Forge AI that will block in the real game, so the prediction is not an
 * approximation OF the opponent, it IS the opponent. That is strictly more
 * faithful than worst-case blocker arithmetic (PR-34), which assumes every
 * opponent always blocks optimally with its biggest creatures.
 *
 * <p><b>Every prediction is time-boxed, and that is not optional.</b> These
 * decks exist to assemble infinite loops. Simulating a board that contains a
 * live loop gives the engine no reason to terminate, so an unbounded
 * prediction is an unbounded hang — and in a 6-worker batch it takes a
 * worker with it. On expiry the caller gets {@link Prediction#timedOut()}
 * and is expected to fall back to the cheap read-model: a slow answer is
 * worth nothing, but a missing answer must never be worth a dead batch.
 */
public final class KillPredictor {

    /**
     * Default time box. The measured cost of a copy advanced to
     * COMBAT_DAMAGE on live boards is 37-44 ms (turn 6 through turn 12,
     * 6 through 14 permanents), of which ~17 ms is fixed copy overhead
     * rather than board-size scaling. 250 ms is ~6x the measured worst
     * case: comfortably out of the way of honest work, and short enough
     * that a hung simulation costs a quarter second rather than a batch.
     *
     * <p><b>That budget was measured in the wrong environment.</b> 35 ms came
     * from a 2-player fixture on one thread. In a real 4-player batch under 6
     * workers the same prediction ran 176-260 ms and timed out 75% of the
     * time — a bigger game state to copy, and six workers contending for
     * cores. Overridable via {@code -Darena.predict.timeout.ms} so the true
     * distribution can be measured rather than truncated by the cap.
     */
    public static final long DEFAULT_TIMEOUT_MS =
            Long.getLong("arena.predict.timeout.ms", 250);

    /**
     * The engine's answer.
     *
     * @param killsSomeone at least one opponent died in the simulated combat
     * @param deadSeats    seat indices of the opponents that died
     * @param timedOut     the simulation was abandoned — verdict UNKNOWN, not
     *                     "no". Callers must fall back, never treat as false.
     * @param elapsedMs    wall clock actually spent, for budget telemetry
     */
    public record Prediction(boolean killsSomeone, List<Integer> deadSeats, boolean timedOut,
            long elapsedMs) {

        public static Prediction none(long elapsedMs) {
            return new Prediction(false, List.of(), false, elapsedMs);
        }

        public static Prediction abandoned(long elapsedMs) {
            return new Prediction(false, List.of(), true, elapsedMs);
        }
    }

    private KillPredictor() {
    }

    /**
     * Would attacking with EVERYTHING kill anyone? Must be called while the
     * game is already at declare-attackers (i.e. from inside a
     * {@code declareAttackers} seam).
     *
     * <p><b>Why the phase requirement is not an inconvenience but the whole
     * design.</b> The obvious approach — copy the game and
     * {@code devAdvanceToPhase(COMBAT_DAMAGE)} — was measured and does not
     * answer our question. That advance runs {@code onPhaseBegin} for every
     * phase it crosses, so the COPY's own controllers declare the attack, and
     * the verdict describes what stock AI would have done. Measured on live
     * Selvala boards: at turn 12, holding 9 creatures and 29 power, the
     * passive simulation attacked for zero.
     *
     * <p>Injecting our own attackers AFTER that advance does not work either
     * — also measured, also zero: by the time the phase has begun the
     * declaration is resolved and further attackers are simply illegal.
     *
     * <p>So the copy must be taken while the live game is ALREADY at
     * declare-attackers, with the declaration still open. Then we script the
     * alpha into the copy's own {@link forge.game.combat.Combat} and let the
     * engine resolve blockers and damage from there. The result describes
     * OUR attack, which is the only thing worth predicting.
     */
    public static Prediction predictAlphaStrike(Game game, Player attacker,
            java.util.function.ToIntFunction<Player> seatOf, long timeoutMs) {
        long started = System.currentTimeMillis();
        AtomicReference<List<Integer>> dead = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();

        Thread worker = new Thread(() -> {
            try {
                GameCopier copier = new GameCopier(game);
                Game copy = copier.makeCopy();
                copy.getAction().checkStateEffects(true);
                Player me = (Player) copier.find(attacker);
                forge.game.combat.Combat combat = copy.getCombat();
                if (me == null || combat == null) {
                    return; // nothing to script — reported as no-answer below
                }
                // Spread the alpha the way the live pilot would: lowest life
                // first, so the prediction matches the attack it is
                // predicting rather than some other attack.
                List<Player> victims = new ArrayList<>();
                for (Player p : copy.getPlayers()) {
                    if (p != me && !p.hasLost()) {
                        victims.add(p);
                    }
                }
                victims.sort(java.util.Comparator.comparingInt(Player::getLife));
                int declared = 0;
                for (forge.game.card.Card c : me.getCreaturesInPlay()) {
                    for (Player victim : victims) {
                        if (forge.game.combat.CombatUtil.canAttack(c, victim)) {
                            combat.addAttacker(c, victim);
                            declared++;
                            break;
                        }
                    }
                }
                if (declared == 0) {
                    dead.set(List.of());
                    return;
                }
                copy.getPhaseHandler().devAdvanceToPhase(PhaseType.COMBAT_DAMAGE);
                List<Integer> died = new ArrayList<>();
                for (Player original : game.getPlayers()) {
                    if (original == attacker) {
                        continue;
                    }
                    Player copied = (Player) copier.find(original);
                    if (copied != null && (copied.hasLost() || copied.getLife() <= 0)) {
                        died.add(seatOf.applyAsInt(original));
                    }
                }
                dead.set(died);
            } catch (Throwable t) {
                failure.set(t);
            }
        }, "arena-predict-alpha");
        worker.setDaemon(true);
        worker.start();
        try {
            worker.join(timeoutMs);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            return Prediction.abandoned(System.currentTimeMillis() - started);
        }
        long elapsed = System.currentTimeMillis() - started;
        if (worker.isAlive()) {
            worker.interrupt();
            return Prediction.abandoned(elapsed);
        }
        if (failure.get() != null || dead.get() == null) {
            return Prediction.abandoned(elapsed);
        }
        List<Integer> died = dead.get();
        return died.isEmpty()
                ? Prediction.none(elapsed)
                : new Prediction(true, List.copyOf(died), false, elapsed);
    }

    /**
     * Would attacking right now kill anyone? Advances a COPY through combat
     * and reports who is dead on the other side. The live game is never
     * touched.
     *
     * @param seatOf maps a live player to its arena seat index
     */
    public static Prediction predictCombat(Game game, Player attacker,
            java.util.function.ToIntFunction<Player> seatOf) {
        return predictCombat(game, attacker, seatOf, DEFAULT_TIMEOUT_MS);
    }

    public static Prediction predictCombat(Game game, Player attacker,
            java.util.function.ToIntFunction<Player> seatOf, long timeoutMs) {
        long started = System.currentTimeMillis();
        AtomicReference<List<Integer>> dead = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();

        // The copy is built on the worker thread too. GameCopier reads the
        // live game, which is safe because the calling thread is blocked
        // here for the duration — but the ADVANCE is the part that can spin
        // forever, and it must be abandonable.
        Thread worker = new Thread(() -> {
            try {
                GameCopier copier = new GameCopier(game);
                Game copy = copier.makeCopy();
                copy.getAction().checkStateEffects(true);
                copy.getPhaseHandler().devAdvanceToPhase(PhaseType.COMBAT_DAMAGE);
                List<Integer> died = new ArrayList<>();
                for (Player original : game.getPlayers()) {
                    if (original == attacker) {
                        continue;
                    }
                    Player copied = (Player) copier.find(original);
                    if (copied != null && (copied.hasLost() || copied.getLife() <= 0)) {
                        died.add(seatOf.applyAsInt(original));
                    }
                }
                dead.set(died);
            } catch (Throwable t) {
                failure.set(t);
            }
        }, "arena-predict");
        // daemon: an abandoned prediction must never hold the JVM open
        worker.setDaemon(true);
        worker.start();
        try {
            worker.join(timeoutMs);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            return Prediction.abandoned(System.currentTimeMillis() - started);
        }
        long elapsed = System.currentTimeMillis() - started;
        if (worker.isAlive()) {
            // Ask it to stop, then walk away. A simulation deep in engine
            // work may never observe the interrupt; the thread is a daemon
            // on a throwaway copy, so leaking it costs CPU but corrupts
            // nothing that the live game can see.
            worker.interrupt();
            return Prediction.abandoned(elapsed);
        }
        if (failure.get() != null) {
            // A prediction that threw is a prediction we do not have. Same
            // contract as a timeout: unknown, fall back — never "no".
            return Prediction.abandoned(elapsed);
        }
        List<Integer> died = dead.get();
        return died == null || died.isEmpty()
                ? Prediction.none(elapsed)
                : new Prediction(true, List.copyOf(died), false, elapsed);
    }
}
