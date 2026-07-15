package forge.arena.engine;

import forge.game.Game;
import forge.game.GameState;

/**
 * Scripted-game-state loader (T0 §15/§4.6: {@code forge.game.GameState}, the
 * Puzzle mechanism — a concrete class on current master; the March-era abstract
 * {@code getPaperCard} hook is gone, card resolution is internal). Shared
 * infrastructure for golden scenario tests and the v3.3 dossier goldfish.
 * State text is {@code key=value} lines with {@code p0..p3} player prefixes,
 * so 4-player states are expressible.
 */
public class ArenaGameState extends GameState {

    /** Apply this parsed state to a running game on its game thread. */
    public void apply(Game game) {
        applyToGame(game);
    }
}
