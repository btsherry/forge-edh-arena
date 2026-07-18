package forge.arena.combo;

import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The fifth archetype (PR-32, the Urza primer's core line): Isochron
 * Scepter with Dramatic Reversal imprinted — activate {2}, the copy untaps
 * every nonland (the Scepter AND the mana rocks), repeat; with 3+ mana of
 * rock production each cycle nets positive. One activation per cycle, the
 * untap built into the copied spell.
 *
 * <p>Assembly: cast the scepter FROM HAND with the imprint target named as
 * a resolution choice ({@code Step.castChoosing} — the exile-from-hand
 * choice rides the PR-27a pendingChoice seam); an already-imprinted scepter
 * shows as scepter on the battlefield + imprint in EXILE. Validation is the
 * Mantle pattern: one engine activation on the copy must succeed AND leave
 * the scepter UNTAPPED (the copy-chain proof); yield is cost-gated by the
 * affordability estimates, not simulated.
 *
 * <p>Params: {@code scepter}, {@code imprint}, {@code activation_cost},
 * {@code scepter_mana_value}, {@code imprint_mana_value},
 * {@code pool_color}, {@code shortcut}, {@code bank_cycles}.
 */
public final class ImprintCopyLoop implements LineExecutor, ShortcutSource {

    public static final String ARCHETYPE = "ImprintCopyLoop";

    private final String scepter;
    private final String imprint;
    private final String activationCost;
    private final int scepterManaValue;
    private final int imprintManaValue;
    private final String poolColor;
    private final boolean shortcutEligible;
    private final int bankCycles;
    private final String entryPhase;

    public ImprintCopyLoop(Map<String, String> params, String entryPhase) {
        this.scepter = require(params, "scepter");
        this.imprint = require(params, "imprint");
        this.activationCost = params.getOrDefault("activation_cost", "{2}");
        this.scepterManaValue = Integer.parseInt(params.getOrDefault("scepter_mana_value", "2"));
        this.imprintManaValue = Integer.parseInt(params.getOrDefault("imprint_mana_value", "2"));
        this.poolColor = params.getOrDefault("pool_color", "U");
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
    public List<Step> assemblySteps(SeatView view) {
        SeatView.Presence scepterAt = view.locate(scepter);
        SeatView.Presence imprintAt = view.locate(imprint);
        if (scepterAt == SeatView.Presence.BATTLEFIELD) {
            // imprinted = the copy target sits in exile; anywhere else means
            // an empty scepter we cannot re-imprint — not this line
            return imprintAt == SeatView.Presence.EXILE ? List.of() : null;
        }
        if (scepterAt == SeatView.Presence.HAND && imprintAt == SeatView.Presence.HAND) {
            return List.of(Step.castChoosing(scepter, imprint));
        }
        return null;
    }

    @Override
    public int castCostEstimate(String card) {
        if (card.equals(scepter)) {
            return scepterManaValue;
        }
        if (card.equals(imprint)) {
            return imprintManaValue;
        }
        return 0;
    }

    /** One engine activation must succeed AND leave the scepter untapped. */
    @Override
    public SimResult validate(SimHandle sim) {
        if (!sim.activate(scepter, activationCost, List.of())) {
            return SimResult.blocked("scepter");
        }
        return sim.untapped(scepter) ? SimResult.profitable(1)
                : SimResult.blocked("scepter_not_untapped");
    }

    @Override
    public String yieldPrereq() {
        return null; // yield comes from rocks, not board power
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
        if (state.iteration() >= bankCycles) {
            return Step.done();
        }
        return Step.activate(scepter, activationCost);
    }
}
