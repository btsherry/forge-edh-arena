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
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;

/**
 * PR-34 (research adoption; the long-200 finding: fire→win 25%,
 * BANK_AND_HOLD the most common post-fire route, win-turn median 31): the
 * continuous lethal-check at every own combat. When worst-case combat math
 * — opponents block and fully absorb our biggest attackers — still
 * GUARANTEES a kill, the pilot forces the alpha, combo or no combo. Needs
 * ZERO artifacts: the dossier here has no combos at all.
 */
public class LethalAlphaTest {

    private static Path emptyDossier;

    @BeforeClass
    public void bootstrap() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        emptyDossier = Files.createTempDirectory("lethal-alpha");
        Files.writeString(emptyDossier.resolve("combos.json"), """
                {"schema": "arena.combos/1", "deck_hash": "x", "combos": []}""");
        Files.writeString(emptyDossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"x\",\"status\":{},\"versions\":{}}");
    }

    /** Inject N Terra Stompers (8/8, no sickness) onto seat 0 at turn 3. */
    static final class BoardProbe implements GameAware {
        private final int stompers;
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        BoardProbe(int stompers) {
            this.stompers = stompers;
        }

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
            for (int i = 0; i < stompers; i++) {
                forge.game.card.Card card = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard("Terra Stomper"), p0);
                game.getAction().moveToPlay(card, null, null);
                card.setSickness(false);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }
    }

    private ArenaGameResult play(int stompers, int turnCap, List<ArenaEvent> events)
            throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("lethal-alpha-stalls").toString());
        java.util.function.Consumer<ArenaEvent> sink = events::add;
        return EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                        new File("decks", "giada-font-of-hope.dck"), emptyDossier),
                        SeatSpec.goldfish(new File("decks", "purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(turnCap, 300, 2000), sink, new BoardProbe(stompers));
    }

    @Test
    public void guaranteedBoardForcesTheAlphaAndWinsWithZeroArtifacts() throws Exception {
        // 8 Stompers = 64 power; worst case two absorbed leaves 48 >= 40
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        ArenaGameResult result = play(8, 14, events);
        long alphas = events.stream().filter(e -> e.t().equals("lethal_alpha")).count();
        assertTrue("the guaranteed board must trigger the lethal alpha; events: "
                + events.stream().map(ArenaEvent::t).toList(), alphas >= 1);
        assertEquals("the alpha must CLOSE the game (got " + result.type()
                + ", " + result.winCondition() + ", turns=" + result.turns() + ")",
                ArenaGameResult.ResultType.WIN, result.type());
        assertEquals(0, result.winnerSeat());
        assertTrue("a guaranteed kill must be taken promptly, not ground out (turns="
                + result.turns() + ")", result.turns() <= 7);
    }

    @Test
    public void insufficientBoardStaysSilent() throws Exception {
        // 2 Stompers = 16 power vs 40 life: no guarantee inside a 4-turn
        // window, stock combat untouched (the inertness half). The first
        // version of this test ran 14 turns and FAILED correctly: natural
        // attrition dropped the opponent low enough that 16 power BECAME a
        // guaranteed kill and the check fired — the window, not the check,
        // was the bug.
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        play(2, 4, events);
        assertEquals("no guarantee -> no forced alpha", 0,
                events.stream().filter(e -> e.t().equals("lethal_alpha")).count());
    }
}
