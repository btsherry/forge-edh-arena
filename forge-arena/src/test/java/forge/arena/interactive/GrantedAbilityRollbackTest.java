package forge.arena.interactive;

import java.io.File;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import com.google.common.collect.Lists;

import forge.StaticData;
import forge.ai.ComputerUtil;
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
 * Vanish regression (2026-08-19, validation game): a FAILED payment on an
 * ability GRANTED by an attachment (Sanctum Weaver + Gauntlets of Light's
 * "{2}{W}: Untap") rolled back via GameActionUtil.rollbackAbility, whose
 * zone surgery resolves ability.getCardState().getCard() to the GRANTOR —
 * it removed the HOST from the battlefield and re-added the grantor: the
 * host vanished from every zone mid-combo. The fix scopes zone rollback to
 * real spell moves; activations refund the payment in place.
 */
public class GrantedAbilityRollbackTest {

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
    public void failedGrantedActivationMustNotVanishTheHost() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        List<RegisteredPlayer> players = Lists.newArrayList();
        Deck d = new Deck();
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("opp", null)));
        players.add(new RegisteredPlayer(d).setPlayer(new LobbyPlayerAi("me", null)));
        GameRules rules = new GameRules(GameType.Commander);
        Game game = new Game(players, rules, new Match(rules, players, "t"));
        Player me = game.getPlayers().get(1);
        game.setAge(GameStage.Play);
        game.getPhaseHandler().devModeSet(PhaseType.MAIN1, me);
        game.getPhaseHandler().onStackResolved();

        Card weaver = put("Sanctum Weaver", me, ZoneType.Battlefield);
        Card gauntlets = put("Gauntlets of Light", me, ZoneType.Battlefield);
        gauntlets.attachToEntity(weaver, null, true);
        weaver.setTapped(true);          // the loop shape: tapped, wanting the untap
        // NO mana sources: the {2}{W} payment must fail

        game.getAction().checkStaticAbilities();   // apply the AddAbility layer
        SpellAbility untap = null;
        for (SpellAbility sa2 : weaver.getAllPossibleAbilities(me, false)) {
            if (sa2.toString().contains("Untap")) {
                untap = sa2;
                break;
            }
        }
        Assert.assertNotNull(untap, "Gauntlets did not grant the untap ability");
        untap.setActivatingPlayer(me);

        boolean played = ComputerUtil.handlePlayingSpellAbility(me, untap, null);
        Assert.assertFalse(played, "payment should fail with no mana sources");

        boolean onBattlefield = weaver.isInZone(ZoneType.Battlefield);
        boolean gauntletsOn = gauntlets.isInZone(ZoneType.Battlefield);
        int copies = 0;
        for (Card c : me.getCardsIn(ZoneType.Battlefield)) {
            if (c.getName().equals("Gauntlets of Light")) copies++;
        }
        System.out.println("ROLLBACK test: weaverOnBf=" + onBattlefield
                + " gauntletsOnBf=" + gauntletsOn + " gauntletsCopies=" + copies);
        Assert.assertTrue(onBattlefield,
                "THE VANISH: the host of a granted ability must survive a failed payment");
        Assert.assertTrue(gauntletsOn, "the grantor must be untouched");
        Assert.assertEquals(copies, 1, "the grantor must not be duplicated by the rollback");
    }
}
