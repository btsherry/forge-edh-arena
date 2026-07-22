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

    private enum State { PREFLIGHT, WIPE_CAST, PROTECTED }

    private State state = State.PREFLIGHT;
    private boolean finished;
    private int ownBefore = -1;
    private int oppBefore = -1;
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
                if (protMana > 0
                        && manaOf(wipe) + protMana > availableMana()) {
                    // coarse (counts sources, not pips) but conservative in
                    // the direction that matters; the retry fires next turn
                    return abortRetryable(turn, "preflight_joint_mana: wipe "
                            + manaOf(wipe) + " + protection " + protMana
                            + " > available " + availableMana());
                }
                ownBefore = creatures(player);
                oppBefore = opponentCreatures();
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
                finished = true;
                if (!protectionSeen) {
                    // the shield's cast can fail as silently as a wipe's —
                    // without this the failure would be misattributed to
                    // delta_mismatch (or worse, a one-sided wipe would emit
                    // a false pairing_complete)
                    return abort(turn, "protection_cast_failed: '" + protectionCard
                            + "' never reached the stack");
                }
                int ownAfter = creatures(player);
                int oppAfter = opponentCreatures();
                boolean preserved = ownAfter >= ownBefore;
                // sweeping to zero is not promised by 'destroy' — opposing
                // indestructible/regeneration legally survive. Measured
                // contract: our board holds, theirs shrank; full_sweep is
                // recorded, not required.
                boolean reduced = oppAfter < oppBefore;
                if (preserved && reduced) {
                    pilot.observe(ArenaEvent.of("pairing_complete", turn, seat)
                            .with("pairing", pairingId)
                            .with("own_before", ownBefore).with("own_after", ownAfter)
                            .with("opp_before", oppBefore).with("opp_after", oppAfter)
                            .with("full_sweep", oppAfter == 0));
                } else {
                    pilot.observe(ArenaEvent.of("pairing_abort", turn, seat)
                            .with("pairing", pairingId)
                            .with("reason", "delta_mismatch: own " + ownBefore + "->"
                                    + ownAfter + ", opp " + oppBefore + "->" + oppAfter));
                }
                return null;
            }
            default -> {
                return null;
            }
        }
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

    private static int creatures(Player p) {
        int n = 0;
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
            if (c.isCreature()) {
                n++;
            }
        }
        return n;
    }

    private int opponentCreatures() {
        int n = 0;
        for (Player other : game.getPlayers()) {
            if (other != player && !other.hasLost()) {
                n += creatures(other);
            }
        }
        return n;
    }
}
