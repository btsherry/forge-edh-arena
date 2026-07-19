package forge.arena.prep;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Phase 6 / PR-48 — find a deck's <b>paired plays</b> by reading card text.
 *
 * <p>These are not Spellbook combos and never will be: nothing about
 * "Armageddon plus Teferi's Protection" is deterministic or infinite, so no
 * combo database lists it. It is simply the best thing the deck does — blow
 * up a whole category of permanents while your own survive — and it has to
 * be reasoned out from oracle text.
 *
 * <p><b>The trap this class exists to avoid: SCOPE.</b> A wipe and a shield
 * only pair if the shield actually covers what the wipe destroys. "Creatures
 * you control gain indestructible" saves nothing at all from a card that
 * destroys all LANDS — pairing those would tell the pilot to blow up its own
 * mana base. So each side is classified by the permanent types it touches,
 * and a pair is emitted only when the protection's scope COVERS the wipe's.
 *
 * <p>Timing is the other requirement: the protection must be an INSTANT, so
 * it can be cast in response to the wipe already on the stack — resolving
 * first, granting the shield, and leaving the wipe to sweep everyone else.
 *
 * <p>Output is deck-scoped and fully general: any dropped-in deck with a
 * sweeper and a shield gets its pairs without anyone naming a card.
 */
public final class PairedPlayFinder {

    /** What a wipe destroys, or what a shield covers. */
    public enum Scope {
        /** Creatures only. */
        CREATURES,
        /** Lands only. */
        LANDS,
        /** Every nonland permanent. */
        NONLAND_PERMANENTS,
        /** Everything you control (phasing / blanket indestructible). */
        ALL_PERMANENTS;

        /** Does a shield of THIS scope save everything {@code wipe} destroys? */
        public boolean covers(Scope wipe) {
            if (this == ALL_PERMANENTS) {
                return true;
            }
            // a nonland-permanent shield saves creatures and other nonland
            // permanents, but NOT lands
            if (this == NONLAND_PERMANENTS) {
                return wipe == CREATURES || wipe == NONLAND_PERMANENTS;
            }
            // a creature shield saves creatures and nothing else — notably
            // NOT lands, which is the whole reason this check exists
            return this == CREATURES && wipe == CREATURES;
        }
    }

    /** One playable pair: cast {@code wipe}, answer with {@code protection}. */
    public record Pair(String wipe, Scope wipeScope, String protection, int combinedManaValue) {
        /** Stable id, mirroring the hand-authored {@code pp-} convention. */
        public String id() {
            return "pp-" + slug(wipe) + "-" + slug(protection);
        }

        private static String slug(String name) {
            return name.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "-")
                    .replaceAll("(^-|-$)", "");
        }
    }

    // "destroy all lands", "destroy all nonland permanents", "exile all creatures"...
    private static final Pattern WIPE = Pattern.compile(
            "(destroy|exile) all ([a-z ]*?)(permanents|creatures|lands)");
    // a shield reads as "<something> you control gain/have <keyword>", or phases out
    private static final Pattern SHIELD = Pattern.compile(
            "(creatures|permanents|nonland permanents) you control "
            + "(gain|have|gains)[^.]*?(indestructible|protection from everything|hexproof)"
            + "|permanents you control phase out");

    private PairedPlayFinder() {
    }

    /** The wipe scope of a card's text, or null when it is not a sweeper. */
    public static Scope wipeScope(String oracleText) {
        String text = normalize(oracleText);
        // a modal sweeper ("destroy all lands OR all creatures") can choose,
        // so treat it as the broader of its options
        boolean lands = text.contains("destroy all lands");
        // a modal sweeper reads "destroy all lands OR ALL CREATURES", so the
        // second option never contains the verb — match the bare option too
        boolean creatures = text.contains("destroy all creatures")
                || text.contains("exile all creatures")
                || text.contains("or all creatures");
        if (lands && creatures) {
            return Scope.ALL_PERMANENTS;
        }
        if (text.contains("all nonland permanents")) {
            return Scope.NONLAND_PERMANENTS;
        }
        if (lands) {
            return Scope.LANDS;
        }
        if (creatures) {
            return Scope.CREATURES;
        }
        return WIPE.matcher(text).find() ? Scope.NONLAND_PERMANENTS : null;
    }

    /** The scope a shield covers, or null when the card is not a shield. */
    public static Scope shieldScope(String oracleText) {
        String text = normalize(oracleText);
        if (!SHIELD.matcher(text).find()) {
            return null;
        }
        // ORDER MATTERS: "nonland permanents you control phase out" CONTAINS
        // "permanents you control phase out" as a substring, so the broad
        // check must come second. Clever Concealment phases out NONLAND
        // permanents only — it saves nothing from a land wipe, which is the
        // precise mistake this class was written to prevent, and the first
        // real deck run made it.
        if (text.contains("nonland permanents you control")) {
            return Scope.NONLAND_PERMANENTS;
        }
        if (text.contains("permanents you control phase out")
                || text.contains("permanents you control gain")
                || text.contains("permanents you control have")) {
            return Scope.ALL_PERMANENTS;
        }
        return Scope.CREATURES;
    }

    /**
     * Numeric mana value from a cost string like {@code {3}{W}} — the
     * dossier stores the printed cost, not a computed value. Generic
     * numerals add their number, every other symbol adds one, and {@code X}
     * counts as zero (its real value is chosen on the stack).
     */
    static int manaValue(String manaCost) {
        if (manaCost == null || manaCost.isBlank()) {
            return 0;
        }
        int total = 0;
        java.util.regex.Matcher m = Pattern.compile("\\{([^}]+)\\}").matcher(manaCost);
        while (m.find()) {
            String symbol = m.group(1);
            if (symbol.matches("\\d+")) {
                total += Integer.parseInt(symbol);
            } else if (!symbol.equalsIgnoreCase("X")) {
                total += 1;
            }
        }
        return total;
    }

    private static String normalize(String oracleText) {
        return oracleText == null ? ""
                : oracleText.replace("\\n", " ").replace('\n', ' ').toLowerCase(Locale.ROOT);
    }

    /**
     * Every legal pair in the deck, cheapest combined cost first (the pilot
     * fires the one it can afford soonest). A protection that is not an
     * INSTANT is skipped: it cannot answer a wipe already on the stack.
     */
    public static List<Pair> find(JsonNode deckCards) {
        Map<String, Scope> wipes = new LinkedHashMap<>();
        Map<String, Scope> shields = new LinkedHashMap<>();
        Map<String, Integer> costs = new LinkedHashMap<>();
        for (JsonNode card : deckCards.get("cards")) {
            String name = card.get("name").asText();
            String oracle = card.path("oracle_text").asText("");
            String types = card.path("type_line").asText("").toLowerCase(Locale.ROOT);
            costs.put(name, manaValue(card.path("mana_cost").asText("")));
            Scope wipe = wipeScope(oracle);
            if (wipe != null && (types.contains("instant") || types.contains("sorcery"))) {
                wipes.put(name, wipe);
            }
            Scope shield = shieldScope(oracle);
            // instants only: the shield has to resolve while the wipe waits
            if (shield != null && types.contains("instant")) {
                shields.put(name, shield);
            }
        }
        List<Pair> pairs = new ArrayList<>();
        for (Map.Entry<String, Scope> w : wipes.entrySet()) {
            for (Map.Entry<String, Scope> s : shields.entrySet()) {
                if (!s.getValue().covers(w.getValue())) {
                    continue;
                }
                pairs.add(new Pair(w.getKey(), w.getValue(), s.getKey(),
                        costs.getOrDefault(w.getKey(), 0) + costs.getOrDefault(s.getKey(), 0)));
            }
        }
        pairs.sort(java.util.Comparator.comparingInt(Pair::combinedManaValue));
        return pairs;
    }
}
