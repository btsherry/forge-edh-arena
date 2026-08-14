package forge.arena.interactive;

import java.nio.file.Path;
import java.util.Collections;

import forge.LobbyPlayer;
import forge.ai.LobbyPlayerAi;
import forge.game.Game;
import forge.game.player.Player;
import forge.game.player.PlayerController;

/**
 * A LobbyPlayer that seats a {@link MailboxController} instead of the stock AI
 * controller. Mirrors {@code ComboAwareLobbyPlayer}'s injection seam exactly:
 * subclass {@link LobbyPlayerAi} and override {@code createIngamePlayer} /
 * {@code createMindSlaveController} to install a custom controller. Because both
 * the headless and GUI paths converge on
 * {@code IGameEntitiesFactory.createIngamePlayer} (Game.java:346), placing this
 * LobbyPlayer in an AI slot is honoured in a GUI-spectated/played game with no
 * parent-module patch.
 *
 * <p>The mailbox base dir is fixed per lobby player; the actual per-seat bus is
 * built lazily once the in-game {@link Player} (and thus its seat id) exists.
 */
public final class MailboxLobbyPlayer extends LobbyPlayerAi {

    private final Path baseDir;

    /** Uses the base dir from {@link MailboxProtocol#baseDir()} (system prop / default). */
    public MailboxLobbyPlayer(String name) {
        this(name, MailboxProtocol.baseDir());
    }

    public MailboxLobbyPlayer(String name, Path baseDir) {
        super(name, Collections.emptySet());
        this.baseDir = baseDir;
    }

    private MailboxController controllerFor(Player p) {
        // Attach the continuously-updated public observer snapshot ONCE per game.
        // ObserverSnapshot.ensureRegistered is idempotent (guarded by Game
        // identity), so calling it for every mailbox seat's controller is safe:
        // only the first call for a given Game actually subscribes.
        ObserverSnapshot.ensureRegistered(p.getGame(), baseDir);
        // Same idempotent pattern: the ELO result spool (placements + control
        // typing at game end, consumed by runner/ratings.py). Passive.
        GameResultSpool.ensureRegistered(p.getGame());
        return new MailboxController(p.getGame(), p, this,
                MailboxProtocol.forSeat(baseDir, p.getId()));
    }

    @Override
    public Player createIngamePlayer(Game game, int id) {
        Player p = new Player(getName(), game, id);
        p.setFirstController(controllerFor(p));
        return p;
    }

    @Override
    public PlayerController createMindSlaveController(Player master, Player slave) {
        return controllerFor(slave);
    }

    @Override
    public void hear(LobbyPlayer player, String message) {
        // mailbox seats do not react to table chat
    }
}
