package forge.arena.interactive;

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
 * Regression for the 2026-08-17 vanished-commander defect. Selvala's brain
 * chose a commander recast at base cost {1}{G}{G} when the true bill was 7
 * (two prior casts -> +4 tax); the mana payer refused; upstream Forge's
 * failed-payment path moved the card stack->stack and invalidated it — the
 * commander was in NO zone for the rest of the game.
 *
 * Two layers now stand between a seat and that hole:
 *  1. MailboxController.playChosenSpellAbility refuses an unaffordable cast
 *     locally (card stays put, priority kept);
 *  2. ComputerUtil.handlePlayingSpellAbility rolls a failed payment back to
 *     the card's ORIGIN zone (arena patch replacing the upstream FIXME).
 * This test drives the engine layer directly (the mailbox layer is a plain
 * refusal): a commander with tax, insufficient mana, cast attempted -> the
 * commander must be back in the command zone afterwards, still castable.
 */
public class UnaffordableCastRollbackTest {

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
    public void failedCommanderPaymentReturnsToCommandZone() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("seat", null)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();

        Card selvala = put("Selvala, Heart of the Wilds", p, ZoneType.Command);
        p.addCommander(selvala);
        // two prior casts -> +4 tax; base {1}{G}{G} -> 7 total
        p.incCommanderCast(selvala);
        p.incCommanderCast(selvala);
        for (int i = 0; i < 3; i++) {
            put("Forest", p, ZoneType.Battlefield);   // only 3 mana available
        }
        Assert.assertEquals(p.getCommanderCast(selvala), 2);

        // Attempt the cast through the AI cast path with insufficient mana.
        forge.game.spellability.SpellAbility castSa = selvala.getFirstSpellAbility();
        castSa.setActivatingPlayer(p);
        boolean played = forge.ai.ComputerUtil.handlePlayingSpellAbility(p, castSa, null);
        Assert.assertFalse(played, "a 7-mana commander cast with 3 mana must not succeed");

        // The defect: card in NO zone. The fix: back in the command zone.
        Card after = null;
        for (Card c : p.getCardsIn(ZoneType.Command)) {
            if (c.getName().equals("Selvala, Heart of the Wilds")) {
                after = c;
            }
        }
        Assert.assertNotNull(after, "commander must return to the command zone after a failed payment "
                + "(was: stack=" + game.getStack().size() + ", zones="
                + game.getZoneOf(selvala) + ")");
        Assert.assertTrue(game.getStack().isEmpty(), "nothing should be left on the stack");
    }

    /**
     * BL-11 second card (group {@code extended}). The seam is the commander
     * cast path itself (commander tax applied by CostAdjustment at payment,
     * failed payment rolled back to the ORIGIN zone), not Selvala: Urza, Lord
     * High Artificer — a legendary creature with a printed cost ({2}{U}{U})
     * and an ETB trigger ({@code T:Mode$ ChangesZone | ... | Execute$
     * TrigUrzaConstruct}) that must NOT fire — with two prior casts owes 8
     * and holds 3 Islands.
     */
    @Test(groups = "extended", timeOut = 180_000)
    public void failedUrzaPaymentReturnsToCommandZone() throws Exception {
        ArenaBootstrap.initialize(new java.io.File("..", "forge-gui"));
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("seat", null)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player p = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, p);
        game.getPhaseHandler().onStackResolved();

        Card urza = put("Urza, Lord High Artificer", p, ZoneType.Command);
        p.addCommander(urza);
        // two prior casts -> +4 tax; base {2}{U}{U} -> 8 total
        p.incCommanderCast(urza);
        p.incCommanderCast(urza);
        for (int i = 0; i < 3; i++) {
            put("Island", p, ZoneType.Battlefield);   // only 3 mana available
        }
        Assert.assertEquals(p.getCommanderCast(urza), 2);

        forge.game.spellability.SpellAbility castSa = urza.getFirstSpellAbility();
        castSa.setActivatingPlayer(p);
        boolean played = forge.ai.ComputerUtil.handlePlayingSpellAbility(p, castSa, null);
        Assert.assertFalse(played, "an 8-mana commander cast with 3 mana must not succeed");

        Card after = null;
        for (Card c : p.getCardsIn(ZoneType.Command)) {
            if (c.getName().equals("Urza, Lord High Artificer")) {
                after = c;
            }
        }
        Assert.assertNotNull(after, "commander must return to the command zone after a failed payment "
                + "(was: stack=" + game.getStack().size() + ", zones="
                + game.getZoneOf(urza) + ")");
        Assert.assertTrue(game.getStack().isEmpty(), "nothing should be left on the stack");
        Assert.assertTrue(p.getCardsIn(ZoneType.Battlefield).size() == 3,
                "no Construct token: the ETB must not have fired for a cast that never happened");
    }
}
