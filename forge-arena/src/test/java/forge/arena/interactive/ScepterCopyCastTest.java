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
 * playSaFromPlayEffect gap (validation game, 2026-08-19): Isochron Scepter's
 * "you may cast the copy" fell to stock, which silently declined a copied
 * Counterspell the seat had set up its whole turn for. Two live shapes:
 * (a) untargeted copy (Dramatic Reversal) — CONFIRM reaches the seat, yes
 *     casts it free, the rocks untap;
 * (b) targeted copy (Counterspell) — CONFIRM yes, then the SEAT aims it at
 *     the stack SpellAbility, and the counter actually removes the spell.
 */
public class ScepterCopyCastTest {

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
        final Card scepter;
        final List<String> seen =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());

        Fixture(String imprintName, boolean oppSpellOnStack, Path base) throws Exception {
            List<RegisteredPlayer> players = Lists.newArrayList();
            Deck d = new Deck();
            players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
            players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
            GameRules rules = new GameRules(GameType.Commander);
            game = new Game(players, rules, new Match(rules, players, "t"));
            opp = game.getPlayers().get(0);
            seat = game.getPlayers().get(1);
            game.setAge(GameStage.Play);
            game.getPhaseHandler().devModeSet(PhaseType.MAIN1,
                    oppSpellOnStack ? opp : seat);
            game.getPhaseHandler().onStackResolved();

            scepter = put("Isochron Scepter", seat, ZoneType.Battlefield);
            Card imprint = put(imprintName, seat, ZoneType.Exile);
            imprint.setExiledWith(scepter);
            scepter.addImprintedCard(imprint);
            scepter.addExiledCard(imprint);   // ExiledWithSource checks this list too
            for (int i = 0; i < 2; i++) put("Island", seat, ZoneType.Battlefield);
            for (int i = 0; i < 2; i++) put("Island", seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) put("Plains", opp, ZoneType.Library);

            if (oppSpellOnStack) {
                for (int i = 0; i < 3; i++) put("Island", opp, ZoneType.Battlefield);
                Card div = put("Divination", opp, ZoneType.Hand);
                SpellAbility divSa = div.getFirstSpellAbility();
                divSa.setActivatingPlayer(opp);
                game.getAction().moveToStack(div, divSa);
                game.getStack().add(divSa);
            }
        }

        void startBrain(String counterTargetLabel) {
            Path root = MailboxDirs.base;
            Path in = root.resolve("seat-" + seat.getId()).resolve("inbox");
            Path out = root.resolve("seat-" + seat.getId()).resolve("outbox");
            final boolean[] activated = {false};   // one activation only, else the
            // Dramatic Reversal copy untaps the Scepter and the brain combos forever
            Thread t = new Thread(() -> {
                long end = System.currentTimeMillis() + 150_000;
                java.util.Set<String> done = new java.util.HashSet<>();
                while (System.currentTimeMillis() < end) {
                    try {
                        if (Files.isDirectory(in)) {
                            for (Path f : Files.newDirectoryStream(in, "req-*.json")) {
                                String n = f.getFileName().toString();
                                if (done.contains(n)) continue;
                                String body = new String(Files.readAllBytes(f));
                                seen.add(body); done.add(n);
                                String resp;
                                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                                        || body.contains("\"decisionType\":\"REACT\""))
                                        && body.contains("Isochron Scepter") && !activated[0]) {
                                    java.util.regex.Matcher m = java.util.regex.Pattern
                                            .compile("\\{\"id\":(\\d+),\"label\":\"Isochron Scepter")
                                            .matcher(body);
                                    if (m.find()) { activated[0] = true; resp = "{\"chosenId\": " + m.group(1) + "}"; }
                                    else resp = "{\"chosenId\": 0}";
                                } else if (body.contains("\"decisionType\":\"CONFIRM\"")) {
                                    resp = "{\"chosenId\": 1}";
                                } else if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")
                                        && counterTargetLabel != null) {
                                    java.util.regex.Matcher m = java.util.regex.Pattern
                                            .compile("\\{\"id\":(\\d+),\"label\":\"" + counterTargetLabel)
                                            .matcher(body);
                                    resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "0") + "}";
                                } else {
                                    resp = "{\"chosenId\": 0}";
                                }
                                Files.createDirectories(out);
                                Path tmp = out.resolve(n.replace("req-", "resp-") + ".tmp");
                                Files.write(tmp, resp.getBytes());
                                Files.move(tmp, out.resolve(n.replace("req-", "resp-")));
                            }
                        }
                        Thread.sleep(25);
                    } catch (Exception e) { /* keep polling */ }
                }
            }, "test-brain-scepter");
            t.setDaemon(true);
            t.start();
        }

        void run(java.util.function.BooleanSupplier done) {
            int steps = 0;
            while (steps++ < 400 && !game.isGameOver()) {
                game.getPhaseHandler().mainLoopStep();
                if (done.getAsBoolean() && game.getStack().isEmpty() && steps > 25) break;
            }
        }
    }

    /** shared temp base so the brain thread can find the boxes */
    private static final class MailboxDirs {
        static Path base;
    }

    @Test(timeOut = 240_000)
    public void untargetedCopyCastsAfterSeatConfirm() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        MailboxDirs.base = Files.createTempDirectory("scepter-a");
        Fixture fx = new Fixture("Dramatic Reversal", false, MailboxDirs.base);
        Card ring = put("Sol Ring", fx.seat, ZoneType.Battlefield);
        ring.setTapped(true);
        Card vault = put("Mana Vault", fx.seat, ZoneType.Battlefield);
        vault.setTapped(true);
        fx.startBrain(null);
        fx.run(() -> !ring.isTapped() && !vault.isTapped());

        boolean confirmSeen = fx.seen.stream().anyMatch(s ->
                s.contains("PLAY_FROM_EFFECT"));
        System.out.println("SCEPTER-A: confirmSeen=" + confirmSeen
                + " ringUntapped=" + !ring.isTapped() + " vaultUntapped=" + !vault.isTapped()
                + " reqs=" + fx.seen.size());
        Assert.assertTrue(confirmSeen, "the may-cast decision never reached the seat");
        Assert.assertTrue(!ring.isTapped() && !vault.isTapped(),
                "the free Dramatic Reversal copy did not resolve (rocks stayed tapped)");
    }

    @Test(timeOut = 240_000)
    public void targetedCopyIsSeatAimedAndCounters() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        MailboxDirs.base = Files.createTempDirectory("scepter-b");
        Fixture fx = new Fixture("Counterspell", true, MailboxDirs.base);
        fx.startBrain("Divination");
        fx.run(() -> !fx.opp.getCardsIn(ZoneType.Graveyard).isEmpty());

        boolean confirmSeen = fx.seen.stream().anyMatch(s -> s.contains("PLAY_FROM_EFFECT"));
        boolean stackAim = fx.seen.stream().anyMatch(s ->
                s.contains("CHOOSE_ENTITY") && s.contains("Divination") && s.contains("\"STACK\""));
        boolean divInGy = false;
        for (Card c : fx.opp.getCardsIn(ZoneType.Graveyard)) divInGy |= c.getName().equals("Divination");
        int oppHand = fx.opp.getCardsIn(ZoneType.Hand).size();
        System.out.println("SCEPTER-B: confirmSeen=" + confirmSeen + " stackAim=" + stackAim
                + " divCountered=" + divInGy + " oppHand=" + oppHand + " reqs=" + fx.seen.size());
        Assert.assertTrue(confirmSeen, "the may-cast decision never reached the seat");
        Assert.assertTrue(stackAim, "the copy's target was not aimed by the seat at the stack SA");
        Assert.assertTrue(divInGy && oppHand == 0,
                "THE LIVE GAP: the copied Counterspell must actually counter "
                + "(stock silently declined this exact shape)");
    }
}
