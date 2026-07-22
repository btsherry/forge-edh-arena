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
import forge.game.keyword.Keyword;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;

/**
 * Phase 11 PR-beta: the ONE runtime that executes a compiled ComboProgram
 * (arena.combo-program/1). Replaces the per-archetype executor + drill pair
 * for program combos — no fallback path exists for a combo that has a
 * program (Ben: dual paths for one combo caused real bugs; sequential
 * migration, never both).
 *
 * <p>The five interpreter invariants, each encoding a bug class this project
 * paid for once already:
 * <ol>
 * <li>Preconditions vs LIVE state, presence AND usability (PR-54).</li>
 * <li>At most one object on the stack, then yield until it resolves — the
 *     runner simply does nothing while the stack is non-empty (PR-74).</li>
 * <li>Post-step MEASURED deltas must match the program's expectations, or
 *     abort with a diagnostic naming expected vs observed (loop-health).</li>
 * <li>Sustain from structured facts, never rendered text (PR-73/76): the
 *     counters-floor precondition re-checked every iteration.</li>
 * <li>The sandbox proves; the LIVE game performs. Everything here acts on
 *     the real game (PR-71).</li>
 * </ol>
 *
 * <p>Loops run REAL iterations toward the governor v0 target — the cheapest
 * engine exit state (all opponents' life to zero) — never a declared jump;
 * a win the engine did not produce is not evidence. Interruption policy:
 * any broken invariant aborts for FRESH EVALUATION rather than resuming
 * blindly (boards change at instant speed or faster).
 */
public final class ProgramRunner {

    /** Runaway backstop far above any real N (3 opponents x 40 life = 120). */
    static final int ITERATION_CAP = 400;

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String comboId;
    private final JsonNode program;
    private final String outlet;

    private boolean finished;
    private int iterations;
    /**
     * PR-gamma governor v0: iterations are planned in TRANCHES. At each
     * boundary the governor recomputes N = min(exit-state need, self-
     * consumption cap) from the LIVE world and emits a governor_plan; a
     * tranche that exhausts with opponents still alive replans rather than
     * firing blindly (life totals move at instant speed). Ben's bound: going
     * 100 times generating mana is great, drawing 100 cards from your own
     * deck will lose you the game.
     */
    private int plannedThrough;
    private int tranche;
    private int grantTurn = -1;
    private boolean pendingGrant;
    private boolean pendingIteration;
    private int preLife;
    private int preCounters;
    private int lastTargetId = -1;
    private int settleWait;

    /**
     * Invariant 3 refinement: an empty stack is NOT "the world has settled".
     * A triggered ability can be queued but not yet PUT on the stack when we
     * next get priority — the ping's lifegain lands immediately with damage
     * resolution, but Heliod's counter arrives one beat later via the
     * trigger. Verifying at the first empty-stack poll read that gap as
     * "counters 2->1, delta_mismatch" and aborted a healthy loop. Deltas get
     * a short settling grace; only a delta still wrong after it is real.
     */
    static final int SETTLE_GRACE_WINDOWS = 3;

    ProgramRunner(Game game, Player player, ComboPilot pilot, int seat, String programPath) {
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
        String o = null;
        if (p != null) {
            for (JsonNode piece : p.path("pieces")) {
                if ("outlet".equals(piece.path("role").asText())) {
                    o = piece.path("card").asText();
                }
            }
        }
        this.outlet = o;
        if (p == null || o == null) {
            finished = true;
        }
    }

    public boolean finished() {
        return finished;
    }

    public String outletCard() {
        return outlet;
    }

    /** Is this card one of the program's own pieces? (trigger-obligation scope) */
    public boolean isPiece(String cardName) {
        if (program == null) {
            return false;
        }
        for (JsonNode piece : program.path("pieces")) {
            if (piece.path("card").asText().equals(cardName)) {
                return true;
            }
        }
        return false;
    }

    /**
     * The target the program OBLIGES for a trigger from the named source
     * card, or null when it declares none ({@code loop.trigger_obligations},
     * matched by {@code source}). This is how "Heliod's counter must return
     * to the Ballista" reaches the engine without a card name in code: the
     * compiled program declares it, the controller's
     * orderAndPlaySimultaneousSa override enforces it.
     */
    public String obligedTargetFor(String sourceCard) {
        if (program == null) {
            return null;
        }
        for (JsonNode ob : program.path("loop").path("trigger_obligations")) {
            if (ob.path("source").asText().equals(sourceCard)) {
                String t = ob.path("must_target").asText();
                return t.isEmpty() ? null : t;
            }
        }
        return null;
    }

    /** One decision per priority window; null = nothing to do this window. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        // invariant 2: one stack object at a time — wait for resolution
        if (!game.getStack().isEmpty()) {
            return null;
        }
        // verify a pending lifelink grant actually APPLIED (PR-71: performed
        // is not the same as resolved-and-effective)
        if (pendingGrant) {
            pendingGrant = false;
            JsonNode g = perTurnStep();
            String kw = g.path("verify").path("keyword").asText("LIFELINK");
            if (!outletHasKeyword(kw)) {
                return abort(turn, "grant_did_not_apply: " + kw + " absent on '" + outlet + "'");
            }
            grantTurn = turn;
            pilot.observe(ArenaEvent.of("loop_prereq", turn, seat)
                    .with("card", g.path("card").asText())
                    .with("target", outlet).with("played", true));
        }
        // invariant 3: verify the previous iteration's measured deltas
        if (pendingIteration) {
            int life = player.getLife();
            int counters = outletCounters();
            if (life <= preLife || counters < preCounters) {
                if (settleWait < SETTLE_GRACE_WINDOWS) {
                    settleWait++;
                    return null;
                }
                pendingIteration = false;
                return abort(turn, "delta_mismatch: expected own_life+1 and counters net 0;"
                        + " observed life " + preLife + "->" + life
                        + ", counters " + preCounters + "->" + counters
                        + " (after " + SETTLE_GRACE_WINDOWS + " settle windows);"
                        + " board counters=" + boardCounters());
            }
            pendingIteration = false;
            settleWait = 0;
            iterations++;
            pilot.reportDrillStep(turn, outlet, lastTargetId, iterations,
                    counters, life, outletHasKeyword("LIFELINK"));
        }
        // setup, frequency=once: put missing pieces onto the battlefield
        for (JsonNode step : program.path("setup")) {
            if (!"once".equals(step.path("frequency").asText())) {
                continue;
            }
            String card = step.path("card").asText();
            if (AbilityResolver.findBattlefield(player, card) != null) {
                continue;
            }
            SpellAbility cast = AbilityResolver.resolveCast(player, card);
            if (cast == null) {
                return abort(turn, "setup_piece_unreachable: '" + card + "'");
            }
            int xMin = step.path("x_min").asInt(0);
            if (xMin > 0 && cast.getPayCosts() != null
                    && cast.getPayCosts().hasXInAnyCostPart()) {
                cast.setXManaCostPaid(xMin);
            }
            return List.of(cast);
        }
        // invariant 1+4: preconditions vs live state, every iteration
        for (JsonNode pre : program.path("preconditions")) {
            String check = pre.path("check").asText();
            if (check.startsWith("on_battlefield")
                    && AbilityResolver.findBattlefield(player, pre.path("card").asText()) == null) {
                return abort(turn, "piece_lost: '" + pre.path("card").asText() + "'");
            }
            if ("counters_at_least".equals(check)
                    && outletCounters() < pre.path("n").asInt(2)) {
                return abort(turn, "insufficient_counters: " + outletCounters()
                        + " < " + pre.path("n").asInt(2));
            }
        }
        // setup, frequency=per_turn: duration-bound effects lapse (PR-77)
        JsonNode grant = perTurnStep();
        if (grant != null && (grantTurn != turn
                || !outletHasKeyword(grant.path("verify").path("keyword").asText("LIFELINK")))) {
            List<String> targets = grant.path("targets").isMissingNode()
                    ? List.of() : List.of(outlet);
            SpellAbility g = AbilityResolver.resolve(player,
                    grant.path("card").asText(), grant.path("cost").asText(), targets);
            if (g == null) {
                return abort(turn, "grant_unresolvable: " + AbilityResolver.describe(player,
                        grant.path("card").asText(), grant.path("cost").asText(), targets));
            }
            pendingGrant = true;
            return List.of(g);
        }
        // governor v0: cheapest exit state = each opponent's life to zero,
        // lowest-life head first. Table dead -> the program is complete.
        Player target = null;
        for (Player p : game.getPlayers()) {
            if (p != player && !p.hasLost()
                    && (target == null || p.getLife() < target.getLife())) {
                target = p;
            }
        }
        if (target == null) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", iterations));
            return null;
        }
        if (iterations >= ITERATION_CAP) {
            return abort(turn, "iteration_cap: " + ITERATION_CAP);
        }
        // governor v0 (PR-gamma): plan a tranche when the previous one is
        // spent. Need is measured from the live table, the cap from the
        // program's declared self-consumption vs live resources.
        if (iterations >= plannedThrough) {
            int need = 0;
            for (Player p : game.getPlayers()) {
                if (p != player && !p.hasLost()) {
                    need += Math.max(0, p.getLife());
                }
            }
            int cap = selfConsumptionCap();
            int planned = Math.min(need, cap);
            if (planned <= 0) {
                return abort(turn, "self_floor: exit state needs " + need
                        + " more iterations but the resource cap allows " + cap);
            }
            plannedThrough = iterations + planned;
            tranche++;
            pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                    .with("combo", comboId)
                    .with("exit_state", program.path("exit_states").path(0)
                            .path("engine_state").asText("opponent_life_zero_each"))
                    .with("need", need)
                    .with("cap", cap == Integer.MAX_VALUE ? "none" : cap)
                    .with("planned", planned)
                    .with("tranche", tranche)
                    .with("iterations_done", iterations));
        } else if (selfConsumptionCap() <= 0) {
            // mid-tranche floor breach (an opponent milling us, a life drain):
            // the declared resource hit its floor before the tranche did
            return abort(turn, "self_floor: resource at floor mid-tranche after "
                    + iterations + " iterations");
        }
        // fire one real iteration
        SpellAbility ping = AbilityResolver.resolveAtPlayer(player, outlet, null, target);
        if (ping == null) {
            return abort(turn, "loop_action_unresolvable on '" + outlet + "'");
        }
        preLife = player.getLife();
        preCounters = outletCounters();
        lastTargetId = target.getId();
        pendingIteration = true;
        return List.of(ping);
    }

    /**
     * How many more iterations the program's declared self-consumption
     * permits, from LIVE resources ({@code self_consumption}: what the loop
     * spends of its OWN that it cannot get back). {@code none} is unbounded;
     * {@code library} keeps a floor above drawing out (CR 704.5c); {@code
     * life} keeps a floor above our own payments. Default floors are the
     * plan's (library 5, life 10) — a program may declare tighter ones.
     */
    private int selfConsumptionCap() {
        JsonNode sc = program.path("self_consumption");
        String resource = sc.path("resource").asText("none");
        return switch (resource) {
            case "library" -> player.getCardsIn(forge.game.zone.ZoneType.Library).size()
                    - sc.path("floor").asInt(5);
            case "life" -> player.getLife() - sc.path("floor").asInt(10);
            default -> Integer.MAX_VALUE;
        };
    }

    private JsonNode perTurnStep() {
        for (JsonNode step : program.path("setup")) {
            if ("per_turn".equals(step.path("frequency").asText())) {
                return step;
            }
        }
        return null;
    }

    private List<SpellAbility> abort(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                .with("combo", comboId).with("iterations", iterations)
                .with("reason", reason));
        return null;
    }

    /** Diagnostic: P1P1 counts on every own battlefield card (mistarget vs no-fire). */
    private String boardCounters() {
        StringBuilder sb = new StringBuilder();
        for (Card c : player.getCardsIn(forge.game.zone.ZoneType.Battlefield)) {
            int n = c.getCounters(CounterEnumType.P1P1);
            if (n > 0 || c.getName().equals(outlet)) {
                sb.append(c.getName()).append('=').append(n).append(' ');
            }
        }
        return sb.toString().trim();
    }

    private int outletCounters() {
        Card c = AbilityResolver.findBattlefield(player, outlet);
        return c == null ? -1 : c.getCounters(CounterEnumType.P1P1);
    }

    private boolean outletHasKeyword(String keyword) {
        Card c = AbilityResolver.findBattlefield(player, outlet);
        try {
            return c != null && c.hasKeyword(Keyword.valueOf(keyword));
        } catch (IllegalArgumentException bad) {
            return false;
        }
    }
}
