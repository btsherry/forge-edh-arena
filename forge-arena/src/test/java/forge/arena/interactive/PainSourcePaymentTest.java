package forge.arena.interactive;

import java.io.File;
import java.util.ArrayList;
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
 * pool. Probes ComputerUtilCost.canPayCost across source classes.
 *
 * <p>Harness boil (2026-08-28): ONE game; each probe SWAPS the battlefield
 * to exactly its source set before asking (canPayCost is read-only, and
 * fresh Card instances per probe mean no counter/state leakage). Oracle
 * isolation is preserved — a probe still sees ONLY its own sources, which
 * is the entire discriminating power of the test.
 */
public class PainSourcePaymentTest {

    private Game game;
    private Player me;

    private Card put(String name, Player p, ZoneType z) {
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

    /** Replace the probe player's battlefield with exactly {@code names};
     *  returns the freshly placed cards (index-aligned). */
    private List<Card> swapBattlefield(String[] names, String counterOn, String counterType) {
        for (Card c : new ArrayList<>(me.getCardsIn(ZoneType.Battlefield))) {
            me.getZone(ZoneType.Battlefield).remove(c);
        }
        List<Card> placed = new ArrayList<>();
        for (String n : names) {
            Card c = put(n, me, ZoneType.Battlefield);
            if (n.equals(counterOn) && counterType != null) {
                c.addCounterInternal(forge.game.card.CounterEnumType.valueOf(counterType),
                        1, me, false, null, null);
            }
            placed.add(c);
        }
        return placed;
    }

    private boolean probe(String[] battlefield, String spellName, ZoneType castFrom,
            String counterOn, String counterType) {
        swapBattlefield(battlefield, counterOn, counterType);
        Card spell = put(spellName, me, castFrom);
        SpellAbility sa = spell.getFirstSpellAbility();
        sa.setActivatingPlayer(me);
        boolean ok = ComputerUtilCost.canPayCost(sa, me, false);
        me.getZone(castFrom).remove(spell);
        System.out.println("PAYPROBE: " + java.util.Arrays.toString(battlefield)
                + " -> " + spellName + " : " + ok);
        return ok;
    }

    private boolean probeCommander(String[] battlefield, String counterOn, String counterType) {
        swapBattlefield(battlefield, counterOn, counterType);
        Card cmdr = me.getCardsIn(ZoneType.Command).isEmpty() ? null
                : me.getCardsIn(ZoneType.Command).get(0);
        SpellAbility sa = cmdr.getFirstSpellAbility();
        sa.setActivatingPlayer(me);
        boolean ok = ComputerUtilCost.canPayCost(sa, me, false);
        System.out.println("PAYPROBE-CMDR: " + java.util.Arrays.toString(battlefield)
                + " -> " + cmdr.getName() + " : " + ok);
        return ok;
    }

    private boolean probeActivation(String[] battlefield, String host) {
        List<Card> placed = swapBattlefield(battlefield, null, null);
        Card hostCard = placed.get(java.util.Arrays.asList(battlefield).indexOf(host));
        SpellAbility sa = hostCard.getSpellAbilities().get(0);
        for (SpellAbility cand : hostCard.getSpellAbilities()) {   // prefer the {2}... ability
            if (cand.getPayCosts() != null
                    && cand.getPayCosts().toSimpleString().contains("{2}")) {
                sa = cand;
                break;
            }
        }
        sa.setActivatingPlayer(me);
        boolean ok = ComputerUtilCost.canPayCost(sa, me, false);
        System.out.println("PAYPROBE-ACT: " + host + " with "
                + java.util.Arrays.toString(battlefield) + " : " + ok);
        return ok;
    }

    @Test(timeOut = 240_000)
    public void painAndConditionalSourcesArePayable() throws Exception {
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
        Card sythis = put("Sythis, Harvest's Hand", me, ZoneType.Command);
        me.addCommander(sythis);   // Command Tower's mana = commander identity

        boolean control = probe(new String[]{"Mountain"}, "Shock", ZoneType.Hand, null, null);
        boolean tombRing = probe(new String[]{"Ancient Tomb"}, "Sol Ring", ZoneType.Hand, null, null);
        boolean tombMedallion = probe(new String[]{"Ancient Tomb"}, "Ruby Medallion", ZoneType.Hand, null, null);
        boolean caverns = probe(new String[]{"Gemstone Caverns"}, "Sol Ring", ZoneType.Hand, null, null);

        // live shapes from games 10-12
        boolean sythisCast = probeCommander(new String[]{"Gemstone Caverns", "Command Tower"},
                "Gemstone Caverns", "LUCK");   // {G}{W}
        boolean nykthos = probeActivation(
                new String[]{"Nykthos, Shrine to Nyx", "Ancient Tomb", "Plains"},
                "Nykthos, Shrine to Nyx");     // {2},{T} devotion
        boolean ctl2 = probeCommander(new String[]{"Forest", "Plains"}, null, null);
        boolean towerHalf = probeCommander(new String[]{"Command Tower", "Plains"}, null, null);
        boolean cavernsHalf = probeCommander(new String[]{"Gemstone Caverns", "Plains"},
                "Gemstone Caverns", "LUCK");
        boolean twoTowers = probeCommander(new String[]{"Command Tower", "Command Tower"}, null, null);
        System.out.println("PAYPROBE-SUMMARY: sythisCast=" + sythisCast
                + " nykthosActivation=" + nykthos + " | forest+plains=" + ctl2
                + " tower+plains=" + towerHalf + " caverns+plains=" + cavernsHalf
                + " tower+tower=" + twoTowers);

        Assert.assertTrue(control, "control failed: Mountain can't pay Shock — probe broken");
        Assert.assertTrue(tombMedallion,
                "THE LIVE BUG: Ancient Tomb ({C}{C}) refused for a {2} cast");
        Assert.assertTrue(tombRing, "Ancient Tomb refused for a {1} cast");
        Assert.assertTrue(caverns, "Gemstone Caverns refused for a {1} cast");
        Assert.assertTrue(sythisCast,
                "THE GAME-12 BUG: Caverns(luck)+Command Tower refused for the "
                + "{G}{W} commander cast — condition-forked mana invisible to "
                + "the payer (guards the ComputerUtilMana effective-part walk)");
        Assert.assertTrue(cavernsHalf,
                "Caverns(luck)+Plains refused for {G}{W} — the fork's Any "
                + "branch must be visible at payment time");
        Assert.assertTrue(nykthos, "Nykthos {2},{T} activation unpayable from Tomb");
    }
}
