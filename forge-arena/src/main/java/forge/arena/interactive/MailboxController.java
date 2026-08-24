package forge.arena.interactive;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.google.common.collect.Multiset;

import forge.LobbyPlayer;
import forge.ai.ComputerUtil;
import forge.ai.ComputerUtilAbility;
import forge.ai.ComputerUtilCost;
import forge.ai.ComputerUtilMana;
import forge.ai.PlayerControllerAi;
import forge.arena.engine.SeatView;
import forge.arena.engine.SeatViews;
import forge.game.Game;
import forge.game.GameEntity;
import forge.game.ability.AbilityUtils;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.card.CardCollectionView;
import forge.game.card.CardLists;
import forge.game.player.PlayerActionConfirmMode;
import forge.game.card.CounterType;
import forge.game.combat.Combat;
import forge.game.combat.CombatUtil;
import forge.game.cost.Cost;
import forge.game.cost.CostTap;
import forge.game.phase.PhaseType;
import forge.game.player.DelayedReveal;
import forge.game.player.Player;
import forge.game.spellability.AbilitySub;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import forge.util.collect.FCollectionView;

/**
 * A "mailbox" seat controller: on a small set of meaningful decisions it writes
 * the (hidden-info-safe) game state + legal options to a file, blocks for an
 * answer file, then plays the chosen option. The answering "brain" is an
 * external process; this class only speaks the file protocol
 * ({@link MailboxProtocol}) and — crucially — every override TIMES OUT back to
 * {@code super} (stock AI), so a silent or crashed brain never hangs the game.
 *
 * <p>Injected exactly like {@code ComboAwareController}: a {@code LobbyPlayerAi}
 * subclass ({@link MailboxLobbyPlayer}) sets this as the player's first
 * controller. No parent-module patch is required.
 *
 * <p>Hidden-info discipline: the serialized state is built from
 * {@link SeatViews#of(Player, int, int)} plus the acting seat's own hand — only
 * this seat's visible zones and PUBLIC board/life/stack of others. Opponents'
 * hands and library order are never serialized.
 *
 * <p>Scope: top-level decisions ({@code CAST_SPELL}, {@code MULLIGAN},
 * {@code DECLARE_ATTACKERS}, {@code DECLARE_BLOCKERS}) PLUS a set of high-value
 * SUB-CHOICES the acting seat makes while resolving its own effects:
 * <ul>
 *   <li>{@code CHOOSE_ENTITY} — a single "choose a creature/permanent" effect
 *       (e.g. Glasspool Mimic's "copy which creature", Clone effects) via
 *       {@link #chooseSingleEntityForEffect}.</li>
 *   <li>{@code CHOOSE_ENTITIES} — a bounded (min..max) multi-entity selection via
 *       {@link #chooseEntitiesForEffect}.</li>
 *   <li>{@code CHOOSE_MODE} — modal/charm mode selection via
 *       {@link #chooseModeForAbility}.</li>
 *   <li>{@code CHOOSE_CARD} — tutor/search-and-move card selection via
 *       {@link #chooseSingleCardForZoneChange}.</li>
 * </ul>
 * These sub-choice hooks are gated NARROWLY: they only mailbox a genuine choice
 * (more than one legal option, or an optional single option) and, for the entity
 * hooks, only when every option is a {@link Card} (so ids never collide with
 * player ids). Everything else — normal spell targeting ({@code chooseTargetsFor},
 * deliberately left on stock because it mutates the SpellAbility in place),
 * {@code confirmAction}, trigger ordering, mana-color, numbers, yes/no — stays on
 * {@code super}. As with the top-level hooks, EVERY sub-choice override falls back
 * to {@code super} on timeout / null / malformed / illegal / wrong-count, so a
 * silent brain never hangs the game.
 */
public final class MailboxController extends PlayerControllerAi
        implements forge.ai.TapCostPreference, forge.ai.SacCostPreference {

    private final MailboxProtocol bus;
    private final int seatIndex;

    MailboxController(Game game, Player p, LobbyPlayer lobby, MailboxProtocol bus) {
        super(game, p, lobby);
        this.bus = bus;
        this.seatIndex = p.getId();
    }

    /**
     * Symmetry-break tap preference (game 7, 2026-08-17): when the seat picks
     * a [SYMMETRY BREAK] option, the piece to tap is recorded here so that
     * {@link forge.ai.AiCostDecision}'s CostTapType payment (via
     * {@link forge.ai.TapCostPreference}) taps THAT card, not a stock pick.
     * Keyed by SA identity; cleared at every new decision window.
     */
    private final Map<SpellAbility, Card> pendingTapPreference =
            new java.util.IdentityHashMap<>();

    /**
     * Triggers the seat declined AT AIM TIME (game-12 finding 1): a
     * required-target optional trigger can't legally stack targetless, so we
     * auto-aim it and honor the decline here — confirmTrigger answers NO
     * without a model call. Weak identity set: entries die with their SAs.
     */
    private final Set<SpellAbility> pendingTriggerDecline =
            java.util.Collections.newSetFromMap(new java.util.WeakHashMap<>());

    /** Non-zero while prepareTriggerViaSeat is aiming — trigger-aim windows
     *  offer an explicit decline (id 0) even for required targets, and
     *  invalid answers fall back to the CALLER (auto-aim + auto-decline),
     *  never to stock's silent aiming. */
    private int triggerAimDepth = 0;

    @Override
    public CardCollection preferredTapCards(SpellAbility ability) {
        Card piece = pendingTapPreference.get(ability);
        if (piece == null && ability != null) {
            piece = pendingTapPreference.get(ability.getRootAbility());
        }
        return piece == null ? null : new CardCollection(piece);
    }

    /**
     * Symmetry pieces: permanents whose CONTINUOUS static applies only while
     * the permanent itself is untapped AND affects PLAYERS (Winter Orb,
     * Static Orb, Storage Matrix class). Detected from script metadata, never
     * card names — a "while untapped" static that only buffs its own card
     * (Paradise Druid class) is deliberately NOT a symmetry piece: tapping
     * those hurts their controller.
     */
    static List<Card> symmetryPieces(Player owner) {
        List<Card> out = new ArrayList<>();
        for (Card c : owner.getCardsIn(ZoneType.Battlefield)) {
            for (forge.game.staticability.StaticAbility st : c.getStaticAbilities()) {
                String present = st.getParam("IsPresent");
                String affected = st.getParam("Affected");
                if ("Continuous".equals(st.getParam("Mode"))
                        && present != null && present.contains("Card.Self+untapped")
                        && affected != null && affected.contains("Player")) {
                    out.add(c);
                    break;
                }
            }
        }
        return out;
    }

    // ---- decision hooks ----------------------------------------------------

    @Override
    public List<SpellAbility> chooseSpellAbilityToPlay() {
        Game game = getGame();
        Player me = getPlayer();
        pendingTapPreference.clear(); // one-shot: valid only for the pick below
        // GATE. Two window kinds are worth the brain's time:
        //  - ownMainEmpty: our own main phase with an empty stack (sorcery-speed
        //    development), and
        //  - reactive: an OPPONENT has a spell/ability on the stack that we could
        //    respond to at instant speed (counter, protect, removal-in-response).
        // Everything else stays with stock so we don't flood the brain: empty-
        // stack instant windows, our own spell merely resolving, forced passes.
        // Note: at a reactive window canPlay() naturally admits only instant-
        // speed responses, and if we hold none the playable list is empty and we
        // fall through to stock below — so a reactive window only actually
        // mailboxes when there is both an opponent object to answer AND a legal
        // response in hand.
        boolean ownMainEmpty = (game.getPhaseHandler().is(PhaseType.MAIN1, me)
                || game.getPhaseHandler().is(PhaseType.MAIN2, me))
                && game.getStack().isEmpty();
        boolean reactive = false;
        if (!ownMainEmpty && !game.getStack().isEmpty()) {
            for (forge.game.spellability.SpellAbilityStackInstance si : game.getStack()) {
                SpellAbility onStack = si.getSpellAbility();
                Player ap = onStack != null ? onStack.getActivatingPlayer() : null;
                if (ap != null && ap != me) {
                    reactive = true; // an opponent's object is on the stack to answer
                    break;
                }
            }
        }
        // v3 (field note 13): TACTICAL windows — combat steps and end steps,
        // any player's turn, empty stack. This is where fogs, combat tricks,
        // saves, and end-step flash live; v2 sent them to stock, which withheld
        // a game-saving Flare of Fortitude (game 2) and burned a held Silence
        // at dead timing (game 3). Fires only when a real, affordable, non-mana
        // action survives the filter below, so instant-less seats never wake.
        PhaseType ph = game.getPhaseHandler().getPhase();
        boolean tactical = !ownMainEmpty && !reactive && game.getStack().isEmpty()
                && (ph == PhaseType.COMBAT_BEGIN
                    || ph == PhaseType.COMBAT_DECLARE_ATTACKERS
                    || ph == PhaseType.COMBAT_DECLARE_BLOCKERS
                    || ph == PhaseType.COMBAT_FIRST_STRIKE_DAMAGE
                    || ph == PhaseType.COMBAT_DAMAGE
                    || ph == PhaseType.COMBAT_END
                    || ph == PhaseType.END_OF_TURN);
        // v4 (field note 21): SELF-TRIGGER windows — one of the seat's OWN
        // triggered abilities is on the stack (no opponent object, else it's
        // reactive) and it holds priority BEFORE that trigger resolves. This is
        // the only window to respond to your own trigger — the Phyrexian
        // Dreadnought line lives here: cast Dreadnought, then in response to its
        // "sacrifice unless" ETB sac it to Greater Good (draw 12) and tap Selvala
        // for 12 while it's still a 12/12. v3 sent this to stock, which never
        // finds it — Selvala provably whiffed the line (2026-08-10). Opens
        // whenever a real action is available (see the playable filter below);
        // we accept the extra windows on spammy triggers (Norin) as slowness
        // rather than risk gating away a line the brain wanted.
        boolean selfTrigger = false;
        if (!ownMainEmpty && !reactive && !tactical && !game.getStack().isEmpty()) {
            for (forge.game.spellability.SpellAbilityStackInstance si : game.getStack()) {
                SpellAbility onStack = si.getSpellAbility();
                if (onStack != null && onStack.isTrigger()
                        && onStack.getActivatingPlayer() == me) {
                    selfTrigger = true; // my own trigger is on the stack to answer
                    break;
                }
            }
        }
        if (!ownMainEmpty && !reactive && !tactical && !selfTrigger) {
            // v3: stock NEVER casts for a mailbox seat anymore. Windows not
            // worth the brain's time are a clean pass — the brain owns this
            // hand. (Stock still takes over wholesale on brain timeout, via
            // the exchange() fallback — that degradation path is unchanged.)
            return null;
        }

        int turn = game.getPhaseHandler().getTurn();
        List<SpellAbility> playable = new ArrayList<>();
        // getSpellAbilities() deliberately STRIPS alternative-cost versions of a
        // spell whenever the base spell is castable (stock AI re-derives them at
        // cast time via getOriginalAndAltCostAbilities). The mailbox plays the
        // chosen SA directly, so the brain only ever saw the paid version:
        // Fierce Guardianship showed as {2}{U}, the seat chose it believing it
        // free (it controlled its commander), and the payer tapped four sources
        // (2026-08-17 game 5 — the counter it held all game fizzled). Expand
        // alt costs into DISTINCT options, cheaper ones first, exactly as stock
        // does when it casts.
        List<SpellAbility> enumerated;
        try {
            enumerated = ComputerUtilAbility.getOriginalAndAltCostAbilities(
                    ComputerUtilAbility.getSpellAbilities(
                            ComputerUtilAbility.getAvailableCards(game, me), me), me);
        } catch (RuntimeException e) {
            enumerated = ComputerUtilAbility.getSpellAbilities(
                    ComputerUtilAbility.getAvailableCards(game, me), me);
        }
        for (SpellAbility sa : enumerated) {
            Card host = sa != null ? sa.getHostCard() : null;
            if (sa == null) {
                continue;
            }
            if (sa.isManaAbility()) {
                // Main-phase development: drop trivial land mana (a plain {T}: add
                // mana) to avoid flooding options, but KEEP non-trivial mana
                // abilities (nonland sources, or costs beyond a bare tap — e.g.
                // Grinning Ignus's {R}, Return: add {C}{C}{R}) as strategic lines.
                // In a REACTIVE or TACTICAL window a mana ability is never a
                // meaningful action on its own (tapping Sol Ring answers nothing),
                // so drop ALL of them there. A SELF-TRIGGER window KEEPS non-trivial
                // mana abilities (like own-main), because "tap Selvala for 12" in
                // response to Dreadnought's ETB is exactly the point.
                if (isTrivialLandMana(sa, host)) {
                    continue;
                }
                if (reactive || tactical) {
                    continue;
                }
            }
            sa.setActivatingPlayer(me);
            try {
                // canPlay() admits some spells the seat cannot actually pay for at a
                // reactive window (e.g. Mana Drain {U}{U} with a single untapped
                // Island), which opened phantom counter windows. Require real
                // affordability for reactive responses so the window only fires when
                // the seat can truly act. Main-phase and self-trigger keep canPlay()
                // alone, since a mana line in the option list may itself enable the
                // cost (float, then sink).
                boolean affordable = !(reactive || tactical)
                        || ComputerUtilCost.canPayCost(sa, me, false);
                if (sa.canPlay() && affordable) {
                    playable.add(sa);
                }
            } catch (RuntimeException canPlayThrew) {
                // a mis-evaluated canPlay must not crash the seat — skip it
            }
        }
        // v4-redesign (2026-08-10): a self-trigger window opens whenever there
        // is ANY real action available — no cleverness about WHICH triggers
        // deserve a window. The earlier "sac-outlet or big-float" gate was
        // Dreadnought-shaped and risked silently removing lines the brain would
        // have taken; correctness/intent beat speed, so we open generously and
        // let the brain decide (and pass) every window. Flood is tolerated as
        // slowness, not eliminated by second-guessing the brain. (playable
        // already excludes trivial land mana; non-trivial mana abilities like
        // Selvala-for-12 remain, so the no-sink Dreadnought float stays live.)
        // SYMMETRY BREAK offers (game 7, 2026-08-17): if the seat controls an
        // untapped symmetry piece (a Continuous static active only while the
        // piece is untapped, affecting Players — Winter Orb class) and the
        // seat's untap step is the NEXT one to happen, offer tapping the
        // piece through any activatable outlet whose CostTapType it can pay
        // (Urza's "tap an untapped artifact", Clock of Omens, the piece's own
        // tap ability...). This is the one case where a mana ability IS the
        // meaningful action, so it bypasses the mana-ability window filter —
        // the piece is pre-selected as the tap payment via TapCostPreference.
        List<Object[]> symOffers = new ArrayList<>(); // {SpellAbility, Card piece, String label}
        try {
            if (game.getPhaseHandler().getPlayerTurn() != me
                    && game.getPhaseHandler().getNextTurn() == me) {
                List<Card> pieces = symmetryPieces(me);
                for (Card piece : pieces) {
                    if (!piece.isUntapped()) {
                        continue;
                    }
                    for (SpellAbility osa : enumerated) {
                        if (symOffers.size() >= 6) {
                            break;
                        }
                        Card oHost = osa != null ? osa.getHostCard() : null;
                        if (oHost == null || !osa.isActivatedAbility()
                                || !oHost.isInZone(ZoneType.Battlefield)
                                || osa.getPayCosts() == null) {
                            continue;
                        }
                        boolean tapsPiece = false;
                        for (forge.game.cost.CostPart part : osa.getPayCosts().getCostParts()) {
                            if (part instanceof forge.game.cost.CostTapType) {
                                forge.game.cost.CostTapType t =
                                        (forge.game.cost.CostTapType) part;
                                if ((t.canTapSource || oHost != piece)
                                        && piece.isValid(t.getType().split(";"),
                                                me, oHost, osa)) {
                                    tapsPiece = true;
                                    break;
                                }
                            }
                            if (part instanceof CostTap && oHost == piece) {
                                tapsPiece = true; // the piece's own {T} ability
                                break;
                            }
                        }
                        if (!tapsPiece) {
                            continue;
                        }
                        osa.setActivatingPlayer(me);
                        boolean usable;
                        try {
                            usable = osa.canPlay()
                                    && ComputerUtilCost.canPayCost(osa, me, false);
                        } catch (RuntimeException e) {
                            usable = false;
                        }
                        if (!usable) {
                            continue;
                        }
                        String label = "[SYMMETRY BREAK] Tap " + piece.getName()
                                + " via " + oHost.getName() + " ("
                                + osa.getPayCosts().toSimpleString() + ") — your "
                                + "untap step is NEXT: with " + piece.getName()
                                + " tapped, its 'while untapped' restriction skips "
                                + "YOUR untap, then it untaps during your untap "
                                + "step and keeps restricting the other players. "
                                + (osa.isManaAbility()
                                    ? "Mana produced now will drain unspent — the "
                                      + "point is the tap, not the mana."
                                    : "The ability's normal effect also happens.");
                        symOffers.add(new Object[] {osa, piece, label});
                    }
                }
            }
        } catch (RuntimeException e) {
            symOffers.clear(); // offers must never break the window
        }

        if (playable.isEmpty() && symOffers.isEmpty()) {
            // Instant windows with nothing real to do are a clean pass (never
            // stock); an empty own-main keeps the v1 stock fallthrough.
            return (reactive || tactical || selfTrigger)
                    ? null : super.chooseSpellAbilityToPlay();
        }

        // Stable id per option this decision; 0 is reserved for "pass".
        String decisionType = ownMainEmpty ? "CAST_SPELL" : "REACT";
        String prompt;
        if (ownMainEmpty) {
            prompt = "Choose a spell/ability to play, or pass.";
        } else if (tactical) {
            prompt = (ph == PhaseType.END_OF_TURN)
                    ? "End-step instant window — act at instant speed, or pass."
                    : "Combat instant window (" + phaseName(game) + ") — fogs, "
                      + "tricks, and saves live here; see state.combat for "
                      + "attackers/blocks. Act at instant speed, or pass.";
        } else if (selfTrigger) {
            prompt = "YOUR OWN trigger/ability is on the stack (see state.stack). "
                    + "This is your window to respond BEFORE it resolves — e.g. "
                    + "sacrifice a creature to an outlet, tap for mana while a big "
                    + "body is still on the battlefield, or protect a piece. Act "
                    + "now, or pass to let it resolve. You keep priority after "
                    + "acting, so you can chain several responses.";
        } else {
            prompt = "Instant-speed window — respond to what's on the stack, or pass.";
        }
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), decisionType, prompt)
                .state(buildState(turn))
                .option(0, "Pass (do nothing)", null, "PASS");
        Map<Integer, SpellAbility> byId = new LinkedHashMap<>();
        int id = 1;
        for (SpellAbility sa : playable) {
            Card host = sa.getHostCard();
            String name = host != null ? host.getName() : sa.getDescription();
            String cost = sa.getPayCosts() != null ? sa.getPayCosts().toSimpleString() : null;
            String lab = label(sa, host);
            // Commander tax is applied by CostAdjustment at PAYMENT time, so
            // the SA's stored cost never shows it: Selvala's third cast read
            // {1}{G}{G} when the true bill was 7. The brain sequenced around 3,
            // the mana payer refused, and Forge's failed-payment path (its own
            // FIXME) orphaned the commander with no zone (2026-08-17). Show the
            // effective cost and say why so the brain never picks it short.
            int tax = commanderTax(sa, host);
            if (tax > 0) {
                cost = (cost != null ? cost : "") + " + {" + tax + "} commander tax";
                lab += " [effective cost: " + describeTotalCost(sa, tax) + "]";
            }
            // A spell offered at {0} whose printed cost is not {0} is an
            // alternative cost the seat qualifies for right now (Fierce
            // Guardianship-class 'if you control a commander', Force of Will
            // pitch, etc.). Say so plainly — the paid version is listed too.
            try {
                if (sa.isSpell() && host != null && host.getManaCost() != null
                        && host.getManaCost().getCMC() > 0
                        && sa.getPayCosts() != null && sa.getPayCosts().isOnlyManaCost()
                        && sa.getPayCosts().getTotalMana() != null
                        && sa.getPayCosts().getTotalMana().getCMC() == 0) {
                    lab += " [FREE — alternative cost you qualify for right now; printed cost "
                            + host.getManaCost() + "]";
                }
            } catch (RuntimeException ignore) {
                // label decoration must never break option building
            }
            // Ground the float decision: any visible mana ability that would
            // add 2+ RIGHT NOW says so (Cradle, Selvala, Tomb...), so the
            // brain prices the float without doing SVar math itself.
            if (sa.isManaAbility()) {
                int yield = manaAbilityYield(sa, host);
                if (yield >= 2) {
                    lab += " [currently adds " + yield + " mana]";
                }
            }
            req.option(id, lab, cost, typeHint(host));
            byId.put(id, sa);
            id++;
        }
        Map<Integer, Card> symPieceById = new LinkedHashMap<>();
        for (Object[] offer : symOffers) {
            SpellAbility osa = (SpellAbility) offer[0];
            Card piece = (Card) offer[1];
            req.option(id, (String) offer[2],
                    osa.getPayCosts() != null ? osa.getPayCosts().toSimpleString() : null,
                    "SYMMETRY");
            byId.put(id, osa);
            symPieceById.put(id, piece);
            id++;
        }

        JsonNode resp = bus.exchange(req);
        if (resp == null) {
            // timeout / IO / silent brain — never hang; let stock decide
            return super.chooseSpellAbilityToPlay();
        }
        JsonNode chosen = resp.get("chosenId");
        if (chosen == null || !chosen.isInt()) {
            return super.chooseSpellAbilityToPlay();
        }
        int chosenId = chosen.asInt();
        if (chosenId == 0) {
            return null; // explicit pass
        }
        SpellAbility pick = byId.get(chosenId);
        if (pick == null) {
            // unknown id — treat as unparseable and fall back to stock
            return super.chooseSpellAbilityToPlay();
        }
        Card symPiece = symPieceById.get(chosenId);
        if (symPiece != null) {
            // the upcoming CostTapType payment for this SA taps THIS card
            pendingTapPreference.put(pick, symPiece);
            pendingTapPreference.put(pick.getRootAbility(), symPiece);
        }
        return Collections.singletonList(pick);
    }

    /**
     * The ACTUAL AI cast path is PhaseHandler.chooseSpellAbilityToPlay ->
     * playChosenSpellAbility -> ComputerUtil.handlePlayingSpellAbility, and
     * that path NEVER announces X (verified: 0 CHOOSE_NUMBER wakes across every
     * game). announceRequirements below is the HUMAN cast path and is never
     * reached for an AI/mailbox cast — so a brain-chosen X spell resolved at
     * its default X=0 (Genesis Wave/Hydra/Ballista/Finale all died 0/0). The
     * real fix lives here: announce mana X on the cast path before delegating.
     * 2026-08-10, corrects the mis-hooked field-note-15b attempt.
     */
    @Override
    public boolean playChosenSpellAbility(SpellAbility sa) {
        if (sa == null || sa.isLandAbility()) {
            return super.playChosenSpellAbility(sa); // null / land: unchanged
        }
        // Affordability guard (2026-08-17): if the seat cannot actually pay
        // for this spell right now (commander tax, colour, whatever), refuse
        // it HERE and keep priority — never hand it to
        // handlePlayingSpellAbility, whose failed-payment path moves the card
        // stack->stack and invalidates it (upstream FIXME: "stuck on stack
        // zone ... nowhere to be found"). Mana abilities are exempt (they ARE
        // the payment). Fail-open: if the check itself throws, play as before.
        if (sa.isSpell() && !sa.isManaAbility()) {
            boolean payable = true;
            try {
                sa.setActivatingPlayer(getPlayer());
                payable = ComputerUtilCost.canPayCost(sa, getPlayer(), false);
            } catch (RuntimeException ignore) {
                payable = true;
            }
            if (!payable) {
                Card h = sa.getHostCard();
                System.err.println("[mailbox seat " + seatIndex + "] REFUSED unaffordable cast: "
                        + (h != null ? h.getName() : sa) + " — cost not payable now (kept in zone)");
                return true; // keep priority; brain gets a fresh window with the same options
            }
        }
        // (1) Announce mana X on the cast path (601.2b) — the stock AI path never
        // does, so a brain's X spell resolved at default X=0. Cancel -> keep
        // priority so the brain can float mana and re-cast.
        if (needsManaX(sa)) {
            org.apache.commons.lang3.Range<Integer> r =
                    AbilityUtils.getAnnouncementBounds(sa, "X");
            Integer x = mailboxManaX(sa, r.getMinimum(), r.getMaximum());
            if (x == null) {
                return true;
            }
            sa.setXManaCostPaid(x);
        }
        // (2) MODAL (Charm) spells choose their mode INSIDE the cast
        // (CharmEffect.makeChoices runs within handlePlayingSpellAbility), which
        // is AFTER any pre-targeting — so the chosen mode's target was never set
        // and the card was lost ("Couldn't add to stack, failed to target",
        // observed on Collective Resistance 2026-08-10). Cast it directly with
        // OUR targeting as the chooseTargets runnable: handlePlayingSpellAbility
        // runs that runnable AFTER makeChoices and before the stack-add, so the
        // mode's target is set at the right moment. (Stock's deferred runnable
        // only handled TargetingPlayer, which is why modal targets were lost.)
        if (sa.getApi() == ApiType.Charm) {
            ComputerUtil.handlePlayingSpellAbility(getPlayer(), sa, () -> {
                // Target the CHAINED MODES, never the Charm shell. Calling
                // chooseTargetsFor(sa) on the shell fell through to stock
                // (no TargetRestrictions on a Charm) -> brains.doTrigger ->
                // CharmAi, which does sa.setSubAbility(null) and re-picks the
                // mode by its own logic — silently discarding the mode the
                // seat chose. Result: a non-targeted mode (Archdruid's Charm
                // tutor, Green Sun's Zenith-class) resolved as an EMPTY Charm:
                // "found nothing", card to graveyard, brain never asked which
                // card to fetch (2026-08-17, Selvala's lost Craterhoof turn).
                for (SpellAbility mode = sa.getSubAbility(); mode != null;
                        mode = mode.getSubAbility()) {
                    if (!mode.usesTargeting()) {
                        continue;
                    }
                    try {
                        chooseTargetsFor(mode);
                    } catch (RuntimeException ignore) {
                        // targeting must never crash the seat
                    }
                }
            });
            return true;
        }
        // (3) NON-modal targeted spell: pre-set targets BEFORE the cast so we
        // can gracefully keep the card in hand if none can be chosen (rather
        // than orphaning it on the stack). The AI cast path otherwise never runs
        // the spell target chooser, so auras/removal reached the stack
        // untargeted and vanished — this hits every deck (aura ramp, targeted
        // removal/pump). chooseTargetsFor: single-target -> CHOOSE_ENTITY over
        // getAllCandidates (all GameEntity kinds); multi-target -> stock.
        forge.game.spellability.TargetRestrictions tgt = sa.getTargetRestrictions();
        Card host = sa.getHostCard();
        boolean requiredTargets = tgt != null && host != null
                && tgt.getMinTargets(host, sa) > 0;
        if (requiredTargets && !sa.isTargetNumberValid()) {
            if (!chooseTargetsFor(sa)) {
                sa.resetTargets();
                return true;
            }
        }
        boolean played = super.playChosenSpellAbility(sa);
        // FIZZLE-2 diagnostic (game 7, 2026-08-17): a required-target spell we
        // pre-targeted reached resolution with EMPTY TargetChoices ("[arena]
        // FIZZLE ... (none set)"). If the cast path ever swaps the SA object
        // (addExtraKeywordCost wrapping, splice re-targeting) or drops the
        // choices between pre-targeting and stack-add, say so AT CAST TIME —
        // the resolution-side FIZZLE line alone can't distinguish the two.
        if (requiredTargets && sa.isSpell()) {
            try {
                boolean sameSaOnStack = false;
                forge.game.spellability.SpellAbilityStackInstance swapped = null;
                for (forge.game.spellability.SpellAbilityStackInstance si
                        : getGame().getStack()) {
                    SpellAbility onStack = si.getSpellAbility();
                    if (onStack == sa) {
                        sameSaOnStack = true;
                        if (!onStack.isTargetNumberValid()) {
                            System.err.println("[arena] TARGETLOSS seat " + seatIndex
                                    + ": " + host.getName() + " reached the stack with "
                                    + "invalid/empty targets right after pre-targeting");
                        }
                        break;
                    }
                    if (onStack != null && onStack.getHostCard() != null
                            && host.getName().equals(onStack.getHostCard().getName())) {
                        swapped = si;
                    }
                }
                if (!sameSaOnStack && swapped != null) {
                    SpellAbility other = swapped.getSpellAbility();
                    System.err.println("[arena] SA-SWAP seat " + seatIndex + ": stack "
                            + "instance for " + host.getName() + " holds a DIFFERENT "
                            + "SpellAbility object than the one the seat targeted "
                            + "(targetsValid=" + other.isTargetNumberValid() + ")");
                }
            } catch (RuntimeException ignore) {
                // diagnostics must never break the cast path
            }
        }
        return played;
    }

    /** True for a spell whose X the card doesn't set itself (mirrors
     *  PlaySpellAbility: Count$xPaid or empty SVar with an X in the cost). */
    private static boolean needsManaX(SpellAbility sa) {
        Cost cost = sa.getPayCosts();
        if (cost == null || !cost.hasXInAnyCostPart()) {
            return false;
        }
        String sVar = sa.getParamOrDefault("XAlternative", sa.getSVar("X"));
        return "Count$xPaid".equals(sVar) || sVar.isEmpty();
    }

    /**
     * Mailbox a mana-X ('X'/'Y') announcement. Returns the X to pay, or null if
     * the brain answered -1 to CANCEL the cast (so it can float mana and
     * re-cast). The ceiling counts the floating pool + untapped sources (same
     * math stock uses), so an announced X is always payable; a silent/failed
     * brain gets that affordable ceiling, never a silent 0.
     */
    private Integer mailboxManaX(SpellAbility ability, int min, int max) {
        Game game = getGame();
        int hi = max;
        try {
            int afford = ComputerUtilMana.determineLeftoverMana(
                    ability, getPlayer(), false);
            if (afford >= 0) {
                hi = Math.min(hi, afford);
            }
        } catch (RuntimeException ignored) {
            // best-effort ceiling; max stands
        }
        if (hi < min) {
            hi = min;
        }
        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("min", min);
        state.put("max", hi);
        state.put("cancelable", true);
        Card host = ability.getHostCard();
        String what = host != null ? host.getName() : String.valueOf(ability);
        String prompt = "Announce 'X' for " + what + " — pick a number in ["
                + min + ", " + hi + "] (max counts your floating pool + untapped "
                + "sources). ";
        prompt += (hi == 0)
                ? "Your affordable X RIGHT NOW is 0 — you have floated no mana. "
                  + "Almost certainly answer -1 to CANCEL, then activate mana "
                  + "abilities (commander, Cradle-class lands, untappers) and "
                  + "re-cast for a real X."
                : "Answer -1 to CANCEL the cast instead (do that when max is far "
                  + "below your intent; float mana, then re-cast).";
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "CHOOSE_NUMBER", prompt)
                .state(state);
        JsonNode resp = bus.exchange(req);
        if (resp != null) {
            JsonNode chosen = resp.get("chosen");
            if (chosen != null && chosen.isInt()) {
                int n = chosen.asInt();
                if (n == -1) {
                    return null; // CANCEL
                }
                if (n >= min && n <= hi) {
                    return n;
                }
            }
        }
        return hi; // bus failure / malformed: affordable max, never a silent 0
    }

    /**
     * Human cast path (kept correct for completeness; not reached for AI casts).
     * Delegates mana X to the same mailbox helper; a CANCEL becomes an
     * unpayable value so PlaySpellAbility rewinds the cast (CR 733.1).
     */
    @Override
    public Integer announceRequirements(SpellAbility ability, int min, int max,
                                        String announce) {
        if ("X".equals(announce) || "Y".equals(announce)) {
            Integer x = mailboxManaX(ability, min, max);
            return x == null ? max + 1000 : x;
        }
        return super.announceRequirements(ability, min, max, announce);
    }

    /**
     * Targeting for mailbox-originated plays (field note 14). Stock's
     * chooseTargetsFor re-runs the api-specific AI heuristics the mailbox
     * path deliberately bypassed — and those heuristics can DECLINE
     * (return false), silently fizzling the brain's chosen play (observed:
     * Lightning Greaves' equip fizzled three times in one game). For
     * single-target abilities the brain now picks the target itself;
     * multi-target and anything unusual falls back to stock, which is never
     * worse than the status quo.
     */
    @Override
    public boolean chooseTargetsFor(SpellAbility currentAbility) {
        try {
            forge.game.spellability.TargetRestrictions tgt =
                    currentAbility.getTargetRestrictions();
            Card host = currentAbility.getHostCard();
            if (tgt == null || host == null) {
                return super.chooseTargetsFor(currentAbility);
            }
            int minT = tgt.getMinTargets(host, currentAbility);
            int maxT = tgt.getMaxTargets(host, currentAbility);
            if (maxT != 1) {
                return super.chooseTargetsFor(currentAbility); // multi-target: stock
            }
            Game game = getGame();
            // Candidates are GameObjects: players/cards for ordinary
            // targeting, and STACK ITEMS (SpellAbility objects) for
            // spell/ability targeting. The seat used to feed
            // tgt.getAllCandidates() straight through, which for a
            // "target spell" ability lists the spell's HOST CARD sitting in
            // the Stack zone — the seat then targeted the CARD, a legal-
            // looking target that CounterEffect (getTargetSpells) never
            // sees: every counterspell a seat targeted itself resolved as a
            // no-op (Fierce Guardianship + Swan Song vs Generous Gift, game 7
            // 2026-08-17; the game-5 fizzle). Stock CounterAi and the human
            // TargetSelection both target si.getSpellAbility(); so do we now.
            boolean stackTargeting = tgt.getZone() != null
                    && tgt.getZone().contains(ZoneType.Stack);
            List<forge.game.GameObject> candidates = new ArrayList<>();
            if (stackTargeting) {
                for (forge.game.spellability.SpellAbilityStackInstance si
                        : game.getStack()) {
                    SpellAbility onStack = si.getSpellAbility();
                    if (onStack != null && onStack != currentAbility
                            && currentAbility.canTargetSpellAbility(onStack)) {
                        candidates.add(onStack);
                    }
                }
                // "target spell or permanent"-style: keep any non-stack
                // GameEntity candidates too (never the stack-zone cards).
                List<forge.game.GameEntity> ents = tgt.getAllCandidates(currentAbility);
                if (ents != null) {
                    for (forge.game.GameEntity e : ents) {
                        if (e instanceof Card && ((Card) e).isInZone(ZoneType.Stack)) {
                            continue;
                        }
                        candidates.add(e);
                    }
                }
            } else {
                List<forge.game.GameEntity> ents = tgt.getAllCandidates(currentAbility);
                if (ents != null) {
                    candidates.addAll(ents);
                }
            }
            if (candidates.isEmpty()) {
                return super.chooseTargetsFor(currentAbility);
            }
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", minT);
            state.put("max", 1);
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CHOOSE_ENTITY",
                    "Choose the TARGET for " + host.getName() + " ("
                            + currentAbility + ").")
                    .state(state);
            if (minT == 0) {
                req.option(0, "No target (decline)", null, "NONE");
            } else if (triggerAimDepth > 0) {
                // aiming one of the seat's own OPTIONAL triggers: declining is
                // always legal (the trigger will be auto-aimed to stack legally
                // and auto-declined at resolution — it does nothing)
                req.option(0, "DECLINE this optional trigger (it will do nothing)",
                        null, "NONE");
            }
            Map<Integer, forge.game.GameObject> byId = new LinkedHashMap<>();
            int id = 1;
            for (forge.game.GameObject e : candidates) {
                String label;
                String kind;
                if (e instanceof SpellAbility) {
                    SpellAbility s = (SpellAbility) e;
                    Card sh = s.getHostCard();
                    Player ap = s.getActivatingPlayer();
                    String desc;
                    try {
                        desc = s.getStackDescription();
                    } catch (RuntimeException ignore) {
                        desc = "";
                    }
                    label = (sh != null ? sh.getName() : "?")
                            + (s.isSpell() ? " (spell)" : s.isTrigger() ? " (trigger)" : " (ability)")
                            + " [" + (ap != null ? ap.getName() : "?") + "]"
                            + (desc != null && !desc.isEmpty()
                                ? " — " + (desc.length() > 90 ? desc.substring(0, 90) : desc) : "");
                    kind = "STACK";
                } else if (e instanceof Card) {
                    Card c = (Card) e;
                    label = c.getName()
                            + (c.isCreature() ? " " + c.getNetPower() + "/"
                                + c.getNetToughness() : "")
                            + " [" + c.getController().getName() + "]";
                    kind = "CARD";
                } else {
                    label = ((forge.game.GameEntity) e).getName();
                    kind = "PLAYER";
                }
                req.option(id, label, null, kind);
                byId.put(id, e);
                id++;
            }
            JsonNode resp = bus.exchange(req);
            if (resp != null) {
                JsonNode chosen = resp.get("chosenId");
                if (chosen != null && chosen.isInt()) {
                    int cid = chosen.asInt();
                    if (cid == 0 && minT == 0) {
                        return true; // legal decline; ability proceeds untargeted
                    }
                    if (cid == 0 && triggerAimDepth > 0) {
                        return false; // trigger decline: caller auto-aims + auto-declines
                    }
                    forge.game.GameObject pick = byId.get(cid);
                    if (pick != null) {
                        currentAbility.resetTargets();
                        if (currentAbility.getTargets().add(pick)) {
                            return true;
                        }
                    }
                }
            }
        } catch (RuntimeException anything) {
            // targeting must never crash the seat — stock is the floor
        }
        if (triggerAimDepth > 0) {
            // inside trigger aiming, stock's silent aim would override the
            // seat's intent — report failure and let the caller handle it
            return false;
        }
        return super.chooseTargetsFor(currentAbility);
    }

    @Override
    public boolean mulliganKeepHand(Player firstPlayer, int cardsToReturn) {
        Game game = getGame();
        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("cardsToReturn", cardsToReturn);
        state.put("hand", ownZone(ZoneType.Hand));
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "MULLIGAN",
                "Keep this hand, or mulligan?")
                .state(state)
                .option(1, "Keep", null, "KEEP")
                .option(0, "Mulligan", null, "MULLIGAN");
        JsonNode resp = bus.exchange(req);
        if (resp == null) {
            return super.mulliganKeepHand(firstPlayer, cardsToReturn);
        }
        JsonNode keep = resp.get("keep");
        if (keep == null || !keep.isBoolean()) {
            return super.mulliganKeepHand(firstPlayer, cardsToReturn);
        }
        return keep.asBoolean();
    }

    @Override
    public void declareAttackers(Player attacker, Combat combat) {
        Game game = getGame();
        Player me = getPlayer();
        // enumerate creatures that can attack at least one defender
        List<GameEntity> defenders = new ArrayList<>();
        for (GameEntity ge : combat.getDefenders()) {
            defenders.add(ge);
        }
        List<Card> candidates = new ArrayList<>();
        for (Card c : me.getCreaturesInPlay()) {
            boolean any = false;
            for (GameEntity d : defenders) {
                if (CombatUtil.canAttack(c, d)) {
                    any = true;
                    break;
                }
            }
            if (any) {
                candidates.add(c);
            }
        }
        if (candidates.isEmpty()) {
            super.declareAttackers(attacker, combat);
            return;
        }

        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("defenders", defenderList(defenders));
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "DECLARE_ATTACKERS",
                "Assign attackers to defenders (empty = attack with nobody).")
                .state(state);
        Map<Integer, Card> byId = new LinkedHashMap<>();
        for (Card c : candidates) {
            req.option(c.getId(), creatureLabel(c), null, "ATTACKER");
            byId.put(c.getId(), c);
        }

        JsonNode resp = bus.exchange(req);
        if (resp == null || resp.get("attackers") == null || !resp.get("attackers").isArray()) {
            super.declareAttackers(attacker, combat);
            return;
        }
        // Validate the WHOLE assignment before mutating combat, so a malformed
        // entry cleanly falls back to stock instead of leaving a half-built
        // combat that stock would then add to.
        List<Card> attackCards = new ArrayList<>();
        List<GameEntity> attackTargets = new ArrayList<>();
        for (JsonNode entry : resp.get("attackers")) {
            JsonNode a = entry.get("attacker");
            JsonNode d = entry.get("defender");
            if (a == null || !a.isInt()) {
                super.declareAttackers(attacker, combat);
                return;
            }
            Card card = byId.get(a.asInt());
            GameEntity defender = card == null ? null : chooseDefender(defenders, d, card);
            if (card == null || defender == null || !CombatUtil.canAttack(card, defender)) {
                super.declareAttackers(attacker, combat);
                return;
            }
            attackCards.add(card);
            attackTargets.add(defender);
        }
        for (int i = 0; i < attackCards.size(); i++) {
            combat.addAttacker(attackCards.get(i), attackTargets.get(i));
        }
        // Per-attacker canAttack (above) does NOT cover the aggregate attack rules
        // — "must attack / attacks each combat if able", "can't attack alone", band
        // constraints. validateAttackers checks the whole assignment against the
        // AttackConstraints; if the brain's attack is illegal (more avoidable
        // violations than a legal attack), drop it and let stock AI declare a legal
        // one (mirrors the malformed-input fallback above).
        if (!CombatUtil.validateAttackers(combat)) {
            combat.clearAttackers();
            super.declareAttackers(attacker, combat);
        }
    }

    @Override
    public void declareBlockers(Player defender, Combat combat) {
        Game game = getGame();
        Player me = getPlayer();
        List<Card> attackers = new ArrayList<>();
        for (Card c : combat.getAttackers()) {
            attackers.add(c);
        }
        if (attackers.isEmpty()) {
            super.declareBlockers(defender, combat);
            return;
        }
        List<Card> blockerCandidates = new ArrayList<>();
        for (Card c : me.getCreaturesInPlay()) {
            if (CombatUtil.canBlock(c, combat)) {
                blockerCandidates.add(c);
            }
        }
        if (blockerCandidates.isEmpty()) {
            super.declareBlockers(defender, combat);
            return;
        }

        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        List<Map<String, Object>> atkList = new ArrayList<>();
        Map<Integer, Card> attackerById = new LinkedHashMap<>();
        for (Card c : attackers) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", c.getId());
            m.put("label", creatureLabel(c));
            atkList.add(m);
            attackerById.put(c.getId(), c);
        }
        state.put("attackers", atkList);
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "DECLARE_BLOCKERS",
                "Assign blockers to attackers (empty = no blocks).")
                .state(state);
        Map<Integer, Card> blockerById = new LinkedHashMap<>();
        for (Card c : blockerCandidates) {
            req.option(c.getId(), creatureLabel(c), null, "BLOCKER");
            blockerById.put(c.getId(), c);
        }

        JsonNode resp = bus.exchange(req);
        if (resp == null || resp.get("blocks") == null || !resp.get("blocks").isArray()) {
            super.declareBlockers(defender, combat);
            return;
        }
        List<Card> blockCards = new ArrayList<>();
        List<Card> blockAttackers = new ArrayList<>();
        for (JsonNode entry : resp.get("blocks")) {
            JsonNode b = entry.get("blocker");
            JsonNode a = entry.get("attacker");
            if (b == null || !b.isInt() || a == null || !a.isInt()) {
                super.declareBlockers(defender, combat);
                return;
            }
            Card blocker = blockerById.get(b.asInt());
            Card atk = attackerById.get(a.asInt());
            if (blocker == null || atk == null || !CombatUtil.canBlock(atk, blocker, combat)) {
                super.declareBlockers(defender, combat);
                return;
            }
            blockCards.add(blocker);
            blockAttackers.add(atk);
        }
        for (int i = 0; i < blockCards.size(); i++) {
            combat.addBlocker(blockAttackers.get(i), blockCards.get(i));
        }
        // Per-blocker canBlock (above) does NOT cover the aggregate block rules —
        // menace/min-blockers, max-blockers ("can't be blocked by more than one"),
        // must-block/provoke/lure, "can't block alone". validateBlocks checks the
        // whole assignment and returns a non-null reason when illegal (e.g. one
        // creature declared onto a menace attacker); undo the blocks and let stock
        // AI declare a legal set.
        String invalidBlocks = CombatUtil.validateBlocks(combat, defender);
        if (invalidBlocks != null && !invalidBlocks.isEmpty()) {
            for (Card b : blockCards) {
                combat.undoBlockingAssignment(b);
            }
            super.declareBlockers(defender, combat);
        }
    }

    // ---- sub-choice hooks (agent makes its own significant sub-decisions) ---

    /**
     * Single "choose a creature/permanent" effect — this is the hook that
     * carries Glasspool Mimic's "copy which creature" choice and generic Clone /
     * choose-a-permanent effects (see {@code CloneEffect} et al., which call the
     * convenience overloads that funnel here). We mailbox it ONLY when it is a
     * genuine choice among {@link Card} entities (so option ids are unambiguous
     * card ids); every other case — a forced single option, an empty list, or a
     * non-card option such as "choose a player" — falls straight through to
     * stock. On timeout / null / malformed / illegal id we also fall to stock.
     */
    @Override
    public <T extends GameEntity> T chooseSingleEntityForEffect(
            FCollectionView<T> optionList, DelayedReveal delayedReveal, SpellAbility sa,
            String title, boolean isOptional, Player relatedPlayer, Map<String, Object> params) {
        List<T> opts = optionList == null ? Collections.<T>emptyList() : new ArrayList<>(optionList);
        // Gate to a genuine, card-only choice. A lone forced option or a
        // non-card entity (e.g. a player) is not worth mailboxing.
        boolean meaningful = opts.size() > 1 || (isOptional && opts.size() == 1);
        if (!meaningful || !allCards(opts)) {
            return super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, relatedPlayer, params);
        }
        Game game = getGame();
        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("min", isOptional ? 0 : 1);
        state.put("max", 1);
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "CHOOSE_ENTITY",
                (title != null && !title.isEmpty() ? title : "Choose one")
                        + (isOptional ? " (or none)" : ""))
                .state(state);
        if (isOptional) {
            req.option(0, "Choose none", null, "NONE"); // id 0 reserved for "none"
        }
        Map<Integer, T> byId = new LinkedHashMap<>();
        for (T e : opts) {
            int oid = e.getId();
            if (oid <= 0 || byId.containsKey(oid)) {
                // 0 is reserved for "none"; a collision means an ambiguous id
                // space we can't safely round-trip — let stock decide.
                return super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, relatedPlayer, params);
            }
            req.option(oid, entityLabel(e), null, entityType(e));
            byId.put(oid, e);
        }
        JsonNode resp = bus.exchange(req);
        if (resp == null) {
            return super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, relatedPlayer, params);
        }
        JsonNode chosen = resp.get("chosenId");
        if (chosen == null || !chosen.isInt()) {
            return super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, relatedPlayer, params);
        }
        int cid = chosen.asInt();
        if (cid == 0) {
            return isOptional ? null
                    : super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, relatedPlayer, params);
        }
        T pick = byId.get(cid);
        return pick != null ? pick
                : super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, relatedPlayer, params);
    }

    /**
     * Bounded multi-entity selection (min..max). Same discipline as
     * {@link #chooseSingleEntityForEffect}: mailbox only a genuine, card-only
     * choice (skip empty lists, forced "take all", or non-card options). The
     * brain must return a subset satisfying min/max with no duplicates; anything
     * else (or a timeout) falls back to stock. Note that if this override falls
     * back to {@code super}, the stock loop itself calls
     * {@code chooseSingleEntityForEffect} — so single picks may still be
     * mailboxed one at a time; that is a safe degradation, not a hang.
     */
    @Override
    public <T extends GameEntity> List<T> chooseEntitiesForEffect(
            FCollectionView<T> optionList, int min, int max, DelayedReveal delayedReveal,
            SpellAbility sa, String title, Player relatedPlayer, Map<String, Object> params) {
        List<T> opts = optionList == null ? Collections.<T>emptyList() : new ArrayList<>(optionList);
        int lo = Math.max(0, min);
        // Nothing to decide when empty, max<=0, forced "take all" (lo>=size), or
        // any option is not a Card.
        if (opts.isEmpty() || max <= 0 || lo >= opts.size() || !allCards(opts)) {
            return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, relatedPlayer, params);
        }
        int hi = Math.min(max, opts.size());
        Game game = getGame();
        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("min", lo);
        state.put("max", hi);
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "CHOOSE_ENTITIES",
                (title != null && !title.isEmpty() ? title : "Choose")
                        + " (" + lo + "-" + hi + ")")
                .state(state);
        Map<Integer, T> byId = new LinkedHashMap<>();
        for (T e : opts) {
            int oid = e.getId();
            if (oid <= 0 || byId.containsKey(oid)) {
                return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, relatedPlayer, params);
            }
            req.option(oid, entityLabel(e), null, entityType(e));
            byId.put(oid, e);
        }
        JsonNode resp = bus.exchange(req);
        if (resp == null || resp.get("chosen") == null || !resp.get("chosen").isArray()) {
            return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, relatedPlayer, params);
        }
        List<T> picks = new ArrayList<>();
        Set<Integer> seen = new HashSet<>();
        for (JsonNode idn : resp.get("chosen")) {
            if (idn == null || !idn.isInt()) {
                return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, relatedPlayer, params);
            }
            int cid = idn.asInt();
            if (!byId.containsKey(cid) || !seen.add(cid)) { // illegal id or duplicate
                return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, relatedPlayer, params);
            }
            picks.add(byId.get(cid));
        }
        if (picks.size() < lo || picks.size() > hi) { // wrong count — never partially apply
            return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, relatedPlayer, params);
        }
        return picks;
    }

    // ---- sacrifice: the seat picks what dies (2026-08-24) -------------------

    /**
     * Sacrifice COST payment ({@link forge.ai.SacCostPreference}, consulted by
     * {@code AiCostDecision.visit(CostSacrifice)} at actual payment time —
     * never during affordability scans). The seat already chose the outlet
     * activation or sacrifice-cost cast in its window; this names WHICH
     * card(s) pay, instead of stock's worst-card heuristics. When the valid
     * set is exactly the required amount the payment is forced — answer
     * locally, no model call. {@code null} on anything odd → stock decides,
     * exactly as before the hook existed.
     */
    @Override
    public CardCollection preferredSacCards(SpellAbility ability, String type, int amount) {
        try {
            Player me = getPlayer();
            Card host = ability != null ? ability.getHostCard() : null;
            CardCollection valid = CardLists.getValidCards(
                    me.getCardsIn(ZoneType.Battlefield), type.split(";"), me, host, ability);
            if (amount <= 0 || valid.size() < amount) {
                return null;
            }
            if (valid.size() == amount) {
                return valid; // forced payment — nothing to decide
            }
            List<Card> picked = cardChoiceViaSeat(
                    "SACRIFICE PAYMENT for " + (host != null ? host.getName() : "an ability")
                            + (ability != null ? " (" + ability.toString() + ")" : "")
                            + " — choose exactly " + amount,
                    valid, amount, amount);
            return picked == null ? null : new CardCollection(picked);
        } catch (RuntimeException e) {
            return null;
        }
    }

    /**
     * Sacrifice by EFFECT (edicts, Innocent-Blood-class symmetrical
     * sacrifices, Balance): stock sent these to
     * {@code ComputerUtil.choosePermanentsToSacrifice} worst-card heuristics
     * — the seat could never keep the death-trigger body or feed the token
     * it wanted gone. Same discipline as every surface: a genuine choice is
     * mailboxed, a forced/degenerate one is not, and any invalid answer or
     * error falls back to stock.
     */
    @Override
    public CardCollectionView choosePermanentsToSacrifice(SpellAbility sa, int min, int max,
            CardCollectionView validTargets, String message) {
        List<Card> picked = permanentsChoiceViaSeat("SACRIFICE", sa, min, max, validTargets, message);
        return picked != null ? new CardCollection(picked)
                : super.choosePermanentsToSacrifice(sa, min, max, validTargets, message);
    }

    /** Same seam as {@link #choosePermanentsToSacrifice} — stock routes both
     *  through the same heuristic chooser. */
    @Override
    public CardCollectionView choosePermanentsToDestroy(SpellAbility sa, int min, int max,
            CardCollectionView validTargets, String message) {
        List<Card> picked = permanentsChoiceViaSeat("DESTROY", sa, min, max, validTargets, message);
        return picked != null ? new CardCollection(picked)
                : super.choosePermanentsToDestroy(sa, min, max, validTargets, message);
    }

    /** Shared body for the two permanent-choice effects: null → caller falls
     *  back to stock. min==0 keeps the decline in the seat's hands (empty
     *  {@code chosen} is a legal answer). */
    private List<Card> permanentsChoiceViaSeat(String kind, SpellAbility sa, int min, int max,
            CardCollectionView validTargets, String message) {
        try {
            List<Card> opts = validTargets == null
                    ? Collections.<Card>emptyList() : new ArrayList<>(validTargets);
            int lo = Math.max(0, min);
            int hi = Math.min(max, opts.size());
            if (opts.isEmpty() || hi <= 0) {
                return null;
            }
            if (lo >= opts.size()) {
                return opts; // forced — everything valid must go; no model call
            }
            Card host = sa != null ? sa.getHostCard() : null;
            return cardChoiceViaSeat(
                    kind + " " + lo + "-" + hi
                            + (message != null && !message.isEmpty() ? " [" + message + "]" : "")
                            + (host != null ? " (source: " + host.getName() + ")" : ""),
                    opts, lo, hi);
        } catch (RuntimeException e) {
            return null;
        }
    }

    /** One bounded pick-cards exchange: CHOOSE_ENTITIES over {@code opts},
     *  answer must be {@code lo..hi} distinct known ids; anything else →
     *  {@code null} (caller falls back). */
    private List<Card> cardChoiceViaSeat(String prompt, List<Card> opts, int lo, int hi) {
        Game game = getGame();
        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("min", lo);
        state.put("max", hi);
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "CHOOSE_ENTITIES",
                prompt + " (answer {\"chosen\": [ids]})")
                .state(state);
        Map<Integer, Card> byId = new LinkedHashMap<>();
        for (Card c : opts) {
            int oid = c.getId();
            if (oid <= 0 || byId.containsKey(oid)) {
                return null;
            }
            req.option(oid, cardChoiceLabel(c),
                    c.getManaCost() != null ? c.getManaCost().toString() : null, typeHint(c));
            byId.put(oid, c);
        }
        JsonNode resp = bus.exchange(req);
        if (resp == null || resp.get("chosen") == null || !resp.get("chosen").isArray()) {
            return null;
        }
        List<Card> picked = new ArrayList<>();
        Set<Integer> seen = new HashSet<>();
        for (JsonNode n : resp.get("chosen")) {
            if (n == null || !n.isInt()) {
                return null;
            }
            Card c = byId.get(n.asInt());
            if (c == null || !seen.add(n.asInt())) {
                return null;
            }
            picked.add(c);
        }
        if (picked.size() < lo || picked.size() > hi) {
            return null;
        }
        return picked;
    }

    /**
     * Modal / charm mode selection ({@code CharmEffect} calls this). Options are
     * the mode texts; the id is the INDEX into {@code possible}. The brain
     * returns a list of chosen indices (respecting {@code allowRepeat} and the
     * min..num count). Mailboxed only when there is more than one mode; otherwise
     * (or on any malformed / out-of-range / wrong-count response) → stock.
     */
    @Override
    public List<AbilitySub> chooseModeForAbility(SpellAbility sa, List<AbilitySub> possible,
            int min, int num, boolean allowRepeat) {
        if (possible == null || possible.size() <= 1) {
            return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
        }
        int lo = Math.max(0, min);
        Game game = getGame();
        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("min", lo);
        state.put("max", num);
        state.put("allowRepeat", allowRepeat);
        Card host = sa != null ? sa.getHostCard() : null;
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "CHOOSE_MODE",
                "Choose mode(s) for " + (host != null ? host.getName() : "ability")
                        + " (" + lo + "-" + num + (allowRepeat ? ", may repeat" : "") + ")")
                .state(state);
        for (int i = 0; i < possible.size(); i++) {
            AbilitySub sub = possible.get(i);
            String desc = sub != null ? sub.getDescription() : null;
            if (desc == null || desc.isEmpty()) {
                desc = sub != null ? sub.getStackDescription() : null;
            }
            req.option(i, desc != null && !desc.isEmpty() ? desc : ("mode " + i), null, "MODE");
        }
        JsonNode resp = bus.exchange(req);
        if (resp == null || resp.get("chosen") == null || !resp.get("chosen").isArray()) {
            return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
        }
        List<AbilitySub> chosen = new ArrayList<>();
        Set<Integer> seen = new HashSet<>();
        for (JsonNode idn : resp.get("chosen")) {
            if (idn == null || !idn.isInt()) {
                return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
            }
            int idx = idn.asInt();
            if (idx < 0 || idx >= possible.size()) {
                return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
            }
            if (!allowRepeat && !seen.add(idx)) { // repeat not permitted
                return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
            }
            chosen.add(possible.get(idx));
        }
        if (chosen.size() < lo || chosen.size() > num) { // wrong count
            return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
        }
        return chosen;
    }

    /**
     * Tutor / search-and-move card selection (fetch effects go through here). The
     * engine hands us {@code fetchList} — the cards this seat is legally allowed
     * to pick from (searching your own library reveals them to YOU), so exposing
     * their names to this seat's brain is hidden-info-safe. Mailboxed only for a
     * genuine choice; forced single / empty, or any malformed / illegal response,
     * → stock. We do NOT override the plural {@code chooseCardsForZoneChange}
     * (stock returns null / "this isn't used").
     */
    @Override
    public Card chooseSingleCardForZoneChange(ZoneType destination, List<ZoneType> origin,
            SpellAbility sa, CardCollection fetchList, DelayedReveal delayedReveal,
            String selectPrompt, boolean isOptional, Player decider) {
        List<Card> opts = fetchList == null ? Collections.<Card>emptyList() : new ArrayList<>(fetchList);
        boolean meaningful = opts.size() > 1 || (isOptional && opts.size() == 1);
        if (!meaningful) {
            return super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList, delayedReveal, selectPrompt, isOptional, decider);
        }
        Game game = getGame();
        int turn = game.getPhaseHandler().getTurn();
        Map<String, Object> state = buildState(turn);
        state.put("min", isOptional ? 0 : 1);
        state.put("max", 1);
        state.put("destination", destination != null ? destination.name() : null);
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "CHOOSE_CARD",
                (selectPrompt != null && !selectPrompt.isEmpty() ? selectPrompt : "Choose a card")
                        + (destination != null ? " -> " + destination.name() : ""))
                .state(state);
        if (isOptional) {
            req.option(0, "Choose none", null, "NONE");
        }
        Map<Integer, Card> byId = new LinkedHashMap<>();
        for (Card c : opts) {
            int oid = c.getId();
            if (oid <= 0 || byId.containsKey(oid)) {
                return super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList, delayedReveal, selectPrompt, isOptional, decider);
            }
            req.option(oid, cardChoiceLabel(c),
                    c.getManaCost() != null ? c.getManaCost().toString() : null, typeHint(c));
            byId.put(oid, c);
        }
        JsonNode resp = bus.exchange(req);
        if (resp == null) {
            return super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList, delayedReveal, selectPrompt, isOptional, decider);
        }
        JsonNode chosen = resp.get("chosenId");
        if (chosen == null || !chosen.isInt()) {
            return super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList, delayedReveal, selectPrompt, isOptional, decider);
        }
        int cid = chosen.asInt();
        if (cid == 0) {
            return isOptional ? null
                    : super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList, delayedReveal, selectPrompt, isOptional, decider);
        }
        Card pick = byId.get(cid);
        return pick != null ? pick
                : super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList, delayedReveal, selectPrompt, isOptional, decider);
    }

    /**
     * Discard selection (backlog item 4, 2026-08-17). Stock picked the seat's
     * discards by heuristic (getCardsToDiscard) — Faithless Looting-class
     * rummage, Sheoldred discards, hellbent costs all bypassed the brain.
     * Engages only when every candidate is visible to this chooser (own hand,
     * or an effect that reveals) — hidden-info discipline over convenience.
     */
    @Override
    public CardCollection chooseCardsToDiscardFrom(Player p, SpellAbility sa,
            CardCollection validCards, int min, int max, CardCollectionView visibleToChooser) {
        try {
            if (validCards == null || validCards.isEmpty() || max <= 0) {
                return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
            }
            int lo = Math.max(0, min);
            int hi = Math.min(max, validCards.size());
            if (lo >= validCards.size()) {
                return new CardCollection(validCards); // forced: all of them
            }
            for (Card c : validCards) {
                if (p != getPlayer() && (visibleToChooser == null || !visibleToChooser.contains(c))) {
                    // choosing from cards we may not see: stock keeps that job
                    return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
                }
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", lo);
            state.put("max", hi);
            Card src = sa != null ? sa.getHostCard() : null;
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CHOOSE_CARDS",
                    "DISCARD " + lo + "-" + hi + " from "
                            + (p == getPlayer() ? "YOUR hand" : p.getName() + "'s cards")
                            + (src != null ? " [source: " + src.getName() + "]" : "")
                            + " (answer {\"chosen\": [ids]})")
                    .state(state);
            Map<Integer, Card> byId = new LinkedHashMap<>();
            for (Card c : validCards) {
                int oid = c.getId();
                if (oid <= 0 || byId.containsKey(oid)) {
                    return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
                }
                req.option(oid, cardChoiceLabel(c),
                        c.getManaCost() != null ? c.getManaCost().toString() : null, typeHint(c));
                byId.put(oid, c);
            }
            JsonNode resp = bus.exchange(req);
            if (resp == null || resp.get("chosen") == null || !resp.get("chosen").isArray()) {
                return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
            }
            CardCollection picked = new CardCollection();
            Set<Integer> seen = new HashSet<>();
            for (JsonNode n : resp.get("chosen")) {
                Card c = n != null && n.isInt() ? byId.get(n.asInt()) : null;
                if (c == null || !seen.add(n.asInt())) {
                    return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
                }
                picked.add(c);
            }
            if (picked.size() < lo || picked.size() > hi) {
                return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
            }
            return picked;
        } catch (RuntimeException e) {
            return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
        }
    }

    /**
     * Face pick from a FINITE list (split/adventure/MDFC prompts). The other
     * chooseSingleCardFace overload (predicate + whole card DB, "name a
     * card") stays stock — the mailbox never ships an unbounded option list.
     */
    @Override
    public forge.card.ICardFace chooseSingleCardFace(SpellAbility sa,
            List<forge.card.ICardFace> faces, String message) {
        try {
            if (faces == null || faces.size() <= 1) {
                return super.chooseSingleCardFace(sa, faces, message);
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", 1);
            state.put("max", 1);
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CHOOSE_CARD",
                    "CHOOSE FACE: " + (message != null ? message : "pick a face")
                            + (sa != null && sa.getHostCard() != null
                                ? " [source: " + sa.getHostCard().getName() + "]" : ""))
                    .state(state);
            Map<Integer, forge.card.ICardFace> byId = new LinkedHashMap<>();
            int id = 1;
            for (forge.card.ICardFace f : faces) {
                String label = f.getName()
                        + (f.getManaCost() != null ? "  " + f.getManaCost() : "")
                        + (f.getType() != null ? " — " + f.getType() : "");
                req.option(id, label, null, "FACE");
                byId.put(id, f);
                id++;
            }
            JsonNode resp = bus.exchange(req);
            if (resp != null && resp.get("chosenId") != null && resp.get("chosenId").isInt()) {
                forge.card.ICardFace pick = byId.get(resp.get("chosenId").asInt());
                if (pick != null) {
                    return pick;
                }
            }
            return super.chooseSingleCardFace(sa, faces, message);
        } catch (RuntimeException e) {
            return super.chooseSingleCardFace(sa, faces, message);
        }
    }

    /** State pick (MDFC "play which side", copy-as choices). */
    @Override
    public forge.game.card.CardState chooseSingleCardState(SpellAbility sa,
            List<forge.game.card.CardState> states, String message, Map<String, Object> params) {
        try {
            if (states == null || states.size() <= 1) {
                return super.chooseSingleCardState(sa, states, message, params);
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", 1);
            state.put("max", 1);
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CHOOSE_CARD",
                    "CHOOSE STATE/SIDE: " + (message != null ? message : "pick a state")
                            + (sa != null && sa.getHostCard() != null
                                ? " [source: " + sa.getHostCard().getName() + "]" : ""))
                    .state(state);
            Map<Integer, forge.game.card.CardState> byId = new LinkedHashMap<>();
            int id = 1;
            for (forge.game.card.CardState st : states) {
                String label = st.getName()
                        + (st.getType() != null ? " — " + st.getType() : "");
                req.option(id, label, null, "STATE");
                byId.put(id, st);
                id++;
            }
            JsonNode resp = bus.exchange(req);
            if (resp != null && resp.get("chosenId") != null && resp.get("chosenId").isInt()) {
                forge.game.card.CardState pick = byId.get(resp.get("chosenId").asInt());
                if (pick != null) {
                    return pick;
                }
            }
            return super.chooseSingleCardState(sa, states, message, params);
        } catch (RuntimeException e) {
            return super.chooseSingleCardState(sa, states, message, params);
        }
    }

    /** "Reduce this cost by up to N" (cost-reduction X). Stock always maxed;
     *  now the brain owns the number. */
    @Override
    public int chooseNumberForCostReduction(SpellAbility sa, int min, int max) {
        try {
            if (max <= min) {
                return super.chooseNumberForCostReduction(sa, min, max);
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", min);
            state.put("max", max);
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CHOOSE_NUMBER",
                    "COST REDUCTION: choose a number " + min + "-" + max
                            + (sa != null && sa.getHostCard() != null
                                ? " for " + sa.getHostCard().getName() : "")
                            + " (answer {\"chosen\": <n>})")
                    .state(state);
            JsonNode resp = bus.exchange(req);
            if (resp != null && resp.get("chosen") != null && resp.get("chosen").isInt()) {
                int n = resp.get("chosen").asInt();
                if (n >= min && n <= max) {
                    return n;
                }
            }
            return super.chooseNumberForCostReduction(sa, min, max);
        } catch (RuntimeException e) {
            return super.chooseNumberForCostReduction(sa, min, max);
        }
    }

    /**
     * Generic "choose N cards for effect" (keep/sacrifice/distribute
     * choices). Same CHOOSE_CARDS shape as discards; falls to stock whenever
     * anything is off-shape.
     */
    @Override
    public CardCollectionView chooseCardsForEffect(CardCollectionView sourceList,
            SpellAbility sa, String title, int min, int max, boolean isOptional,
            Map<String, Object> params) {
        try {
            if (sourceList == null || sourceList.isEmpty() || max <= 0) {
                return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
            }
            int lo = Math.max(0, isOptional ? 0 : min);
            int hi = Math.min(max, sourceList.size());
            if (lo >= sourceList.size()) {
                return new CardCollection(sourceList); // forced: all of them
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", lo);
            state.put("max", hi);
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CHOOSE_CARDS",
                    (title != null && !title.isEmpty() ? title : "Choose cards")
                            + " (choose " + lo + "-" + hi
                            + "; answer {\"chosen\": [ids]})")
                    .state(state);
            Map<Integer, Card> byId = new LinkedHashMap<>();
            for (Card c : sourceList) {
                int oid = c.getId();
                if (oid <= 0 || byId.containsKey(oid)) {
                    return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
                }
                req.option(oid, cardChoiceLabel(c),
                        c.getManaCost() != null ? c.getManaCost().toString() : null, typeHint(c));
                byId.put(oid, c);
            }
            JsonNode resp = bus.exchange(req);
            if (resp == null || resp.get("chosen") == null || !resp.get("chosen").isArray()) {
                return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
            }
            CardCollection picked = new CardCollection();
            Set<Integer> seen = new HashSet<>();
            for (JsonNode n : resp.get("chosen")) {
                Card c = n != null && n.isInt() ? byId.get(n.asInt()) : null;
                if (c == null || !seen.add(n.asInt())) {
                    return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
                }
                picked.add(c);
            }
            if (picked.size() < lo || picked.size() > hi) {
                return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
            }
            return picked;
        } catch (RuntimeException e) {
            return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
        }
    }

    /** Commander tax for casting {@code host} from the command zone right
     *  now (Forge's own formula: 2 x prior casts), else 0. */
    private int commanderTax(SpellAbility sa, Card host) {
        try {
            if (host == null || !sa.isSpell() || !host.isCommander()) {
                return 0;
            }
            if (host.getZone() == null || !host.getZone().is(ZoneType.Command)) {
                return 0;
            }
            return getPlayer().getCommanderCast(host) * 2;
        } catch (RuntimeException e) {
            return 0;
        }
    }

    /** Human-readable total for the label, e.g. "{1}{G}{G} + {4} = 7 mana". */
    private static String describeTotalCost(SpellAbility sa, int tax) {
        try {
            String base = sa.getPayCosts() != null ? sa.getPayCosts().toSimpleString() : "";
            int baseCmc = sa.getPayCosts() != null && sa.getPayCosts().getTotalMana() != null
                    ? sa.getPayCosts().getTotalMana().getCMC() : 0;
            return base + " + {" + tax + "} = " + (baseCmc + tax) + " mana";
        } catch (RuntimeException e) {
            return "+{" + tax + "} tax";
        }
    }

    // ---- unless-costs, multi-card searches, may-confirms (2026-08-17) --------
    // Three surfaces that stock AI had been deciding FOR the brain, with
    // heuristics wrong for the situation:
    //  - payCostToPreventEffect: ChangeZoneAi.willPayUnlessCost refuses to pay
    //    for any non-creature (Transmute Artifact's X -> Mana Vault binned) and
    //    refuses opponents' taxes on our own spells (Mana Leak-class): the
    //    brain never got to say "yes, pay".
    //  - chooseCardsForZoneChange (plural): stock literally returns null, so a
    //    mailbox seat's MULTI-card search (Cultivate/Kodama's Reach, "up to
    //    two") fetched NOTHING.
    //  - confirmAction: "cancel the search?" / "cast this while searching?" /
    //    optional-effect confirms answered by stock heuristics.
    // Every path is fail-open: forced choice, malformed answer, or exception
    // -> super (stock), exactly as before.

    /** "Pay {cost} or {effect happens}" — the brain decides, and pays only
     *  if it can. Answer contract: {"chosenId": 1} = pay, 0 = decline. */
    @Override
    public boolean payCostToPreventEffect(forge.game.cost.Cost cost, SpellAbility sa,
            boolean alreadyPaid, forge.util.collect.FCollectionView<Player> allPayers) {
        try {
            if (alreadyPaid || cost == null || sa == null) {
                return super.payCostToPreventEffect(cost, sa, alreadyPaid, allPayers);
            }
            Player me = getPlayer();
            // Can we even pay? If not, there is nothing to ask.
            if (!ComputerUtilCost.canPayCost(cost, sa, me, true)) {
                return false;
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Card host = sa.getHostCard();
            String effect = sa.getStackDescription();
            if (effect == null || effect.isEmpty()) {
                effect = sa.getDescription();
            }
            boolean mine = sa.getActivatingPlayer() == me;
            Map<String, Object> state = buildState(turn);
            state.put("min", 0);
            state.put("max", 1);
            state.put("unlessCost", cost.toSimpleString());
            state.put("effectSource", host != null ? host.getName() : null);
            state.put("effectIsMine", mine);
            String prompt = "PAY OR ELSE: pay " + cost.toSimpleString() + " now, or "
                    + (host != null ? host.getName() : "the effect") + " does: "
                    + (effect != null ? effect.trim() : "(unknown)")
                    + (mine ? " (this is YOUR OWN spell/ability — e.g. paying X to keep a "
                             + "tutored card, or an optional additional payment)"
                            : " (an OPPONENT's effect taxing you — e.g. a counter-unless-you-pay, "
                             + "Rhystic Study, Propaganda)")
                    + ". Paying uses your floating mana first, then untapped sources.";
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "PAY_UNLESS", prompt)
                    .state(state)
                    .option(0, "Decline — do not pay; let the effect happen", null, "NONE")
                    .option(1, "Pay " + cost.toSimpleString(), cost.toSimpleString(), "PAY");
            JsonNode resp = bus.exchange(req);
            if (resp == null || resp.get("chosenId") == null || !resp.get("chosenId").isInt()) {
                return super.payCostToPreventEffect(cost, sa, alreadyPaid, allPayers);
            }
            if (resp.get("chosenId").asInt() != 1) {
                return false;
            }
            forge.game.cost.CostPayment pay = new forge.game.cost.CostPayment(cost, sa);
            return pay.payComputerCosts(new forge.ai.AiCostDecision(me, sa, true));
        } catch (RuntimeException e) {
            return super.payCostToPreventEffect(cost, sa, alreadyPaid, allPayers);
        }
    }

    /** Multi-card search/fetch (Cultivate, "search for up to N"). Stock
     *  returns null (= fetch nothing). Answer contract: {"chosen": [ids]}
     *  with min..max entries; 0/empty = none when min == 0. */
    @Override
    public List<Card> chooseCardsForZoneChange(ZoneType destination, List<ZoneType> origin,
            SpellAbility sa, CardCollection fetchList, int min, int max,
            DelayedReveal delayedReveal, String selectPrompt, Player decider) {
        try {
            List<Card> opts = fetchList == null ? Collections.<Card>emptyList() : new ArrayList<>(fetchList);
            if (opts.isEmpty() || max <= 0) {
                return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max, delayedReveal, selectPrompt, decider);
            }
            int lo = Math.max(0, min);
            int hi = Math.min(max, opts.size());
            if (hi <= lo && lo >= opts.size()) {
                return new ArrayList<>(opts); // forced: take them all
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", lo);
            state.put("max", hi);
            state.put("destination", destination != null ? destination.name() : null);
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CHOOSE_CARDS",
                    (selectPrompt != null && !selectPrompt.isEmpty() ? selectPrompt : "Choose cards")
                            + (destination != null ? " -> " + destination.name() : "")
                            + " (choose " + lo + "-" + hi + "; answer {\"chosen\": [ids]})")
                    .state(state);
            Map<Integer, Card> byId = new LinkedHashMap<>();
            for (Card c : opts) {
                int oid = c.getId();
                if (oid <= 0 || byId.containsKey(oid)) {
                    return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max, delayedReveal, selectPrompt, decider);
                }
                req.option(oid, cardChoiceLabel(c),
                        c.getManaCost() != null ? c.getManaCost().toString() : null, typeHint(c));
                byId.put(oid, c);
            }
            JsonNode resp = bus.exchange(req);
            if (resp == null || resp.get("chosen") == null || !resp.get("chosen").isArray()) {
                return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max, delayedReveal, selectPrompt, decider);
            }
            List<Card> picked = new ArrayList<>();
            Set<Integer> seen = new HashSet<>();
            for (JsonNode n : resp.get("chosen")) {
                if (n == null || !n.isInt()) {
                    return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max, delayedReveal, selectPrompt, decider);
                }
                Card c = byId.get(n.asInt());
                if (c == null || !seen.add(n.asInt())) {
                    return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max, delayedReveal, selectPrompt, decider);
                }
                picked.add(c);
            }
            if (picked.size() < lo || picked.size() > hi) {
                return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max, delayedReveal, selectPrompt, decider);
            }
            return picked;
        } catch (RuntimeException e) {
            return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max, delayedReveal, selectPrompt, decider);
        }
    }

    /** Yes/no confirms the brain should own: cancelling a search it just
     *  declined, casting-while-searching, optional effects. Other modes
     *  (Random, BidLife, Tribute, damage assignment...) stay with stock. */
    @Override
    public boolean confirmAction(SpellAbility sa, PlayerActionConfirmMode mode, String message,
            List<String> options, Card cardToShow, Map<String, Object> params) {
        try {
            if (mode != PlayerActionConfirmMode.ChangeZoneGeneral
                    && mode != PlayerActionConfirmMode.OptionalChoose
                    && mode != PlayerActionConfirmMode.ChangeZoneToAltDestination
                    && mode != PlayerActionConfirmMode.ChangeZoneFromAltSource
                    && mode != null) {
                return super.confirmAction(sa, mode, message, options, cardToShow, params);
            }
            if (mode == null && (message == null || !message.toLowerCase().contains("play"))) {
                // untyped confirms other than "do you want to play X" stay stock
                return super.confirmAction(sa, mode, message, options, cardToShow, params);
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Card host = sa != null ? sa.getHostCard() : cardToShow;
            Map<String, Object> state = buildState(turn);
            state.put("min", 1);
            state.put("max", 1);
            state.put("confirmMode", mode != null ? mode.name() : "untyped");
            String prompt = "CONFIRM (" + (mode != null ? mode.name() : "question") + "): "
                    + (message != null ? message : "?")
                    + (host != null ? "  [source: " + host.getName() + "]" : "");
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CONFIRM", prompt)
                    .state(state)
                    .option(0, "No", null, "NO")
                    .option(1, "Yes", null, "YES");
            JsonNode resp = bus.exchange(req);
            if (resp == null || resp.get("chosenId") == null || !resp.get("chosenId").isInt()) {
                return super.confirmAction(sa, mode, message, options, cardToShow, params);
            }
            return resp.get("chosenId").asInt() == 1;
        } catch (RuntimeException e) {
            return super.confirmAction(sa, mode, message, options, cardToShow, params);
        }
    }

    // ---- triggers: the seat aims and confirms its own triggers ---------------

    /**
     * Trigger TARGETING (game 7, 2026-08-17). Stock puts a seat's triggers on
     * the stack via prepareSingleSa -> brains.doTrigger(sa, true), i.e. the
     * api-specific AI heuristics pick the target — Tidespout Tyrant's "you may
     * return target permanent" bounced Urza's OWN 17/17 Construct, then the
     * Tyrant itself. The mailbox overrides spell targeting (chooseTargetsFor)
     * but never intercepted this path. Now: for every trigger in the seat's
     * simultaneous batch, each targeting SA in its chain is aimed through the
     * seat (single-target -> CHOOSE_ENTITY; multi-target/odd -> stock, exactly
     * as chooseTargetsFor already does). Non-targeting triggers keep stock's
     * doTrigger setup untouched; copied spells keep stock's branch verbatim.
     * ORDER of simultaneous triggers stays stock (orderSimultaneousSa) — a
     * separate, smaller surface.
     */
    @Override
    public void orderAndPlaySimultaneousSa(List<SpellAbility> activePlayerSAs) {
        Game game = getGame();
        Player me = getPlayer();
        for (final SpellAbility sa : orderSimultaneousSa(activePlayerSAs)) {
            if (sa.isTrigger() && !sa.isCopied()) {
                boolean ready;
                try {
                    ready = prepareTriggerViaSeat(sa);
                } catch (RuntimeException e) {
                    // the seam must never crash the seat — stock is the floor
                    ready = getAi().doTrigger(sa, true);
                }
                if (ready) {
                    ComputerUtil.playStack(sa, me, game);
                }
            } else {
                if (sa.isCopied()) {
                    if (sa.isSpell()) {
                        if (!sa.getHostCard().isInZone(ZoneType.Stack)) {
                            sa.setHostCard(game.getAction().moveToStack(sa.getHostCard(), sa));
                        } else {
                            game.getStackZone().add(sa.getHostCard());
                        }
                    }
                    if (sa.isMayChooseNewTargets()) {
                        forge.game.spellability.TargetChoices tc = sa.getTargets();
                        if (!sa.setupTargets()) {
                            sa.setTargets(tc);
                        }
                    }
                }
                game.getStack().add(sa);
            }
        }
    }

    /** Mirror of stock prepareSingleSa with the seat aiming targeting triggers. */
    private boolean prepareTriggerViaSeat(SpellAbility sa) {
        Card host = sa.getHostCard();
        if (sa.getApi() == ApiType.Charm) {
            // modal trigger: mode choice already reaches the seat via
            // chooseModeForAbility (CHOOSE_MODE); stock flow otherwise
            if (!forge.game.ability.effects.CharmEffect.makeChoices(sa)) {
                return false;
            }
            if (!sa.hasParam("Random")) {
                return true;
            }
            sa = sa.getSubAbility();
        }
        if (sa.hasParam("TargetingPlayer")) {
            Player targetingPlayer = AbilityUtils.getDefinedPlayers(
                    host, sa.getParam("TargetingPlayer"), sa).get(0);
            sa.setTargetingPlayer(targetingPlayer);
            return targetingPlayer.getController().chooseTargetsFor(sa);
        }
        boolean anyTargeting = false;
        for (SpellAbility s = sa; s != null; s = s.getSubAbility()) {
            if (s.usesTargeting()) {
                anyTargeting = true;
                break;
            }
        }
        if (!anyTargeting) {
            return getAi().doTrigger(sa, true); // stock setup for non-targeting triggers
        }
        triggerAimDepth++;
        try {
        for (SpellAbility s = sa; s != null; s = s.getSubAbility()) {
            if (!s.usesTargeting()) {
                continue;
            }
            s.setActivatingPlayer(getPlayer());
            boolean aimed = chooseTargetsFor(s);
            Card h = s.getHostCard();
            forge.game.spellability.TargetRestrictions tr = s.getTargetRestrictions();
            int minT = (tr != null && h != null) ? tr.getMinTargets(h, s) : 0;
            if (minT > 0 && !s.isTargetNumberValid()) {
                // Game-12 finding 1: the brain declined (or the exchange
                // failed) on a REQUIRED-target trigger. A targetless stack
                // entry is rules-broken (it resolved as a confusing FIZZLE);
                // instead: aim the first legal candidate so the trigger
                // stacks LEGALLY, and honor the decline intent at resolve
                // time (confirmTrigger auto-answers NO, zero model calls).
                List<forge.game.GameEntity> cands =
                        tr.getAllCandidates(s);
                if (cands == null || cands.isEmpty()) {
                    return false; // no legal targets: trigger doesn't stack (603.3d)
                }
                s.resetTargets();
                if (!s.getTargets().add(cands.get(0))) {
                    return false;
                }
                if (!aimed) {
                    pendingTriggerDecline.add(sa);
                    System.err.println("[mailbox seat " + seatIndex + "] trigger "
                            + (h != null ? h.getName() : "?") + " declined at aim — "
                            + "auto-aimed " + cands.get(0) + " to stack legally; "
                            + "will auto-decline at resolve");
                }
            } else if (minT == 0 && aimed && !s.isTargetNumberValid()) {
                // legal targetless decline (min 0): the resolve-time confirm
                // is a foregone NO — answer it locally, save the call
                pendingTriggerDecline.add(sa);
            }
        }
        return true;
        } finally {
            triggerAimDepth--;
        }
    }

    /**
     * "May cast/play from effect" (validation game, 2026-08-19): Isochron
     * Scepter copies, cascade, discover, and impulse-style "you may cast"
     * effects route through {@code playSaFromPlayEffect} — stock decided
     * BOTH the yes/no and the targeting via canPlayFromEffectAI/doTrigger,
     * and silently declined a Scepter-copied Counterspell the seat had spent
     * its turn setting up. Now: optional plays reach the seat as CONFIRM
     * (mode PLAY_FROM_EFFECT); on yes (and for mandatory plays) required
     * targets are aimed by the SEAT before the cast. Fail-safe to stock.
     */
    @Override
    public boolean playSaFromPlayEffect(SpellAbility tgtSA) {
        try {
            if (!(tgtSA instanceof forge.game.spellability.Spell)) {
                return super.playSaFromPlayEffect(tgtSA);
            }
            final boolean optional = !tgtSA.getPayCosts().isMandatory();
            final Card host = tgtSA.getHostCard();
            final boolean free = tgtSA.hasParam("WithoutManaCost");
            if (optional) {
                Game game = getGame();
                int turn = game.getPhaseHandler().getTurn();
                Map<String, Object> state = buildState(turn);
                state.put("min", 1);
                state.put("max", 1);
                state.put("confirmMode", "PLAY_FROM_EFFECT");
                state.put("spell", host != null ? host.getName() : String.valueOf(tgtSA));
                state.put("free", free);
                String desc;
                try {
                    desc = tgtSA.getStackDescription();
                } catch (RuntimeException ignore) {
                    desc = String.valueOf(tgtSA);
                }
                String prompt = "PLAY FROM EFFECT (yours to accept or decline): cast "
                        + (host != null ? host.getName() : "the copy")
                        + (free ? " WITHOUT paying its mana cost"
                                : " (cost: " + (tgtSA.getPayCosts() != null
                                    ? tgtSA.getPayCosts().toSimpleString() : "?") + ")")
                        + " — " + (desc.length() > 140 ? desc.substring(0, 140) : desc)
                        + "  1 = cast it, 0 = decline.";
                MailboxProtocol.Request req = new MailboxProtocol.Request(
                        seatIndex, turn, phaseName(game), "CONFIRM", prompt)
                        .state(state)
                        .option(0, "No — decline the play", null, "NO")
                        .option(1, free ? "Yes — cast it for free" : "Yes — cast it", null, "YES");
                JsonNode resp = bus.exchange(req);
                if (resp == null || resp.get("chosenId") == null
                        || !resp.get("chosenId").isInt()) {
                    return super.playSaFromPlayEffect(tgtSA);
                }
                if (resp.get("chosenId").asInt() != 1) {
                    return false;
                }
            }
            // the SEAT aims every required-target part before the cast — the
            // stock path's targeting lived inside the yes/no heuristic we
            // just bypassed, and an untargeted copy fizzles
            for (SpellAbility s = tgtSA; s != null; s = s.getSubAbility()) {
                if (!s.usesTargeting() || s.isTargetNumberValid()) {
                    continue;
                }
                Card h = s.getHostCard();
                forge.game.spellability.TargetRestrictions tr = s.getTargetRestrictions();
                int minT = (tr != null && h != null) ? tr.getMinTargets(h, s) : 0;
                s.setActivatingPlayer(getPlayer());
                if (!chooseTargetsFor(s) && minT > 0) {
                    if (optional) {
                        return false;     // no target the seat wants: decline cleanly
                    }
                    return super.playSaFromPlayEffect(tgtSA);  // mandatory: stock floor
                }
            }
            return ComputerUtil.playStack(tgtSA, getPlayer(), getGame());
        } catch (RuntimeException e) {
            return super.playSaFromPlayEffect(tgtSA);
        }
    }

    /**
     * Optional-trigger CONFIRM (game 7, 2026-08-17). "You may [pay X to] ..."
     * triggers resolve through WrappedAbility -> confirmTrigger, which stock
     * routes to brains.doTrigger — e.g. CopySpellAbilityAi NEVER pays for a
     * Rings of Brighthearth copy of the seat's own activated ability (rolls a
     * low profile chance, then refuses activated abilities outright), so
     * Urza's Rings + Basalt Monolith "infinite" netted zero mana every cycle
     * while the brain narrated the loop. The seat now answers every optional
     * trigger itself: CONFIRM with the trigger text, the yes-cost, the chosen
     * targets and the stack. Only an unpayable yes-cost is auto-declined.
     */
    @Override
    public boolean confirmTrigger(forge.game.trigger.WrappedAbility wrapper) {
        try {
            if (wrapper.isMandatory()) {
                return true;
            }
            SpellAbility sa = wrapper.getWrappedAbility();
            if (pendingTriggerDecline.remove(wrapper)
                    || pendingTriggerDecline.remove(sa)
                    || (sa != null && pendingTriggerDecline.remove(sa.getRootAbility()))) {
                // the seat already declined this trigger at aim time
                return false;
            }
            Card host = wrapper.getHostCard();
            Player me = getPlayer();
            Cost yesCost = sa.getPayCosts();
            boolean hasCost = false;
            if (yesCost != null) {
                for (forge.game.cost.CostPart part : yesCost.getCostParts()) {
                    if (part instanceof forge.game.cost.CostPartMana) {
                        forge.game.cost.CostPartMana cm = (forge.game.cost.CostPartMana) part;
                        if (cm.getMana() != null && !cm.getMana().isZero()) {
                            hasCost = true;
                        }
                    } else {
                        hasCost = true; // tap / sacrifice / life / discard...
                    }
                }
            }
            if (hasCost) {
                boolean payable;
                try {
                    payable = ComputerUtilCost.canPayCost(sa, me, true);
                } catch (RuntimeException ignore) {
                    payable = true;
                }
                if (!payable) {
                    System.err.println("[mailbox seat " + seatIndex + "] optional trigger "
                            + (host != null ? host.getName() : "?")
                            + " auto-declined: yes-cost " + yesCost.toSimpleString()
                            + " not payable now");
                    return false;
                }
            }
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            Map<String, Object> state = buildState(turn);
            state.put("min", 1);
            state.put("max", 1);
            state.put("confirmMode", "TRIGGER");
            state.put("triggerSource", host != null ? host.getName() : null);
            String trigText;
            try {
                trigText = wrapper.getTrigger() != null
                        ? wrapper.getTrigger().toString() : String.valueOf(sa);
            } catch (RuntimeException ignore) {
                trigText = String.valueOf(sa);
            }
            state.put("triggerText", trigText);
            state.put("yesCost", hasCost ? yesCost.toSimpleString() : "none");
            List<String> tgts = new ArrayList<>();
            for (SpellAbility s = sa; s != null; s = s.getSubAbility()) {
                if (s.usesTargeting()) {
                    for (forge.game.GameObject o : s.getTargets()) {
                        tgts.add(o instanceof SpellAbility
                                ? ((SpellAbility) o).getHostCard().getName() + " (spell/ability)"
                                : o.toString());
                    }
                }
            }
            state.put("chosenTargets", tgts);
            String prompt = "OPTIONAL TRIGGER (yours to accept or decline): "
                    + (host != null ? host.getName() + " — " : "") + trigText
                    + (hasCost ? "  Saying YES pays " + yesCost.toSimpleString()
                        + " (pool now " + me.getManaPool().totalMana() + ")." : "  Saying YES costs nothing.")
                    + (tgts.isEmpty() ? "" : "  Targets already chosen: " + tgts + ".")
                    + "  1 = yes (do it" + (hasCost ? ", pay" : "") + "), 0 = no.";
            MailboxProtocol.Request req = new MailboxProtocol.Request(
                    seatIndex, turn, phaseName(game), "CONFIRM", prompt)
                    .state(state)
                    .option(0, "No — decline the trigger", null, "NO")
                    .option(1, "Yes" + (hasCost ? " — pay " + yesCost.toSimpleString() + " and do it" : " — do it"),
                            hasCost ? yesCost.toSimpleString() : null, "YES");
            JsonNode resp = bus.exchange(req);
            if (resp == null || resp.get("chosenId") == null || !resp.get("chosenId").isInt()) {
                return super.confirmTrigger(wrapper);
            }
            return resp.get("chosenId").asInt() == 1;
        } catch (RuntimeException e) {
            return super.confirmTrigger(wrapper);
        }
    }

    // ---- state projection (hidden-info-safe) -------------------------------

    private Map<String, Object> buildState(int turn) {
        return buildState(getPlayer(), seatIndex, turn);
    }

    /**
     * Static, reusable hidden-info-safe projection. The advisor shadow feed
     * ({@link AdvisorControllerHuman}) serializes the HUMAN seat through this
     * exact method — the fairness discipline lives here once, never
     * reimplemented (opponent hands/library order are never serialized).
     */
    static Map<String, Object> buildState(Player me, int seatIndex, int turn) {
        SeatView view = SeatViews.of(me, seatIndex, turn);
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("seat", seatIndex);
        state.put("turn", turn);
        state.put("phase", view.phase());
        state.put("life", me.getLife());
        state.put("poison", me.getPoisonCounters());
        Map<String, Integer> ownCmdDmg = new LinkedHashMap<>();
        for (java.util.Map.Entry<Card, Integer> e : me.getCommanderDamage()) {
            if (e.getValue() != null && e.getValue() > 0) {
                ownCmdDmg.put(e.getKey().getName(), e.getValue());
            }
        }
        if (!ownCmdDmg.isEmpty()) {
            state.put("commanderDamageTaken", ownCmdDmg);
        }
        // Symmetry pieces on ANY battlefield (public info): permanents whose
        // continuous static is active only while the permanent is untapped
        // and restricts PLAYERS (Winter Orb class), plus whose untap step is
        // next — the facts a brain needs to see the end-step tap line (or to
        // see an opponent about to take it).
        try {
            Game g = me.getGame();
            List<Map<String, Object>> pieces = new ArrayList<>();
            for (Player owner : g.getPlayers()) {
                for (Card piece : symmetryPieces(owner)) {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("name", piece.getName());
                    row.put("controllerSeat", owner.getId());
                    row.put("untapped", piece.isUntapped());
                    pieces.add(row);
                }
            }
            if (!pieces.isEmpty()) {
                state.put("symmetryPieces", pieces);
                Player next = g.getPhaseHandler().getNextTurn();
                if (next != null) {
                    state.put("untapNextSeat", next.getId());
                }
            }
        } catch (RuntimeException ignore) {
            // projection extras must never break state building
        }
        // The seat's OWN command zone (opponents' were already serialized;
        // the seat's never was — after a failed recast Selvala's brain wrote
        // "not on the battlefield or in my command zone", blind). Cast counts
        // make the tax derivable: next cast costs base + 2*casts.
        List<Map<String, Object>> ownCmd = new ArrayList<>();
        for (Card c : me.getCardsIn(ZoneType.Command)) {
            if (!c.isCommander()) {
                continue;
            }
            Map<String, Object> cm = new LinkedHashMap<>();
            cm.put("name", c.getName());
            cm.put("timesCast", me.getCommanderCast(c));
            cm.put("nextCastTax", me.getCommanderCast(c) * 2);
            ownCmd.add(cm);
        }
        state.put("commandZone", ownCmd);
        state.put("manaPool", view.manaPool());
        // Renamed from "untappedManaSources" 2026-08-10: a brain read the
        // SOURCE COUNT as floating mana ("seven floating mana") and wasted its
        // X spell. The name now says what it is.
        state.put("untappedManaSourceCount", view.untappedManaSources());
        state.put("handSize", view.handSize());
        state.put("handLands", view.handLands());
        state.put("librarySize", view.librarySize());
        state.put("ownBoardPower", view.ownBoardPower());
        // Rich, per-card serialization. The battlefield is fully public, so we
        // read the ACTUAL Card objects (not the SeatView name Set) for the
        // acting seat AND each opponent — one entry per card (no dedupe by name).
        // Own battlefield cards carry their activated abilities (incl. mana
        // abilities); opponents' entries stay lean (public mechanical fields).
        List<Map<String, Object>> ownBattlefield = new ArrayList<>();
        for (Card c : me.getCardsIn(ZoneType.Battlefield)) {
            ownBattlefield.add(cardState(c, true));
        }
        state.put("battlefield", ownBattlefield);
        // Own hand is private-to-owner (fair): per-card name/manaCost/types.
        List<Map<String, Object>> ownHand = new ArrayList<>();
        for (Card c : me.getCardsIn(ZoneType.Hand)) {
            Map<String, Object> hm = new LinkedHashMap<>();
            hm.put("name", c.getName());
            hm.put("manaCost", c.getManaCost() != null ? c.getManaCost().toString() : "");
            // MDFC/DFC back faces are real information in hand (a land back is
            // a land drop): serialize both faces' types so the state never
            // contradicts the deck text (the Bala Ged mulligan incident).
            String types = c.getType() != null ? c.getType().toString() : "";
            try {
                if (c.hasAlternateState()) {
                    types = types + " // " + c.getAlternateState().getType();
                }
            } catch (RuntimeException ignored) {
                // odd card layouts — front face alone is still true
            }
            hm.put("types", types);
            ownHand.add(hm);
        }
        state.put("hand", ownHand);
        state.put("command", new ArrayList<>(view.cardsIn(SeatView.Zone.COMMAND)));
        state.put("graveyard", new ArrayList<>(view.cardsIn(SeatView.Zone.GRAVEYARD)));
        state.put("exile", new ArrayList<>(view.cardsIn(SeatView.Zone.EXILE)));
        List<Map<String, Object>> opps = new ArrayList<>();
        for (SeatView.OpponentView ov : view.opponents()) {
            Map<String, Object> o = new LinkedHashMap<>();
            o.put("seat", ov.seatIndex());
            o.put("life", ov.life());
            o.put("poison", ov.poison());
            o.put("creaturePower", ov.creaturePower());
            // Opponent battlefields are PUBLIC — read the real Card objects, but
            // WITHOUT the verbose per-card abilities list (kept lean).
            List<Map<String, Object>> oppBattlefield = new ArrayList<>();
            Player oppPlayer = playerById(me.getGame(), ov.seatIndex());
            if (oppPlayer != null) {
                for (Card c : oppPlayer.getCardsIn(ZoneType.Battlefield)) {
                    oppBattlefield.add(cardState(c, false));
                }
            }
            o.put("battlefield", oppBattlefield);
            if (oppPlayer != null) {
                // Remaining PUBLIC information (audit 2026-08-07): hand/library
                // counts, graveyard + face-up exile contents, command zone, and
                // commander damage taken. All open information at a real table;
                // brains were doing threat assessment without it.
                o.put("handSize", oppPlayer.getCardsIn(ZoneType.Hand).size());
                o.put("librarySize", oppPlayer.getCardsIn(ZoneType.Library).size());
                List<String> oppGy = new ArrayList<>();
                for (Card c : oppPlayer.getCardsIn(ZoneType.Graveyard)) {
                    oppGy.add(c.getName());
                }
                o.put("graveyard", oppGy);
                List<String> oppExile = new ArrayList<>();
                for (Card c : oppPlayer.getCardsIn(ZoneType.Exile)) {
                    oppExile.add(c.isFaceDown() ? "(face-down card)" : c.getName());
                }
                o.put("exile", oppExile);
                List<String> oppCmd = new ArrayList<>();
                for (Card c : oppPlayer.getCardsIn(ZoneType.Command)) {
                    oppCmd.add(c.getName());
                }
                o.put("commandZone", oppCmd);
                Map<String, Integer> cmdDmg = new LinkedHashMap<>();
                for (java.util.Map.Entry<Card, Integer> e : oppPlayer.getCommanderDamage()) {
                    if (e.getValue() != null && e.getValue() > 0) {
                        cmdDmg.put(e.getKey().getName(), e.getValue());
                    }
                }
                if (!cmdDmg.isEmpty()) {
                    o.put("commanderDamageTaken", cmdDmg);
                }
            }
            opps.add(o);
        }
        state.put("opponents", opps);
        // PUBLIC combat context (field note 13): who attacks whom and current
        // blocks — an instant-speed combat decision (fog, trick, save) is
        // unjudgeable without the incoming-damage picture.
        forge.game.combat.Combat combat = me.getGame().getPhaseHandler().getCombat();
        if (combat != null && !combat.getAttackers().isEmpty()) {
            List<Map<String, Object>> combatList = new ArrayList<>();
            for (Card a : combat.getAttackers()) {
                Map<String, Object> am = new LinkedHashMap<>();
                am.put("id", a.getId());
                am.put("name", a.getName());
                am.put("power", a.getNetPower());
                am.put("toughness", a.getNetToughness());
                forge.game.GameEntity def = combat.getDefenderByAttacker(a);
                am.put("defender", def != null ? def.getName() : null);
                List<String> blockedBy = new ArrayList<>();
                forge.game.card.CardCollection bs = combat.getBlockers(a);
                if (bs != null) {
                    for (Card b : bs) {
                        blockedBy.add(b.getName() + " (" + b.getNetPower() + "/"
                                + b.getNetToughness() + ")");
                    }
                }
                if (!blockedBy.isEmpty()) {
                    am.put("blockedBy", blockedBy);
                }
                combatList.add(am);
            }
            state.put("combat", combatList);
        }
        // PUBLIC stack contents (source names only), for interaction context
        List<String> stack = new ArrayList<>();
        // Additive (2026-08-17): who controls each stack item and whether it is
        // a triggered/activated ability vs a spell — public information (every
        // player sees whose object is on the stack). Lets the runner recognise
        // "every stack item is my OWN trigger" windows and route them to a
        // lighter think (never skip), and lets the memo fastpath ignore how
        // MANY identical own-triggers remain in a cascade.
        List<Integer> stackOwners = new ArrayList<>();
        List<String> stackKinds = new ArrayList<>();
        for (forge.game.spellability.SpellAbilityStackInstance si : me.getGame().getStack()) {
            SpellAbility sa = si.getSpellAbility();
            Card host = sa != null ? sa.getHostCard() : null;
            stack.add(host != null ? host.getName() : String.valueOf(si));
            Player ctl = sa != null ? sa.getActivatingPlayer() : null;
            stackOwners.add(ctl != null ? ctl.getId() : -1);
            stackKinds.add(sa == null ? "?" : sa.isTrigger() ? "trigger"
                    : sa.isSpell() ? "spell" : "ability");
        }
        state.put("stack", stack);
        state.put("stackOwners", stackOwners);
        state.put("stackKinds", stackKinds);
        return state;
    }

    private List<String> ownZone(ZoneType zone) {
        List<String> names = new ArrayList<>();
        for (Card c : getPlayer().getCardsIn(zone)) {
            names.add(c.getName());
        }
        return names;
    }

    /** The game's Player whose id matches {@code id}, or null. */
    private Player playerById(int id) {
        return playerById(getGame(), id);
    }

    private static Player playerById(Game game, int id) {
        for (Player p : game.getPlayers()) {
            if (p.getId() == id) {
                return p;
            }
        }
        return null;
    }

    /**
     * Per-card mechanical projection of a PUBLIC battlefield card. Fields are
     * all public information (P/T, type line, tapped/summoning-sick, counters,
     * and the names of Auras/Equipment attached TO this card). When
     * {@code includeAbilities} is set (acting seat's OWN cards only), the card's
     * ACTIVATED abilities are listed too — including mana abilities, so lines
     * like Grinning Ignus's mana ability are visible.
     */
    // The keyword classes a decision-maker must not have to remember: what
    // removal bounces off, and how combat actually resolves.
    private static final String[] SALIENT_KEYWORDS = {
            "indestructible", "hexproof", "shroud", "ward", "protection",
            "flying", "reach", "first strike", "double strike", "deathtouch",
            "lifelink", "trample", "vigilance", "menace", "haste", "defender",
    };

    private static Map<String, Object> cardState(Card c, boolean includeAbilities) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", c.getId());
        m.put("name", c.getName());
        if (c.isCreature()) {
            m.put("power", c.getNetPower());
            m.put("toughness", c.getNetToughness());
            m.put("sick", c.isSick());
        }
        m.put("types", c.getType() != null ? c.getType().toString() : "");
        m.put("tapped", c.isTapped());
        // Effective keywords (engine-computed, so board-wide grants like an
        // Avacyn's indestructibility are included). Grounding, not trivia:
        // a brain advised destroying The One Ring because nothing in-context
        // said "Indestructible" — recall under pressure loses to stated fact.
        List<String> kws = new ArrayList<>();
        for (forge.game.keyword.KeywordInterface ki : c.getKeywords()) {
            String kw = ki.getOriginal();
            if (kw == null || kw.isEmpty()) {
                continue;
            }
            String lower = kw.toLowerCase(java.util.Locale.ROOT);
            for (String salient : SALIENT_KEYWORDS) {
                if (lower.startsWith(salient)) {
                    if (!kws.contains(kw)) {
                        kws.add(kw);
                    }
                    break;
                }
            }
            if (kws.size() >= 8) {
                break;
            }
        }
        if (!kws.isEmpty()) {
            m.put("keywords", kws);
        }
        Multiset<CounterType> counters = c.getCounters();
        if (counters != null && !counters.isEmpty()) {
            Map<String, Integer> cm = new LinkedHashMap<>();
            for (Multiset.Entry<CounterType> e : counters.entrySet()) {
                cm.put(e.getElement().getName(), e.getCount());
            }
            m.put("counters", cm);
        }
        // Auras/Equipment/Fortifications attached TO this card (what makes an
        // aura like Kenrith's Transformation visible on the creature it modifies).
        List<String> attached = new ArrayList<>();
        for (Card at : c.getAttachedCards()) {
            attached.add(at.getName());
        }
        if (!attached.isEmpty()) {
            m.put("auras", attached);
        }
        if (includeAbilities) {
            List<Map<String, Object>> abilities = new ArrayList<>();
            for (SpellAbility sa : c.getSpellAbilities()) {
                if (sa == null || !sa.isActivatedAbility()) {
                    continue; // activated abilities only — not spells or triggers
                }
                Map<String, Object> am = new LinkedHashMap<>();
                Cost cost = sa.getPayCosts();
                am.put("cost", cost != null ? cost.toSimpleString() : "");
                String desc = sa.getDescription();
                if (desc == null || desc.isEmpty()) {
                    desc = sa.getStackDescription();
                }
                if (desc == null) {
                    desc = "";
                }
                am.put("desc", desc.length() > 100 ? desc.substring(0, 100) : desc);
                am.put("producesMana", sa.isManaAbility());
                abilities.add(am);
            }
            m.put("abilities", abilities);
        }
        return m;
    }

    /**
     * True when {@code sa} is a bare land mana ability — the host is a land AND
     * the only payment is a tap of that land (e.g. a plain {@code {T}: Add {C}}
     * Forest). Such trivial land taps are filtered out of the options to avoid
     * flooding; every other mana ability (nonland source, or a cost that
     * returns/sacrifices/removes-a-counter) is kept as a selectable option.
     */
    /**
     * v4 (2026-08-10, GAN-reviewed): trivial = bare-tap land whose CURRENT
     * yield is 0 or 1 mana. Yield is data-driven from the ability chain's
     * Amount params (walking sub-abilities — Nykthos-style chains keep their
     * mana part on a sub), so Gaea's Cradle / Serra's Sanctum / Ancient Tomb /
     * Lotus Field become deliberate float options while Forests, duals, and
     * color-fixers (Command Tower, City of Brass, Cavern — the brain never
     * gets the color sub-choice anyway, and Cavern's mana is spend-restricted)
     * stay auto-payment-only. A Cradle with no creatures yields 0 → hidden
     * until it's live. Costed land abilities (Nykthos {2},{T}) were never
     * filtered and still aren't.
     */
    private static boolean isTrivialLandMana(SpellAbility sa, Card host) {
        if (host == null || !host.isLand()) {
            return false;
        }
        Cost cost = sa.getPayCosts();
        boolean bareTap = cost == null
                || (cost.hasTapCost() && cost.hasOnlySpecificCostType(CostTap.class));
        if (!bareTap) {
            return false;
        }
        int yield = manaAbilityYield(sa, host);
        return yield >= 0 && yield <= 1; // unknown (-1) => show it, to be safe
    }

    /** Current total mana yield of a mana-ability chain evaluated against the
     *  live board (e.g. Selvala's {G},{T}: add X = 12 with a Dreadnought out);
     *  -1 if it can't be evaluated. Works for any host, not just lands. */
    private static int manaAbilityYield(SpellAbility sa, Card host) {
        int total = 0;
        boolean sawManaPart = false;
        try {
            for (SpellAbility cur = sa; cur != null; cur = cur.getSubAbility()) {
                if (cur.getApi() != null && "Mana".equals(cur.getApi().toString())) {
                    sawManaPart = true;
                    String amt = cur.getParam("Amount");
                    if (amt == null) {
                        total += 1;
                    } else {
                        total += AbilityUtils.calculateAmount(host, amt, cur);
                    }
                } else if (cur.getParam("Amount") != null && cur == sa) {
                    // root carries the amount for simple one-part scripts
                    sawManaPart = true;
                    total += AbilityUtils.calculateAmount(
                            host, cur.getParam("Amount"), cur);
                }
            }
        } catch (RuntimeException e) {
            return -1; // evaluation failed — treat as strategic, show it
        }
        return sawManaPart ? total : 1; // no explicit part: plain single mana
    }

    private static List<Map<String, Object>> defenderList(List<GameEntity> defenders) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (GameEntity ge : defenders) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", ge.getId());
            m.put("label", ge.getName());
            m.put("type", ge instanceof Player ? "PLAYER" : "PERMANENT");
            out.add(m);
        }
        return out;
    }

    /** Resolve the defender for an attacker: honour an explicit id, else the sole legal one. */
    private static GameEntity chooseDefender(List<GameEntity> defenders, JsonNode defenderId, Card attacker) {
        if (defenderId != null && defenderId.isInt()) {
            for (GameEntity ge : defenders) {
                if (ge.getId() == defenderId.asInt()) {
                    return ge;
                }
            }
            return null; // an explicit but unknown defender id is an error
        }
        // no defender given — only unambiguous if exactly one is legal
        GameEntity only = null;
        for (GameEntity ge : defenders) {
            if (CombatUtil.canAttack(attacker, ge)) {
                if (only != null) {
                    return null;
                }
                only = ge;
            }
        }
        return only;
    }

    // ---- labels ------------------------------------------------------------

    private static String phaseName(Game game) {
        PhaseType phase = game.getPhaseHandler().getPhase();
        return phase == null ? "" : phase.name();
    }

    private static String label(SpellAbility sa, Card host) {
        StringBuilder sb = new StringBuilder();
        sb.append(host != null ? host.getName() : "(ability)");
        String cost = sa.getPayCosts() != null ? sa.getPayCosts().toSimpleString() : null;
        if (cost != null && !cost.isEmpty()) {
            sb.append("  ").append(cost);
        }
        // Stack descriptions render CHOSEN targets; at offer time a targeted
        // ability has none yet and the text collapses to "Exile ." / "Untap ."
        // (2026-08-24 game). Prefer the printed rules text whenever any part
        // of the chain still wants targets it doesn't have; either source
        // falls back to the other when empty.
        boolean wantsUnchosenTargets = false;
        for (SpellAbility s = sa; s != null; s = s.getSubAbility()) {
            if (s.usesTargeting() && s.getTargets().size() == 0) {
                wantsUnchosenTargets = true;
                break;
            }
        }
        String desc = wantsUnchosenTargets ? sa.getDescription() : sa.getStackDescription();
        if (desc == null || desc.isEmpty()) {
            desc = wantsUnchosenTargets ? sa.getStackDescription() : sa.getDescription();
        }
        if (desc != null && !desc.isEmpty()) {
            sb.append(" — ").append(desc.length() > 120 ? desc.substring(0, 120) : desc);
        }
        return sb.toString();
    }

    private static String typeHint(Card host) {
        return host != null && host.getType() != null ? host.getType().toString() : null;
    }

    private static String creatureLabel(Card c) {
        return c.getName() + " (" + c.getNetPower() + "/" + c.getNetToughness() + ")";
    }

    /** True iff every entity in {@code opts} is a {@link Card} (id space = card ids). */
    private static boolean allCards(List<? extends GameEntity> opts) {
        for (GameEntity e : opts) {
            if (!(e instanceof Card)) {
                return false;
            }
        }
        return !opts.isEmpty();
    }

    /** A decision label for an entity option (card gets name + P/T + types). */
    private static String entityLabel(GameEntity e) {
        return e instanceof Card ? cardChoiceLabel((Card) e) : e.getName();
    }

    /** The option {@code type} hint for an entity (card type line, or PLAYER). */
    private static String entityType(GameEntity e) {
        if (e instanceof Card) {
            return typeHint((Card) e);
        }
        return e instanceof Player ? "PLAYER" : "ENTITY";
    }

    /** Rich card label for a choose/tutor option: name, P/T if a creature, and type line. */
    private static String cardChoiceLabel(Card c) {
        StringBuilder sb = new StringBuilder(c.getName());
        if (c.isCreature()) {
            sb.append(" (").append(c.getNetPower()).append('/').append(c.getNetToughness()).append(')');
        }
        String t = c.getType() != null ? c.getType().toString() : null;
        if (t != null && !t.isEmpty()) {
            sb.append(" [").append(t).append(']');
        }
        return sb.toString();
    }
}
