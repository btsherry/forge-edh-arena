package forge.arena.interactive;

import forge.game.Game;
import forge.game.player.Player;
import forge.game.player.PlayerController;
import forge.player.LobbyPlayerHuman;
import forge.player.PlayerControllerHuman;
import forge.util.GuiDisplayUtil;

/**
 * The human lobby player with the advisor shadow: identical to
 * {@link LobbyPlayerHuman} (which it MUST extend — YieldController hard-casts
 * the lobby player for the persistent auto-yield store), except the controller
 * it mints is {@link AdvisorControllerHuman}. All GUI wiring in HostedMatch is
 * {@code instanceof}-based and rides through untouched.
 */
public final class AdvisorLobbyPlayer extends LobbyPlayerHuman {

    private final AdvisorFeed feed;
    private final boolean castsAutopass;

    public AdvisorLobbyPlayer(final String name, final AdvisorFeed feed, final boolean castsAutopass) {
        super(name);
        this.feed = feed;
        this.castsAutopass = castsAutopass;
    }

    @Override
    public PlayerController createMindSlaveController(final Player master, final Player slave) {
        return new AdvisorControllerHuman(slave, this,
                (PlayerControllerHuman) master.getController(), feed, castsAutopass);
    }

    @Override
    public Player createIngamePlayer(final Game game, final int id) {
        final Player player = new Player(GuiDisplayUtil.personalizeHuman(getName()), game, id);
        final AdvisorControllerHuman controller =
                new AdvisorControllerHuman(game, player, this, feed, castsAutopass);
        player.setFirstController(controller);
        System.err.println("advisor-shadow: controller installed for seat " + id
                + " (autopass-casts=" + castsAutopass + ")");
        return player;
    }
}
