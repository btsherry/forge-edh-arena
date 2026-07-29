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
import forge.game.zone.ZoneType;

/**
 * PR-chi: the cast-bounce interpreter (program_class: cast_bounce) — the
 * Tidespout family's shape. Two of OUR casts per iteration, each one bounced
 * back by the engine's mandatory SpellCast trigger: tap the rock (+N, a mana
 * ability, off-stack), cast the zero-cost fodder (the trigger MUST target
 * the rock — it bounces to HAND), recast the rock from hand (the trigger
 * MUST target the fodder — it bounces to HAND), repeat. Net positive mana,
 * +2 storm per iteration; the close is Aetherflux Reservoir's storm-count
 * lifegain (the kth cast of the turn gains k), NOT a library playout.
 *
 * <p>The binding invariants, cast-bounce form — each a paid-for bug class:
 * <ol>
 * <li>Preconditions vs LIVE state, presence AND usability: a tapped rock
 *     cannot tap — Forge's CostTap.payAsDecided returns true on a no-op tap
 *     and MINTS the mana (PR-lambda, traced to source), so the runner gates
 *     on isTapped itself and never asks a tapped rock for mana.</li>
 * <li>One stack object per window, then yield until it resolves.</li>
 * <li>Count NOTHING at SA-return: every half-iteration is verified by
 *     MEASUREMENT next window — spend-proof (the pool moved exactly as the
 *     program declares) and zone-proof (the bounced piece actually reached
 *     HAND). A countered cast, a stolen trigger, a mistargeted bounce all
 *     surface as measured mismatches, never as phantom iterations.</li>
 * <li>Costs and targets from the program JSON only — no card names in
 *     code. The alternating trigger obligation is served to the controller
 *     via {@link #obligedTargetForPhase} (the proven
 *     orderAndPlaySimultaneousSa seam), returning the rock or the fodder
 *     depending on the loop half.</li>
 * <li>Aborts are fresh_evaluation via program_abort; an unaffordable or
 *     unreachable SETUP defers quietly via pilot.programDeferred — nothing
 *     was spent, so nothing may burn the refire lockout.</li>
 * </ol>
 *
 * <p>Tapped-rock entry is NORMALIZED, not deferred: the loop's second half
 * runs first (cast fodder, bounce the TAPPED rock to hand, recast it — it
 * enters untapped). Load-bearing for Mana Vault and Grim Monolith, which
 * never untap on their own: the bounce is the deck's only free untap. The
 * normalization recast's spend-proof expects land payment when the pool is
 * short (the only half where that is legitimate); every in-loop recast is
 * fully pool-funded (tap_produces >= recast_cost) and stays exact.
 *
 * <p>The governor plans iterations from the outlet's declared lifegain
 * target against the LIVE storm count and judges completion by MEASURED
 * life, replanning at tranche boundaries; on completion it hands the seat
 * back — the existing drill machinery activates the outlet's PayLife<50>,
 * never the runner.
 */
public final class CastBounceRunner {

    static final int ITERATION_CAP = 400;

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String comboId;
    private final JsonNode program;

    // program facts — pieces/roles, costs, obligation source, outlet: all
    // read from the compiled JSON, never named in code
    private String engineName;
    private String rockName;
    private String outletName;
    private String obligationSource;
    private int tapProduces;
    private int recastCost;
    private int lifeTarget;
    /** Resolved at ENTRY from the template piece's resolve_from vs live hand. */
    private String fodderName;

    private enum State { SETUP, TAP, CAST_FODDER, RECAST_ROCK }

    private State state = State.SETUP;
    private boolean finished;
    private int iterations;
    private int plannedThrough;
    private int tranche;
    private int lifeAtPlan = -1;

    /** Measurement baselines — nothing counts at SA-return. */
    private boolean pendingTap;
    private boolean pendingFodder;
    private boolean pendingRock;
    private int poolBefore = -1;
    private int stormAtIterationStart = -1;
    /** The one half-pair allowed to pay its recast from lands: the tapped-
     *  rock entry normalization, where no tap could fund the pool first. */
    private boolean normalizing;

    /** The bounce target the CURRENT loop half obliges, or null (setup). */
    private String bounceTarget;

    CastBounceRunner(Game game, Player player, ComboPilot pilot, int seat, String programPath) {
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
        if (p == null) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_abort", game.getPhaseHandler().getTurn(), seat)
                    .with("combo", comboId).with("reason", "program_unreadable: " + programPath));
            return;
        }
        for (JsonNode piece : p.path("pieces")) {
            String role = piece.path("role").asText();
            if ("engine".equals(role)) {
                engineName = piece.path("card").asText(null);
            }
            if ("rock".equals(role)) {
                rockName = piece.path("card").asText(null);
            }
        }
        outletName = p.path("outlet").path("card").asText(null);
        lifeTarget = p.path("outlet").path("target_cumulative_lifegain").asInt(150);
        obligationSource = p.path("loop").path("trigger_obligations")
                .path(0).path("source").asText(null);
        tapProduces = p.path("loop").path("tap_produces").asInt(0);
        recastCost = symbolCount(p.path("loop").path("recast_cost").asText(""));
        if (engineName == null || rockName == null || outletName == null
                || obligationSource == null || tapProduces <= 0) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_abort", game.getPhaseHandler().getTurn(), seat)
                    .with("combo", comboId)
                    .with("reason", "program_malformed: engine=" + engineName
                            + " rock=" + rockName + " outlet=" + outletName
                            + " obligation=" + obligationSource
                            + " tap_produces=" + tapProduces));
        }
    }

    public boolean finished() {
        return finished;
    }

    /**
     * THE alternating obligation (the orderAndPlaySimultaneousSa seam): the
     * card the named trigger source MUST bounce in the current loop half —
     * the rock while the fodder's cast is live, the fodder while the rock's
     * recast is live — or null (setup casts keep stock trigger targeting).
     */
    public String obligedTargetForPhase(String sourceCard) {
        if (bounceTarget == null || !sourceCard.equals(obligationSource)) {
            return null;
        }
        return bounceTarget;
    }

    /** One decision per priority window; null = nothing to do this window. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!game.getStack().isEmpty()) {
            return null; // invariant 2 — casts resolve before the next act
        }
        // ---- measured verifications for the previous window's action ----
        if (pendingTap) {
            pendingTap = false;
            int pool = player.getManaPool().totalMana();
            if (pool != poolBefore + tapProduces) {
                return abort(turn, "tap_unverified: pool " + poolBefore + "->" + pool
                        + ", expected +" + tapProduces + " from '" + rockName + "'");
            }
            state = State.CAST_FODDER;
        }
        if (pendingFodder) {
            pendingFodder = false;
            bounceTarget = null;
            int pool = player.getManaPool().totalMana();
            if (!inHand(rockName)) {
                return abort(turn, "bounce_unverified: '" + rockName
                        + "' not in HAND after the fodder cast (trigger mistargeted,"
                        + " countered, or the cast never happened)");
            }
            if (AbilityResolver.findBattlefield(player, fodderName) == null) {
                return abort(turn, "fodder_never_resolved: '" + fodderName
                        + "' not on the battlefield");
            }
            if (pool != poolBefore) {
                // a {0} cast that moved the pool means a TAX effect is live,
                // and a taxed loop no longer nets what the program declares
                return abort(turn, "fodder_spend_mismatch: pool " + poolBefore + "->" + pool
                        + ", a {0} cast must move nothing");
            }
            state = State.RECAST_ROCK;
        }
        if (pendingRock) {
            pendingRock = false;
            bounceTarget = null;
            int pool = player.getManaPool().totalMana();
            Card rock = AbilityResolver.findBattlefield(player, rockName);
            if (!inHand(fodderName)) {
                return abort(turn, "bounce_unverified: '" + fodderName
                        + "' not in HAND after the rock recast");
            }
            if (rock == null) {
                return abort(turn, "rock_never_resolved: '" + rockName
                        + "' not on the battlefield after its recast");
            }
            // spend-proof, bounded: the pool may move by AT MOST the
            // declared recast cost. Less is a measured DISCOUNT — the deck's
            // own artifact-spell reducers (Etherium Sculptor / Foundry
            // Inspector / Cloud Key class) discount at payment, the
            // PR-lambda lesson's flip side — and the resolution guarantee is
            // the zone-proofs above. MORE is a tax, and a taxed recast
            // breaks the program's declared net-per-iteration math, so it
            // aborts. (The normalization half may also pay from lands with
            // a short pool — spent 0, in range.)
            int spent = poolBefore - pool;
            if (spent < 0 || spent > recastCost) {
                return abort(turn, "recast_spend_mismatch: pool " + poolBefore + "->" + pool
                        + ", spent " + spent + " outside [0, " + recastCost
                        + "] ('" + rockName + "')");
            }
            // storm observable: exactly 2 of OUR casts per iteration
            int storm = player.getSpellsCastThisTurn();
            if (storm != stormAtIterationStart + 2) {
                return abort(turn, "storm_mismatch: casts this turn "
                        + stormAtIterationStart + "->" + storm + ", expected +2");
            }
            normalizing = false;
            iterations++;
            pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                    .with("outlet", rockName).with("kind", "cast_bounce")
                    .with("iteration", iterations)
                    .with("storm", storm)
                    .with("own_life", player.getLife()));
            state = State.TAP;
        }
        // ---- SETUP: resolve the template, deploy missing pieces ----
        if (state == State.SETUP) {
            // the template piece resolves at ENTRY against the LIVE hand —
            // the compiler pattern: the program lists candidates, the runner
            // picks what is actually there; nothing there = quiet defer
            if (fodderName == null) {
                for (JsonNode piece : program.path("pieces")) {
                    if (!piece.has("template")) {
                        continue;
                    }
                    for (JsonNode cand : piece.path("resolve_from")) {
                        if (inHand(cand.asText())) {
                            fodderName = cand.asText();
                            break;
                        }
                    }
                }
                if (fodderName == null) {
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
            }
            // setup casts, idempotent: on the battlefield = done; in hand and
            // affordable = cast (verified by PRESENCE next pass, this same
            // loop); unreachable/unaffordable = quiet defer — nothing spent,
            // never a burned refire (PR-lambda)
            for (JsonNode step : program.path("setup")) {
                String card = step.path("card").asText();
                if (AbilityResolver.findBattlefield(player, card) != null) {
                    continue;
                }
                SpellAbility cast = AbilityResolver.resolveCast(player, card);
                if (cast == null) {
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
                return List.of(cast);
            }
            if (!inHand(fodderName)) {
                // present at entry, gone before the loop — intervention
                return abort(turn, "piece_lost: fodder '" + fodderName + "' left HAND");
            }
            state = State.TAP;
        }
        // ---- loop boundary: completion, plan, live preconditions ----
        if (state == State.TAP) {
            if (lifeAtPlan >= 0 && player.getLife() - lifeAtPlan >= lifeTarget) {
                finished = true;
                pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                        .with("combo", comboId)
                        .with("iterations", iterations)
                        .with("storm", player.getSpellsCastThisTurn())
                        .with("life_gained", player.getLife() - lifeAtPlan)
                        .with("own_life", player.getLife()));
                return null; // hand back — the drill machinery owns PayLife<50>
            }
            if (iterations >= ITERATION_CAP) {
                return abort(turn, "iteration_cap: " + ITERATION_CAP);
            }
            Card engine = AbilityResolver.findBattlefield(player, engineName);
            if (engine == null) {
                return abort(turn, "piece_lost: '" + engineName + "' mid-loop");
            }
            if (AbilityResolver.findBattlefield(player, outletName) == null) {
                return abort(turn, "piece_lost: outlet '" + outletName + "' mid-loop");
            }
            Card rock = AbilityResolver.findBattlefield(player, rockName);
            if (rock == null) {
                return abort(turn, "piece_lost: '" + rockName + "' mid-loop");
            }
            if (!inHand(fodderName)) {
                return abort(turn, "piece_lost: fodder '" + fodderName + "' not in HAND");
            }
            // governor: plan (or replan) from the LIVE storm count — the kth
            // cast of the turn gains k with the outlet out, so the casts
            // needed to gain the target shrink as the storm grows; measured
            // life decides completion, the plan bounds the tranche
            if (lifeAtPlan < 0 || iterations >= plannedThrough) {
                int storm = player.getSpellsCastThisTurn();
                if (lifeAtPlan < 0) {
                    lifeAtPlan = player.getLife();
                }
                int remaining = lifeTarget - (player.getLife() - lifeAtPlan);
                int needCasts = 0;
                long gain = 0;
                while (gain < remaining && needCasts < 2 * ITERATION_CAP) {
                    needCasts++;
                    gain += storm + needCasts;
                }
                int planned = Math.min((needCasts + 1) / 2, ITERATION_CAP - iterations);
                if (planned <= 0) {
                    return abort(turn, "iteration_cap: " + ITERATION_CAP
                            + " reached with " + remaining + " lifegain still needed");
                }
                plannedThrough = iterations + planned;
                tranche++;
                pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                        .with("combo", comboId)
                        .with("exit_state", "storm_lifegain_" + lifeTarget)
                        .with("need", needCasts)
                        .with("cap", ITERATION_CAP)
                        .with("planned", planned)
                        .with("tranche", tranche)
                        .with("iterations_done", iterations));
            }
            if (rock.isTapped()) {
                if (iterations == 0 && !normalizing) {
                    // tapped-rock ENTRY (it paid the outlet's setup cast, or
                    // the turn spent it earlier; Vault/Monolith never untap
                    // on their own): run the loop's second half first — the
                    // bounce is the untap. Usability invariant kept: a
                    // tapped rock is never asked to tap (CostTap would mint).
                    normalizing = true;
                    state = State.CAST_FODDER;
                } else {
                    return abort(turn, "rock_tapped_mid_loop after "
                            + iterations + " iterations");
                }
            } else {
                SpellAbility tap = bestUsableManaAbility(rock);
                if (tap == null) {
                    return abort(turn, "loop_action_unresolvable: tap on '" + rockName + "'");
                }
                poolBefore = player.getManaPool().totalMana();
                stormAtIterationStart = player.getSpellsCastThisTurn();
                bounceTarget = null;
                pendingTap = true;
                return List.of(tap);
            }
        }
        // ---- half 1: cast the fodder; the trigger must bounce the rock ----
        if (state == State.CAST_FODDER) {
            if (normalizing) {
                stormAtIterationStart = player.getSpellsCastThisTurn();
            }
            SpellAbility cast = AbilityResolver.resolveCast(player, fodderName);
            if (cast == null) {
                return abort(turn, "loop_action_unresolvable: cast '" + fodderName + "'");
            }
            poolBefore = player.getManaPool().totalMana();
            bounceTarget = rockName;
            pendingFodder = true;
            return List.of(cast);
        }
        // ---- half 2: recast the rock; the trigger must bounce the fodder ----
        if (state == State.RECAST_ROCK) {
            SpellAbility cast = AbilityResolver.resolveCast(player, rockName);
            if (cast == null) {
                return abort(turn, "loop_action_unresolvable: recast '" + rockName + "'");
            }
            poolBefore = player.getManaPool().totalMana();
            bounceTarget = fodderName;
            pendingRock = true;
            return List.of(cast);
        }
        return null;
    }

    /**
     * The rock's highest-yield mana ability that is USABLE right now —
     * called only on an untapped rock (the isTapped gate lives at the loop
     * boundary). Same hardening as the mana-loop's: spend-restricted mana
     * never funds the loop, unplayable abilities never return.
     */
    private SpellAbility bestUsableManaAbility(Card c) {
        SpellAbility best = null;
        int bestYield = -1;
        for (SpellAbility ma : c.getManaAbilities()) {
            if (ma.hasParam("RestrictValid")) {
                continue;
            }
            ma.setActivatingPlayer(player);
            if (!ma.canPlay()) {
                continue;
            }
            int y = yieldOf(ma);
            if (y > bestYield) {
                bestYield = y;
                best = ma;
            }
        }
        return best;
    }

    /** Amount as a number; variables score 0 (conservative). */
    private static int yieldOf(SpellAbility ma) {
        String amount = ma.getParam("Amount");
        if (amount == null) {
            return 1;
        }
        try {
            return Integer.parseInt(amount.trim());
        } catch (NumberFormatException variable) {
            return 0;
        }
    }

    /** Generic mana value of a brace cost string ("{2}" -> 2, "{1}" -> 1). */
    private static int symbolCount(String cost) {
        int total = 0;
        for (String sym : cost.replace("{", " ").replace("}", " ").trim().split("\\s+")) {
            if (sym.isEmpty()) {
                continue;
            }
            if (sym.chars().allMatch(Character::isDigit)) {
                total += Integer.parseInt(sym);
            } else {
                total += 1;
            }
        }
        return total;
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
                .with("combo", comboId).with("iterations", iterations)
                .with("reason", reason));
        return null;
    }
}
