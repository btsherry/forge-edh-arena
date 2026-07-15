package forge.arena.engine;

/** Forge-free card description for dossier artifacts (deck-cards.json). */
public record CardInfo(String name, String manaCost, String typeLine, String colorIdentity, String oracleText) {
}
