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
        // a failed REAL payment leaves the tapped sources' mana floating (the
        // engine's rollback refunds it; this fixture has no rollback): empty
        // the pool so one case's leftovers never pay the next case's shards
        me.getManaPool().resetPool();
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

        // a Combo producer (Choked Estuary: "Combo U B") is ONE mana, not two
        // (review 2026-09-04): 4 Swamps + the Estuary = 5 real for a cost of 6,
        // so exactly one pip goes to life; the old count (6) said "not short",
        // spent the Swamps on {B}{B}{B} and refused the generic.
        me.setLife(40, null);
        board(true, 4);
        put("Choked Estuary", me, ZoneType.Battlefield);
        game.getAction().checkStateEffects(true);
        SpellAbility mikaeusT = inHand("Mikaeus, the Unhallowed");
        Assert.assertTrue(ComputerUtilCost.canPayCost(mikaeusT, me, false),
                "five real mana + life must be payable");
        Assert.assertTrue(ComputerUtilMana.payManaCost(mikaeusT.getPayCosts(), me, mikaeusT, false));
        Assert.assertEquals(me.getLife(), 38, "one pip to life, the dual land counted once");

        // the gate is the keyword: no K'rrik, same board -> stock still refuses
        me.setLife(40, null);
        board(false, 3);
        SpellAbility mikaeus3 = inHand("Mikaeus, the Unhallowed");
        Assert.assertFalse(ComputerUtilCost.canPayCost(mikaeus3, me, false),
                "without the keyword three Swamps cannot pay {3}{B}{B}{B}");
        Assert.assertEquals(me.getLife(), 40);
    }

    private long tapped(String name) {
        return me.getCardsIn(ZoneType.Battlefield).stream()
                .filter(c -> c.getName().equals(name) && c.isTapped()).count();
    }

    /** BL-65 (game 20261107-184934 t26): a PHYREXIAN shard goes to life only
     *  when the sources are short of the remaining shards — the shard type is
     *  the gate, no keyword and no card name. Dismember {1}{B/P}{B/P} is the
     *  general shape; Solphim's {1}{R/P}{R/P} activation is the live one. */
    @Test(timeOut = 240_000)
    public void phyrexianShardsGoToLifeOnlyWhenSourcesAreShort() throws Exception {
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

        // two Swamps, 40 life: {1} and one {B/P} from the Swamps, the other {B/P} from life
        me.setLife(40, null);
        board(false, 2);
        SpellAbility dismember = inHand("Dismember");
        Assert.assertTrue(ComputerUtilCost.canPayCost(dismember, me, false),
                "two Swamps + 2 life is a legal payment for {1}{B/P}{B/P}");
        Assert.assertTrue(ComputerUtilMana.payManaCost(dismember.getPayCosts(), me, dismember, false),
                "the real payment succeeds");
        Assert.assertEquals(me.getLife(), 38, "exactly one Phyrexian pip was paid with life");
        Assert.assertEquals(tapped("Swamp"), 2L, "both Swamps were spent");

        // three Swamps: sources suffice, no life spent
        me.setLife(40, null);
        board(false, 3);
        SpellAbility dismember2 = inHand("Dismember");
        Assert.assertTrue(ComputerUtilCost.canPayCost(dismember2, me, false));
        Assert.assertTrue(ComputerUtilMana.payManaCost(dismember2.getPayCosts(), me, dismember2, false));
        Assert.assertEquals(me.getLife(), 40, "a cost mana alone can pay never costs life");

        // one Swamp: {1} from the Swamp, both {B/P} from life
        me.setLife(40, null);
        board(false, 1);
        SpellAbility dismember3 = inHand("Dismember");
        Assert.assertTrue(ComputerUtilCost.canPayCost(dismember3, me, false));
        Assert.assertTrue(ComputerUtilMana.payManaCost(dismember3.getPayCosts(), me, dismember3, false));
        Assert.assertEquals(me.getLife(), 36, "two Phyrexian pips to life, the generic to the Swamp");

        // at 2 life, life cannot pay: two Swamps alone cannot cover three shards
        me.setLife(2, null);
        board(false, 2);
        SpellAbility dismember4 = inHand("Dismember");
        Assert.assertFalse(ComputerUtilCost.canPayCost(dismember4, me, false),
                "life at 2 cannot pay a Phyrexian pip, and two Swamps cannot pay three shards");
        Assert.assertEquals(me.getLife(), 2);

        // the sources cannot cover the non-Phyrexian shards: the payment fails
        // WITHOUT spending life (a rollback refunds mana, never life) — stock's
        // behaviour kept (critic, round two): {3}{U/P} with two Islands
        me.setLife(40, null);
        board(false, 0);
        for (int i = 0; i < 2; i++) {
            put("Island", me, ZoneType.Battlefield);
        }
        SpellAbility metamorph = inHand("Phyrexian Metamorph");
        Assert.assertFalse(ComputerUtilCost.canPayCost(metamorph, me, false),
                "two Islands cannot pay {3}{U/P} even with life");
        Assert.assertFalse(ComputerUtilMana.payManaCost(metamorph.getPayCosts(), me, metamorph, false),
                "the real payment fails");
        Assert.assertEquals(me.getLife(), 40, "no life spent on a payment that was going to fail");
        // ... and with three Islands life bridges exactly the one Phyrexian pip
        me.setLife(40, null);
        board(false, 0);
        for (int i = 0; i < 3; i++) {
            put("Island", me, ZoneType.Battlefield);
        }
        SpellAbility metamorph2 = inHand("Phyrexian Metamorph");
        Assert.assertTrue(ComputerUtilCost.canPayCost(metamorph2, me, false));
        Assert.assertTrue(ComputerUtilMana.payManaCost(metamorph2.getPayCosts(), me, metamorph2, false));
        Assert.assertEquals(me.getLife(), 38);

        // colours count, not just mana (Gemini, round three): Tamiyo {2}{G}{G/U/P}{U}
        // with Forest, Forest, Sol Ring has four mana for four non-life shards but no
        // blue source — the payment fails WITHOUT life; add an Island and life
        // bridges exactly the Phyrexian pip
        me.setLife(40, null);
        board(false, 0);
        put("Forest", me, ZoneType.Battlefield);
        put("Forest", me, ZoneType.Battlefield);
        put("Sol Ring", me, ZoneType.Battlefield);
        game.getAction().checkStateEffects(true);
        SpellAbility tamiyo = inHand("Tamiyo, Compleated Sage");
        Assert.assertFalse(ComputerUtilCost.canPayCost(tamiyo, me, false), "no blue source: unpayable");
        Assert.assertFalse(ComputerUtilMana.payManaCost(tamiyo.getPayCosts(), me, tamiyo, false));
        Assert.assertEquals(me.getLife(), 40, "no life bled on a colour-starved payment");
        me.setLife(40, null);
        board(false, 0);
        put("Forest", me, ZoneType.Battlefield);
        put("Island", me, ZoneType.Battlefield);
        put("Sol Ring", me, ZoneType.Battlefield);
        game.getAction().checkStateEffects(true);
        SpellAbility tamiyo2 = inHand("Tamiyo, Compleated Sage");
        Assert.assertTrue(ComputerUtilCost.canPayCost(tamiyo2, me, false), "Forest, Island, Sol Ring + 2 life pays it");
        Assert.assertTrue(ComputerUtilMana.payManaCost(tamiyo2.getPayCosts(), me, tamiyo2, false));
        Assert.assertEquals(me.getLife(), 38);

        // the live shape: Solphim's {1}{R/P}{R/P}, Discard two cards with two Mountains
        me.setLife(37, null);
        board(false, 0);
        for (int i = 0; i < 2; i++) {
            put("Mountain", me, ZoneType.Battlefield);
        }
        Card solphim = put("Solphim, Mayhem Dominus", me, ZoneType.Battlefield);
        game.getAction().checkStateEffects(true);
        inHand("Gnoll War Band");
        put("Gemstone Caverns", me, ZoneType.Hand); // two cards to discard
        SpellAbility counter = null;
        for (SpellAbility a : solphim.getSpellAbilities()) {
            if (a.isActivatedAbility()) {
                counter = a;
            }
        }
        Assert.assertNotNull(counter, "Solphim's activated ability");
        counter.setActivatingPlayer(me);
        Assert.assertTrue(ComputerUtilCost.canPayCost(counter, me, false),
                "two Mountains + 2 life + two discards is a legal payment");
        Assert.assertTrue(ComputerUtilMana.payManaCost(counter.getPayCosts(), me, counter, false),
                "the mana part is paid: one {R/P} from life, the rest from the Mountains");
        Assert.assertEquals(me.getLife(), 35);
        Assert.assertEquals(tapped("Mountain"), 2L);
    }
}
