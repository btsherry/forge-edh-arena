package forge.arena.interactive;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.testng.Assert;
import org.testng.annotations.Test;

import forge.ai.LobbyPlayerAi;
import forge.arena.bootstrap.ArenaBootstrap;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.player.RegisteredPlayer;

/**
 * Isolates SeatAvatars.assign() from the GUI pipeline (game-8/avatar handoff,
 * 2026-08-19): live launches showed W-pool heads on mono-red Purphoros twice
 * in a row, which a correct R-weighted pick cannot produce — this proves (or
 * disproves) that OUR half assigns the right pools, pinning the corruption
 * (if any) downstream of assign().
 */
public class SeatAvatarsAssignTest {

    private static Deck load(String name) {
        File f = new File(new File("decks"), name);
        Deck d = DeckSerializer.fromFile(f);
        Assert.assertNotNull(d, "deck missing: " + f);
        return d;
    }

    @Test(timeOut = 240_000)
    public void assignedHeadsMatchDeckColorPools() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        Map<Character, int[]> pools = SeatAvatars.loadPoolsForTest();
        Assert.assertNotNull(pools, "avatar-colors.json failed to load");

        String[] decks = {"selvala-heart-of-the-wilds.dck",
                "purphoros-god-of-the-forge.dck", "giada-font-of-hope.dck",
                "urza-lord-high-artificer.dck"};
        char[] expected = {'G', 'R', 'W', 'U'};   // dominant color per deck

        int trials = 40;
        int[] correct = new int[4];
        for (int t = 0; t < trials; t++) {
            List<RegisteredPlayer> players = new ArrayList<>();
            for (String d : decks) {
                RegisteredPlayer rp = new RegisteredPlayer(load(d));
                rp.setPlayer(new LobbyPlayerAi(d, null));
                players.add(rp);
            }
            SeatAvatars.assign(players);
            java.util.Set<Integer> seen = new java.util.HashSet<>();
            for (int i = 0; i < 4; i++) {
                int idx = players.get(i).getPlayer().getAvatarIndex();
                Assert.assertTrue(idx >= 0, "seat " + i + " got no avatar");
                Assert.assertTrue(seen.add(idx),
                        "duplicate head across seats in one launch: " + idx);
                if (contains(pools.get(expected[i]), idx)) {
                    correct[i]++;
                }
            }
        }
        System.out.println("AVATAR test: pool-hit rates over " + trials
                + " trials — selvala G:" + correct[0] + " purphoros R:" + correct[1]
                + " giada W:" + correct[2] + " urza U:" + correct[3]);
        // Mono decks must hit their color pool essentially always (the only
        // colored pips are that color); allow a couple of fallback picks.
        Assert.assertTrue(correct[0] >= trials - 2, "Selvala not green enough");
        Assert.assertTrue(correct[1] >= trials - 2, "Purphoros not red enough");
        Assert.assertTrue(correct[2] >= trials - 2, "Giada not white enough");
        // Urza runs a few off-color pips historically; still expect strong U.
        Assert.assertTrue(correct[3] >= (int) (trials * 0.8), "Urza not blue enough");
    }

    private static boolean contains(int[] pool, int v) {
        if (pool == null) return false;
        for (int x : pool) if (x == v) return true;
        return false;
    }
}
