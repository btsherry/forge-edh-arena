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
import forge.arena.engine.ArenaGameResult;
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
 * cast_recur Body C — the Grinning Ignus self-recast, converting each ETB
 * through Purphoros's on-board damage (the first non-Aetherflux outlet). The
 * loop product is directly measured by opponent-life delta. Two refund
 * sources, same runner body: Steam-Kin (counter cycle, the Spellbook combo
 * 411-3101) and Birgi (per-cast mana, Ben's paper line). This test forces
 * the Steam-Kin board (the tracked Spellbook combo 411-3101) and asserts the loop
 * runs measured iterations and kills the table.
 */
public class PurphorosCastRecurTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class RecurBoardProbe implements GameAware {
        private final boolean useBirgi;
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        RecurBoardProbe(boolean useBirgi) {
            this.useBirgi = useBirgi;
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
            // Purphoros from the command zone (the real commander — the
            // outlet), plus Birgi (per-cast refund) and Grinning Ignus (the
            // recur card) on the battlefield, and enough red to prime.
            for (forge.game.card.Card c : List.copyOf(p0.getCardsIn(ZoneType.Command))) {
                if (c.getName().equals("Purphoros, God of the Forge")) {
                    game.getAction().moveToPlay(c, null, null);
                }
            }
            if (useBirgi) {
                // Ben's paper line — Birgi's per-cast {R} makes the recast
                // break-even every single cast (no counter cycle)
                game.getAction().moveToPlay(card("Birgi, God of Storytelling", p0), null, null);
            } else {
                forge.game.card.Card steamKin = card("Runaway Steam-Kin", p0);
                game.getAction().moveToPlay(steamKin, null, null);
                steamKin.addCounterInternal(forge.game.card.CounterEnumType.P1P1, 3, p0, false,
                        null, null);
            }
            game.getAction().moveToPlay(card("Grinning Ignus", p0), null, null);
            for (int i = 0; i < 6; i++) {
                game.getAction().moveToPlay(card("Mountain", p0), null, null);
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
    public void theIgnusSteamKinLoopKillsTheTable() throws Exception {
        runVariant(false, "411-3101");
    }

    @Test
    public void theIgnusBirgiLoopKillsTheTable() throws Exception {
        runVariant(true, "ben-ignus-birgi");
    }

    private void runVariant(boolean useBirgi, String comboId) throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("purph-castrecur-stalls").toString());
        Path dossier = Path.of("decks", "purphoros-god-of-the-forge", "dossier");
        List<ArenaEvent> events = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/purphoros-god-of-the-forge.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new RecurBoardProbe(useBirgi));

        List<ArenaEvent> plans = events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && comboId.equals(String.valueOf(e.fields().get("combo"))))
                .toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        long iters = events.stream()
                .filter(e -> e.t().equals("outlet_drill")
                        && "cast_recur".equals(String.valueOf(e.fields().get("kind"))))
                .count();
        assertTrue("the governor must plan (plans=" + plans.size() + ") events="
                + events.stream().map(ArenaEvent::t).distinct().toList(), !plans.isEmpty());
        assertTrue("the loop must run MEASURED cast_recur iterations (iters="
                + iters + ") aborts=" + aborts, iters >= 5);
        // the lethal final cast ends the game before program_complete can
        // fire (the mana-loop lesson): the WIN is the ground truth, asserted
        // on the engine result — cast_recur's on-board outlet converting
        // gamestate to a kill, no library playout, no Aetherflux.
        assertTrue("the loop must CONVERT to an engine win for seat 0, got "
                + result.type() + "/" + result.winnerName() + " aborts=" + aborts,
                result.type() == ArenaGameResult.ResultType.WIN
                        && result.winnerSeat() == 0);
    }
}
