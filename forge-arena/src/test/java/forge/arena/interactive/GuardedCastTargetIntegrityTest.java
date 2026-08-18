package forge.arena.interactive;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import com.google.common.collect.Lists;

import forge.StaticData;
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
 * FIZZLE-2 regression (game 7 t28, 2026-08-17): a targeted spell cast through
 * the seat's guarded path (playChosenSpellAbility pre-targeting) reached
 * resolution with EMPTY TargetChoices ("[arena] FIZZLE ... targets: (none
 * set)") after an interleaved opponent trigger — while two counters aimed at
 * it failed to remove it (that half was the stack-targeting bug, fixed).
 *
 * <p>This test replays the live shape with TWO mailbox seats:
 * caster (Generous Gift at an opponent permanent) + an interleaved Rhystic
 * Study trigger (PAY_UNLESS declined) — and asserts, in two variants:
 * <ol>
 *   <li>RESOLUTION: no counter — the Gift must still carry its target at
 *       resolution and destroy the permanent (caster-side target integrity
 *       across an interleaved trigger).</li>
 *   <li>COUNTER: the second seat counters the Gift by targeting the STACK
 *       SpellAbility — the Gift must actually be removed (countered), the
 *       permanent must survive.</li>
 * </ol>
 */
public class GuardedCastTargetIntegrityTest {

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

    /** Shared fixture: A (caster, mailbox) vs B (responder, mailbox). */
    private static final class Table {
        final Game game;
        final Player a;
        final Player b;
        final Card orb;
        final java.util.List<String> seen =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        private final Thread brain;

        Table(Path base, boolean bCounters) throws Exception {
            this(base, bCounters, false);
        }

        Table(Path base, boolean bCounters, boolean bHasTyrant) throws Exception {
            List<RegisteredPlayer> players = Lists.newArrayList();
            Deck d = new Deck();
            players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("caster", base)));
            players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("responder", base)));
            GameRules rules = new GameRules(GameType.Commander);
            game = new Game(players, rules, new Match(rules, players, "t"));
            a = game.getPlayers().get(0);
            b = game.getPlayers().get(1);
            game.setAge(GameStage.Play);
            game.getPhaseHandler().devModeSet(PhaseType.MAIN1, a);
            game.getPhaseHandler().onStackResolved();

            // caster A: the targeted spell + mana
            put("Generous Gift", a, ZoneType.Hand);
            for (int i = 0; i < 5; i++) put("Plains", a, ZoneType.Battlefield);
            for (int i = 0; i < 3; i++) put("Plains", a, ZoneType.Library);

            // responder B: the interleaving trigger + the target + a counter
            put("Rhystic Study", b, ZoneType.Battlefield);
            if (bHasTyrant) {
                put("Tidespout Tyrant", b, ZoneType.Battlefield);
            }
            orb = put("Winter Orb", b, ZoneType.Battlefield);
            put("Counterspell", b, ZoneType.Hand);
            for (int i = 0; i < 3; i++) put("Island", b, ZoneType.Battlefield);
            for (int i = 0; i < 4; i++) put("Island", b, ZoneType.Library);

            brain = brainThread(base, a.getId(), b.getId(), bCounters, seen);
            brain.setDaemon(true);
            brain.start();
        }

        void runUntil(java.util.function.BooleanSupplier done) {
            int steps = 0;
            while (steps++ < 400 && !game.isGameOver()) {
                game.getPhaseHandler().mainLoopStep();
                if (done.getAsBoolean() && game.getStack().isEmpty() && steps > 20) {
                    break;
                }
            }
        }
    }

    /** One polling thread answering both seats' inboxes. */
    private static Thread brainThread(Path base, int idA, int idB,
            boolean bCounters, List<String> seen) {
        return new Thread(() -> {
            long end = System.currentTimeMillis() + 150_000;
            java.util.Set<String> done = new java.util.HashSet<>();
            while (System.currentTimeMillis() < end) {
                for (int id : new int[] {idA, idB}) {
                    Path inbox = base.resolve("seat-" + id).resolve("inbox");
                    Path outbox = base.resolve("seat-" + id).resolve("outbox");
                    try {
                        if (!Files.isDirectory(inbox)) continue;
                        for (Path f : Files.newDirectoryStream(inbox, "req-*.json")) {
                            String n = f.getFileName().toString();
                            String key = id + "/" + n;
                            if (done.contains(key)) continue;
                            String body = new String(Files.readAllBytes(f));
                            done.add(key);
                            String resp = answer(body, id == idA, bCounters);
                            seen.add("seat" + id + " -> " + resp + " :: " + body);
                            Files.createDirectories(outbox);
                            Path tmp = outbox.resolve(n.replace("req-", "resp-") + ".tmp");
                            Files.write(tmp, resp.getBytes());
                            Files.move(tmp, outbox.resolve(n.replace("req-", "resp-")));
                        }
                    } catch (Exception e) { /* keep polling */ }
                }
                try { Thread.sleep(25); } catch (InterruptedException ie) { return; }
            }
        }, "test-brain-guarded");
    }

    private static String pick(String body, String regex) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(regex).matcher(body);
        return m.find() ? m.group(1) : null;
    }

    private static String answer(String body, boolean isCaster, boolean bCounters) {
        if (isCaster) {
            if (body.contains("\"decisionType\":\"CAST_SPELL\"")) {
                String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Generous Gift");
                return "{\"chosenId\": " + (id != null ? id : "0") + "}";
            }
            if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")) {
                String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Winter Orb");
                return "{\"chosenId\": " + (id != null ? id : "0") + "}";
            }
            if (body.contains("\"decisionType\":\"PAY_UNLESS\"")) {
                return "{\"chosenId\": 0}";      // decline the Rhystic tax (live shape)
            }
            return "{\"chosenId\": 0}";
        }
        // responder
        if (bCounters && body.contains("\"decisionType\":\"REACT\"")) {
            String id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Counterspell");
            return "{\"chosenId\": " + (id != null ? id : "0") + "}";
        }
        if (bCounters && body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")) {
            String id;
            if (body.contains("Tidespout Tyrant (")) {
                // the Tyrant's own bounce trigger, aimed BY THE SEAT — pick a
                // Plains (an opponent permanent), never our own board
                id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Plains");
            } else {
                id = pick(body, "\\{\"id\":(\\d+),\"label\":\"Generous Gift");
            }
            return "{\"chosenId\": " + (id != null ? id : "0") + "}";
        }
        return "{\"chosenId\": 0}";
    }

    @Test(timeOut = 240_000)
    public void targetSurvivesInterleavedTriggerAndResolves() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Table t = new Table(Files.createTempDirectory("guarded-resolve"), false);
        t.runUntil(() -> !t.orb.isInZone(ZoneType.Battlefield)
                || !t.a.getCardsIn(ZoneType.Hand).isEmpty() && t.game.getStack().isEmpty());

        boolean orbOnBf = false, orbInGy = false, giftInGy = false;
        for (Card c : t.b.getCardsIn(ZoneType.Battlefield)) orbOnBf |= c.getName().equals("Winter Orb");
        for (Card c : t.b.getCardsIn(ZoneType.Graveyard)) orbInGy |= c.getName().equals("Winter Orb");
        for (Card c : t.a.getCardsIn(ZoneType.Graveyard)) giftInGy |= c.getName().equals("Generous Gift");
        boolean payUnlessSeen = t.seen.stream().anyMatch(s -> s.contains("PAY_UNLESS"));
        System.out.println("GUARDED-RESOLVE: orbOnBf=" + orbOnBf + " orbInGy=" + orbInGy
                + " giftInGy=" + giftInGy + " payUnlessSeen=" + payUnlessSeen
                + " reqs=" + t.seen.size());
        for (String s : t.seen) {
            System.out.println("   XCHG: " + (s.length() > 400 ? s.substring(0, 400) : s));
        }
        System.out.println("   A battlefield: " + t.a.getCardsIn(ZoneType.Battlefield));
        System.out.println("   A graveyard:   " + t.a.getCardsIn(ZoneType.Graveyard));
        System.out.println("   B battlefield: " + t.b.getCardsIn(ZoneType.Battlefield));
        Assert.assertTrue(giftInGy, "Generous Gift was never cast/resolved through the guarded path");
        Assert.assertTrue(payUnlessSeen, "the Rhystic trigger never interleaved (test lost its shape)");
        Assert.assertTrue(orbInGy && !orbOnBf,
                "FIZZLE-2: the Gift resolved WITHOUT destroying its chosen target — "
                + "targets were lost between pre-targeting and resolution");
    }

    /**
     * The full game-7 collision: guarded cast + PAY_UNLESS interleave + a
     * counter aimed at the stack SA + the counterer's OWN cast-trigger
     * (Tidespout Tyrant) aimed by its seat — all on one stack. Asserts every
     * piece lands: Gift countered, Orb alive, the Tyrant bounce hit the
     * permanent the SEAT chose (an opponent Plains), nothing fizzled sideways.
     */
    @Test(timeOut = 240_000)
    public void fullTriggerMachineryCollision() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Table t = new Table(Files.createTempDirectory("guarded-collision"), true, true);
        t.runUntil(() -> !t.a.getCardsIn(ZoneType.Graveyard).isEmpty());

        boolean orbOnBf = false, giftInGy = false, counterInGy = false;
        for (Card c : t.b.getCardsIn(ZoneType.Battlefield)) orbOnBf |= c.getName().equals("Winter Orb");
        for (Card c : t.a.getCardsIn(ZoneType.Graveyard)) giftInGy |= c.getName().equals("Generous Gift");
        for (Card c : t.b.getCardsIn(ZoneType.Graveyard)) counterInGy |= c.getName().equals("Counterspell");
        int plainsOnBf = 0, plainsInHand = 0;
        for (Card c : t.a.getCardsIn(ZoneType.Battlefield)) if (c.getName().equals("Plains")) plainsOnBf++;
        for (Card c : t.a.getCardsIn(ZoneType.Hand)) if (c.getName().equals("Plains")) plainsInHand++;
        boolean tyrantChoiceSeen = t.seen.stream().anyMatch(x ->
                x.contains("CHOOSE_ENTITY") && x.contains("Tidespout Tyrant ("));
        System.out.println("GUARDED-COLLISION: orbOnBf=" + orbOnBf + " giftInGy=" + giftInGy
                + " counterInGy=" + counterInGy + " plainsBf=" + plainsOnBf
                + " plainsHand=" + plainsInHand + " tyrantChoiceSeen=" + tyrantChoiceSeen
                + " reqs=" + t.seen.size());
        Assert.assertTrue(counterInGy, "Counterspell never cast");
        Assert.assertTrue(giftInGy && orbOnBf, "the counter must remove the Gift (Orb alive)");
        Assert.assertTrue(tyrantChoiceSeen,
                "the Tyrant's bounce target choice never reached the counterer's seat");
        Assert.assertEquals(plainsInHand, 1,
                "the seat-chosen bounce target (a Plains) should be in A's hand");
        Assert.assertEquals(plainsOnBf, 4, "exactly one Plains bounced");
    }

    @Test(timeOut = 240_000)
    public void counterAimedAtStackSaActuallyRemovesTheSpell() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        Table t = new Table(Files.createTempDirectory("guarded-counter"), true);
        t.runUntil(() -> !t.a.getCardsIn(ZoneType.Graveyard).isEmpty());

        boolean orbOnBf = false, giftInGy = false, counterInGy = false;
        for (Card c : t.b.getCardsIn(ZoneType.Battlefield)) orbOnBf |= c.getName().equals("Winter Orb");
        for (Card c : t.a.getCardsIn(ZoneType.Graveyard)) giftInGy |= c.getName().equals("Generous Gift");
        for (Card c : t.b.getCardsIn(ZoneType.Graveyard)) counterInGy |= c.getName().equals("Counterspell");
        boolean stackOptionSeen = t.seen.stream().anyMatch(s ->
                s.contains("CHOOSE_ENTITY") && s.contains("Generous Gift") && s.contains("\"STACK\""));
        System.out.println("GUARDED-COUNTER: orbOnBf=" + orbOnBf + " giftInGy=" + giftInGy
                + " counterInGy=" + counterInGy + " stackOptionSeen=" + stackOptionSeen
                + " reqs=" + t.seen.size());
        Assert.assertTrue(counterInGy, "Counterspell was never cast by the responder seat");
        Assert.assertTrue(stackOptionSeen,
                "the counter's target was not offered as a STACK item");
        Assert.assertTrue(giftInGy, "the countered Gift should be in its owner's graveyard");
        Assert.assertTrue(orbOnBf,
                "game-7 shape: the counter 'resolved' but the Gift still destroyed the Orb "
                + "(counter was a no-op — SA identity/targeting defect)");
    }
}
