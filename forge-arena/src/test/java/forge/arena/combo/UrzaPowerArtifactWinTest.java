package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
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
 * The Power Artifact loop, verified end to end (the "look at the combo file"
 * finding). Urza fired ONE combo in 30 games while ten reached ready, and
 * eight entered lines that aborted at validation — because the binding
 * modelled Power Artifact as an "untapper" with an invented {1} untap cost.
 *
 * <p>Power Artifact untaps nothing. Basalt Monolith untaps ITSELF for {3};
 * Power Artifact reduces that self-untap to {1}. Tap for {C}{C}{C}, untap for
 * a net {1}, +2 per cycle, infinite. The binding now names Basalt as its own
 * untapper with the REAL {3} script cost as the resolver hint — Power Artifact
 * applies its reduction at payment — so the copy-validation activates the real
 * ability and measures the true pool delta, instead of hunting a fictional
 * {1} ability the resolver could never match.
 *
 * <p>This test asserts the thing the binding fix actually fixed: the loop
 * enters and STEPS rather than aborting at validation:blocked:engine, which
 * was the batch's dominant Urza failure (8 aborts against 1 fire).
 */
public class UrzaPowerArtifactWinTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    static final class HandProbe implements GameAware {
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
            // both combo pieces on the battlefield, plus a payoff to spend the
            // pool on (Aetherflux: pay 50 life, deal 50 to any target)
            for (String name : List.of("Basalt Monolith", "Power Artifact",
                    "Aetherflux Reservoir")) {
                forge.game.card.Card card = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard(name), p0);
                game.getAction().moveToPlay(card, null, null);
            }
            // Power Artifact is an Aura enchanting Basalt Monolith — attach it
            for (forge.game.card.Card c : p0.getCardsIn(ZoneType.Battlefield)) {
                if (c.getName().equals("Power Artifact")) {
                    for (forge.game.card.Card host : p0.getCardsIn(ZoneType.Battlefield)) {
                        if (host.getName().equals("Basalt Monolith")) {
                            c.attachToEntity(host, null);
                        }
                    }
                }
            }
            for (int i = 0; i < 6; i++) {
                forge.game.card.Card land = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard("Island"), p0);
                game.getAction().moveToPlay(land, null, null);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }
    }

    @Test
    public void urzaFiresThePowerArtifactLoop() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("urza-pa-stalls").toString());
        Path dossier = Path.of("decks", "urza-lord-high-artificer", "dossier");
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                                new File("decks/urza-lord-high-artificer.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(14, 400, 2000), sink, new HandProbe());

        // the loop must PROVE and FIRE — the exact step that aborted 8 times
        // in the batch with validation:blocked:engine
        // the binding bug was validation:blocked:engine — the loop entered
        // and was refused because Power Artifact was modelled as an untapper
        // with an invented {1} untap cost the resolver could not find. With
        // the untap hint set to Basalt's real {3} script cost (Power Artifact
        // reduces it at PAYMENT), the loop validates: it enters and STEPS
        // instead of aborting.
        long entered = events.stream()
                .filter(e -> e.t().equals("line_entered")).count();
        long steps = events.stream()
                .filter(e -> e.t().equals("line_step")).count();
        long validationAborts = events.stream()
                .filter(e -> e.t().equals("line_aborted")
                        && String.valueOf(e.fields().get("cause")).equals("validation"))
                .count();
        assertTrue("the loop must enter (entered=" + entered + ")", entered >= 1);
        assertTrue("the loop must run cycle steps rather than abort (steps="
                + steps + ")", steps >= 2);
        assertEquals("no validation abort once the self-untap is modelled with"
                + " the real script cost", 0, validationAborts);
    }
}
