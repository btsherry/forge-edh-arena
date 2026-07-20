package forge.arena.combo;

import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The ninth archetype (PR-65): the <b>self-bounce recast loop</b>, found by
 * the first hand-run of the new ingestion pattern rather than by a human
 * reading decklists.
 *
 * <p>A creature whose own activated ability returns ITSELF to hand while
 * producing mana (Grinning Ignus: {@code Cost$ R Return<1/CARDNAME> |
 * Produced$ C C R}), plus a battery that refunds the per-cycle deficit
 * (Runaway Steam-Kin: three counters from casting red spells, spent for
 * {@code {R}{R}{R}}). Each cycle the creature leaves and re-enters the
 * battlefield.
 *
 * <p><b>Why this could not reuse {@link CastBounceManaLoop}.</b> That
 * archetype needs a separate {@code bouncer} permanent whose cast-trigger
 * returns a {@code rock}. Here there is no second card — the engine bounces
 * itself, so the params, the step order, and the profitability arithmetic
 * are all different. The whole-deck synthesis DID claim CastBounceManaLoop
 * was executable for this line; it was wrong, and only checking the
 * archetype's required params against the card script caught it. That is
 * why executability is verified rather than asserted.
 *
 * <p><b>The product is ETB TRIGGERS, not mana.</b> Over three cycles the
 * loop is exactly mana-neutral — it can run forever and bank nothing. What
 * it produces is repeated creature entries, which a payoff like Purphoros
 * converts into damage. So this loop must be STEPPED PHYSICALLY and must
 * never be compressed to a bounded mana product: compression would discard
 * the very entries the payoff feeds on (the same mistake PR-51 guarded
 * against for cast triggers).
 *
 * <p>Params: {@code engine}, {@code activation_cost}, {@code engine_produces},
 * {@code recast_cost}, {@code battery}, {@code battery_cost},
 * {@code battery_produces}, {@code casts_per_charge}, {@code bank_cycles}.
 */
public final class SelfBounceRecastLoop implements LineExecutor {

    public static final String ARCHETYPE = "SelfBounceRecastLoop";

    private final String engine;
    private final String activationCost;
    private final int engineProduces;
    private final int recastCost;
    private final String battery;
    private final String batteryCost;
    private final int batteryProduces;
    private final int castsPerCharge;
    private final int bankCycles;
    private final String entryPhase;

    public SelfBounceRecastLoop(Map<String, String> params, String entryPhase) {
        this.engine = require(params, "engine");
        this.activationCost = params.getOrDefault("activation_cost", "{R}");
        this.engineProduces = Integer.parseInt(params.getOrDefault("engine_produces", "3"));
        this.recastCost = Integer.parseInt(params.getOrDefault("recast_cost", "3"));
        this.battery = require(params, "battery");
        this.batteryCost = params.getOrDefault("battery_cost", "SubCounter<3/P1P1>");
        this.batteryProduces = Integer.parseInt(params.getOrDefault("battery_produces", "3"));
        this.castsPerCharge = Integer.parseInt(params.getOrDefault("casts_per_charge", "3"));
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
        return List.of("ASSEMBLY", "BOUNCE_LOOP");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    @Override
    public List<String> lineCards() {
        return List.of(engine, battery);
    }

    /**
     * Per-cycle arithmetic, amortising the battery over the casts it takes
     * to charge it. One cycle nets {@code produces - activation - recast};
     * the battery refunds {@code batteryProduces} every {@code castsPerCharge}
     * casts. Sustainable when the sum is at least break-even, because the
     * PRODUCT is entries rather than mana — a loop that merely pays for
     * itself is still infinite damage given an entry payoff.
     */
    public SimResult mathProfitable() {
        int perCycle = engineProduces - 1 - recastCost;
        double amortised = perCycle + (double) batteryProduces / Math.max(1, castsPerCharge);
        return amortised >= 0 ? SimResult.profitable(1) : SimResult.unprofitable();
    }

    /** Both pieces on the battlefield; either castable from hand is a step. */
    @Override
    public List<Step> assemblySteps(SeatView view) {
        for (String piece : List.of(battery, engine)) {
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
     * The engine's self-bounce must actually produce its claimed mana on the
     * copy — the one number a wrong binding would invent. The recast half is
     * ordinary casting and is attested by the Spellbook entry, exactly as in
     * {@link CastBounceManaLoop}.
     */
    @Override
    public SimResult validate(SimHandle sim) {
        if (!mathProfitable().isProfitable()) {
            return SimResult.unprofitable();
        }
        int before = sim.manaPoolTotal();
        if (!sim.activate(engine, activationCost, List.of())) {
            return SimResult.blocked("engine");
        }
        if (sim.manaPoolTotal() - before < engineProduces - 1) {
            return SimResult.blocked("engine_yield");
        }
        return SimResult.profitable(1);
    }

    /**
     * Alternate activate and recast: the engine is in HAND after every
     * activation, so the next activation is only legal once it has been
     * recast — and that recast is exactly the creature entry the payoff
     * needs. Even iterations activate, odd iterations recast.
     */
    @Override
    public Step next(LineState state, SeatView view) {
        if (state.iteration() >= bankCycles * 2) {
            return Step.done();
        }
        return state.iteration() % 2 == 0
                ? Step.activate(engine, activationCost)
                : Step.cast(engine);
    }
}
