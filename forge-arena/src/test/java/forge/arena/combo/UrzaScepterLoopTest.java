package forge.arena.combo;

import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
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
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * PR-mu: the deck's PRIMARY line — Isochron Scepter + Dramatic Reversal
 * through the float_then_copy mana-loop shape. The program must cast the
 * Scepter with the Reversal steered into its imprint trigger (the PR-27a
 * choice seam), float the artifact mana, loop with MEASURED net-positive
 * iterations (Ben's secondary requirement: rocks producing 3+, pay {2},
 * net >= 1), bank, sink into Urza's {5}, and hand back.
 *
 * <p>Board forced: Urza from the COMMAND zone, Scepter + Reversal in HAND
 * (the imprint takes it from hand — the ordering the program encodes),
 * Sol Ring + Mana Vault on the battlefield (production 5, net +3/iter).
 */
public class UrzaScepterLoopTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class ScepterBoardProbe implements GameAware {
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

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
            for (forge.game.card.Card c : List.copyOf(p0.getCardsIn(ZoneType.Command))) {
                if (c.getName().equals("Urza, Lord High Artificer")) {
                    game.getAction().moveToPlay(c, null, null);
                }
            }
            for (String name : List.of("Isochron Scepter", "Dramatic Reversal")) {
                game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
            }
            for (String name : List.of("Sol Ring", "Mana Vault")) {
                game.getAction().moveToPlay(card(name, p0), null, null);
            }
            for (int i = 0; i < 6; i++) {
                game.getAction().moveToPlay(card("Island", p0), null, null);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }

        private forge.game.card.Card card(String name, Player owner) {
            return forge.game.card.Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard(name), owner);
        }
    }

    @Test
    public void theScepterLoopImprintsFloatsBanksAndSinks() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("urza-scepter-stalls").toString());
        Path dossier = Path.of("decks", "urza-lord-high-artificer", "dossier");
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/urza-lord-high-artificer.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new ScepterBoardProbe());

        List<ArenaEvent> plans = events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && "4821-5261".equals(String.valueOf(e.fields().get("combo"))))
                .toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        List<ArenaEvent> completes = events.stream()
                .filter(e -> e.t().equals("program_complete")
                        && "4821-5261".equals(String.valueOf(e.fields().get("combo"))))
                .toList();
        long iters = events.stream()
                .filter(e -> e.t().equals("outlet_drill")
                        && "copy_iteration".equals(String.valueOf(e.fields().get("kind"))))
                .count();

        assertTrue("the imprint must land and the governor must plan (plans="
                + plans.size() + ") aborts=" + aborts + " events="
                + events.stream().map(ArenaEvent::t).distinct().toList(),
                !plans.isEmpty());
        assertTrue("the loop must run MEASURED net-positive iterations (iters="
                + iters + ") aborts=" + aborts, iters >= 5);
        assertTrue("the program must COMPLETE its sinks, aborts=" + aborts,
                !completes.isEmpty());
        var f = completes.get(0).fields();
        assertTrue("sinks must actually fire, got " + f,
                ((Number) f.get("sinks")).intValue() >= 2);
    }
}
