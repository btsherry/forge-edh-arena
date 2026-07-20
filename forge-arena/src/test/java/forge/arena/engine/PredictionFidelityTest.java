package forge.arena.engine;

import static org.testng.AssertJUnit.assertEquals;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.google.common.eventbus.Subscribe;

import forge.ai.simulation.GameCopier;
import forge.arena.bootstrap.ArenaBootstrap;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.phase.PhaseType;
import forge.game.player.Player;

/**
 * Phase 7 diagnostic: establishes WHAT the prediction primitive actually
 * simulates, before any decision is built on top of it.
 *
 * <p>The open question is who declares attackers inside the copy.
 * {@code devAdvanceToPhase} runs {@code onPhaseBegin} for every phase it
 * passes through, so by the time the copy reaches COMBAT_DAMAGE its own
 * controllers have already declared. That means the prediction answers
 * "what happens if combat plays out from here" — NOT "what happens if I
 * alpha strike" — unless the copy's controller for our seat happens to
 * script the same attack the live pilot would.
 *
 * <p>Those are different questions, and building a decision on the wrong one
 * would be the exact mistake this phase exists to stop making. So: measure
 * it. Prints, asserts only that the measurement ran.
 */
public class PredictionFidelityTest {

    @BeforeClass
    public void bootstrap() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    private static String lifeOf(Game live, GameCopier copier) {
        StringBuilder sb = new StringBuilder();
        for (Player p : live.getPlayers()) {
            Player c = (Player) copier.find(p);
            sb.append(c == null ? "?" : c.getLife()).append(' ');
        }
        return sb.toString().trim();
    }

    @Test
    public void whatDoesTheCopyActuallySimulate() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("fidelity-stalls").toString());
        Path dossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        List<String> observations = new CopyOnWriteArrayList<>();
        List<String> failures = new CopyOnWriteArrayList<>();

        class Probe implements GameAware {
            private volatile Game game;

            @Override
            public void onGameCreated(Game g) {
                this.game = g;
            }

            @Subscribe
            public void onTurn(GameEventTurnBegan event) {
                Game live = game;
                if (live == null || live.isGameOver() || event.turnNumber() < 5
                        || event.turnNumber() > 12) {
                    return;
                }
                try {
                    Player me = live.getPlayers().get(0);
                    // ONLY our own turn: advancing on an opponent's turn
                    // simulates THEIR combat, which says nothing about ours
                    if (live.getPhaseHandler().getPlayerTurn() != me
                            || me.getCreaturesInPlay().isEmpty()) {
                        return;
                    }
                    int myPower = me.getCreaturesInPlay().stream()
                            .mapToInt(c -> Math.max(0, c.getNetPower())).sum();
                    StringBuilder before = new StringBuilder();
                    for (Player p : live.getPlayers()) {
                        before.append(p.getLife()).append(' ');
                    }

                    // (a) PASSIVE: let the copy's own controllers decide
                    GameCopier passiveCopier = new GameCopier(live);
                    Game passive = passiveCopier.makeCopy();
                    passive.getAction().checkStateEffects(true);
                    passive.getPhaseHandler().devAdvanceToPhase(PhaseType.COMBAT_DAMAGE);
                    String passiveLife = lifeOf(live, passiveCopier);

                    // (b) INJECTED: stop at declare-attackers, script our own
                    // alpha into the copy's Combat, THEN resolve to damage.
                    // This is the question we actually need answered: not
                    // "what would the AI do" but "does MY attack kill".
                    GameCopier injCopier = new GameCopier(live);
                    Game inj = injCopier.makeCopy();
                    inj.getAction().checkStateEffects(true);
                    inj.getPhaseHandler().devAdvanceToPhase(PhaseType.COMBAT_DECLARE_ATTACKERS);
                    Player injMe = (Player) injCopier.find(me);
                    forge.game.combat.Combat combat = inj.getCombat();
                    int injected = 0;
                    if (combat != null && injMe != null) {
                        Player victim = null;
                        for (Player p : inj.getPlayers()) {
                            if (p != injMe && !p.hasLost()) {
                                victim = p;
                                break;
                            }
                        }
                        for (forge.game.card.Card c : injMe.getCreaturesInPlay()) {
                            if (victim != null
                                    && forge.game.combat.CombatUtil.canAttack(c, victim)) {
                                combat.addAttacker(c, victim);
                                injected++;
                            }
                        }
                    }
                    inj.getPhaseHandler().devAdvanceToPhase(PhaseType.COMBAT_DAMAGE);
                    String injLife = lifeOf(live, injCopier);

                    observations.add("t" + event.turnNumber()
                            + " creatures=" + me.getCreaturesInPlay().size()
                            + " power=" + myPower
                            + " before=[" + before.toString().trim() + "]"
                            + "  passive=[" + passiveLife + "]"
                            + "  injected(" + injected + " attackers)=[" + injLife + "]");
                } catch (Throwable t) {
                    failures.add("t" + event.turnNumber() + ": " + t);
                }
            }
        }

        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks", "selvala-heart-of-the-wilds.dck"),
                                dossier),
                        SeatSpec.goldfish(new File("decks", "purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(14, 300, 2000), new Probe());

        System.out.println("=== PREDICTION FIDELITY (own turns only) ===");
        observations.forEach(o -> System.out.println("  " + o));
        failures.forEach(f -> System.out.println("  FAIL " + f));
        assertEquals("the copy must never throw during a combat advance: " + failures,
                0, failures.size());
    }
}
