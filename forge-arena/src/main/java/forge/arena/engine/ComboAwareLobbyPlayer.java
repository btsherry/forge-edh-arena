package forge.arena.engine;

import java.util.Collections;
import java.util.List;

import forge.LobbyPlayer;
import forge.ai.ComputerUtil;
import forge.ai.LobbyPlayerAi;
import forge.ai.PlayerControllerAi;
import forge.arena.combo.ComboPilot;
import forge.arena.combo.LineExecutor;
import forge.game.Game;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.PlayerController;
import forge.game.spellability.SpellAbility;

/**
 * The combo-aware seat (plan §6, PR-15): stock AI everywhere, except that
 * each priority first asks the {@link ComboPilot} whether to enter or
 * continue a combo line. Inert without artifacts by construction — a pilot
 * with no ready bound combo always defers to {@code super}, so a seat with
 * empty artifacts is behaviorally the stock AI (the §8 inertness property).
 *
 * <p>Uses the same controller-injection seam GoldfishLobbyPlayer proved
 * (subclass LobbyPlayerAi, replace the controller), and the same play
 * mechanics validation was proven on: steps resolve through
 * {@link AbilityResolver}, mana abilities play off-stack via
 * {@code ComputerUtil.playNoStack} (they must never touch the stack), stack
 * abilities go through the stock {@code playChosenSpellAbility} path.
 */
public final class ComboAwareLobbyPlayer extends LobbyPlayerAi {

    /** Builds the seat's pilot once the in-game Player exists. */
    public interface PilotFactory {
        ComboPilot create(Player player);
    }

    private final PilotFactory pilotFactory;

    public ComboAwareLobbyPlayer(String name, PilotFactory pilotFactory) {
        super(name, Collections.emptySet());
        this.pilotFactory = pilotFactory;
    }

    private ComboAwareController controllerFor(Player p) {
        return new ComboAwareController(p.getGame(), p, this, pilotFactory.create(p));
    }

    @Override
    public Player createIngamePlayer(Game game, int id) {
        Player p = new Player(getName(), game, id);
        p.setFirstController(controllerFor(p));
        return p;
    }

    @Override
    public PlayerController createMindSlaveController(Player master, Player slave) {
        return controllerFor(slave);
    }

    @Override
    public void hear(LobbyPlayer player, String message) {
    }

    static final class ComboAwareController extends PlayerControllerAi {

        private final ComboPilot pilot;
        private final int seatIndex;

        ComboAwareController(Game game, Player p, ComboAwareLobbyPlayer lobby, ComboPilot pilot) {
            super(game, p, lobby);
            this.pilot = pilot;
            this.seatIndex = p.getId();
        }

        private int shortcutTurn = -1;
        private String shortcutCombo;
        private String shortcutRoute;
        private boolean stallReported;
        /** PR-27a: the active step's resolution-choice hint (Sabertooth bounce). */
        private String pendingChoice;

        @Override
        public List<SpellAbility> chooseSpellAbilityToPlay() {
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            // a new priority means the prior step's resolution is done — a
            // stale choice hint must never steer an unrelated choice
            pendingChoice = null;
            watchForStall(game, turn);
            SeatView view = SeatViews.of(player, seatIndex, turn);
            boolean entryWindowOpen = game.getPhaseHandler().is(PhaseType.MAIN1, player)
                    && game.getStack().isEmpty();
            java.util.function.Function<forge.arena.combo.LineExecutor, forge.arena.combo.SimResult>
                    validator = executor -> executor.validate(GameSimHandle.copyOf(game, player));
            ComboPilot.Action action = pilot.nextAction(view, entryWindowOpen, validator)
                    .orElse(null);
            if (action == null) {
                // PR-26: pilot-initiated tutor cast — stock cast zero tutors
                // in 100 observed games; the fetch target is decided by the
                // existing chooseCardsForZoneChange hook (ranked by urgency)
                if (entryWindowOpen && pilot.wantsTutor(view)) {
                    // reserved set: a payoff that is ITSELF a search effect
                    // (Finale) must not be spent as a generic tutor — the
                    // deploy path casts it at the scripted X when it matters
                    SpellAbility tutorSa = findCastableTutor(turn,
                            pilot.conversionPayoffNames(view));
                    if (tutorSa != null) {
                        return Collections.singletonList(tutorSa);
                    }
                }
                List<SpellAbility> stock = super.chooseSpellAbilityToPlay();
                // PR-26 payoff-protection veto: one-shot conversion spells
                // (Finale class) are reserved while a bound combo exists —
                // obs game 78's PRE-fire pathology: stock burned Finale at a
                // pool-blind small X in the window between abort and refire.
                // Permanent payoffs deploy freely (a battlefield Crossroads
                // makes SPREAD_COMBAT better, not worse).
                if (stock != null && pilot.hasBoundCombo(view)) {
                    for (SpellAbility sa : stock) {
                        forge.game.card.Card host = sa.getHostCard();
                        if (sa.isSpell() && host != null && !host.getType().isPermanent()
                                && pilot.conversionPayoffNames(view).contains(host.getName())) {
                            return null; // pass — the payoff waits for conversion
                        }
                    }
                }
                return stock;
            }
            if (!action.isStep() && action.flood() != null) {
                // PR-27b token flood: N real copier entries with triggers
                // ACTIVE — the rules engine prices every ping and amplifier;
                // the win (or the stall, watchdog-guarded) is the engine's
                injectFlood(action.flood());
                shortcutTurn = turn;
                shortcutCombo = action.flood().comboId();
                shortcutRoute = "DIRECT_DAMAGE_LOOP";
                return super.chooseSpellAbilityToPlay();
            }
            if (!action.isStep()) {
                // loop shortcut (plan §6): the proof already ran on a copy —
                // compress the loop to its bounded product
                injectPool(action.shortcut());
                shortcutTurn = turn;
                shortcutCombo = action.shortcut().comboId();
                shortcutRoute = action.shortcut().route();
                // PR-25 deploy-first (game 78): with the pool now injected,
                // ask the pilot again in the SAME priority — stock only gets
                // the window when the pilot has nothing to deploy, so it can
                // never squander a payoff (Finale at pool-blind small X)
                ComboPilot.Action deploy = pilot.nextAction(
                        SeatViews.of(player, seatIndex, turn), entryWindowOpen, validator)
                        .orElse(null);
                if (deploy != null && deploy.isStep()) {
                    List<SpellAbility> resolved = resolveStep(deploy.step(), turn);
                    if (resolved != null) {
                        return resolved;
                    }
                }
                return super.chooseSpellAbilityToPlay();
            }
            List<SpellAbility> resolved = resolveStep(action.step(), turn);
            return resolved != null ? resolved : super.chooseSpellAbilityToPlay();
        }

        /** Step → engine ability; null = failure handled, stock takes the priority. */
        private List<SpellAbility> resolveStep(LineExecutor.Step step, int turn) {
            SpellAbility sa = step.isCast()
                    ? AbilityResolver.resolveCast(player, step.card())
                    : AbilityResolver.resolve(player, step.card(), step.costHint(), step.targets());
            if (sa == null) {
                // inside a line: a piece is gone/changed or a cast is
                // unaffordable — graceful abort, recorded, retried next turn.
                // OUTSIDE a line (PR-26 pre-assembly, PR-25 conversion
                // deploys): soft skip — there is no line to abort, and the
                // per-turn dedupe already prevents a retry loop
                if (pilot.lineActive()) {
                    pilot.abortLine(turn, step.isCast() ? "validation" : "interaction", step.card());
                }
                return null;
            }
            // PR-25: scripted X — playChosenSpellAbility never recomputes X,
            // so the pinned value flows straight into cost payment, which
            // prices it against the injected pool (the payment layer sees
            // floating mana; only the decision layer is blind). PR-28 guard:
            // only when every X cost part is MANA — an X life/sacrifice
            // rider at X=500 would be lethal to ourselves
            if (step.x() != null && sa.getPayCosts() != null
                    && sa.getPayCosts().hasXInAnyCostPart() && manaOnlyX(sa.getPayCosts())) {
                sa.setXManaCostPaid(step.x());
            }
            // PR-27a: arm the resolution-choice hint (Sabertooth's bounce
            // asks WHICH creature to return while this ability resolves)
            pendingChoice = step.choice();
            return Collections.singletonList(sa);
        }

        /** PR-28: X is pin-safe only when every X cost part is mana. */
        private static boolean manaOnlyX(forge.game.cost.Cost cost) {
            for (forge.game.cost.CostPart part : cost.getCostParts()) {
                if ("X".equals(part.getAmount())
                        && !(part instanceof forge.game.cost.CostPartMana)) {
                    return false;
                }
            }
            return true;
        }

        private int tutorTriedTurn = -1;
        private final java.util.Set<String> tutorTried = new java.util.HashSet<>();

        /**
         * PR-26: a castable search-effect spell in hand, found STRUCTURALLY
         * (ChangeZone from the Library — no card names), affordable now.
         * X-cost tutors get the maximum payable X: pre-fire that is real
         * mana (the correct on-curve choice); post-fire the payment probe
         * sees the injected pool, so the conversion fetch runs at a huge X.
         * One attempt per card per turn — a refused cast never loops.
         */
        private SpellAbility findCastableTutor(int turn, java.util.Set<String> reserved) {
            if (turn != tutorTriedTurn) {
                tutorTriedTurn = turn;
                tutorTried.clear();
            }
            for (forge.game.card.Card c : player.getCardsIn(forge.game.zone.ZoneType.Hand)) {
                if (tutorTried.contains(c.getName()) || reserved.contains(c.getName())) {
                    continue;
                }
                for (SpellAbility sa : c.getAllPossibleAbilities(player, true)) {
                    if (!sa.isSpell() || sa.getApi() != forge.game.ability.ApiType.ChangeZone
                            || !String.valueOf(sa.getParam("Origin")).contains("Library")) {
                        continue;
                    }
                    sa.setActivatingPlayer(player);
                    if (sa.getPayCosts() != null && sa.getPayCosts().hasXInAnyCostPart()) {
                        int x = forge.ai.ComputerUtilMana.determineLeftoverMana(sa, player, false);
                        if (x <= 0) {
                            continue;
                        }
                        sa.setXManaCostPaid(x);
                    }
                    if (!forge.ai.ComputerUtilCost.canPayCost(sa, player, false)) {
                        continue;
                    }
                    tutorTried.add(c.getName());
                    return sa;
                }
            }
            return null;
        }

        /**
         * PR-27b: the flood — real copies via the T0 §4.4b programmatic
         * pattern with triggers ACTIVE, one entry at a time so each ETB's
         * pings resolve before the next body lands; stop early the moment
         * the game ends. Bounded by the binding's flood_count.
         */
        private void injectFlood(ComboPilot.TokenFlood order) {
            Game game = getGame();
            forge.item.PaperCard paper = forge.StaticData.instance().getCommonCards()
                    .getCard(order.copier());
            if (paper == null) {
                return;
            }
            for (int i = 0; i < order.count() && !game.isGameOver(); i++) {
                forge.game.card.Card copy = forge.game.card.Card.fromPaperCard(paper, player);
                // a card materialized from NO zone takes a non-triggering
                // path in GameAction — stage it quietly in hand, then make a
                // REAL hand->battlefield entry; the live priority loop runs
                // the queued triggers after this priority returns
                game.getTriggerHandler().setSuppressAllTriggers(true);
                game.getAction().moveTo(forge.game.zone.ZoneType.Hand, copy, null, null);
                game.getTriggerHandler().setSuppressAllTriggers(false);
                game.getAction().moveToPlay(copy, null, null);
                game.getAction().checkStateEffects(true);
            }
        }

        private void injectPool(ComboPilot.ShortcutOrder order) {
            forge.game.card.Card source = AbilityResolver.findBattlefield(player, order.engineCard());
            byte color = forge.card.MagicColor.fromName(order.color().toLowerCase());
            forge.game.mana.Mana[] mana = new forge.game.mana.Mana[order.amount()];
            for (int i = 0; i < order.amount(); i++) {
                mana[i] = new forge.game.mana.Mana(color, source, null, player);
            }
            player.getManaPool().addMana(mana);
        }

        @Override
        public void declareAttackers(Player attacker, forge.game.combat.Combat combat) {
            // PR-25 forced close: while conversion is pending the pilot may
            // steer combat — all-in split alpha (SPREAD_COMBAT) or commander
            // at the lowest-life head (COMMANDER_DMG_SEQUENCE). No directive
            // = stock combat untouched (inertness).
            if (attacker == player) {
                int turn = getGame().getPhaseHandler().getTurn();
                ComboPilot.CombatOrder order = pilot.combatOrder(
                        SeatViews.of(player, seatIndex, turn)).orElse(null);
                if (order != null && scriptAttack(order, combat)) {
                    return;
                }
            }
            super.declareAttackers(attacker, combat);
        }

        /**
         * Assign attackers per the pilot's directive: biggest hitters first,
         * lethal-then-spill down the kill order (the commander sequence puts
         * all pressure on the head). False = nothing could attack — stock
         * declares instead.
         */
        private boolean scriptAttack(ComboPilot.CombatOrder order,
                forge.game.combat.Combat combat) {
            List<Player> targets = new java.util.ArrayList<>();
            for (int seatIdx : order.killOrder()) {
                for (Player p : getGame().getPlayers()) {
                    if (p.getId() == seatIdx && !p.hasLost()) {
                        targets.add(p);
                    }
                }
            }
            if (targets.isEmpty()) {
                return false;
            }
            List<forge.game.card.Card> attackers = new java.util.ArrayList<>();
            for (forge.game.card.Card c : player.getCreaturesInPlay()) {
                if (forge.game.combat.CombatUtil.canAttack(c)) {
                    attackers.add(c);
                }
            }
            attackers.sort(java.util.Comparator.comparingInt(
                    forge.game.card.Card::getNetPower).reversed());
            boolean commanderRoute = "COMMANDER_DMG_SEQUENCE".equals(order.route());
            int targetIndex = 0;
            long assignedPower = 0;
            boolean any = false;
            for (forge.game.card.Card c : attackers) {
                Player target = targets.get(commanderRoute ? 0 : targetIndex);
                if (!forge.game.combat.CombatUtil.canAttack(c, target)) {
                    for (Player alt : targets) {
                        if (forge.game.combat.CombatUtil.canAttack(c, alt)) {
                            combat.addAttacker(c, alt);
                            any = true;
                            break;
                        }
                    }
                    continue;
                }
                combat.addAttacker(c, target);
                any = true;
                if (!commanderRoute) {
                    assignedPower += Math.max(0, c.getNetPower());
                    if (assignedPower > target.getLife() && targetIndex < targets.size() - 1) {
                        targetIndex++;
                        assignedPower = 0;
                    }
                }
            }
            return any;
        }

        /**
         * Gate 3.6 window, PR-25 form: measured in the SEAT's own turns
         * (global turns ÷ pod size) — the old +2-global window fired before
         * the seat's next turn even arrived, mid-legitimate-sequence (the
         * stall autopsy's no-repair finding). Same-turn routes get 2 own
         * turns; the commander sequence kills one head per combat and gets 4.
         */
        private int stallWindowTurns(Game game) {
            int players = Math.max(1, game.getPlayers().size());
            int ownTurns = "COMMANDER_DMG_SEQUENCE".equals(shortcutRoute) ? 4 : 2;
            return ownTurns * players;
        }

        /** Gate 3.6 logging half: proven-infinite with no end state within the window. */
        private void watchForStall(Game game, int turn) {
            if (shortcutTurn < 0 || stallReported || game.isGameOver()
                    || turn < shortcutTurn + stallWindowTurns(game)) {
                return;
            }
            stallReported = true;
            StringBuilder dump = new StringBuilder("turn=").append(turn).append('\n');
            for (forge.game.player.Player p : game.getPlayers()) {
                dump.append(p.getName()).append(" life=").append(p.getLife())
                        .append(" battlefield=");
                for (forge.game.card.Card c : p.getCardsIn(forge.game.zone.ZoneType.Battlefield)) {
                    dump.append(c.getName()).append(';');
                }
                dump.append('\n');
            }
            try {
                String hash = Integer.toHexString(dump.toString().hashCode());
                java.nio.file.Path dir = java.nio.file.Path.of(
                        System.getProperty("arena.stall.dir", "stalls"));
                java.nio.file.Files.createDirectories(dir);
                java.nio.file.Path file = dir.resolve(hash + ".txt");
                java.nio.file.Files.writeString(file, dump.toString());
                pilot.reportStalled(turn, shortcutCombo, hash, file.toString());
            } catch (java.io.IOException e) {
                pilot.reportStalled(turn, shortcutCombo, "unhashed", "dump_failed:" + e.getMessage());
            }
        }

        @Override
        public boolean playChosenSpellAbility(SpellAbility sa) {
            if (sa.isManaAbility()) {
                // same off-stack path validation used (GameSimHandle):
                // mana abilities never stack, and the stock path would
                return ComputerUtil.playNoStack(player, sa, getGame(), false);
            }
            return super.playChosenSpellAbility(sa);
        }

        private int mulligansTaken;

        @Override
        public boolean mulliganKeepHand(Player firstPlayer, int cardsToReturn) {
            // PR-24 (plan §6 distance-aware keep): stock evaluates first —
            // its land judgment stays the fallback — then the pilot may keep
            // for a piece/payoff or spend the free 4-player mulligan digging
            boolean stockKeeps = super.mulliganKeepHand(firstPlayer, cardsToReturn);
            int turn = getGame().getPhaseHandler().getTurn();
            boolean firstMullFree = getGame().getPlayers().size() > 2;
            boolean keep = pilot.mulliganKeep(SeatViews.of(player, seatIndex, turn),
                    mulligansTaken, firstMullFree, stockKeeps);
            if (!keep) {
                mulligansTaken++;
            }
            return keep;
        }

        @Override
        public forge.game.card.CardCollection chooseCardsToDiscardFrom(Player p, SpellAbility sa,
                forge.game.card.CardCollection validCards, int min, int max,
                forge.game.card.CardCollectionView visibleToChooser) {
            // PR-28 discard shield (the tuck shield's sibling): cleanup and
            // effect discards never pitch bound-combo pieces or payoffs while
            // unprotected cards can fill the quota — a hand kept FOR a card
            // must not discard that card
            if (p == player) {
                java.util.Set<String> shielded = pilot.protectedMulliganCards(
                        SeatViews.of(player, seatIndex, getGame().getPhaseHandler().getTurn()));
                forge.game.card.CardCollection free = new forge.game.card.CardCollection();
                for (forge.game.card.Card c : validCards) {
                    if (!shielded.contains(c.getName())) {
                        free.add(c);
                    }
                }
                if (free.size() >= min && free.size() < validCards.size()) {
                    return super.chooseCardsToDiscardFrom(p, sa, free, min,
                            Math.min(max, free.size()), visibleToChooser);
                }
            }
            return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
        }

        @Override
        public forge.game.card.CardCollectionView tuckCardsViaMulligan(
                forge.game.card.CardCollectionView hand, int cardsToReturn) {
            // PR-24: a hand kept FOR a piece/payoff must not have its reason
            // bottomed — stock picks the tucks from the unprotected cards only
            java.util.Set<String> shieldedNames = pilot.protectedMulliganCards(
                    SeatViews.of(player, seatIndex, getGame().getPhaseHandler().getTurn()));
            forge.game.card.CardCollection free = new forge.game.card.CardCollection();
            forge.game.card.CardCollection shielded = new forge.game.card.CardCollection();
            for (forge.game.card.Card c : hand) {
                (shieldedNames.contains(c.getName()) ? shielded : free).add(c);
            }
            if (free.size() >= cardsToReturn) {
                return super.tuckCardsViaMulligan(free, cardsToReturn);
            }
            // hand is nearly all pieces/payoffs: every free card goes and the
            // shield yields the remainder in hand order
            forge.game.card.CardCollection tucked = new forge.game.card.CardCollection(free);
            for (forge.game.card.Card c : shielded) {
                if (tucked.size() >= cardsToReturn) {
                    break;
                }
                tucked.add(c);
            }
            return tucked;
        }

        @Override
        public List<forge.game.card.Card> chooseCardsForZoneChange(
                forge.game.zone.ZoneType destination, List<forge.game.zone.ZoneType> origin,
                SpellAbility sa, forge.game.card.CardCollection fetchList, int min, int max,
                forge.game.player.DelayedReveal delayedReveal, String selectPrompt, Player decider) {
            // PR-27a: an armed step choice (Sabertooth bounce — "return
            // another creature you control") is answered exactly once
            if (pendingChoice != null && decider == player) {
                for (forge.game.card.Card card : fetchList) {
                    if (card.getName().equals(pendingChoice)) {
                        pendingChoice = null;
                        return List.of(card);
                    }
                }
            }
            // TutorRanker hook (PR-18: the REAL library-search seam — the first
            // e2e run proved chooseSingleEntityForEffect never fires for AI
            // hidden-origin searches). Single-pick searches we decide only.
            if (sa != null && decider == player && max == 1 && origin != null
                    && origin.contains(forge.game.zone.ZoneType.Library) && !fetchList.isEmpty()) {
                java.util.List<String> names = new java.util.ArrayList<>();
                for (forge.game.card.Card card : fetchList) {
                    names.add(card.getName());
                }
                int turn = getGame().getPhaseHandler().getTurn();
                var ranked = pilot.rankTutor(sa.getHostCard().getName(), names,
                        SeatViews.of(player, seatIndex, turn));
                if (!ranked.isEmpty()) {
                    String best = ranked.get(0).card();
                    for (forge.game.card.Card card : fetchList) {
                        if (card.getName().equals(best)) {
                            return List.of(card);
                        }
                    }
                }
            }
            return super.chooseCardsForZoneChange(destination, origin, sa, fetchList, min, max,
                    delayedReveal, selectPrompt, decider);
        }
    }
}
