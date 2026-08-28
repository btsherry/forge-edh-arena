package forge.arena.interactive;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.function.Function;

import com.google.common.collect.Lists;

import forge.StaticData;
import forge.ai.LobbyPlayerAi;
import forge.arena.bootstrap.ArenaBootstrap;
import forge.deck.Deck;
import forge.game.Game;
import forge.game.GameRules;
import forge.game.GameStage;
import forge.game.GameType;
import forge.game.Match;
import forge.game.card.Card;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.RegisteredPlayer;
import forge.game.zone.ZoneType;
import forge.item.IPaperCard;
import forge.model.FModel;

/**
 * Shared fixture for mailbox-seam tests (wave-2 cleanup, 2026-08-28): one
 * two-player Commander game (stock {@code opp} at seat A, mailbox {@code seat}
 * at seat B), a scripted brain thread, and the card-placement helper every
 * older test copy-pasted. New tests prefer DIRECT CALLS on the seat's
 * controller (cheap, no phase machinery) and use {@link #run} only when the
 * engine call-site itself is under test.
 */
final class MailboxTestKit {

    final Game game;
    final Player opp;
    final Player seat;
    final Path base;
    final List<String> seen =
            java.util.Collections.synchronizedList(new java.util.ArrayList<>());

    private volatile boolean brainAlive = true;

    MailboxTestKit(boolean oppActive) throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        base = Files.createTempDirectory("mbkit");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Commander);
        game = new Game(players, rules, new Match(rules, players, "t"));
        opp = game.getPlayers().get(0);
        seat = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, oppActive ? opp : seat);
        game.getPhaseHandler().onStackResolved();
    }

    static Card put(String name, Player p, ZoneType z) {
        IPaperCard pc = FModel.getMagicDb().getCommonCards().getCard(name);
        if (pc == null) {
            StaticData.instance().attemptToLoadCard(name);
            pc = FModel.getMagicDb().getCommonCards().getCard(name);
        }
        Card c = Card.fromPaperCard(pc, p);
        c.setGameTimestamp(p.getGame().getNextTimestamp());
        p.getZone(z).add(c);
        return c;
    }

    MailboxController controller() {
        return (MailboxController) seat.getController();
    }

    /** First option id in {@code body} whose label starts with {@code name}. */
    static String idOf(String body, String name) {
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile("\\{\"id\":(\\d+),\"label\":\"" + java.util.regex.Pattern.quote(name))
                .matcher(body);
        return m.find() ? m.group(1) : null;
    }

    /** Start the scripted brain: {@code responder} maps a request body to a
     *  response JSON; {@code null} answers the safe default. */
    void startBrain(Function<String, String> responder) {
        Path in = base.resolve("seat-" + seat.getId()).resolve("inbox");
        Path out = base.resolve("seat-" + seat.getId()).resolve("outbox");
        Thread t = new Thread(() -> {
            java.util.Set<String> done = new java.util.HashSet<>();
            while (brainAlive) {
                try {
                    if (Files.isDirectory(in)) {
                        for (Path f : Files.newDirectoryStream(in, "req-*.json")) {
                            String n = f.getFileName().toString();
                            if (done.contains(n)) continue;
                            String body = new String(Files.readAllBytes(f));
                            seen.add(body);
                            done.add(n);
                            String resp = responder.apply(body);
                            if (resp == null) {
                                resp = "{\"chosenId\": 0}";
                            }
                            Files.createDirectories(out);
                            Path tmp = out.resolve(n.replace("req-", "resp-") + ".tmp");
                            Files.write(tmp, resp.getBytes());
                            Files.move(tmp, out.resolve(n.replace("req-", "resp-")));
                        }
                    }
                    Thread.sleep(20);
                } catch (Exception e) { /* keep polling */ }
            }
        }, "mbkit-brain");
        t.setDaemon(true);
        t.start();
    }

    void stopBrain() {
        brainAlive = false;
    }

    /** Step the phase loop until {@code done} (or {@code maxSteps}). */
    void run(java.util.function.BooleanSupplier done, int maxSteps) {
        int steps = 0;
        while (steps++ < maxSteps && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            if (done.getAsBoolean() && game.getStack().isEmpty() && steps > 5) {
                break;
            }
        }
    }
}
