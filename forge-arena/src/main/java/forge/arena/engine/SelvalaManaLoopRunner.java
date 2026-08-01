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
    // GOD WIN-PLAN (Rhonas/Nylea flood-pump) bounds.
    static final int GOD_DIG_CAP = 80;
    static final int GOD_PUMP_CAP = 400;
    static final int GOD_HAND_CREATURE_TARGET = 14;

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
    /** untap-fixpoint windows spent readying a board stock pre-tapped. */
    private int normalizeAttempts;
    /** greatest power at THIS cycle's tap — the X Selvala actually produced. */
    private int xAtCycleTap = -1;

    // sink
    private boolean pendingOutlet;
    private int permanentsAtOutlet = -1;
    private String outletCard;
    private int outletX;
    /** GOD WIN-PLAN phase: -1 idle, 0 dig (Nylea), 1 cast, 2 pump (Rhonas), 3 done. */
    private int winPlanPhase = -1;
    private int winPlanDigs;
    private int winPlanPumps;

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
        String mc = producer != null ? producer.path("mana_color").asText("G") : "G";
        this.manaColor = mc.isEmpty() ? "G" : mc; // asText returns "" for a present-but-empty field
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
        // default 35, not 10: the Genesis Wave flip forces ~one draw per
        // nontoken creature via The Great Henge (mandatory), so a small reserve
        // decks us out mid-win (measured). Programs may still override.
        this.libraryReserve = p != null ? p.path("sink").path("library_reserve").asInt(35) : 35;
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
        boolean powerScaling = yieldModel.startsWith("POWER");
        int entryNet = x0 - cycleCost;
        if (!ramping && entryNet < minNet) {
            // PR-xi (loop-dispatch timing): a POWER_CONSTANT loop's yield IS the
            // greatest creature power, so a low yield is a WAIT, not a failure —
            // the board can still grow a bigger creature. The batch showed the
            // loop dispatching at power 2-4 and aborting while Kogla (6/6) sat on
            // the board 7x/30; it never re-fired at the higher power. DEFER so it
            // re-dispatches once power clears the untap cost. Non-power counts
            // (enchantment/creature count) keep the canonical zero-yield reject —
            // a single big creature does not lift them (gate 1355-2816).
            if (powerScaling) {
                pilot.observe(ArenaEvent.of("program_deferred", turn, seat)
                        .with("combo", comboId).with("entry_yield", x0)
                        .with("entry_net", entryNet).with("cycle_cost", cycleCost)
                        .with("reason", "low_power"));
                finished = true;
                pilot.programDeferred(comboId);
                return null;
            }
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
        // PR-mu (bootstrap gate): POWER_RAMPING opens net-NEGATIVE and relies on
        // the board's power ramping the yield positive over cycles. The priming
        // cycles run at a loss, funded from EXTERNAL mana (lands/rocks other than
        // the producer). With too small a board (low producer power) AND too
        // little external mana to cover even the first cycle's shortfall, the
        // loop CANNOT bootstrap: it taps the producer, cannot pay the untap, and
        // aborts cycle_incomplete — burning the turn (the 30-game batch showed
        // 527-2816 doing exactly this ~6x). DEFER instead: wait for a bigger
        // board or more mana, so the pilot plays its real game this turn. The
        // GATE-2 fixture funds the priming with 8 Forests, far above the
        // deficit, so this never fires there. Only guards the net-negative
        // opening; a net>=0 loop (POWER_CONSTANT, or ramping already positive)
        // is untouched.
        if (ramping && entryNet <= 0) {
            // net 0 still can't prime: the producer's own {G} activation must be
            // paid from EXTERNAL mana before it yields anything (deficit >= 1).
            int deficit = Math.max(1, -entryNet);           // first-cycle shortfall
            Card producer = AbilityResolver.findBattlefield(player, producerCard);
            int have = player.getManaPool().totalMana() + externalUntappedSources(producer);
            if (have < deficit) {
                pilot.observe(ArenaEvent.of("program_deferred", turn, seat)
                        .with("combo", comboId)
                        .with("entry_yield", x0).with("entry_net", entryNet)
                        .with("external_mana", have).with("deficit", deficit)
                        .with("reason", "bootstrap_unfunded"));
                finished = true;
                pilot.programDeferred(comboId);
                return null;
            }
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

    // --- NORMALIZATION (untap fixpoint) ----------------------------------

    /** The state a normal cycle expects at phase 0: the producer AND every
     * distinct untapper card untapped. Stock AI taps mana sources — and often
     * the untappers — before the combo fires; until every piece is untapped the
     * first untap step (which needs its own card untapped to pay {T}) can't run. */
    private boolean loopReady(Card producer) {
        if (producer.isTapped()) {
            return false;
        }
        for (JsonNode step : untapSequence) {
            Card c = AbilityResolver.findBattlefield(player, step.path("card").asText());
            if (c != null && c.isTapped()) {
                return false;
            }
        }
        return true;
    }

    /** The first untap step that is currently PAYABLE and would untap a piece
     * that is presently tapped — the next useful move toward {@link #loopReady}.
     * Returns null when no affordable step advances readiness (out of external
     * mana for the untap costs, or a piece is otherwise stuck). Untapping one
     * piece can re-tap another (Satyr taps to untap Cradle); the phase-0 caller
     * re-invokes this each window until the whole chain settles. */
    private SpellAbility firstReadyingUntap() {
        for (JsonNode step : untapSequence) {
            String tgt = step.path("target").asText(null);
            // the card this step untaps: its target, or itself for a self-untap
            Card untapped = AbilityResolver.findBattlefield(player,
                    tgt != null ? tgt : step.path("card").asText());
            if (untapped == null || !untapped.isTapped()) {
                continue; // that piece is already untapped — no gain
            }
            SpellAbility act = AbilityResolver.resolve(player, step.path("card").asText(),
                    step.path("cost").asText(), tgt != null ? List.of(tgt) : List.of());
            if (act != null && forge.ai.ComputerUtilCost.canPayCost(act, player, false)) {
                return act;
            }
        }
        return null;
    }

    /** Untapped mana sources OTHER than the producer — the external mana that
     * funds a POWER_RAMPING loop's net-negative priming cycles. Mirrors
     * {@code SeatViews}: untapped, has a mana ability, not a restricted source
     * (Workshop-class), not a summoning-sick creature. Counts one per source (a
     * conservative lower bound; sources that make >1 only make bootstrapping
     * more likely, never less). */
    private int externalUntappedSources(Card producer) {
        int n = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c == producer || c.isTapped() || c.getManaAbilities().isEmpty()
                    || (c.isCreature() && c.hasSickness())) {
                continue;
            }
            boolean restricted = false;
            for (SpellAbility ma : c.getManaAbilities()) {
                if (ma.hasParam("RestrictValid")) {
                    restricted = true;
                    break;
                }
            }
            if (!restricted) {
                n++;
            }
        }
        return n;
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
            // produced THIS cycle (ramping nets carry a NEGATIVE sign during
            // priming). NO settle grace: next()'s stack gate already absorbed
            // every in-flight resolution, so a failed first measure is final
            // (the parent ManaLoopRunner aborts on first failure too; a null
            // return here on an empty stack would only pass priority, end the
            // phase, and empty the very pool we are measuring). The
            // tap-actually-happened check in the untap block catches the
            // negative-net NO-OP that this pool test alone would pass.
            int expectedNet = xAtCycleTap - cycleCost;
            if (producer.isTapped() || pool < poolAtCycleStart + expectedNet) {
                return abort(turn, "cycle_incomplete: producer "
                        + (producer.isTapped() ? "TAPPED" : "untapped") + ", pool "
                        + poolAtCycleStart + "->" + pool + " (expected net " + expectedNet
                        + ") after cycle " + (iterations + 1));
            }
            pendingMeasure = false;
            iterations++;
            xAtCycleTap = computeYield();
            pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                    .with("outlet", producerCard).with("kind", "mana_pair")
                    .with("iteration", iterations)
                    .with("pool", pool)
                    .with("yield", xAtCycleTap)
                    .with("own_life", player.getLife()));
        }

        if (pool >= target) {
            state = State.SINK;
            return sink(turn);
        }
        if (iterations >= ITERATION_CAP) {
            return abort(turn, "iteration_cap: " + ITERATION_CAP);
        }

        if (cyclePhase == 0) {
            // phase 0 — the board must be READY (the producer AND every distinct
            // untapper untapped) before a normal cycle: the first untap step
            // (Staff {3}{T} -> producer) needs its own card untapped to fire.
            // Stock AI taps the producer (Cradle/Weaver/Fanatic) and often the
            // untappers too before the combo fires, so run an UNTAP FIXPOINT:
            // fire one payable untap that readies a still-tapped piece per
            // window until ready. A CHAIN (Satyr->Cradle, Staff->Satyr,
            // Staff->self) needs several passes because untapping one piece taps
            // the next; the loop converges. These untap costs are paid from
            // OTHER mana (lands) — the producer is tapped, so the pool is empty
            // until the first normal tap.
            if (!loopReady(producer)) {
                if (normalizeAttempts >= untapSequence.size() * 2 + 3) {
                    return abort(turn, "producer_stuck_tapped: board not ready after "
                            + normalizeAttempts + " untap attempts (producer "
                            + (producer.isTapped() ? "TAPPED" : "untapped") + ")");
                }
                SpellAbility untap = firstReadyingUntap();
                if (untap == null) {
                    // no affordable untap advances readiness — out of external
                    // mana for the {3}/{1} untap costs, or a piece is otherwise
                    // stuck; hand back rather than spin
                    return abort(turn, "normalize_no_payable_untap: no affordable "
                            + "untap readies the loop (external mana for the untap "
                            + "costs exhausted?)");
                }
                normalizeAttempts++;
                return List.of(untap);
            }
            normalizeAttempts = 0;
            poolAtCycleStart = pool;
            xAtCycleTap = computeYield();
            SpellAbility tap = AbilityResolver.resolve(
                    player, producerCard, activateCost, List.of());
            // the tap's own coloured cost ({G} for Selvala) must be PAYABLE from
            // the banked pool; resolve() finds the ability but does not price it,
            // so a silently-unpayable tap would fizzle
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
            // Selvala/Weaver produce "any combination of colors" — the controller
            // banks GREEN at RESOLUTION (chooseColor/specifyManaCombo overrides)
            // so the pool pays the producer's own coloured activation and Genesis
            // Wave's {G}{G}{G}; setting it on the pre-play SA is lost when Forge
            // clones onto the stack.
            cyclePhase = 1;
            return List.of(tap);
        }

        // untap step — runs for cyclePhase >= 1, whether a normal cycle (after
        // the producer tap) or a normalization pass. Each step is on its OWN
        // card, targeting the producer where the ability targets (Staff's
        // {3}{T} untaps Selvala; Satyr's {T} untaps Gaea's Cradle).
        //
        // At the FIRST untap step of a normal cycle the producer MUST be tapped
        // — the phase-0 tap should have tapped it. If it is not, the tap
        // fizzled (canPayCost prices the cost, not activation restrictions like
        // Cursed Totem), no mana was produced, and continuing would false-
        // complete the cycle on a negative-net measure. Not checked at later
        // Staff steps (the producer is already untapped by then). Normalization
        // no longer runs through this block — the fixpoint above readies the
        // board before any phase-0 tap.
        if (cyclePhase == 1 && !producer.isTapped()) {
            return abort(turn, "producer_tap_failed: '" + producerCard
                    + "' not tapped after its activation (blocked?)");
        }
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
            // sequence done — the producer is untapped and the pool moved; a
            // normal cycle now measures the per-cycle net.
            cyclePhase = 0;
            pendingMeasure = true;
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

        // GOD WIN-PLAN (Rhonas/Nylea flood-pump) — a same-turn kill that needs NO
        // Genesis Wave: Nylea digs the deck's creatures into hand, we cast them
        // (hasty via Concordant Crossroads, {1} cheaper via Nylea), then Rhonas
        // pumps the board +2/+0 and grants trample until it alpha-strikes lethal.
        // Both Gods are indestructible, so the plan is hard to disrupt. Preferred
        // over the flip when Rhonas is online (it wins THIS turn, no sick board).
        if (winPlanPhase >= 0) {
            return godWinPlan(turn); // already committed to the plan
        }
        if (godWinPlanViable()) {
            winPlanPhase = 0;
            return godWinPlan(turn);
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

    // --- GOD WIN-PLAN (Rhonas/Nylea flood-pump) -------------------------
    // A two-card "pairing" (powerful play, not a combo): with infinite mana,
    // Nylea, Keen-Eyed digs the deck's creatures into hand, we cast them (hasty
    // via Concordant Crossroads, {1} cheaper via Nylea), and Rhonas the
    // Indomitable pumps the board +2/+0 with trample until it alpha-strikes
    // lethal. Both Gods are indestructible. No Genesis Wave required.

    /** Worth running when Rhonas (the pump engine) is on the battlefield and we
     *  can field at least one attacker per opponent — either creatures that can
     *  already attack, or Nylea to dig a whole board out of the library. */
    private boolean godWinPlanViable() {
        boolean rhonas = AbilityResolver.findBattlefield(player, "Rhonas the Indomitable") != null;
        boolean nylea = AbilityResolver.findBattlefield(player, "Nylea, Keen-Eyed") != null;
        if (!rhonas && !nylea) {
            return false;
        }
        // EITHER God alone can close the game: Nylea digs a whole board out of the
        // library and swings wide (hasty via Crossroads); Rhonas pumps a board
        // that is already present into a trampling lethal. So Nylea is viable on
        // its own; Rhonas is viable when we already have attackers to pump.
        return nylea || nonSickAttackers().size() >= Math.max(1, liveOpponentCount());
    }

    /** One action per window across the plan's phases; sets finished when the
     *  board is lethal and hands to combat (the pilot's lethalAlphaOrder swings). */
    private List<SpellAbility> godWinPlan(int turn) {
        // PHASE 0 — DIG: Nylea banks creatures from the top of the library into
        // hand, widening the eventual attack. Stop at a target hand or thin deck.
        if (winPlanPhase == 0) {
            if (AbilityResolver.findBattlefield(player, "Nylea, Keen-Eyed") != null
                    && countIn(ZoneType.Library, Card::isCreature) > 0
                    && winPlanDigs < GOD_DIG_CAP
                    && countIn(ZoneType.Hand, Card::isCreature) < GOD_HAND_CREATURE_TARGET) {
                SpellAbility dig = AbilityResolver.resolve(
                        player, "Nylea, Keen-Eyed", "{2}{G}", List.of());
                if (dig != null && forge.ai.ComputerUtilCost.canPayCost(dig, player, false)) {
                    winPlanDigs++;
                    return List.of(dig);
                }
            }
            winPlanPhase = 1;
        }
        // PHASE 1 — CAST: put the creatures onto the battlefield (hasty via
        // Concordant Crossroads). One per window; when none is castable, pump.
        if (winPlanPhase == 1) {
            SpellAbility cast = castCreatureFromHand();
            if (cast != null) {
                return List.of(cast);
            }
            winPlanPhase = 2;
        }
        // PHASE 2 — PUMP (Rhonas only): +2/+0 and trample, distributed across the
        // attackers (lowest power first) until the board can alpha-strike lethal.
        // Skipped entirely with a Nylea-only board — there the wide hasty swing is
        // the kill, no pump required.
        if (winPlanPhase == 2) {
            Card rhonas = AbilityResolver.findBattlefield(player, "Rhonas the Indomitable");
            if (rhonas != null && !boardTrampleLethal(nonSickAttackers())
                    && winPlanPumps < GOD_PUMP_CAP) {
                Card target = pumpTarget(nonSickAttackersOrAll(), rhonas);
                if (target != null) {
                    SpellAbility pump = AbilityResolver.resolve(player,
                            "Rhonas the Indomitable", "{2}{G}", List.of(target.getName()));
                    if (pump != null && forge.ai.ComputerUtilCost.canPayCost(pump, player, false)) {
                        winPlanPumps++;
                        return List.of(pump);
                    }
                }
            }
            winPlanPhase = 3;
        }
        // PHASE 3 — DONE: the board is as lethal as we can make it; hand to combat.
        finished = true;
        List<Card> attackers = nonSickAttackers();
        // label by whichever God actually closed — Rhonas if we pumped, else Nylea
        String godOutlet = winPlanPumps > 0 ? "Rhonas the Indomitable"
                : winPlanDigs > 0 ? "Nylea, Keen-Eyed" : "God win-plan";
        pilot.observe(ArenaEvent.of("outlet_fired", turn, seat)
                .with("combo", comboId).with("outlet", godOutlet)
                .with("x", winPlanPumps).with("digs", winPlanDigs)
                .with("attackers", attackers.size())
                .with("board_power", totalPower(attackers)));
        pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                .with("combo", comboId).with("iterations", iterations)
                .with("outlet", godOutlet));
        return null;
    }

    private int countIn(ZoneType zone, java.util.function.Predicate<Card> pred) {
        int n = 0;
        for (Card c : player.getCardsIn(zone)) {
            if (pred.test(c)) {
                n++;
            }
        }
        return n;
    }

    /** Creatures we control that can ATTACK this turn — CombatUtil.canAttack is
     *  haste-aware (Concordant Crossroads) and honours Rhonas's "not alone"
     *  restriction, unlike Card.isSick which ignores haste. */
    private List<Card> nonSickAttackers() {
        List<Card> out = new ArrayList<>();
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isCreature() && forge.game.combat.CombatUtil.canAttack(c)) {
                out.add(c);
            }
        }
        return out;
    }

    /** Pump candidates: creatures that are not summoning sick (or are hasted) —
     *  broader than {@link #nonSickAttackers} because Rhonas can't attack until
     *  another creature reaches power 4, so we must be allowed to pump one that
     *  canAttack() currently rejects only for the "not alone" reason. */
    private List<Card> nonSickAttackersOrAll() {
        List<Card> out = new ArrayList<>();
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isCreature() && (!c.isSick() || c.hasKeyword(forge.game.keyword.Keyword.HASTE))) {
                out.add(c);
            }
        }
        return out;
    }

    private int totalPower(List<Card> cards) {
        int p = 0;
        for (Card c : cards) {
            p += Math.max(0, c.getNetPower());
        }
        return p;
    }

    private int liveOpponentCount() {
        int n = 0;
        for (Player o : game.getPlayers()) {
            if (o != player && !o.hasLost()) {
                n++;
            }
        }
        return n;
    }

    /** Trample means blockers don't save the table: total attacker power over the
     *  opponents' combined life plus a buffer, with at least one attacker per
     *  opponent so the damage can be spread. */
    private boolean boardTrampleLethal(List<Card> attackers) {
        int opps = liveOpponentCount();
        if (opps == 0 || attackers.size() < opps) {
            return false;
        }
        int need = 20; // blocker / distribution buffer
        for (Player o : game.getPlayers()) {
            if (o != player && !o.hasLost()) {
                need += Math.max(0, o.getLife());
            }
        }
        return totalPower(attackers) >= need;
    }

    /** The next creature to pump — the lowest-power one Rhonas may target (any
     *  creature other than Rhonas itself), so the pumps spread evenly. */
    private Card pumpTarget(List<Card> candidates, Card rhonas) {
        Card best = null;
        for (Card c : candidates) {
            if (rhonas != null && c == rhonas) {
                continue; // Rhonas pumps ANOTHER creature
            }
            if (best == null || c.getNetPower() < best.getNetPower()) {
                best = c;
            }
        }
        return best;
    }

    /** A creature spell in hand we can afford, biggest body first (fewer pumps to
     *  lethal). Null when none is castable. */
    private SpellAbility castCreatureFromHand() {
        List<Card> creatures = new ArrayList<>();
        for (Card c : player.getCardsIn(ZoneType.Hand)) {
            if (c.isCreature()) {
                creatures.add(c);
            }
        }
        creatures.sort((a, b) -> Integer.compare(b.getNetPower(), a.getNetPower()));
        for (Card c : creatures) {
            SpellAbility cast = AbilityResolver.resolveCast(player, c.getName());
            if (cast != null && forge.ai.ComputerUtilCost.canPayCost(cast, player, false)) {
                return cast;
            }
        }
        return null;
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
        int pool = player.getManaPool().totalMana();
        // 1) Genesis Wave — flip the deck onto the board (leave the reserve).
        // Only when the flip is MEANINGFUL (>=10 cards) and the pool can pay
        // {X}{G}{G}{G}; a 1-card flip near the reserve boundary is not a win.
        int gwX = library - libraryReserve;
        if (gwX >= 10 && pool >= gwX + GENESIS_WAVE_TAIL) {
            SpellAbility gw = AbilityResolver.resolveCast(player, "Genesis Wave");
            if (gw != null && gw.getPayCosts() != null
                    && gw.getPayCosts().hasXInAnyCostPart()) {
                gw.setXManaCostPaid(gwX);
                outletCard = "Genesis Wave";
                outletX = gwX;
                return gw;
            }
        }
        // 2) Finale of Devastation ({X}{G}{G}) — fetch Craterhoof (trample) +
        // pump. Bound X by what the pool can actually pay (tail 2), and only
        // fire when X is meaningful; a floored-but-unpayable X would fizzle and
        // strand the bank.
        int finaleX = pool - 2;
        if (finaleX >= 10) {
            SpellAbility finale = AbilityResolver.resolveCast(player, "Finale of Devastation");
            if (finale != null && finale.getPayCosts() != null
                    && finale.getPayCosts().hasXInAnyCostPart()) {
                finale.setXManaCostPaid(finaleX);
                outletCard = "Finale of Devastation";
                outletX = finaleX;
                return finale;
            }
        }
        // 3) Craterhoof from hand — a team trample overrun. Craterhoof pumps
        // every creature +X/+X where X = creatures you control, so it is only a
        // win on a board wide enough to be lethal; on a 1-2 creature board it is
        // a wasted 8-mana last resort. Gate on a meaningful board.
        long creatures = player.getCardsIn(ZoneType.Battlefield).stream()
                .filter(Card::isCreature).count();
        if (creatures >= 4) {
            SpellAbility hoof = AbilityResolver.resolveCast(player, "Craterhoof Behemoth");
            if (hoof != null) {
                outletCard = "Craterhoof Behemoth";
                outletX = 0;
                return hoof;
            }
        }
        // 4) Goldvein Hydra ({X}{G}) — FLOOR outlet. Native vigilance+trample+
        // haste, enters with X +1/+1 counters (X = mana paid), so off infinite
        // mana it is a lone X/X trampler that swings the turn it lands. It only
        // kills ONE opponent (single body, no board flood), so it ranks below
        // the multi-kill outlets above; fire it only when the pool is large
        // enough that a trampler is unconditionally lethal to one seat even
        // through a chump (>=40), and nothing better was castable.
        int goldX = pool - 1; // {X}{G}: reserve one green for the coloured pip
        if (goldX >= 40) {
            SpellAbility gold = AbilityResolver.resolveCast(player, "Goldvein Hydra");
            if (gold != null && gold.getPayCosts() != null
                    && gold.getPayCosts().hasXInAnyCostPart()) {
                gold.setXManaCostPaid(goldX);
                outletCard = "Goldvein Hydra";
                outletX = goldX;
                return gold;
            }
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
