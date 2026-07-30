package forge.arena.engine;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.combo.ComboPilot;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * PR (selvala_mana_loop) — the FORKED variable-yield mana loop, broken out
 * from ManaLoopRunner so Selvala's family can grow without putting Urza's
 * fixed-net combos at risk (Ben, 2026-07-30). It is the runner for the shape
 * the stock ManaLoopRunner cannot model:
 *
 * <ul>
 *   <li><b>producer != untapper.</b> Selvala (the producer) taps for X; a
 *       SEPARATE card untaps her — Staff of Domination in two steps
 *       ({3}{T} untap Selvala, then {1} untap Staff), Umbral Mantle in one
 *       ({3}{Q} on Selvala herself, the granted pump). Urza's loops tap and
 *       untap ONE card; this one splits them.</li>
 *   <li><b>the producer's activation COSTS mana.</b> Selvala is {G},{T}: the
 *       per-cycle spend is {G} + the untap steps (Staff 5, Umbral 4), which
 *       is exactly the dossier's "net P-5 / P-4". Urza's Basalt/Grim tap for
 *       free ({T} only).</li>
 *   <li><b>the yield is VARIABLE.</b> X = greatest creature power (Selvala),
 *       enchantment count (Sanctum Weaver), creature count (Voyaging Satyr +
 *       Gaea's Cradle), or a flat constant (Fanatic of Rhonas). POWER_RAMPING
 *       (Umbral pumps +2/+2 each untap) OPENS NEGATIVE and diverges — the
 *       entry test proves monotonic divergence, not entry-net>=1.</li>
 * </ul>
 *
 * <p>The five invariants hold in this shape: preconditions vs LIVE state
 * (producer + untapper on board, attached, not summoning-sick); ONE ability
 * per priority window, yield until resolution; MEASURED per-cycle delta (the
 * producer came back untapped AND the pool moved by the model's expected net,
 * which may be negative while a ramping loop primes); costs/targets from the
 * program's structured facts; the live game performs. The sink is Ben's:
 * Genesis Wave force-cast at X = library - reserve, flipping the MAJORITY of
 * the library into play while leaving ~10 cards so the draw triggers on the
 * flooded board do not deck us out.
 */
public final class SelvalaManaLoopRunner {

    /** Runaway backstop far above any real bank (a 99-card deck needs ~90). */
    static final int ITERATION_CAP = 400;
    static final int SETTLE_GRACE_WINDOWS = 3;
    /** Genesis Wave's {X}{G}{G}{G} — the coloured tail on top of the X. */
    static final int GENESIS_WAVE_TAIL = 3;

    private enum State { SETUP, LOOP, SINK }

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String comboId;
    private final JsonNode program;

    private final String producerCard;
    private final String activateCost;
    private final String manaColor;
    private final String yieldModel;
    private final int rampPerCycle;
    private final int yieldConstant;
    private final int cycleCost;
    private final int minNet;
    private final List<JsonNode> untapSequence = new ArrayList<>();

    private final int libraryReserve;

    private State state = State.SETUP;
    private boolean finished;
    private boolean planned;
    private int iterations;
    private int target = -1;

    // cycle machine: phase 0 = tap producer; 1..N = untap step i
    private int cyclePhase;
    private int poolAtCycleStart = -1;
    private boolean pendingMeasure;
    private int settleWait;
    /** a one-shot untap pass to ready a producer stock tapped before entry. */
    private boolean normalizing;
    private int normalizeAttempts;
    /** greatest power at THIS cycle's tap — the X Selvala actually produced. */
    private int xAtCycleTap = -1;

    // sink
    private boolean pendingOutlet;
    private int permanentsAtOutlet = -1;
    private String outletCard;
    private int outletX;

    SelvalaManaLoopRunner(Game game, Player player, ComboPilot pilot, int seat, String programPath) {
        this.game = game;
        this.player = player;
        this.pilot = pilot;
        this.seat = seat;
        JsonNode p;
        try {
            p = new ObjectMapper().readTree(Path.of(programPath).toFile());
        } catch (Exception e) {
            p = null;
        }
        this.program = p;
        this.comboId = p != null ? p.path("combo_id").asText("?") : "?";
        JsonNode loop = p != null ? p.path("loop") : null;
        JsonNode producer = loop != null ? loop.path("producer") : null;
        this.producerCard = producer != null ? producer.path("card").asText(null) : null;
        this.activateCost = producer != null ? producer.path("activate_cost").asText("{G}") : "{G}";
        this.manaColor = producer != null ? producer.path("mana_color").asText("G") : "G";
        this.yieldModel = loop != null ? loop.path("yield_model").asText("POWER_CONSTANT") : "POWER_CONSTANT";
        this.rampPerCycle = loop != null ? loop.path("ramp_per_cycle").asInt(0) : 0;
        this.yieldConstant = loop != null ? loop.path("yield_constant").asInt(0) : 0;
        this.cycleCost = loop != null ? loop.path("cycle_cost").asInt(5) : 5;
        this.minNet = loop != null ? loop.path("min_net").asInt(1) : 1;
        if (loop != null) {
            for (JsonNode step : loop.path("untap_sequence")) {
                untapSequence.add(step);
            }
        }
        this.libraryReserve = p != null ? p.path("sink").path("library_reserve").asInt(10) : 10;
        if (producerCard == null || untapSequence.isEmpty()) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_abort", game.getPhaseHandler().getTurn(), seat)
                    .with("combo", comboId).with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    public boolean isPiece(String cardName) {
        if (cardName.equals(producerCard)) {
            return true;
        }
        for (JsonNode step : untapSequence) {
            if (cardName.equals(step.path("card").asText())) {
                return true;
            }
        }
        return false;
    }

    /** One ability per priority window. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!game.getStack().isEmpty()) {
            return null; // invariant 2 — resolve before the next act
        }

        if (state == State.SETUP) {
            List<SpellAbility> setup = runSetup(turn);
            if (setup != null || finished) {
                return setup;
            }
            state = State.LOOP;
            cyclePhase = 0;
        }

        if (state == State.LOOP) {
            return loop(turn);
        }

        return sink(turn);
    }

    // --- SETUP -----------------------------------------------------------

    /** Cast any setup pieces, verify preconditions, plan the bank. Returns a
     * SA to play (still setting up), or null to advance to LOOP; sets
     * {@code finished} on abort/defer. */
    private List<SpellAbility> runSetup(int turn) {
        for (JsonNode step : program.path("setup")) {
            String card = step.path("card").asText();
            if (AbilityResolver.findBattlefield(player, card) != null) {
                continue;
            }
            SpellAbility cast = AbilityResolver.resolveCast(player, card);
            if (cast == null) {
                // an unaffordable setup cast spent NOTHING — defer quietly
                finished = true;
                pilot.programDeferred(comboId);
                return null;
            }
            return List.of(cast);
        }
        // preconditions vs LIVE state
        for (JsonNode pre : program.path("preconditions")) {
            String check = pre.path("check").asText();
            String card = pre.path("card").asText();
            if ("on_battlefield".equals(check)
                    && AbilityResolver.findBattlefield(player, card) == null) {
                abortNow(turn, "piece_lost: '" + card + "'");
                return null;
            }
            if ("attached".equals(check) && !attached(card, pre.path("host").asText())) {
                abortNow(turn, "piece_misattached: '" + card + "' not on '"
                        + pre.path("host").asText() + "'");
                return null;
            }
            if ("not_summoning_sick".equals(check)) {
                Card c = AbilityResolver.findBattlefield(player, card);
                if (c != null && c.isSick()) {
                    // sickness is a WAIT, not a failure — it wears off next turn
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
            }
        }
        // entry decision + governor plan
        int x0 = computeYield();
        boolean ramping = "POWER_RAMPING".equals(yieldModel);
        int entryNet = x0 - cycleCost;
        if (!ramping && entryNet < minNet) {
            // the canonical zero-yield reject (Weaver+Umbral at E=3 nets 0)
            abortNow(turn, "zero_yield: " + yieldModel + " X=" + x0
                    + " - cycle_cost " + cycleCost + " = net " + entryNet
                    + " (< min_net " + minNet + ", not diverging)");
            return null;
        }
        if (ramping && rampPerCycle <= 0) {
            abortNow(turn, "non_diverging_ramp: ramp_per_cycle " + rampPerCycle);
            return null;
        }
        int library = player.getCardsIn(ZoneType.Library).size();
        // bank enough to force-cast Genesis Wave at X = library - reserve
        target = Math.max(cycleCost, (library - libraryReserve) + GENESIS_WAVE_TAIL);
        pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                .with("combo", comboId)
                .with("exit_state", ramping ? "power_ramps_diverges" : "pool_banked_then_outlet")
                .with("yield_model", yieldModel)
                .with("entry_yield", x0)
                .with("entry_net", entryNet)
                .with("need", target)
                .with("library", library)
                .with("reserve", libraryReserve)
                .with("tranche", 1)
                .with("iterations_done", 0));
        planned = true;
        xAtCycleTap = x0;
        return null;
    }

    // --- LOOP ------------------------------------------------------------

    private List<SpellAbility> loop(int turn) {
        int pool = player.getManaPool().totalMana();
        Card producer = AbilityResolver.findBattlefield(player, producerCard);
        if (producer == null) {
            return abort(turn, "piece_lost: '" + producerCard + "' mid-loop");
        }

        if (pendingMeasure) {
            // MEASURED cycle completion: the producer came back UNTAPPED and
            // the pool moved by at least the model's expected net for the X
            // Selvala produced THIS cycle. A ramping loop's early nets are
            // negative — the expected number carries the sign, so a genuine
            // stall (producer stuck tapped, untap countered) is still caught.
            int expectedNet = xAtCycleTap - cycleCost;
            if (!producer.isTapped() && pool >= poolAtCycleStart + expectedNet) {
                pendingMeasure = false;
                settleWait = 0;
                iterations++;
                xAtCycleTap = computeYield(); // ramps for the next cycle
                pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                        .with("outlet", producerCard).with("kind", "mana_pair")
                        .with("iteration", iterations)
                        .with("pool", pool)
                        .with("yield", xAtCycleTap)
                        .with("own_life", player.getLife()));
            } else if (settleWait < SETTLE_GRACE_WINDOWS) {
                settleWait++;
                return null;
            } else {
                return abort(turn, "cycle_incomplete: producer "
                        + (producer.isTapped() ? "TAPPED" : "untapped") + ", pool "
                        + poolAtCycleStart + "->" + pool + " (expected net " + expectedNet
                        + ") after cycle " + (iterations + 1));
            }
        }

        if (pool >= target) {
            state = State.SINK;
            return sink(turn);
        }
        if (iterations >= ITERATION_CAP) {
            return abort(turn, "iteration_cap: " + ITERATION_CAP);
        }

        if (cyclePhase == 0) {
            // phase 0 — tap the producer for X. If it comes in TAPPED (stock
            // AI taps mana sources like Cradle/Weaver/Fanatic before the combo
            // fires), run the untap sequence once as a NORMALIZATION pass (no
            // tap, no measure) to ready it, rather than aborting.
            if (producer.isTapped()) {
                if (normalizeAttempts >= 2) {
                    return abort(turn, "producer_stuck_tapped after "
                            + normalizeAttempts + " untap attempts");
                }
                normalizeAttempts++;
                normalizing = true;
                cyclePhase = 1;
                // fall through to the untap block below
            } else {
                normalizeAttempts = 0;
                poolAtCycleStart = pool;
                xAtCycleTap = computeYield();
                SpellAbility tap = AbilityResolver.resolve(
                        player, producerCard, activateCost, List.of());
                // the tap's own coloured cost ({G} for Selvala) must be
                // PAYABLE from the banked pool; resolve() finds the ability but
                // does not price it, so a silently-unpayable tap would fizzle
                if (tap == null || !forge.ai.ComputerUtilCost.canPayCost(tap, player, false)) {
                    pilot.observe(ArenaEvent.of("program_deferred", turn, seat)
                            .with("combo", comboId).with("iterations", iterations)
                            .with("pool", pool)
                            .with("green", player.getManaPool()
                                    .getAmountOfColor(forge.card.MagicColor.GREEN))
                            .with("resolvable", tap != null)
                            .with("reason", "producer_tap_unpayable"));
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
                // Selvala/Weaver produce "any combination of colors" — the
                // controller banks GREEN at RESOLUTION (chooseColor/
                // specifyManaCombo overrides) so the pool pays the producer's
                // own coloured activation and Genesis Wave's {G}{G}{G}; setting
                // it on the pre-play SA is lost when Forge clones onto the stack.
                cyclePhase = 1;
                return List.of(tap);
            }
        }

        // untap step — runs for cyclePhase >= 1, whether a normal cycle (after
        // the producer tap) or a normalization pass. Each step is on its OWN
        // card, targeting the producer where the ability targets (Staff's
        // {3}{T} untaps Selvala; Satyr's {T} untaps Gaea's Cradle).
        JsonNode step = untapSequence.get(cyclePhase - 1);
        String stepCard = step.path("card").asText();
        String cost = step.path("cost").asText();
        String tgt = step.path("target").asText(null);
        List<String> targets = tgt != null ? List.of(tgt) : List.of();
        SpellAbility act = AbilityResolver.resolve(player, stepCard, cost, targets);
        if (act == null) {
            return abort(turn, "untap_step_unresolvable: '" + stepCard + "' " + cost
                    + (tgt != null ? " -> " + tgt : ""));
        }
        if (cyclePhase >= untapSequence.size()) {
            // sequence done. A normalization pass just readied the producer —
            // no mana produced, no measure; a normal cycle now measures.
            cyclePhase = 0;
            if (normalizing) {
                normalizing = false;
            } else {
                pendingMeasure = true;
            }
        } else {
            cyclePhase++;
        }
        return List.of(act);
    }

    // --- SINK (Ben's outlet: Genesis Wave force-cast) --------------------

    private List<SpellAbility> sink(int turn) {
        if (pendingOutlet) {
            // MEASURED outlet: the board flipped (permanents jumped) and the
            // library dropped to about the reserve — Genesis Wave resolved as
            // designed. The game is won downstream by the flooded board.
            int permanentsNow = player.getCardsIn(ZoneType.Battlefield).size();
            int libraryNow = player.getCardsIn(ZoneType.Library).size();
            if (permanentsNow > permanentsAtOutlet) {
                finished = true;
                pilot.observe(ArenaEvent.of("outlet_fired", turn, seat)
                        .with("combo", comboId).with("outlet", outletCard)
                        .with("x", outletX)
                        .with("permanents_before", permanentsAtOutlet)
                        .with("permanents_after", permanentsNow)
                        .with("library_after", libraryNow));
                pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                        .with("combo", comboId).with("iterations", iterations)
                        .with("outlet", outletCard));
                return null;
            }
            if (settleWait < SETTLE_GRACE_WINDOWS) {
                settleWait++;
                return null;
            }
            return abort(turn, "outlet_no_flip: '" + outletCard + "' X=" + outletX
                    + " left the board at " + permanentsNow + " (was " + permanentsAtOutlet + ")");
        }

        SpellAbility outlet = chooseOutlet();
        if (outlet == null) {
            // banked but no outlet reachable — hand back rather than stall;
            // the pool is spent by stock's own windows the same phase
            pilot.observe(ArenaEvent.of("program_deferred", turn, seat)
                    .with("combo", comboId).with("reason", "no_outlet_castable"));
            finished = true;
            pilot.programDeferred(comboId);
            return null;
        }
        permanentsAtOutlet = player.getCardsIn(ZoneType.Battlefield).size();
        settleWait = 0;
        pendingOutlet = true;
        pilot.observe(ArenaEvent.of("outlet_cast", turn, seat)
                .with("combo", comboId).with("outlet", outletCard).with("x", outletX)
                .with("permanents_before", permanentsAtOutlet));
        return List.of(outlet);
    }

    /**
     * Ben's outlet, in preference order. Genesis Wave is the default: force-
     * cast at X = library - reserve so it flips the MAJORITY of the library
     * onto the battlefield and leaves ~reserve cards for the flood's draw
     * triggers. resolveCast never consults the AI's NeedsToPlayVar gate
     * (>=6 untapped LANDS) — Selvala's mana is creature-based, so building
     * the SA ourselves and pinning X IS the force-cast.
     */
    private SpellAbility chooseOutlet() {
        int library = player.getCardsIn(ZoneType.Library).size();
        // 1) Genesis Wave — flip the deck onto the board (leave the reserve)
        if (library > libraryReserve) {
            SpellAbility gw = AbilityResolver.resolveCast(player, "Genesis Wave");
            if (gw != null && gw.getPayCosts() != null
                    && gw.getPayCosts().hasXInAnyCostPart()) {
                int x = library - libraryReserve;
                gw.setXManaCostPaid(x);
                outletCard = "Genesis Wave";
                outletX = x;
                return gw;
            }
        }
        // 2) Finale of Devastation — fetch Craterhoof (trample) + pump, big X
        SpellAbility finale = AbilityResolver.resolveCast(player, "Finale of Devastation");
        if (finale != null && finale.getPayCosts() != null
                && finale.getPayCosts().hasXInAnyCostPart()) {
            int x = Math.max(10, player.getManaPool().totalMana() - GENESIS_WAVE_TAIL);
            finale.setXManaCostPaid(x);
            outletCard = "Finale of Devastation";
            outletX = x;
            return finale;
        }
        // 3) Craterhoof from hand — a one-shot team trample overrun
        SpellAbility hoof = AbilityResolver.resolveCast(player, "Craterhoof Behemoth");
        if (hoof != null) {
            outletCard = "Craterhoof Behemoth";
            outletX = 0;
            return hoof;
        }
        return null;
    }

    // --- yield models ----------------------------------------------------

    private int computeYield() {
        switch (yieldModel) {
            case "CONSTANT":
                return yieldConstant;
            case "ENCHANTMENT_COUNT":
                return count(Card::isEnchantment);
            case "CREATURE_COUNT":
                return count(Card::isCreature);
            case "POWER_CONSTANT":
            case "POWER_RAMPING":
            default:
                return greatestPower();
        }
    }

    private int greatestPower() {
        int max = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isCreature()) {
                max = Math.max(max, c.getNetPower());
            }
        }
        return max;
    }

    private int count(java.util.function.Predicate<Card> is) {
        int n = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (is.test(c)) {
                n++;
            }
        }
        return n;
    }

    // --- helpers ---------------------------------------------------------

    /** The colour this loop banks — the controller pins every "any/combo"
     * mana to it while the runner is active, so the pool pays the producer's
     * own coloured activation and the outlet's coloured tail. */
    public byte neededColor() {
        return forge.card.MagicColor.fromName(manaColor.charAt(0));
    }

    private boolean attached(String equipName, String hostName) {
        Card host = AbilityResolver.findBattlefield(player, hostName);
        if (host == null) {
            return false;
        }
        for (Card att : host.getAttachedCards()) {
            if (att.getName().equals(equipName)) {
                return true;
            }
        }
        return false;
    }

    private void abortNow(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                .with("combo", comboId).with("iterations", iterations)
                .with("reason", reason));
    }

    private List<SpellAbility> abort(int turn, String reason) {
        abortNow(turn, reason);
        return null;
    }
}
