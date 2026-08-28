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
 * Sacrifice choices are seat-owned (2026-08-24). Two engine paths fell to
 * stock worst-card heuristics, thwarting deliberate play lines:
 *
 * <ul>
 *   <li>EFFECT path — {@code SacrificeEffect} → {@code
 *       choosePermanentsToSacrifice} (edicts, symmetrical sacrifices,
 *       Balance). Covered by Innocent Blood (Defined$ Player) and Diabolic
 *       Edict (targeted) — two script shapes, one seam.</li>
 *   <li>COST path — {@code AiCostDecision.visit(CostSacrifice)} → the new
 *       {@link forge.ai.SacCostPreference} hook (outlet activations and
 *       additional-cost casts). Covered by Viscera Seer (activated ability)
 *       and Altar's Reap (spell additional cost).</li>
 * </ul>
 *
 * Every scenario gives the seat a big creature (Colossal Dreadmaw) and a
 * small one (Llanowar Elves) and has the brain sacrifice the BIG one — the
 * opposite of stock's pick — so a pass proves seat authority, not heuristic
 * coincidence.
 */
public class SacrificeSeatChoiceTest {

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
        final Card dreadmaw;
        final Card elves;
        final Path base;
        final List<String> seen =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());

        Fixture(boolean oppActive, Path base) throws Exception {
            this.base = base;
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

            dreadmaw = put("Colossal Dreadmaw", seat, ZoneType.Battlefield);
            elves = put("Llanowar Elves", seat, ZoneType.Battlefield);
            for (int i = 0; i < 3; i++) put("Swamp", seat, ZoneType.Library);
            for (int i = 0; i < 3; i++) put("Plains", opp, ZoneType.Library);
        }

        /** Opp casts a spell straight from the stack (Divination pattern);
         *  target the seat when {@code targetSeat}. */
        void oppCasts(String name, boolean targetSeat) {
            for (int i = 0; i < 3; i++) put("Swamp", opp, ZoneType.Battlefield);
            Card spell = put(name, opp, ZoneType.Hand);
            SpellAbility sa = spell.getFirstSpellAbility();
            sa.setActivatingPlayer(opp);
            if (targetSeat) {
                sa.getTargets().add(seat);
            }
            game.getAction().moveToStack(spell, sa);
            game.getStack().add(sa);
        }

        /** Brain: play each label once (in any window order); whenever a
         *  sacrifice/destroy card choice arrives, feed the biggest big
         *  creature still alive. */
        void startBrain(String... playLabels) {
            Path in = base.resolve("seat-" + seat.getId()).resolve("inbox");
            Path out = base.resolve("seat-" + seat.getId()).resolve("outbox");
            final java.util.Set<String> played =
                    java.util.Collections.synchronizedSet(new java.util.HashSet<>());
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
                                if (body.contains("\"decisionType\":\"CAST_SPELL\"")
                                        || body.contains("\"decisionType\":\"REACT\"")) {
                                    resp = "{\"chosenId\": 0}";
                                    for (String label : playLabels) {
                                        if (played.contains(label)) continue;
                                        java.util.regex.Matcher m = java.util.regex.Pattern
                                                .compile("\\{\"id\":(\\d+),\"label\":\"" + label)
                                                .matcher(body);
                                        if (m.find()) {
                                            played.add(label);
                                            resp = "{\"chosenId\": " + m.group(1) + "}";
                                            break;
                                        }
                                    }
                                } else if (body.contains("\"decisionType\":\"CHOOSE_ENTITIES\"")
                                        && (body.contains("SACRIFICE") || body.contains("DESTROY"))) {
                                    // merged scenarios: feed the biggest big
                                    // creature still alive (anti-stock both times)
                                    java.util.regex.Matcher m = java.util.regex.Pattern
                                            .compile("\\{\"id\":(\\d+),\"label\":\"Colossal Dreadmaw")
                                            .matcher(body);
                                    if (!m.find()) {
                                        m = java.util.regex.Pattern
                                            .compile("\\{\"id\":(\\d+),\"label\":\"Ghalta")
                                            .matcher(body);
                                        if (!m.find()) { resp = "{\"chosen\": []}"; m = null; }
                                    }
                                    resp = m != null ? "{\"chosen\": [" + m.group(1) + "]}" : "{\"chosen\": []}";
                                } else if (body.contains("\"decisionType\":\"CHOOSE_ENTITIES\"")) {
                                    resp = "{\"chosen\": []}";
                                } else if (body.contains("\"decisionType\":\"CONFIRM\"")) {
                                    resp = "{\"chosenId\": 1}";
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
            }, "test-brain-sac");
            t.setDaemon(true);
            t.start();
        }

        void run(java.util.function.BooleanSupplier done) {
            int steps = 0;
            while (steps++ < 400 && !game.isGameOver()) {
                game.getPhaseHandler().mainLoopStep();
                if (done.getAsBoolean() && game.getStack().isEmpty() && steps > 25) {
                    break;
                }
            }
        }

        void assertSeatChoseTheBigOne(String label) {
            boolean sacWindow = seen.stream().anyMatch(s ->
                    s.contains("\"decisionType\":\"CHOOSE_ENTITIES\"")
                    && (s.contains("SACRIFICE") || s.contains("DESTROY")));
            System.out.println(label + ": sacWindow=" + sacWindow
                    + " dreadmawInGy=" + dreadmaw.isInZone(ZoneType.Graveyard)
                    + " elvesAlive=" + elves.isInZone(ZoneType.Battlefield)
                    + " reqs=" + seen.size());
            Assert.assertTrue(sacWindow, "the sacrifice choice never reached the seat");
            Assert.assertTrue(dreadmaw.isInZone(ZoneType.Graveyard),
                    "the seat chose Dreadmaw — it must be the one sacrificed");
            Assert.assertTrue(elves.isInZone(ZoneType.Battlefield),
                    "stock's pick (the worst creature) must have survived");
        }
    }

    // ---- EFFECT path: SacrificeEffect -> choosePermanentsToSacrifice --------

    /** Harness boil note: an Innocent-Blood-then-Edict single-game merge was
     *  tried and reverted — the second resolution needs more game-turns than
     *  the deliberately tiny fixture libraries support (players deck out).
     *  Two worlds, two games: the anti-contortion rule wins over one boot. */
    @Test(timeOut = 240_000)
    public void symmetricalSacrificeEffectIsSeatChosen() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Fixture fx = new Fixture(true, Files.createTempDirectory("sac-blood"));
        fx.oppCasts("Innocent Blood", false);   // each player sacrifices a creature
        fx.startBrain();
        fx.run(() -> fx.dreadmaw.isInZone(ZoneType.Graveyard));
        fx.assertSeatChoseTheBigOne("SAC-EFFECT-SYM");
    }

    @Test(timeOut = 240_000)
    public void targetedEdictIsSeatChosen() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Fixture fx = new Fixture(true, Files.createTempDirectory("sac-edict"));
        fx.oppCasts("Diabolic Edict", true);    // target player sacrifices a creature
        fx.startBrain();
        fx.run(() -> fx.dreadmaw.isInZone(ZoneType.Graveyard));
        fx.assertSeatChoseTheBigOne("SAC-EFFECT-EDICT");
    }

    /** Harness boil: both cost shapes in ONE game — the Viscera Seer
     *  activation feeds Dreadmaw, then Altar's Reap (additional-cost cast)
     *  feeds Ghalta and draws two. Same oracles as the former two tests. */
    @Test(timeOut = 240_000)
    public void costPathSacrificesAreSeatChosen() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Fixture fx = new Fixture(false, Files.createTempDirectory("sac-cost"));
        Card seer = put("Viscera Seer", fx.seat, ZoneType.Battlefield);
        Card ghalta = put("Ghalta, Primal Hunger", fx.seat, ZoneType.Battlefield);
        for (int i = 0; i < 2; i++) put("Swamp", fx.seat, ZoneType.Battlefield);
        put("Altar's Reap", fx.seat, ZoneType.Hand);
        int hand0 = fx.seat.getCardsIn(ZoneType.Hand).size();
        fx.startBrain("Viscera Seer", "Altar's Reap");
        fx.run(() -> fx.dreadmaw.isInZone(ZoneType.Graveyard)
                && ghalta.isInZone(ZoneType.Graveyard));
        fx.assertSeatChoseTheBigOne("SAC-COST-MERGED");
        Assert.assertTrue(seer.isInZone(ZoneType.Battlefield),
                "the outlet itself (also a legal payment) must survive");
        Assert.assertTrue(ghalta.isInZone(ZoneType.Graveyard),
                "Altar's Reap fed the second big creature");
        Assert.assertEquals(fx.seat.getCardsIn(ZoneType.Hand).size(), hand0 - 1 + 2,
                "Altar's Reap must have resolved (cast from hand, draw two)");
    }
}
