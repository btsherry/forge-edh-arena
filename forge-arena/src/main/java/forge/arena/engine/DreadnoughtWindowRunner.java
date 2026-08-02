package forge.arena.engine;

import java.nio.file.Path;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.combo.ComboPilot;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.spellability.SpellAbilityStackInstance;
import forge.game.zone.ZoneType;

/**
 * PR (dreadnought_window) — the NEW shape from the whole-deck discovery run:
 * an instant-speed VALUE BURST taken inside a creature's own ETB-trigger
 * window. Phyrexian Dreadnought costs {1} and is a 12/12, but its ETB
 * trigger sacrifices it unless you sacrifice creatures with total power 12+.
 * Between the trigger being PUT on the stack (CR 603.3) and its resolution
 * the pilot holds priority with a 12/12 on the battlefield — that window is
 * the whole combo. The runner casts the body, waits for the trigger to reach
 * the stack, then acts:
 *
 * <ul>
 *   <li><b>sac_draw</b> — respond by sacrificing the 12/12 to a draw-for-power
 *       outlet (Momentous Fall's additional Sac cost, cast; Greater Good's
 *       {@code Sac<1/Creature>} activated ability). The sacrifice is STEERED
 *       to the body via the controller's choosePermanentsToSacrifice override
 *       (stock would sac a dork, not the 12/12). Dreadnought's own trigger
 *       then finds it gone and does nothing. Measured by hand growth.</li>
 *   <li><b>power_mana</b> — respond by activating Selvala's {G},{T} mana
 *       ability, whose yield reads the greatest creature power (12 while the
 *       body is on the battlefield). No sacrifice; the body dies to its own
 *       trigger afterward. Measured by mana-pool growth.</li>
 * </ul>
 *
 * <p>This is the designed exception to the "yield while the stack is non-empty"
 * invariant, exactly like PairingRunner's respond-on-stack: the exploit MUST
 * be played with the body's trigger on the stack. A one-shot (no loop): one
 * body, one burst, hand back. Any broken step aborts for fresh evaluation.
 */
public final class DreadnoughtWindowRunner {

    /** Windows to wait for the body's ETB trigger to reach the stack before
     * giving up (the cast must resolve first — a couple of priority passes). */
    static final int TRIGGER_WAIT_WINDOWS = 4;
    /** A burst is "real" only if the measured delta clears this floor — a
     * mistargeted sac (drew off a 1-power dork) or a fizzled read reads small. */
    static final int DEFAULT_EXPECT_MIN = 4;

    private enum State { SETUP, WAIT_TRIGGER, EXPLOIT, MEASURE, POWER_LOOP }

    /** power_loop: how many windows to wait for an untap ability to resolve
     * before banking what we have (a spin guard — the loop can never hang). */
    static final int LOOP_SPIN_CAP = 6;

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final ComboAwareLobbyPlayer.ComboAwareController controller;
    private final int seat;
    private final String comboId;

    private final String bodyCard;
    private final String exploitCard;
    private final String exploitKind;     // sac_draw | power_mana | power_draw | power_loop
    private final String exploitCost;      // activated cost ({G} Selvala, Sac<1/Creature> Greater Good)
    private final boolean exploitActivate; // true = activated ability, false = cast a spell
    private final String sacrificeTarget;  // sac_draw: the creature to sacrifice (the body)
    private final String measure;          // hand_size | mana_pool
    private final int expectMin;
    private final String untapCost;        // power_loop: the granted untap ability's cost ({3} for Umbral)
    private final int maxCycles;           // power_loop: hard bound on tap/untap cycles

    private State state = State.SETUP;
    private boolean finished;
    private int waited;
    private long burstBefore = -1;
    // power_loop state (respond-on-stack — the sac-trigger stays pinned under
    // our own untap ability every cycle, so the 12/12 body never leaves)
    private int loopPhase;                  // 0=tap, 1=verify+untap, 2=wait untap
    private int loopCyclesDone;
    private long poolBeforeCycle = -1;
    private long bankStart = -1;
    private int loopSpin;

    DreadnoughtWindowRunner(Game game, Player player, ComboPilot pilot,
            ComboAwareLobbyPlayer.ComboAwareController controller, int seat, String programPath) {
        this.game = game;
        this.player = player;
        this.pilot = pilot;
        this.controller = controller;
        this.seat = seat;
        JsonNode p;
        try {
            p = new ObjectMapper().readTree(Path.of(programPath).toFile());
        } catch (Exception e) {
            p = null;
        }
        this.comboId = p != null ? p.path("combo_id").asText("?") : "?";
        JsonNode w = p != null ? p.path("window") : null;
        this.bodyCard = w != null ? w.path("body").asText(null) : null;
        JsonNode ex = w != null ? w.path("exploit") : null;
        this.exploitCard = ex != null ? ex.path("card").asText(null) : null;
        this.exploitKind = ex != null ? ex.path("kind").asText("sac_draw") : "sac_draw";
        this.exploitCost = ex != null ? ex.path("cost").asText("{G}") : "{G}";
        this.exploitActivate = ex != null && ex.path("activate").asBoolean(false);
        this.sacrificeTarget = ex != null ? ex.path("sacrifice").asText(null) : null;
        this.measure = ex != null ? ex.path("measure").asText("hand_size") : "hand_size";
        this.expectMin = ex != null ? ex.path("expect_min").asInt(DEFAULT_EXPECT_MIN) : DEFAULT_EXPECT_MIN;
        this.untapCost = ex != null ? ex.path("untap_cost").asText("{3}") : "{3}";
        this.maxCycles = ex != null ? ex.path("max_cycles").asInt(12) : 12;
        if (bodyCard == null || exploitCard == null) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_abort", game.getPhaseHandler().getTurn(), seat)
                    .with("combo", comboId).with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    public boolean isPiece(String cardName) {
        return cardName.equals(bodyCard) || cardName.equals(exploitCard);
    }

    /** One decision per priority window — called stack-empty or not. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        switch (state) {
            case SETUP -> {
                // stack must be empty to cast the body at sorcery speed
                if (!game.getStack().isEmpty()) {
                    return null;
                }
                if (AbilityResolver.findBattlefield(player, bodyCard) != null) {
                    // already on the battlefield (an earlier deploy cast it) —
                    // its ETB trigger has long resolved and sacrificed it out of
                    // the window; nothing to exploit
                    return abort(turn, "body_already_resolved: '" + bodyCard
                            + "' on battlefield with no live trigger window");
                }
                SpellAbility cast = AbilityResolver.resolveCast(player, bodyCard);
                if (cast == null) {
                    // unaffordable/absent body cast spent nothing — defer quietly
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
                state = State.WAIT_TRIGGER;
                waited = 0;
                pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                        .with("combo", comboId).with("exit_state", "value_burst")
                        .with("body", bodyCard).with("exploit", exploitCard)
                        .with("kind", exploitKind).with("measure", measure)
                        .with("tranche", 1).with("iterations_done", 0));
                return List.of(cast);
            }
            case WAIT_TRIGGER -> {
                // the body's ETB sac-trigger reaches the stack one priority
                // after its spell resolves; act only once the 12/12 is on the
                // battlefield AND its trigger is on the stack
                Card body = AbilityResolver.findBattlefield(player, bodyCard);
                if (body != null && triggerOnStack(bodyCard)) {
                    if ("power_loop".equals(exploitKind)) {
                        state = State.POWER_LOOP;
                        bankStart = burstValue();
                        return powerLoop(turn);
                    }
                    state = State.EXPLOIT;
                    return exploit(turn, body);
                }
                if (body == null && waited > 0) {
                    // the trigger resolved before we acted (or the cast was
                    // countered) — the 12/12 is gone, the window is closed
                    return abort(turn, "window_closed: '" + bodyCard
                            + "' left before the exploit (trigger resolved / countered)");
                }
                if (waited++ >= TRIGGER_WAIT_WINDOWS) {
                    return abort(turn, "trigger_never_reached_stack: '" + bodyCard + "'");
                }
                return null; // the body's spell is still resolving — wait
            }
            case EXPLOIT -> {
                // re-entrant guard: EXPLOIT already fired its SA and set MEASURE
                return null;
            }
            case POWER_LOOP -> {
                return powerLoop(turn);
            }
            case MEASURE -> {
                if (!game.getStack().isEmpty()) {
                    return null; // the exploit is resolving — wait
                }
                long now = burstValue();
                long delta = now - burstBefore;
                finished = true;
                if (delta >= expectMin) {
                    pilot.observe(ArenaEvent.of("dreadnought_window", turn, seat)
                            .with("combo", comboId).with("body", bodyCard)
                            .with("exploit", exploitCard).with("kind", exploitKind)
                            .with("measure", measure).with("delta", delta)
                            .with("own_life", player.getLife()));
                    pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                            .with("combo", comboId).with("iterations", 1)
                            .with("outlet", exploitCard));
                    return null;
                }
                pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                        .with("combo", comboId).with("iterations", 0)
                        .with("reason", "burst_below_floor: " + measure + " delta " + delta
                                + " < " + expectMin + " (mistargeted sac / fizzled read?)"));
                return null;
            }
            default -> {
                return null;
            }
        }
    }

    /** Fire the exploit in the body's trigger window; sets MEASURE + the
     * pre-burst baseline, or aborts when the exploit is unresolvable. */
    private List<SpellAbility> exploit(int turn, Card body) {
        SpellAbility ex;
        if ("power_mana".equals(exploitKind)) {
            // activate the producer's mana ability; its yield reads the body's
            // 12 power while it is on the battlefield (measured by pool growth)
            ex = AbilityResolver.resolve(player, exploitCard, exploitCost, List.of());
        } else if ("power_draw".equals(exploitKind)) {
            // cast a charm (Return of the Wildspeaker) and steer it to its DRAW
            // mode; draw = greatest non-Human power, pinned at 12 by the body.
            // It resolves ABOVE the sac-trigger (LIFO), so the 12/12 is still
            // present when the count is taken.
            controller.setPendingCharmDrawHost(exploitCard);
            ex = AbilityResolver.resolveCast(player, exploitCard);
        } else {
            // sac_draw: cast (Momentous Fall) or activate (Greater Good) a
            // draw-for-power outlet, STEERING its sacrifice cost onto the body
            if (sacrificeTarget != null) {
                controller.setPendingSacChoice(sacrificeTarget);
            }
            ex = exploitActivate
                    ? AbilityResolver.resolve(player, exploitCard, exploitCost, List.of())
                    : AbilityResolver.resolveCast(player, exploitCard);
        }
        if (ex == null || !forge.ai.ComputerUtilCost.canPayCost(ex, player, false)) {
            // couldn't pay the exploit (no mana in the window) — the body will
            // die to its own trigger; nothing spent on the exploit, defer
            finished = true;
            pilot.programDeferred(comboId);
            return null;
        }
        burstBefore = burstValue();
        state = State.MEASURE;
        return List.of(ex);
    }

    /**
     * power_loop: keep the body's sac-trigger SUSPENDED (our own untap ability
     * sits above it every cycle, LIFO), and loop tap-for-mana + untap at a
     * PINNED yield — the producer reads the 12/12's power each cycle. Hard
     * bounded by {@code max_cycles} and a spin guard, so it can never hang; the
     * banked pool is the product, spent by the pilot's outlets the same phase.
     * When we stop adding to the stack the sac-trigger resolves and the body
     * dies. (v1 supports a single-step granted untap — Umbral Mantle's {3}{Q}
     * on the producer; a producer whose "any" mana isn't steered green relies on
     * the deck's own green for the {G} tap, as the loop runners do.)
     */
    private List<SpellAbility> powerLoop(int turn) {
        Card producer = AbilityResolver.findBattlefield(player, exploitCard);
        if (producer == null) {
            return finishLoop(turn); // producer gone — bank what we have
        }
        if (loopPhase == 0) {
            // TAP: the producer's mana ability (a mana ability — resolves
            // immediately, does NOT pass priority, so the sac-trigger stays put)
            if (producer.isTapped()) {
                loopPhase = 2; // recover by waiting for it to untap
                return null;
            }
            SpellAbility tap = AbilityResolver.resolve(player, exploitCard, exploitCost, List.of());
            if (tap == null || !forge.ai.ComputerUtilCost.canPayCost(tap, player, false)) {
                return finishLoop(turn); // out of green for the tap — bank + stop
            }
            poolBeforeCycle = player.getManaPool().totalMana();
            loopPhase = 1;
            return List.of(tap);
        }
        if (loopPhase == 1) {
            // VERIFY the tap grew the pool, then either finish (bound reached /
            // untap unaffordable) or activate the untap ability (goes on stack,
            // re-suspending the sac-trigger beneath it)
            if (player.getManaPool().totalMana() <= poolBeforeCycle) {
                return finishLoop(turn); // the tap produced nothing measurable
            }
            loopCyclesDone++;
            if (loopCyclesDone >= maxCycles) {
                return finishLoop(turn);
            }
            SpellAbility untap = AbilityResolver.resolve(player, exploitCard, untapCost, List.of());
            if (untap == null || !forge.ai.ComputerUtilCost.canPayCost(untap, player, false)) {
                return finishLoop(turn); // can't afford the untap — bank + stop
            }
            loopSpin = 0;
            loopPhase = 2;
            return List.of(untap);
        }
        // loopPhase 2: WAIT for the untap ability to resolve (producer untapped)
        if (!producer.isTapped()) {
            loopPhase = 0;              // untapped — tap again
            return powerLoop(turn);
        }
        if (loopSpin++ >= LOOP_SPIN_CAP) {
            return finishLoop(turn);    // untap never resolved — bank + stop
        }
        return null;                    // the untap ability is still resolving
    }

    /** Terminate the power_loop: the banked pool over {@code bankStart} is the
     * measured product. Emits the burst + program_complete, or aborts if we
     * never banked past the floor. Handing back lets the sac-trigger resolve. */
    private List<SpellAbility> finishLoop(int turn) {
        finished = true;
        long delta = burstValue() - bankStart;
        if (delta >= expectMin && loopCyclesDone >= 1) {
            pilot.observe(ArenaEvent.of("dreadnought_window", turn, seat)
                    .with("combo", comboId).with("body", bodyCard)
                    .with("exploit", exploitCard).with("kind", exploitKind)
                    .with("measure", measure).with("delta", delta)
                    .with("cycles", loopCyclesDone).with("own_life", player.getLife()));
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", loopCyclesDone)
                    .with("outlet", exploitCard));
            return null;
        }
        pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                .with("combo", comboId).with("iterations", loopCyclesDone)
                .with("reason", "power_loop_below_floor: banked " + delta
                        + " over " + loopCyclesDone + " cycles < " + expectMin));
        return null;
    }

    private long burstValue() {
        if ("mana_pool".equals(measure)) {
            return player.getManaPool().totalMana();
        }
        return player.getCardsIn(ZoneType.Hand).size();
    }

    /** Is a TRIGGERED ability sourced from the named card on the stack right
     * now (the body's ETB sac-trigger), controlled by us? */
    private boolean triggerOnStack(String cardName) {
        for (SpellAbilityStackInstance si : game.getStack()) {
            if (si.isTrigger() && si.getSourceCard() != null
                    && cardName.equals(si.getSourceCard().getName())
                    && si.getActivatingPlayer() == player) {
                return true;
            }
        }
        return false;
    }

    private List<SpellAbility> abort(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                .with("combo", comboId).with("iterations", 0).with("reason", reason));
        return null;
    }
}
