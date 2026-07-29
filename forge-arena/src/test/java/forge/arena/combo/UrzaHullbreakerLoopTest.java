package forge.arena.combo;

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
 * PR-psi: the Hullbreaker family — combo 513-5034--46 (Hullbreaker Horror
 * + Sol Ring, the deck's single most popular Spellbook line) through the
 * same CastBounceRunner as the Tidespout family, plus the one piece of new
 * machinery this engine needs: its SpellCast trigger is a CHARM ("choose
 * up to one", MinCharmNum 0 — stock may decline it entirely or pick the
 * spell-return mode). The controller's chooseModeForAbility override picks
 * the mode that CAN TARGET the obliged card — structurally "return target
 * nonland permanent" — and the orderAndPlaySimultaneousSa seam then sets
 * the target, exactly as for Tidespout.
 *
 * <p>Scope note encoded from Ben's directive: Hullbreaker's bounce mode is
 * NONLAND permanents only; Tidespout's trigger returns ANY permanent
 * (lands included). Both engines out means two triggers per cast — one
 * sustains the loop, the surplus (unobliged, different source name) falls
 * through to stock targeting and peels the opponents' boards.
 */
public class UrzaHullbreakerLoopTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class HullbreakerBoardProbe implements GameAware {
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
            for (String name : List.of("Hullbreaker Horror", "Sol Ring")) {
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
    public void theCharmObligedBounceLoopConverts() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("urza-hullbreaker-stalls").toString());
        Path dossier = Path.of("decks", "urza-lord-high-artificer", "dossier");
        List<ArenaEvent> events = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/urza-lord-high-artificer.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new HullbreakerBoardProbe());
        UrzaTidespoutLoopTest.assertLoopConverts(events, "513-5034--46");
    }
}
