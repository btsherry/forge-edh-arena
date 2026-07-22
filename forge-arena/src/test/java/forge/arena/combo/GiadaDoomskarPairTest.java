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
 * PR-eta: the first compiled pairing — Doomskar + Flawless Maneuver,
 * respond-on-stack — must fire, protect, and be MEASURED doing both. The
 * epsilon batch showed the legacy PairedPlay archetype entering twice in 30
 * games and never once completing its protect stage (a silent modal-cast
 * failure dangled the armed protection forever); the compiled runner aborts
 * loudly at every state and verifies survival on the live board.
 *
 * <p>Board forced: Giada moved from the COMMAND zone (the real commander
 * object — Flawless Maneuver's free cast is gated on IsCommander), own
 * angels worth protecting, an opposing board past the program's threat
 * floor, both pair cards in hand, lands for the wipe.
 */
public class GiadaDoomskarPairTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class PairBoardProbe implements GameAware {
        private final boolean commanderOut;
        private final int plains;
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        /**
         * @param commanderOut move the REAL Giada from the command zone (a
         *                     fresh copy would not satisfy Card.IsCommander
         *                     for the free Maneuver); false = the retail-cost
         *                     path the verify panel showed the first test
         *                     was masking
         */
        PairBoardProbe(boolean commanderOut, int plains) {
            this.commanderOut = commanderOut;
            this.plains = plains;
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
            Player p1 = game.getPlayers().get(1);
            game.getTriggerHandler().setSuppressAllTriggers(true);
            if (commanderOut) {
                for (forge.game.card.Card c : List.copyOf(p0.getCardsIn(ZoneType.Command))) {
                    if (c.getName().equals("Giada, Font of Hope")) {
                        game.getAction().moveToPlay(c, null, null);
                    }
                }
            }
            for (String name : List.of("Lyra Dawnbringer", "Serra Angel")) {
                game.getAction().moveToPlay(card(name, p0), null, null);
            }
            // opposing threats past the program's floor (6): 2x Serra = 8
            for (int i = 0; i < 2; i++) {
                game.getAction().moveToPlay(card("Serra Angel", p1), null, null);
            }
            for (String name : List.of("Doomskar", "Flawless Maneuver")) {
                game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
            }
            for (int i = 0; i < plains; i++) {
                game.getAction().moveToPlay(card("Plains", p0), null, null);
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
    public void theDoomskarPairFiresProtectsAndIsMeasured() throws Exception {
        // free-cast path: Giada controlled, 6 lands cover the wipe alone
        runScenario(new PairBoardProbe(true, 6));
    }

    /**
     * The verify panel's blocker scenario: no commander, so the free cast is
     * dead and the pair needs {3}{W}{W} + {2}{W} JOINTLY. With the old
     * independent preflight this cast Doomskar off the shield's mana and
     * swept its own board; the joint check must instead hold the pair (or
     * retry) until both fit — and then complete at retail cost.
     */
    @Test
    public void theRetailCostPathNeverFiresUnprotected() throws Exception {
        runScenario(new PairBoardProbe(false, 9));
    }

    private void runScenario(PairBoardProbe probe) throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("doomskar-pair-stalls").toString());
        Path dossier = Path.of("decks", "giada-font-of-hope", "dossier");
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/giada-font-of-hope.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/urza-lord-high-artificer.dck"))),
                42L, new ArenaLimits(12, 400, 2000), sink, probe);

        long entered = events.stream()
                .filter(e -> e.t().equals("pairing_entered")
                        && "pp-doomskar-flawless-maneuver"
                                .equals(String.valueOf(e.fields().get("pairing"))))
                .count();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("pairing_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        List<ArenaEvent> completes = events.stream()
                .filter(e -> e.t().equals("pairing_complete")).toList();

        assertTrue("the compiled pairing must enter (entered=" + entered
                + ") events=" + events.stream().map(ArenaEvent::t).distinct().toList(),
                entered >= 1);
        assertTrue("the pairing must COMPLETE with measured survival, aborts="
                + aborts, !completes.isEmpty());

        // the measured contract: our creatures preserved, every opponent
        // creature swept — read back from the completion event itself
        var f = completes.get(0).fields();
        int ownBefore = ((Number) f.get("own_before")).intValue();
        int ownAfter = ((Number) f.get("own_after")).intValue();
        int oppBefore = ((Number) f.get("opp_before")).intValue();
        int oppAfter = ((Number) f.get("opp_after")).intValue();
        assertTrue("own board must survive the wipe (own " + ownBefore + "->"
                + ownAfter + ")", ownAfter >= ownBefore && ownBefore >= 2);
        assertTrue("opponents must be reduced (opp " + oppBefore + "->" + oppAfter
                + ")", oppBefore >= 2 && oppAfter < oppBefore);
        // no unprotected resolution, ever: a wipe that ate its own board
        // would fail the preserved check above, and a shield that never hit
        // the stack aborts as protection_cast_failed
        assertTrue("no pairing may abort as unprotected/cast-failed: " + aborts,
                aborts.stream().noneMatch(a -> a.contains("unprotected")
                        || a.contains("protection_cast_failed")));

        // one path: the legacy PairedPlay line must never fire for this pair
        long legacy = events.stream()
                .filter(e -> e.t().equals("line_entered")
                        && "pp-doomskar-flawless-maneuver"
                                .equals(String.valueOf(e.fields().get("combo"))))
                .count();
        assertTrue("legacy PairedPlay must not run a compiled pair (saw "
                + legacy + ")", legacy == 0);
    }
}
