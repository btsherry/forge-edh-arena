package forge.arena.combo;

import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The eighth archetype (PR-50): the <b>self-topdeck recast loop</b>. An
 * artifact that draws a card and then puts ITSELF on top of your library
 * (Sensei's Divining Top) becomes an engine once two things are true — a
 * cost reducer makes recasting it free, and something lets you cast from
 * the top of your library. Then: tap to draw, the engine goes on top, cast
 * it for nothing, tap again. Every cycle draws a card.
 *
 * <p>Six of Urza's unbound combos are this exact shape with interchangeable
 * parts (Etherium Sculptor / Foundry Inspector / Cloud Key as the reducer;
 * The Reality Chip or Forensic Gadgeteer as the top-cast enabler), which is
 * why it earns an archetype rather than six hand-written bindings.
 *
 * <p><b>The product is CARDS, not mana</b>, so there is no pool to compress
 * — and that is exactly what makes it valuable here: it feeds the
 * conversion module's dig path directly. Drawing the deck is how a seat
 * with a live engine and no outlet in hand finds one.
 *
 * <p>The loop is stepped PHYSICALLY rather than compressed, because the
 * engine card alternates zones every half-cycle: after the draw it is on
 * top of the library, not the battlefield, so the next activation is only
 * legal once it has been recast. Even iterations activate, odd iterations
 * recast. Bounded by {@code bank_cycles} and by the library itself — a
 * draw loop that outruns its deck kills its own pilot (CR 121.4/704.5b).
 *
 * <p>Params: {@code engine}, {@code cost_reducer}, {@code topdeck_enabler},
 * {@code activation_cost} (default {@code {T}}), {@code bank_cycles}.
 */
public final class SelfTopdeckRecastLoop implements LineExecutor {

    public static final String ARCHETYPE = "SelfTopdeckRecastLoop";

    private final String engine;
    private final String costReducer;
    private final String topdeckEnabler;
    private final String activationCost;
    private final int bankCycles;
    private final String entryPhase;

    /**
     * Never draw the library down past this. The loop's whole purpose is
     * to find an outlet, and decking yourself while looking for one turns
     * a won game into a loss at the next state-based check.
     */
    static final int LIBRARY_FLOOR = 6;

    public SelfTopdeckRecastLoop(Map<String, String> params, String entryPhase) {
        this.engine = require(params, "engine");
        this.costReducer = require(params, "cost_reducer");
        this.topdeckEnabler = require(params, "topdeck_enabler");
        this.activationCost = params.getOrDefault("activation_cost", "{T}");
        this.bankCycles = Integer.parseInt(params.getOrDefault("bank_cycles", "12"));
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
        return List.of("ASSEMBLY", "DRAW_LOOP");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    @Override
    public List<String> lineCards() {
        return List.of(engine, costReducer, topdeckEnabler);
    }

    /**
     * Both support pieces must be DEPLOYED — one to make the recast free,
     * one to make it legal from the library — and the engine itself must be
     * on the battlefield to tap. Any of them castable from hand is a step;
     * anything else is not this line from here.
     */
    @Override
    public List<Step> assemblySteps(SeatView view) {
        for (String piece : List.of(costReducer, topdeckEnabler, engine)) {
            SeatView.Presence where = view.locate(piece);
            if (where == SeatView.Presence.BATTLEFIELD) {
                continue;
            }
            if (where == SeatView.Presence.HAND || where == SeatView.Presence.COMMAND) {
                return List.of(Step.cast(piece));
            }
            return null;
        }
        return List.of();
    }

    /**
     * The engine's own draw activation must work on the copy. The recast
     * half is attested by the Spellbook entry (the W1 gate), exactly as the
     * bounce choreography is in {@link BounceRecastLoop}: a loop that
     * cannot actually sustain itself simply stops resolving, and the line
     * aborts and is recorded rather than spinning.
     */
    @Override
    public SimResult validate(SimHandle sim) {
        return sim.activate(engine, activationCost, List.of())
                ? SimResult.profitable(1)
                : SimResult.blocked("engine");
    }

    /**
     * Alternate tap and recast, because the engine changes zones every half
     * cycle. Stops at the cycle bound, or when the library can no longer
     * afford to be drawn from.
     */
    @Override
    public Step next(LineState state, SeatView view) {
        if (state.iteration() >= bankCycles * 2 || view.librarySize() <= LIBRARY_FLOOR) {
            return Step.done();
        }
        return state.iteration() % 2 == 0
                ? Step.activate(engine, activationCost)
                : Step.cast(engine);
    }
}
