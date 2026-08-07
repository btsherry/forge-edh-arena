package forge.arena.interactive;

import java.io.File;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import forge.GuiDesktop;
import forge.Singletons;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.GameType;
import forge.game.player.RegisteredPlayer;
import forge.gamemodes.match.HostedMatch;
import forge.gui.FThreads;
import forge.gui.GuiBase;
import forge.gui.interfaces.IGuiGame;
import forge.player.GamePlayerUtil;

/**
 * Launcher for a 4-player Commander game in the DESKTOP GUI where seat 0 is a
 * HUMAN (played through the normal Forge GUI) and seats 1-3 are file-driven
 * {@link MailboxLobbyPlayer} seats. A human can therefore play against three
 * mailbox opponents and watch the game render.
 *
 * <h2>Bootstrap</h2>
 * This mirrors {@code forge.view.Main.main} (forge-gui-desktop) exactly for the
 * no-arg desktop path:
 * <pre>
 *   GuiBase.setInterface(new GuiDesktop());
 *   Singletons.initializeOnce(true);      // loads FModel / card DB (must NOT be on the EDT)
 *   Singletons.getControl().initialize(); // brings up the home screen
 * </pre>
 * After the home screen is up we assemble the players and call
 * {@code hostMatch().startMatch(...)} on the EDT (UI creation —
 * {@code getNewGuiGame()} / {@code addMatch()} — must run there).
 *
 * <h2>Known risks / TODO</h2>
 * <ul>
 *   <li><b>Game-thread stack size.</b> {@link HostedMatch} owns the game thread
 *       ({@code game.getAction().invoke(...)} in {@code HostedMatch.startGame}),
 *       created with the JVM's DEFAULT stack. The headless
 *       {@code EngineFacade} runs on a 64MB stack precisely because Forge's
 *       target-legality walk StackOverflows on large combo boards; that knob is
 *       NOT reachable from the GUI launch path. Raising {@code -Xss} on the JVM
 *       does not resize an already-created thread, so a deep combo board CAN
 *       still StackOverflow here. Mitigation would require a HostedMatch change
 *       (out of scope: no parent patch).</li>
 *   <li><b>Bootstrap coupling.</b> {@code Singletons.getControl().initialize()}
 *       drives the full desktop home screen and may perform network version
 *       checks; it is the same call {@code Main.main} makes, so it is the
 *       supported entry, but it is heavier than a headless bootstrap.</li>
 * </ul>
 *
 * <h2>Usage</h2>
 * <pre>
 *   java [-Darena.assets.dir=/path/to/forge-gui]
 *        [-Darena.decks.dir=forge-arena/decks]
 *        [-Darena.mailbox.dir=forge-arena/mailbox]
 *        [-Darena.mailbox.timeout.sec=300]
 *        forge.arena.interactive.GuiPilotMatch [humanDeckFileName] [busDir]
 * </pre>
 * {@code humanDeckFileName} (arg 0) picks which of the four decks the human
 * plays (default {@code selvala-heart-of-the-wilds.dck}); {@code busDir}
 * (arg 1) overrides the mailbox base dir.
 */
public final class GuiPilotMatch {

    private static final String DECKS_DIR_PROPERTY = "arena.decks.dir";

    /** The four Commander decks; index 0 is the default human seat. */
    private static final String[] DECKS = {
            "selvala-heart-of-the-wilds.dck",
            "purphoros-god-of-the-forge.dck",
            "giada-font-of-hope.dck",
            "urza-lord-high-artificer.dck",
    };

    private GuiPilotMatch() {
    }

    public static void main(String[] args) {
        String humanDeck = args.length > 0 ? args[0] : DECKS[0];
        // --all-ai: EVERY seat (incl. 0) is a mailbox seat; the GUI attaches as
        // a pure spectator via HostedMatch's humanCount==0 watch path.
        final boolean allAi = "--all-ai".equals(humanDeck);
        if (allAi) {
            humanDeck = DECKS[0];
        }
        if (args.length > 1) {
            System.setProperty(MailboxProtocol.DIR_PROPERTY, args[1]);
        }
        final File decksDir = new File(System.getProperty(DECKS_DIR_PROPERTY,
                "forge-arena/decks"));

        // --- desktop GUI bootstrap (mirrors forge.view.Main.main) -----------
        GuiBase.setInterface(new GuiDesktop());
        // initializeOnce loads FModel/card DB and asserts it is NOT on the EDT.
        Singletons.initializeOnce(true);
        // brings up the home screen; same call Main.main makes.
        Singletons.getControl().initialize();

        // --- assemble + start the match on the EDT --------------------------
        final String humanDeckFinal = humanDeck;
        FThreads.invokeInEdtNowOrLater(() -> {
            try {
                startCommanderMatch(decksDir, humanDeckFinal, allAi);
            } catch (RuntimeException e) {
                System.err.println("GuiPilotMatch: failed to start match: " + e);
                e.printStackTrace();
            }
        });
    }

    private static void startCommanderMatch(File decksDir, String humanDeckFile,
            boolean allAi) {
        // Order the seats: human deck first, then the remaining three as mailbox
        // seats (preserving the fixed DECKS order).
        List<String> ordered = new ArrayList<>();
        ordered.add(humanDeckFile);
        for (String d : DECKS) {
            if (!d.equals(humanDeckFile)) {
                ordered.add(d);
            }
        }

        List<RegisteredPlayer> players = new ArrayList<>();
        Map<RegisteredPlayer, IGuiGame> guis = new LinkedHashMap<>();
        for (int seat = 0; seat < ordered.size(); seat++) {
            File deckFile = new File(decksDir, ordered.get(seat));
            Deck deck = DeckSerializer.fromFile(deckFile);
            if (deck == null || deck.getCommanders().isEmpty()) {
                throw new IllegalArgumentException(
                        "not a loadable Commander deck: " + deckFile.getAbsolutePath());
            }
            RegisteredPlayer rp = RegisteredPlayer.forCommander(deck);
            if (seat == 0 && !allAi) {
                // seat 0 = HUMAN via the GUI player; its IGuiGame renders the game.
                rp.setPlayer(GamePlayerUtil.getGuiPlayer());
                guis.put(rp, GuiBase.getInterface().getNewGuiGame());
            } else {
                // mailbox seats (all four of them under --all-ai; the GUI then
                // rides along as HostedMatch's humanCount==0 spectator).
                rp.setPlayer(new MailboxLobbyPlayer("mailbox-seat" + seat + "-" + deck.getName()));
            }
            players.add(rp);
        }

        // A human seat means humanCount >= 1, which avoids the humanCount == 0
        // spectator IndexOutOfBounds path in HostedMatch.startGame.
        HostedMatch hm = GuiBase.getInterface().hostMatch();
        hm.startMatch(GameType.Commander, EnumSet.of(GameType.Commander), players, guis);
    }
}
