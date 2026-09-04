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
import forge.game.GameRules;
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
 *        [-Darena.seat.decks=slug0,slug1,slug2,slug3]
 *        forge.arena.interactive.GuiPilotMatch [humanDeckFileName] [busDir]
 * </pre>
 * {@code humanDeckFileName} (arg 0) picks which deck the human plays (default
 * seat 0 of the roster); {@code busDir} (arg 1) overrides the mailbox base
 * dir. {@code arena.seat.decks} repoints the whole table roster in seat order
 * (".dck" suffix optional; run-pilot-match.sh forwards ARENA_SEAT_DECKS here
 * so the engine's seats and run_table.sh's brains stay in lockstep).
 */
public final class GuiPilotMatch {

    private static final String DECKS_DIR_PROPERTY = "arena.decks.dir";
    private static final String SEAT_DECKS_PROPERTY = "arena.seat.decks";

    /** The default table (item R, Ben 2026-09-04), in seat order for an all-AI
     *  game: Urza, Giada, Purphoros, Selvala. A human game seats the human's
     *  deck at 0 and the first three roster decks that are not the human's
     *  behind it — see {@link #buildRoster}. run_table.sh and the advisor
     *  apply the same rule. */
    static final String[] DECKS = {
            "urza-lord-high-artificer.dck",
            "giada-font-of-hope.dck",
            "purphoros-god-of-the-forge.dck",
            "selvala-heart-of-the-wilds.dck",
    };

    /** The deck the human plays when none is named. */
    static final String DEFAULT_HUMAN_DECK = "selvala-heart-of-the-wilds.dck";

    private GuiPilotMatch() {
    }

    /**
     * Table roster in seat order: {@code -Darena.seat.decks} as comma- or
     * whitespace-separated deck names (".dck" appended if missing), defaulting
     * to {@link #DECKS}. The 4-pod guard in startCommanderMatch validates the
     * final roster size, so a malformed property fails loud, not weird.
     */
    private static String[] seatDecks() {
        final String prop = System.getProperty(SEAT_DECKS_PROPERTY);
        if (prop == null || prop.trim().isEmpty()) {
            return DECKS;
        }
        final String[] raw = prop.trim().split("[,\\s]+");
        final String[] out = new String[raw.length];
        for (int i = 0; i < raw.length; i++) {
            out[i] = raw[i].endsWith(".dck") ? raw[i] : raw[i] + ".dck";
        }
        return out;
    }

    /** System property enabling the seat-0 advisor shadow ("1" = on). */
    private static final String ADVISOR_PROPERTY = "arena.advisor";
    /** System property for autopass strictness: off | strict | casts (default casts). */
    private static final String AUTOPASS_PROPERTY = "arena.autopass";

    private static boolean advisorEnabled() {
        return "1".equals(System.getProperty(ADVISOR_PROPERTY));
    }

    /**
     * The human seat's lobby player: the plain GUI singleton, or — with the
     * advisor enabled — the {@link AdvisorLobbyPlayer} wrapper publishing the
     * decision shadow feed to {@code <mailbox>/seat-0-advisor/inbox/}.
     */
    private static forge.LobbyPlayer advisorLobbyOrGuiPlayer() {
        if (!advisorEnabled()) {
            return GamePlayerUtil.getGuiPlayer();
        }
        String mode = System.getProperty(AUTOPASS_PROPERTY, "casts");
        AdvisorFeed feed = new AdvisorFeed(MailboxProtocol.baseDir(), 0);
        return new AdvisorLobbyPlayer("Human", feed, "casts".equals(mode));
    }

    public static void main(String[] args) {
        final String[] decks = seatDecks();
        String humanDeck = args.length > 0 ? args[0] : DEFAULT_HUMAN_DECK;
        // --all-ai: EVERY seat (incl. 0) is a mailbox seat; the GUI attaches as
        // a pure spectator via HostedMatch's humanCount==0 watch path.
        final boolean allAi = "--all-ai".equals(humanDeck);
        if (allAi) {
            humanDeck = decks[0];
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

        // Advisor autopass rides on upstream APINA ("auto-pass if no actions"):
        // strict = APINA verbatim; casts = APINA + the AdvisorControllerHuman
        // utility-taps filter. In-memory only — deliberately no save(), so the
        // user's stored Forge preferences stay untouched.
        if (advisorEnabled()
                && !"off".equals(System.getProperty(AUTOPASS_PROPERTY, "casts"))) {
            forge.model.FModel.getPreferences().setPref(
                    forge.localinstance.properties.ForgePreferences.FPref.YIELD_AUTO_PASS_NO_ACTIONS,
                    String.valueOf(true));
        }

        // --- assemble + start the match on the EDT --------------------------
        final String humanDeckFinal = humanDeck;
        FThreads.invokeInEdtNowOrLater(() -> {
            try {
                startCommanderMatch(decksDir, humanDeckFinal, allAi, decks);
            } catch (RuntimeException e) {
                System.err.println("GuiPilotMatch: failed to start match: " + e);
                e.printStackTrace();
            }
        });
    }

    /** Deck file name → slug ({@code path/x.dck} → {@code x}). */
    static String slugOf(String deckFile) {
        String base = deckFile;
        final int slash = Math.max(base.lastIndexOf('/'), base.lastIndexOf('\\'));
        if (slash >= 0) {
            base = base.substring(slash + 1);
        }
        return base.endsWith(".dck") ? base.substring(0, base.length() - 4) : base;
    }

    /**
     * The seat-ordered roster (item R). All-AI: the four roster entries in
     * order. Human: the human's deck at seat 0 — ANY deck, including a freshly
     * ingested one — then the first three roster decks that are not the
     * human's. run_table.sh (ARENA_HUMAN_DECK) and the advisor apply the same
     * rule, so the brains and the seats move together. Exactly four seats or
     * this throws: a pod short of a brain is the unbrained-seat hang.
     */
    static List<String> buildRoster(String[] decks, String humanDeckFile, boolean allAi) {
        List<String> ordered = new ArrayList<>();
        if (allAi) {
            for (String d : decks) {
                ordered.add(d);
            }
        } else {
            ordered.add(humanDeckFile);
            final String human = slugOf(humanDeckFile);
            for (String d : decks) {
                if (ordered.size() >= 4) {
                    break;
                }
                if (!slugOf(d).equals(human)) {
                    ordered.add(d);
                }
            }
        }
        if (ordered.size() != 4) {
            throw new IllegalStateException(
                    "arena pod must be exactly 4 seats (1 human + 3 AI, or 4 AI"
                    + " under --all-ai), but built " + ordered.size()
                    + " from a roster of " + decks.length + " (arena.seat.decks"
                    + " must list exactly 4 decks, in seat order, matching"
                    + " runner/run_table.sh's ARENA_SEAT_DECKS).");
        }
        return ordered;
    }

    /**
     * Plan item 7, the start invariant, GUI-free so it can be tested (BL-12):
     * every deck in {@code ordered} must load and hold 100 real cards. The
     * first failure writes {@code launch-status.json} with {@code ok:false}
     * naming the seat, the deck and the problems, and throws; success writes
     * {@code ok:true}. A missing or unreadable deck file is a problem too.
     */
    static List<Deck> verifyRoster(File decksDir, List<String> ordered,
            java.nio.file.Path statusFile) {
        List<Deck> decks = new ArrayList<>();
        for (int seat = 0; seat < ordered.size(); seat++) {
            File deckFile = new File(decksDir, ordered.get(seat));
            Deck deck = deckFile.isFile() ? DeckSerializer.fromFile(deckFile) : null;
            List<String> problems = deck == null
                    ? List.of("deck file missing or unreadable: " + deckFile)
                    : DeckLoadProbe.playabilityProblems(deck);
            if (!problems.isEmpty()) {
                String msg = "seat " + seat + " deck " + deckFile.getName() + ": "
                        + String.join("; ", problems);
                writeLaunchStatus(statusFile, false, msg);
                System.err.println("[arena] LAUNCH REFUSED — " + msg);
                throw new IllegalStateException("launch refused: " + msg);
            }
            decks.add(deck);
        }
        writeLaunchStatus(statusFile, true, ordered.size() + " decks verified at 100 real cards each");
        return decks;
    }

    private static void startCommanderMatch(File decksDir, String humanDeckFile,
            boolean allAi, String[] decks) {
        List<String> ordered = buildRoster(decks, humanDeckFile, allAi);
        // Stash the resolved seat-ordered SLUG roster for the ELO result spool
        // (plan F-23: the deck ladder keys on slugs, and display names don't
        // match runner-side slugs — this property is the authoritative join).
        final StringBuilder slugCsv = new StringBuilder();
        for (int i = 0; i < ordered.size(); i++) {
            if (i > 0) {
                slugCsv.append(',');
            }
            slugCsv.append(slugOf(ordered.get(i)));
        }
        System.setProperty("arena.seat.slugs", slugCsv.toString());

        final java.nio.file.Path statusFile = MailboxProtocol.baseDir().resolve("launch-status.json");
        final List<Deck> loaded = verifyRoster(decksDir, ordered, statusFile);

        List<RegisteredPlayer> players = new ArrayList<>();
        Map<RegisteredPlayer, IGuiGame> guis = new LinkedHashMap<>();
        for (int seat = 0; seat < ordered.size(); seat++) {
            Deck deck = loaded.get(seat);
            RegisteredPlayer rp = RegisteredPlayer.forCommander(deck);
            if (seat == 0 && !allAi) {
                // seat 0 = HUMAN via the GUI player; its IGuiGame renders the game.
                // Under -Darena.advisor=1 the seat gets the advisor wrapper instead:
                // identical GUI wiring (HostedMatch detects by instanceof), plus the
                // one-way decision shadow feed and optional casts-mode autopass.
                rp.setPlayer(advisorLobbyOrGuiPlayer());
                guis.put(rp, GuiBase.getInterface().getNewGuiGame());
            } else {
                // mailbox seats (all four of them under --all-ai; the GUI then
                // rides along as HostedMatch's humanCount==0 spectator).
                rp.setPlayer(new MailboxLobbyPlayer("mailbox-seat" + seat + "-" + deck.getName()));
            }
            players.add(rp);
        }

        // Cosmetic: give each seat a built-in avatar matched to its deck's colors
        // (proportional to pip composition; fail-safe — Forge's default avatar
        // applies on any error). Never blocks the launch.
        SeatAvatars.assign(players);

        // A human seat means humanCount >= 1, which avoids the humanCount == 0
        // spectator IndexOutOfBounds path in HostedMatch.startGame.
        HostedMatch hm = GuiBase.getInterface().hostMatch();
        // ONE game per launch — Forge treats a Match as best-of-3 by default
        // (GameRules.gamesPerMatch=3 / UI_MATCHES_PER_GAME), which is what
        // auto-started games 2 and 3 ("auto-chaining"). Not a bug — a Match is
        // multi-game — but the arena wants a single game per launch, so build
        // explicit rules with gamesPerMatch=1 and use the rules overload. Pure
        // arena-side change; no Forge patch.
        GameRules rules = new GameRules(GameType.Commander);
        rules.setGamesPerMatch(1);
        hm.startMatch(rules, EnumSet.of(GameType.Commander), players, guis, null);
    }

    /** {@code <mailbox>/launch-status.json}: {@code {"ok":bool,"detail":…,"ts":…}}
     *  — arena-play.sh reads it so a refused launch reports at once instead of
     *  after the 150 s liveness wait. Best effort; never blocks the launch. */
    private static void writeLaunchStatus(java.nio.file.Path file, boolean ok, String detail) {
        try {
            java.nio.file.Files.createDirectories(file.getParent());
            String json = "{\"ok\": " + ok + ", \"detail\": \""
                    + detail.replace("\\", "\\\\").replace("\"", "\\\"") + "\", \"ts\": "
                    + System.currentTimeMillis() + "}";
            java.nio.file.Path tmp = file.resolveSibling(file.getFileName() + ".tmp");
            java.nio.file.Files.write(tmp, json.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            java.nio.file.Files.move(tmp, file, java.nio.file.StandardCopyOption.REPLACE_EXISTING,
                    java.nio.file.StandardCopyOption.ATOMIC_MOVE);
        } catch (java.io.IOException | RuntimeException e) {
            System.err.println("GuiPilotMatch: could not write launch status: " + e);
        }
    }
}
