package forge.arena.interactive;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import forge.LobbyPlayer;
import forge.game.Game;
import forge.game.GameEntity;
import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.combat.Combat;
import forge.game.phase.PhaseType;
import forge.game.player.DelayedReveal;
import forge.game.player.Player;
import forge.game.player.PlayerActionConfirmMode;
import forge.game.spellability.AbilitySub;
import forge.game.spellability.LandAbility;
import forge.game.spellability.SpellAbility;
import forge.game.spellability.SpellAbilityStackInstance;
import forge.game.zone.ZoneType;
import forge.player.PlayerControllerHuman;
import forge.util.collect.FCollectionView;

/**
 * The human seat's controller with an advisory shadow: every decision the
 * human is asked to make is ALSO published (options offered + the choice
 * actually made) to the one-way {@link AdvisorFeed}, where an external
 * advisor brain reads it and streams teaching commentary into the GUI's
 * AI Advisor tab. The human's play is never altered — every method delegates
 * to {@code super} for the real interaction.
 *
 * <p>Optional casts-mode autopass: upstream APINA (YIELD_AUTO_PASS_NO_ACTIONS)
 * already passes priority when there are NO legal actions; casts mode
 * additionally passes stops where the only "actions" are utility activations
 * (tap abilities, equips) — not castable spells, land drops, or planeswalker
 * activations. Gates: stack empty or own-only, never in declare steps,
 * upstream's own ability enumeration (never a reimplementation), fail-open to
 * prompting on any doubt, strictly one stop at a time, and every pass is
 * narrated to the advisor feed for auditability.
 */
public class AdvisorControllerHuman extends PlayerControllerHuman {

    private static final int MAX_OPTIONS = 40;

    private final AdvisorFeed feed;
    private final boolean castsAutopass;
    private final int seatIndex;
    private volatile boolean oneStopPass;
    private int lastDigestTurn;
    private int lastLogIndex;

    public AdvisorControllerHuman(final Game game, final Player p, final LobbyPlayer lp,
            final AdvisorFeed feed, final boolean castsAutopass) {
        super(game, p, lp);
        this.feed = feed;
        this.castsAutopass = castsAutopass;
        this.seatIndex = p.getId();
    }

    /** Mind-slave variant — keeps the shadow alive under Mindslaver effects. */
    public AdvisorControllerHuman(final Player p, final LobbyPlayer lp,
            final PlayerControllerHuman owner, final AdvisorFeed feed, final boolean castsAutopass) {
        super(p, lp, owner);
        this.feed = feed;
        this.castsAutopass = castsAutopass;
        this.seatIndex = p.getId();
    }

    // ---- priority ----------------------------------------------------------

    @Override
    public List<SpellAbility> chooseSpellAbilityToPlay() {
        maybePublishTurnDigest();
        armCastsAutopassIfIdle();
        long n = -1;
        if (feed != null && shouldFeedPriority()) {
            n = feed.publish(request("PRIORITY",
                    "human priority window — act or pass"));
        }
        List<SpellAbility> chosen;
        try {
            chosen = super.chooseSpellAbilityToPlay();
        } finally {
            oneStopPass = false; // strictly one stop, even on exceptions
        }
        if (n >= 0) {
            feed.publishChosen(n, "PRIORITY", describeSas(chosen));
        }
        // Every silent skip leaves a receipt: upstream APINA passes produced no
        // narration before (the t11 audit found the gap). Deduped per phase.
        if (chosen == null && feed != null
                && !getPlayer().getView().hasAvailableActions()) {
            String key = getGame().getPhaseHandler().getTurn() + ":"
                    + getGame().getPhaseHandler().getPhase();
            if (!key.equals(lastSilentNoteKey)) {
                lastSilentNoteKey = key;
                feed.publishNote(getGame().getPhaseHandler().getTurn(),
                        String.valueOf(getGame().getPhaseHandler().getPhase()),
                        "(auto-passed — nothing available)");
            }
        }
        return chosen;
    }

    private String lastSilentNoteKey;

    @Override
    public boolean mayAutoPass() {
        // Ben's floating-mana rule: unspent mana in the pool signals intent —
        // never auto-clear the stop, OURS or upstream's. (Also compensates the
        // floating-mana-lost confirm dialog, which the wrapper's lobby-player
        // identity check silently disables upstream.)
        try {
            if (getPlayer().getManaPool().totalMana() > 0) {
                return false;
            }
        } catch (RuntimeException ignored) {
            return false; // can't read the pool → fail open to prompting
        }
        return oneStopPass || super.mayAutoPass();
    }

    /**
     * Color-commentary source: on the first stop of a new turn, publish the
     * public game-log delta of the completed turn(s). Batched — one digest
     * event per turn, never per play. The human gets priority every turn, so
     * hooking here needs no extra event subscription; auto-passed stops still
     * execute this method.
     */
    private void maybePublishTurnDigest() {
        if (feed == null) {
            return;
        }
        try {
            int turn = getGame().getPhaseHandler().getTurn();
            if (turn <= lastDigestTurn) {
                return;
            }
            List<forge.game.GameLogEntry> all = getGame().getGameLog().getAllEntries();
            if (lastLogIndex < all.size() && lastDigestTurn > 0) {
                List<String> lines = new ArrayList<>();
                for (forge.game.GameLogEntry e : all.subList(lastLogIndex, all.size())) {
                    lines.add(String.valueOf(e));
                }
                feed.publishDigest(lastDigestTurn, lines);
            }
            lastLogIndex = all.size();
            lastDigestTurn = turn;
        } catch (RuntimeException never) {
            // commentary is best-effort; the game is not
        }
    }

    /**
     * Casts-mode arming: when upstream's scan would keep the prompt alive but
     * every available action is a utility activation, pass this one stop.
     */
    private void armCastsAutopassIfIdle() {
        oneStopPass = false;
        if (!castsAutopass || feed == null) {
            return;
        }
        try {
            if (getPlayer().getManaPool().totalMana() > 0) {
                return; // floating mana = intent; the stop stays open
            }
            PhaseType phase = getGame().getPhaseHandler().getPhase();
            if (phase == PhaseType.COMBAT_DECLARE_ATTACKERS
                    || phase == PhaseType.COMBAT_DECLARE_BLOCKERS) {
                return;
            }
            for (SpellAbilityStackInstance si : getGame().getStack()) {
                SpellAbility sa = si.getSpellAbility();
                if (sa == null || !getPlayer().equals(sa.getActivatingPlayer())) {
                    return; // an opponent's spell is up — always offer the window
                }
            }
            List<String> utilityOnly = new ArrayList<>();
            if (hasRealPlay(utilityOnly) || utilityOnly.isEmpty()) {
                // real play available, or truly nothing (upstream APINA passes that)
                return;
            }
            oneStopPass = true;
            feed.publishNote(getGame().getPhaseHandler().getTurn(), String.valueOf(phase),
                    "(auto-passed — only utility activations available: "
                            + String.join(", ", utilityOnly) + ")");
        } catch (RuntimeException failOpen) {
            oneStopPass = false; // any doubt → show the prompt
        }
    }

    /**
     * Rebased on upstream's own actionable scan ({@code collectActionable},
     * which runs under its AI-controller swap) — we can structurally never
     * see FEWER plays than upstream sees; our job is only classification:
     * <ul>
     *   <li>REAL play: castable spell, land drop, planeswalker ability;</li>
     *   <li>REAL play (Ben's equipment rule): ANY affordable activation on an
     *       equipment that ENTERED THE BATTLEFIELD THIS TURN — the drop turn
     *       is when equipping is the natural play, never skip it (the t11
     *       Lightning Greaves incident);</li>
     *   <li>REAL play: anything actionable we fail to classify (fail-open —
     *       the t11 missed-spell incident made this the logic, not just the
     *       exception handler);</li>
     *   <li>utility: everything else, collected for the narration line.</li>
     * </ul>
     */
    private boolean hasRealPlay(List<String> utilityOut) {
        java.util.Set<forge.game.card.CardView> actionable =
                forge.ai.AvailableActions.collectActionable(getPlayer(), 500);
        if (actionable == null || actionable.isEmpty()) {
            return false; // upstream sees nothing; its own APINA handles the pass
        }
        int matched = 0;
        for (ZoneType zone : new ZoneType[] { ZoneType.Hand, ZoneType.Battlefield, ZoneType.Flashback }) {
            for (Card card : getPlayer().getCardsIn(zone)) {
                if (!actionable.contains(card.getView())) {
                    continue;
                }
                matched++;
                if (card.isEquipment() && card.enteredThisTurn()) {
                    return true; // Ben's rule: fresh equipment holds the turn open
                }
                boolean classified = false;
                for (SpellAbility sa : card.getAllPossibleAbilities(getPlayer(), true)) {
                    if (sa.isManaAbility()) {
                        classified = true;
                        continue;
                    }
                    if (sa.isSpell() || sa instanceof LandAbility || sa.isPwAbility()) {
                        return true;
                    }
                    if (sa.isActivatedAbility()) {
                        classified = true;
                        if (!utilityOut.contains(card.getName())) {
                            utilityOut.add(card.getName());
                        }
                    }
                }
                if (!classified) {
                    return true; // upstream says actionable, we can't say why — fail open
                }
            }
        }
        if (matched < actionable.size()) {
            return true; // actionable cards outside our walk — fail open
        }
        return false;
    }

    /** Feed priority stops only at moments worth advising on. */
    private boolean shouldFeedPriority() {
        if (!getGame().getStack().isEmpty()) {
            return true; // something is on the stack — interaction moment
        }
        PhaseType phase = getGame().getPhaseHandler().getPhase();
        boolean myTurn = getGame().getPhaseHandler().isPlayerTurn(getPlayer());
        return (myTurn && phase.isMain())
                || phase == PhaseType.COMBAT_DECLARE_ATTACKERS
                || phase == PhaseType.COMBAT_DECLARE_BLOCKERS;
    }

    // ---- combat ------------------------------------------------------------

    @Override
    public void declareAttackers(final Player attackingPlayer, final Combat combat) {
        long n = pub("DECLARE_ATTACKERS", "declare attackers");
        super.declareAttackers(attackingPlayer, combat);
        if (n >= 0) {
            List<String> attacks = new ArrayList<>();
            for (Card a : combat.getAttackers()) {
                GameEntity def = combat.getDefenderByAttacker(a);
                attacks.add(a.getName() + " -> " + (def != null ? def.getName() : "?"));
            }
            feed.publishChosen(n, "DECLARE_ATTACKERS", attacks.isEmpty() ? "no attacks" : attacks);
        }
    }

    @Override
    public void declareBlockers(final Player defender, final Combat combat) {
        long n = pub("DECLARE_BLOCKERS", "declare blockers");
        super.declareBlockers(defender, combat);
        if (n >= 0) {
            List<String> blocks = new ArrayList<>();
            for (Card a : combat.getAttackers()) {
                CardCollection bs = combat.getBlockers(a);
                if (bs != null) {
                    for (Card b : bs) {
                        blocks.add(b.getName() + " blocks " + a.getName());
                    }
                }
            }
            feed.publishChosen(n, "DECLARE_BLOCKERS", blocks.isEmpty() ? "no blocks" : blocks);
        }
    }

    // ---- pre-game ----------------------------------------------------------

    // The first human decision of every game (the die-roll dialog) — also the
    // decision that proves the shadow feed is alive before turn 1.
    @Override
    public Player chooseStartingPlayer(final boolean isFirstGame) {
        long n = pub("CHOOSE_STARTING_PLAYER", isFirstGame
                ? "won the roll — choose who plays first" : "lost last game — choose who plays first");
        Player chosen = super.chooseStartingPlayer(isFirstGame);
        if (n >= 0) {
            feed.publishChosen(n, "CHOOSE_STARTING_PLAYER",
                    chosen != null ? chosen.getName() : "?");
        }
        return chosen;
    }

    // ---- mulligan ----------------------------------------------------------

    @Override
    public boolean mulliganKeepHand(final Player mulliganingPlayer, final int cardsToReturn) {
        long n = pub("MULLIGAN", "keep or mulligan");
        boolean keep = super.mulliganKeepHand(mulliganingPlayer, cardsToReturn);
        if (n >= 0) {
            feed.publishChosen(n, "MULLIGAN", keep ? "keep" : "mulligan");
        }
        return keep;
    }

    // ---- choices -----------------------------------------------------------

    @Override
    public <T extends GameEntity> T chooseSingleEntityForEffect(final FCollectionView<T> optionList,
            final DelayedReveal delayedReveal, final SpellAbility sa, final String title,
            final boolean isOptional, final Player targetedPlayer, final Map<String, Object> params) {
        long n = pubWithOptions("CHOOSE_ENTITY", title, entityLabels(optionList));
        T chosen = super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title,
                isOptional, targetedPlayer, params);
        if (n >= 0) {
            feed.publishChosen(n, "CHOOSE_ENTITY", chosen != null ? chosen.getName() : "none");
        }
        return chosen;
    }

    @Override
    public <T extends GameEntity> List<T> chooseEntitiesForEffect(final FCollectionView<T> optionList,
            final int min, final int max, final DelayedReveal delayedReveal, final SpellAbility sa,
            final String title, final Player targetedPlayer, final Map<String, Object> params) {
        long n = pubWithOptions("CHOOSE_ENTITIES", title + " [" + min + ".." + max + "]",
                entityLabels(optionList));
        List<T> chosen = super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa,
                title, targetedPlayer, params);
        if (n >= 0) {
            List<String> names = new ArrayList<>();
            if (chosen != null) {
                for (T t : chosen) {
                    names.add(t.getName());
                }
            }
            feed.publishChosen(n, "CHOOSE_ENTITIES", names);
        }
        return chosen;
    }

    @Override
    public List<AbilitySub> chooseModeForAbility(final SpellAbility sa, final List<AbilitySub> possible,
            final int min, final int num, final boolean allowRepeat) {
        List<String> labels = new ArrayList<>();
        for (AbilitySub m : possible) {
            labels.add(String.valueOf(m));
        }
        long n = pubWithOptions("CHOOSE_MODE", "choose mode: " + sa.getHostCard().getName(), labels);
        List<AbilitySub> chosen = super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
        if (n >= 0) {
            List<String> picked = new ArrayList<>();
            if (chosen != null) {
                for (AbilitySub m : chosen) {
                    picked.add(String.valueOf(m));
                }
            }
            feed.publishChosen(n, "CHOOSE_MODE", picked);
        }
        return chosen;
    }

    @Override
    public Card chooseSingleCardForZoneChange(final ZoneType destination, final List<ZoneType> origin,
            final SpellAbility sa, final CardCollection fetchList, final DelayedReveal delayedReveal,
            final String selectPrompt, final boolean isOptional, final Player decider) {
        List<String> labels = new ArrayList<>();
        for (Card c : fetchList) {
            labels.add(c.getName());
        }
        long n = pubWithOptions("CHOOSE_CARD", selectPrompt, labels);
        Card chosen = super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList,
                delayedReveal, selectPrompt, isOptional, decider);
        if (n >= 0) {
            feed.publishChosen(n, "CHOOSE_CARD", chosen != null ? chosen.getName() : "none");
        }
        return chosen;
    }

    @Override
    public int chooseNumber(final SpellAbility sa, final String title, final int min, final int max) {
        long n = pub("CHOOSE_NUMBER", title + " [" + min + ".." + max + "]");
        int chosen = super.chooseNumber(sa, title, min, max);
        if (n >= 0) {
            feed.publishChosen(n, "CHOOSE_NUMBER", chosen);
        }
        return chosen;
    }

    @Override
    public Integer announceRequirements(final SpellAbility ability, final int min, final int max,
            final String announce) {
        long n = pub("ANNOUNCE_X", announce + " for " + ability.getHostCard().getName()
                + " [" + min + ".." + max + "]");
        Integer chosen = super.announceRequirements(ability, min, max, announce);
        if (n >= 0) {
            feed.publishChosen(n, "ANNOUNCE_X", chosen);
        }
        return chosen;
    }

    @Override
    public boolean confirmAction(final SpellAbility sa, final PlayerActionConfirmMode mode,
            final String message, final List<String> options, final Card cardToShow,
            final Map<String, Object> params) {
        long n = pub("CONFIRM", message);
        boolean chosen = super.confirmAction(sa, mode, message, options, cardToShow, params);
        if (n >= 0) {
            feed.publishChosen(n, "CONFIRM", chosen);
        }
        return chosen;
    }

    // Arena advisor games should not pollute the local achievement stats
    // (WatchLocalGame precedent for the spectator controller).
    @Override
    public void updateAchievements() {
    }

    // ---- feed helpers ------------------------------------------------------

    private volatile boolean pubFailureLogged;

    private MailboxProtocol.Request request(String type, String prompt) {
        int turn = getGame().getPhaseHandler().getTurn();
        MailboxProtocol.Request r = new MailboxProtocol.Request(seatIndex, turn,
                String.valueOf(getGame().getPhaseHandler().getPhase()), type, prompt);
        try {
            r.state(MailboxController.buildState(getPlayer(), seatIndex, turn));
        } catch (RuntimeException preGameOrOdd) {
            // A failed projection must not mute the event — ship a minimal state.
            java.util.Map<String, Object> minimal = new java.util.LinkedHashMap<>();
            minimal.put("seat", seatIndex);
            minimal.put("turn", turn);
            minimal.put("stateError", String.valueOf(preGameOrOdd));
            r.state(minimal);
            logPubFailure(preGameOrOdd);
        }
        return r;
    }

    private long pub(String type, String prompt) {
        if (feed == null) {
            return -1;
        }
        try {
            return feed.publish(request(type, prompt));
        } catch (RuntimeException never) {
            logPubFailure(never);
            return -1; // the feed must never break the game
        }
    }

    private long pubWithOptions(String type, String prompt, List<String> labels) {
        if (feed == null) {
            return -1;
        }
        try {
            MailboxProtocol.Request r = request(type, prompt);
            int id = 0;
            for (String label : labels) {
                if (id >= MAX_OPTIONS) {
                    r.option(id, "(+" + (labels.size() - MAX_OPTIONS) + " more)", "", "");
                    break;
                }
                r.option(id++, label, "", "");
            }
            return feed.publish(r);
        } catch (RuntimeException never) {
            logPubFailure(never);
            return -1;
        }
    }

    // Swallowing must never mean invisible: the first failure prints a full
    // trace to stderr (gui.out) so a broken shadow is diagnosable.
    private void logPubFailure(RuntimeException e) {
        if (!pubFailureLogged) {
            pubFailureLogged = true;
            System.err.println("advisor-shadow: publish failed (first occurrence): " + e);
            e.printStackTrace();
        }
    }

    private static <T extends GameEntity> List<String> entityLabels(FCollectionView<T> optionList) {
        List<String> labels = new ArrayList<>();
        for (T t : optionList) {
            labels.add(t.getName());
        }
        return labels;
    }

    private static Object describeSas(List<SpellAbility> chosen) {
        if (chosen == null || chosen.isEmpty()) {
            return "pass";
        }
        List<String> out = new ArrayList<>();
        for (SpellAbility sa : chosen) {
            out.add(sa.getHostCard() != null
                    ? sa.getHostCard().getName() + ": " + sa
                    : String.valueOf(sa));
        }
        return out;
    }
}
