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
 * PR (seedborn_engine) — the NEW shape from the whole-deck discovery run: a
 * MULTI-TURN mana/value engine anchored on Seedborn Muse. Seedborn is a static
 * ({@code S:Mode$ UntapOtherPlayer | ValidCard$ Permanent.YouCtrl}) that untaps
 * all your permanents during EACH other player's untap step — so a producer or
 * a sink can be activated far more often than once a turn. Two modes, both
 * bounded per turn and MEASURED, so the runner never hogs priority:
 *
 * <ul>
 *   <li><b>activated_sink</b> — repeatedly activate an on-board sink funded by
 *       the extra untaps (Nylea, Keen-Eyed's {2}{G} dig), measured by hand
 *       growth. No exit state (card-advantage engine, EngineProgramRunner's
 *       class): cycle for value, hand back, re-engage next window.</li>
 *   <li><b>omnath_accumulate</b> — tap the producer to float green, retained
 *       across turns by Omnath, Locus of Mana ({@code S:Mode$ UnspentMana |
 *       ManaType$ Green}); Omnath grows +1/+1 per unspent green until his power
 *       clears a table and he swings. Measured by Omnath's net power; exits
 *       omnath_lethal, handing to combat.</li>
 * </ul>
 *
 * <p>Lifecycle mirrors EngineProgramRunner: one engagement per own-turn
 * dispatch, gate-then-act-then-measure, silent idle on a gate miss, loud abort
 * on a broken measure. It finishes after {@code per_turn_cap} cycles and
 * re-engages next dispatch — cross-turn accumulation is Omnath's real
 * retention, not a runner that never yields.
 *
 * <p>KNOWN v1 LIMITS (for the review pass, documented not hidden): (1) the
 * engine engages on the pilot's OWN turns; fully exploiting Seedborn's
 * opponent-turn untaps needs the pilot to re-dispatch outside its MAIN1
 * entry window, which v1 does not do — Seedborn is still the load-bearing
 * gate (the combo requires it) and accelerates within-turn throughput. (2)
 * omnath_accumulate assumes the producer's yield banks GREEN; a producer that
 * makes "any" colour (Selvala) needs the green-steering the mana loop uses,
 * wired here only for native-green producers (Gaea's Cradle) in v1.
 */
public final class SeedbornEngineRunner {

    static final int SETTLE_GRACE_WINDOWS = 3;
    static final int DEFAULT_PER_TURN_CAP = 8;

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String comboId;

    private final String untapper;         // Seedborn Muse — the static gate
    private final String producerCard;
    private final String producerCost;
    private final String retainer;          // Omnath — omnath_accumulate
    private final String sinkCard;          // Nylea — activated_sink
    private final String sinkCost;
    private final String mode;              // activated_sink | omnath_accumulate
    private final String measure;           // hand_size | omnath_power | pool_green
    private final int perTurnCap;

    private boolean finished;
    private boolean planned;
    private int cyclesDone;
    private boolean pendingMeasure;
    private long measureBefore = -1;
    private int settleWait;

    SeedbornEngineRunner(Game game, Player player, ComboPilot pilot, int seat, String programPath) {
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
        this.comboId = p != null ? p.path("combo_id").asText("?") : "?";
        JsonNode e = p != null ? p.path("engine") : null;
        this.untapper = e != null ? e.path("untapper").asText("Seedborn Muse") : "Seedborn Muse";
        JsonNode prod = e != null ? e.path("producer") : null;
        this.producerCard = prod != null ? prod.path("card").asText(null) : null;
        this.producerCost = prod != null ? prod.path("activate_cost").asText("{T}") : "{T}";
        this.retainer = e != null ? e.path("retainer").asText(null) : null;
        JsonNode sink = e != null ? e.path("sink") : null;
        this.sinkCard = sink != null ? sink.path("card").asText(null) : null;
        this.sinkCost = sink != null ? sink.path("cost").asText("{2}{G}") : "{2}{G}";
        this.mode = e != null ? e.path("mode").asText("activated_sink") : "activated_sink";
        this.measure = e != null ? e.path("measure").asText("hand_size") : "hand_size";
        this.perTurnCap = e != null ? e.path("per_turn_cap").asInt(DEFAULT_PER_TURN_CAP) : DEFAULT_PER_TURN_CAP;
        boolean sinkMode = "activated_sink".equals(mode);
        if (untapper == null || (sinkMode ? sinkCard == null : producerCard == null)) {
            finished = true;
            pilot.observe(ArenaEvent.of("engine_abort", game.getPhaseHandler().getTurn(), seat)
                    .with("engine", comboId).with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    public boolean isPiece(String cardName) {
        return cardName.equals(untapper) || cardName.equals(producerCard)
                || cardName.equals(sinkCard) || cardName.equals(retainer);
    }

    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (!game.getStack().isEmpty()) {
            return null; // one activation at a time, resolve before the next
        }

        // verify the previous cycle's MEASURED delta
        if (pendingMeasure) {
            long now = measureValue();
            if (now > measureBefore) {
                pendingMeasure = false;
                settleWait = 0;
                cyclesDone++;
                pilot.observe(ArenaEvent.of("engine_cycle", turn, seat)
                        .with("engine", comboId).with("mode", mode)
                        .with("measure", measure).with("value", now)
                        .with("cycle", cyclesDone));
            } else if (settleWait < SETTLE_GRACE_WINDOWS) {
                settleWait++;
                return null;
            } else {
                return abort(turn, "engine_no_delta: " + measure + " "
                        + measureBefore + "->" + now + " after cycle " + (cyclesDone + 1));
            }
        }

        // gate vs LIVE state — a miss is a silent idle (the engine waits)
        if (AbilityResolver.findBattlefield(player, untapper) == null) {
            finished = true;
            return null;
        }
        boolean accumulate = "omnath_accumulate".equals(mode);
        String actor = accumulate ? producerCard : sinkCard;
        if (AbilityResolver.findBattlefield(player, actor) == null
                || (accumulate && retainer != null
                        && AbilityResolver.findBattlefield(player, retainer) == null)) {
            finished = true;
            return null;
        }

        if (!planned) {
            planned = true;
            pilot.observe(ArenaEvent.of("governor_plan", turn, seat)
                    .with("combo", comboId)
                    .with("exit_state", accumulate ? "omnath_lethal" : "card_advantage")
                    .with("untapper", untapper).with("actor", actor)
                    .with("measure", measure).with("tranche", 1).with("iterations_done", 0));
        }

        // exit (accumulate): Omnath's power clears the biggest table seat and
        // he can swing — hand to combat (the pilot's lethalAlphaOrder closes)
        if (accumulate && retainer != null && omnathLethal()) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", cyclesDone)
                    .with("outlet", retainer).with("exit", "omnath_lethal"));
            return null;
        }
        // per-turn bound — hand back and re-engage next dispatch (Omnath keeps
        // the floated green; a Nylea engine simply banked cyclesDone cards)
        if (cyclesDone >= perTurnCap) {
            finished = true;
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", cyclesDone)
                    .with("outlet", accumulate ? retainer : sinkCard)
                    .with("exit", "per_turn_cap"));
            return null;
        }

        String actCost = accumulate ? producerCost : sinkCost;
        SpellAbility act = AbilityResolver.resolve(player, actor, actCost, List.of());
        if (act == null || !forge.ai.ComputerUtilCost.canPayCost(act, player, false)) {
            // fuel/untap ran out this turn — hand back with what we banked
            finished = true;
            pilot.observe(ArenaEvent.of("program_complete", turn, seat)
                    .with("combo", comboId).with("iterations", cyclesDone)
                    .with("outlet", accumulate ? retainer : sinkCard)
                    .with("exit", "fuel_exhausted"));
            return null;
        }
        measureBefore = measureValue();
        pendingMeasure = true;
        return List.of(act);
    }

    private long measureValue() {
        switch (measure) {
            case "omnath_power": {
                Card o = AbilityResolver.findBattlefield(player, retainer);
                return o == null ? 0 : o.getNetPower();
            }
            case "pool_green":
                return player.getManaPool().getAmountOfColor(forge.card.MagicColor.GREEN);
            case "hand_size":
            default:
                return player.getCardsIn(ZoneType.Hand).size();
        }
    }

    /** Omnath's power clears the biggest live opponent's life and he can attack. */
    private boolean omnathLethal() {
        Card o = AbilityResolver.findBattlefield(player, retainer);
        if (o == null || !forge.game.combat.CombatUtil.canAttack(o)) {
            return false;
        }
        int maxLife = 0;
        for (Player p : game.getPlayers()) {
            if (p != player && !p.hasLost()) {
                maxLife = Math.max(maxLife, p.getLife());
            }
        }
        return maxLife > 0 && o.getNetPower() >= maxLife;
    }

    private List<SpellAbility> abort(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("engine_abort", turn, seat)
                .with("engine", comboId).with("iterations", cyclesDone).with("reason", reason));
        return null;
    }
}
