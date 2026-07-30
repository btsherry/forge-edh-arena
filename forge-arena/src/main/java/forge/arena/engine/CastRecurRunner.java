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
import forge.game.cost.CostPart;
import forge.game.cost.CostRemoveCounter;
import forge.game.cost.CostReturn;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * PR (cast_recur, Body C — self_recast): recast a bounce-to-hand creature
 * whose recast is mana-neutral thanks to a refund source, converting each
 * ETB through an ON-BOARD damage payoff (Purphoros: creature enters → 2 to
 * each opponent). The FIRST non-Aetherflux outlet, and the cleanest
 * verification in the project — the loop product is directly lethal and
 * directly MEASURED by opponent-life delta.
 *
 * <p>Grinning Ignus + {Steam-Kin | Birgi}: the refund_source is a PROGRAM
 * PARAMETER, so one body covers both the Spellbook combo (Steam-Kin counter
 * cycle) and Ben's paper line (Birgi per-cast mana). Names come from the
 * program JSON; the abilities are found STRUCTURALLY (a mana ability whose
 * cost returns its host; a mana ability whose cost removes counters), never
 * by card name in code.
 *
 * <p>The five invariants, cast_recur form: preconditions vs LIVE state
 * (refund source + recur card + an outlet on board); one action per window,
 * yield until resolved; MEASURED per-iteration delta (opponent life fell —
 * the ETB payoff fired); costs/targets from structured facts; live game
 * performs. Termination is the ENGINE'S: loop until every opponent is dead
 * (state-based) — the amplifier math only sizes the governor plan, it is not
 * load-bearing for correctness.
 */
public final class CastRecurRunner {

    /** Runaway backstop far above any real N (3 opp × 40 life ÷ 2 = 60). */
    static final int ITERATION_CAP = 400;
    static final int SETTLE_GRACE_WINDOWS = 3;

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String comboId;
    private final JsonNode program;
    private final String recurCard;
    private final String refundCard;
    private final boolean refundIsCounterCycle;

    private boolean finished;
    private boolean planned;
    private int iterations;
    private boolean pendingVerify;
    private int oppLifeAtCast = -1;
    private int settleWait;

    CastRecurRunner(Game game, Player player, ComboPilot pilot, int seat, String programPath) {
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
        this.recurCard = loop != null ? loop.path("recur_card").asText(null) : null;
        JsonNode refund = loop != null ? loop.path("refund_source") : null;
        this.refundCard = refund != null ? refund.path("card").asText(null) : null;
        this.refundIsCounterCycle = refund != null
                && "counter_cycle".equals(refund.path("kind").asText(""));
        if (recurCard == null || refundCard == null) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_abort",
                    game.getPhaseHandler().getTurn(), seat)
                    .with("combo", comboId).with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    public boolean isPiece(String cardName) {
        return cardName.equals(recurCard) || cardName.equals(refundCard);
    }

    /** One decision per priority window. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!game.getStack().isEmpty()) {
            return null; // invariant 2 — yield until resolution
        }

        // invariant 3: verify the previous cast's ETB actually dealt damage
        if (pendingVerify) {
            int oppLifeNow = opponentLifeTotal();
            if (oppLifeNow < oppLifeAtCast) {
                pendingVerify = false;
                settleWait = 0;
                iterations++;
                pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                        .with("outlet", recurCard).with("kind", "cast_recur")
                        .with("iteration", iterations)
                        .with("opp_life", oppLifeNow)
                        .with("own_life", player.getLife()));
            } else {
                // an empty stack is not a settled world — the ETB damage can
                // arrive a beat after the cast resolves; grace, then abort
                if (settleWait < SETTLE_GRACE_WINDOWS) {
                    settleWait++;
                    return null;
                }
                return abort(turn, "etb_no_damage: opponent life " + oppLifeAtCast
                        + "->" + oppLifeNow + " after cast (no on-board outlet firing?)");
            }
        }

        // win check — the engine's, not ours
        if (allOpponentsDead()) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", iterations));
            return null;
        }
        if (iterations >= ITERATION_CAP) {
            return abort(turn, "iteration_cap: " + ITERATION_CAP);
        }

        // preconditions vs LIVE state, once entered
        if (AbilityResolver.findBattlefield(player, refundCard) == null) {
            return abort(turn, "refund_source_lost: '" + refundCard + "'");
        }
        if (perEtbDamage() <= 0) {
            return abort(turn, "no_outlet: no creature-ETB damage trigger on board");
        }

        if (!planned) {
            planned = true;
            int need = maxOpponentLife();
            int perEtb = perEtbDamage();
            pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                    .with("combo", comboId)
                    .with("exit_state", "opponents_life_zero_each")
                    .with("need", need)
                    .with("per_etb", perEtb)
                    .with("planned", perEtb > 0 ? (need + perEtb - 1) / perEtb : ITERATION_CAP)
                    .with("tranche", 1)
                    .with("iterations_done", iterations));
        }

        Card recur = AbilityResolver.findBattlefield(player, recurCard);
        if (recur != null) {
            // Ignus is on the battlefield — activate its self-returning mana
            // ability ({R}, return to hand → {C}{C}{R}). Found structurally.
            // The activation's {R} is funded by the refund source (Steam-Kin
            // RRR / Birgi mana), NOT by external lands — reload first when
            // it cannot be paid, or the loop drains its priming and stalls.
            SpellAbility ret = selfReturnManaAbility(recur);
            if (ret == null) {
                return abort(turn, "return_ability_unresolvable on '" + recurCard + "'");
            }
            if (!payable(ret)) {
                SpellAbility reload = readyReload();
                if (reload != null) {
                    return List.of(reload);
                }
                finished = true;
                pilot.programDeferred(comboId);
                return null;
            }
            return List.of(ret);
        }

        // Ignus is in hand — recast it (funded by its own {C}{C}{R}); reload
        // the refund first if the recast is unpayable.
        SpellAbility cast = AbilityResolver.resolveCast(player, recurCard);
        if (cast == null) {
            SpellAbility reload = readyReload();
            if (reload != null) {
                return List.of(reload);
            }
            // nothing was spent — hand the combo back for fresh evaluation
            finished = true;
            pilot.programDeferred(comboId);
            return null;
        }
        oppLifeAtCast = opponentLifeTotal();
        pendingVerify = true;
        return List.of(cast);
    }

    /** A mana ability of the host whose cost RETURNS the host to hand. */
    private SpellAbility selfReturnManaAbility(Card host) {
        for (SpellAbility sa : host.getAllPossibleAbilities(player, false)) {
            if (!sa.isManaAbility() || sa.getPayCosts() == null) {
                continue;
            }
            for (CostPart part : sa.getPayCosts().getCostParts()) {
                if (part instanceof CostReturn) {
                    sa.setActivatingPlayer(player);
                    return sa;
                }
            }
        }
        return null;
    }

    /** A mana ability of the host whose cost REMOVES counters (Steam-Kin). */
    private SpellAbility counterRemovalManaAbility(Card host) {
        if (host == null) {
            return null;
        }
        for (SpellAbility sa : host.getAllPossibleAbilities(player, false)) {
            if (!sa.isManaAbility() || sa.getPayCosts() == null) {
                continue;
            }
            for (CostPart part : sa.getPayCosts().getCostParts()) {
                if (part instanceof CostRemoveCounter) {
                    sa.setActivatingPlayer(player);
                    return sa;
                }
            }
        }
        return null;
    }

    private int counterCount(Card host) {
        return host == null ? 0 : host.getCounters(CounterEnumType.P1P1);
    }

    private boolean payable(SpellAbility sa) {
        return sa != null && sa.getPayCosts() != null
                && forge.ai.ComputerUtilCost.canPayCost(sa, player, false);
    }

    /**
     * The counter-cycle refund's mana ability (Steam-Kin's RRR), IF it is
     * ready to fire (counters full) — the loop's self-funding source. Birgi
     * (per_cast_mana) has no reload: its mana arrives automatically on each
     * cast, so this returns null and the pool feeds itself.
     */
    private SpellAbility readyReload() {
        if (!refundIsCounterCycle) {
            return null;
        }
        Card refund = AbilityResolver.findBattlefield(player, refundCard);
        SpellAbility reload = counterRemovalManaAbility(refund);
        return reload != null && payable(reload) ? reload : null;
    }

    /**
     * Per-ETB damage the board's amplified outlet deals to an opponent.
     * Purphoros class = 2 base; Terror = its power. Sums damage triggers on
     * OUR battlefield that fire on another creature entering. Advisory only —
     * termination is by measured opponent death, so a rough number is fine.
     */
    private int perEtbDamage() {
        int total = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            String oracle = c.getOracleText() == null ? "" : c.getOracleText().toLowerCase();
            boolean etbTrigger = oracle.contains("enters")
                    && oracle.contains("deals")
                    && (oracle.contains("each opponent") || oracle.contains("any target"));
            if (etbTrigger) {
                java.util.regex.Matcher m = java.util.regex.Pattern
                        .compile("deals (\\d+) damage").matcher(oracle);
                total += m.find() ? Integer.parseInt(m.group(1)) : Math.max(1, c.getNetPower());
            }
        }
        return total;
    }

    private int opponentLifeTotal() {
        int total = 0;
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                // raw life, NOT max(0,...): a 'can't lose' opponent held at
                // negative life (Platinum Angel class) must still register a
                // dropping delta, or the loop false-aborts (Gemini review)
                total += other.getLife();
            }
        }
        return total;
    }

    private int maxOpponentLife() {
        int max = 0;
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                max = Math.max(max, other.getLife());
            }
        }
        return max;
    }

    private boolean allOpponentsDead() {
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                return false;
            }
        }
        return true;
    }

    private List<SpellAbility> abort(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                .with("combo", comboId).with("iterations", iterations)
                .with("reason", reason));
        return null;
    }
}
