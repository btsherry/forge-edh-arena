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
 * PR-lambda: the first Urza compiled program — Power Artifact + Basalt
 * Monolith through the mana-loop interpreter. The program must SET UP (cast
 * Basalt; cast the aura PRE-TARGETED at Basalt — stock's AttachAILogic
 * would enchant anything; verify the attachment), LOOP with measured pool
 * growth (+2 per tap/untap pair — the untap asks for the REAL scripted {3},
 * Power Artifact discounts at payment), BANK to the governor's target, SINK
 * into Urza's {5}, and hand back.
 *
 * <p>Urza comes from the COMMAND zone (the real commander object — his
 * artifact-tap mana and the {5} sink are the deck's spine). Aetherflux and
 * the storm conversion downstream are stock's business after the hand-back
 * and deliberately NOT asserted here.
 */
public class UrzaManaLoopTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class ManaBoardProbe implements GameAware {
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
            for (String name : List.of("Basalt Monolith", "Power Artifact")) {
                game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
            }
            for (int i = 0; i < 7; i++) {
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
    public void theManaLoopBanksAndSinks() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("urza-manaloop-stalls").toString());
        Path dossier = Path.of("decks", "urza-lord-high-artificer", "dossier");
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/urza-lord-high-artificer.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new ManaBoardProbe());

        List<ArenaEvent> plans = events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && "4131-5149".equals(String.valueOf(e.fields().get("combo"))))
                .toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        List<ArenaEvent> completes = events.stream()
                .filter(e -> e.t().equals("program_complete")
                        && "4131-5149".equals(String.valueOf(e.fields().get("combo"))))
                .toList();
        long pairs = events.stream().filter(e -> e.t().equals("outlet_drill")).count();

        assertTrue("the governor must plan the bank (plans=" + plans.size()
                + ") events=" + events.stream().map(ArenaEvent::t).distinct().toList(),
                !plans.isEmpty());
        assertTrue("the loop must run MEASURED pairs (pairs=" + pairs
                + ") aborts=" + aborts, pairs >= 5);
        assertTrue("the program must COMPLETE its sinks, aborts=" + aborts,
                !completes.isEmpty());
        var f = completes.get(0).fields();
        assertTrue("sinks must actually fire, got " + f,
                ((Number) f.get("sinks")).intValue() >= 2);
    }
}
