package forge.arena.interactive;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.WeakHashMap;

import com.google.common.eventbus.Subscribe;

import forge.LobbyPlayer;
import forge.game.Game;
import forge.game.event.GameEvent;
import forge.game.player.Player;

/**
 * Passive, write-only match-end recorder for the local ELO ladders (plan
 * ~/Claude/openrouter-backends-plan.md §13.1). Subscribes to the game event
 * bus exactly like {@link ObserverSnapshot}; on every event it diffs
 * {@code game.getLostPlayers()} (append-ordered, never cleared) against what
 * it has already seen — each diff batch is one TIE GROUP (players eliminated
 * by the same game-over pass, e.g. everyone alive when someone wins, share a
 * placement). On the outcome event it spools one uniquely-named JSON file to
 * {@code runner/results/game-&lt;startMillis&gt;-&lt;pid&gt;.json}; the Python
 * ratings applier ({@code runner/ratings.py}) consumes and renames it.
 *
 * Never throws into the game loop; writes at most one file per Game.
 */
public final class GameResultSpool {

    private static final Set<Game> REGISTERED =
            Collections.newSetFromMap(new WeakHashMap<>());

    private final Game game;
    private final long startMillis;
    private final Set<Integer> seenLost = new HashSet<>();
    private final List<List<Integer>> lostGroups = new ArrayList<>();
    private final List<Integer> lostGroupTurns = new ArrayList<>();
    private volatile boolean written;

    private GameResultSpool(final Game game) {
        this.game = game;
        this.startMillis = System.currentTimeMillis();
    }

    /** Idempotent per Game; mirrors ObserverSnapshot.ensureRegistered. */
    public static void ensureRegistered(final Game game) {
        if (game == null) {
            return;
        }
        synchronized (REGISTERED) {
            if (REGISTERED.contains(game)) {
                return;
            }
            REGISTERED.add(game);
        }
        try {
            game.subscribeToEvents(new GameResultSpool(game));
        } catch (final RuntimeException e) {
            synchronized (REGISTERED) {
                REGISTERED.remove(game);
            }
            System.err.println("GameResultSpool: could not register: " + e.getMessage());
        }
    }

    @Subscribe
    public void onGameEvent(final GameEvent ev) {
        try {
            diffLostPlayers();
            if (ev != null && ev.getClass().getSimpleName().contains("GameOutcome")) {
                writeSpool();
            }
        } catch (final Throwable t) {
            // never let result recording escape into the game loop
        }
    }

    /** New entries in lostPlayers since last look = one tie group. */
    private synchronized void diffLostPlayers() {
        final List<Integer> fresh = new ArrayList<>();
        for (final Player p : game.getLostPlayers()) {
            if (seenLost.add(p.getId())) {
                fresh.add(p.getId());
            }
        }
        if (!fresh.isEmpty()) {
            lostGroups.add(fresh);
            lostGroupTurns.add(game.getPhaseHandler().getTurn());
        }
    }

    private synchronized void writeSpool() {
        if (written) {
            return;
        }
        written = true;
        final List<Player> players = new ArrayList<>(game.getRegisteredPlayers());
        // Placement groups, best first: winners, then loss groups in reverse
        // elimination order (later-eliminated beats earlier). A draw has no
        // winner group and the final loss batch is simply the top group.
        final List<List<Integer>> placement = new ArrayList<>();
        final List<Integer> winners = new ArrayList<>();
        for (final Player p : players) {
            if (p.hasWon()) {
                winners.add(p.getId());
            }
        }
        if (!winners.isEmpty()) {
            placement.add(winners);
        }
        for (int i = lostGroups.size() - 1; i >= 0; i--) {
            placement.add(lostGroups.get(i));
        }
        final String[] slugs = System.getProperty("arena.seat.slugs", "").split(",", -1);
        final StringBuilder sb = new StringBuilder(1024);
        sb.append("{\"schema\": 1, \"startMillis\": ").append(startMillis)
          .append(", \"endMillis\": ").append(System.currentTimeMillis())
          .append(", \"turnsPlayed\": ").append(game.getPhaseHandler().getTurn())
          .append(", \"advisor\": ")
          .append("1".equals(System.getProperty("arena.advisor", "0")))
          .append(", \"seats\": [");
        for (int i = 0; i < players.size(); i++) {
            final Player p = players.get(i);
            final int seat = p.getId();
            if (i > 0) {
                sb.append(", ");
            }
            sb.append("{\"seat\": ").append(seat)
              .append(", \"name\": \"").append(esc(p.getName()))
              .append("\", \"slug\": \"")
              .append(esc(seat >= 0 && seat < slugs.length ? slugs[seat] : ""))
              .append("\", \"control\": \"").append(controlOf(p)).append("\"}");
        }
        sb.append("], \"placementGroups\": ").append(intGroups(placement))
          .append(", \"lostGroupTurns\": ").append(ints(lostGroupTurns))
          .append("}");
        try {
            final Path dir = resultsDir();
            Files.createDirectories(dir);
            final Path out = dir.resolve("game-" + startMillis + "-"
                    + ProcessHandle.current().pid() + ".json");
            final Path tmp = out.resolveSibling(out.getFileName() + ".tmp");
            Files.write(tmp, sb.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            try {
                Files.move(tmp, out, StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
            } catch (final IOException atomicUnsupported) {
                Files.move(tmp, out, StandardCopyOption.REPLACE_EXISTING);
            }
            System.err.println("[arena] game result spooled: " + out.getFileName());
        } catch (final IOException | RuntimeException e) {
            System.err.println("GameResultSpool: write failed: " + e.getMessage());
        }
    }

    /** Control typing by LobbyPlayer class — NEVER by name (plan F-24). */
    private static String controlOf(final Player p) {
        final LobbyPlayer lp = p.getLobbyPlayer();
        if (lp instanceof AdvisorLobbyPlayer) {
            return "human+advisor";
        }
        if (lp instanceof MailboxLobbyPlayer) {
            return "ai";
        }
        return "human";
    }

    private static Path resultsDir() {
        final String logs = System.getProperty("arena.runner.logs.dir", "");
        if (!logs.isEmpty()) {
            return Paths.get(logs).getParent().resolve("results");
        }
        return MailboxProtocol.baseDir().getParent().resolve("runner").resolve("results");
    }

    private static String esc(final String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static String ints(final List<Integer> xs) {
        final StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < xs.size(); i++) {
            if (i > 0) {
                b.append(", ");
            }
            b.append(xs.get(i));
        }
        return b.append("]").toString();
    }

    private static String intGroups(final List<List<Integer>> gs) {
        final StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < gs.size(); i++) {
            if (i > 0) {
                b.append(", ");
            }
            b.append(ints(gs.get(i)));
        }
        return b.append("]").toString();
    }
}
