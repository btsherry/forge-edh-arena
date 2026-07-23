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
 * PR-theta: the first assembly_gated pairing — Armageddon + Teferi's
 * Protection. Protected mass land destruction, Ben's rule: fire as soon as
 * it is assembled and affordable, no threat condition.
 *
 * <p>Two things this pair proves that Doomskar + Maneuver could not:
 * <ol>
 * <li>PHASING protection: Teferi's phases out ALL our permanents (lands
 *     included) so Armageddon structurally cannot see them —
 *     Game.getCardsIn(Battlefield) filters phased-out cards. Our lands are
 *     also invisible to OUR OWN counts until they phase in before our
 *     untap, which is why the own-side measure is DEFERRED to our next
 *     turn (verify.measure_at: next_untap).</li>
 * <li>Opponents' losses are snapshotted at resolution, so a land replayed
 *     during the deferred window cannot launder the reduction.</li>
 * </ol>
 */
public class GiadaArmageddonPairTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class MldBoardProbe implements GameAware {
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
            // a board worth keeping through our own Armageddon
            for (String name : List.of("Lyra Dawnbringer", "Serra Angel")) {
                game.getAction().moveToPlay(card(name, p0), null, null);
            }
            // opponents' lands to destroy (the goldfish also plays its own)
            for (int i = 0; i < 3; i++) {
                game.getAction().moveToPlay(card("Island", p1), null, null);
            }
            for (String name : List.of("Armageddon", "Teferi's Protection")) {
                game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
            }
            // {3}{W} + {2}{W} jointly — no free condition on this pair
            for (int i = 0; i < 8; i++) {
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
    public void protectedArmageddonFiresOnAssemblyAndOurLandsReturn() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("armageddon-pair-stalls").toString());
        Path dossier = Path.of("decks", "giada-font-of-hope", "dossier");
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/giada-font-of-hope.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/urza-lord-high-artificer.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new MldBoardProbe());

        List<ArenaEvent> entries = events.stream()
                .filter(e -> e.t().equals("pairing_entered")
                        && "pp-armageddon-teferi-s-protection"
                                .equals(String.valueOf(e.fields().get("pairing"))))
                .toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("pairing_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        List<ArenaEvent> completes = events.stream()
                .filter(e -> e.t().equals("pairing_complete")
                        && "pp-armageddon-teferi-s-protection"
                                .equals(String.valueOf(e.fields().get("pairing"))))
                .toList();

        assertTrue("assembly_gated MLD must enter once assembled (entries="
                + entries.size() + ") events="
                + events.stream().map(ArenaEvent::t).distinct().toList(),
                !entries.isEmpty());
        assertTrue("the pairing must COMPLETE via the DEFERRED measure, aborts="
                + aborts, !completes.isEmpty());

        var f = completes.get(0).fields();
        int ownBefore = ((Number) f.get("own_before")).intValue();
        int ownAfter = ((Number) f.get("own_after")).intValue();
        int oppBefore = ((Number) f.get("opp_before")).intValue();
        int oppAfter = ((Number) f.get("opp_after")).intValue();
        assertTrue("the own measure must be the deferred one",
                "next_untap".equals(String.valueOf(f.get("measured_at"))));
        assertTrue("our lands must phase back in (own " + ownBefore + "->"
                + ownAfter + ", counted post-untap)",
                ownBefore >= 8 && ownAfter >= ownBefore);
        assertTrue("opponents' lands must be destroyed at resolution (opp "
                + oppBefore + "->" + oppAfter + ")",
                oppBefore >= 3 && oppAfter < oppBefore);
        // the deferred verdict must land on a LATER turn than entry
        int enteredTurn = entries.get(0).turn();
        int completedTurn = completes.get(0).turn();
        assertTrue("measure must defer past the casting turn (entered t"
                + enteredTurn + ", completed t" + completedTurn + ")",
                completedTurn > enteredTurn);
        assertTrue("no unprotected resolution or cast failure: " + aborts,
                aborts.stream().noneMatch(a -> a.contains("unprotected")
                        || a.contains("protection_cast_failed")));
    }
}
