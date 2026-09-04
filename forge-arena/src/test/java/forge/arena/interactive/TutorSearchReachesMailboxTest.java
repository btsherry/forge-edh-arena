package forge.arena.interactive;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import com.google.common.collect.Lists;

import forge.StaticData;
import forge.ai.LobbyPlayerAi;
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
import forge.arena.bootstrap.ArenaBootstrap;
import forge.model.FModel;

/**
 * Regression for the 2026-08-17 modal-spell seam defect (Selvala's lost
 * Craterhoof turn): a mailbox seat cast Archdruid's Charm, chose the tutor
 * mode through the mailbox, and the Charm resolved EMPTY — no CHOOSE_CARD,
 * "found nothing", card to graveyard.
 *
 * Root cause: MailboxController.playChosenSpellAbility's post-mode targeting
 * runnable called chooseTargetsFor(shell) on the Charm itself; a Charm shell
 * has no TargetRestrictions, so it fell through to stock
 * PlayerControllerAi.chooseTargetsFor -> AiController.doTrigger ->
 * CharmAi.checkApiLogic, which does sa.setSubAbility(null) and re-picks the
 * mode by its own logic — silently discarding the seat's chained choice.
 * Fix: target only the CHAINED MODES that actually use targeting.
 *
 * liveShapedCastThroughMailboxLobbyPlayer reproduces the exact live flow
 * (MailboxLobbyPlayer seat, three legal modes, real cast, phase-handler
 * resolution) and fails without the fix; the other two pin the surrounding
 * contract (search override correct when reached; stock baseline documented).
 */
public class TutorSearchReachesMailboxTest {

    private static void model() {
        // same headless bootstrap the arena's engine tests use
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
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

    @Test(timeOut = 180_000)
    public void charmModeOneReachesTheSeatAndDeliversToHand() throws Exception {
        model();
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("seat", null)));
        GameRules rules = new GameRules(GameType.Constructed);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();

        Path base = Files.createTempDirectory("tutor-mb");
        MailboxProtocol bus = MailboxProtocol.forSeat(base, p.getId());
        MailboxController mc = new MailboxController(game, p, p.getLobbyPlayer(), bus);

        put("Craterhoof Behemoth", p, ZoneType.Library);
        for (int i = 0; i < 12; i++) {
            put("Forest", p, ZoneType.Library);          // realistic: many identical basics
        }
        for (String n : new String[] {"Llanowar Elves", "Kogla, the Titan Ape",
                "Temur Sabertooth", "Arbor Elf", "Gaea's Cradle", "Nykthos, Shrine to Nyx",
                "Earthcraft", "Sylvan Library"}) {
            put(n, p, ZoneType.Library);
        }
        Card charm = put("Archdruid's Charm", p, ZoneType.Hand);

        // A "brain" on another thread: answer the seat's requests. For a
        // CHOOSE_CARD, pick Craterhoof; for anything else, pass/none.
        Path inbox = base.resolve("seat-" + p.getId()).resolve("inbox");
        Path outbox = base.resolve("seat-" + p.getId()).resolve("outbox");
        java.util.List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Thread brain = new Thread(() -> {
            long end = System.currentTimeMillis() + 60_000;
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
                            int chosen = 0;
                            java.util.regex.Matcher m = java.util.regex.Pattern
                                    .compile("^(\\d+)$").matcher(String.valueOf(MailboxTestKit.idOf(body, "Craterhoof")));
                            if (m.find()) chosen = Integer.parseInt(m.group(1));
                            Files.createDirectories(outbox);
                            Path tmp = outbox.resolve(n.replace("req-", "resp-") + ".tmp");
                            Files.write(tmp, ("{\"chosenId\": " + chosen + "}").getBytes());
                            Files.move(tmp, outbox.resolve(n.replace("req-", "resp-")));
                        }
                    }
                    Thread.sleep(40);
                } catch (Exception e) {
                    // keep polling
                }
            }
        }, "test-brain");
        brain.setDaemon(true);
        brain.start();

        // Resolve mode 1 (the tutor chain) as the seat, under the mailbox controller.
        SpellAbility charmSa = charm.getFirstSpellAbility();
        SpellAbility tutor = charmSa.getAdditionalAbilityList("Choices").get(0);
        tutor.setActivatingPlayer(p);
        p.runWithController(() -> {
            game.getStack().addAndUnfreeze(tutor);
            int guard = 0;
            while (!game.getStack().isEmpty() && guard++ < 50) {
                game.getStack().resolveStack();
            }
        }, mc);

        boolean inHand = false;
        for (Card c : p.getCardsIn(ZoneType.Hand)) {
            inHand |= c.getName().equals("Craterhoof Behemoth");
        }
        boolean asked = seen.stream().anyMatch(s -> s.contains("CHOOSE_CARD"));
        Assert.assertTrue(asked, "the library search never reached the mailbox seat (no CHOOSE_CARD request)");
        Assert.assertTrue(inHand, "Craterhoof should be in hand after the Charm resolves");
    }

    /** The fallback the mailbox seat takes whenever its brain does not answer:
     *  does stock AI actually find a creature here, or "fail to find"? */
    @Test(timeOut = 180_000)
    public void stockFallbackForTheSameSearch() throws Exception {
        model();
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("seat", null)));
        GameRules rules = new GameRules(GameType.Constructed);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();
        put("Craterhoof Behemoth", p, ZoneType.Library);
        put("Forest", p, ZoneType.Library);
        put("Llanowar Elves", p, ZoneType.Library);
        Card charm = put("Archdruid's Charm", p, ZoneType.Hand);
        SpellAbility tutor = charm.getFirstSpellAbility().getAdditionalAbilityList("Choices").get(0);
        tutor.setActivatingPlayer(p);
        game.getStack().addAndUnfreeze(tutor);
        int guard = 0;
        while (!game.getStack().isEmpty() && guard++ < 50) {
            game.getStack().resolveStack();
        }
        // Documented baseline: stock fetches a land to the battlefield rather
        // than the creature to hand — the behavior the seat silently inherited
        // whenever its choice was discarded. Not asserted (stock may change).
    }

    /** LIVE-SHAPED: the seat is created by MailboxLobbyPlayer (exactly as
     *  GuiPilotMatch does), the Charm is CAST as a spell with mana, mode chosen
     *  through the mailbox, resolved by the phase-handler loop. The test brain
     *  answers CHOOSE_MODE=0 (tutor), CHOOSE_CARD=Craterhoof, everything else pass. */
    @Test(timeOut = 240_000)
    public void liveShapedCastThroughMailboxLobbyPlayer() throws Exception {
        model();
        Path base = Files.createTempDirectory("tutor-live");
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new MailboxLobbyPlayer("seat", base)));
        GameRules rules = new GameRules(GameType.Constructed);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player p = game.getPlayers().get(1);
        Assert.assertTrue(p.getController() instanceof MailboxController,
                "seat controller should be the MailboxController, got " + p.getController().getClass());
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();

        put("Craterhoof Behemoth", p, ZoneType.Library);
        for (int i = 0; i < 12; i++) put("Forest", p, ZoneType.Library);
        for (String n : new String[] {"Llanowar Elves", "Kogla, the Titan Ape", "Temur Sabertooth"}) {
            put(n, p, ZoneType.Library);
        }
        Card charm = put("Archdruid's Charm", p, ZoneType.Hand);
        for (int i = 0; i < 4; i++) put("Forest", p, ZoneType.Battlefield);
        // Live condition: ALL THREE Charm modes legal (opponent has a creature
        // and an artifact; seat has a creature), so the mailbox mode chooser
        // engages exactly as it did in the real game.
        Player opp = game.getPlayers().get(0);
        put("Grizzly Bears", opp, ZoneType.Battlefield);
        put("Sol Ring", opp, ZoneType.Battlefield);
        put("Llanowar Elves", p, ZoneType.Battlefield);

        Path inbox = base.resolve("seat-" + p.getId()).resolve("inbox");
        Path outbox = base.resolve("seat-" + p.getId()).resolve("outbox");
        java.util.List<String> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Thread brain = new Thread(() -> {
            long end = System.currentTimeMillis() + 120_000;
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
                            if (body.contains("\"decisionType\":\"CHOOSE_MODE\"")) {
                                resp = "{\"chosen\": [0]}";
                            } else if (body.contains("\"decisionType\":\"CHOOSE_CARD\"")) {
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("^(\\d+)$").matcher(String.valueOf(MailboxTestKit.idOf(body, "Craterhoof")));
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "0") + "}";
                            } else if (body.contains("\"decisionType\":\"CAST_SPELL\"")) {
                                // cast the Charm if offered, else pass
                                java.util.regex.Matcher m = java.util.regex.Pattern
                                        .compile("^(\\d+)$").matcher(String.valueOf(MailboxTestKit.idOf(body, "Archdruid")));
                                resp = "{\"chosenId\": " + (m.find() ? m.group(1) : "0") + "}";
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
        }, "test-brain-live");
        brain.setDaemon(true);
        brain.start();

        // Truly live-shaped: the SEAT casts the Charm through the AI cast path.
        // The test brain answers CAST_SPELL (pick the Charm), CHOOSE_MODE (0 =
        // tutor), CHOOSE_CARD (Craterhoof). Resolution via the phase handler.
        int steps = 0;
        boolean cast = false;
        while (steps++ < 400 && !game.isGameOver()) {
            game.getPhaseHandler().mainLoopStep();
            boolean inHandNow = false;
            for (Card c : p.getCardsIn(ZoneType.Hand)) inHandNow |= c.getName().equals("Archdruid's Charm");
            if (!inHandNow) cast = true;
            if (cast && game.getStack().isEmpty() && !game.getPhaseHandler().is(PhaseType.MAIN1, p)) break;
            if (cast && game.getStack().isEmpty() && steps > 60) break;
        }
        boolean inHand = false;
        for (Card c : p.getCardsIn(ZoneType.Hand)) inHand |= c.getName().equals("Craterhoof Behemoth");
        Assert.assertTrue(cast, "the Charm was never cast through the mailbox");
        Assert.assertTrue(seen.stream().anyMatch(x -> x.contains("CHOOSE_MODE")),
                "mode choice never reached the seat");
        Assert.assertTrue(seen.stream().anyMatch(x -> x.contains("CHOOSE_CARD")),
                "library search never reached the seat — the seat's chosen mode was discarded");
        Assert.assertTrue(inHand, "Craterhoof should be in hand after the tutor resolves");
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
     * BL-11 second card (group {@code extended}). Primal Command is the same
     * modal-tutor seam by script shape — {@code A:SP$ Charm | Choices$ ...}
     * with a hidden-origin search mode ({@code DB$ ChangeZone | Origin$
     * Library | Destination$ Hand | ChangeType$ Creature}) — but with
     * {@code CharmNum$ 2}: the seat chains a TARGETED mode (put target
     * noncreature permanent on top of its owner's library) together with the
     * untargeted tutor. The fixed seam must aim only the chained mode that
     * targets and still deliver the tutor's CHOOSE_CARD: Sol Ring ends on
     * top of the opponent's library AND Craterhoof lands in hand.
     */
    @Test(groups = "extended", timeOut = 240_000)
    public void primalCommandTwoModesReachTheSeatAndTutor() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            for (int i = 0; i < 5; i++) MailboxTestKit.put("Forest", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Primal Command", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Craterhoof Behemoth", k.seat, ZoneType.Library);
            for (int i = 0; i < 12; i++) MailboxTestKit.put("Forest", k.seat, ZoneType.Library);
            for (String n : new String[] {"Llanowar Elves", "Kogla, the Titan Ape", "Temur Sabertooth"}) {
                MailboxTestKit.put(n, k.seat, ZoneType.Library);
            }
            MailboxTestKit.put("Sol Ring", k.opp, ZoneType.Battlefield);   // the targeted mode's prey
            for (int i = 0; i < 2; i++) MailboxTestKit.put("Island", k.opp, ZoneType.Library);
            final boolean[] played = {false};
            k.startBrain(body -> {
                if (body.contains("\"decisionType\":\"CHOOSE_MODE\"")) {
                    String top = MailboxTestKit.idOf(body, "Put target noncreature permanent");
                    String tutor = MailboxTestKit.idOf(body, "Search your library for a creature");
                    return top != null && tutor != null
                            ? "{\"chosen\": [" + top + ", " + tutor + "]}" : null;
                }
                if (body.contains("\"decisionType\":\"CHOOSE_ENTITY\"")) {
                    String id = MailboxTestKit.idOf(body, "Sol Ring");
                    return id != null ? "{\"chosenId\": " + id + "}" : null;
                }
                if (body.contains("\"decisionType\":\"CHOOSE_CARD\"")) {
                    String id = MailboxTestKit.idOf(body, "Craterhoof");
                    return id != null ? "{\"chosenId\": " + id + "}" : null;
                }
                if ((body.contains("\"decisionType\":\"CAST_SPELL\"")
                        || body.contains("\"decisionType\":\"REACT\"")) && !played[0]) {
                    String id = MailboxTestKit.idOf(body, "Primal Command");
                    if (id != null) {
                        played[0] = true;
                        return "{\"chosenId\": " + id + "}";
                    }
                }
                return null;
            });
            k.run(() -> played[0] && has(k.seat, ZoneType.Hand, "Craterhoof Behemoth"), 300);

            boolean modeAsked = k.seen.stream().anyMatch(x -> x.contains("\"decisionType\":\"CHOOSE_MODE\""));
            boolean searchAsked = k.seen.stream().anyMatch(x -> x.contains("\"decisionType\":\"CHOOSE_CARD\""));
            boolean aimAsked = k.seen.stream().anyMatch(x -> x.contains("\"decisionType\":\"CHOOSE_ENTITY\"")
                    && x.contains("Sol Ring"));
            forge.game.card.CardCollectionView oppLib = k.opp.getCardsIn(ZoneType.Library);
            String oppTop = oppLib.isEmpty() ? "(empty)" : oppLib.get(0).getName();
            System.out.println("PRIMAL COMMAND test: cast=" + played[0] + " modeAsked=" + modeAsked
                    + " aimAsked=" + aimAsked + " searchAsked=" + searchAsked
                    + " hoofInHand=" + has(k.seat, ZoneType.Hand, "Craterhoof Behemoth")
                    + " oppTop=" + oppTop + " reqs=" + k.seen.size());
            Assert.assertTrue(played[0], "Primal Command was never cast through the mailbox");
            Assert.assertTrue(modeAsked, "mode choice never reached the seat");
            Assert.assertTrue(aimAsked, "the chained targeted mode must be aimed by the seat");
            Assert.assertTrue(searchAsked,
                    "library search never reached the seat — the seat's chosen modes were discarded");
            Assert.assertTrue(has(k.seat, ZoneType.Hand, "Craterhoof Behemoth"),
                    "Craterhoof should be in hand after the tutor mode resolves");
            Assert.assertEquals(oppTop, "Sol Ring", "the targeted mode must have put Sol Ring on top");
            Assert.assertFalse(has(k.opp, ZoneType.Battlefield, "Sol Ring"), "Sol Ring must have left the battlefield");
        }
    }
}
