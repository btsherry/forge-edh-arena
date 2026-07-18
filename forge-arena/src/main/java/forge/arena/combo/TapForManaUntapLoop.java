package forge.arena.combo;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The first executor archetype (plan §6/§10 Phase 4): tap an engine
 * permanent for mana, untap it, repeat — Selvala + Umbral Mantle / Staff of
 * Domination class. One step script drives BOTH validation and live play
 * ({@link #cycleSteps} — what was proven is what executes). Two validation
 * layers:
 *
 * <ul>
 *   <li>{@link #mathProfitable} — the plan §8 arithmetic (net per cycle =
 *       yield − cycle cost, engine pump compounding): cheap, engine-free;
 *   <li>{@link #validate} — the real proof on a {@link SimHandle} game copy:
 *       three full cycles with the engine's own cost payment, profitable
 *       only when the FINAL cycle grows the mana pool (steady state — early
 *       cycles may be land-funded and would read as false profit) and the
 *       engine ends untapped (repeatable).
 * </ul>
 *
 * <p>Params: {@code engine}, {@code untapper}, {@code activation_cost},
 * {@code untap_cost}, {@code untap_ability_host} (engine|untapper — Umbral
 * Mantle GRANTS its ability to the equipped creature), {@code
 * untap_targets_engine} (Staff's untap ability targets), {@code
 * untapper_reset_cost} (Staff re-readies itself for {1}), {@code
 * self_pump_per_cycle}, {@code bank_cycles} (PR-15 live-play primitive: run
 * this many cycles, then hand the floated mana to stock AI — the PR-16
 * shortcut/planner replaces counting with proving).
 */
public final class TapForManaUntapLoop implements LineExecutor, ShortcutSource {

    public static final String ARCHETYPE = "TapForManaUntapLoop";
    private static final int VALIDATE_CYCLES = 3;

    private final String engine;
    private final String untapper;
    private final String activationCost;
    private final String untapCost;
    /** Card hosting the untap ability: Mantle GRANTS it to the engine. */
    private final String untapAbilityHost;
    private final boolean untapTargetsEngine;
    private final String untapperResetCost;
    private final int selfPumpPerCycle;
    private final int bankCycles;
    private final boolean shortcutEligible;
    private final String poolColor;
    /** Equip/attach cost when the untap ability is GRANTED to the engine (Mantle: {0}). */
    private final String attachCost;
    private final int engineManaValue;
    private final int untapperManaValue;
    private final String entryPhase;

    public TapForManaUntapLoop(Map<String, String> params, String entryPhase) {
        this.engine = require(params, "engine");
        this.untapper = require(params, "untapper");
        this.activationCost = require(params, "activation_cost");
        this.untapCost = require(params, "untap_cost");
        this.untapAbilityHost = "engine".equals(params.get("untap_ability_host")) ? engine : untapper;
        this.untapTargetsEngine = Boolean.parseBoolean(params.getOrDefault("untap_targets_engine", "false"));
        this.untapperResetCost = params.get("untapper_reset_cost");
        this.selfPumpPerCycle = Integer.parseInt(params.getOrDefault("self_pump_per_cycle", "0"));
        this.bankCycles = Integer.parseInt(params.getOrDefault("bank_cycles", "6"));
        this.shortcutEligible = Boolean.parseBoolean(params.getOrDefault("shortcut", "true"));
        this.poolColor = params.getOrDefault("pool_color", "G");
        this.attachCost = params.get("attach_cost");
        this.engineManaValue = Integer.parseInt(params.getOrDefault("engine_mana_value", "0"));
        this.untapperManaValue = Integer.parseInt(params.getOrDefault("untapper_mana_value", "0"));
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
    public List<String> lineCards() {
        return List.of(engine, untapper);
    }

    @Override
    public List<String> stages() {
        return List.of("ASSEMBLY", "MANA_LOOP", "DEPLOY");
    }

    /**
     * PR-18 (from the first e2e run): reachable pieces get DEPLOYED before
     * the loop is provable — cast from hand/command, then attach when the
     * untap ability is equipment-granted. Incremental: returns the current
     * TODO each priority; the pilot plays the first item and asks again.
     */
    @Override
    public List<Step> assemblySteps(SeatView view) {
        List<Step> steps = new ArrayList<>();
        for (String piece : List.of(engine, untapper)) {
            switch (view.locate(piece)) {
                case BATTLEFIELD -> {
                }
                case HAND, COMMAND -> steps.add(Step.cast(piece));
                default -> {
                    return null; // graveyard/absent: not assemblable from here
                }
            }
        }
        if (steps.isEmpty() && untapAbilityHost.equals(engine) && attachCost != null
                && !engine.equals(view.ownAttachments().get(untapper))) {
            steps.add(Step.activateTargeting(untapper, attachCost, engine));
        }
        return steps;
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    /** The one loop cycle, as scripted steps — validation and live play both run THIS. */
    public List<Step> cycleSteps() {
        List<Step> steps = new ArrayList<>();
        steps.add(Step.activate(engine, activationCost));
        if (untapTargetsEngine) {
            steps.add(Step.activateTargeting(untapAbilityHost, untapCost, engine));
        } else {
            steps.add(Step.activate(untapAbilityHost, untapCost));
        }
        if (untapperResetCost != null && !untapperResetCost.isBlank()) {
            steps.add(Step.activate(untapper, untapperResetCost));
        }
        return steps;
    }

    /** Full cycle cost in generic-mana terms (activation + untap + reset). */
    int cycleCost() {
        return cmc(activationCost) + cmc(untapCost)
                + (untapperResetCost == null || untapperResetCost.isBlank() ? 0 : cmc(untapperResetCost));
    }

    /**
     * Plan §8 SelvalaMantleMathTest semantics: floating += yield − cycle
     * cost per cycle; the engine pumps itself between cycles; going negative
     * means the costs are unpayable from the loop (needs floated mana up
     * front); strictly positive floating = profitable.
     */
    public SimResult mathProfitable(int engineStartPower, int greatestOtherPower, int floatedMana) {
        int cost = cycleCost();
        int enginePower = engineStartPower;
        int floating = floatedMana;
        for (int cycle = 1; cycle <= VALIDATE_CYCLES; cycle++) {
            int yield = Math.max(enginePower, greatestOtherPower);
            floating += yield - cost;
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

    @Override
    public int castCostEstimate(String card) {
        if (card.equals(engine)) {
            return engineManaValue;
        }
        if (card.equals(untapper)) {
            return untapperManaValue;
        }
        return 0;
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
        List<Step> steps = cycleSteps();
        int lastCycleDelta = 0;
        for (int cycle = 1; cycle <= VALIDATE_CYCLES; cycle++) {
            int poolAtCycleStart = sim.manaPoolTotal();
            for (int i = 0; i < steps.size(); i++) {
                Step step = steps.get(i);
                if (!sim.activate(step.card(), step.costHint(), step.targets())) {
                    // blocked-by names the ROLE, not the card: with
                    // untap_ability_host=engine both steps live on the engine
                    return SimResult.blocked(i == 0 ? "engine" : "untapper");
                }
            }
            if (!sim.untapped(engine)) {
                return SimResult.blocked("engine_not_untapped");
            }
            lastCycleDelta = sim.manaPoolTotal() - poolAtCycleStart;
        }
        // steady state only: cycle 1-2 costs may be land-funded, which floats
        // mana without proving the loop feeds itself
        return lastCycleDelta > 0 ? SimResult.profitable(VALIDATE_CYCLES) : SimResult.unprofitable();
    }

    /** PR-29: the yield is GREATEST power — a bigger body makes it profitable. */
    @Override
    public String yieldPrereq() {
        return "board_power";
    }

    /** PR-16: a proven loop compresses to a pool injection instead of physical cycles. */
    public boolean shortcutEligible() {
        return shortcutEligible;
    }

    /** Color of the shortcut-injected pool (the engine's production color). */
    public String poolColor() {
        return poolColor;
    }

    @Override
    public String poolSourceCard() {
        return engine;
    }

    @Override
    public Step next(LineState state, SeatView view) {
        List<Step> steps = cycleSteps();
        int cycle = state.iteration() / steps.size();
        if (cycle >= bankCycles) {
            // banking fallback for shortcut-ineligible lines: floated mana is
            // handed back to stock AI in the same priority window
            return Step.done();
        }
        return steps.get(state.iteration() % steps.size());
    }
}
