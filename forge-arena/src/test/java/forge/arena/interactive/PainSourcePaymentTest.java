package forge.arena.interactive;

import java.io.File;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.Test;

import com.google.common.collect.Lists;

import forge.StaticData;
import forge.ai.ComputerUtilCost;
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
 * Game-12 finding 3 (six live incidents): the AI auto-payer refuses casts
 * payable from Ancient Tomb / Gemstone Caverns-class sources with an empty
 * pool. This probes ComputerUtilCost.canPayCost directly across source
 * classes to pin exactly which source the payer can't see.
 */
public class PainSourcePaymentTest {

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

    private static boolean probeActivation(String[] battlefield, String host, int saIndex) {
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
        Card hostCard = null;
        for (String n : battlefield) {
            Card c = put(n, me, ZoneType.Battlefield);
            if (n.equals(host)) hostCard = c;
        }
        List<SpellAbility> sas = Lists.newArrayList(hostCard.getSpellAbilities());
        SpellAbility sa = sas.get(Math.min(saIndex, sas.size() - 1));
        for (SpellAbility cand : sas) {   // prefer the costed ({2}...) ability
            if (cand.getPayCosts() != null
                    && cand.getPayCosts().toSimpleString().contains("{2}")) {
                sa = cand;
                break;
            }
        }
        sa.setActivatingPlayer(me);
        boolean ok = ComputerUtilCost.canPayCost(sa, me, false);
        System.out.println("PAYPROBE-ACT: " + host + " sa[" + saIndex + "]='"
                + sa.toString().substring(0, Math.min(60, sa.toString().length()))
                + "' with " + java.util.Arrays.toString(battlefield) + " : " + ok);
        return ok;
    }

    private static boolean probeCast(String[] battlefield, String spellName,
            String counterOn, String counterType) {
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
        for (String n : battlefield) {
            Card c = put(n, me, ZoneType.Battlefield);
            if (n.equals(counterOn) && counterType != null) {
                c.addCounterInternal(forge.game.card.CounterEnumType.valueOf(counterType),
                        1, me, false, null, null);
            }
        }
        Card spell = put(spellName, me, ZoneType.Command);
        me.addCommander(spell);   // Command Tower's mana = commander identity
        SpellAbility sa = spell.getFirstSpellAbility();
        sa.setActivatingPlayer(me);
        boolean ok = ComputerUtilCost.canPayCost(sa, me, false);
        System.out.println("PAYPROBE-CAST: " + java.util.Arrays.toString(battlefield)
                + " -> " + spellName + " (commander) : " + ok);
        return ok;
    }

    private static boolean probe(String landName, String spellName) {
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
        put(landName, me, ZoneType.Battlefield);
        Card spell = put(spellName, me, ZoneType.Hand);
        SpellAbility sa = spell.getFirstSpellAbility();
        sa.setActivatingPlayer(me);
        boolean ok = ComputerUtilCost.canPayCost(sa, me, false);
        System.out.println("PAYPROBE: " + landName + " -> " + spellName + " : " + ok);
        return ok;
    }

    @Test(timeOut = 240_000)
    public void painAndConditionalSourcesArePayable() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        boolean island = probe("Island", "Omen of the Sea");        // {1}{U} — control, needs 2 lands... use cheap
        boolean control = probe("Mountain", "Shock");               // {R} — control: MUST be true
        boolean tombRing = probe("Ancient Tomb", "Sol Ring");       // {1} off {C}{C}
        boolean tombMedallion = probe("Ancient Tomb", "Ruby Medallion"); // {2} — the live case
        boolean caverns = probe("Gemstone Caverns", "Sol Ring");    // {1} off {C}

        // live shapes from games 10-12
        boolean sythis = probeCast(new String[]{"Gemstone Caverns", "Command Tower"},
                "Sythis, Harvest's Hand", "Gemstone Caverns", "LUCK");   // {G}{W}
        boolean nykthos = probeActivation(
                new String[]{"Nykthos, Shrine to Nyx", "Ancient Tomb", "Plains"},
                "Nykthos, Shrine to Nyx", 1);                            // {2},{T} devotion
        boolean ctl2 = probeCast(new String[]{"Forest", "Plains"},
                "Sythis, Harvest's Hand", null, null);
        boolean towerHalf = probeCast(new String[]{"Command Tower", "Plains"},
                "Sythis, Harvest's Hand", null, null);
        boolean cavernsHalf = probeCast(new String[]{"Gemstone Caverns", "Plains"},
                "Sythis, Harvest's Hand", "Gemstone Caverns", "LUCK");
        boolean twoTowers = probeCast(new String[]{"Command Tower", "Command Tower"},
                "Sythis, Harvest's Hand", null, null);
        System.out.println("PAYPROBE-SUMMARY: sythisCast=" + sythis
                + " nykthosActivation=" + nykthos + " | forest+plains=" + ctl2
                + " tower+plains=" + towerHalf + " caverns+plains=" + cavernsHalf
                + " tower+tower=" + twoTowers);

        Assert.assertTrue(control, "control failed: Mountain can't pay Shock — probe broken");
        Assert.assertTrue(tombMedallion,
                "THE LIVE BUG: Ancient Tomb ({C}{C}) refused for a {2} cast");
        Assert.assertTrue(tombRing, "Ancient Tomb refused for a {1} cast");
        Assert.assertTrue(caverns, "Gemstone Caverns refused for a {1} cast");
        Assert.assertTrue(sythis,
                "THE GAME-12 BUG: Caverns(luck)+Command Tower refused for the "
                + "{G}{W} commander cast — condition-forked mana invisible to "
                + "the payer (guards the ComputerUtilMana effective-part walk)");
        Assert.assertTrue(cavernsHalf,
                "Caverns(luck)+Plains refused for {G}{W} — the fork's Any "
                + "branch must be visible at payment time");
        Assert.assertTrue(nykthos, "Nykthos {2},{T} activation unpayable from Tomb");
    }
}
