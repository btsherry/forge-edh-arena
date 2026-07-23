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
 * PR-kappa: the Land Tax + Scroll Rack engine program must SET UP and CYCLE
 * — measured, not narrated. Stock is triple-broken here (Land Tax cast at
 * turns 15/15/30 across 60 games, Scroll Rack never cast at all thanks to
 * AI:RemoveDeck:All, zero activations) — so every event this test asserts
 * is pilot-delivered, and the Scroll Rack CAST doubles as the build-time
 * check that AI:RemoveDeck does not gate our direct cast path.
 *
 * <p>Board forced: our lands kept BELOW an opponent's (the Tax condition
 * and the engine's shuffle gate), both pieces plus spare basics in hand.
 */
public class GiadaEngineTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class EngineBoardProbe implements GameAware {
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
            Player p1 = game.getPlayers().get(1);
            game.getTriggerHandler().setSuppressAllTriggers(true);
            for (String name : List.of("Land Tax", "Scroll Rack", "Plains", "Plains")) {
                game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
            }
            for (int i = 0; i < 3; i++) {
                game.getAction().moveToPlay(card("Plains", p0), null, null);
            }
            // the condition: an opponent with clearly more lands
            for (int i = 0; i < 8; i++) {
                game.getAction().moveToPlay(card("Island", p1), null, null);
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
    public void theEngineSetsUpAndCycles() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("engine-stalls").toString());
        Path dossier = Path.of("decks", "giada-font-of-hope", "dossier");
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/giada-font-of-hope.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/urza-lord-high-artificer.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new EngineBoardProbe());

        // spell_cast events belong to the BATCH recorder, not the pilot
        // sink — a completed cycle transitively proves both casts (the
        // cycle's own gates require both pieces on the battlefield), the
        // activation, the exile choice, and the measurement, so the cycle
        // IS the assertion. It also proves AI:RemoveDeck:All does not gate
        // our direct cast path (stock never plays Scroll Rack at all).
        List<ArenaEvent> cycles = events.stream()
                .filter(e -> e.t().equals("engine_cycle")).toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("engine_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        assertTrue("the engine must complete at least one MEASURED cycle,"
                + " aborts=" + aborts, !cycles.isEmpty());
        int totalSwapped = cycles.stream()
                .mapToInt(e -> ((Number) e.fields().get("swapped")).intValue()).sum();
        assertTrue("cycles must actually swap cards (total=" + totalSwapped
                + " across " + cycles.size() + " cycles)", totalSwapped >= 2);
        assertTrue("no swap mismatches or unreadable programs: " + aborts,
                aborts.stream().noneMatch(a -> a.contains("swap_mismatch")
                        || a.contains("program_unreadable")));
    }
}
