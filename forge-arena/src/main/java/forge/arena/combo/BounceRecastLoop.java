package forge.arena.combo;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The second executor archetype (PR-27a, from the Gate 3.5 bindgen
 * proposals): tap a big-mana creature, BOUNCE it to hand with Temur
 * Sabertooth's activated ability, recast it, tap again — the Sabertooth
 * family (Selvala / Sanctum Weaver variants). Infinite MANA, so the proven
 * loop rides the exact PR-16/25 shortcut machinery via
 * {@link ShortcutSource}.
 *
 * <p>Two structural differences from {@link TapForManaUntapLoop}:
 *
 * <ul>
 *   <li>the recast tapper returns summoning-sick, so every variant carries a
 *       HASTE piece — {@code haste_mode} {@code static} (Concordant
 *       Crossroads' static, Surrak's ETB trigger: no per-cycle step) or
 *       {@code equip} (Lightning Greaves: an attach step each cycle);
 *   <li>Sabertooth's bounce is a RESOLUTION-TIME choice (Hidden ChangeZone),
 *       not a cast-time target — the cycle step carries a {@code choice}
 *       hint the controller answers when the engine asks. The copy's stock
 *       controller cannot be steered, so validation engine-measures the TAP
 *       YIELD (the only unknown) and cost-checks the fixed bounce/recast
 *       arithmetic; the live choice is watchdog-guarded like every step.
 * </ul>
 *
 * <p>Params: {@code tapper}, {@code tapper_cost} (activation hint),
 * {@code bouncer}, {@code bounce_cost}, {@code recast_mana_value} (the
 * tapper's hand-cast cost), {@code haste_piece}, {@code haste_mode}
 * (static|equip), {@code equip_cost}, {@code tapper_mana_value} /
 * {@code bouncer_mana_value} / {@code haste_mana_value} (affordability
 * estimates), {@code pool_color}, {@code shortcut}, {@code bank_cycles}.
 */
public final class BounceRecastLoop implements LineExecutor, ShortcutSource {

    public static final String ARCHETYPE = "BounceRecastLoop";

    private final String tapper;
    private final String tapperCost;
    private final String bouncer;
    private final String bounceCost;
    private final int recastManaValue;
    private final String hastePiece;
    private final boolean equipMode;
    private final String equipCost;
    private final int tapperManaValue;
    private final int bouncerManaValue;
    private final int hasteManaValue;
    private final String poolColor;
    private final boolean shortcutEligible;
    private final int bankCycles;
    private final String entryPhase;
    private final String yieldPrereq;

    public BounceRecastLoop(Map<String, String> params, String entryPhase) {
        this.tapper = require(params, "tapper");
        this.tapperCost = require(params, "tapper_cost");
        this.bouncer = require(params, "bouncer");
        this.bounceCost = require(params, "bounce_cost");
        this.recastManaValue = Integer.parseInt(require(params, "recast_mana_value"));
        this.hastePiece = require(params, "haste_piece");
        this.equipMode = "equip".equals(params.getOrDefault("haste_mode", "static"));
        this.equipCost = params.getOrDefault("equip_cost", "{0}");
        this.tapperManaValue = Integer.parseInt(params.getOrDefault("tapper_mana_value", "0"));
        this.bouncerManaValue = Integer.parseInt(params.getOrDefault("bouncer_mana_value", "0"));
        this.hasteManaValue = Integer.parseInt(params.getOrDefault("haste_mana_value", "0"));
        this.poolColor = params.getOrDefault("pool_color", "G");
        this.shortcutEligible = Boolean.parseBoolean(params.getOrDefault("shortcut", "true"));
        this.bankCycles = Integer.parseInt(params.getOrDefault("bank_cycles", "6"));
        this.entryPhase = entryPhase != null ? entryPhase : "MAIN1";
        String prereq = params.getOrDefault("yield_prereq", "board_power");
        this.yieldPrereq = "none".equals(prereq) ? null : prereq;
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
        return List.of("ASSEMBLY", "MANA_LOOP", "DEPLOY");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    @Override
    public List<Step> assemblySteps(SeatView view) {
        List<Step> steps = new ArrayList<>();
        for (String piece : List.of(tapper, bouncer, hastePiece)) {
            switch (view.locate(piece)) {
                case BATTLEFIELD -> {
                }
                case HAND, COMMAND -> steps.add(Step.cast(piece));
                default -> {
                    return null; // graveyard/absent: not assemblable from here
                }
            }
        }
        if (steps.isEmpty() && equipMode
                && !tapper.equals(view.ownAttachments().get(hastePiece))) {
            steps.add(Step.activateTargeting(hastePiece, equipCost, tapper));
        }
        return steps;
    }

    /** One loop cycle: tap big, bounce the tapper, recast it (, re-equip). */
    public List<Step> cycleSteps() {
        List<Step> steps = new ArrayList<>();
        steps.add(Step.activate(tapper, tapperCost));
        steps.add(Step.activateChoosing(bouncer, bounceCost, tapper));
        steps.add(Step.cast(tapper));
        if (equipMode) {
            steps.add(Step.activateTargeting(hastePiece, equipCost, tapper));
        }
        return steps;
    }

    /** Full cycle cost: activation + bounce + recast (+ equip). */
    int cycleCost() {
        return TapForManaUntapLoop.cmc(tapperCost) + TapForManaUntapLoop.cmc(bounceCost)
                + recastManaValue + (equipMode ? TapForManaUntapLoop.cmc(equipCost) : 0);
    }

    /** The plan §8 arithmetic: net per cycle = engine-measured yield − fixed costs. */
    public SimResult mathProfitable(int tapYield, int floatedMana) {
        int net = tapYield - cycleCost();
        if (floatedMana + net < 0) {
            return SimResult.blocked("mana");
        }
        return net > 0 ? SimResult.profitable(1) : SimResult.unprofitable();
    }

    @Override
    public int castCostEstimate(String card) {
        if (card.equals(tapper)) {
            return tapperManaValue;
        }
        if (card.equals(bouncer)) {
            return bouncerManaValue;
        }
        if (card.equals(hastePiece)) {
            return hasteManaValue;
        }
        return 0;
    }

    /**
     * The tap yield is the ONE unknown — engine-measured on the copy (real
     * activation, real pool). The bounce and recast are fixed costs the
     * arithmetic prices; their resolution-time choice cannot be steered on
     * the copy's stock controller (live steering is the Step choice hint,
     * watchdog-guarded like every scripted step).
     */
    @Override
    public SimResult validate(SimHandle sim) {
        int before = sim.manaPoolTotal();
        if (!sim.activate(tapper, tapperCost, List.of())) {
            return SimResult.blocked("tapper");
        }
        int tapYield = sim.manaPoolTotal() - before;
        int net = tapYield - cycleCost();
        return net > 0 ? SimResult.profitable(1) : SimResult.unprofitable();
    }

    /**
     * PR-29: Selvala variants yield GREATEST power (a bigger body pays the
     * loop); the Weaver variant yields enchantment count — its binding sets
     * {@code yield_prereq: none} until an enchantment-deploy vocabulary
     * exists.
     */
    @Override
    public String yieldPrereq() {
        return yieldPrereq;
    }

    @Override
    public boolean shortcutEligible() {
        return shortcutEligible;
    }

    @Override
    public String poolColor() {
        return poolColor;
    }

    @Override
    public Step next(LineState state, SeatView view) {
        List<Step> steps = cycleSteps();
        int cycle = state.iteration() / steps.size();
        if (cycle >= bankCycles) {
            return Step.done();
        }
        return steps.get(state.iteration() % steps.size());
    }
}
