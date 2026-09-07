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
        if (feed != null) {
            feed.setGameId(MailboxController.gameIdFor(game)); // item 8
        }
    }

    /** Mind-slave variant — keeps the shadow alive under Mindslaver effects. */
    public AdvisorControllerHuman(final Player p, final LobbyPlayer lp,
            final PlayerControllerHuman owner, final AdvisorFeed feed, final boolean castsAutopass) {
        super(p, lp, owner);
        this.feed = feed;
        this.castsAutopass = castsAutopass;
        this.seatIndex = p.getId();
        if (feed != null) {
            feed.setGameId(MailboxController.gameIdFor(p.getGame())); // item 8
        }
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
            inPriorityStop = true;
            chosen = super.chooseSpellAbilityToPlay();
        } finally {
            inPriorityStop = false;
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
        // Ben's floating-mana rule: unspent pool mana signals intent — never
        // auto-clear the stop, ours or upstream's. SCOPED strictly to the
        // priority-stop window: mayAutoPass is ALSO the guard inside
        // autoPassCancel (PCH:3847), and vetoing there blocks yield CLEANUP at
        // turn boundaries — a stuck pass-until-end-of-turn skipped whole turns
        // (game-3 combat-skip incident).
        if (inPriorityStop) {
            try {
                if (getPlayer().getManaPool().totalMana() > 0) {
                    return false;
                }
                // Own main phases are SACRED — no auto-pass by ANY layer.
                // Game-4 MAIN2 incident: upstream's affordability solver
                // (ComputerUtilMana) is blind to Selvala-class mana (Cradle/
                // Nykthos/power-scaled), so even a correct rebase inherits its
                // false "nothing castable". Mains cost one click; a swallowed
                // main costs the turn.
                final PhaseType ph = getGame().getPhaseHandler().getPhase();
                if (ph != null && ph.isMain()
                        && getGame().getPhaseHandler().isPlayerTurn(getPlayer())) {
                    return false;
                }
            } catch (RuntimeException ignored) {
                return false; // can't read the state → fail open to prompting
            }
        }
        return oneStopPass || super.mayAutoPass();
    }

    private volatile boolean inPriorityStop;

    /** ARENA_AUTOPASS_RESOLVE_OWN=on (opt-in, 2026-09-07): in your own main phase
     *  with only your own items on the stack, one pass lets the spell resolve
     *  instead of a click. Off by default — it is the one hole in "mains are
     *  sacred", and holding priority to stack a second spell is what it costs. */
    private static final boolean RESOLVE_OWN =
            "on".equalsIgnoreCase(String.valueOf(System.getenv("ARENA_AUTOPASS_RESOLVE_OWN")));

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
            final PhaseType phase = getGame().getPhaseHandler().getPhase();
            final boolean myTurn = getGame().getPhaseHandler().isPlayerTurn(getPlayer());
            boolean oppOnStack = false;
            int stackSize = 0;
            java.util.Set<Card> targetedByOpp = new java.util.HashSet<>();
            for (SpellAbilityStackInstance si : getGame().getStack()) {
                stackSize++;
                SpellAbility sa = si.getSpellAbility();
                if (sa == null || !getPlayer().equals(sa.getActivatingPlayer())) {
                    oppOnStack = true;
                    for (SpellAbility part = sa; part != null; part = part.getSubAbility()) {
                        try {
                            targetedByOpp.addAll(part.getTargets().getTargetCards());
                        } catch (RuntimeException ignore) {
                            // untargeted part
                        }
                    }
                }
            }
            List<String> utilityOnly = new ArrayList<>();
            List<AutopassPolicy.Utility> utilities = new ArrayList<>();
            List<AutopassPolicy.Play> plays = new ArrayList<>();
            boolean freshEquipment = collectPlays(plays, utilityOnly, utilities, targetedByOpp);
            AutopassPolicy.Stop stop = new AutopassPolicy.Stop(myTurn, phase,
                    getPlayer().getManaPool().totalMana(), manaCeiling(), freshEquipment,
                    plays, utilityOnly, utilities, oppOnStack,
                    stackSize > 0 && !oppOnStack, RESOLVE_OWN);
            AutopassPolicy.Decision d = AutopassPolicy.decide(stop);
            int turn = getGame().getPhaseHandler().getTurn();
            if (d.pass) {
                oneStopPass = true;
                feed.publishNote(turn, String.valueOf(phase), "(auto-passed — " + d.reason + ")");
            } else if (!plays.isEmpty() && !(myTurn && phase != null && phase.isMain())) {
                // receipt for a kept prompt outside the sacred stops, once per
                // phase: says which card held it open (tuning evidence)
                String key = turn + ":" + phase + ":kept";
                if (!key.equals(lastSilentNoteKey)) {
                    lastSilentNoteKey = key;
                    feed.publishNote(turn, String.valueOf(phase), "(prompt kept — " + d.reason + ")");
                }
            }
        } catch (RuntimeException failOpen) {
            oneStopPass = false; // any doubt → show the prompt
        }
    }

    /**
     * Pool plus every untapped source's yield on the live board, from the
     * seats' own mana table ({@code MailboxController.manaSources}); {@code -1}
     * when any source's yield is not a plain number (Selvala-class,
     * power-scaled, condition-forked) — the policy then stays conservative.
     */
    private int manaCeiling() {
        try {
            int total = getPlayer().getManaPool().totalMana();
            for (java.util.Map<String, Object> row : MailboxController.manaSources(getPlayer())) {
                if (row.containsKey("sick")) {
                    continue;
                }
                Object y = row.get("yield");
                if (!(y instanceof Integer)) {
                    return -1;
                }
                Object n = row.get("count");
                total += (Integer) y * (n instanceof Integer ? (Integer) n : 1);
            }
            return total;
        } catch (RuntimeException unknown) {
            return -1;
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
    private boolean collectPlays(List<AutopassPolicy.Play> playsOut, List<String> utilityOut,
            List<AutopassPolicy.Utility> utilitiesOut, java.util.Set<Card> targetedByOpp) {
        java.util.Set<forge.game.card.CardView> actionable =
                forge.ai.AvailableActions.collectActionable(getPlayer(), 500);
        if (actionable == null || actionable.isEmpty()) {
            return false; // upstream sees nothing
        }
        boolean freshEquipment = false;
        int matched = 0;
        for (ZoneType zone : new ZoneType[] { ZoneType.Hand, ZoneType.Battlefield, ZoneType.Flashback }) {
            for (Card card : getPlayer().getCardsIn(zone)) {
                if (!actionable.contains(card.getView())) {
                    continue;
                }
                matched++;
                if (card.isEquipment() && card.enteredThisTurn()) {
                    freshEquipment = true; // Ben's rule: fresh equipment holds the turn open
                }
                boolean classified = false;
                for (SpellAbility sa : card.getAllPossibleAbilities(getPlayer(), true)) {
                    if (sa.isManaAbility()) {
                        classified = true;
                        continue;
                    }
                    if (sa.isSpell() || sa instanceof LandAbility || sa.isPwAbility()) {
                        classified = true;
                        playsOut.add(new AutopassPolicy.Play(card.getName(), manaCostOf(sa)));
                        continue;
                    }
                    if (sa.isActivatedAbility()) {
                        classified = true;
                        if (!utilityOut.contains(card.getName())) {
                            utilityOut.add(card.getName());
                        }
                        boolean sac = false;
                        try {
                            sac = sa.getPayCosts() != null
                                    && sa.getPayCosts().hasSpecificCostType(forge.game.cost.CostSacrifice.class);
                        } catch (RuntimeException ignore) {
                            // cost unreadable → not a sac outlet
                        }
                        utilitiesOut.add(new AutopassPolicy.Utility(card.getName(), sac,
                                sa.usesTargeting(), targetedByOpp.contains(card)));
                    }
                }
                if (!classified) {
                    // upstream says actionable, we can't say why — fail open as a free play
                    playsOut.add(new AutopassPolicy.Play(card.getName() + " (unclassified)", 0));
                }
            }
        }
        if (matched < actionable.size()) {
            playsOut.add(new AutopassPolicy.Play("(actionable outside hand/battlefield/flashback)", 0)); // fail open
        }
        return freshEquipment;
    }

    /** Total mana of the ability's cost (0 for pitch / alternative / free casts). */
    private static int manaCostOf(SpellAbility sa) {
        try {
            if (sa.getPayCosts() == null || sa.getPayCosts().getTotalMana() == null) {
                return 0;
            }
            return sa.getPayCosts().getTotalMana().getCMC();
        } catch (RuntimeException unknown) {
            return 0; // unknown cost → treat as free → the prompt stays open
        }
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

    // ---- mana color picks ---------------------------------------------------

    private volatile boolean colorPickNoted;

    /**
     * Discrete skip for arbitrary any-color mana picks (the Gemstone Caverns /
     * City of Brass class): with a MONO-colored commander, a 3+-color choice
     * is arbitrary — off-color mana casts nothing in this deck, so the dialog
     * is pure interruption. Name-free by design (card names never live in
     * Java); multi-color commanders keep the dialog; fail-open on any doubt.
     */
    private byte autoPickColorOrZero(final forge.card.ColorSet colors) {
        try {
            if (colors == null || colors.countColors() < 3) {
                return 0; // constrained choices stay human
            }
            final List<Card> cmdrs = getPlayer().getCommanders();
            if (cmdrs == null || cmdrs.size() != 1) {
                return 0;
            }
            final forge.card.ColorSet id = cmdrs.get(0).getRules().getColorIdentity();
            if (id == null || id.countColors() != 1) {
                return 0;
            }
            final byte mono = id.getColor();
            if (!colors.hasAnyColor(mono)) {
                return 0;
            }
            if (feed != null && !colorPickNoted) {
                colorPickNoted = true; // one receipt per game, then silent
                feed.publishNote(getGame().getPhaseHandler().getTurn(),
                        String.valueOf(getGame().getPhaseHandler().getPhase()),
                        "(auto-picking your commander's color for any-color mana choices this game)");
            }
            return mono;
        } catch (RuntimeException failOpen) {
            return 0;
        }
    }

    @Override
    public byte chooseColor(final String message, final SpellAbility sa,
            final forge.card.ColorSet colors) {
        final byte auto = autoPickColorOrZero(colors);
        return auto != 0 ? auto : super.chooseColor(message, sa, colors);
    }

    @Override
    public byte chooseColorAllowColorless(final String message, final Card c,
            final forge.card.ColorSet colors) {
        final byte auto = autoPickColorOrZero(colors);
        return auto != 0 ? auto : super.chooseColorAllowColorless(message, c, colors);
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
