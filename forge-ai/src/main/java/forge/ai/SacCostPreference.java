package forge.ai;

import forge.game.card.CardCollection;
import forge.game.spellability.SpellAbility;

/**
 * [arena] Optional controller hook: pick WHICH cards pay a
 * {@link forge.game.cost.CostSacrifice} ("Sacrifice a creature:",
 * "As an additional cost ... sacrifice a creature", ...).
 *
 * <p>Motivation (2026-08-24): a seat that deliberately activates a sacrifice
 * outlet (Viscera Seer class) or casts a sacrifice-cost spell (Altar's Reap
 * class) is expressing a play LINE — sacrifice THIS creature (the one with
 * the death trigger, the about-to-be-exiled one, the token) — but stock
 * {@link AiCostDecision} picks the payment by its own worst-card heuristics
 * and can even refuse outright ({@code Amount$ All} is a blanket null),
 * silently thwarting the line the seat chose. A controller implementing this
 * interface names the exact payment; the payer vets it against the cost's
 * valid-type filter and falls back to stock heuristics on any mismatch.
 * Every controller that does not implement the interface keeps the original
 * path untouched (additive, no-harm — the {@link TapCostPreference} pattern).
 */
public interface SacCostPreference {

    /**
     * The exact cards the controller wants to sacrifice for the
     * CostSacrifice of {@code ability} ({@code amount} cards of the cost's
     * {@code type}), or {@code null} for no preference (stock heuristics
     * decide). Returned cards are validated by the payer; an invalid or
     * wrong-sized answer falls back to stock.
     */
    CardCollection preferredSacCards(SpellAbility ability, String type, int amount);
}
