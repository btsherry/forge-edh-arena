package forge.ai;

import java.util.List;

import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.spellability.SpellAbility;

/**
 * [arena] Optional controller hook: pick WHICH cards pay a from-visible-zone
 * cost part — exile (Force of Will pitch), discard, return-to-hand
 * (Temur Sabertooth class), or put-to-library. One interface serves all four
 * {@link AiCostDecision} visit sites; {@code kind} names the cost type.
 *
 * <p>Motivation (2026-08-28 dual audit, consensus finding): a seat that
 * deliberately casts an alternative-cost spell is expressing a play line, but
 * stock heuristics pick the payment — {@code chooseExileFromList} sorts by
 * power ascending, meaningless for a hand of instants — and the pilot cannot
 * even see which card it is about to lose. Same fail-safe contract as
 * {@link TapCostPreference}/{@link SacCostPreference}: the payer vets the
 * answer against the cost's valid pool; {@code null} or any mismatch falls
 * through to stock, and controllers without the hook keep the original path
 * byte-identical.
 */
public interface PaymentPickPreference {

    /** Cost kinds routed through the hook. */
    String KIND_EXILE = "EXILE";
    String KIND_DISCARD = "DISCARD";
    String KIND_RETURN = "RETURN";
    String KIND_PUT_TO_LIBRARY = "PUT TO LIBRARY";

    /**
     * The exact {@code amount} cards (out of {@code valid}, all visible to
     * the payer) the controller wants to pay the {@code kind} cost of
     * {@code ability} with, or {@code null} for no preference (stock
     * heuristics decide).
     */
    CardCollection preferredPaymentCards(SpellAbility ability, String kind,
            List<Card> valid, int amount);
}
