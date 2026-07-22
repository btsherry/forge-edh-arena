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
 * PR-72: the Heliod + Walking Ballista loop must SUSTAIN, not fire once.
 *
 * <p>A 120-game batch fires this combo about twice, so a batch is a terrible
 * instrument for a deterministic claim. This forces the board instead and
 * asserts the property directly.
 *
 * <p>Four separate bugs had to be fixed before the loop could run, and each
 * was invisible until the one before it was cleared:
 * <ol>
 * <li>PR-69 — Ballista cast at X=0 entered as a 0/0 and died on resolution.</li>
 * <li>PR-70 — the loop never granted lifelink, so a ping gained no life.</li>
 * <li>PR-71 — the grant was proven on a COPY and never performed for real.</li>
 * <li>PR-72 — Heliod's trigger TARGETS, and stock AI fed the returning
 *     counter to {@code getBestAI()} (a fat Angel) instead of the Ballista,
 *     so the loop died after exactly one ping.</li>
 * </ol>
 *
 * <p>The observable that separates a real loop from a pinger eating itself is
 * drill sequence length: one iteration means broken, many means closed.
 */
public class GiadaHeliodLoopTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class BoardProbe implements GameAware {
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
            // both combo pieces, plus a fat Angel that stock AI would rather
            // put the counter on — the misdirection PR-72 exists to prevent
            for (String name : List.of("Heliod, Sun-Crowned", "Lyra Dawnbringer")) {
                forge.game.card.Card c = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard(name), p0);
                game.getAction().moveToPlay(c, null, null);
            }
            // Ballista from HAND so the pilot casts it and assemblyX picks X
            forge.game.card.Card ballista = forge.game.card.Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard("Walking Ballista"), p0);
            game.getAction().moveTo(ZoneType.Hand, ballista, null, null);
            for (int i = 0; i < 10; i++) {
                forge.game.card.Card land = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard("Plains"), p0);
                game.getAction().moveToPlay(land, null, null);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }
    }

    @Test
    public void theHeliodBallistaLoopSustains() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("giada-loop-stalls").toString());
        Path dossier = Path.of("decks", "giada-font-of-hope", "dossier");
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/giada-font-of-hope.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/urza-lord-high-artificer.dck"))),
                42L, new ArenaLimits(12, 400, 2000), sink, new BoardProbe());

        long drillSteps = events.stream()
                .filter(e -> e.t().equals("outlet_drill")).count();
        long prereq = events.stream()
                .filter(e -> e.t().equals("loop_prereq")).count();

        // Spellbook step 1 must happen on the real board, exactly once per arm
        assertTrue("lifelink must be granted for real (loop_prereq=" + prereq
                + "), events=" + events.stream().map(ArenaEvent::t).distinct().toList(),
                prereq >= 1);

        // Phase 11 PR-beta: the REAL bar. The interpreter must run sustained,
        // verified, engine-real iterations — the assertion six defects, a
        // rewrite, and one traced seam were spent earning. The seam: Forge
        // routes a wrapped trigger through orderAndPlaySimultaneousSa ->
        // brains.doTrigger() (chooseTargetsFor is only for TargetingPlayer
        // scripts), so the obligation is enforced in the controller's
        // orderAndPlaySimultaneousSa override, where the counter actually
        // gets its target.
        assertTrue("the loop must SUSTAIN through the interpreter (drill steps="
                + drillSteps + ") aborts=" + events.stream()
                        .filter(e -> e.t().equals("program_abort"))
                        .map(e -> String.valueOf(e.fields())).toList(),
                drillSteps >= 5);
    }
}
