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
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import forge.item.IPaperCard;
import forge.model.FModel;

/**
 * 2026-08-17 game 5: Urza (mailbox seat) held Fierce Guardianship for sixteen
 * windows, fired it at Nature's Rhythm, targeted the Rhythm through
 * CHOOSE_ENTITY — and the Rhythm resolved anyway, fetching Craterhoof. Two
 * defects were suspected: (1) the FREE alternative cost was never offered
 * (getSpellAbilities strips alt-cost SAs; the seat paid {2}{U}{U} believing
 * it free); (2) the counter did not counter. This test casts a counterspell
 * from a mailbox seat at an opponent's spell on the stack and asserts the
 * target is countered, and that a free-if-commander alt cost is OFFERED as a
 * distinct option when the seat controls its commander.
 */
public class CounterspellReachesTargetTest {

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

    @Test(timeOut = 240_000)
    public void guardianshipOfferedFreeAndCountersTheTarget() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Path base = Files.createTempDirectory("counter-mb");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player opp = game.getPlayers().get(0);
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        // opponent's turn, main phase: they will have a spell on the stack
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, opp);
        game.getPhaseHandler().onStackResolved();

        // seat controls its commander -> Guardianship should be castable for {0}
        Card urza = put("Urza, Lord High Artificer", p, ZoneType.Battlefield);
        p.addCommander(urza);
        for (int i = 0; i < 4; i++) put("Island", p, ZoneType.Battlefield);
        put("Fierce Guardianship", p, ZoneType.Hand);

        // opponent casts a noncreature spell (Divination) — put it on the stack
        for (int i = 0; i < 3; i++) put("Island", opp, ZoneType.Battlefield);
        // A LIBRARY for the opponent: with an empty library an UNcountered
        // Divination draws nothing and still hits the graveyard, which made
        // this test pass for months while the seat targeted the Divination
        // CARD (never countering anything). Now a resolved Divination is
        // visible as +2 cards in hand / -2 in library.
        for (int i = 0; i < 6; i++) put("Island", opp, ZoneType.Library);
        Card div = put("Divination", opp, ZoneType.Hand);
        SpellAbility divSa = div.getFirstSpellAbility();
        divSa.setActivatingPlayer(opp);
        game.getAction().moveToStack(div, divSa);
        game.getStack().add(divSa);

        Path inbox = base.resolve("seat-" + p.getId()).resolve("inbox");
        Path outbox = base.resolve("seat-" + p.getId()).resolve("outbox");
        java.util.List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Thread brain = new Thread(() -> {
            long end = System.currentTimeMillis() + 150_000;
            java.util.Set<String> done = new java.util.HashSet<>();
            while (System.currentTimeMillis() < end) {
                try {
                    if (Files.isDirectory(inbox)) {
                        for (Path f : Files.newDirectoryStream(inbox, "req-*.json")) {
                            String n = f.getFileName().toString();
                            if (done.contains(n)) continue;
                            String body = new String(Files.readAllBytes(f));
                            seen.add(body); done.add(n);
                            String resp;
                            if (body.contains("\"decisionType\":\"REACT\"") || body.contains("\"decisionType\":\"CAST_SPELL\"")) {
                                // prefer the FREE Guardianship option if offered, else any Guardianship
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("\"id\"\\s*:\\s*(\\d+)[^}]*Fierce Guardianship[^}]*FREE").matcher(body);
                                if (!m.find()) {
                                    m = java.util.regex.Pattern
                                            .compile("\"id\"\\s*:\\s*(\\d+)[^}]*Fierce Guardianship").matcher(body);
                                    if (!m.find()) { resp = "{\"chosenId\": 0}"; }
                                    else resp = "{\"chosenId\": " + m.group(1) + "}";
                                } else resp = "{\"chosenId\": " + m.group(1) + "}";
                            } else if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")) {
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("\"id\"\\s*:\\s*(\\d+)[^}]*Divination").matcher(body);
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "1") + "}";
                            } else {
                                resp = "{\"chosenId\": 0}";
                            }
                            Files.createDirectories(outbox);
                            Path tmp = outbox.resolve(n.replace("req-", "resp-") + ".tmp");
                            Files.write(tmp, resp.getBytes());
                            Files.move(tmp, outbox.resolve(n.replace("req-", "resp-")));
                        }
                    }
                    Thread.sleep(30);
                } catch (Exception e) { /* keep polling */ }
            }
        }, "test-brain-counter");
        brain.setDaemon(true);
        brain.start();

        int steps = 0;
        while (steps++ < 300 && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            if (game.getStack().isEmpty() && steps > 20) break;
        }
        boolean divInGy = false, divInHand = false;
        for (Card c : opp.getCardsIn(ZoneType.Graveyard)) divInGy |= c.getName().equals("Divination");
        for (Card c : opp.getCardsIn(ZoneType.Hand)) divInHand |= c.getName().equals("Divination");
        int oppHand = opp.getCardsIn(ZoneType.Hand).size();
        boolean freeOffered = seen.stream().anyMatch(s -> s.contains("Fierce Guardianship") && s.contains("FREE"));
        boolean guardOffered = seen.stream().anyMatch(s -> s.contains("Fierce Guardianship"));
        boolean targeted = seen.stream().anyMatch(s -> s.contains("CHOOSE_ENTITY") && s.contains("Divination"));
        for (String sreq : seen) {
            int i = sreq.indexOf("\"options\"");
            System.out.println("   REQ: " + sreq.substring(0, Math.min(90, sreq.length())) + " ... " + (i >= 0 ? sreq.substring(i, Math.min(i + 700, sreq.length())) : ""));
        }
        System.out.println("COUNTER test: guardOffered=" + guardOffered + " freeOffered=" + freeOffered
                + " targeted=" + targeted + " divInGy=" + divInGy + " oppHand=" + oppHand
                + " reqs=" + seen.size());
        Assert.assertTrue(guardOffered, "Guardianship never offered as a response");
        Assert.assertTrue(freeOffered, "the FREE alternative cost was not offered as a distinct option");
        Assert.assertTrue(targeted, "the counter's target choice never reached the seat");
        // Divination countered => it never drew (opp hand stays 0) and it is in the graveyard
        Assert.assertTrue(divInGy, "Divination should be countered (in graveyard)");
        Assert.assertEquals(oppHand, 0, "Divination must not have resolved (opponent drew cards)");
        Assert.assertEquals(opp.getCardsIn(ZoneType.Library).size(), 6,
                "opponent library must be untouched — a resolved Divination draws two");
        Assert.assertTrue(seen.stream().anyMatch(s -> s.contains("CHOOSE_ENTITY") && s.contains("\"STACK\"")),
                "the counter's target must be offered as a STACK item (spell), not the stack-zone card");
    }

    /** Live shape (game 5): the seat paid {2}{U} for Guardianship (its
     *  commander-free option was not offered) and the counter did NOT counter.
     *  Cast at full cost with no commander -> the target must still be countered. */
    @Test(timeOut = 240_000)
    public void paidGuardianshipStillCounters() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Path base = Files.createTempDirectory("counter-paid-mb");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player opp = game.getPlayers().get(0);
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, opp);
        game.getPhaseHandler().onStackResolved();
        // NO commander on the battlefield: only the paid version exists.
        // Mana exactly like live: Mana Vault + Islands.
        put("Mana Vault", p, ZoneType.Battlefield);
        for (int i = 0; i < 3; i++) put("Island", p, ZoneType.Battlefield);
        put("Fierce Guardianship", p, ZoneType.Hand);
        for (int i = 0; i < 3; i++) put("Island", opp, ZoneType.Battlefield);
        // A LIBRARY for the opponent: with an empty library an UNcountered
        // Divination draws nothing and still hits the graveyard, which made
        // this test pass for months while the seat targeted the Divination
        // CARD (never countering anything). Now a resolved Divination is
        // visible as +2 cards in hand / -2 in library.
        for (int i = 0; i < 6; i++) put("Island", opp, ZoneType.Library);
        Card div = put("Divination", opp, ZoneType.Hand);
        SpellAbility divSa = div.getFirstSpellAbility();
        divSa.setActivatingPlayer(opp);
        game.getAction().moveToStack(div, divSa);
        game.getStack().add(divSa);

        Path inbox = base.resolve("seat-" + p.getId()).resolve("inbox");
        Path outbox = base.resolve("seat-" + p.getId()).resolve("outbox");
        java.util.List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Thread brain = new Thread(() -> {
            long end = System.currentTimeMillis() + 150_000;
            java.util.Set<String> done = new java.util.HashSet<>();
            while (System.currentTimeMillis() < end) {
                try {
                    if (Files.isDirectory(inbox)) {
                        for (Path f : Files.newDirectoryStream(inbox, "req-*.json")) {
                            String n = f.getFileName().toString();
                            if (done.contains(n)) continue;
                            String body = new String(Files.readAllBytes(f));
                            seen.add(body); done.add(n);
                            String resp;
                            if (body.contains("\"decisionType\":\"REACT\"") || body.contains("\"decisionType\":\"CAST_SPELL\"")) {
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("\"id\"\\s*:\\s*(\\d+)[^}]*Fierce Guardianship").matcher(body);
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "0") + "}";
                            } else if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")) {
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("\"id\"\\s*:\\s*(\\d+)[^}]*Divination").matcher(body);
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "1") + "}";
                            } else {
                                resp = "{\"chosenId\": 0}";
                            }
                            Files.createDirectories(outbox);
                            Path tmp = outbox.resolve(n.replace("req-", "resp-") + ".tmp");
                            Files.write(tmp, resp.getBytes());
                            Files.move(tmp, outbox.resolve(n.replace("req-", "resp-")));
                        }
                    }
                    Thread.sleep(30);
                } catch (Exception e) { /* keep polling */ }
            }
        }, "test-brain-counter-paid");
        brain.setDaemon(true);
        brain.start();

        int steps = 0;
        while (steps++ < 300 && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            if (game.getStack().isEmpty() && steps > 20) break;
        }
        boolean divInGy = false;
        for (Card c : opp.getCardsIn(ZoneType.Graveyard)) divInGy |= c.getName().equals("Divination");
        int oppHand = opp.getCardsIn(ZoneType.Hand).size();
        boolean cast = true;
        for (Card c : p.getCardsIn(ZoneType.Hand)) if (c.getName().equals("Fierce Guardianship")) cast = false;
        System.out.println("PAID COUNTER test: cast=" + cast + " divInGy=" + divInGy + " oppHand=" + oppHand
                + " seatHand=" + p.getCardsIn(ZoneType.Hand) + " seatGy=" + p.getCardsIn(ZoneType.Graveyard)
                + " reqs=" + seen.size());
        Assert.assertTrue(cast, "Guardianship was never cast");
        Assert.assertTrue(divInGy && oppHand == 0, "paid Guardianship must still counter its target");
        Assert.assertEquals(opp.getCardsIn(ZoneType.Library).size(), 6,
                "opponent library must be untouched — a resolved Divination draws two");
    }
}
