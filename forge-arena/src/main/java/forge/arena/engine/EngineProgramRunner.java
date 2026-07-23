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
 * PR-kappa: one CYCLE of a compiled engine program (arena.engine-program/1)
 * — a background card-advantage loop with no exit state. For Land Tax +
 * Scroll Rack: gate on the LOAD-BEARING interaction (an opponent must have
 * more lands than us, so the Tax trigger will shuffle away whatever the
 * Rack puts on top, at our next upkeep, BEFORE our draw), then activate the
 * Rack once, let the controller's chooseCardsForZoneChange callback exile
 * the excess basics, and MEASURE the swap after the stack empties.
 *
 * <p>One runner instance per cycle attempt, PairingRunner-style: it owns
 * windows only across its own resolution, then hands the seat back. A
 * failed gate is a silent idle (engines wait; fresh evaluation next turn);
 * a failed resolution or measurement aborts loudly.
 */
public final class EngineProgramRunner {

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String engineId;
    private final String rackCard;
    private final String rackCost;
    private final List<String> pieces;

    private boolean finished;
    private boolean activated;
    private int handBefore = -1;
    private int swapped = -1;

    EngineProgramRunner(Game game, Player player, ComboPilot pilot, int seat,
            String programPath) {
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
        this.engineId = p != null ? p.path("engine_id").asText("?") : "?";
        this.rackCard = p != null
                ? p.path("cycle").path("action").path("activate").asText(null) : null;
        this.rackCost = p != null
                ? p.path("cycle").path("action").path("cost").asText("{1}") : "{1}";
        java.util.List<String> pc = new java.util.ArrayList<>();
        if (p != null) {
            for (JsonNode piece : p.path("pieces")) {
                pc.add(piece.path("card").asText());
            }
        }
        this.pieces = pc;
        if (rackCard == null || pieces.isEmpty()) {
            finished = true;
            pilot.observe(ArenaEvent.of("engine_abort",
                    game.getPhaseHandler().getTurn(), seat)
                    .with("engine", engineId)
                    .with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    public String rackCard() {
        return rackCard;
    }

    /** The exile chooser reports each card as it hands one over (the AI
     *  path is ONE AT A TIME — allowMultiSelect excludes AI controllers,
     *  so the multi-select callback never fires; the PR-72 lesson found
     *  again by the first diagnostic run). */
    public void recordExiled() {
        swapped = Math.max(0, swapped) + 1;
    }

    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!activated) {
            // gates, all against the LIVE game; any miss is a silent idle
            for (String piece : pieces) {
                if (AbilityResolver.findBattlefield(player, piece) == null) {
                    finished = true;
                    return null;
                }
            }
            int excess = excessBasicsInHand();
            if (!shuffleAvailable() || excess < 1
                    // never activate into a library shorter than the swap —
                    // the exiled basics would strand on top as real card loss
                    || player.getCardsIn(ZoneType.Library).size() < excess) {
                finished = true;
                return null;
            }
            SpellAbility rack = AbilityResolver.resolve(player, rackCard, rackCost, List.of());
            // the program's fourth gate, actually IMPLEMENTED (panel: resolve()
            // does not check playability, so a tapped or mana-short rack came
            // back non-null, failed at payment, and false-aborted as
            // swap_mismatch): host untapped + cost payable, else silent idle
            if (rack == null || rack.getHostCard() == null || rack.getHostCard().isTapped()
                    || !forge.ai.ComputerUtilCost.canPayCost(rack, player, false)) {
                finished = true;
                return null;
            }
            handBefore = player.getCardsIn(ZoneType.Hand).size();
            swapped = 0;
            activated = true;
            return List.of(rack);
        }
        if (!game.getStack().isEmpty()) {
            return null;
        }
        finished = true;
        int handAfter = player.getCardsIn(ZoneType.Hand).size();
        if (handAfter == handBefore && swapped >= 1) {
            pilot.observe(ArenaEvent.of("engine_cycle", turn, seat)
                    .with("engine", engineId).with("swapped", swapped));
        } else if (swapped == 0) {
            // with playability gated above, a zero-swap resolution means the
            // activation never resolved (countered, or a response emptied the
            // exile choice) — name it honestly, not as a swap mismatch
            pilot.observe(ArenaEvent.of("engine_abort", turn, seat)
                    .with("engine", engineId)
                    .with("reason", "activation_never_resolved"));
        } else {
            pilot.observe(ArenaEvent.of("engine_abort", turn, seat)
                    .with("engine", engineId)
                    .with("reason", "cycle_disrupted: hand " + handBefore + "->" + handAfter
                            + " with " + swapped + " exiled (interaction mid-cycle)"));
        }
        return null;
    }

    /**
     * The load-bearing gate: the Rack's put-back only becomes card advantage
     * if the Tax trigger will SHUFFLE it away at our next upkeep — which
     * requires an opponent to control more lands than we do.
     */
    private boolean shuffleAvailable() {
        int ours = player.getLandsInPlay().size();
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()
                    && other.getLandsInPlay().size() > ours) {
                return true;
            }
        }
        return false;
    }

    /** Basic lands in hand beyond the one held for the land drop. */
    private int excessBasicsInHand() {
        int basics = 0;
        for (Card c : player.getCardsIn(ZoneType.Hand)) {
            if (c.isBasicLand()) {
                basics++;
            }
        }
        return basics - 1;
    }
}
