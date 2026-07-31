package forge.arena.prep;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Reads INSTANT-SPEED protection covers out of a deck's card text — the reactive
 * shields that keep an assembled combo alive when an opponent points removal at a
 * piece. Sibling of {@link PairedPlayFinder}: Commander Spellbook never lists
 * "Heroic Intervention protects Selvala", so it is reasoned from oracle text.
 *
 * <p>Only INSTANTS qualify (a cover has to resolve while the threat waits on the
 * stack). Static/enchantment protection (Asceticism) is a proactive deploy, not a
 * reactive cover, and is out of scope here. The pilot consumes the emitted
 * {@code protection-priorities.json}; the controller casts the cheapest cover
 * whose scope saves the threatened piece.
 */
public final class ProtectionFinder {

    /** What a cover saves. ALL_PERMANENTS saves any piece (creature, artifact,
     *  land); CREATURES saves only creature pieces. */
    public enum Scope {
        CREATURES,
        ALL_PERMANENTS;

        /** Does a cover of THIS scope save a piece of the given kind? */
        public boolean covers(boolean pieceIsCreature) {
            return this == ALL_PERMANENTS || pieceIsCreature;
        }
    }

    /** One reactive cover: cast {@code card} to shield a piece of {@code scope}. */
    public record Cover(String card, Scope scope, int manaValue) {
    }

    // "<permanents|creatures> you control gain/have <hexproof|indestructible|
    // protection from ...|shroud>" — a same-controller grant of a save keyword
    private static final Pattern GRANT = Pattern.compile(
            "(creatures|permanents) you control (gain|have|gains)[^.]*?"
            + "(hexproof|indestructible|protection from|shroud)");

    private ProtectionFinder() {
    }

    /** The reactive cover a card provides, or null when it is not one. Public so
     *  it can be unit-tested against known card text. */
    public static Cover coverOf(String name, String oracleText, String typeLine, String manaCost) {
        String types = typeLine == null ? "" : typeLine.toLowerCase(Locale.ROOT);
        if (!types.contains("instant")) {
            return null; // reactive covers must resolve while the threat waits
        }
        Matcher m = GRANT.matcher(normalize(oracleText));
        if (!m.find()) {
            return null;
        }
        Scope scope = "permanents".equals(m.group(1)) ? Scope.ALL_PERMANENTS : Scope.CREATURES;
        return new Cover(name, scope, PairedPlayFinder.manaValue(manaCost));
    }

    /** Every reactive cover in the deck, cheapest first. */
    public static List<Cover> find(JsonNode deckCards) {
        List<Cover> covers = new ArrayList<>();
        for (JsonNode card : deckCards.get("cards")) {
            Cover cover = coverOf(card.path("name").asText(""),
                    card.path("oracle_text").asText(""),
                    card.path("type_line").asText(""),
                    card.path("mana_cost").asText(""));
            if (cover != null) {
                covers.add(cover);
            }
        }
        covers.sort(java.util.Comparator.comparingInt(Cover::manaValue));
        return covers;
    }

    private static String normalize(String oracleText) {
        return oracleText == null ? ""
                : oracleText.replace("\\n", " ").replace('\n', ' ').toLowerCase(Locale.ROOT);
    }
}
