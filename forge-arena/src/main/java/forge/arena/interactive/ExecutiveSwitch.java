package forge.arena.interactive;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;

import forge.LobbyPlayer;
import forge.game.Game;
import forge.game.player.Player;
import forge.game.player.PlayerController;

/**
 * "Advisor Executive" (Ben, 2026-09-07): a GUI toggle that lets the advisor
 * PLAY the human's seat. Forge already owns the mechanism — a runtime
 * controller override on the {@link Player} ({@code controlledBy}, the
 * Mindslaver path): {@link Player#addController(long, Player, PlayerController, boolean)}
 * routes every later decision to the override until
 * {@link Player#removeController(long)}.
 *
 * <p>The switch is a file, {@code logs/control/executive.json} {"on": true},
 * written by the Advisor tab's button (forge-gui-desktop cannot reference
 * this module; both sides agree on the path). It is read at DECISION
 * BOUNDARIES on the game thread only: the human controller installs the
 * override at its next priority when the file says on; the override removes
 * itself at its next priority when the file says off, and hands that very
 * decision back. So the toggle takes effect at the next decision, never
 * mid-decision, and no other thread touches the controller map.
 *
 * <p>The override is a {@link MailboxController} for seat 0 on the seat-0 bus
 * ({@code mailbox/seat-0}); the advisor runner answers that bus with the
 * advisor's own brain (one session, no second agent).
 */
public final class ExecutiveSwitch {

    private static final Map<Player, Long> INSTALLED =
            Collections.synchronizedMap(new WeakHashMap<>());
    private static final Set<PlayerController> EXECUTIVES =
            Collections.newSetFromMap(Collections.synchronizedMap(new WeakHashMap<>()));

    private ExecutiveSwitch() {
    }

    /** The runner's logs dir: {@code arena.runner.logs.dir} when set, else the
     *  mailbox dir's sibling {@code runner/logs}. */
    static Path logsDir() {
        final String logs = System.getProperty("arena.runner.logs.dir", "");
        if (!logs.isEmpty()) {
            return Paths.get(logs);
        }
        return MailboxProtocol.baseDir().toAbsolutePath().getParent().resolve("runner").resolve("logs");
    }

    public static Path controlFile() {
        return logsDir().resolve("control").resolve("executive.json");
    }

    /** True when the control file exists and says {"on": true}. Never throws. */
    public static boolean wanted() {
        try {
            final Path f = controlFile();
            if (!Files.exists(f)) {
                return false;
            }
            final String s = new String(Files.readAllBytes(f), StandardCharsets.UTF_8).replace(" ", "");
            return s.contains("\"on\":true");
        } catch (IOException | RuntimeException e) {
            return false;
        }
    }

    /** Install the seat-0 mailbox override on {@code human}. False when already
     *  installed or anything fails (the human keeps playing). */
    public static boolean install(final Player human, final LobbyPlayer lobby) {
        if (human == null || INSTALLED.containsKey(human)) {
            return false;
        }
        try {
            final Game game = human.getGame();
            final MailboxController exec = new MailboxController(game, human, lobby,
                    MailboxProtocol.forSeat(MailboxProtocol.baseDir(), human.getId()));
            final long ts = game.getNextTimestamp();
            human.addController(ts, human, exec, true);
            INSTALLED.put(human, ts);
            EXECUTIVES.add(exec);
            System.err.println("advisor-executive: ON — seat " + human.getId()
                    + " is played by the advisor from this decision");
            return true;
        } catch (RuntimeException e) {
            System.err.println("advisor-executive: install failed: " + e);
            return false;
        }
    }

    public static boolean isExecutive(final PlayerController c) {
        return c != null && EXECUTIVES.contains(c);
    }

    /** Remove the override; the human controller answers from the next decision. */
    public static boolean release(final Player human) {
        final Long ts = human == null ? null : INSTALLED.remove(human);
        if (ts == null) {
            return false;
        }
        try {
            human.removeController(ts, true);
            System.err.println("advisor-executive: OFF — seat " + human.getId() + " is the human's again");
            return true;
        } catch (RuntimeException e) {
            System.err.println("advisor-executive: release failed: " + e);
            return false;
        }
    }

    /** Test/teardown helper. */
    static void forget(final Player human) {
        INSTALLED.remove(human);
    }
}
