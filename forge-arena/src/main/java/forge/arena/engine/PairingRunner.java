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
 * PR-eta: executes a compiled pairing program (arena.pairing-program/1) —
 * wipe + protection, respond-on-stack. The one deliberate exception to the
 * interpreter's "yield while the stack is non-empty" invariant: the whole
 * point of this runner is to act with its OWN wipe on the stack, casting the
 * protection in response so LIFO resolves the shield first.
 *
 * <p>What the legacy PairedPlay archetype lacked, encoded as states:
 * <ol>
 * <li>PREFLIGHT — both casts resolvable vs LIVE state before anything is
 *     spent (never cast a wipe whose protection cannot follow).</li>
 * <li>WIPE_CAST — verify the wipe is actually ON the stack next window. The
 *     epsilon batch measured the legacy machinery silently failing this cast
 *     (Final Showdown's Spree modal), dangling its armed protection forever;
 *     here a missing wipe aborts loudly.</li>
 * <li>PROTECTED — after the stack empties, MEASURE: own creatures preserved,
 *     every opponent swept. The legacy path emitted optimistic events and
 *     verified nothing.</li>
 * </ol>
 *
 * <p>Fresh evaluation on any abort; once per pair per game (the pilot marks
 * it fired at dispatch). Deck-agnostic: every card name comes from the
 * compiled program.
 */
public final class PairingRunner {

    private final Game game;
    private final Player player;
    private final ComboPilot pilot;
    private final int seat;
    private final String pairingId;
    private final String wipeCard;
    private final String protectionCard;
    private final String programPath;
    /** CREATURES | LANDS | NONLAND_PERMANENTS | ALL_PERMANENTS — what the wipe hits, so what we count. */
    private final String scope;
    /**
     * PR-theta: stack_empty (default) or next_untap. A phasing shield
     * (Teferi's Protection) makes our permanents INVISIBLE to battlefield
     * counts until they phase in before our untap — an end-of-stack own-side
     * measure would false-abort a textbook execution, so the own measure
     * waits for our next turn while the opponents' losses are taken at
     * stack-empty (they are real immediately, and an opponent replaying
     * lands meanwhile must not launder the reduction).
     */
    private final boolean measureAtNextUntap;

    private enum State { PREFLIGHT, WIPE_CAST, PROTECTED, MEASURE_DEFERRED }

    private State state = State.PREFLIGHT;
    private boolean finished;
    private int ownBefore = -1;
    private int oppBefore = -1;
    private int oppAfterAtResolution = -1;
    private int castTurn = -1;
    /** The shield must be SEEN on the stack before the measure counts. */
    private boolean protectionSeen;

    PairingRunner(Game game, Player player, ComboPilot pilot, int seat, String programPath) {
        this.programPath = programPath;
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
        this.pairingId = p != null ? p.path("pairing_id").asText("?") : "?";
        this.wipeCard = p != null ? p.path("wipe").path("card").asText(null) : null;
        this.protectionCard = p != null ? p.path("protection").path("card").asText(null) : null;
        this.scope = p != null ? p.path("wipe").path("scope").asText("CREATURES") : "CREATURES";
        this.measureAtNextUntap = p != null
                && "next_untap".equals(p.path("verify").path("measure_at").asText("stack_empty"));
        if (wipeCard == null || protectionCard == null) {
            finished = true;
            // aborts are LOUD, even this one (panel finding: a swallowed
            // constructor failure left pairing_entered with no terminal)
            pilot.observe(ArenaEvent.of("pairing_abort", 0, seat)
                    .with("pairing", pairingId)
                    .with("reason", "program_unreadable: " + programPath));
        }
    }

    public boolean finished() {
        return finished;
    }

    /** One decision per priority window — called stack-empty or not. */
    public List<SpellAbility> next(int turn) {
        if (finished) {
            return null;
        }
        if (player.hasLost()) {
            // reachable during a multi-turn deferral in 4p — without this
            // the runner freezes silently, the exact signature the loud-
            // abort rule exists to prevent (a game ENDING mid-deferral is
            // scored as truncated by the fidelity scorer instead; no window
            // ever arrives to emit anything)
            return abort(turn, "seat_eliminated_during_pairing");
        }
        switch (state) {
            case PREFLIGHT -> {
                // invariant 1 vs LIVE state, both halves, JOINTLY — the
                // panel's blocker: validating each cast against the same
                // pre-spend mana let the wipe eat the shield's mana and
                // resolve unprotected. Nothing is spent before this passes,
                // so every abort here is retryable (fresh evaluation).
                SpellAbility wipe = AbilityResolver.resolveCast(player, wipeCard);
                if (wipe == null) {
                    return abortRetryable(turn, "preflight_wipe_unresolvable: '"
                            + wipeCard + "'");
                }
                SpellAbility protection = cheapestCast(protectionCard);
                if (protection == null) {
                    return abortRetryable(turn, "preflight_protection_unresolvable: '"
                            + protectionCard + "'");
                }
                int protMana = manaOf(protection);
                if (protMana > 0) {
                    // PIP-AWARE joint check (kappa60 batch, measured twice:
                    // the colorless source count passed, the wipe's payment
                    // tapped the W sources, and the shield's {W}{W} went
                    // unpayable — Doomskar swept our own board in game 18,
                    // Armageddon ate our own lands in game 39)
                    int needTotal = manaOf(wipe) + protMana;
                    int needWhite = coloredPips(wipe, 'W') + coloredPips(protection, 'W');
                    if (needTotal > availableMana()
                            || needWhite > whiteCapableSources()) {
                        return abortRetryable(turn, "preflight_joint_mana: total "
                                + needTotal + "/" + availableMana()
                                + " whitePips " + needWhite + "/" + whiteCapableSources());
                    }
                }
                ownBefore = countScoped(player);
                oppBefore = opponentScoped();
                castTurn = turn;
                state = State.WIPE_CAST;
                return List.of(wipe);
            }
            case WIPE_CAST -> {
                if (!onStack(wipeCard)) {
                    // the legacy deadlock, made loud — and made PRECISE: a
                    // non-empty stack holding someone else's object is not
                    // our wipe (the panel caught the weaker emptiness check)
                    return abort(turn, "wipe_cast_failed: '" + wipeCard
                            + "' not on the stack");
                }
                SpellAbility protection = cheapestCast(protectionCard);
                if (protection == null) {
                    return abort(turn, "protection_unresolvable_in_response: '"
                            + protectionCard + "' (wipe resolves unprotected)");
                }
                state = State.PROTECTED;
                return List.of(protection);
            }
            case PROTECTED -> {
                if (!game.getStack().isEmpty()) {
                    protectionSeen = protectionSeen || onStack(protectionCard);
                    return null; // both spells resolving, LIFO — shield first
                }
                if (!protectionSeen) {
                    // the shield's cast can fail as silently as a wipe's —
                    // without this the failure would be misattributed to
                    // delta_mismatch (or worse, a one-sided wipe would emit
                    // a false pairing_complete)
                    finished = true;
                    return abort(turn, "protection_cast_failed: '" + protectionCard
                            + "' never reached the stack");
                }
                // opponents' losses are real the moment the wipe resolves —
                // snapshot NOW so later land replays cannot launder them
                oppAfterAtResolution = opponentScoped();
                if (measureAtNextUntap) {
                    state = State.MEASURE_DEFERRED;
                    return null;
                }
                finished = true;
                return measure(turn, countScoped(player));
            }
            case MEASURE_DEFERRED -> {
                // our phased permanents return before our untap; the first
                // priority window of our NEXT turn is after that
                if (turn <= castTurn
                        || game.getPhaseHandler().getPlayerTurn() != player) {
                    return null;
                }
                finished = true;
                return measure(turn, countScoped(player));
            }
            default -> {
                return null;
            }
        }
    }

    /**
     * The verdict, from measured counts: our side held (post phase-in when
     * deferred), theirs shrank. Sweeping to zero is not promised by
     * 'destroy' — indestructible/regeneration legally survive — so
     * full_sweep is recorded, never required.
     */
    private List<SpellAbility> measure(int turn, int ownAfter) {
        boolean preserved = ownAfter >= ownBefore;
        boolean reduced = oppAfterAtResolution < oppBefore;
        if (preserved && reduced) {
            pilot.observe(ArenaEvent.of("pairing_complete", turn, seat)
                    .with("pairing", pairingId)
                    .with("own_before", ownBefore).with("own_after", ownAfter)
                    .with("opp_before", oppBefore).with("opp_after", oppAfterAtResolution)
                    .with("full_sweep", oppAfterAtResolution == 0)
                    .with("measured_at", measureAtNextUntap ? "next_untap" : "stack_empty"));
        } else {
            // name the failing SIDE — a countered shield (own collapsed), a
            // countered wipe (opp unchanged), and a both-sides mess are
            // different investigations (verifier finding: one reason string
            // conflated opponent interaction with runner malfunction)
            String side = !preserved && !reduced ? "both"
                    : !preserved ? "own" : "opp";
            pilot.observe(ArenaEvent.of("pairing_abort", turn, seat)
                    .with("pairing", pairingId)
                    .with("reason", "delta_mismatch[" + side + "]: own " + ownBefore
                            + "->" + ownAfter
                            + ", opp " + oppBefore + "->" + oppAfterAtResolution));
        }
        return null;
    }

    private List<SpellAbility> abort(int turn, String reason) {
        finished = true;
        pilot.observe(ArenaEvent.of("pairing_abort", turn, seat)
                .with("pairing", pairingId).with("reason", reason));
        return null;
    }

    /**
     * A PREFLIGHT abort spent NOTHING — burning the once-per-game pair on it
     * contradicted the program's own self_consumption rationale (panel).
     * The pilot un-marks it; attemptedThisTurn still blocks a same-turn spin.
     */
    private List<SpellAbility> abortRetryable(int turn, String reason) {
        pilot.pairingPreflightFailed(pairingId);
        return abort(turn, reason);
    }

    /**
     * The castable SA with the LOWEST total mana cost — Flawless Maneuver
     * offers both retail {2}{W} and the commander-gated {0} alternative, and
     * resolveCast's first-match could pick retail, failing the joint check
     * on boards where the free cast is live.
     */
    private SpellAbility cheapestCast(String cardName) {
        SpellAbility best = null;
        int bestMana = Integer.MAX_VALUE;
        for (forge.game.zone.ZoneType zone
                : List.of(forge.game.zone.ZoneType.Hand, forge.game.zone.ZoneType.Command)) {
            for (Card card : player.getCardsIn(zone)) {
                if (!card.getName().equals(cardName)) {
                    continue;
                }
                for (SpellAbility sa : card.getAllPossibleAbilities(player, true)) {
                    if (!sa.isSpell()) {
                        continue;
                    }
                    // never pick an alternative that SACRIFICES a permanent
                    // just because its mana is low — Flare of Fortitude's
                    // sac-a-white-creature mode reads as 0 mana and would
                    // eat an angel (or Avacyn) to save the rest
                    boolean sacrifices = false;
                    if (sa.getPayCosts() != null) {
                        for (forge.game.cost.CostPart part : sa.getPayCosts().getCostParts()) {
                            if (part instanceof forge.game.cost.CostSacrifice) {
                                sacrifices = true;
                                break;
                            }
                        }
                    }
                    if (sacrifices) {
                        continue;
                    }
                    sa.setActivatingPlayer(player);
                    if (!forge.ai.ComputerUtilCost.canPayCost(sa, player, false)) {
                        continue;
                    }
                    int mana = manaOf(sa);
                    if (mana < bestMana) {
                        bestMana = mana;
                        best = sa;
                    }
                }
            }
        }
        return best;
    }

    private static int manaOf(SpellAbility sa) {
        return sa.getPayCosts() == null || sa.getPayCosts().getTotalMana() == null
                ? 0 : sa.getPayCosts().getTotalMana().getCMC();
    }

    /** Colored pips of one color in the SA's structured mana cost. */
    private static int coloredPips(SpellAbility sa, char color) {
        if (sa.getPayCosts() == null || sa.getPayCosts().getTotalMana() == null) {
            return 0;
        }
        int pips = 0;
        for (forge.card.mana.ManaCostShard shard : sa.getPayCosts().getTotalMana()) {
            if (shard.toString().contains(String.valueOf(color))) {
                pips++;
            }
        }
        return pips;
    }

    /** Untapped sources whose mana abilities can produce this deck's color. */
    private int whiteCapableSources() {
        int n = 0;
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (c.isTapped() || c.getManaAbilities().isEmpty()
                    || (c.isCreature() && c.hasSickness())) {
                continue;
            }
            for (SpellAbility ma : c.getManaAbilities()) {
                String produced = ma.getParam("Produced");
                if (produced != null
                        && (produced.contains("W") || produced.contains("Any"))) {
                    n++;
                    break;
                }
            }
        }
        return n;
    }

    /** Pool plus untapped mana sources, one each — coarse, conservative. */
    private int availableMana() {
        int available = player.getManaPool().totalMana();
        for (Card c : player.getCardsIn(ZoneType.Battlefield)) {
            if (!c.isTapped() && !c.getManaAbilities().isEmpty()
                    && !(c.isCreature() && c.hasSickness())) {
                available++;
            }
        }
        return available;
    }

    /** Is OUR named card on the stack right now? */
    private boolean onStack(String cardName) {
        for (forge.game.spellability.SpellAbilityStackInstance si : game.getStack()) {
            if (si.getSourceCard() != null
                    && cardName.equals(si.getSourceCard().getName())
                    && si.getActivatingPlayer() == player) {
                return true;
            }
        }
        return false;
    }

    /** Count what the wipe's declared scope hits (battlefield, unphased). */
    private int countScoped(Player p) {
        int n = 0;
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
            boolean hit = switch (scope) {
                case "LANDS" -> c.isLand();
                case "NONLAND_PERMANENTS" -> !c.isLand();
                case "ALL_PERMANENTS" -> true;
                default -> c.isCreature();
            };
            if (hit) {
                n++;
            }
        }
        return n;
    }

    private int opponentScoped() {
        int n = 0;
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                n += countScoped(other);
            }
        }
        return n;
    }
}
