package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.ComboAwareLobbyPlayer;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;

/**
 * PR-37 (Phase 6 A3, the loop-to-lethal executor): a single-target outlet
 * must be activated REPEATEDLY until the table is dead — never fired once
 * (the playbook's loop-to-lethal law). One activation per priority window,
 * so interaction lands between iterations; the drill re-resolves the outlet
 * every pass and stops honestly when it is gone, unpayable, or everyone is
 * dead. Zero combo artifacts: the drill is pure conversion machinery.
 */
public class LethalDrillTest {

    private static Path emptyDossier;

    @BeforeClass
    public void bootstrap() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        emptyDossier = Files.createTempDirectory("lethal-drill");
        Files.writeString(emptyDossier.resolve("combos.json"), """
                {"schema": "arena.combos/1", "deck_hash": "x", "combos": []}""");
        Files.writeString(emptyDossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"x\",\"status\":{},\"versions\":{}}");
    }

    /** Inject a Walking Ballista with 50 counters and ARM the drill at t3. */
    static final class DrillProbe implements GameAware {
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        @Override
        public void onGameCreated(Game game) {
            this.game = game;
        }

        @Subscribe
        public void onTurn(GameEventTurnBegan event) {
            if (event.turnNumber() < 3 || !applied.compareAndSet(false, true)) {
                return;
            }
            Player p0 = game.getPlayers().get(0);
            game.getTriggerHandler().setSuppressAllTriggers(true);
            forge.game.card.Card ballista = forge.game.card.Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard("Walking Ballista"), p0);
            game.getAction().moveToPlay(ballista, null, null);
            ballista.setSickness(false);
            ballista.addCounterInternal(forge.game.card.CounterEnumType.P1P1, 50, p0, false,
                    null, null);
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
            ((ComboAwareLobbyPlayer.ComboAwareController) p0.getController()).armDrill(
                    new ComboAwareLobbyPlayer.ComboAwareController.DrillOrder(
                            "Walking Ballista", "remove a +1/+1 counter"));
        }
    }

    @Test
    public void armedDrillPingsTheTableToDeath() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("lethal-drill-stalls").toString());
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        java.util.function.Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                        new File("decks", "giada-font-of-hope.dck"), emptyDossier),
                        SeatSpec.goldfish(new File("decks", "purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(14, 300, 2000), sink, new DrillProbe());

        long drills = events.stream().filter(e -> e.t().equals("outlet_drill")).count();
        assertTrue("the drill must iterate to lethal, not fire once (got " + drills + ")",
                drills >= 40);
        assertEquals("the drill must CLOSE the game (got " + result.type() + ", "
                + result.winCondition() + ", turns=" + result.turns() + ")",
                ArenaGameResult.ResultType.WIN, result.type());
        assertEquals(0, result.winnerSeat());
        assertTrue("a 40-life kill at 1 damage per window must land promptly (turns="
                + result.turns() + ")", result.turns() <= 6);
    }
}
