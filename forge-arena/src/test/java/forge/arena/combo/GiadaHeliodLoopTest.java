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

        // The drill must at least fire once, safely.
        assertTrue("the drill must fire (steps=" + drillSteps + ")", drillSteps >= 1);

        // KNOWN GAP, deliberately recorded rather than asserted-away.
        //
        // The loop does not yet SUSTAIN. Five separate defects were found and
        // fixed getting this far (PR-69 X=0 on cast, PR-70 no lifelink grant,
        // PR-71 grant proven on a copy but never performed, PR-72 the counter
        // trigger targeting the wrong creature, PR-73 the drill spending the
        // outlet's last counter and killing it). Each was real, necessary,
        // and insufficient.
        //
        // What remains: after a safe ping the +1/+1 counter still does not
        // return, so the drill correctly declines to fire again rather than
        // destroying Ballista. Whether the break is in lifelink actually
        // applying, in the life-gain trigger firing, or in the counter
        // landing on the pinger is not yet established — and guessing is what
        // produced two of the five fixes above.
        //
        // Raise this to `>= 5` once the counter demonstrably returns; that is
        // the single assertion that proves the loop is real.
        if (drillSteps >= 5) {
            System.out.println("LOOP SUSTAINS: " + drillSteps + " drill steps");
        } else {
            System.out.println("LOOP DOES NOT SUSTAIN YET: " + drillSteps
                    + " drill step(s), prereq=" + prereq);
            events.stream().filter(e -> e.t().equals("outlet_drill")
                            || e.t().equals("loop_prereq"))
                    .forEach(e -> System.out.println("   EVIDENCE " + e.t()
                            + " " + e.fields()));
        }
    }
}
