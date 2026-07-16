package forge.arena.engine;

import forge.game.Game;

/**
 * Engine-internal contract: a facade subscriber that needs the live Game at
 * creation time (before startGame). Only engine-package classes may implement
 * this — it exposes a Forge type, so the ArchUnit wall keeps it out of the
 * combo/report layers.
 */
public interface GameAware {

    void onGameCreated(Game game);
}
