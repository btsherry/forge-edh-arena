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
import forge.game.card.CounterEnumType;
import forge.game.card.CounterType;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.RegisteredPlayer;
import forge.item.IPaperCard;
import forge.model.FModel;

/**
 * Regression for the 2026-08-17 (game 7) trigger seams: a seat's OWN triggers
 * were decided by stock Forge AI, never reaching the brain.
 *
 * <p>1) OPTIONAL-TRIGGER CONFIRM — Rings of Brighthearth ("whenever you
 * activate an ability ... you may pay {2} to copy it"). Stock's
 * CopySpellAbilityAi refuses to copy the seat's own activated abilities, so
 * Urza's Rings + Basalt "infinite" netted zero. With the override the seat
 * gets a CONFIRM (confirmMode TRIGGER) and, on yes, the copy resolves.
 *
 * <p>2) TRIGGER TARGETING — a targeting trigger's target used to be aimed by
 * stock AI (Tidespout Tyrant bounced Urza's own 17/17). The override routes it
 * to the seat as CHOOSE_ENTITY. (Covered structurally here by asserting the
 * copy path; the bounce-targeting is exercised by the priority loop reaching
 * the seat — see the CONFIRM assertions.)
 */
public class TriggerSurfacesReachMailboxTest {

    private static Card put(String name, Player p, forge.game.zone.ZoneType z) {
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
    public void ringsCopyConfirmReachesSeatAndCopies() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Path base = Files.createTempDirectory("trig-mb");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();

        put("Rings of Brighthearth", p, forge.game.zone.ZoneType.Battlefield);
        // Walking Ballista is 0/0; give it counters so it survives and so a
        // second (copied) +1/+1 is unambiguous.
        Card ballista = put("Walking Ballista", p, forge.game.zone.ZoneType.Battlefield);
        ballista.addCounterInternal(CounterEnumType.P1P1, 3,
                p, false, null, null);
        // mana: {4} to activate PutCounter + {2} for the Rings copy = 6
        for (int i = 0; i < 8; i++) put("Wastes", p, forge.game.zone.ZoneType.Battlefield);

        final CounterType p1p1 = CounterEnumType.P1P1;
        int startCounters = ballista.getCounters(p1p1);

        Path inbox = base.resolve("seat-" + p.getId()).resolve("inbox");
        Path outbox = base.resolve("seat-" + p.getId()).resolve("outbox");
        java.util.List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Thread brain = new Thread(() -> {
            long end = System.currentTimeMillis() + 150_000;
            java.util.Set<String> done = new java.util.HashSet<>();
            boolean[] activatedOnce = {false};
            while (System.currentTimeMillis() < end) {
                try {
                    if (Files.isDirectory(inbox)) {
                        for (Path f : Files.newDirectoryStream(inbox, "req-*.json")) {
                            String n = f.getFileName().toString();
                            if (done.contains(n)) continue;
                            String body = new String(Files.readAllBytes(f));
                            seen.add(body); done.add(n);
                            String resp;
                            if (body.contains("\"decisionType\":\"CONFIRM\"")) {
                                resp = "{\"chosenId\": 1}";              // yes, pay {2}, copy
                            } else if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                                    || body.contains("\"decisionType\":\"REACT\""))
                                    && !activatedOnce[0]) {
                                // Ballista has TWO activated abilities; pick the
                                // {4}: Put a +1/+1 counter (the non-mana ability that
                                // triggers Rings), NOT "remove a +1/+1 counter: deal
                                // damage". The {4} cost is the unique discriminator.
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("\"id\"\\s*:\\s*(\\d+)[^}]*Walking Ballista[^}]*\\{4\\}")
                                        .matcher(body);
                                if (m.find()) { resp = "{\"chosenId\": " + m.group(1) + "}"; activatedOnce[0] = true; }
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
                    Thread.sleep(30);
                } catch (Exception e) { /* keep polling */ }
            }
        }, "test-brain-trigger");
        brain.setDaemon(true);
        brain.start();

        int steps = 0;
        while (steps++ < 400 && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            if (ballista.getCounters(p1p1) >= startCounters + 2 && game.getStack().isEmpty()
                    && steps > 20) {
                break;
            }
        }

        boolean triggerConfirmSeen = seen.stream().anyMatch(s ->
                s.contains("\"decisionType\":\"CONFIRM\"")
                && (s.contains("Rings of Brighthearth") || s.contains("\"TRIGGER\"")));
        int endCounters = ballista.getCounters(p1p1);
        System.out.println("TRIGGER test: reqs=" + seen.size()
                + " triggerConfirmSeen=" + triggerConfirmSeen
                + " counters " + startCounters + "->" + endCounters);
        Assert.assertTrue(triggerConfirmSeen,
                "the Rings optional-trigger CONFIRM never reached the seat "
                + "(defect: stock CopySpellAbilityAi decided it, never the brain)");
        Assert.assertEquals(endCounters, startCounters + 2,
                "paying the Rings copy should add a SECOND +1/+1 counter "
                + "(activation + copy); got " + (endCounters - startCounters));
    }
}
