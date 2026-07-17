package forge.arena.engine;

import java.io.File;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import com.google.common.eventbus.Subscribe;

import forge.arena.bindgen.BindGen;
import forge.arena.combo.ExecutorBindings;
import forge.arena.combo.LineExecutor;
import forge.arena.combo.SimResult;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;

/**
 * Gate 3.5's sandbox oracle (plan §3 step 3): verify a generated binding by
 * building its board inside a real (short, seeded, disposable) game — the
 * pieces from the card DB, attached per the binding, plus generous mana and
 * a generic large creature for power-class prerequisites — then running the
 * executor's validate() on a GameCopier copy. The engine either proves the
 * loop or refuses it; a hallucinated card name or wrong cost is BLOCKED
 * here and never becomes executable. Same probe pattern the golden tests
 * use (T0 §4.4b: board setup is programmatic).
 */
public final class BindingVerifier implements BindGen.Verifier {

    private final File deckFile;

    public BindingVerifier(File deckFile) {
        this.deckFile = deckFile;
    }

    @Override
    public SimResult verify(ExecutorBindings.Binding binding) {
        LineExecutor executor = ExecutorBindings.executorFor(binding).orElse(null);
        if (executor == null) {
            return SimResult.blocked("unknown_archetype");
        }
        AtomicReference<SimResult> verdict = new AtomicReference<>();
        AtomicReference<Exception> failure = new AtomicReference<>();

        GameAware probe = new GameAware() {
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
                try {
                    Player p0 = game.getPlayers().get(0);
                    game.getTriggerHandler().setSuppressAllTriggers(true);
                    forge.game.card.Card engine = addCard(p0, binding.params().get("engine"));
                    forge.game.card.Card untapper = addCard(p0, binding.params().get("untapper"));
                    engine.setSickness(false);
                    if ("engine".equals(binding.params().get("untap_ability_host"))
                            && binding.params().get("attach_cost") != null) {
                        untapper.attachToEntity(engine, null, true);
                    }
                    // generous board (plan: "generous mana"): power-class
                    // prerequisites get a generic big creature, costs get lands
                    addCard(p0, "Terra Stomper").setSickness(false);
                    for (int i = 0; i < 10; i++) {
                        addCard(p0, "Forest");
                    }
                    game.getTriggerHandler().setSuppressAllTriggers(false);
                    game.getAction().checkStateEffects(true);
                    verdict.set(executor.validate(GameSimHandle.copyOf(game, p0)));
                } catch (Exception e) {
                    failure.set(e);
                }
            }

            private forge.game.card.Card addCard(Player owner, String name) {
                var paper = forge.StaticData.instance().getCommonCards().getCard(name);
                if (paper == null) {
                    throw new IllegalArgumentException("unknown card: " + name);
                }
                forge.game.card.Card card = forge.game.card.Card.fromPaperCard(paper, owner);
                game.getAction().moveToPlay(card, null, null);
                return card;
            }
        };

        try {
            EngineFacade.playCommanderGame(
                    List.of(SeatSpec.of(deckFile), SeatSpec.goldfish(deckFile)),
                    7L, new ArenaLimits(4, 120, 2000), probe);
        } catch (RuntimeException e) {
            return SimResult.blocked("verifier_game_failed: " + e.getMessage());
        }
        if (failure.get() != null) {
            return SimResult.blocked("verifier_board_failed: " + failure.get().getMessage());
        }
        return verdict.get() != null ? verdict.get() : SimResult.blocked("verifier_never_ran");
    }
}
