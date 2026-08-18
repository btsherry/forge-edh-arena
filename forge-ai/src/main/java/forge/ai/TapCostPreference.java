package forge.ai;

import forge.game.card.CardCollection;
import forge.game.spellability.SpellAbility;

/**
 * [arena] Optional controller hook: pre-select specific cards for a
 * {@link forge.game.cost.CostTapType} payment ("tap an untapped artifact you
 * control", "tap two untapped creatures", ...).
 *
 * <p>Motivation (2026-08-17, game 7): the meaningful play "tap your own
 * Winter Orb via Urza at the opponent's end step so YOUR untap step escapes
 * the lock" is expressible only through WHICH card pays a tap cost — stock
 * {@link AiCostDecision} picks tap payments by its own heuristics and would
 * never tap the symmetry piece on purpose. A controller implementing this
 * interface can name the card(s) it wants tapped first; stock heuristics
 * fill any remainder and remain the full decision-maker for every
 * controller that does not implement the interface (additive, no-harm).
 */
public interface TapCostPreference {

    /**
     * Cards the controller wants tapped FIRST when paying a CostTapType of
     * {@code ability}, or {@code null}/empty for no preference. Invalid or
     * already-tapped entries are ignored by the payer.
     */
    CardCollection preferredTapCards(SpellAbility ability);
}
