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
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * PR-chi: the first cast_bounce program — Tidespout Tyrant + Sol Ring
 * (542-5034) through the CastBounceRunner. The program must deploy the
 * Aetherflux outlet from HAND as setup, resolve the zero-cost fodder
 * template against the live hand (Mox Amber), then LOOP: tap the rock,
 * cast the fodder with the Tidespout trigger OBLIGED onto the rock (bounce
 * to hand, MEASURED), recast the rock with the trigger obliged onto the
 * fodder (bounced back, MEASURED), +2 storm per iteration — to the
 * governor's lifegain target, then COMPLETE and hand back. The PayLife<50>
 * conversion downstream is the drill machinery's business and deliberately
 * NOT asserted here.
 *
 * <p>Urza comes from the COMMAND zone (the real commander object). Every
 * iteration must be MEASURED — the aborts list rides every failure message
 * so a counting-at-return phantom can never hide.
 */
public class UrzaTidespoutLoopTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class TidespoutBoardProbe implements GameAware {
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
            for (String name : List.of("Tidespout Tyrant", "Sol Ring")) {
                game.getAction().moveToPlay(card(name, p0), null, null);
            }
            for (String name : List.of("Mox Amber", "Aetherflux Reservoir")) {
                game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
            }
            for (int i = 0; i < 8; i++) {
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
    public void theCastBounceLoopStormsToTheLifegainTarget() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("urza-tidespout-stalls").toString());
        Path dossier = Path.of("decks", "urza-lord-high-artificer", "dossier");
        // COW re-copies the whole array per append — the storm-heavy Urza
        // games emit enough events to OOM the shared fork (measured, PR-pi).
        // Synchronized ArrayList keeps thread-safety with O(1) appends.
        List<ArenaEvent> events = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/urza-lord-high-artificer.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new TidespoutBoardProbe());

        List<ArenaEvent> plans = events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && "542-5034".equals(String.valueOf(e.fields().get("combo"))))
                .toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort")
                        && "542-5034".equals(String.valueOf(e.fields().get("combo"))))
                .map(e -> String.valueOf(e.fields())).toList();
        List<ArenaEvent> completes = events.stream()
                .filter(e -> e.t().equals("program_complete")
                        && "542-5034".equals(String.valueOf(e.fields().get("combo"))))
                .toList();
        long iterations = events.stream()
                .filter(e -> e.t().equals("outlet_drill")
                        && "cast_bounce".equals(String.valueOf(e.fields().get("kind"))))
                .count();

        assertTrue("the governor must plan the storm (plans=" + plans.size()
                + ") aborts=" + aborts + " events="
                + events.stream().map(ArenaEvent::t).distinct().toList(),
                !plans.isEmpty());
        assertTrue("the loop must run MEASURED cast-bounce iterations (iterations="
                + iterations + ") aborts=" + aborts, iterations >= 5);
        assertTrue("the program must COMPLETE at the lifegain target, aborts=" + aborts,
                !completes.isEmpty());
        // zero counting-at-return phantoms: every iteration above was
        // measured (spend-proof + zone-proof), so the program that completed
        // must have no aborts on its record — an abort here means a half
        // failed verification and the run should not have counted
        assertTrue("542-5034 must complete without aborts, got " + aborts,
                aborts.isEmpty());
        var f = completes.get(0).fields();
        assertTrue("completion must record the measured lifegain, got " + f,
                ((Number) f.get("life_gained")).intValue() >= 150);
    }
}
