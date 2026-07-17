package forge.arena.engine;

import java.util.List;

import forge.ai.ComputerUtil;
import forge.ai.simulation.GameCopier;
import forge.ai.simulation.GameSimulator;
import forge.arena.combo.SimHandle;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;

/**
 * The sandbox implementation of {@link SimHandle} (plan §6): wraps a
 * {@code GameCopier} COPY of a live game, so executor validation drives the
 * real rules engine — real cost payment, real untap symbols, real static
 * abilities — without ever touching the game being played. Built on the
 * same seams the lookahead AI uses ({@code GameCopier},
 * {@code ComputerUtil.playNoStack} for off-stack mana abilities,
 * {@code handlePlayingSpellAbility} + {@code GameSimulator.resolveStack}
 * for stack abilities). Ability lookup and target scripting are shared with
 * live execution via {@link AbilityResolver} — what validates is what plays.
 */
public final class GameSimHandle implements SimHandle {

    private final Game sim;
    private final Player player;

    private GameSimHandle(Game sim, Player player) {
        this.sim = sim;
        this.player = player;
    }

    /** Copy {@code game} and take {@code perspective}'s seat in the copy. */
    public static GameSimHandle copyOf(Game game, Player perspective) {
        GameCopier copier = new GameCopier(game);
        Game sim = copier.makeCopy();
        Player simPlayer = (Player) copier.find(perspective);
        // make the copy self-consistent before anything queries it: static
        // layers (granted abilities — the Mantle pump on Selvala) apply here
        sim.getAction().checkStateEffects(true);
        return new GameSimHandle(sim, simPlayer);
    }

    @Override
    public boolean activate(String cardName, String costHint, List<String> targetNames) {
        SpellAbility sa = AbilityResolver.resolve(player, cardName, costHint, targetNames);
        if (sa == null) {
            return false;
        }
        if (sa.isManaAbility()) {
            // mana abilities never use the stack; playNoStack pays costs
            // (tap/untap symbols included) through the AI cost machinery
            return ComputerUtil.playNoStack(player, sa, sim, false);
        }
        boolean played = ComputerUtil.handlePlayingSpellAbility(player, sa, () -> {
        });
        if (played) {
            GameSimulator.resolveStack(sim, player.getWeakestOpponent());
        }
        return played;
    }

    @Override
    public int manaPoolTotal() {
        return player.getManaPool().totalMana();
    }

    @Override
    public int greatestOwnPower() {
        int greatest = 0;
        for (Card c : player.getCreaturesInPlay()) {
            greatest = Math.max(greatest, c.getNetPower());
        }
        return greatest;
    }

    @Override
    public boolean untapped(String cardName) {
        Card card = AbilityResolver.findBattlefield(player, cardName);
        return card != null && !card.isTapped();
    }
}
