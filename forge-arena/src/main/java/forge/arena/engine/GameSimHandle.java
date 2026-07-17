package forge.arena.engine;

import forge.ai.ComputerUtil;
import forge.ai.simulation.GameCopier;
import forge.ai.simulation.GameSimulator;
import forge.arena.combo.SimHandle;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * The sandbox implementation of {@link SimHandle} (plan §6): wraps a
 * {@code GameCopier} COPY of a live game, so executor validation drives the
 * real rules engine — real cost payment, real untap symbols, real static
 * abilities — without ever touching the game being played. Built on the
 * same seams the lookahead AI uses ({@code GameCopier},
 * {@code ComputerUtil.playNoStack} for off-stack mana abilities,
 * {@code handlePlayingSpellAbility} + {@code GameSimulator.resolveStack}
 * for stack abilities).
 *
 * <p>v1 refuses abilities that need targets: unscripted target choices are
 * nondeterministic. Target scripting arrives with Step execution (PR-15+),
 * where the executor names its targets explicitly.
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
    public boolean activate(String cardName, String costHint) {
        Card card = findBattlefield(cardName);
        if (card == null) {
            return false;
        }
        // getAllPossibleAbilities is the canonical enumeration: it walks the
        // CURRENT state, so abilities granted by attachments/statics (the
        // Mantle pump lives on Selvala only while equipped) are included
        for (SpellAbility sa : card.getAllPossibleAbilities(player, false)) {
            if (!sa.isActivatedAbility() || sa.usesTargeting()) {
                continue;
            }
            if (sa.getPayCosts() == null || !costMatches(sa.getPayCosts().toString(), costHint)) {
                continue;
            }
            sa.setActivatingPlayer(player);
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
        return false;
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
        Card card = findBattlefield(cardName);
        return card != null && !card.isTapped();
    }

    private Card findBattlefield(String cardName) {
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.getName().equals(cardName)) {
                return c;
            }
        }
        return null;
    }

    /**
     * Cost matching by normalized symbol containment: hint "{3}" matches
     * "{3}, {Q}: ..." but not "{13}". Hints are whole symbols, so a binding
     * distinguishes Staff's {1}/{3}/{5} abilities unambiguously.
     */
    static boolean costMatches(String costString, String costHint) {
        String normalizedCost = "{" + costString.toLowerCase()
                .replace("{", " ").replace("}", " ").replaceAll("[,:]", " ").trim()
                .replaceAll("\\s+", "}{") + "}";
        String normalizedHint = "{" + costHint.toLowerCase()
                .replace("{", " ").replace("}", " ").trim()
                .replaceAll("\\s+", "}{") + "}";
        return normalizedCost.contains(normalizedHint);
    }
}
