package forge.arena.combo;

import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;

/**
 * Target C — the mana-funded bounce/ETB-recursion sink (BounceRecurRunner).
 * C1 flagship: Eternal Witness + Temur Sabertooth + Defiler of Vigor. Each
 * cycle Sabertooth ({1}{G}) bounces the Witness (steered choice), we recast it
 * ({1}{G}{G}), and Defiler's on-cast trigger puts a +1/+1 counter on every
 * creature we control -> the board grows unbounded -> lethal. Fuelled here by a
 * pile of Forests (in a real game, by Selvala's infinite mana loop).
 */
public class BounceRecurTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class Probe implements GameAware {
        private final List<String> battlefield;
        private final List<String> opponentBattlefield;
        private final int forests;
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        Probe(List<String> battlefield, int forests) {
            this(battlefield, List.of(), forests);
        }

        Probe(List<String> battlefield, List<String> opponentBattlefield, int forests) {
            this.battlefield = battlefield;
            this.opponentBattlefield = opponentBattlefield;
            this.forests = forests;
        }

        @Override
        public void onGameCreated(Game game) {
            this.game = game;
        }

        @Subscribe
        public void onTurn(GameEventTurnBegan event) {
            if (event.turnNumber() < 4 || !applied.compareAndSet(false, true)) {
                return;
            }
            Player p0 = game.getPlayers().get(0);
            game.getTriggerHandler().setSuppressAllTriggers(true);
            for (String name : battlefield) {
                Card c = game.getAction().moveToPlay(card(name, p0), null, null);
                c.setSickness(false);
            }
            for (int i = 0; i < forests; i++) {
                game.getAction().moveToPlay(card("Forest", p0), null, null);
            }
            if (!opponentBattlefield.isEmpty() && game.getPlayers().size() > 1) {
                Player opp = game.getPlayers().get(1);
                for (String name : opponentBattlefield) {
                    game.getAction().moveToPlay(card(name, opp), null, null);
                }
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }

        private Card card(String name, Player owner) {
            return Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard(name), owner);
        }
    }

    private List<ArenaEvent> run(String label, Probe probe) throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("bounce-recur-" + label + "-stalls").toString());
        Path dossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        List<ArenaEvent> events =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                            new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 4000), sink, probe);
        return events;
    }

    /** Assert the bounce-recursion RECOGNISES the combo and runs measured cycles.
     * requireComplete additionally demands the payoff reached its terminal. */
    private void assertRuns(String label, List<ArenaEvent> events, String combo,
            int minCycles, boolean requireComplete) {
        var plans = events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && combo.equals(String.valueOf(e.fields().get("combo")))).toList();
        long cycles = events.stream()
                .filter(e -> e.t().equals("outlet_drill")
                        && "bounce_recur".equals(String.valueOf(e.fields().get("kind")))).count();
        var done = events.stream()
                .filter(e -> e.t().equals("program_complete")
                        && combo.equals(String.valueOf(e.fields().get("combo")))).toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        System.out.println("[" + label + "] plans=" + plans.size() + " cycles=" + cycles
                + " complete=" + done.size() + " aborts=" + aborts);
        assertTrue("[" + label + "] runner must plan, aborts=" + aborts, !plans.isEmpty());
        assertTrue("[" + label + "] must run MEASURED cycles (cycles=" + cycles + ") aborts="
                + aborts, cycles >= minCycles);
        if (requireComplete) {
            assertTrue("[" + label + "] must reach terminal (program_complete) aborts=" + aborts,
                    !done.isEmpty());
        }
    }

    /** C1 (DIRECT KILL) — E-Wit + Sabertooth + Defiler -> lethal counter board. */
    @Test
    public void witnessSabertoothDefilerBuildsLethalCounterBoard() throws Exception {
        var events = run("c1-defiler", new Probe(
                List.of("Eternal Witness", "Temur Sabertooth", "Defiler of Vigor"), 45));
        assertRuns("c1-defiler", events, "ben-ewit-sabertooth-defiler", 5, true);
    }

    /** C2 (draw) — E-Wit + Sabertooth + The Great Henge draws a card per cycle. */
    @Test
    public void witnessSabertoothGreatHengeDrawsPerCycle() throws Exception {
        var events = run("c2-henge", new Probe(
                List.of("Eternal Witness", "Temur Sabertooth", "The Great Henge"), 60));
        // hand_size terminates at the library floor (~80 draws) — too slow to
        // reach in a gate; prove the draw loop RUNS and measures hand growth
        assertRuns("c2-henge", events, "ben-ewit-sabertooth-henge", 5, false);
    }

    /** C3 (removal) — Kogla + Sabertooth: recast Kogla fights an opponent creature. */
    @Test
    public void koglaSabertoothFightsOpponentCreatures() throws Exception {
        var events = run("c3-kogla", new Probe(
                List.of("Kogla, the Titan Ape", "Temur Sabertooth"),
                List.of("Grizzly Bears", "Grizzly Bears", "Grizzly Bears",
                        "Grizzly Bears", "Grizzly Bears"),
                40));
        // clears the seeded opponent creatures, then completes (opponents_cleared)
        assertRuns("c3-kogla", events, "ben-kogla-sabertooth", 2, false);
    }
}
