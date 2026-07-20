package forge.arena.engine;

import java.util.List;

import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * The ONE place a scripted step (card name + cost hint + explicit targets)
 * becomes an engine {@code SpellAbility} — shared by sandbox validation
 * ({@link GameSimHandle}) and live execution (ComboAwareController), so what
 * was proven on the copy is exactly what gets played for real.
 */
final class AbilityResolver {

    private AbilityResolver() {
    }

    /**
     * Find and configure the ability, or null: card not on the player's
     * battlefield, no cost-hint match, unscripted targeting, or a named
     * target missing/illegal. Targets are resolved on the player's own
     * battlefield (combo pieces target the combo's own permanents).
     */
    static SpellAbility resolve(Player player, String cardName, String costHint,
            List<String> targetNames) {
        Card card = findBattlefield(player, cardName);
        if (card == null) {
            return null;
        }
        // getAllPossibleAbilities walks the CURRENT state, so abilities
        // granted by attachments/statics (the Mantle pump lives on Selvala
        // only while equipped) are included
        // PR-60: among abilities that match the cost hint, prefer the one
        // that produces the MOST mana.
        //
        // The search below returns the first match, which silently picks the
        // wrong ability whenever a card has two mana abilities at the same
        // cost. Fanatic of Rhonas is the case that surfaced it: "{T}: Add
        // {G}" and "Ferocious — {T}: Add {G}{G}{G}{G}" both cost {T}, so a
        // loop binding got the one-mana version, netted negative against a
        // {3} untap cost, and was correctly rejected as unprofitable — a
        // working combo, invisible because we asked for the wrong ability.
        //
        // A combo that names a card and a cost always wants that cost's
        // best yield; nobody scripts a loop around the weaker half of a
        // card. Deck-agnostic (no names, no card list) and mana-only: every
        // other ability class keeps first-match, because "most" is only
        // meaningful for a quantity.
        SpellAbility bestMana = null;
        int bestYield = -1;
        for (SpellAbility sa : card.getAllPossibleAbilities(player, false)) {
            if (!sa.isActivatedAbility() || costHint == null || !sa.isManaAbility()
                    || sa.getPayCosts() == null
                    || !costMatches(sa.getPayCosts().toString(), costHint)
                    || sa.usesTargeting() != !targetNames.isEmpty()) {
                continue;
            }
            int yield = manaYield(sa);
            if (yield > bestYield) {
                bestYield = yield;
                bestMana = sa;
            }
        }
        if (bestMana != null) {
            bestMana.setActivatingPlayer(player);
            return bestMana;
        }

        for (SpellAbility sa : card.getAllPossibleAbilities(player, false)) {
            if (!sa.isActivatedAbility()) {
                continue;
            }
            // PR-38: a null cost hint on a NON-targeting step means "find the
            // draw ability" — the conversion module's dig path names a
            // deployed engine (Sensei's Top, Staff of Domination) and the
            // engine layer discovers how it draws. Structural, not a list.
            if (costHint == null) {
                if (sa.getApi() != forge.game.ability.ApiType.Draw || sa.usesTargeting()) {
                    continue;
                }
                sa.setActivatingPlayer(player);
                return sa;
            }
            if (sa.getPayCosts() == null || !costMatches(sa.getPayCosts().toString(), costHint)) {
                continue;
            }
            if (sa.usesTargeting() != !targetNames.isEmpty()) {
                continue; // scripted targets and ability targeting must agree
            }
            sa.setActivatingPlayer(player);
            if (!targetNames.isEmpty()) {
                sa.resetTargets();
                for (String targetName : targetNames) {
                    Card target = findBattlefield(player, targetName);
                    if (target == null || !sa.canTarget(target)) {
                        return null;
                    }
                    sa.getTargets().add(target);
                }
            }
            return sa;
        }
        return null;
    }

    /**
     * How much mana an ability produces per activation, as a comparable
     * number (PR-60). Reads the card script's own {@code Amount}, which
     * defaults to 1 when absent — Sol Ring is {@code Produced$ C | Amount$
     * 2}, Fanatic of Rhonas's weak half is {@code Produced$ G} with no
     * Amount at all.
     *
     * <p>A variable amount ({@code Amount$ X}, Sanctum Weaver's
     * enchantment count) scores 1: unknowable without evaluating the board,
     * and deliberately never allowed to WIN a comparison on a guess. It
     * still resolves normally when it is the only ability at that cost,
     * and the executor's copy-validation measures its real yield anyway.
     */
    private static int manaYield(SpellAbility sa) {
        String amount = sa.getParam("Amount");
        if (amount == null) {
            return 1;
        }
        try {
            return Integer.parseInt(amount.trim());
        } catch (NumberFormatException notAConstant) {
            return 1;
        }
    }

    /**
     * PR-37 (Phase 6 A3): the player-target variant — an outlet activation
     * aimed at an OPPONENT (Ballista/Reservoir class, "any target"). Same
     * search as {@link #resolve}, but the scripted target is a player.
     */
    static SpellAbility resolveAtPlayer(Player player, String cardName, String costHint,
            Player targetPlayer) {
        Card card = findBattlefield(player, cardName);
        if (card == null) {
            return null;
        }
        for (SpellAbility sa : card.getAllPossibleAbilities(player, false)) {
            if (!sa.isActivatedAbility() || !sa.usesTargeting()) {
                continue;
            }
            // PR-38: a null cost hint means DISCOVER the outlet's ability
            // structurally — the pilot names the card (from the deck's own
            // payoff artifacts) and the engine layer finds the activation
            // that can actually hurt a player. Damage or life loss only;
            // "any target" abilities that merely tap or draw are not sinks.
            if (costHint == null) {
                if (sa.getApi() != forge.game.ability.ApiType.DealDamage
                        && sa.getApi() != forge.game.ability.ApiType.LoseLife) {
                    continue;
                }
            } else if (sa.getPayCosts() == null
                    || !costMatches(sa.getPayCosts().toString(), costHint)) {
                continue;
            }
            sa.setActivatingPlayer(player);
            sa.resetTargets();
            if (!sa.canTarget(targetPlayer)) {
                return null;
            }
            sa.getTargets().add(targetPlayer);
            return sa;
        }
        return null;
    }

    static Card findBattlefield(Player player, String cardName) {
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.getName().equals(cardName)) {
                return c;
            }
        }
        return null;
    }

    /**
     * Resolve a {@code cast} assembly step (PR-18): the named card's spell,
     * from hand or the command zone (commander tax and MayPlay statics are
     * the engine's business — getAllPossibleAbilities carries them). Null
     * when the card isn't castable here and now (missing, or costs
     * unpayable) — the pilot records the abort and retries next turn.
     */
    static SpellAbility resolveCast(Player player, String cardName) {
        for (ZoneType zone : List.of(ZoneType.Hand, ZoneType.Command)) {
            for (Card card : player.getCardsIn(zone)) {
                if (!card.getName().equals(cardName)) {
                    continue;
                }
                for (SpellAbility sa : card.getAllPossibleAbilities(player, true)) {
                    if (!sa.isSpell()) {
                        continue;
                    }
                    sa.setActivatingPlayer(player);
                    if (forge.ai.ComputerUtilCost.canPayCost(sa, player, false)) {
                        return sa;
                    }
                }
            }
        }
        return null;
    }

    /**
     * Cost matching by normalized symbol containment: hint "{3}" matches
     * "{3}, {Q}: ..." but not "{13}". Hints are whole symbols, so a binding
     * distinguishes Staff's {1}/{3}/{5} abilities unambiguously.
     */
    static boolean costMatches(String costString, String costHint) {
        // PR-37: non-mana costs (counter removal, sacrifice) carry no brace
        // symbols — a braceless hint matches by raw substring instead
        if (!costHint.contains("{")) {
            return costString.toLowerCase().contains(costHint.toLowerCase());
        }
        String normalizedCost = "{" + costString.toLowerCase()
                .replace("{", " ").replace("}", " ").replaceAll("[,:]", " ").trim()
                .replaceAll("\\s+", "}{") + "}";
        String normalizedHint = "{" + costHint.toLowerCase()
                .replace("{", " ").replace("}", " ").trim()
                .replaceAll("\\s+", "}{") + "}";
        return normalizedCost.contains(normalizedHint);
    }
}
