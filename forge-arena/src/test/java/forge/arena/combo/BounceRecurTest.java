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
import forge.game.zone.ZoneType;

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
        private final int forests;
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        Probe(List<String> battlefield, int forests) {
            this.battlefield = battlefield;
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
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }

        private Card card(String name, Player owner) {
            return Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard(name), owner);
        }
    }

    @Test
    public void witnessSabertoothDefilerBuildsLethalCounterBoard() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("bounce-recur-stalls").toString());
        Path dossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        List<ArenaEvent> events =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        // 45 Forests = ~9 cycles of {1}{G}+{1}{G}{G}; ~7 cycles suffice for a
        // lethal counter board (base ~12 power + ~4/cycle vs a 40-life goldfish)
        Probe probe = new Probe(
                List.of("Eternal Witness", "Temur Sabertooth", "Defiler of Vigor"), 45);
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                            new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 4000), sink, probe);

        String combo = "ben-ewit-sabertooth-defiler";
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

        System.out.println("[bounce-recur] plans=" + plans.size() + " cycles=" + cycles
                + " complete=" + done.size() + " aborts=" + aborts);
        if (!done.isEmpty()) {
            System.out.println("[bounce-recur] complete=" + done.get(0).fields());
        }

        assertTrue("the runner must plan (plans=" + plans.size() + ") aborts=" + aborts,
                !plans.isEmpty());
        assertTrue("the bounce-recursion must run MEASURED cycles (cycles=" + cycles
                + ") aborts=" + aborts, cycles >= 5);
        assertTrue("the loop must build a lethal board (program_complete) aborts=" + aborts,
                !done.isEmpty());
    }
}
