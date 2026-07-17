package forge.arena.combo;

/**
 * The narrow sandbox surface executors validate against (plan §6/§9 W2):
 * a COPY of the game — activations here can never touch the real game. The
 * implementation ({@code engine/GameSimHandle}) is the only place allowed to
 * drive Forge for simulation; this interface keeps combo/ pure (W8: combo/
 * depends on nothing engine-side but SeatView, and on its own contracts).
 */
public interface SimHandle {

    /**
     * Activate an ability of the named battlefield card, matched by a cost
     * hint (e.g. "{G}" for Selvala's mana ability, "{3}" for the
     * Mantle-granted untap-pump). Costs are paid by the engine's own AI cost
     * payment — lands tap, floating mana spends, {Q} untap-costs untap.
     *
     * @return false when the card/ability isn't found, costs can't be paid,
     *         or the ability needs targets (v1: unscripted targets are
     *         nondeterministic, so they are refused — target scripting is a
     *         Step concern, not a validation concern)
     */
    boolean activate(String cardName, String costHint);

    /** Total floating mana in the perspective player's pool. */
    int manaPoolTotal();

    /** Greatest power among creatures the perspective player controls. */
    int greatestOwnPower();

    /** True when the named battlefield card exists and is untapped. */
    boolean untapped(String cardName);
}
