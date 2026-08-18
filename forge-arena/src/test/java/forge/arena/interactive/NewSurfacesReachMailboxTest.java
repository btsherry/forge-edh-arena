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
import forge.card.ICardFace;
import forge.deck.Deck;
import forge.game.Game;
import forge.game.GameRules;
import forge.game.GameStage;
import forge.game.GameType;
import forge.game.Match;
import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.card.CardCollectionView;
import forge.game.card.CardState;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.PlayerController;
import forge.game.player.RegisteredPlayer;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import forge.item.IPaperCard;
import forge.model.FModel;

/**
 * Backlog item 4 (2026-08-17): four decision surfaces that still ran on
 * stock AI now reach the seat — discard selection (end-to-end through a
 * Faithless Looting-class rummage), face pick, state/side pick, and
 * cost-reduction number (direct invocation through the live bus).
 */
public class NewSurfacesReachMailboxTest {

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
            base = Files.createTempDirectory("surfaces-mb");
            List<RegisteredPlayer> players = Lists.newArrayList();
            Deck d = new Deck();
            players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
            players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
            GameRules rules = new GameRules(GameType.Commander);
            game = new Game(players, rules, new Match(rules, players, "t"));
            opp = game.getPlayers().get(0);
            seat = game.getPlayers().get(1);
            game.setAge(GameStage.Play);
            game.getPhaseHandler().devModeSet(PhaseType.MAIN1, seat);
            game.getPhaseHandler().onStackResolved();
            startBrain();
        }

        private void startBrain() {
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
            }, "test-brain-surfaces");
            t.setDaemon(true);
            t.start();
        }
    }

    private static String pick(String body, String regex) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(regex).matcher(body);
        return m.find() ? m.group(1) : null;
    }

    private static String ids(String body, String... names) {
        StringBuilder sb = new StringBuilder("[");
        for (String name : names) {
            String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"" + name);
            if (id == null) return null;
            if (sb.length() > 1) sb.append(",");
            sb.append(id);
        }
        return sb.append("]").toString();
    }

    private static String answer(String body) {
        if (body.contains("\"decisionType\":\"CAST_SPELL\"")) {
            String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Faithless Looting");
            return "{\"chosenId\": " + (id != null ? id : "0") + "}";
        }
        if (body.contains("\"decisionType\":\"CHOOSE_CARDS\"") && body.contains("DISCARD")) {
            String chosen = ids(body, "Lightning Bolt", "Giant Growth");
            return chosen != null ? "{\"chosen\": " + chosen + "}" : "{\"chosen\": []}";
        }
        if (body.contains("\"decisionType\":\"CHOOSE_CARDS\"") && body.contains("Pick two")) {
            String chosen = ids(body, "Sol Ring", "Arcane Signet");
            return chosen != null ? "{\"chosen\": " + chosen + "}" : "{\"chosen\": []}";
        }
        if (body.contains("\"decisionType\":\"CHOOSE_CARD\"") && body.contains("CHOOSE FACE")) {
            String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Ice");
            return "{\"chosenId\": " + (id != null ? id : "0") + "}";
        }
        if (body.contains("\"decisionType\":\"CHOOSE_CARD\"") && body.contains("CHOOSE STATE")) {
            String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Mountain");
            return "{\"chosenId\": " + (id != null ? id : "0") + "}";
        }
        if (body.contains("\"decisionType\":\"CHOOSE_NUMBER\"") && body.contains("COST REDUCTION")) {
            return "{\"chosen\": 2}";
        }
        return "{\"chosenId\": 0}";
    }

    @Test(timeOut = 240_000)
    public void discardSelectionReachesSeatEndToEnd() throws Exception {
        Fixture fx = new Fixture();
        put("Faithless Looting", fx.seat, ZoneType.Hand);
        put("Lightning Bolt", fx.seat, ZoneType.Hand);
        put("Shock", fx.seat, ZoneType.Hand);
        put("Giant Growth", fx.seat, ZoneType.Hand);
        put("Mountain", fx.seat, ZoneType.Battlefield);
        for (int i = 0; i < 4; i++) put("Mountain", fx.seat, ZoneType.Library);
        for (int i = 0; i < 2; i++) put("Island", fx.opp, ZoneType.Library);

        int steps = 0;
        boolean discarded = false;
        while (steps++ < 300 && !fx.game.isGameOver()) {
            fx.game.getPhaseHandler().mainLoopStep();
            boolean boltGy = false, growthGy = false;
            for (Card c : fx.seat.getCardsIn(ZoneType.Graveyard)) {
                boltGy |= c.getName().equals("Lightning Bolt");
                growthGy |= c.getName().equals("Giant Growth");
            }
            if (boltGy && growthGy && fx.game.getStack().isEmpty()) {
                discarded = true;
                break;
            }
        }
        boolean surfaced = fx.seen.stream().anyMatch(s ->
                s.contains("\"decisionType\":\"CHOOSE_CARDS\"") && s.contains("DISCARD"));
        boolean shockInHand = false;
        for (Card c : fx.seat.getCardsIn(ZoneType.Hand)) shockInHand |= c.getName().equals("Shock");
        System.out.println("DISCARD test: surfaced=" + surfaced + " discarded=" + discarded
                + " shockInHand=" + shockInHand + " reqs=" + fx.seen.size());
        Assert.assertTrue(surfaced, "the discard choice never reached the seat as CHOOSE_CARDS");
        Assert.assertTrue(discarded, "the SEAT-CHOSEN discards (Bolt+Growth) did not happen");
        Assert.assertTrue(shockInHand, "Shock was discarded although the seat chose Bolt+Growth");
    }

    @Test(timeOut = 240_000)
    public void facesStatesNumbersAndEffectCardsReachSeat() throws Exception {
        Fixture fx = new Fixture();
        Card bolt = put("Lightning Bolt", fx.seat, ZoneType.Hand);
        Card island = put("Island", fx.seat, ZoneType.Battlefield);
        Card mountain = put("Mountain", fx.seat, ZoneType.Battlefield);
        Card ring = put("Sol Ring", fx.seat, ZoneType.Battlefield);
        Card signet = put("Arcane Signet", fx.seat, ZoneType.Battlefield);
        Card vault = put("Mana Vault", fx.seat, ZoneType.Battlefield);
        PlayerController pc = fx.seat.getController();
        SpellAbility sa = bolt.getFirstSpellAbility();

        // face pick: Fire // Ice — brain takes Ice
        IPaperCard fireIce = FModel.getMagicDb().getCommonCards().getCard("Fire // Ice");
        Assert.assertNotNull(fireIce, "Fire // Ice missing from DB");
        List<ICardFace> faces = Lists.newArrayList(
                fireIce.getRules().getMainPart(), fireIce.getRules().getOtherPart());
        ICardFace face = pc.chooseSingleCardFace(sa, faces, "Choose a half");
        Assert.assertNotNull(face, "face pick fell to null");
        Assert.assertEquals(face.getName(), "Ice", "the seat-chosen face was not honored");

        // state pick — brain takes the Mountain state
        List<CardState> states = Lists.newArrayList(
                island.getCurrentState(), mountain.getCurrentState());
        CardState st = pc.chooseSingleCardState(sa, states, "Choose a side", null);
        Assert.assertNotNull(st);
        Assert.assertEquals(st.getName(), "Mountain", "the seat-chosen state was not honored");

        // cost-reduction number — brain answers 2
        int n = pc.chooseNumberForCostReduction(sa, 0, 3);
        Assert.assertEquals(n, 2, "the seat-chosen reduction number was not honored");

        // generic choose-cards-for-effect — brain takes Sol Ring + Arcane Signet
        CardCollection pool = new CardCollection();
        pool.add(ring);
        pool.add(signet);
        pool.add(vault);
        CardCollectionView chosen = pc.chooseCardsForEffect(pool, sa,
                "Pick two artifacts", 2, 2, false, null);
        Assert.assertNotNull(chosen);
        Assert.assertEquals(chosen.size(), 2);
        Assert.assertTrue(chosen.contains(ring) && chosen.contains(signet),
                "the seat-chosen cards were not honored: " + chosen);

        System.out.println("SURFACES test: face=" + face.getName() + " state=" + st.getName()
                + " n=" + n + " effectCards=" + chosen + " reqs=" + fx.seen.size());
    }
}
