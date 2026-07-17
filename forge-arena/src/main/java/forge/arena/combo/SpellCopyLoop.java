package forge.arena.combo;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import forge.arena.engine.SeatView;

/**
 * The third executor archetype (PR-27b, from the Purphoros bindgen
 * proposals): the Dualcaster family — a copy spell (Twinflame / Devastating
 * Onslaught) plus Dualcaster Mage sustains an ETB chain of hasty token
 * copies. Its product is TOKEN ENTRIES, not mana: under a damage engine
 * (Purphoros / Agate Instigator / Terror of the Peaks) every entry pings
 * the table, so the proven loop compresses to a bounded TOKEN FLOOD — the
 * controller puts N real copies of the copier onto the battlefield WITH
 * TRIGGERS ACTIVE and the rules engine prices every ping and amplifier
 * (Torbran, Solphim, Ojer Axonil) itself. No arena-side damage math, ever.
 *
 * <p>Fidelity note (documented deviation): the flood executes a
 * SPELLBOOK-ATTESTED loop. Validation engine-proves the CONSEQUENCE chain —
 * one injected entry on the game copy must actually reduce opponents' life —
 * and cost-gates the pieces; the copy-chain stack choreography itself
 * (cast → flash → copy → retarget) is trusted from the combo data, not
 * stepped. A stalled flood is caught by the Gate 3.6 watchdog like any
 * other line.
 *
 * <p>Params: {@code copy_spell}, {@code copier}, {@code damage_engines}
 * (comma-separated — at least one must be on the battlefield),
 * {@code copy_spell_mana_value} / {@code copier_mana_value} /
 * {@code engine_mana_value} (affordability), {@code flood_count}.
 */
public final class SpellCopyLoop implements LineExecutor {

    public static final String ARCHETYPE = "SpellCopyLoop";
    public static final int DEFAULT_FLOOD = 30;

    private final String copySpell;
    private final String copier;
    private final List<String> damageEngines;
    private final int copySpellManaValue;
    private final int copierManaValue;
    private final int engineManaValue;
    private final int floodCount;
    private final String entryPhase;

    public SpellCopyLoop(Map<String, String> params, String entryPhase) {
        this.copySpell = require(params, "copy_spell");
        this.copier = require(params, "copier");
        // semicolon-separated: card names carry commas ("Purphoros, God of the Forge")
        this.damageEngines = List.of(require(params, "damage_engines").split("\\s*;\\s*"));
        this.copySpellManaValue = Integer.parseInt(params.getOrDefault("copy_spell_mana_value", "0"));
        this.copierManaValue = Integer.parseInt(params.getOrDefault("copier_mana_value", "0"));
        this.engineManaValue = Integer.parseInt(params.getOrDefault("engine_mana_value", "0"));
        this.floodCount = Integer.parseInt(params.getOrDefault("flood_count",
                String.valueOf(DEFAULT_FLOOD)));
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
        return List.of("ASSEMBLY", "TOKEN_FLOOD");
    }

    @Override
    public String entryPhase() {
        return entryPhase;
    }

    public String copier() {
        return copier;
    }

    public int floodCount() {
        return floodCount;
    }

    /**
     * Executable when a damage engine is on the battlefield and both loop
     * pieces are in HAND (they are consumed by the loop, not deployed).
     * Assembly's only step is casting an engine that is reachable but not
     * yet down (Purphoros is the commander — usually castable).
     */
    @Override
    public List<Step> assemblySteps(SeatView view) {
        if (view.locate(copySpell) != SeatView.Presence.HAND
                || view.locate(copier) != SeatView.Presence.HAND) {
            return null;
        }
        for (String engine : damageEngines) {
            if (view.locate(engine) == SeatView.Presence.BATTLEFIELD) {
                return List.of();
            }
        }
        for (String engine : damageEngines) {
            SeatView.Presence where = view.locate(engine);
            if (where == SeatView.Presence.HAND || where == SeatView.Presence.COMMAND) {
                return List.of(Step.cast(engine));
            }
        }
        return null; // no engine reachable: entries would ping nothing
    }

    @Override
    public int castCostEstimate(String card) {
        if (card.equals(copySpell)) {
            return copySpellManaValue;
        }
        if (card.equals(copier)) {
            return copierManaValue;
        }
        if (damageEngines.contains(card)) {
            return engineManaValue;
        }
        return 0;
    }

    /**
     * Engine-real proof of the CONSEQUENCE chain: one injected copier entry
     * on the game copy must reduce opponents' summed life (the engine's
     * trigger fires and amplifiers price through the rules engine). The
     * pieces' castability is the affordability gate's job; the loop's own
     * stack choreography is Spellbook-attested (class doc).
     */
    @Override
    public SimResult validate(SimHandle sim) {
        int before = sim.opponentsLifeTotal();
        if (before <= 0) {
            return SimResult.blocked("no_opponents");
        }
        if (!sim.injectCopy(copier)) {
            return SimResult.blocked("copier");
        }
        int damagePerEntry = before - sim.opponentsLifeTotal();
        return damagePerEntry > 0 ? SimResult.profitable(1) : SimResult.unprofitable();
    }

    @Override
    public Step next(LineState state, SeatView view) {
        return Step.done(); // the flood is a compressed order, never stepped
    }
}
