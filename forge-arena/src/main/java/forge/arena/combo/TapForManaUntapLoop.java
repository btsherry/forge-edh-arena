package forge.arena.combo;

import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The first executor archetype (plan §6/§10 Phase 4): tap an engine
 * permanent for mana, untap it, repeat — Selvala + Umbral Mantle / Staff of
 * Domination class. Two validation layers:
 *
 * <ul>
 *   <li>{@link #mathProfitable} — the plan §8 arithmetic (net per cycle =
 *       yield − cycle cost, engine pump compounding): cheap, engine-free,
 *       used by tests and (later) the tracker's cheap pre-check;
 *   <li>{@link #validate} — the real proof on a {@link SimHandle} game copy:
 *       three full cycles with the engine's own cost payment, profitable
 *       only when the FINAL cycle grows the mana pool (steady state — early
 *       cycles may be land-funded and would read as false profit) and the
 *       engine ends untapped (repeatable).
 * </ul>
 */
public final class TapForManaUntapLoop implements LineExecutor {

    public static final String ARCHETYPE = "TapForManaUntapLoop";
    private static final int CYCLES = 3;

    private final String engine;
    private final String untapper;
    private final String activationCost;
    private final String untapCost;
    /** Card hosting the untap ability: Mantle GRANTS it to the engine. */
    private final String untapAbilityHost;
    private final int selfPumpPerCycle;
    private final String entryPhase;

    public TapForManaUntapLoop(Map<String, String> params, String entryPhase) {
        this.engine = require(params, "engine");
        this.untapper = require(params, "untapper");
        this.activationCost = require(params, "activation_cost");
        this.untapCost = require(params, "untap_cost");
        this.untapAbilityHost = "engine".equals(params.get("untap_ability_host")) ? engine : untapper;
        this.selfPumpPerCycle = Integer.parseInt(params.getOrDefault("self_pump_per_cycle", "0"));
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
        return List.of("MANA_LOOP");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    /**
     * Plan §8 SelvalaMantleMathTest semantics: floating += yield − cycle
     * cost per cycle; the engine pumps itself between cycles; going negative
     * means the costs are unpayable from the loop (needs floated mana up
     * front); strictly positive floating = profitable.
     */
    public SimResult mathProfitable(int engineStartPower, int greatestOtherPower, int floatedMana) {
        int cycleCost = cmc(activationCost) + cmc(untapCost);
        int enginePower = engineStartPower;
        int floating = floatedMana;
        for (int cycle = 1; cycle <= CYCLES; cycle++) {
            int yield = Math.max(enginePower, greatestOtherPower);
            floating += yield - cycleCost;
            if (floating < 0) {
                return SimResult.blocked("mana");
            }
            if (floating > 0) {
                return SimResult.profitable(cycle);
            }
            enginePower += selfPumpPerCycle;
        }
        return SimResult.unprofitable();
    }

    /** Generic-mana estimate of a cost string: digits count face value, symbols count 1. */
    static int cmc(String cost) {
        int total = 0;
        for (String part : cost.replace("{", " ").replace("}", " ").trim().split("\\s+")) {
            if (part.isEmpty()) {
                continue;
            }
            try {
                total += Integer.parseInt(part);
            } catch (NumberFormatException e) {
                total += 1; // colored symbol
            }
        }
        return total;
    }

    @Override
    public SimResult validate(SimHandle sim) {
        int lastCycleDelta = 0;
        for (int cycle = 1; cycle <= CYCLES; cycle++) {
            int poolAtCycleStart = sim.manaPoolTotal();
            if (!sim.activate(engine, activationCost)) {
                return SimResult.blocked("engine");
            }
            if (!sim.activate(untapAbilityHost, untapCost)) {
                return SimResult.blocked("untapper");
            }
            if (!sim.untapped(engine)) {
                return SimResult.blocked("engine_not_untapped");
            }
            lastCycleDelta = sim.manaPoolTotal() - poolAtCycleStart;
        }
        // steady state only: cycle 1-2 costs may be land-funded, which floats
        // mana without proving the loop feeds itself
        return lastCycleDelta > 0 ? SimResult.profitable(CYCLES) : SimResult.unprofitable();
    }

    @Override
    public Step next(LineState state, SeatView view) {
        // MANA_LOOP script: engine activation and untap alternate (PR-15's
        // controller consumes this; validation above never calls it)
        if (state.iteration() % 2 == 0) {
            return Step.activate(engine, activationCost);
        }
        return Step.activate(untapAbilityHost, untapCost);
    }
}
