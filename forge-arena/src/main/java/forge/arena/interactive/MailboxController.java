package forge.arena.interactive;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;

import forge.LobbyPlayer;
import forge.ai.ComputerUtilAbility;
import forge.ai.PlayerControllerAi;
import forge.arena.engine.SeatView;
import forge.arena.engine.SeatViews;
import forge.game.Game;
import forge.game.GameEntity;
import forge.game.card.Card;
import forge.game.combat.Combat;
import forge.game.combat.CombatUtil;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

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
 * <p>v1 scope: only top-level decisions are mailboxed. Targets and sub-choices
 * are intentionally left to stock (the targeting hooks are NOT overridden), so a
 * chosen spell's targets are filled by {@code super}'s normal flow.
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
        // GATE to meaningful windows: our main phase, empty stack, and at least
        // one non-mana playable ability. Everything else (combat tricks, forced
        // priority passes, others' turns) stays with stock so we do not spam the
        // brain with trivial windows.
        boolean mainWindow = (game.getPhaseHandler().is(PhaseType.MAIN1, me)
                || game.getPhaseHandler().is(PhaseType.MAIN2, me))
                && game.getStack().isEmpty();
        if (!mainWindow) {
            return super.chooseSpellAbilityToPlay();
        }

        int turn = game.getPhaseHandler().getTurn();
        List<SpellAbility> playable = new ArrayList<>();
        for (SpellAbility sa : ComputerUtilAbility.getSpellAbilities(
                ComputerUtilAbility.getAvailableCards(game, me), me)) {
            if (sa == null || sa.isManaAbility()) {
                continue;
            }
            sa.setActivatingPlayer(me);
            try {
                if (sa.canPlay()) {
                    playable.add(sa);
                }
            } catch (RuntimeException canPlayThrew) {
                // a mis-evaluated canPlay must not crash the seat — skip it
            }
        }
        if (playable.isEmpty()) {
            return super.chooseSpellAbilityToPlay();
        }

        // Stable id per option this decision; 0 is reserved for "pass".
        MailboxProtocol.Request req = new MailboxProtocol.Request(
                seatIndex, turn, phaseName(game), "CAST_SPELL",
                "Choose a spell/ability to play, or pass.")
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
        state.put("battlefield", new ArrayList<>(view.cardsIn(SeatView.Zone.BATTLEFIELD)));
        state.put("hand", new ArrayList<>(view.cardsIn(SeatView.Zone.HAND)));
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
            o.put("battlefield", new ArrayList<>(ov.battlefield()));
            opps.add(o);
        }
        state.put("opponents", opps);
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
}
