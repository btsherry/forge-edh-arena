package forge.arena.interactive;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

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
 * Symmetry-break offers (game 7, 2026-08-17): a seat controlling a permanent
 * whose continuous static is active only "as long as ~ is untapped" AND
 * restricts PLAYERS (Winter Orb / Static Orb / Storage Matrix class) is
 * offered — at windows on the turn right before its own — the play "tap the
 * piece through an outlet, with the piece pre-selected as the tap payment".
 * The piece then sits tapped through the seat's untap step (restriction off
 * for the seat alone) and untaps during that same untap step to re-lock the
 * table.
 *
 * <p>Generality is the point (detect by script metadata, never card names):
 * two distinct pieces through two distinct outlet kinds, plus a negative —
 * a self-buff "while untapped" card must never be offered.
 */
public class TapSymmetryBreakTest {

    private static Card put(String name, Player p, ZoneType z) {
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

    private static final class Fixture {
        final Game game;
        final Player opp;
        final Player seat;
        final List<String> seen =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        final Path base;

        Fixture() throws Exception {
            ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
            base = Files.createTempDirectory("sym-break");
            List<RegisteredPlayer> players = Lists.newArrayList();
            Deck d = new Deck();
            players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
            players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
            GameRules rules = new GameRules(GameType.Commander);
            game = new Game(players, rules, new Match(rules, players, "t"));
            opp = game.getPlayers().get(0);
            seat = game.getPlayers().get(1);
            game.setAge(GameStage.Play);
        }

        void startAtOppEndStep() {
            game.getPhaseHandler().devModeSet(PhaseType.END_OF_TURN, opp);
            game.getPhaseHandler().onStackResolved();
        }

        /** Answer loop for the seat; routes by content. */
        Thread startBrain() {
            Path inbox = base.resolve("seat-" + seat.getId()).resolve("inbox");
            Path outbox = base.resolve("seat-" + seat.getId()).resolve("outbox");
            Thread t = new Thread(() -> {
                long end = System.currentTimeMillis() + 150_000;
                java.util.Set<String> done = new java.util.HashSet<>();
                while (System.currentTimeMillis() < end) {
                    try {
                        if (Files.isDirectory(inbox)) {
                            for (Path f : Files.newDirectoryStream(inbox, "req-*.json")) {
                                String n = f.getFileName().toString();
                                if (done.contains(n)) continue;
                                String body = new String(Files.readAllBytes(f));
                                seen.add(body);
                                done.add(n);
                                String resp = answer(body);
                                Files.createDirectories(outbox);
                                Path tmp = outbox.resolve(n.replace("req-", "resp-") + ".tmp");
                                Files.write(tmp, resp.getBytes());
                                Files.move(tmp, outbox.resolve(n.replace("req-", "resp-")));
                            }
                        }
                        Thread.sleep(25);
                    } catch (Exception e) { /* keep polling */ }
                }
            }, "test-brain-sym");
            t.setDaemon(true);
            t.start();
            return t;
        }

        void runUntilSeatMain1() {
            int steps = 0;
            while (steps++ < 300 && !game.isGameOver()) {
                game.getPhaseHandler().mainLoopStep();
                if (game.getPhaseHandler().getPlayerTurn() == seat
                        && game.getPhaseHandler().getPhase() == PhaseType.MAIN1) {
                    break;
                }
            }
        }

        int untapped(String name) {
            int n = 0;
            for (Card c : seat.getCardsIn(ZoneType.Battlefield)) {
                if (c.getName().equals(name) && c.isUntapped()) n++;
            }
            return n;
        }
    }

    private static String pick(String body, String regex) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(regex).matcher(body);
        return m.find() ? m.group(1) : null;
    }

    private static String answer(String body) {
        if (body.contains("[SYMMETRY BREAK]")
                && (body.contains("\"decisionType\":\"REACT\"")
                    || body.contains("\"decisionType\":\"CAST_SPELL\""))) {
            String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"\\[SYMMETRY BREAK\\]");
            if (id != null) {
                return "{\"chosenId\": " + id + "}";
            }
        }
        if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")) {
            // Clock of Omens' untap target: aim at the Clock itself, NEVER the
            // symmetry piece (untapping it would defeat the play)
            String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Clock of Omens");
            if (id == null) {
                id = pick(body, "\\{\"id\":(\\d+),\"label\":");
            }
            return "{\"chosenId\": " + (id != null ? id : "0") + "}";
        }
        return "{\"chosenId\": 0}";
    }

    @Test(timeOut = 240_000)
    public void winterOrbTappedViaUrzaAtEndStepFreesOwnUntap() throws Exception {
        Fixture fx = new Fixture();
        Card orb = put("Winter Orb", fx.seat, ZoneType.Battlefield);
        put("Urza, Lord High Artificer", fx.seat, ZoneType.Battlefield);
        for (int i = 0; i < 5; i++) {
            put("Island", fx.seat, ZoneType.Battlefield).setTapped(true);
        }
        for (int i = 0; i < 3; i++) put("Island", fx.seat, ZoneType.Library);
        for (int i = 0; i < 2; i++) put("Plains", fx.opp, ZoneType.Library);
        fx.startAtOppEndStep();
        fx.startBrain();
        fx.runUntilSeatMain1();

        boolean offered = fx.seen.stream().anyMatch(s -> s.contains("[SYMMETRY BREAK]")
                && s.contains("Winter Orb") && s.contains("Urza"));
        System.out.println("SYM-URZA: offered=" + offered
                + " untappedIslands=" + fx.untapped("Island")
                + " orbUntapped=" + orb.isUntapped() + " reqs=" + fx.seen.size());
        Assert.assertTrue(offered,
                "the end-step window never offered tapping Winter Orb via Urza");
        Assert.assertTrue(fx.untapped("Island") >= 4,
                "the symmetry break failed: lands stayed locked (Winter Orb "
                + "restriction applied to the seat's own untap step)");
        Assert.assertTrue(orb.isUntapped(),
                "Winter Orb should untap during the seat's own untap step (re-armed)");
    }

    @Test(timeOut = 240_000)
    public void staticOrbTappedViaClockOfOmensFreesOwnUntap() throws Exception {
        Fixture fx = new Fixture();
        Card orb = put("Static Orb", fx.seat, ZoneType.Battlefield);
        put("Clock of Omens", fx.seat, ZoneType.Battlefield);
        put("Sol Ring", fx.seat, ZoneType.Battlefield);
        for (int i = 0; i < 5; i++) {
            put("Plains", fx.seat, ZoneType.Battlefield).setTapped(true);
        }
        for (int i = 0; i < 3; i++) put("Plains", fx.seat, ZoneType.Library);
        for (int i = 0; i < 2; i++) put("Island", fx.opp, ZoneType.Library);
        fx.startAtOppEndStep();
        fx.startBrain();
        fx.runUntilSeatMain1();

        boolean offered = fx.seen.stream().anyMatch(s -> s.contains("[SYMMETRY BREAK]")
                && s.contains("Static Orb") && s.contains("Clock of Omens"));
        System.out.println("SYM-CLOCK: offered=" + offered
                + " untappedPlains=" + fx.untapped("Plains")
                + " orbUntapped=" + orb.isUntapped() + " reqs=" + fx.seen.size());
        Assert.assertTrue(offered,
                "the end-step window never offered tapping Static Orb via Clock of Omens");
        Assert.assertTrue(fx.untapped("Plains") >= 4,
                "the symmetry break failed under Static Orb: the untap step "
                + "stayed restricted to two permanents");
    }

    @Test(timeOut = 240_000)
    public void selfBuffWhileUntappedIsNeverOffered() throws Exception {
        Fixture fx = new Fixture();
        // Paradise Druid: hexproof "as long as it's untapped" — a SELF buff.
        // Springleaf Drum: "T, Tap an untapped creature you control: add mana"
        // — a valid outlet, but there is no symmetry piece, so no offer.
        put("Paradise Druid", fx.seat, ZoneType.Battlefield);
        put("Springleaf Drum", fx.seat, ZoneType.Battlefield);
        for (int i = 0; i < 3; i++) {
            put("Forest", fx.seat, ZoneType.Battlefield).setTapped(true);
        }
        for (int i = 0; i < 3; i++) put("Forest", fx.seat, ZoneType.Library);
        for (int i = 0; i < 2; i++) put("Island", fx.opp, ZoneType.Library);
        fx.startAtOppEndStep();
        fx.startBrain();
        fx.runUntilSeatMain1();

        boolean offered = fx.seen.stream().anyMatch(s -> s.contains("[SYMMETRY BREAK]"));
        System.out.println("SYM-NEG: offered=" + offered + " reqs=" + fx.seen.size());
        Assert.assertFalse(offered,
                "a self-buff 'while untapped' permanent (Paradise Druid) must "
                + "never be offered as a symmetry break — tapping it only hurts");
    }
}
