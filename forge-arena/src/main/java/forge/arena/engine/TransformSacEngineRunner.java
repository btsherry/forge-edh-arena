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
 * PR (transform_sac_engine) — the NEW shape from the v1.1 whole-deck discovery
 * (Greater Good + Ojer Kaslem, rank 0.85): a LOSSLESS per-turn sacrifice value
 * engine built on a transform-return body. Sacrificing Ojer Kaslem (power 6) to
 * Greater Good draws 6 / discards 3, but his death trigger ({@code ChangesZone
 * Battlefield->Graveyard -> ChangeZone back Transformed$ True Tapped$ True})
 * returns him as the Temple of Cultivation land — and Temple's {@code {2}{G},
 * {T}} sorcery-speed flip (needs 10+ permanents, engine-enforced via IsPresent)
 * re-creates the creature to sacrifice again next turn. Net +3 cards per turn
 * for {2}{G}, zero permanent loss.
 *
 * <p>Lifecycle mirrors {@link SeedbornEngineRunner}: one engagement per own-turn
 * dispatch, gate-then-act-then-measure, silent idle (defer) on a gate miss, loud
 * abort on a broken measure. Two alternating actions across turns:
 * <ol>
 *   <li>Body face up — activate the sac outlet, STEERING the sacrifice cost to
 *       the body via the controller's pendingSacChoice hook (the
 *       DreadnoughtWindow seam); measure the hand delta (draw power − discard
 *       3, ≥ +1 or the engine is broken).</li>
 *   <li>Back face up — activate the flip ({@code {2}{G},{T}}); Forge's own
 *       IsPresent/SorcerySpeed gates make an illegal flip unresolvable, which
 *       defers quietly. The flipped body arrives tapped — irrelevant: the
 *       sacrifice is a cost, not a tap ability, and needs no sickness clearance
 *       ({@code CR 302.6} covers only the creature's own {T} abilities).</li>
 * </ol>
 */
public final class TransformSacEngineRunner {

    static final int SETTLE_GRACE_WINDOWS = 3;

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final ComboAwareLobbyPlayer.ComboAwareController controller;
    private final int seat;
    private final String comboId;

    private final String bodyCard;      // Ojer Kaslem, Deepest Growth
    private final String backFace;      // Temple of Cultivation
    private final String flipCost;      // {2}{G} ({T} is part of the ability cost)
    private final String sacOutletCard; // Greater Good
    private final String sacOutletCost; // Sac<1/Creature>
    private final int perTurnCap;

    private boolean finished;
    private boolean planned;
    private int cyclesDone;
    private boolean pendingMeasure;
    private long handBefore = -1;
    private int settleWait;

    TransformSacEngineRunner(Game game, Player player, ComboPilot pilot,
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
        JsonNode e = p != null ? p.path("engine") : null;
        this.bodyCard = e != null ? e.path("body").asText(null) : null;
        this.backFace = e != null ? e.path("back_face").asText(null) : null;
        this.flipCost = e != null ? e.path("flip_cost").asText("{2}{G}") : "{2}{G}";
        JsonNode sac = e != null ? e.path("sac_outlet") : null;
        this.sacOutletCard = sac != null ? sac.path("card").asText(null) : null;
        this.sacOutletCost = sac != null ? sac.path("cost").asText("Sac") : "Sac";
        this.perTurnCap = e != null ? e.path("per_turn_cap").asInt(1) : 1;
        if (bodyCard == null || backFace == null || sacOutletCard == null) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_abort", game.getPhaseHandler().getTurn(), seat)
                    .with("combo", comboId).with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    public boolean isPiece(String cardName) {
        return cardName.equals(bodyCard) || cardName.equals(backFace)
                || cardName.equals(sacOutletCard);
    }

    /** One action per priority window. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!game.getStack().isEmpty()) {
            return null;
        }

        if (pendingMeasure) {
            long now = player.getCardsIn(ZoneType.Hand).size();
            // draw(power) − discard 3 must net at least +1 (Ojer nets +3); the
            // transform-return is the engine's whole point — verify it too.
            if (now >= handBefore + 1 && faceUp(backFace) != null) {
                pendingMeasure = false;
                settleWait = 0;
                cyclesDone++;
                pilot.observe(ArenaEvent.of("outlet_drill", turn, seat)
                        .with("outlet", sacOutletCard).with("kind", "transform_sac")
                        .with("iteration", cyclesDone)
                        .with("hand", now).with("own_life", player.getLife()));
            } else if (settleWait < SETTLE_GRACE_WINDOWS) {
                settleWait++;
                return null;
            } else {
                return abort(turn, "engine_broken: hand " + handBefore + "->" + now
                        + ", back face " + (faceUp(backFace) != null ? "returned" : "MISSING")
                        + " after sac " + (cyclesDone + 1));
            }
        }

        if (cyclesDone >= perTurnCap) {
            // engine turn done — hand back; the dispatch re-engages next turn
            finished = true;
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", cyclesDone)
                    .with("exit", "per_turn_cap"));
            return null;
        }

        Card outlet = AbilityResolver.findBattlefield(player, sacOutletCard);
        if (outlet == null) {
            return abort(turn, "piece_lost: '" + sacOutletCard + "'");
        }
        if (!planned) {
            planned = true;
            pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                    .with("combo", comboId).with("exit_state", "cards_per_turn_engine")
                    .with("body", bodyCard).with("sac_outlet", sacOutletCard)
                    .with("tranche", 1).with("iterations_done", cyclesDone));
        }

        Card body = faceUp(bodyCard);
        if (body != null) {
            // creature face up — sacrifice it to the outlet (steered)
            SpellAbility sacSa = AbilityResolver.resolve(
                    player, sacOutletCard, sacOutletCost, List.of());
            if (sacSa == null || !forge.ai.ComputerUtilCost.canPayCost(sacSa, player, false)) {
                pilot.observe(ArenaEvent.of("program_deferred", turn, seat)
                        .with("combo", comboId).with("reason", "sac_unresolvable")
                        .with("resolvable", sacSa != null));
                finished = true;
                pilot.programDeferred(comboId);
                return null;
            }
            if (controller != null) {
                controller.setPendingSacChoice(bodyCard);
            }
            handBefore = player.getCardsIn(ZoneType.Hand).size();
            pendingMeasure = true;
            return List.of(sacSa);
        }

        Card temple = faceUp(backFace);
        if (temple != null) {
            // land face up — flip it back to the creature ({2}{G},{T}; the
            // 10-permanent and sorcery-speed gates are Forge-enforced, so an
            // illegal flip is simply unresolvable here -> quiet defer)
            SpellAbility flip = AbilityResolver.resolve(player, backFace, flipCost, List.of());
            if (flip == null || !forge.ai.ComputerUtilCost.canPayCost(flip, player, false)) {
                pilot.observe(ArenaEvent.of("program_deferred", turn, seat)
                        .with("combo", comboId).with("reason", "flip_unresolvable")
                        .with("resolvable", flip != null));
                finished = true;
                pilot.programDeferred(comboId);
                return null;
            }
            return List.of(flip);
        }

        // neither face on the battlefield — the body is in hand/graveyard/exile;
        // casting him is the pilot's ordinary job, not this engine's
        pilot.observe(ArenaEvent.of("program_deferred", turn, seat)
                .with("combo", comboId).with("reason", "body_unavailable"));
        finished = true;
        pilot.programDeferred(comboId);
        return null;
    }

    /** Find OUR battlefield card currently showing the given face name. */
    private Card faceUp(String faceName) {
        if (faceName == null) {
            return null;
        }
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (faceName.equals(c.getName())) {
                return c;
            }
        }
        return null;
    }

    private List<SpellAbility> abort(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("program_abort", turn, seat)
                .with("combo", comboId).with("iterations", cyclesDone).with("reason", reason));
        return null;
    }
}
