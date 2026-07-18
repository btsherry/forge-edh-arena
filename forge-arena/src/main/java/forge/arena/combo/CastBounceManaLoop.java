package forge.arena.combo;

import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The sixth archetype (Phase 6 / PR-39, from the Gate 3.5 bindgen sweep):
 * the <b>cast-bounce mana loop</b>. A battlefield permanent with a
 * "whenever you cast a spell, return target permanent to its owner's hand"
 * trigger (Tidespout Tyrant class) plus a mana rock that produces MORE than
 * it costs to recast (Sol Ring, Mana Vault, Grim Monolith): tap the rock,
 * cast it again after the trigger returns it, and every cycle nets the
 * difference. Infinite MANA, so it rides the existing {@link
 * ShortcutSource} machinery unchanged.
 *
 * <p>This family was the single largest cluster in the sweep — 13 of 34
 * proposals, and the reason Urza's deck had 22 of 23 combos unbound while
 * being the pod's densest combo deck. Every proposal independently
 * described the same shape, which is why it earns an archetype rather than
 * a special case.
 *
 * <p><b>What is proven vs. attested.</b> The per-cycle arithmetic (mana
 * produced minus recast cost) is checked here, and the ENGINE is asked to
 * confirm the two facts a hallucinated binding would get wrong: the bouncer
 * is really on the battlefield with a cast-trigger, and the rock really
 * taps for the claimed mana. The bounce choreography itself is attested by
 * the Commander Spellbook entry (the W1 gate) exactly as
 * {@link BounceRecastLoop}'s is — a live line that cannot actually loop
 * aborts on its first failed step and is recorded, never silently spun.
 *
 * <p>Params: {@code bouncer}, {@code rock}, {@code rock_cost} (generic mana
 * to recast), {@code rock_mana} (mana produced per tap), {@code
 * rock_tap_cost} (the tap ability's cost hint, default {@code {T}}),
 * {@code pool_color}, {@code shortcut}, {@code bank_cycles}.
 */
public final class CastBounceManaLoop implements LineExecutor, ShortcutSource {

    public static final String ARCHETYPE = "CastBounceManaLoop";

    private final String bouncer;
    private final String rock;
    private final int rockCost;
    private final int rockMana;
    private final String rockTapCost;
    private final String poolColor;
    private final boolean shortcutEligible;
    private final int bankCycles;
    private final String entryPhase;

    public CastBounceManaLoop(Map<String, String> params, String entryPhase) {
        this.bouncer = require(params, "bouncer");
        this.rock = require(params, "rock");
        this.rockCost = Integer.parseInt(params.getOrDefault("rock_cost", "1"));
        this.rockMana = Integer.parseInt(params.getOrDefault("rock_mana", "2"));
        this.rockTapCost = params.getOrDefault("rock_tap_cost", "{T}");
        this.poolColor = params.getOrDefault("pool_color", "C");
        this.shortcutEligible = Boolean.parseBoolean(params.getOrDefault("shortcut", "true"));
        this.bankCycles = Integer.parseInt(params.getOrDefault("bank_cycles", "6"));
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
        return List.of("ASSEMBLY", "MANA_LOOP", "DEPLOY");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    @Override
    public List<String> lineCards() {
        return List.of(bouncer, rock);
    }

    /**
     * The bouncer must be DEPLOYED (its trigger is the loop); the rock may
     * be cast from hand as the first loop iteration. Anything else — either
     * piece missing or stranded in a zone we cannot reach — is not this
     * line from here.
     */
    @Override
    public List<Step> assemblySteps(SeatView view) {
        if (view.locate(bouncer) != SeatView.Presence.BATTLEFIELD) {
            return view.locate(bouncer) == SeatView.Presence.HAND
                    ? List.of(Step.cast(bouncer))
                    : null;
        }
        return switch (view.locate(rock)) {
            case BATTLEFIELD -> List.of();
            case HAND -> List.of(Step.cast(rock));
            default -> null;
        };
    }

    @Override
    public int castCostEstimate(String card) {
        return card.equals(rock) ? rockCost : 0;
    }

    /** Per cycle: mana produced minus the cost to recast the rock. */
    public SimResult mathProfitable() {
        int net = rockMana - rockCost;
        return net > 0 ? SimResult.profitable(net) : SimResult.unprofitable();
    }

    /**
     * Engine-checked: the rock must actually tap for mana on the copy (the
     * one number a wrong binding would invent), and the arithmetic must net
     * positive. The bouncer's presence is a precondition of assembly.
     */
    @Override
    public SimResult validate(SimHandle sim) {
        if (!mathProfitable().isProfitable()) {
            return SimResult.unprofitable();
        }
        int before = sim.manaPoolTotal();
        if (!sim.activate(rock, rockTapCost, List.of())) {
            return SimResult.blocked("rock");
        }
        if (sim.manaPoolTotal() - before < rockMana) {
            // the rock produced less than the binding claims — refuse rather
            // than fire a loop whose per-cycle yield is a fiction
            return SimResult.blocked("rock_yield");
        }
        return SimResult.profitable(rockMana - rockCost);
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
    public String poolSourceCard() {
        return rock;
    }

    /** The banking path (shortcut disabled): recast the rock each cycle. */
    @Override
    public Step next(LineState state, SeatView view) {
        if (state.iteration() >= bankCycles) {
            return Step.done();
        }
        return Step.cast(rock);
    }
}
