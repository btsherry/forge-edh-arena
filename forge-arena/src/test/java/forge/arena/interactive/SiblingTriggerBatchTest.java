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
 * Game-12 finding 1 (2026-08-19): MANY simultaneous identical optional
 * targeted triggers (Aura Shards x N off a multi-token ETB). Some resolved
 * with "(none set)" targets and were labeled FIZZLE. This pins the mechanism:
 * one Raise the Alarm = two simultaneous Aura Shards triggers; the seat aims
 * the first at a real artifact and declines the second. Asserts the aimed
 * sibling destroys its target, the declined one no-ops without contaminating
 * anything, and records whether the aim window offered a decline (min==0).
 */
public class SiblingTriggerBatchTest {

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
    public void simultaneousOptionalTriggersAimAndDeclineIndependently() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Path base = Files.createTempDirectory("sibling-mb");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player opp = game.getPlayers().get(0);
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();

        put("Aura Shards", p, ZoneType.Battlefield);
        put("Raise the Alarm", p, ZoneType.Hand);     // two tokens -> two triggers
        for (int i = 0; i < 3; i++) put("Plains", p, ZoneType.Battlefield);
        for (int i = 0; i < 2; i++) put("Plains", p, ZoneType.Library);
        Card ring = put("Sol Ring", opp, ZoneType.Battlefield);
        Card vault = put("Mana Vault", opp, ZoneType.Battlefield);
        for (int i = 0; i < 2; i++) put("Island", opp, ZoneType.Library);

        Path inbox = base.resolve("seat-" + p.getId()).resolve("inbox");
        Path outbox = base.resolve("seat-" + p.getId()).resolve("outbox");
        java.util.List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        final boolean[] aimedOnce = {false};
        final boolean[] confirmedOnce = {false};
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
                                        .compile("\\{\"id\":(\\d+),\"label\":\"Raise the Alarm").matcher(body);
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "0") + "}";
                            } else if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")
                                    && body.contains("Aura Shards")) {
                                if (!aimedOnce[0]) {
                                    java.util.regex.Matcher m = java.util.regex.Pattern
                                            .compile("\\{\"id\":(\\d+),\"label\":\"Sol Ring").matcher(body);
                                    if (m.find()) { aimedOnce[0] = true; resp = "{\"chosenId\": " + m.group(1) + "}"; }
                                    else resp = "{\"chosenId\": 0}";
                                } else {
                                    // second sibling: DECLINE via the explicit option
                                    resp = "{\"chosenId\": 0}";
                                }
                            } else if (body.contains("\"decisionType\":\"CONFIRM\"")) {
                                if (!confirmedOnce[0]) { confirmedOnce[0] = true; resp = "{\"chosenId\": 1}"; }
                                else resp = "{\"chosenId\": 0}";
                            } else {
                                resp = "{\"chosenId\": 0}";
                            }
                            Files.createDirectories(outbox);
                            Path tmp = outbox.resolve(n.replace("req-", "resp-") + ".tmp");
                            Files.write(tmp, resp.getBytes());
                            Files.move(tmp, outbox.resolve(n.replace("req-", "resp-")));
                        }
                    }
                    Thread.sleep(25);
                } catch (Exception e) { /* keep polling */ }
            }
        }, "test-brain-sibling");
        brain.setDaemon(true);
        brain.start();

        int steps = 0;
        while (steps++ < 400 && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            if (!ring.isInZone(ZoneType.Battlefield) && game.getStack().isEmpty() && steps > 30) {
                break;
            }
        }

        long aims = seen.stream().filter(s2 -> s2.contains("\"decisionType\":\"CHOOSE_ENTITY\"")
                && s2.contains("Aura Shards")).count();
        boolean declineOffered = seen.stream().anyMatch(s2 ->
                s2.contains("\"decisionType\":\"CHOOSE_ENTITY\"") && s2.contains("Aura Shards")
                && s2.contains("DECLINE this optional trigger"));
        long confirms = seen.stream().filter(s2 ->
                s2.contains("\"decisionType\":\"CONFIRM\"")).count();
        boolean ringGone = !ring.isInZone(ZoneType.Battlefield);
        boolean vaultAlive = vault.isInZone(ZoneType.Battlefield);
        System.out.println("SIBLING test: aims=" + aims + " declineOffered=" + declineOffered + " confirms=" + confirms
                + " ringDestroyed=" + ringGone + " vaultAlive=" + vaultAlive
                + " reqs=" + seen.size());
        Assert.assertTrue(aims >= 2, "two simultaneous Aura Shards triggers should each ask for a target");
        Assert.assertTrue(declineOffered,
                "trigger-aim windows must offer the explicit DECLINE option");
        Assert.assertTrue(ringGone, "the aimed sibling must destroy Sol Ring");
        Assert.assertTrue(vaultAlive, "the declined sibling must not destroy anything");
        Assert.assertTrue(confirms <= 1,
                "the declined sibling's resolve-confirm must be auto-answered "
                + "locally (saw " + confirms + " CONFIRM requests)");
    }

    /**
     * BL-11 second card (group {@code extended}). Dire Undercurrents' blue
     * trigger has Aura Shards' exact shape — {@code T:Mode$ ChangesZone |
     * Origin$ Any | Destination$ Battlefield | ValidCard$ Creature.Blue+YouCtrl
     * | TriggerZones$ Battlefield | OptionalDecider$ You} executing a targeted
     * effect ({@code DB$ Draw | ValidTgts$ Player}) — with a PLAYER target
     * instead of a permanent. Two Drakes from one Talrand's Invocation = two
     * simultaneous optional triggers; the seat aims the first at itself and
     * declines the second: exactly one card drawn, one aim honoured, one
     * decline honoured, no stray CONFIRM for the declined sibling.
     */
    @Test(groups = "extended", timeOut = 240_000)
    public void direUndercurrentsSiblingsAimAndDeclineIndependently() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            MailboxTestKit.put("Dire Undercurrents", k.seat, ZoneType.Battlefield);
            for (int i = 0; i < 4; i++) MailboxTestKit.put("Island", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Talrand's Invocation", k.seat, ZoneType.Hand); // two blue Drakes
            for (int i = 0; i < 3; i++) MailboxTestKit.put("Plains", k.seat, ZoneType.Library);
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Island", k.opp, ZoneType.Library);
            final String me = k.seat.getName();
            final boolean[] aimedOnce = {false};
            final boolean[] confirmedOnce = {false};
            k.startBrain(body -> {
                if (body.contains("\"decisionType\":\"CAST_SPELL\"")) {
                    String id = MailboxTestKit.idOf(body, "Talrand's Invocation");
                    return id != null ? "{\"chosenId\": " + id + "}" : null;
                }
                if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")
                        && body.contains("Dire Undercurrents")) {
                    if (!aimedOnce[0]) {
                        String id = MailboxTestKit.idOf(body, me);   // aim the draw at myself
                        if (id != null) {
                            aimedOnce[0] = true;
                            return "{\"chosenId\": " + id + "}";
                        }
                        return "{\"chosenId\": 0}";
                    }
                    return "{\"chosenId\": 0}";      // second sibling: DECLINE
                }
                if (body.contains("\"decisionType\":\"CONFIRM\"")) {
                    if (!confirmedOnce[0]) {
                        confirmedOnce[0] = true;
                        return "{\"chosenId\": 1}";
                    }
                    return "{\"chosenId\": 0}";
                }
                return null;
            });
            k.run(() -> k.seat.getCardsIn(ZoneType.Library).size() <= 2, 300);

            long aims = k.seen.stream().filter(s2 -> s2.contains("\"decisionType\":\"CHOOSE_ENTITY\"")
                    && s2.contains("Dire Undercurrents")).count();
            boolean declineOffered = k.seen.stream().anyMatch(s2 ->
                    s2.contains("\"decisionType\":\"CHOOSE_ENTITY\"") && s2.contains("Dire Undercurrents")
                    && s2.contains("DECLINE this optional trigger"));
            long confirms = k.seen.stream().filter(s2 ->
                    s2.contains("\"decisionType\":\"CONFIRM\"")).count();
            int lib = k.seat.getCardsIn(ZoneType.Library).size();
            int drakes = 0;
            for (Card c : k.seat.getCardsIn(ZoneType.Battlefield)) {
                if (c.isCreature() && c.isToken()) drakes++;
            }
            System.out.println("SIBLING-UNDERCURRENTS test: aims=" + aims + " declineOffered=" + declineOffered
                    + " confirms=" + confirms + " drakes=" + drakes + " lib=" + lib + " reqs=" + k.seen.size());
            Assert.assertEquals(drakes, 2, "Talrand's Invocation must have made two Drakes");
            Assert.assertTrue(aims >= 2, "two simultaneous Dire Undercurrents triggers should each ask for a target");
            Assert.assertTrue(declineOffered, "trigger-aim windows must offer the explicit DECLINE option");
            Assert.assertEquals(lib, 2, "the aimed sibling draws exactly one card; the declined one draws none");
            Assert.assertTrue(confirms <= 1,
                    "the declined sibling's resolve-confirm must be auto-answered "
                    + "locally (saw " + confirms + " CONFIRM requests)");
        }
    }
}
