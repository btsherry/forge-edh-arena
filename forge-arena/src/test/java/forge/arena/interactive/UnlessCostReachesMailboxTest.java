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
 * Regression for the 2026-08-17 unless-cost defect (Urza's Transmute Artifact):
 * the seat sacrificed a Construct token (MV 0), fetched Mana Vault (MV 1), and
 * owed X=1 — Forge's "pay X unless" step went to STOCK, whose
 * ChangeZoneAi.willPayUnlessCost hard-refuses to pay for any non-creature, so
 * the Vault went to the graveyard although the seat had mana and wanted it.
 * With the override, the seat receives PAY_UNLESS, answers "pay", and the
 * artifact lands on the battlefield.
 */
public class UnlessCostReachesMailboxTest {

    /** Item 15 (2026-09-03): the scripted brain must not outlive its test —
     *  these pre-kit pollers used to spin for up to 150 s after their method
     *  returned, inside the one reused surefire fork. */
    private static volatile boolean legacyBrainAlive = true;

    @org.testng.annotations.BeforeMethod
    public void armLegacyBrain() {
        legacyBrainAlive = true;
    }

    @org.testng.annotations.AfterMethod(alwaysRun = true)
    public void stopLegacyBrain() {
        legacyBrainAlive = false;
    }

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
    public void transmuteArtifactPaysTheDifferenceThroughTheSeat() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Path base = Files.createTempDirectory("unless-mb");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Constructed);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();

        // library: the target + filler; battlefield: a cheap artifact to sac
        // (Ornithopter, MV 0) and mana for the spell {1}{U}{U} plus X=1
        put("Mana Vault", p, ZoneType.Library);
        put("Sol Ring", p, ZoneType.Library);
        put("Island", p, ZoneType.Library);
        put("Ornithopter", p, ZoneType.Battlefield);
        for (int i = 0; i < 6; i++) put("Island", p, ZoneType.Battlefield);
        Card transmute = put("Transmute Artifact", p, ZoneType.Hand);

        Path inbox = base.resolve("seat-" + p.getId()).resolve("inbox");
        Path outbox = base.resolve("seat-" + p.getId()).resolve("outbox");
        java.util.List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Thread brain = new Thread(() -> {
            long end = System.currentTimeMillis() + 150_000;
            java.util.Set<String> done = new java.util.HashSet<>();
            while (legacyBrainAlive && System.currentTimeMillis() < end) {
                try {
                    if (Files.isDirectory(inbox)) {
                        for (Path f : Files.newDirectoryStream(inbox, "req-*.json")) {
                            String n = f.getFileName().toString();
                            if (done.contains(n)) continue;
                            String body = new String(Files.readAllBytes(f));
                            seen.add(body); done.add(n);
                            String resp;
                            if (body.contains("\"decisionType\":\"CAST_SPELL\"")) {
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("^(\\d+)$").matcher(String.valueOf(MailboxTestKit.idOf(body, "Transmute Artifact")));
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "0") + "}";
                            } else if (body.contains("\"decisionType\":\"CHOOSE_CARD\"")) {
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("^(\\d+)$").matcher(String.valueOf(MailboxTestKit.idOf(body, "Mana Vault")));
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "0") + "}";
                            } else if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")) {
                                // sacrifice choice: pick Ornithopter
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("^(\\d+)$").matcher(String.valueOf(MailboxTestKit.idOf(body, "Ornithopter")));
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "1") + "}";
                            } else if (body.contains("\"decisionType\":\"PAY_UNLESS\"")) {
                                resp = "{\"chosenId\": 1}";      // PAY the difference
                            } else if (body.contains("\"decisionType\":\"CONFIRM\"")) {
                                resp = "{\"chosenId\": 1}";
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
        }, "test-brain-unless");
        brain.setDaemon(true);
        brain.start();

        int steps = 0;
        boolean cast = false;
        while (steps++ < 500 && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            boolean inHand = false;
            for (Card c : p.getCardsIn(ZoneType.Hand)) inHand |= c.getName().equals("Transmute Artifact");
            if (!inHand) cast = true;
            if (cast && game.getStack().isEmpty() && steps > 40) break;
        }
        boolean vaultOnBf = false, vaultInGy = false;
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) vaultOnBf |= c.getName().equals("Mana Vault");
        for (Card c : p.getCardsIn(ZoneType.Graveyard)) vaultInGy |= c.getName().equals("Mana Vault");
        System.out.println("UNLESS test: cast=" + cast + " reqs=" + seen.size()
                + " payUnlessAsked=" + seen.stream().anyMatch(x -> x.contains("PAY_UNLESS"))
                + " vaultOnBf=" + vaultOnBf + " vaultInGy=" + vaultInGy);
        Assert.assertTrue(cast, "Transmute Artifact was never cast through the mailbox");
        Assert.assertTrue(seen.stream().anyMatch(x -> x.contains("PAY_UNLESS")),
                "the pay-X-unless decision never reached the seat");
        Assert.assertTrue(vaultOnBf, "Mana Vault should be on the battlefield after paying X "
                + "(defect: stock refuses to pay for non-creatures -> graveyard)");
        Assert.assertFalse(vaultInGy, "Mana Vault must not be binned");
    }

    private static boolean has(Player p, ZoneType z, String name) {
        for (Card c : p.getCardsIn(z)) {
            if (name.equals(c.getName())) {
                return true;
            }
        }
        return false;
    }

    /**
     * BL-11 second card (group {@code extended}). Abandon Attachments carries
     * the exact script triple that routes Transmute Artifact's X to the seat:
     * {@code UnlessCost$ ... | UnlessPayer$ You | UnlessSwitched$ True} on the
     * seat's OWN spell ({@code A:SP$ Draw | NumCards$ 2 | UnlessCost$
     * Discard<1/Card> | UnlessPayer$ You | UnlessSwitched$ True}). The unless
     * cost is a discard rather than X mana, so the seat must both decide to
     * pay (PAY_UNLESS) and name the discarded card (DISCARD PAYMENT), and the
     * "if you do" draw must then actually happen.
     */
    @Test(groups = "extended", timeOut = 240_000)
    public void abandonAttachmentsDiscardUnlessReachesTheSeat() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Abandon Attachments", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Swamp", k.seat, ZoneType.Hand);                 // the discard
            MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Hand);   // must survive
            for (int i = 0; i < 4; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Island", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            k.startBrain(body -> {
                if (body.contains("DISCARD PAYMENT")) {
                    String id = MailboxTestKit.idOf(body, "Swamp");
                    return id != null ? "{\"chosen\": [" + id + "]}" : null;
                }
                if (body.contains("\"decisionType\":\"PAY_UNLESS\"")) {
                    return "{\"chosenId\": 1}";      // PAY: discard, then draw two
                }
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Abandon Attachments");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                return null;
            });
            k.run(() -> played[0] && has(k.seat, ZoneType.Graveyard, "Swamp"), 300);

            boolean payUnlessAsked = k.seen.stream().anyMatch(s -> s.contains("\"decisionType\":\"PAY_UNLESS\""));
            boolean discardWindow = k.seen.stream().anyMatch(s -> s.contains("DISCARD PAYMENT"));
            int lib = k.seat.getCardsIn(ZoneType.Library).size();
            int hand = k.seat.getCardsIn(ZoneType.Hand).size();
            System.out.println("UNLESS-DISCARD test: cast=" + played[0] + " payUnlessAsked=" + payUnlessAsked
                    + " discardWindow=" + discardWindow + " swampInGy=" + has(k.seat, ZoneType.Graveyard, "Swamp")
                    + " lib=" + lib + " hand=" + hand + " reqs=" + k.seen.size());
            Assert.assertTrue(played[0], "Abandon Attachments was never cast through the mailbox");
            Assert.assertTrue(payUnlessAsked, "the discard-unless decision never reached the seat");
            Assert.assertTrue(discardWindow, "WHICH card is discarded must be the seat's pick");
            Assert.assertTrue(has(k.seat, ZoneType.Graveyard, "Swamp"), "the seat's named discard must be the card discarded");
            Assert.assertTrue(has(k.seat, ZoneType.Hand, "Craterhoof Behemoth"), "the high-value card must survive");
            Assert.assertEquals(lib, 2, "paying the unless cost must draw two (library 4 -> 2)");
            Assert.assertEquals(hand, 3, "hand = Craterhoof + the two drawn Plains");
        }
    }
}
