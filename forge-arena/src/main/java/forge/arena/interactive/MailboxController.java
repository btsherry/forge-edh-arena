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
import forge.ai.ComputerUtilAbility;
import forge.ai.ComputerUtilCost;
import forge.ai.PlayerControllerAi;
import forge.arena.engine.SeatView;
import forge.arena.engine.SeatViews;
import forge.game.Game;
import forge.game.GameEntity;
import forge.game.card.Card;
import forge.game.card.CardCollection;
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
public final class MailboxController extends PlayerControllerAi {

    private final MailboxProtocol bus;
    private final int seatIndex;

    MailboxController(Game game, Player p, LobbyPlayer lobby, MailboxProtocol bus) {
        super(game, p, lobby);
        this.bus = bus;
        this.seatIndex = p.getId();
    }

    // ---- decision hooks ----------------------------------------------------

    @Override
    public List<SpellAbility> chooseSpellAbilityToPlay() {
        Game game = getGame();
        Player me = getPlayer();
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
        if (!ownMainEmpty && !reactive && !tactical) {
            // v3: stock NEVER casts for a mailbox seat anymore. Windows not
            // worth the brain's time are a clean pass — the brain owns this
            // hand. (Stock still takes over wholesale on brain timeout, via
            // the exchange() fallback — that degradation path is unchanged.)
            return null;
        }

        int turn = game.getPhaseHandler().getTurn();
        List<SpellAbility> playable = new ArrayList<>();
        for (SpellAbility sa : ComputerUtilAbility.getSpellAbilities(
                ComputerUtilAbility.getAvailableCards(game, me), me)) {
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
                // so drop ALL of them there — this stopped rock/land mana abilities
                // opening empty "respond?" windows for every seat on ramp spells.
                if (reactive || tactical || isTrivialLandMana(sa, host)) {
                    continue;
                }
            }
            sa.setActivatingPlayer(me);
            try {
                // canPlay() admits some spells the seat cannot actually pay for at a
                // reactive window (e.g. Mana Drain {U}{U} with a single untapped
                // Island), which opened phantom counter windows. Require real
                // affordability for reactive responses so the window only fires when
                // the seat can truly act. Main-phase keeps canPlay() alone, since a
                // mana line in the option list may itself enable the cost.
                boolean affordable = !(reactive || tactical)
                        || ComputerUtilCost.canPayCost(sa, me, false);
                if (sa.canPlay() && affordable) {
                    playable.add(sa);
                }
            } catch (RuntimeException canPlayThrew) {
                // a mis-evaluated canPlay must not crash the seat — skip it
            }
        }
        if (playable.isEmpty()) {
            // Instant windows with nothing real to do are a clean pass (never
            // stock); an empty own-main keeps the v1 stock fallthrough.
            return (reactive || tactical) ? null : super.chooseSpellAbilityToPlay();
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
            req.option(id, label(sa, host), cost, typeHint(host));
            byId.put(id, sa);
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
        return Collections.singletonList(pick);
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

    // ---- state projection (hidden-info-safe) -------------------------------

    private Map<String, Object> buildState(int turn) {
        SeatView view = SeatViews.of(getPlayer(), seatIndex, turn);
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("seat", seatIndex);
        state.put("turn", turn);
        state.put("phase", view.phase());
        state.put("life", getPlayer().getLife());
        state.put("manaPool", view.manaPool());
        state.put("untappedManaSources", view.untappedManaSources());
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
        for (Card c : getPlayer().getCardsIn(ZoneType.Battlefield)) {
            ownBattlefield.add(cardState(c, true));
        }
        state.put("battlefield", ownBattlefield);
        // Own hand is private-to-owner (fair): per-card name/manaCost/types.
        List<Map<String, Object>> ownHand = new ArrayList<>();
        for (Card c : getPlayer().getCardsIn(ZoneType.Hand)) {
            Map<String, Object> hm = new LinkedHashMap<>();
            hm.put("name", c.getName());
            hm.put("manaCost", c.getManaCost() != null ? c.getManaCost().toString() : "");
            hm.put("types", c.getType() != null ? c.getType().toString() : "");
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
            Player oppPlayer = playerById(ov.seatIndex());
            if (oppPlayer != null) {
                for (Card c : oppPlayer.getCardsIn(ZoneType.Battlefield)) {
                    oppBattlefield.add(cardState(c, false));
                }
            }
            o.put("battlefield", oppBattlefield);
            opps.add(o);
        }
        state.put("opponents", opps);
        // PUBLIC combat context (field note 13): who attacks whom and current
        // blocks — an instant-speed combat decision (fog, trick, save) is
        // unjudgeable without the incoming-damage picture.
        forge.game.combat.Combat combat = getGame().getPhaseHandler().getCombat();
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
        for (forge.game.spellability.SpellAbilityStackInstance si : getGame().getStack()) {
            SpellAbility sa = si.getSpellAbility();
            Card host = sa != null ? sa.getHostCard() : null;
            stack.add(host != null ? host.getName() : String.valueOf(si));
        }
        state.put("stack", stack);
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
        for (Player p : getGame().getPlayers()) {
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
    private static boolean isTrivialLandMana(SpellAbility sa, Card host) {
        if (host == null || !host.isLand()) {
            return false;
        }
        Cost cost = sa.getPayCosts();
        if (cost == null) {
            return true; // a free land mana source is trivial too
        }
        return cost.hasTapCost() && cost.hasOnlySpecificCostType(CostTap.class);
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
        String desc = sa.getStackDescription();
        if (desc == null || desc.isEmpty()) {
            desc = sa.getDescription();
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
