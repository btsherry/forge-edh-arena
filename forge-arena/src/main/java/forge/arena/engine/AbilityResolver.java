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
        for (SpellAbility sa : card.getAllPossibleAbilities(player, false)) {
            if (!sa.isActivatedAbility()) {
                continue;
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
        String normalizedCost = "{" + costString.toLowerCase()
                .replace("{", " ").replace("}", " ").replaceAll("[,:]", " ").trim()
                .replaceAll("\\s+", "}{") + "}";
        String normalizedHint = "{" + costHint.toLowerCase()
                .replace("{", " ").replace("}", " ").trim()
                .replaceAll("\\s+", "}{") + "}";
        return normalizedCost.contains(normalizedHint);
    }
}
