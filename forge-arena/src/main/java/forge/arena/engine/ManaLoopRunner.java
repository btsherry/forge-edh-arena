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
 * PR-lambda: the mana-loop interpreter (program_class: mana_loop) — the
 * second program shape, compiled for Power Artifact + Basalt Monolith and
 * anything with the same skeleton: SETUP casts (aura pre-targeted at its
 * declared host), a LOOP whose pairs of activations are verified by
 * MEASURED mana-pool growth, then a SINK stage spending the banked pool,
 * then a hand-back so stock converts the downstream (Urza's MayPlay storm
 * into Aetherflux).
 *
 * <p>The five invariants, mana-loop form: preconditions vs LIVE state
 * including AURA ATTACHMENT (a Power Artifact on the wrong artifact never
 * loops — verified, not assumed); one action per window; post-pair measured
 * pool delta (+2 or abort); costs from the program's structured hints — the
 * untap asks for the REAL scripted {3}, Power Artifact discounts at payment
 * (the fictional-{1} hunt hid this combo for a phase); everything on the
 * live game. Phase-bound: the pool dies at phase end, so loop + sink run
 * inside one main phase and a measured pool collapse aborts.
 */
public final class ManaLoopRunner {

    static final int ITERATION_CAP = 400;

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String comboId;
    private final JsonNode program;

    private enum State { SETUP, LOOP_TAP, LOOP_UNTAP, SINK }

    private State state = State.SETUP;
    private boolean finished;
    private int iterations;
    private int sinksDone;
    private int plannedSinks = -1;
    private int poolAtPairStart = -1;
    /** A pair/sink counts only when MEASURED complete next window (panel:
     *  counting at SA-return scored countered untaps as done, and the
     *  phantom pair chained straight into the illegal tapped-tap mint). */
    private boolean pendingPair;
    private boolean pendingSink;
    private int libraryAtSink = -1;
    /** PR-xi storm (rollback: sink.storm_mode="stock" in the program JSON —
     *  reverts to bank=sinks*5 and hand-back, the exact pre-storm shape). */
    private boolean stormEnabled;
    private java.util.Set<Integer> exileIdsAtSink = java.util.Set.of();
    private int pendingStormCardId = -1;
    private String pendingStormCardName;
    private int stormCasts;
    private int stormSkips;
    private int normalizeAttempts;
    /** float_then_copy: pool at the iteration's first float action. */
    private int poolAtIterStart = -1;
    private boolean iterationOpen;
    /** Pool right after the floats, before the {2} activation — the spend
     *  proof (reviewer: a FAILED play left floats-grown pool passing the
     *  net check, scoring a phantom iteration). */
    private int poolAtActivation = -1;
    /** Float progress guard (reviewer: an unpayable float SA returned
     *  verbatim every window livelocks the seat). */
    private int lastFloatPool = -1;
    private int floatStalls;
    /** Imprint choice for the cast just returned; controller consumes it. */
    private String pendingImprint;

    public String pendingImprint() {
        String out = pendingImprint;
        pendingImprint = null;
        return out;
    }

    ManaLoopRunner(Game game, Player player, ComboPilot pilot, int seat, String programPath) {
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
        }
    }

    public boolean finished() {
        return finished;
    }

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

    /** One decision per priority window. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!game.getStack().isEmpty()) {
            return null; // invariant 2 — casts resolve before the next act
        }
        if (state == State.SETUP) {
            for (JsonNode step : program.path("setup")) {
                String card = step.path("card").asText();
                if (AbilityResolver.findBattlefield(player, card) != null) {
                    continue;
                }
                String imprint = step.path("imprint").asText(null);
                if (imprint != null && !inHand(imprint)) {
                    // the imprint trigger takes its card from HAND — casting
                    // the Scepter without it is a dead Scepter; defer
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
                SpellAbility cast = AbilityResolver.resolveCast(player, card);
                if (cast == null) {
                    // panel: an unaffordable/unreachable setup cast spent
                    // NOTHING — defer quietly (retry next turn), never abort
                    // and burn the refire lockout in a phantom state
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
                if (imprint != null) {
                    pendingImprint = imprint; // controller arms pendingChoice
                }
                String attachTo = step.path("target").asText(null);
                if (attachTo != null && cast.usesTargeting()) {
                    Card host = AbilityResolver.findBattlefield(player, attachTo);
                    if (host == null || !cast.canTarget(host)) {
                        return abort(turn, "attach_host_unavailable: '" + attachTo + "'");
                    }
                    cast.resetTargets();
                    cast.getTargets().add(host);
                }
                return List.of(cast);
            }
            // preconditions, incl. ATTACHMENT — verified, never assumed
            for (JsonNode pre : program.path("preconditions")) {
                String check = pre.path("check").asText();
                if ("on_battlefield".equals(check)
                        && AbilityResolver.findBattlefield(player, pre.path("card").asText()) == null) {
                    return abort(turn, "piece_lost: '" + pre.path("card").asText() + "'");
                }
                if ("attached".equals(check) && !attached(pre.path("card").asText(),
                        pre.path("host").asText())) {
                    return abort(turn, "piece_misattached: '" + pre.path("card").asText()
                            + "' not on '" + pre.path("host").asText() + "'");
                }
                if ("imprinted".equals(check) && !imprinted(pre.path("card").asText(),
                        pre.path("host").asText())) {
                    return abort(turn, "not_imprinted: '" + pre.path("card").asText()
                            + "' not on '" + pre.path("host").asText() + "'");
                }
                if ("artifact_mana_production_at_least".equals(check)
                        && artifactManaProduction(false) < pre.path("n").asInt(3)) {
                    // the secondary requirement is a WAIT, not a failure —
                    // more rocks arrive; defer for a later refire
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
            }
            // governor: bank exactly what the sinks will spend, bounded by
            // the declared library floor (each sink exiles our top card)
            int perSink = program.path("sink").path("per_activation_pool").asInt(5);
            stormEnabled = "program_casts".equals(
                    program.path("sink").path("storm_mode").asText("stock"));
            if (stormEnabled) {
                // nu30 root cause: MayPlay is not free — bank a casting
                // reserve per sink or the exiles just sit there
                perSink += program.path("sink").path("storm_reserve_per_sink").asInt(4);
            }
            int floor = program.path("self_consumption").path("floor").asInt(5);
            int library = player.getCardsIn(ZoneType.Library).size();
            plannedSinks = Math.min(8, Math.max(0, library - floor));
            if (plannedSinks == 0) {
                return abort(turn, "self_floor: library " + library + " at floor " + floor);
            }
            pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                    .with("combo", comboId)
                    .with("exit_state", "pool_banked_then_sunk")
                    .with("need", plannedSinks * perSink)
                    .with("cap", "library-" + floor)
                    .with("planned", plannedSinks)
                    .with("tranche", 1)
                    .with("iterations_done", 0));
            state = State.LOOP_TAP;
        }
        if ((state == State.LOOP_TAP || state == State.LOOP_UNTAP)
                && "float_then_copy".equals(program.path("loop").path("shape").asText(""))) {
            int perSink = bankPerSink();
            int netMin = program.path("loop").path("expected_net_min_per_iteration").asInt(1);
            int pool = player.getManaPool().totalMana();
            String scepterCard = program.path("loop").path("activate").path("card").asText();
            Card scepter = AbilityResolver.findBattlefield(player, scepterCard);
            if (scepter == null) {
                return abort(turn, "piece_lost: '" + scepterCard + "' mid-loop");
            }
            if (pendingPair) {
                // MEASURED iteration completion, spend-proof included: the
                // {2} left the pool (pool == poolAtActivation - 2 — a play
                // that failed to happen leaves it untouched) and the copy
                // RESOLVED (the Reversal untapped the scepter) and the net
                // over the iteration start held
                if (pool >= poolAtActivation) {
                    return abort(turn, "activation_never_played: pool "
                            + poolAtActivation + " unchanged after the {2}");
                }
                if (scepter.isTapped() || pool < poolAtIterStart + netMin) {
                    return abort(turn, "iteration_incomplete: scepter "
                            + (scepter.isTapped() ? "TAPPED" : "untapped")
                            + ", pool " + poolAtIterStart + "->" + pool
                            + " (net_min " + netMin + ") after iteration "
                            + (iterations + 1));
                }
                pendingPair = false;
                iterationOpen = false;
                iterations++;
                pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                        .with("outlet", scepterCard).with("kind", "copy_iteration")
                        .with("iteration", iterations)
                        .with("own_life", player.getLife()));
            }
            if (pool >= plannedSinks * perSink) {
                state = State.SINK;
            } else if (iterations >= ITERATION_CAP) {
                return abort(turn, "iteration_cap: " + ITERATION_CAP);
            } else {
                // tapped-scepter check FIRST (reviewer: floating every rock
                // and THEN discovering the defer banked a phase-dying pool
                // for nothing)
                if (scepter.isTapped()) {
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
                }
                // FLOAT: one untapped artifact mana ability per window,
                // highest USABLE yield first (PR-60) — legality-gated
                // (canPlay: Metalcraft-off Mox Opal never floats) and
                // restriction-aware (Throne of Eldraine's spell-only mana
                // cannot pay the {2} or the {5} and never enters the bank)
                SpellAbility floatAct = bestUntappedArtifactMana();
                if (floatAct != null) {
                    if (!iterationOpen) {
                        poolAtIterStart = pool;
                        iterationOpen = true;
                    }
                    if (pool == lastFloatPool && ++floatStalls >= 3) {
                        return abort(turn, "float_stalled: pool " + pool
                                + " unchanged across " + floatStalls + " floats");
                    }
                    if (pool != lastFloatPool) {
                        floatStalls = 0;
                    }
                    lastFloatPool = pool;
                    return List.of(floatAct);
                }
                if (!iterationOpen) {
                    poolAtIterStart = pool;
                    iterationOpen = true;
                }
                if (pool < 2) {
                    return abort(turn, "float_underfunded: pool " + pool
                            + " < {2} with no untapped artifact mana left");
                }
                SpellAbility act = AbilityResolver.resolve(player, scepterCard,
                        program.path("loop").path("activate").path("cost").asText("{2}"),
                        List.of());
                if (act == null) {
                    return abort(turn, "loop_action_unresolvable: '" + scepterCard + "'");
                }
                poolAtActivation = pool;
                pendingPair = true;
                return List.of(act);
            }
        }
        if (state == State.LOOP_TAP || state == State.LOOP_UNTAP) {
            int perSink = bankPerSink();
            int pool = player.getManaPool().totalMana();
            JsonNode body = program.path("loop").path("body");
            String engineCard = body.path(0).path("card").asText();
            Card engine = AbilityResolver.findBattlefield(player, engineCard);
            if (engine == null) {
                return abort(turn, "piece_lost: '" + engineCard + "' mid-loop");
            }
            if (state == State.LOOP_TAP && pendingPair) {
                // MEASURED pair completion: the untap RESOLVED (host is
                // untapped) and the pool grew. A countered untap leaves the
                // host tapped at exactly poolAtPairStart+2 — the numeric
                // check alone cannot see it (panel).
                if (engine.isTapped() || pool < poolAtPairStart + 2) {
                    return abort(turn, "pair_incomplete: host "
                            + (engine.isTapped() ? "TAPPED" : "untapped")
                            + ", pool " + poolAtPairStart + "->" + pool
                            + " after pair " + (iterations + 1));
                }
                pendingPair = false;
                iterations++;
                pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                        .with("outlet", engineCard).with("kind", "mana_pair")
                        .with("iteration", iterations)
                        .with("own_life", player.getLife()));
            }
            if (pool >= plannedSinks * perSink) {
                state = State.SINK;
            } else if (iterations >= ITERATION_CAP) {
                return abort(turn, "iteration_cap: " + ITERATION_CAP);
            } else if (state == State.LOOP_TAP) {
                // LEGALITY, not just resolvability: Forge's AI payment path
                // 'pays' {T} on an already-tapped host and mints the mana
                // anyway (CostTap.payAsDecided returns true on a no-op tap —
                // panel, traced to source). A tapped engine first gets a
                // real, paid untap; only an UNTAPPED engine may tap.
                if (engine.isTapped()) {
                    if (normalizeAttempts >= 2) {
                        return abort(turn, "engine_stuck_tapped after "
                                + normalizeAttempts + " untap attempts");
                    }
                    SpellAbility untap = AbilityResolver.resolve(player,
                            engineCard, body.path(1).path("cost").asText(), List.of());
                    if (untap == null) {
                        return abort(turn, "loop_action_unresolvable: normalize untap");
                    }
                    normalizeAttempts++;
                    return List.of(untap);
                }
                normalizeAttempts = 0;
                SpellAbility tap = AbilityResolver.resolve(player,
                        engineCard, body.path(0).path("cost").asText(), List.of());
                if (tap == null) {
                    return abort(turn, "loop_action_unresolvable: '" + engineCard
                            + "' cost " + body.path(0).path("cost").asText());
                }
                poolAtPairStart = pool;
                state = State.LOOP_UNTAP;
                return List.of(tap);
            } else {
                SpellAbility untap = AbilityResolver.resolve(player,
                        engineCard, body.path(1).path("cost").asText(), List.of());
                if (untap == null) {
                    return abort(turn, "loop_action_unresolvable: '" + engineCard
                            + "' cost " + body.path(1).path("cost").asText());
                }
                pendingPair = true;
                state = State.LOOP_TAP;
                return List.of(untap);
            }
        }
        if (state == State.SINK) {
            int perSink = program.path("sink").path("per_activation_pool").asInt(5);
            // storm verification: the exiled card we chose to cast must have
            // LEFT exile (measured); a card still sitting there means the
            // cast never happened — recorded as a skip, never a phantom
            if (pendingStormCardId >= 0) {
                boolean gone = true;
                for (Card c : player.getCardsIn(ZoneType.Exile)) {
                    if (c.getId() == pendingStormCardId) {
                        gone = false;
                        break;
                    }
                }
                if (gone) {
                    stormCasts++;
                    pilot.observe(ArenaEvent.of("storm_cast", turn, seat)
                            .with("combo", comboId).with("card", pendingStormCardName));
                } else {
                    stormSkips++;
                }
                pendingStormCardId = -1;
                pendingStormCardName = null;
            }
            if (pendingSink) {
                // MEASURED sink completion: Urza's {5} exiles our top card,
                // so the library must have shrunk by one (a countered sink
                // leaves it unchanged with the {5} already spent — panel)
                pendingSink = false;
                if (player.getCardsIn(ZoneType.Library).size() < libraryAtSink) {
                    sinksDone++;
                    if (stormEnabled) {
                        // the card this sink just exiled: cast it NOW while
                        // the reserve is in the pool. Forge decides legality
                        // and affordability; we only choose the intent.
                        SpellAbility stormCast = playableFromNewExile();
                        if (stormCast != null) {
                            pendingStormCardId = stormCast.getHostCard().getId();
                            pendingStormCardName = stormCast.getHostCard().getName();
                            return List.of(stormCast);
                        }
                        stormSkips++;
                    }
                } else {
                    return abort(turn, "sink_never_resolved after " + sinksDone
                            + " completed sinks");
                }
            }
            if (sinksDone >= plannedSinks
                    || player.getManaPool().totalMana() < perSink) {
                finished = true;
                pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                        .with("combo", comboId)
                        .with("iterations", iterations)
                        .with("sinks", sinksDone)
                        .with("storm_casts", stormCasts)
                        .with("storm_skips", stormSkips)
                        .with("pool_remaining", player.getManaPool().totalMana()));
                return null; // hand back (storm handled per storm_mode)
            }
            JsonNode sink = program.path("sink");
            SpellAbility act = AbilityResolver.resolve(player,
                    sink.path("card").asText(), sink.path("cost").asText(), List.of());
            if (act == null) {
                return abort(turn, "sink_unresolvable: '" + sink.path("card").asText() + "'");
            }
            libraryAtSink = player.getCardsIn(ZoneType.Library).size();
            java.util.Set<Integer> ids = new java.util.HashSet<>();
            for (Card c : player.getCardsIn(ZoneType.Exile)) {
                ids.add(c.getId());
            }
            exileIdsAtSink = ids;
            pendingSink = true;
            return List.of(act);
        }
        return null;
    }

    /** perSink plus the storm reserve when the program storms itself. */
    private int bankPerSink() {
        int perSink = program.path("sink").path("per_activation_pool").asInt(5);
        if ("program_casts".equals(program.path("sink").path("storm_mode").asText("stock"))) {
            perSink += program.path("sink").path("storm_reserve_per_sink").asInt(4);
        }
        return perSink;
    }

    /**
     * The spell this sink just exiled, IF Forge will let us cast it right
     * now — getAllPossibleAbilities carries the MayPlay grant, canPayCost
     * the affordability. Null (a land, wrong timing, unaffordable) means an
     * honest skip: the exile stays for stock to try after hand-back.
     */
    private SpellAbility playableFromNewExile() {
        for (Card c : player.getCardsIn(ZoneType.Exile)) {
            if (exileIdsAtSink.contains(c.getId())) {
                continue; // was already there before this sink
            }
            for (SpellAbility sa : c.getAllPossibleAbilities(player, true)) {
                if (!sa.isSpell()) {
                    continue;
                }
                sa.setActivatingPlayer(player);
                if (forge.ai.ComputerUtilCost.canPayCost(sa, player, false)) {
                    return sa;
                }
            }
        }
        return null;
    }

    private boolean inHand(String cardName) {
        for (Card c : player.getCardsIn(ZoneType.Hand)) {
            if (c.getName().equals(cardName)) {
                return true;
            }
        }
        return false;
    }

    private boolean imprinted(String cardName, String hostName) {
        Card host = AbilityResolver.findBattlefield(player, hostName);
        if (host == null) {
            return false;
        }
        for (Card imp : host.getImprintedCards()) {
            if (imp.getName().equals(cardName)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Total mana the untapped, USABLE artifact sources can produce right
     * now. Reviewer-hardened: skips artifact LANDS (the Reversal untaps
     * nonland only, so their float never recurs), spend-restricted mana
     * (Throne of Eldraine's RestrictValid — the PR-B lesson, runner form),
     * unplayable abilities (Metalcraft-off, unimprinted Chrome Mox), and
     * scores Amount$ X as 0 for the GATE (underestimate is safe: it defers).
     */
    private int artifactManaProduction(boolean unused) {
        int total = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            SpellAbility usable = bestUsableManaAbility(c);
            if (usable != null) {
                total += yieldOf(usable);
            }
        }
        return total;
    }

    /** The single best usable float, or null when the float is done. */
    private SpellAbility bestUntappedArtifactMana() {
        SpellAbility best = null;
        int bestYield = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            SpellAbility sa = bestUsableManaAbility(c);
            if (sa != null && yieldOf(sa) > bestYield) {
                bestYield = yieldOf(sa);
                best = sa;
            }
        }
        return best;
    }

    /**
     * The card's highest-yield mana ability that is actually USABLE for the
     * loop — the ABILITY is returned, never getFirst() (the PR-60 wrong-half
     * class the reviewer flagged latent here).
     */
    private SpellAbility bestUsableManaAbility(Card c) {
        if (!c.isArtifact() || c.isLand() || c.isTapped()
                || c.getManaAbilities().isEmpty()) {
            return null;
        }
        SpellAbility best = null;
        int bestYield = 0;
        for (SpellAbility ma : c.getManaAbilities()) {
            if (ma.hasParam("RestrictValid")) {
                continue; // spell-only mana cannot pay the {2} or the {5}
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

    /** Amount as a number; X and other variables score 0 (conservative). */
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

    private boolean attached(String auraName, String hostName) {
        Card host = AbilityResolver.findBattlefield(player, hostName);
        if (host == null) {
            return false;
        }
        for (Card att : host.getAttachedCards()) {
            if (att.getName().equals(auraName)) {
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
