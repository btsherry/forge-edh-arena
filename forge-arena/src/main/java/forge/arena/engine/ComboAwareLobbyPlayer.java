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

    public static final class ComboAwareController extends PlayerControllerAi {

        /**
         * PR-37 (Phase 6 A3): an armed loop-to-lethal DRILL — repeat the
         * outlet's activation, one per priority window (the step model is
         * the interrupt handler: opponent interaction lands between
         * iterations and a lost outlet simply fails to resolve next pass),
         * aimed at the lowest-life alive opponent, until nobody is left or
         * the activation stops resolving. Armed by the ConversionPlanner
         * (PR-38); package-armed directly in tests.
         */
        public record DrillOrder(String outletCard, String costHint) {
        }

        private DrillOrder activeDrill;
        private int drillIterations;
        /** Bounded per game — a runaway drill is a stall, not a win. */
        static final int DRILL_BOUND = 200;
        /**
         * Opponents the drill has proven it cannot hurt (adversarial review
         * find): a target with damage prevention, "can't lose the game", or
         * protection would otherwise absorb every one of the 200 bounded
         * iterations while the real threats sat untouched. Two consecutive
         * activations that fail to move a life total retire that target.
         */
        private final java.util.Set<Integer> drillImmune = new java.util.HashSet<>();
        private int drillLastTargetSeat = -1;
        private int drillLastTargetLife = Integer.MIN_VALUE;
        private int drillNoProgress;
        /** Consecutive resolved activations that moved nothing = immune. */
        static final int DRILL_NO_PROGRESS_LIMIT = 3;

        public void armDrill(DrillOrder order) {
            activeDrill = order;
            drillIterations = 0;
            drillImmune.clear();
            drillLastTargetSeat = -1;
            drillLastTargetLife = Integer.MIN_VALUE;
            drillNoProgress = 0;
        }

        /**
         * PR-50 (playbook §4): who to shoot first. We used to always pick
         * the LOWEST-LIFE opponent, which is backwards in multiplayer — the
         * dangerous player is the one with cards and open mana, not the one
         * already nearly dead. A low life total still matters (it is the
         * cheapest elimination), so it stays in the score rather than being
         * the whole score.
         *
         * <p>Higher is more urgent: open mana they could interact with,
         * cards in hand, and board presence push a player up; a low life
         * total also pushes them up because finishing them is cheap and
         * removes a whole set of blockers and answers from the table.
         */
        private int threatScore(Player opponent) {
            int openMana = 0;
            int board = 0;
            for (forge.game.card.Card c : opponent.getCardsIn(
                    forge.game.zone.ZoneType.Battlefield)) {
                if (c.isLand() && !c.isTapped()) {
                    openMana++;
                }
                if (c.isCreature()) {
                    board++;
                }
            }
            int handSize = opponent.getCardsIn(forge.game.zone.ZoneType.Hand).size();
            // life is inverted: 40 life scores 0, 1 life scores ~39
            int nearlyDead = Math.max(0, 40 - opponent.getLife());
            return openMana * 3 + handSize * 2 + board + nearlyDead;
        }

        /** The next drill activation, or null (disarms when done/failed). */
        private List<SpellAbility> drillStep(int turn) {
            if (activeDrill == null) {
                return null;
            }
            if (drillIterations >= DRILL_BOUND || getGame().isGameOver()) {
                activeDrill = null;
                return null;
            }
            // Did the previous activation actually move the life total it
            // aimed at? If not, that opponent is unkillable by this outlet
            // (prevention / protection / "can't lose") and is retired rather
            // than absorbing the whole bound.
            //
            // Only judge with an EMPTY STACK. The controller regains priority
            // while its own activation is still on the stack, so an
            // unconditional check reads the pre-resolution life total, calls
            // a perfectly good outlet immune on its first shot, and disarms
            // the drill after one activation — which is exactly what the
            // regression suite caught.
            if (drillLastTargetSeat >= 0 && getGame().getStack().isEmpty()) {
                for (Player p : getGame().getPlayers()) {
                    if (p.getId() == drillLastTargetSeat && !p.hasLost()
                            && p.getLife() >= drillLastTargetLife
                            && ++drillNoProgress >= DRILL_NO_PROGRESS_LIMIT) {
                        drillImmune.add(drillLastTargetSeat);
                        drillNoProgress = 0;
                    }
                }
            }
            // the alive set is re-derived EVERY iteration: eliminating a
            // player removes them and their permanents immediately (CR
            // 800.4a), which can change what is legal next pass
            Player target = null;
            for (Player p : getGame().getPlayers()) {
                if (p != player && !p.hasLost() && !drillImmune.contains(p.getId())
                        && (target == null || threatScore(p) > threatScore(target))) {
                    target = p;
                }
            }
            if (target == null) {
                activeDrill = null; // table cleared, or nothing left we can hurt
                return null;
            }
            if (target.getId() != drillLastTargetSeat) {
                drillNoProgress = 0; // new target, fresh judgement
            }
            drillLastTargetSeat = target.getId();
            drillLastTargetLife = target.getLife();
            SpellAbility sa = AbilityResolver.resolveAtPlayer(
                    player, activeDrill.outletCard(), activeDrill.costHint(), target);
            if (sa == null) {
                activeDrill = null; // outlet gone or cost unpayable — stop honestly
                return null;
            }
            drillIterations++;
            pilot.reportDrillStep(turn, activeDrill.outletCard(), target.getId());
            return Collections.singletonList(sa);
        }

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
        /** PR-27a/32: the active step's resolution-choice hint (bounce, imprint). */
        private String pendingChoice;
        private int pendingChoiceTurn = -1;

        @Override
        public List<SpellAbility> chooseSpellAbilityToPlay() {
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            // PR-32 fix: resolution-time choices (Scepter's imprint trigger)
            // resolve AFTER later priorities — the hint persists until
            // consumed, replaced by a newer step, or the turn changes; it can
            // only ever steer a choice list containing exactly its card
            if (pendingChoice != null && turn != pendingChoiceTurn) {
                pendingChoice = null;
            }
            watchForStall(game, turn);
            // PR-31: an armed paired-play protection fires at the first
            // priority with our trigger on the stack — cast it in response
            if (pilot.pendingProtection() != null && !game.getStack().isEmpty()) {
                SpellAbility protection = AbilityResolver.resolveCast(
                        player, pilot.pendingProtection());
                pilot.protectionResolved(turn, protection != null);
                if (protection != null) {
                    return Collections.singletonList(protection);
                }
            }
            SeatView view = SeatViews.of(player, seatIndex, turn);
            boolean entryWindowOpen = game.getPhaseHandler().is(PhaseType.MAIN1, player)
                    && game.getStack().isEmpty();
            java.util.function.Function<forge.arena.combo.LineExecutor, forge.arena.combo.SimResult>
                    validator = executor -> executor.validate(GameSimHandle.copyOf(game, player));
            ComboPilot.Action action = pilot.nextAction(view, entryWindowOpen, validator)
                    .orElse(null);
            if (action == null) {
                // PR-37: an armed drill outranks every other passive lever —
                // it IS the conversion in progress
                List<SpellAbility> drill = drillStep(turn);
                if (drill != null) {
                    return drill;
                }
                // PR-30 ramp runway (research: "ramp before durdle"): below
                // the cheapest bound line's entry cost in untapped sources,
                // cast a mana producer from hand before stock decides
                if (entryWindowOpen && pilot.hasBoundCombo(view)
                        && view.untappedManaSources() < pilot.entryRunway(view)) {
                    SpellAbility ramp = findCastableRamp(turn);
                    if (ramp != null) {
                        return Collections.singletonList(ramp);
                    }
                }
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
                // PR-29: the injected pool is PILOT-ONLY. Stock's payment
                // layer can see floating mana, and on the fire turn it
                // wielded 1000 mana into a Sabertooth bounce-recast-draw
                // spiral that decked the seat (gauntlet find). With the pool
                // live and the pilot done, pass the priority instead.
                if (shortcutTurn == turn && player.getManaPool().totalMana() > 0) {
                    return null;
                }
                List<SpellAbility> stock = super.chooseSpellAbilityToPlay();
                // PR-26 payoff-protection veto: one-shot conversion spells
                // (Finale class) are reserved while a bound combo exists —
                // obs game 78's PRE-fire pathology: stock burned Finale at a
                // pool-blind small X in the window between abort and refire.
                // Permanent payoffs deploy freely (a battlefield Crossroads
                // makes SPREAD_COMBAT better, not worse).
                if (stock != null && pilot.hasReservedPlays(view)) {
                    for (SpellAbility sa : stock) {
                        forge.game.card.Card host = sa.getHostCard();
                        // PR-33 (giada trace): foretelling SPENDS the card
                        // just as surely as casting — stock exiled Doomskar
                        // face-down at t3 and wiped uncoordinated at t5,
                        // sailing straight past the cast-only veto
                        boolean spends = sa.isForetelling()
                                || (sa.isSpell() && host != null
                                        && !host.getType().isPermanent());
                        if (spends && host != null
                                && pilot.reservedCastNames(view).contains(host.getName())) {
                            return null; // pass — reserved for the pilot's play
                        }
                    }
                }
                return stock;
            }
            if (!action.isStep() && action.drill() != null) {
                // PR-38: the planner picked a single-target sink. PROVE it on
                // a copy first (an "any target" ability that cannot actually
                // drop a life total must never arm a 200-iteration drill),
                // then arm and fire the first activation in this same window.
                String outlet = action.drill().outletCard();
                if (GameSimHandle.copyOf(game, player).activateAtOpponent(outlet, null)) {
                    armDrill(new DrillOrder(outlet, null));
                    List<SpellAbility> first = drillStep(turn);
                    if (first != null) {
                        return first;
                    }
                }
                return super.chooseSpellAbilityToPlay();
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

        /**
         * PR-41b: WHY a scripted step could not be turned into an ability.
         * These aborts were the single largest unexplained loss in the
         * 300-game funnel — 141 for one deck, 136 for another, all recorded
         * as the bare word "validation" with no way to tell a mana problem
         * from a missing piece. Cheap to compute, and it splits the two.
         */
        private String stepFailure(LineExecutor.Step step) {
            String card = step.card();
            if (card == null) {
                return "no_card";
            }
            if (step.isCast()) {
                boolean present = false;
                for (forge.game.zone.ZoneType zone : List.of(
                        forge.game.zone.ZoneType.Hand, forge.game.zone.ZoneType.Command)) {
                    for (forge.game.card.Card c : player.getCardsIn(zone)) {
                        if (c.getName().equals(card)) {
                            present = true;
                        }
                    }
                }
                // present but unresolvable == the cost could not be paid;
                // absent == the piece moved (drawn away, countered, exiled)
                return present ? "cast_unaffordable" : "cast_card_not_in_hand";
            }
            forge.game.card.Card onBoard = AbilityResolver.findBattlefield(player, card);
            if (onBoard == null) {
                return "activate_card_not_on_battlefield";
            }
            return step.targets().isEmpty()
                    ? "activate_ability_not_found"
                    : "activate_target_illegal";
        }

        /** Step → engine ability; null = failure handled, stock takes the priority. */
        private List<SpellAbility> resolveStep(LineExecutor.Step step, int turn) {
            SpellAbility sa;
            if ("dig_activate".equals(step.action())) {
                // PR-41c: a dig is the LAST resort. With a banked pool, a
                // tutor that FETCHES the payoff ends the game; drawing one
                // card only hopes to. The first live dig measurement showed
                // 14 digs and ZERO tutor decisions in 166 games — the
                // conversion module had quietly starved the better line, so
                // the tutor gets first refusal here, where castability
                // (the engine's business) can actually be tested.
                SpellAbility tutor = findCastableTutor(turn,
                        pilot.conversionPayoffNames(SeatViews.of(player, seatIndex, turn)));
                if (tutor != null) {
                    return Collections.singletonList(tutor);
                }
                sa = AbilityResolver.resolve(player, step.card(), null, List.of());
            } else if ("prereq_deploy".equals(step.action())) {
                // PR-29: the biggest affordable creature in hand — engine
                // data (power, castability) the pilot structurally lacks
                sa = biggestCastableCreature();
            } else {
                sa = step.isCast()
                        ? AbilityResolver.resolveCast(player, step.card())
                        : AbilityResolver.resolve(player, step.card(), step.costHint(), step.targets());
            }
            if (sa == null) {
                // inside a line: a piece is gone/changed or a cast is
                // unaffordable — graceful abort, recorded, retried next turn.
                // OUTSIDE a line (PR-26 pre-assembly, PR-25 conversion
                // deploys): soft skip — there is no line to abort, and the
                // per-turn dedupe already prevents a retry loop
                if (pilot.lineActive()) {
                    pilot.abortLine(turn, step.isCast() ? "validation" : "interaction",
                            step.card(), stepFailure(step));
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
            // PR-27a: arm the resolution-choice hint (Sabertooth's bounce,
            // Scepter's imprint) — persists within the turn until consumed
            if (step.choice() != null) {
                pendingChoice = step.choice();
                pendingChoiceTurn = getGame().getPhaseHandler().getTurn();
            }
            return Collections.singletonList(sa);
        }

        private int rampTriedTurn = -1;
        private final java.util.Set<String> rampTried = new java.util.HashSet<>();

        /**
         * PR-30: a castable mana producer in hand (a card carrying its own
         * mana abilities — dorks, rocks), found structurally, cheapest
         * first; one attempt per card per turn.
         */
        private SpellAbility findCastableRamp(int turn) {
            if (turn != rampTriedTurn) {
                rampTriedTurn = turn;
                rampTried.clear();
            }
            SpellAbility best = null;
            int bestCost = Integer.MAX_VALUE;
            for (forge.game.card.Card c : player.getCardsIn(forge.game.zone.ZoneType.Hand)) {
                if (c.getManaAbilities().isEmpty() || rampTried.contains(c.getName())
                        || c.getCMC() >= bestCost) {
                    continue;
                }
                for (SpellAbility sa : c.getAllPossibleAbilities(player, true)) {
                    if (sa.isSpell()) {
                        sa.setActivatingPlayer(player);
                        if (forge.ai.ComputerUtilCost.canPayCost(sa, player, false)) {
                            best = sa;
                            bestCost = c.getCMC();
                            break;
                        }
                    }
                }
            }
            if (best != null) {
                rampTried.add(best.getHostCard().getName());
            }
            return best;
        }

        /** PR-29: biggest-power castable creature spell in hand, or null. */
        private SpellAbility biggestCastableCreature() {
            SpellAbility best = null;
            int bestPower = -1;
            for (forge.game.card.Card c : player.getCardsIn(forge.game.zone.ZoneType.Hand)) {
                if (!c.isCreature() || c.getNetPower() <= bestPower) {
                    continue;
                }
                for (SpellAbility sa : c.getAllPossibleAbilities(player, true)) {
                    if (sa.isSpell()) {
                        sa.setActivatingPlayer(player);
                        if (forge.ai.ComputerUtilCost.canPayCost(sa, player, false)) {
                            best = sa;
                            bestPower = c.getNetPower();
                            break;
                        }
                    }
                }
            }
            return best;
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
        /**
         * X for a pool-funded tutor. Big enough to fetch anything in a
         * Commander deck, small enough that the payment prober is not walking
         * hundreds of pool objects (the PR-29 wall-clock lesson).
         */
        static final int POOL_TUTOR_X = 20;

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
                    // PR-41d — the oldest engine trap in this project, hit
                    // again: determineLeftoverMana and canPayCost are
                    // DECISION-layer helpers and the decision layer cannot
                    // see floating mana (only the payment layer can). After a
                    // loop fires, the seat's lands are tapped and its pool
                    // holds a thousand mana — so an X-cost tutor computed
                    // X<=0 and was skipped, every single time. That is why
                    // 166 games produced ZERO tutor decisions while the green
                    // deck's every route failure read "mass_pump absent" with
                    // Craterhoof sitting in the library.
                    int pool = player.getManaPool().totalMana();
                    if (sa.getPayCosts() != null && sa.getPayCosts().hasXInAnyCostPart()) {
                        int x = pool > 1
                                // leave room for coloured pips; a fetch only
                                // needs to cover the biggest creature's cost
                                ? Math.min(pool - 1, POOL_TUTOR_X)
                                : forge.ai.ComputerUtilMana.determineLeftoverMana(sa, player, false);
                        if (x <= 0) {
                            continue;
                        }
                        sa.setXManaCostPaid(x);
                    }
                    // canPayCost is NOT blind — it reaches the payment layer,
                    // which is why pool-funded payoff casts have always
                    // worked through AbilityResolver.resolveCast (the Finale
                    // golden proves it). Only the X ESTIMATE above was
                    // broken. Keep the real affordability gate.
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
            if (source == null) {
                // PR-33 hardening: Mana's constructor NPEs on a null source
                // card — if the named producer left the battlefield between
                // the order and the injection, cite any own permanent (the
                // source is provenance, the loop was already proven)
                for (forge.game.card.Card c : player.getCardsIn(
                        forge.game.zone.ZoneType.Battlefield)) {
                    source = c;
                    break;
                }
                if (source == null) {
                    return; // no battlefield at all — nothing to cite, no pool
                }
            }
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
                // PR-34 continuous lethal-check (the long-200 finding: 25%
                // fire→win, BANK_AND_HOLD the most common post-fire route,
                // win-turn median 31 — the boards get there, the combat
                // never closes): every own combat, if worst-case math
                // GUARANTEES a kill right now, take it — combo or no combo
                ComboPilot.CombatOrder lethal = lethalAlphaOrder(turn);
                if (lethal != null && scriptAttack(lethal, combat)) {
                    return;
                }
            }
            super.declareAttackers(attacker, combat);
        }

        /**
         * PR-58 (Phase 7 stage 2, the fidelity ledger): ask the engine
         * whether attacking with everything kills anyone, and RECORD the
         * answer next to what the existing predicate decided. Changes no
         * decision.
         *
         * <p>This exists because an A/B win rate cannot tell a right
         * prediction from a wrong one that happened to win anyway, and a
         * confidently wrong prediction is worse than an honest proxy. The
         * numbers this emits — how often the engine says "this kills" while
         * the predicate says "do not attack" — are what decide whether the
         * cutover is justified at all.
         *
         * <p>Gated on the cheap read-model so it costs nothing on the turns
         * it cannot matter: no creatures, or not enough power on the board to
         * kill the weakest opponent even unblocked.
         */

        /**
         * PR-34: a kill order when combat math GUARANTEES an elimination
         * right now, else null. Worst case per opponent: they block and
         * fully absorb our TOP-power B attackers (B = their untapped
         * creatures); if the remaining power still meets their life, the
         * kill cannot be combat-tricked below lethal by blocks alone. A
         * conservative lower bound — trample, menace, and flash blockers
         * all shift it in known directions; guarantee beats greed.
         */
        private ComboPilot.CombatOrder lethalAlphaOrder(int turn) {
            List<forge.game.card.Card> ready = new java.util.ArrayList<>();
            for (forge.game.card.Card c : player.getCreaturesInPlay()) {
                if (forge.game.combat.CombatUtil.canAttack(c)) {
                    ready.add(c);
                }
            }
            if (ready.isEmpty()) {
                return null;
            }
            List<Player> alive = new java.util.ArrayList<>();
            for (Player p : getGame().getPlayers()) {
                if (p != player && !p.hasLost()) {
                    alive.add(p);
                }
            }
            alive.sort(java.util.Comparator.comparingInt(Player::getLife));
            for (Player opp : alive) {
                List<Integer> powers = new java.util.ArrayList<>();
                for (forge.game.card.Card c : ready) {
                    if (forge.game.combat.CombatUtil.canAttack(c, opp)) {
                        powers.add(Math.max(0, c.getNetPower()));
                    }
                }
                powers.sort(java.util.Collections.reverseOrder());
                int blockers = 0;
                for (forge.game.card.Card c : opp.getCreaturesInPlay()) {
                    if (!c.isTapped()) {
                        blockers++;
                    }
                }
                int guaranteed = 0;
                for (int i = blockers; i < powers.size(); i++) {
                    guaranteed += powers.get(i);
                }
                if (guaranteed >= opp.getLife() && guaranteed > 0) {
                    List<Integer> killOrder = new java.util.ArrayList<>();
                    killOrder.add(opp.getId());
                    for (Player p : alive) {
                        if (p != opp) {
                            killOrder.add(p.getId());
                        }
                    }
                    pilot.reportLethalAlpha(turn, opp.getId(), guaranteed, opp.getLife());
                    return new ComboPilot.CombatOrder("LETHAL_ALPHA", killOrder);
                }
            }
            return null;
        }

        /**
         * Assign attackers per the pilot's directive: biggest hitters first,
         * lethal-then-spill down the kill order (the commander sequence puts
         * all pressure on the head; LETHAL_ALPHA too — the guarantee was
         * computed all-in, spilling would dilute it below lethal). False =
         * nothing could attack — stock declares instead.
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
            boolean commanderRoute = "COMMANDER_DMG_SEQUENCE".equals(order.route())
                    || "LETHAL_ALPHA".equals(order.route());
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
        public boolean confirmAction(SpellAbility sa,
                forge.game.player.PlayerActionConfirmMode mode, String message,
                List<String> options, forge.game.card.Card cardToShow,
                java.util.Map<String, Object> params) {
            // PR-33 (urza gauntlet find): an optional trigger the pilot's own
            // step armed a resolution choice for (Isochron Scepter's "you may
            // imprint...") — stock's default DECLINES the may before any card
            // choice appears, silently killing the line. While the hint is
            // live this turn, the answer to "may I?" is yes; the armed
            // chooseCardsForZoneChange hook then steers the card pick.
            if (pendingChoice != null && sa != null && sa.isTrigger()
                    && getGame().getPhaseHandler().getTurn() == pendingChoiceTurn) {
                return true;
            }
            // PR-33, the same find's second half: while a line is LIVE, an
            // optional effect hosted by the line's own cards is part of the
            // proven loop — the Scepter's "you may copy / you may cast the
            // copy" resolves mid-line, and stock's default (the script even
            // says AI:RemoveDeck:All) declines it
            if (sa != null && sa.getHostCard() != null && pilot.lineActive()
                    && pilot.activeLineCards().contains(sa.getHostCard().getName())) {
                return true;
            }
            return super.confirmAction(sa, mode, message, options, cardToShow, params);
        }

        @Override
        public boolean playSaFromPlayEffect(SpellAbility tgtSa) {
            // PR-33: the "may cast the copy" half of a line card's Play
            // effect — stock's brain (canPlayFromEffectAI) won't-plays
            // Dramatic Reversal; while the line is live, the cast IS the
            // proven loop, so play it
            forge.game.card.Card host = tgtSa != null ? tgtSa.getHostCard() : null;
            if (host != null && pilot.lineActive()
                    && pilot.activeLineCards().contains(host.getName())) {
                return ComputerUtil.playStack(tgtSa, player, getGame());
            }
            return super.playSaFromPlayEffect(tgtSa);
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

        /**
         * PR-41f — THE tutor seam, found by measurement. Green Sun's Zenith
         * was cast 27 times in 101 games and Craterhoof entered 11 times,
         * while {@code tutor_decision} stayed at ZERO: the ranked hook was
         * never consulted, so every fetch target was the stock AI's pick.
         *
         * <p>Forge routes a ONE-card library search through
         * {@code chooseSingleCardForZoneChange} (singular) and a
         * multi-card one through {@code chooseCardsForZoneChange} (plural).
         * PR-18 already moved this hook once — from
         * chooseSingleEntityForEffect to the plural form — and landed one
         * seam short. This is the singular form.
         */
        @Override
        public forge.game.card.Card chooseSingleCardForZoneChange(
                forge.game.zone.ZoneType destination, List<forge.game.zone.ZoneType> origin,
                SpellAbility sa, forge.game.card.CardCollection fetchList,
                forge.game.player.DelayedReveal delayedReveal, String selectPrompt,
                boolean isOptional, Player decider) {
            // an armed step choice wins outright (the PR-27a seam)
            if (pendingChoice != null && decider == player) {
                for (forge.game.card.Card card : fetchList) {
                    if (card.getName().equals(pendingChoice)) {
                        pendingChoice = null;
                        return card;
                    }
                }
            }
            if (sa != null && decider == player && origin != null
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
                            return card;
                        }
                    }
                }
            }
            return super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList,
                    delayedReveal, selectPrompt, isOptional, decider);
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
