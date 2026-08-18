package forge.arena.engine;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.combo.ExecutorBindings;
import forge.arena.combo.LineExecutor;
import forge.arena.combo.SimResult;
import forge.arena.combo.TapForManaUntapLoop;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;

/**
 * The PR-14 proof: on a live seeded game with a scripted Selvala + attached
 * Umbral Mantle board, the SHIPPED binding validates PROFITABLE on a
 * {@code GameSimHandle} copy — real cost payment, real granted ability,
 * real mana pool — while the real game is untouched (copy isolation), and a
 * hallucinated binding is BLOCKED (plan §8
 * BindingGenerationVerificationTest's core property, ahead of bindgen).
 */
public class SimHandleValidationTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    /** Applies the scripted board at turn 3 and validates on a copy, on the game thread. */
    static final class ValidationProbe implements GameAware {
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();
        final AtomicReference<SimResult> mantleResult = new AtomicReference<>();
        final AtomicReference<SimResult> hallucinatedResult = new AtomicReference<>();
        final AtomicReference<SimResult> staffResult = new AtomicReference<>();
        final AtomicReference<String> realGameAfter = new AtomicReference<>();
        final AtomicReference<Exception> failure = new AtomicReference<>();

        @Override
        public void onGameCreated(Game game) {
            this.game = game;
        }

        @Subscribe
        public void onTurn(GameEventTurnBegan event) {
            if (event.turnNumber() < 3 || !applied.compareAndSet(false, true)) {
                return;
            }
            try {
                // Board setup is PROGRAMMATIC, not via GameState.applyToGame:
                // dev-mode state application clears each player's command zone
                // and commander list (it targets puzzle/1v1 dev use), which
                // orphans the Commander Effect and breaks GameCopier. Findings
                // recorded in the plan doc; the dossier goldfish (v3.3 prep
                // v2) must set up boards the same way this does.
                Player p0 = game.getPlayers().get(0);
                game.getTriggerHandler().setSuppressAllTriggers(true);
                forge.game.card.Card selvala = p0.getCommanders().get(0);
                game.getAction().moveToPlay(selvala, null, null);
                forge.game.card.Card mantle = addCard(p0, "Umbral Mantle");
                forge.game.card.Card craterhoof = addCard(p0, "Craterhoof Behemoth");
                for (int i = 0; i < 6; i++) {
                    addCard(p0, "Forest");
                }
                mantle.attachToEntity(selvala, null, true);
                selvala.setSickness(false);
                craterhoof.setSickness(false);
                game.getTriggerHandler().setSuppressAllTriggers(false);
                game.getAction().checkStateEffects(true);

                ExecutorBindings bindings = ExecutorBindings.load(ExecutorBindings.defaultPath());
                LineExecutor mantleLine = ExecutorBindings.executorFor(
                        bindings.forCombo("527-2816").orElseThrow()).orElseThrow();
                mantleResult.set(mantleLine.validate(GameSimHandle.copyOf(game, p0)));

                // a plausible-but-wrong binding must be BLOCKED, never executable
                LineExecutor hallucinated = new TapForManaUntapLoop(Map.of(
                        "engine", "Selvala, Heart of the Wilds",
                        "untapper", "Umbral Mantle",
                        "activation_cost", "{G}",
                        "untap_cost", "{9}",
                        "untap_ability_host", "engine"), "MAIN1");
                hallucinatedResult.set(hallucinated.validate(GameSimHandle.copyOf(game, p0)));

                // Staff line: the untap ability TARGETS — scripted targets (PR-15)
                // make it engine-validatable; Terra Stomper supplies power 6+
                addCard(p0, "Staff of Domination");
                forge.game.card.Card stomper = addCard(p0, "Terra Stomper");
                stomper.setSickness(false);
                game.getAction().checkStateEffects(true);
                LineExecutor staffLine = ExecutorBindings.executorFor(
                        bindings.forCombo("527-2645").orElseThrow()).orElseThrow();
                staffResult.set(staffLine.validate(GameSimHandle.copyOf(game, p0)));

                // copy isolation: the REAL game saw none of the ~9 activations
                Player realP0 = game.getPlayers().get(0);
                boolean selvalaUntapped = realP0.getCardsIn(forge.game.zone.ZoneType.Battlefield)
                        .stream().filter(c -> c.getName().equals("Selvala, Heart of the Wilds"))
                        .allMatch(c -> !c.isTapped());
                realGameAfter.set("pool=" + realP0.getManaPool().totalMana()
                        + " selvalaUntapped=" + selvalaUntapped);
            } catch (Exception e) {
                failure.set(e);
            }
        }

        private forge.game.card.Card addCard(Player owner, String name) {
            forge.game.card.Card card = forge.game.card.Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard(name), owner);
            game.getAction().moveToPlay(card, null, null);
            return card;
        }
    }

    @Test
    public void shippedMantleBindingValidatesOnTheEngineAndHallucinationsCannot() {
        ValidationProbe probe = new ValidationProbe();
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.of(new File("decks/selvala-heart-of-the-wilds.dck")),
                        SeatSpec.goldfish(new File("decks/purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(5, 300, 2000), probe);

        if (probe.failure.get() != null) {
            throw new AssertionError("probe failed on game thread", probe.failure.get());
        }
        SimResult mantle = probe.mantleResult.get();
        assertTrue("probe never ran", mantle != null);
        assertTrue("shipped Mantle binding must validate PROFITABLE, got " + mantle,
                mantle.isProfitable());
        assertEquals("steady-state proof takes all 3 cycles", 3, mantle.cycles());

        SimResult hallucinated = probe.hallucinatedResult.get();
        assertEquals("wrong untap cost must be BLOCKED (W1: hallucinated bindings"
                + " can never reach executable)", SimResult.Status.BLOCKED, hallucinated.status());
        assertEquals("untapper", hallucinated.blockedBy());

        SimResult staff = probe.staffResult.get();
        assertTrue("Staff line (targeted untap, scripted targets) must validate, got " + staff,
                staff != null && staff.isProfitable());

        // ~9 ability activations happened on copies; the real game saw zero
        assertEquals("pool=0 selvalaUntapped=true", probe.realGameAfter.get());
    }
}
