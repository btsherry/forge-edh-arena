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
 * Game-15 finding (2026-08-28): stack serialization carried source names,
 * owners and kinds but NOT chosen targets — public information at any real
 * table. A REACT brain therefore guessed who a spell was aimed at (Urza
 * countered a Beast Within it believed threatened itself; the real target
 * was an indestructible god). Every stack item's chain now announces its
 * chosen targets in {@code state.stackTargets}, card and player shapes both.
 */
public class StackTargetsVisibleTest {

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

    /** Opp casts {@code spellName} at the seat's bear and/or the seat's face;
     *  the seat (holding a live Counterspell so the reactive gate opens) must
     *  see every chosen target. {@code aimBears}: root part targets the bear;
     *  {@code aimFaceOnSub}: (root if !aimBears else the SubAbility part)
     *  targets the seat player — exercises the chained multi-target shape. */
    private String runSpell(String spellName, boolean aimBears, boolean aimFaceOnSub) throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Path base = Files.createTempDirectory("stacktgt");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player opp = game.getPlayers().get(0);
        Player seat = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, opp);
        game.getPhaseHandler().onStackResolved();

        Card bears = put("Grizzly Bears", seat, ZoneType.Battlefield);
        put("Counterspell", seat, ZoneType.Hand);
        for (int i = 0; i < 2; i++) put("Island", seat, ZoneType.Battlefield);
        for (int i = 0; i < 2; i++) put("Island", seat, ZoneType.Library);
        for (int i = 0; i < 2; i++) put("Mountain", opp, ZoneType.Battlefield);
        for (int i = 0; i < 2; i++) put("Mountain", opp, ZoneType.Library);

        Card spell = put(spellName, opp, ZoneType.Hand);
        SpellAbility sa = spell.getFirstSpellAbility();
        sa.setActivatingPlayer(opp);
        if (aimBears) {
            sa.getTargets().add(bears);
            if (aimFaceOnSub) {
                sa.getSubAbility().getTargets().add(seat); // chained second target
            }
        } else {
            sa.getTargets().add(seat);
        }
        game.getAction().moveToStack(spell, sa);
        game.getStack().add(sa);

        Path in = base.resolve("seat-" + seat.getId()).resolve("inbox");
        Path out = base.resolve("seat-" + seat.getId()).resolve("outbox");
        List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Thread brain = new Thread(() -> {
            long end = System.currentTimeMillis() + 120_000;
            java.util.Set<String> done = new java.util.HashSet<>();
            while (System.currentTimeMillis() < end) {
                try {
                    if (Files.isDirectory(in)) {
                        for (Path f : Files.newDirectoryStream(in, "req-*.json")) {
                            String n = f.getFileName().toString();
                            if (done.contains(n)) continue;
                            seen.add(new String(Files.readAllBytes(f)));
                            done.add(n);
                            Files.createDirectories(out);
                            Path tmp = out.resolve(n.replace("req-", "resp-") + ".tmp");
                            Files.write(tmp, "{\"chosenId\": 0}".getBytes());
                            Files.move(tmp, out.resolve(n.replace("req-", "resp-")));
                        }
                    }
                    Thread.sleep(25);
                } catch (Exception e) { /* keep polling */ }
            }
        }, "test-brain-stacktgt");
        brain.setDaemon(true);
        brain.start();

        int steps = 0;
        while (steps++ < 200 && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            boolean sawWindow = seen.stream().anyMatch(s -> s.contains(spellName));
            if (sawWindow && steps > 5) break;
        }
        for (String s : seen) {
            if (s.contains(spellName) && s.contains("stackTargets")) return s;
        }
        return seen.stream().filter(s -> s.contains(spellName)).findFirst().orElse("");
    }

    /** Arc Trail: "2 damage to any target AND 1 damage to any other target" —
     *  root part aims the bear, the chained SubAbility part aims the face.
     *  One game proves the whole surface (harness boil: this scenario
     *  strictly subsumes the former single-target Shock card/player pair):
     *  stackTargets present, CARD target named, PLAYER target named, and the
     *  per-PART chain walk covered. */
    @Test(timeOut = 240_000)
    public void targetsAnnouncedCardPlayerAndChain() throws Exception {
        String body = runSpell("Arc Trail", true, true);
        boolean present = body.contains("\"stackTargets\"");
        boolean card = body.contains("Grizzly Bears");
        boolean player = body.contains("seat ");
        System.out.println("STACKTGT: present=" + present
                + " card=" + card + " player=" + player);
        Assert.assertTrue(present && card && player,
                "every chosen target — card and player, root and chained part — "
                + "must be announced (public info)");
    }
}
