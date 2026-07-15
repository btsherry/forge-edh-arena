package forge.arena.engine;

import java.util.Optional;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.card.CardRules;
import forge.item.PaperCard;
import forge.model.FModel;

/**
 * Card-DB lookups for prep artifacts (v3.3 deck-cards.json — the oracle-text
 * package handed to the LLM in bindgen/stall autopsy). Engine package: the
 * only place allowed to touch forge.item/forge.card.
 */
public final class CardCatalog {

    private CardCatalog() {
    }

    /** Resolve a card name against the loaded DB; empty if unimplemented/unknown. */
    public static Optional<CardInfo> describe(String name) {
        if (!ArenaBootstrap.isInitialized()) {
            throw new IllegalStateException("ArenaBootstrap.initialize() first");
        }
        PaperCard card = FModel.getMagicDb().getCommonCards().getCard(name);
        if (card == null) {
            return Optional.empty();
        }
        CardRules rules = card.getRules();
        return Optional.of(new CardInfo(
                card.getName(),
                String.valueOf(rules.getManaCost()),
                String.valueOf(rules.getType()),
                String.valueOf(rules.getColorIdentity()),
                rules.getOracleText()));
    }
}
