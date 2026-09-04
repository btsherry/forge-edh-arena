package forge.arena.interactive;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import com.google.common.collect.Lists;

import forge.StaticData;
import forge.ai.ComputerUtilCost;
import forge.ai.ComputerUtilMana;
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
 * BL-01 (2026-09-04), forge-ai payer patch: a player with a
 * {@code PayLifeInsteadOf:<C>} keyword (K'rrik's static) whose sources cannot
 * cover every shard pays the {@code <C>} shards with life FIRST and keeps the
 * sources for the shards life cannot pay. Game 19 t44: three Swamps, 40 life,
 * Mikaeus at {3}{B}{B}{B} — stock spent the Swamps on the black pips, found
 * nothing for the generic, and reported unpayable. Two spells, two board
 * shapes, and the gate proven to be the keyword (no K'rrik → still refused).
 * Stock players, no mailbox: this guards a parent-module patch.
 */
public class LifeForManaPayerTest {

    private Game game;
    private Player me;

    private Card put(String name, Player p, ZoneType z) {
        IPaperCard pc = FModel.getMagicDb().getCommonCards().getCard(name);
        if (pc == null) {
            StaticData.instance().attemptToLoadCard(name);
            pc = FModel.getMagicDb().getCommonCards().getCard(name);
        }
        Assert.assertNotNull(pc, "Forge must know " + name);
        Card c = Card.fromPaperCard(pc, p);
        c.setGameTimestamp(p.getGame().getNextTimestamp());
        p.getZone(z).add(c);
        return c;
    }

    private void board(boolean krrik, int swamps) {
        for (Card c : new ArrayList<>(me.getCardsIn(ZoneType.Battlefield))) {
            me.getZone(ZoneType.Battlefield).remove(c);
        }
        for (int i = 0; i < swamps; i++) {
            put("Swamp", me, ZoneType.Battlefield);
        }
        if (krrik) {
            put("K'rrik, Son of Yawgmoth", me, ZoneType.Battlefield);
        }
        game.getAction().checkStateEffects(true); // applies K'rrik's static (the keyword)
        Assert.assertEquals(me.hasKeyword("PayLifeInsteadOf:B"), krrik, "keyword state");
    }

    private SpellAbility inHand(String spell) {
        for (Card c : new ArrayList<>(me.getCardsIn(ZoneType.Hand))) {
            me.getZone(ZoneType.Hand).remove(c);
        }
        Card card = put(spell, me, ZoneType.Hand);
        SpellAbility sa = card.getFirstSpellAbility();
        sa.setActivatingPlayer(me);
        return sa;
    }

    @Test(timeOut = 240_000)
    public void lifeCoversTheColouredPipsOnlyWhenSourcesAreShort() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("me", null)));
        GameRules rules = new GameRules(GameType.Commander);
        game = new Game(players, rules, new Match(rules, players, "t"));
        me = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, me);
        game.getPhaseHandler().onStackResolved();
        me.setLife(40, null);

        // shape 1: {3}{B}{B}{B} with three Swamps — payable ONLY through life
        board(true, 3);
        SpellAbility mikaeus = inHand("Mikaeus, the Unhallowed");
        Assert.assertTrue(ComputerUtilCost.canPayCost(mikaeus, me, false),
                "K'rrik: 3 Swamps on generic + 6 life on {B}{B}{B} is a legal payment");
        Assert.assertTrue(ComputerUtilMana.payManaCost(mikaeus.getPayCosts(), me, mikaeus, false),
                "the real payment succeeds");
        Assert.assertEquals(me.getLife(), 34, "exactly the three black pips were paid with life");
        Assert.assertEquals(me.getCardsIn(ZoneType.Battlefield).stream()
                .filter(c -> c.getName().equals("Swamp") && c.isTapped()).count(), 3L,
                "every Swamp went to the generic pips");

        // shape 2: {2}{B} with three Swamps — sources suffice, NO life spent
        me.setLife(40, null);
        board(true, 3);
        SpellAbility bones = inHand("Read the Bones");
        Assert.assertTrue(ComputerUtilCost.canPayCost(bones, me, false));
        Assert.assertTrue(ComputerUtilMana.payManaCost(bones.getPayCosts(), me, bones, false));
        Assert.assertEquals(me.getLife(), 40, "a cost mana alone can pay never costs life");

        // shape 1 again but with a two-mana rock: only the shortfall goes to life
        me.setLife(40, null);
        board(true, 3);
        put("Sol Ring", me, ZoneType.Battlefield);
        game.getAction().checkStateEffects(true);
        SpellAbility mikaeus2 = inHand("Mikaeus, the Unhallowed");
        Assert.assertTrue(ComputerUtilCost.canPayCost(mikaeus2, me, false));
        Assert.assertTrue(ComputerUtilMana.payManaCost(mikaeus2.getPayCosts(), me, mikaeus2, false));
        Assert.assertTrue(me.getLife() >= 36 && me.getLife() <= 38,
                "five mana from sources leaves at most one or two pips to life, got life " + me.getLife());

        // the gate is the keyword: no K'rrik, same board -> stock still refuses
        me.setLife(40, null);
        board(false, 3);
        SpellAbility mikaeus3 = inHand("Mikaeus, the Unhallowed");
        Assert.assertFalse(ComputerUtilCost.canPayCost(mikaeus3, me, false),
                "without the keyword three Swamps cannot pay {3}{B}{B}{B}");
        Assert.assertEquals(me.getLife(), 40);
    }
}
