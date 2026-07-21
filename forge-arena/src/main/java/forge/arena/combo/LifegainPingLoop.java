package forge.arena.combo;

import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The seventh archetype (PR-47): the <b>lifegain ping loop</b> — a
 * repeatable damage sink whose activation cost is refunded by a
 * lifegain trigger. Walking Ballista removes a +1/+1 counter to deal 1
 * damage; Heliod (or Archangel of Thune) sees the life gained and puts the
 * counter back; repeat until the table is dead.
 *
 * <p>This archetype is different in kind from the six before it, and that
 * difference is the point: its product is neither mana nor tokens, so there
 * is nothing to compress into a bounded pool. What it produces is
 * <b>permission to keep activating</b> — which is precisely the PR-37
 * loop-to-lethal drill. So a proven line here ARMS THE DRILL and the
 * existing executor does the killing, one activation per priority window,
 * re-targeting the lowest-life opponent and re-deriving the alive set as
 * players are eliminated.
 *
 * <p>Why it matters beyond one deck: the white deck reached "combo ready"
 * 22 times in a 183-game batch and ATTEMPTED ZERO of them, because both of
 * its combos were unbound. It won 44 games on stock aggression alone with
 * its actual engine sitting unused.
 *
 * <p>What is proven vs. attested: the engine is asked for the one fact a
 * wrong binding would invent — that activating the pinger at an opponent
 * really does reduce a life total. The counter-refund half is attested by
 * the Commander Spellbook entry (the W1 gate), exactly as
 * {@link BounceRecastLoop}'s bounce choreography is; a loop that cannot
 * actually sustain itself simply stops resolving and the drill disarms
 * honestly on its next pass.
 *
 * <p>Params: {@code pinger}, {@code lifegain_engine},
 * {@code pinger_mana_value}, {@code engine_mana_value}.
 */
public final class LifegainPingLoop implements LineExecutor {

    public static final String ARCHETYPE = "LifegainPingLoop";

    private final String pinger;
    private final String lifegainEngine;
    private final String lifelinkSource;
    private final String lifelinkCost;
    private final int pingerManaValue;
    private final int engineManaValue;
    private final String entryPhase;

    public LifegainPingLoop(Map<String, String> params, String entryPhase) {
        this.pinger = require(params, "pinger");
        this.lifegainEngine = require(params, "lifegain_engine");
        // PR-70: the loop is not a loop without LIFELINK on the pinger.
        // Ballista's ping deals damage; only lifelink turns that damage into
        // life; only the life gain triggers the engine to hand the counter
        // back. Optional param because a pinger that already HAS lifelink
        // needs no grant — but when it is needed and absent, the "loop"
        // silently degrades into a pinger burning through its own counters.
        this.lifelinkSource = params.get("lifelink_source");
        this.lifelinkCost = params.getOrDefault("lifelink_cost", "{1}{W}");
        this.pingerManaValue = Integer.parseInt(params.getOrDefault("pinger_mana_value", "2"));
        this.engineManaValue = Integer.parseInt(params.getOrDefault("engine_mana_value", "3"));
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
        return List.of("ASSEMBLY", "DRILL");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    @Override
    public List<String> lineCards() {
        return List.of(pinger, lifegainEngine);
    }

    /** The card the drill activates once the line is proven. */
    public String pinger() {
        return pinger;
    }

    /**
     * Both halves must be DEPLOYED — the pinger to activate and the engine
     * to refund it. Either one castable from hand is an assembly step;
     * anything else is not this line from here.
     */
    @Override
    public List<Step> assemblySteps(SeatView view) {
        List<String> required = lifelinkSource == null
                ? List.of(lifegainEngine, pinger)
                : List.of(lifegainEngine, pinger, lifelinkSource);
        for (String piece : required) {
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

    @Override
    public int castCostEstimate(String card) {
        if (card.equals(pinger)) {
            return pingerManaValue;
        }
        return card.equals(lifegainEngine) ? engineManaValue : 0;
    }

    /**
     * One activation at an opponent must actually drop a life total. That
     * is the fact a hallucinated binding gets wrong, and it is the same
     * proof the conversion module requires before arming a drill.
     */
    @Override
    public SimResult validate(SimHandle sim) {
        // PR-70: grant lifelink BEFORE proving the ping. Without it the ping
        // gains no life, the engine never triggers, and the counter never
        // comes back — the loop is a one-shot that eats itself. Spellbook's
        // own prerequisite for both of this deck's combos is explicit:
        // "You have a way to give Walking Ballista lifelink."
        if (lifelinkSource != null
                && !sim.activate(lifelinkSource, lifelinkCost, List.of(pinger))) {
            return SimResult.blocked("lifelink_grant");
        }
        return sim.activateAtOpponent(pinger, null)
                ? SimResult.profitable(1)
                : SimResult.blocked("pinger");
    }

    /** The lifelink grant the drill needs standing before it starts. */
    public String lifelinkSource() {
        return lifelinkSource;
    }

    /**
     * PR-70: grant lifelink, THEN hand off to the drill. Lifelink lasts until
     * end of turn, so one grant covers every drill iteration this turn — but
     * without it the drill's first ping breaks the loop it was armed to run.
     */
    @Override
    public Step next(LineState state, SeatView view) {
        if (lifelinkSource != null && state.iteration() == 0) {
            return Step.activateTargeting(lifelinkSource, lifelinkCost, pinger);
        }
        return Step.done();
    }
}
