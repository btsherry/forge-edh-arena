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
    private int normalizeAttempts;

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
                SpellAbility cast = AbilityResolver.resolveCast(player, card);
                if (cast == null) {
                    // panel: an unaffordable/unreachable setup cast spent
                    // NOTHING — defer quietly (retry next turn), never abort
                    // and burn the refire lockout in a phantom state
                    finished = true;
                    pilot.programDeferred(comboId);
                    return null;
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
            }
            // governor: bank exactly what the sinks will spend, bounded by
            // the declared library floor (each sink exiles our top card)
            int perSink = program.path("sink").path("per_activation_pool").asInt(5);
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
        if (state == State.LOOP_TAP || state == State.LOOP_UNTAP) {
            int perSink = program.path("sink").path("per_activation_pool").asInt(5);
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
            if (pendingSink) {
                // MEASURED sink completion: Urza's {5} exiles our top card,
                // so the library must have shrunk by one (a countered sink
                // leaves it unchanged with the {5} already spent — panel)
                pendingSink = false;
                if (player.getCardsIn(ZoneType.Library).size() < libraryAtSink) {
                    sinksDone++;
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
                        .with("pool_remaining", player.getManaPool().totalMana()));
                return null; // hand back — stock storms the MayPlay exiles
            }
            JsonNode sink = program.path("sink");
            SpellAbility act = AbilityResolver.resolve(player,
                    sink.path("card").asText(), sink.path("cost").asText(), List.of());
            if (act == null) {
                return abort(turn, "sink_unresolvable: '" + sink.path("card").asText() + "'");
            }
            libraryAtSink = player.getCardsIn(ZoneType.Library).size();
            pendingSink = true;
            return List.of(act);
        }
        return null;
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
