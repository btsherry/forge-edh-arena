package forge.arena.interactive;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Map.Entry;
import java.util.Random;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import forge.card.mana.ManaCost;
import forge.card.mana.ManaCostShard;
import forge.deck.Deck;
import forge.item.PaperCard;
import forge.game.player.RegisteredPlayer;

/**
 * Cosmetic seat-avatar assignment for the arena. Each seat gets a built-in Forge
 * avatar ({@code sprite_avatars.png}, 126 heads) chosen to match its deck's color
 * character: tally the colored mana pips across the deck, weighted-random a color
 * in proportion to that composition, then pick a head from that color's pool
 * (seeded per launch, without replacement across seats). New decks get a themed
 * avatar for free — nothing is per-deck-authored.
 *
 * <p>The color->heads index is the checked-in resource
 * {@code /forge/arena/avatar-colors.json} (built once by an offline vision pass;
 * see docs/research). The selection RNG is a fresh {@link Random} — deliberately
 * NOT {@code MyRandom} — so avatars vary per launch without perturbing game
 * determinism.
 *
 * <p><b>Fail-safe:</b> purely cosmetic, so every path is wrapped — any failure
 * (missing/garbled resource, API surprise) silently leaves {@code avatarIndex} at
 * -1 and Forge's own default avatar applies. It must never block a game launch.
 */
final class SeatAvatars {

    private static final String RESOURCE = "/forge/arena/avatar-colors.json";
    private static final char[] WUBRG = {'W', 'U', 'B', 'R', 'G'};
    private static final ManaCostShard[] MONO = {
            ManaCostShard.WHITE, ManaCostShard.BLUE, ManaCostShard.BLACK,
            ManaCostShard.RED, ManaCostShard.GREEN };

    private SeatAvatars() { }

    /** Test seam: the parsed color->heads pools (null on failure). */
    static Map<Character, int[]> loadPoolsForTest() {
        return loadPools();
    }

    /** Assign a color-matched, distinct avatar to each seat. Never throws. */
    static void assign(final List<RegisteredPlayer> players) {
        try {
            final Map<Character, int[]> pools = loadPools();
            if (pools == null || pools.isEmpty()) {
                return; // no index -> Forge default avatars
            }
            int maxIdx = 0;
            for (int[] arr : pools.values()) {
                for (int v : arr) { maxIdx = Math.max(maxIdx, v); }
            }
            final Random rng = new Random();
            final java.util.Set<Integer> used = new HashSet<>();
            final StringBuilder log = new StringBuilder("[arena] seat avatars:");
            int seat = 0;
            for (RegisteredPlayer rp : players) {
                try {
                    final int idx = pickForDeck(rp.getDeck(), pools, rng, used, maxIdx + 1);
                    if (idx >= 0) {
                        rp.getPlayer().setAvatarIndex(idx);
                        used.add(idx);
                    }
                    log.append(" seat").append(seat).append('=').append(idx)
                       .append('(').append(rp.getDeck() != null
                               ? rp.getDeck().getName() : "?").append(')');
                } catch (Throwable perSeat) {
                    log.append(" seat").append(seat).append("=ERR");
                }
                seat++;
            }
            System.err.println(log);
        } catch (Throwable t) {
            System.err.println("[arena] seat-avatar assignment skipped: " + t);
        }
    }

    /** Weighted color by pip composition, then a head from that color's pool. */
    private static int pickForDeck(final Deck deck, final Map<Character, int[]> pools,
                                   final Random rng, final java.util.Set<Integer> used,
                                   final int count) {
        final int[] w = new int[5]; // W U B R G
        if (deck != null) {
            for (PaperCard c : deck.getCommanders()) { tally(c, 1, w); }
            if (deck.getMain() != null) {
                for (Entry<PaperCard, Integer> e : deck.getMain()) {
                    tally(e.getKey(), e.getValue() == null ? 1 : e.getValue(), w);
                }
            }
        }
        int total = 0;
        for (int v : w) { total += v; }

        char color = 'C';
        if (total > 0) {
            int r = rng.nextInt(total), acc = 0;
            for (int i = 0; i < 5; i++) {
                acc += w[i];
                if (r < acc) { color = WUBRG[i]; break; }
            }
        }
        // preferred color -> any of the deck's colors -> colorless -> any head
        int idx = pickHead(pools.get(color), rng, used);
        if (idx < 0) {
            for (int i = 0; i < 5 && idx < 0; i++) {
                if (w[i] > 0) { idx = pickHead(pools.get(WUBRG[i]), rng, used); }
            }
        }
        if (idx < 0) { idx = pickHead(pools.get('C'), rng, used); }
        if (idx < 0) { idx = anyUnused(rng, used, count); }
        return idx;
    }

    private static void tally(final PaperCard card, final int qty, final int[] w) {
        if (card == null || card.getRules() == null) { return; }
        final ManaCost mc = card.getRules().getManaCost();
        if (mc == null) { return; }
        for (int i = 0; i < 5; i++) {
            w[i] += mc.getShardCount(MONO[i]) * qty;
        }
    }

    /** Pick a still-unused head from a pool; if all are used, reuse one. -1 if none. */
    private static int pickHead(final int[] pool, final Random rng, final java.util.Set<Integer> used) {
        if (pool == null || pool.length == 0) { return -1; }
        final List<Integer> free = new ArrayList<>();
        for (int v : pool) { if (!used.contains(v)) { free.add(v); } }
        if (!free.isEmpty()) { return free.get(rng.nextInt(free.size())); }
        return pool[rng.nextInt(pool.length)]; // pool exhausted across seats
    }

    private static int anyUnused(final Random rng, final java.util.Set<Integer> used, final int count) {
        if (count <= 0) { return -1; }
        for (int tries = 0; tries < count * 2; tries++) {
            int v = rng.nextInt(count);
            if (!used.contains(v)) { return v; }
        }
        return rng.nextInt(count);
    }

    /** Parse the {@code by_color} arrays from the JSON resource. */
    private static Map<Character, int[]> loadPools() {
        final String text = readResource();
        if (text == null) { return null; }
        final Map<Character, int[]> pools = new HashMap<>();
        // matches only  "W": [ints]  (by_index uses "colors":[strings] and numeric keys)
        final Matcher m = Pattern.compile("\"([WUBRGC])\"\\s*:\\s*\\[([0-9,\\s]*)\\]").matcher(text);
        while (m.find()) {
            final char color = m.group(1).charAt(0);
            final String body = m.group(2).trim();
            final List<Integer> ids = new ArrayList<>();
            if (!body.isEmpty()) {
                for (String tok : body.split(",")) {
                    tok = tok.trim();
                    if (!tok.isEmpty()) { ids.add(Integer.parseInt(tok)); }
                }
            }
            final int[] arr = new int[ids.size()];
            for (int i = 0; i < arr.length; i++) { arr[i] = ids.get(i); }
            pools.put(color, arr);
        }
        return pools;
    }

    private static String readResource() {
        try (InputStream in = SeatAvatars.class.getResourceAsStream(RESOURCE)) {
            if (in == null) { return null; }
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (Throwable t) {
            return null;
        }
    }
}
