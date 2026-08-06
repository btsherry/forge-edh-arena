package forge.arena.engine;

import java.nio.file.Path;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.combo.ComboPilot;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.card.CounterEnumType;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * PR (bounce_recur) — the mana-funded bounce/ETB-recursion SINK. Distinct from
 * cast_recur (self-recast funded by a mana refund) and cast_bounce (Tidespout
 * cast-trigger): here an activated bounce ability on ANOTHER permanent (Temur
 * Sabertooth {1}{G}: return a creature; Kogla {1}{G}: return a Human) returns a
 * value creature to hand, we recast it, and its ETB/cast trigger fires a payoff
 * — every cycle, funded by Selvala's already-online (near-)infinite mana. The
 * research verdict: these are OUTLETS on the mana loop, not loops in their own
 * right (each is ~4-8 mana/cycle negative).
 *
 * <p>One runner, three payoffs (program picks via {@code payoff.measure}):
 * <ul>
 *   <li><b>board_counters</b> (C1, DIRECT KILL) — recast Eternal Witness (a green
 *       permanent) triggers Defiler of Vigor: a +1/+1 counter on EVERY creature
 *       you control, accumulating (the counter on the bounced Witness is lost,
 *       but the ones on Selvala/Sabertooth/Defiler stay). Board grows unbounded
 *       -> swing lethal. Measured by total +1/+1 counters on your creatures.</li>
 *   <li><b>hand_size</b> (C2) — The Great Henge draws a card per creature ETB;
 *       loop draws the library (stop before decking). Measured by hand size.</li>
 *   <li><b>opp_creatures</b> (C3, Kogla) — Kogla's ETB fight destroys an opponent
 *       creature each recast; measured by opponent creature count falling.</li>
 * </ul>
 *
 * <p>The bounce is a HIDDEN CHOICE (Sabertooth's {@code ChangeType$
 * Creature.YouCtrl+Other}, Kogla's {@code ValidTgts$ Human.YouCtrl}) — the
 * runner steers it to the recur creature via ComboAwareController's
 * pendingRecurBounce hook (the AI would not reliably pick the Witness).
 *
 * <p>Invariants: one action per priority window, yield until resolution;
 * MEASURED per-cycle payoff delta (strictly positive, or the trigger did not
 * fire -> abort); preconditions vs LIVE state; mana affordability priced by
 * canPayCost so the loop stops cleanly when the fuel runs out.
 */
public final class BounceRecurRunner {

    static final int ITERATION_CAP = 400;
    static final int SETTLE_GRACE_WINDOWS = 3;

    private enum State { LOOP, WIN }

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final ComboAwareLobbyPlayer.ComboAwareController controller;
    private final int seat;
    private final String comboId;

    private final String recurCard;
    private final String bounceCard;
    private final String bounceCost;
    private final String payoffMeasure;

    private State state = State.LOOP;
    private boolean finished;
    private boolean planned;
    private int iterations;

    // cycle: phase 0 = activate bounce (recur creature -> hand); 1 = recast
    private int cyclePhase;
    private boolean pendingMeasure;
    private long payoffAtCycleStart = -1;
    private int settleWait;

    BounceRecurRunner(Game game, Player player, ComboPilot pilot,
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
        JsonNode loop = p != null ? p.path("loop") : null;
        this.recurCard = loop != null ? loop.path("recur_card").asText(null) : null;
        JsonNode outlet = loop != null ? loop.path("bounce_outlet") : null;
        this.bounceCard = outlet != null ? outlet.path("card").asText(null) : null;
        this.bounceCost = outlet != null ? outlet.path("cost").asText("{1}{G}") : "{1}{G}";
        this.payoffMeasure = p != null
                ? p.path("payoff").path("measure").asText("board_counters") : "board_counters";
        if (recurCard == null || bounceCard == null) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_abort", game.getPhaseHandler().getTurn(), seat)
                    .with("combo", comboId).with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    public boolean isPiece(String cardName) {
        return cardName.equals(recurCard) || cardName.equals(bounceCard);
    }

    /** One action per priority window. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!game.getStack().isEmpty()) {
            return null; // invariant 2
        }

        if (pendingMeasure) {
            long now = payoffValue();
            if (now > payoffAtCycleStart) {
                pendingMeasure = false;
                settleWait = 0;
                iterations++;
                pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                        .with("outlet", recurCard).with("kind", "bounce_recur")
                        .with("iteration", iterations)
                        .with("payoff", now).with("measure", payoffMeasure)
                        .with("own_life", player.getLife()));
            } else if (settleWait < SETTLE_GRACE_WINDOWS) {
                settleWait++;
                return null;
            } else {
                return abort(turn, "payoff_no_delta: " + payoffMeasure + " "
                        + payoffAtCycleStart + "->" + now + " after cycle " + (iterations + 1));
            }
        }

        // terminate: the payoff has reached its natural end (board_counters ->
        // lethal board; hand_size -> library at the floor; opp_creatures -> the
        // opponents' creatures are all gone). Then the measured product IS the
        // win setup and we hand back (combat / a downstream outlet closes).
        if (state == State.LOOP && terminalReached()) {
            state = State.WIN;
        }
        if (state == State.WIN) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", iterations)
                    .with("exit", terminalExit()));
            return null;
        }
        if (iterations >= ITERATION_CAP) {
            return abort(turn, "iteration_cap: " + ITERATION_CAP);
        }

        // preconditions vs LIVE state
        Card recur = AbilityResolver.findBattlefield(player, recurCard);
        Card bounce = AbilityResolver.findBattlefield(player, bounceCard);
        if (bounce == null) {
            return abort(turn, "bounce_outlet_lost: '" + bounceCard + "'");
        }
        if (!planned) {
            planned = true;
            pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                    .with("combo", comboId).with("exit_state", "board_lethal_swing")
                    .with("recur", recurCard).with("bounce", bounceCard)
                    .with("measure", payoffMeasure).with("tranche", 1).with("iterations_done", 0));
        }

        if (cyclePhase == 0) {
            // phase 0 — activate the bounce, steering it to the recur creature.
            // The recur creature must be ON the battlefield to bounce it.
            if (recur == null) {
                // it may be in hand mid-cycle (a prior bounce not yet recast) —
                // if so, jump to recast; else it is genuinely gone
                if (inHand(recurCard)) {
                    cyclePhase = 1;
                } else {
                    return abort(turn, "recur_card_lost: '" + recurCard + "'");
                }
            } else {
                SpellAbility act = AbilityResolver.resolve(player, bounceCard, bounceCost, List.of());
                if (act == null || !forge.ai.ComputerUtilCost.canPayCost(act, player, false)) {
                    // fuel ran out (the mana loop is not online / drained) — the
                    // built board so far still stands; hand back rather than spin
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
                payoffAtCycleStart = payoffValue();
                controller.setPendingRecurBounce(recurCard); // steer the hidden choice
                cyclePhase = 1;
                return List.of(act);
            }
        }

        // phase 1 — recast the recur creature from hand; its ETB/cast payoff
        // fires (Defiler counters / Henge draw / Kogla fight), measured next.
        SpellAbility cast = AbilityResolver.resolveCast(player, recurCard);
        if (cast == null) {
            finished = true;
            pilot.programDeferred(comboId);
            return null;
        }
        cyclePhase = 0;
        pendingMeasure = true;
        return List.of(cast);
    }

    // --- payoff measures --------------------------------------------------

    private long payoffValue() {
        switch (payoffMeasure) {
            case "hand_size":
                return player.getCardsIn(ZoneType.Hand).size();
            case "opp_creatures":
                // fewer opponent creatures = MORE progress; negate so it "grows"
                return -opponentCreatureCount();
            case "opp_artifacts_enchantments":
                // Reclamation Sage class: each recast destroys an opposing
                // artifact/enchantment; fewer = more progress, so negate.
                return -opponentArtifactEnchantmentCount();
            case "board_counters":
            default:
                return boardCounters();
        }
    }

    private long boardCounters() {
        long total = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isCreature()) {
                total += c.getCounters(CounterEnumType.P1P1);
            }
        }
        return total;
    }

    private int opponentCreatureCount() {
        int n = 0;
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                for (Card c : other.getCardsIn(ZoneType.Battlefield)) {
                    if (c.isCreature()) {
                        n++;
                    }
                }
            }
        }
        return n;
    }

    private int opponentArtifactEnchantmentCount() {
        int n = 0;
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                for (Card c : other.getCardsIn(ZoneType.Battlefield)) {
                    if (c.isArtifact() || c.isEnchantment()) {
                        n++;
                    }
                }
            }
        }
        return n;
    }

    /** The board's total power clears the biggest single opponent's life —
     * a rough "can I alpha-strike lethal" gate for the counter build. */
    private boolean boardIsLethal() {
        int power = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isCreature()) {
                power += Math.max(0, c.getNetPower());
            }
        }
        int maxLife = 0;
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                maxLife = Math.max(maxLife, other.getLife());
            }
        }
        return power >= maxLife && maxLife > 0;
    }

    /** Leave a draw-buffer so a hand_size (draw-the-deck) loop stops short of
     * decking; a player who would win and lose simultaneously LOSES (CR 104.3f). */
    static final int LIBRARY_FLOOR = 8;

    private boolean terminalReached() {
        switch (payoffMeasure) {
            case "hand_size":
                return player.getCardsIn(ZoneType.Library).size() <= LIBRARY_FLOOR;
            case "opp_creatures":
                return opponentCreatureCount() == 0;
            case "opp_artifacts_enchantments":
                return opponentArtifactEnchantmentCount() == 0;
            case "board_counters":
            default:
                return boardIsLethal();
        }
    }

    private String terminalExit() {
        switch (payoffMeasure) {
            case "hand_size":
                return "library_floor";
            case "opp_creatures":
                return "opponents_cleared";
            case "opp_artifacts_enchantments":
                return "opp_artifacts_cleared";
            case "board_counters":
            default:
                return "board_lethal";
        }
    }

    private boolean inHand(String cardName) {
        for (Card c : player.getCardsIn(ZoneType.Hand)) {
            if (c.getName().equals(cardName)) {
                return true;
            }
        }
        return false;
    }

    private List<SpellAbility> abort(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                .with("combo", comboId).with("iterations", iterations).with("reason", reason));
        return null;
    }
}
