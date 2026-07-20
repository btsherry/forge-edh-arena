package forge.game.staticability;

import forge.game.Game;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

public class StaticAbilityTurnPhaseReversed {

    // ARENA-PATCH (forge-edh-arena): reentrancy guard against an infinite
    // mutual recursion that crashed ~10% of headless 4-player games.
    //
    // The cycle: anyTurnPhaseReversed walks every static ability and calls
    // matchesValidParam("ValidPlayer", ...); a Valid expression that mentions
    // opponents reaches Player.getOpponents -> Game.getPlayersInTurnOrder ->
    // Player.isTurnOrderReversed -> back into anyTurnPhaseReversed, forever.
    // It needs no unusual card — only a board large enough to make the walk
    // hit such an ability, which is why a combo harness reproduces it
    // constantly and normal play rarely does.
    //
    // While a computation for this thread is already in flight, answer with
    // the identity value (false = "not reversed"). That is the correct
    // fallback: the outer call is mid-way through deciding exactly this
    // question, and no real card reverses turn order conditionally on turn
    // order. Thread-scoped so concurrent games never interfere.
    private static final ThreadLocal<Boolean> COMPUTING = ThreadLocal.withInitial(() -> false);
    public static boolean isTurnReversed(Player player) {
        return anyTurnPhaseReversed(player, StaticAbilityMode.TurnReversed);
    }
    public static boolean isPhaseReversed(Player player) {
        return anyTurnPhaseReversed(player, StaticAbilityMode.PhaseReversed);
    }

    protected static boolean anyTurnPhaseReversed(Player player, final StaticAbilityMode mode)
    {
        // ARENA-PATCH: see COMPUTING above
        if (COMPUTING.get()) {
            return false;
        }
        boolean result = false;
        final Game game = player.getGame();
        COMPUTING.set(true);
        try {
            for (final Card ca : game.getCardsIn(ZoneType.STATIC_ABILITIES_SOURCE_ZONES)) {
                for (final StaticAbility stAb : ca.getStaticAbilities()) {
                    if (!stAb.checkConditions(mode)) {
                        continue;
                    }
                    if (applyTurnPhaseReversed(stAb, player)) {
                        result = !result;
                    }
                }
            }
        } finally {
            COMPUTING.set(false);
        }
        return result;
    }

    protected static boolean applyTurnPhaseReversed(StaticAbility stAb, Player player) {
        if (!stAb.matchesValidParam("ValidPlayer", player)) {
            return false;
        }

        return true;
    }
}
