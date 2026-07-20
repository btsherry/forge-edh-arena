package forge.arena.combo;

import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The fourth archetype (PR-31, Ben's insight from the Giada primer): a
 * NON-LOOP, combo-LIKE win condition — a one-sided sweep executed as a
 * PAIR: cast the trigger (a creature/land wipe) only while the protection
 * (an instant-speed board shield) is in hand with its mana RESERVED, then
 * cast the protection in response while the trigger is on the stack. The
 * analysis-100 evidence: stock cast wipes 48 times in 43 games with zero
 * coordination.
 *
 * <p>Paired plays are not Spellbook combos, so detection is BINDING-driven
 * (combo ids prefixed {@code pp-}): the pilot checks the pair directly —
 * both cards in hand, combined mana affordable, and a board worth punishing
 * (opponents' visible battlefield at least twice ours; deliberately coarse
 * v1, recorded in the line events). No loop, no shortcut, no validation
 * sim: two casts of the deck's own cards carry no hallucination risk (W1),
 * and the win that follows is stock combat from a dominant board.
 *
 * <p>Params: {@code trigger_card}, {@code protection_card},
 * {@code trigger_mana_value}, {@code protection_mana_value}.
 */
public final class PairedPlay implements LineExecutor {

    public static final String ARCHETYPE = "PairedPlay";

    private final String triggerCard;
    private final String protectionCard;
    private final int triggerManaValue;
    private final int protectionManaValue;
    private final String entryPhase;
    /** LANDS / CREATURES / NONLAND_PERMANENTS / ALL_PERMANENTS, or "" (v1 pairs). */
    private final String wipeScope;

    public PairedPlay(Map<String, String> params, String entryPhase) {
        this.wipeScope = params.getOrDefault("wipe_scope", "");
        this.triggerCard = require(params, "trigger_card");
        this.protectionCard = require(params, "protection_card");
        this.triggerManaValue = Integer.parseInt(params.getOrDefault("trigger_mana_value", "0"));
        this.protectionManaValue = Integer.parseInt(
                params.getOrDefault("protection_mana_value", "0"));
        this.entryPhase = entryPhase != null ? entryPhase : "MAIN1";
    }

    private static String require(Map<String, String> params, String key) {
        String value = params.get(key);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(ARCHETYPE + " binding missing param '" + key + "'");
        }
        return value;
    }

    @Override
    public String archetype() {
        return ARCHETYPE;
    }

    @Override
    public List<String> stages() {
        return List.of("PAIRED_CAST", "PAIRED_PROTECT");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    public String triggerCard() {
        return triggerCard;
    }

    public String protectionCard() {
        return protectionCard;
    }

    public int combinedManaValue() {
        return triggerManaValue + protectionManaValue;
    }

    /** Both cards in hand = playable; there is no assembly. */
    public boolean playable(SeatView view) {
        return view.locate(triggerCard) == SeatView.Presence.HAND
                && view.locate(protectionCard) == SeatView.Presence.HAND
                && view.manaPool() + view.untappedManaSources() >= combinedManaValue();
    }

    /**
     * Coarse v1 timing: opponents' combined visible battlefield at real
     * mid-game scale. The view is a NAME set per opponent — duplicates
     * (basics, token swarms) collapse, so the count undercounts wide
     * boards and the floor stays low: 8 distinct names across the table
     * is an established multiplayer board (the PR-33 gauntlet trace: a
     * 12-creature injected board read 11 after a 0/0 died, and the old
     * flat 12 never fired). Bounded by the once-per-pair-per-game and
     * both-cards+mana gates.
     */
    public boolean worthFiring(SeatView view) {
        return valueAgainst(view) > 0;
    }

    /**
     * PR-49: how much this pair is worth RIGHT NOW, against what the
     * opponents actually have. The pilot fires the highest-scoring
     * affordable pair, not the cheapest one.
     *
     * <p>The first 300-game batch with generated pairs made the flaw
     * obvious: every single pair the white deck used was its CHEAPEST
     * wipe, because pairs were offered cheapest-first and a 3-mana
     * sweeper always wins an affordability race. Its land-destruction
     * lines — the strongest thing the deck does — never fired once.
     *
     * <p>Value is the count of opponent permanents this scope would
     * actually destroy, so a land wipe scores high into a mana-heavy
     * table and a creature wipe scores high into a creature-heavy one,
     * and neither fires into a board it would barely dent. 0 = not worth
     * casting yet.
     */
    public int valueAgainst(SeatView view) {
        int hit = 0;
        for (SeatView.OpponentView opp : view.opponents()) {
            for (String card : opp.battlefield()) {
                if (scopeHits(card)) {
                    hit++;
                }
            }
        }
        // the same floor as before, now measured against what the wipe
        // really touches rather than the whole table
        return hit >= MIN_TARGETS ? hit : 0;
    }

    /** Board impact worth spending a two-card play on. */
    static final int MIN_TARGETS = 5;

    /**
     * Does this wipe hit that permanent? The seat view is name-level, so
     * lands are identified by the basic-land names plus the "s" of a
     * nonbasic being unnameable here — an approximation, deliberately
     * conservative: an unrecognised card counts as a nonland permanent.
     */
    private boolean scopeHits(String cardName) {
        boolean land = BASIC_LANDS.contains(cardName);
        return switch (wipeScope) {
            case "LANDS" -> land;
            case "CREATURES", "NONLAND_PERMANENTS" -> !land;
            case "ALL_PERMANENTS" -> true;
            // v1 hand-authored pairs carry no scope: keep the old
            // whole-board reading so their behaviour is unchanged
            default -> true;
        };
    }

    private static final java.util.Set<String> BASIC_LANDS = java.util.Set.of(
            "Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
            "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
            "Snow-Covered Mountain", "Snow-Covered Forest");

    @Override
    public List<String> lineCards() {
        return List.of(triggerCard, protectionCard);
    }

    @Override
    public SimResult validate(SimHandle sim) {
        return SimResult.profitable(1); // two own casts: nothing to prove on a copy
    }

    @Override
    public Step next(LineState state, SeatView view) {
        return Step.done();
    }
}
