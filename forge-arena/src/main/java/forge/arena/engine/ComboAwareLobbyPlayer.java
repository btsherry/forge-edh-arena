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
        public record DrillOrder(String outletCard, String costHint,
                String prereqCard, String prereqCost) {
            public DrillOrder(String outletCard, String costHint) {
                this(outletCard, costHint, null, null);
            }
        }

        private DrillOrder activeDrill;
        /** Phase 11: the running compiled-program interpreter, if any. */
        private ProgramRunner activeProgram;
        /** PR-lambda: the mana-loop interpreter (program_class: mana_loop). */
        private ManaLoopRunner activeManaLoop;
        /** PR: the forked Selvala variable-yield loop (program_class: selvala_mana_loop). */
        private SelvalaManaLoopRunner activeSelvalaLoop;
        /** cast_recur (Body C self_recast + future bodies). */
        private CastRecurRunner activeCastRecur;
        /** PR-chi: the cast-bounce interpreter (program_class: cast_bounce). */
        private CastBounceRunner activeCastBounce;
        /** PR: the mana-funded bounce/ETB-recursion sink (program_class: bounce_recur). */
        private BounceRecurRunner activeBounceRecur;
        /** the creature the active bounce_recur runner wants Sabertooth/Kogla to
         * return this window — steers the hidden ChangeZone choice. */
        private String pendingRecurBounce;

        void setPendingRecurBounce(String cardName) {
            this.pendingRecurBounce = cardName;
        }

        private final java.util.Map<String, String> programClassCache =
                new java.util.HashMap<>();

        /** Cached per path; "unreadable" on parse failure — never a silent
         *  misroute to the wrong interpreter (panel). */
        private String programClassOf(String programPath) {
            return programClassCache.computeIfAbsent(programPath, path -> {
                try {
                    return new com.fasterxml.jackson.databind.ObjectMapper()
                            .readTree(new java.io.File(path))
                            .path("program_class").asText("ping_loop");
                } catch (Exception e) {
                    return "unreadable";
                }
            });
        }
        /** PR-eta: the live pairing runner — polled even with a non-empty
         *  stack, because respond-on-stack IS its job. */
        private PairingRunner activePairing;
        /** PR-kappa: one engine cycle in flight (brief — its own resolution only). */
        private EngineProgramRunner activeEngine;
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

        /**
         * PR-70: +1/+1 counters on the drill's outlet, or -1 if it is gone.
         * The single number that distinguishes a sustaining loop (stable or
         * rising) from a pinger consuming itself (falling to zero).
         */
        /**
         * PR-75: does the outlet ACTUALLY have lifelink right now? The whole
         * loop hinges on it — without lifelink the ping gains no life, the
         * engine never triggers, and the counter never returns. Everything so
         * far has inferred this from "we activated the grant"; this observes
         * the permanent itself.
         */
        private boolean outletHasLifelink(String outlet) {
            for (forge.game.card.Card c : player.getCardsIn(
                    forge.game.zone.ZoneType.Battlefield)) {
                if (c.getName().equals(outlet)) {
                    return c.hasKeyword(forge.game.keyword.Keyword.LIFELINK);
                }
            }
            return false;
        }

        private int outletCounters(String outlet) {
            for (forge.game.card.Card c : player.getCardsIn(
                    forge.game.zone.ZoneType.Battlefield)) {
                if (c.getName().equals(outlet)) {
                    return c.getCounters(forge.game.card.CounterEnumType.P1P1);
                }
            }
            return -1;
        }

        /**
         * PR-76: counters this ability's cost REMOVES, read from the
         * structured cost parts.
         *
         * <p>PR-70 and PR-73 both regex-matched {@code SubCounter<N/P1P1>}
         * against {@code Cost.toString()} — which renders human-readable
         * text ("Remove a +1/+1 counter from CARDNAME"), not script syntax.
         * Neither ever matched. assemblyX silently fell back to X=1 instead
         * of 2, and the drill's survival check silently returned "safe" and
         * let Ballista spend its last counter and die.
         *
         * <p>I parsed rendered text instead of structured data — the exact
         * mistake this project has spent a week diagnosing everywhere else
         * (oracle prose versus card scripts). Forge models this as a
         * {@link forge.game.cost.CostRemoveCounter} part; ask the object.
         */
        private static int countersRemovedByCost(SpellAbility ab) {
            if (ab == null || ab.getPayCosts() == null) {
                return 0;
            }
            int most = 0;
            for (forge.game.cost.CostPart part : ab.getPayCosts().getCostParts()) {
                if (part instanceof forge.game.cost.CostRemoveCounter rc
                        && rc.counter != null && rc.counter.is(forge.game.card.CounterEnumType.P1P1)) {
                    Integer n = rc.convertAmount();
                    most = Math.max(most, n == null ? 1 : n);
                }
            }
            return most;
        }

        /**
         * PR-72, corrected: this seam is NOT how Forge targets a wrapped
         * trigger. {@code chooseTargetsFor} is only invoked for scripted
         * {@code TargetingPlayer} flows ({@code prepareSingleSa}); a normal
         * queued trigger goes {@code MagicStack.chooseOrderOfSimultaneous-
         * StackEntry -> orderAndPlaySimultaneousSa -> brains.doTrigger()},
         * where CountersPutAi feeds {@code getBestAI()} — a fat Angel over a
         * 1/1 Ballista. PR-72's gate here never fired (measured: Lyra=1,
         * Ballista=1); the real obligation lives in the
         * {@link #orderAndPlaySimultaneousSa} override below. This narrow
         * form is kept for the rare TargetingPlayer case while a drill or
         * program is live.
         */
        @Override
        public boolean chooseTargetsFor(SpellAbility currentAbility) {
            String obligedOutlet = activeDrill != null ? activeDrill.outletCard()
                    : activeProgram != null ? activeProgram.outletCard() : null;
            if (obligedOutlet != null && currentAbility != null
                    && currentAbility.usesTargeting()
                    && currentAbility.getApi() == forge.game.ability.ApiType.PutCounter) {
                forge.game.card.Card outlet =
                        AbilityResolver.findBattlefield(player, obligedOutlet);
                if (outlet != null && currentAbility.canTarget(outlet)) {
                    currentAbility.resetTargets();
                    currentAbility.getTargets().add(outlet);
                    return true;
                }
            }
            return super.chooseTargetsFor(currentAbility);
        }

        /**
         * THE trigger-targeting seam. Forge routes every queued (wrapped)
         * triggered ability through this controller method on its way to the
         * stack; stock AI then picks targets in {@code brains.doTrigger()}
         * with {@code getBestAI()}. While a program is live, a trigger whose
         * source card carries a declared obligation
         * ({@code loop.trigger_obligations}) has its targets set to the
         * obliged card and goes to the stack directly — exactly what super
         * does after {@code doTrigger}, minus the AI's target choice. All
         * other entries keep stock behavior, including order.
         *
         * <p>Deck-agnostic: the obligation names cards in the COMPILED
         * PROGRAM, never in code. An override, not a parent patch.
         */
        @Override
        public void orderAndPlaySimultaneousSa(List<SpellAbility> activePlayerSAs) {
            if (activeProgram == null && activeCastBounce == null) {
                super.orderAndPlaySimultaneousSa(activePlayerSAs);
                return;
            }
            List<SpellAbility> rest = new java.util.ArrayList<>();
            for (SpellAbility sa : activePlayerSAs) {
                // PR-chi: the cast-bounce runner's obligation ALTERNATES by
                // loop half (bounce the rock while the fodder's cast is
                // live, the fodder while the rock's recast is), so it is
                // asked per-phase rather than per-program
                String obliged = sa.isTrigger() && !sa.isCopied() && sa.getHostCard() != null
                        ? (activeProgram != null
                                ? activeProgram.obligedTargetFor(sa.getHostCard().getName())
                                : activeCastBounce.obligedTargetForPhase(
                                        sa.getHostCard().getName()))
                        : null;
                forge.game.card.Card target = obliged == null ? null
                        : AbilityResolver.findBattlefield(player, obliged);
                // PR-psi: an obliged CHARM trigger (Hullbreaker Horror's
                // "choose up to one") needs its mode chosen before any
                // targeting sub-ability exists. CharmEffect.makeChoices
                // routes through our chooseModeForAbility override below,
                // which picks the mode that can target the obliged card —
                // structurally, no mode names in code. A charm whose choice
                // fails falls to stock (MinCharmNum 0: stock may decline;
                // the runner's zone-proof measures the consequence).
                if (target != null && sa.getApi() == forge.game.ability.ApiType.Charm
                        && !forge.game.ability.effects.CharmEffect.makeChoices(sa)) {
                    rest.add(sa);
                    continue;
                }
                // the wrapper itself may not target — walk to the
                // (sub)ability that does
                SpellAbility targeting = sa;
                while (targeting != null && !targeting.usesTargeting()) {
                    targeting = targeting.getSubAbility();
                }
                if (target != null && targeting != null && targeting.canTarget(target)) {
                    targeting.resetTargets();
                    targeting.getTargets().add(target);
                    ComputerUtil.playStack(sa, player, getGame());
                } else {
                    rest.add(sa);
                }
            }
            if (!rest.isEmpty()) {
                super.orderAndPlaySimultaneousSa(rest);
            }
        }

        /**
         * PR-psi: mode choice for an obliged CHARM trigger. Forge routes
         * every charm mode decision through this controller method (
         * {@code CharmEffect.makeChoices -> chooseModeForAbility}); while a
         * cast-bounce program is live and the trigger's source carries the
         * program's obligation, the chosen mode is the one that CAN TARGET
         * the obliged card — for Hullbreaker Horror that is structurally
         * "return target nonland permanent" over the spell-return mode,
         * with no mode names or indices in code. Everything else keeps
         * stock behavior, including declining (MinCharmNum 0).
         */
        @Override
        public List<forge.game.spellability.AbilitySub> chooseModeForAbility(
                SpellAbility sa, List<forge.game.spellability.AbilitySub> possible,
                int min, int num, boolean allowRepeat) {
            // PR-nu: a CAST charm the pilot chose as a library tutor picks its
            // library-search mode (Archdruid's Charm: creature/land search).
            // The fetch target is then steered by chooseCardsForZoneChange ->
            // rankTutor (PR-mu completes the closest combo). Consumed once.
            if (pilotCharmTutorHost != null && sa != null && !sa.isTrigger()
                    && sa.getHostCard() != null
                    && pilotCharmTutorHost.equals(sa.getHostCard().getName())) {
                pilotCharmTutorHost = null;
                for (forge.game.spellability.AbilitySub sub : possible) {
                    if (sub.getApi() == forge.game.ability.ApiType.ChangeZone
                            && String.valueOf(sub.getParam("Origin")).contains("Library")) {
                        java.util.List<forge.game.spellability.AbilitySub> chosen =
                                new java.util.ArrayList<>();
                        chosen.add(sub);
                        return chosen;
                    }
                }
            }
            if (activeCastBounce != null && sa != null && sa.isTrigger()
                    && sa.getHostCard() != null) {
                String obliged = activeCastBounce.obligedTargetForPhase(
                        sa.getHostCard().getName());
                forge.game.card.Card target = obliged == null ? null
                        : AbilityResolver.findBattlefield(player, obliged);
                if (target != null) {
                    for (forge.game.spellability.AbilitySub sub : possible) {
                        if (sub.usesTargeting() && sub.canTarget(target)) {
                            // MUTABLE list — CharmEffect.chainAbilities sorts
                            // the returned list in place (List.of() throws)
                            java.util.List<forge.game.spellability.AbilitySub> chosen =
                                    new java.util.ArrayList<>();
                            chosen.add(sub);
                            return chosen;
                        }
                    }
                }
            }
            return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
        }

                /**
         * PR-73: would paying the outlet's own activation cost kill it?
         *
         * <p>Walking Ballista removes a +1/+1 counter to deal damage, and its
         * toughness IS those counters. Spend the last one and it becomes 0/0
         * — state-based actions bury it as the cost is paid, before the
         * lifelink damage resolves, so the life gain and the engine's trigger
         * arrive with nothing to put the counter back on. The loop kills
         * itself on its final iteration and looks like "the drill only ran
         * once".
         *
         * <p>This is precisely what Commander Spellbook's prerequisite
         * protects — "Walking Ballista has at least two +1/+1 counters on
         * it" — and the drill had no notion of it. Deck-agnostic: never pay a
         * cost that destroys the source of the ability being paid for.
         */
        private boolean outletSurvivesItsOwnCost(String outlet) {
            for (forge.game.card.Card c : player.getCardsIn(
                    forge.game.zone.ZoneType.Battlefield)) {
                if (!c.getName().equals(outlet)) {
                    continue;
                }
                int spend = 0;
                for (SpellAbility ab : c.getSpellAbilities()) {
                    spend = Math.max(spend, countersRemovedByCost(ab));
                }
                // no counter-spending ability -> the cost cannot kill it
                return spend == 0 || c.getNetToughness() - spend > 0;
            }
            return true;
        }

        /** The next drill activation, or null (disarms when done/failed). */
        private List<SpellAbility> drillStep(int turn) {
            if (activeDrill == null) {
                return null;
            }
            // PLAY-OBSERVATIONS finding 3: ONE shot in flight at a time. The
            // drill used to re-activate every priority window while its own
            // shot sat on the stack — measured: four stacked PayLife<50>
            // shots against a 40-life opponent (150 life of overkill), then
            // 196 refused windows to the bound before the stack resolved.
            // Waiting for resolution lets the kill be SEEN before the next
            // cost is paid; opponent interaction landing mid-drill still
            // works (the wait is the step model's interrupt window).
            if (!getGame().getStack().isEmpty()) {
                return null;
            }
            // PR-77: lifelink is granted "until end of turn". The drill runs
            // across turns, so on every turn after the first it was pinging
            // with no lifelink — gaining no life, triggering nothing, and the
            // counter never returning. Observed directly: the second logged
            // drill step read outlet_lifelink=false. A drill must MAINTAIN
            // its own precondition, not assume a one-time setup persists.
            if (activeDrill.prereqCard() != null
                    && !outletHasLifelink(activeDrill.outletCard())) {
                SpellAbility regrant = AbilityResolver.resolve(player,
                        activeDrill.prereqCard(), activeDrill.prereqCost(),
                        List.of(activeDrill.outletCard()));
                if (regrant != null
                        && ComputerUtil.handlePlayingSpellAbility(player, regrant, () -> { })) {
                    pilot.observe(forge.arena.report.ArenaEvent.of(
                            "loop_prereq", turn, seatIndex)
                            .with("card", activeDrill.prereqCard())
                            .with("cost", activeDrill.prereqCost())
                            .with("target", activeDrill.outletCard())
                            .with("regrant", true));
                    // yield so it RESOLVES before the next ping (the LIFO
                    // stack lesson from PR-74)
                    return null;
                }
            }
            if (!outletSurvivesItsOwnCost(activeDrill.outletCard())) {
                // hold this window rather than destroy the engine: the
                // deck's own life gain refills the counter and the loop
                // resumes next priority
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
            pilot.reportDrillStep(turn, activeDrill.outletCard(), target.getId(),
                    drillIterations, outletCounters(activeDrill.outletCard()),
                    player.getLife(), outletHasLifelink(activeDrill.outletCard()));
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

        /**
         * While the forked Selvala loop is active, bank ITS needed colour from
         * every "any/combo" mana its producer makes. ManaEffect asks the
         * controller for combo colours at RESOLUTION — after the ability is
         * cloned onto the stack, which drops any express choice set on the
         * pre-play SA — so the controller is the only place the pick sticks.
         * Selvala's own {G} re-activation and Genesis Wave's {G}{G}{G} tail
         * both need the banked pool to actually be green.
         */
        @Override
        public byte chooseColor(String message, SpellAbility sa, forge.card.ColorSet colors) {
            if (activeSelvalaLoop != null) {
                byte need = activeSelvalaLoop.neededColor();
                if (colors.hasAnyColor(need)) {
                    return need;
                }
            }
            return super.chooseColor(message, sa, colors);
        }

        @Override
        public java.util.Map<Byte, Integer> specifyManaCombo(SpellAbility sa,
                forge.card.ColorSet colorSet, int manaAmount, boolean different) {
            if (activeSelvalaLoop != null && !different) {
                byte need = activeSelvalaLoop.neededColor();
                if (colorSet.hasAnyColor(need)) {
                    java.util.Map<Byte, Integer> all = new java.util.LinkedHashMap<>();
                    all.put(need, manaAmount);
                    return all;
                }
            }
            return super.specifyManaCombo(sa, colorSet, manaAmount, different);
        }

        /**
         * Deck-agnostic ETB-draw engines: a creature entering under our control
         * makes us draw. The Genesis Wave flip (SP$ Dig, DestinationZone
         * Battlefield, ChangeNum Any) enters ~40 creatures at once and each
         * fires a MANDATORY draw that never routes through confirmAction — the
         * only reason library_reserve had to sit at 35. "Order the engine last"
         * does NOT help: Forge collects the batch's ETB triggers in one
         * deferred pass over the full active-trigger set after every card has
         * entered, so the engine sees every co-entrant regardless of move order
         * (verified against DigEffect/TriggerHandler). Keeping the engine OUT
         * of the flip (it falls to the graveyard via DestinationZone2) is the
         * only fix — then the reserve can drop to ~10 and we flip ~89%.
         */
        static final java.util.Set<String> FLIP_DRAW_ENGINES = java.util.Set.of(
                "The Great Henge", "Guardian Project", "Beast Whisperer",
                "Garruk's Uprising", "Elemental Bond", "Colossal Majesty");

        @Override
        public <T extends forge.game.GameEntity> List<T> chooseEntitiesForEffect(
                forge.util.collect.FCollectionView<T> optionList, int min, int max,
                forge.game.player.DelayedReveal delayedReveal, SpellAbility sa, String title,
                Player relatedPlayer, java.util.Map<String, Object> params) {
            // Scope: ONLY the live Selvala flip. ApiType.Dig is Genesis Wave's
            // selection; every other effect and every other deck (activeSelvala
            // Loop == null) falls straight through to stock.
            if (activeSelvalaLoop != null && sa != null
                    && sa.getApi() == forge.game.ability.ApiType.Dig) {
                forge.util.collect.FCollection<T> kept = new forge.util.collect.FCollection<>();
                for (T t : optionList) {
                    if (t instanceof forge.game.card.Card
                            && FLIP_DRAW_ENGINES.contains(((forge.game.card.Card) t).getName())) {
                        continue; // don't flip a mandatory ETB-draw engine onto the board
                    }
                    kept.add(t);
                }
                return super.chooseEntitiesForEffect(kept, Math.min(min, kept.size()),
                        Math.min(max, kept.size()), delayedReveal, sa, title, relatedPlayer, params);
            }
            return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title,
                    relatedPlayer, params);
        }

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
            // PR-eta: an active pairing owns every window — including the
            // ones with its own wipe on the stack (respond-on-stack is the
            // designed exception to the yield-while-stack-full invariant)
            if (activePairing != null) {
                List<SpellAbility> step = activePairing.next(turn);
                if (activePairing.finished()) {
                    activePairing = null;
                }
                if (step != null) {
                    return step;
                }
                if (activePairing != null) {
                    return null;
                }
            }
            // PR-kappa: an engine cycle owns windows only across its own
            // resolution — the measure lands, the seat comes right back
            if (activeEngine != null) {
                List<SpellAbility> step = activeEngine.next(turn);
                if (activeEngine.finished()) {
                    activeEngine = null;
                }
                if (step != null) {
                    return step;
                }
                if (activeEngine != null) {
                    return null;
                }
            }
            // PR-31: an armed paired-play protection fires at the first
            // priority with our trigger on the stack — cast it in response.
            // PR-eta: only the turn it was armed — a stale shield (its wipe's
            // cast silently failed) must not fire into unrelated stacks,
            // including a compiled pairing's own wipe
            pilot.expireStaleProtection(turn);
            if (pilot.pendingProtectionFresh(turn) && !game.getStack().isEmpty()) {
                SpellAbility protection = AbilityResolver.resolveCast(
                        player, pilot.pendingProtection());
                pilot.protectionResolved(turn, protection != null);
                if (protection != null) {
                    return Collections.singletonList(protection);
                }
            }
            // REACTIVE PROTECTION: an opponent's spell/ability on the stack is
            // pointed at one of OUR combo pieces -> cast the cheapest covering
            // instant (Heroic Intervention class) in response to save it, before
            // resuming any loop. Keeps an assembled combo alive through removal —
            // the resilience half of the assembly frontier.
            SpellAbility cover = reactiveProtect(turn);
            if (cover != null) {
                return Collections.singletonList(cover);
            }
            SeatView view = SeatViews.of(player, seatIndex, turn);
            boolean entryWindowOpen = game.getPhaseHandler().is(PhaseType.MAIN1, player)
                    && game.getStack().isEmpty();
            java.util.function.Function<forge.arena.combo.LineExecutor, forge.arena.combo.SimResult>
                    validator = executor -> {
                        // PR-68: one seam, so every executor gains the
                        // diagnostic without any of them changing. A blocked
                        // result carries WHY out of the sandbox.
                        GameSimHandle handle = GameSimHandle.copyOf(game, player);
                        forge.arena.combo.SimResult proof = executor.validate(handle);
                        return proof.isBlocked()
                                ? proof.withDiagnostic(handle.lastFailure()) : proof;
                    };
            if (activeProgram != null) {
                List<SpellAbility> step = activeProgram.next(turn);
                if (activeProgram != null && activeProgram.finished()) {
                    activeProgram = null;
                }
                if (step != null) {
                    return step;
                }
                if (activeProgram != null) {
                    return null;
                }
            }
            if (activeCastRecur != null) {
                List<SpellAbility> step = activeCastRecur.next(turn);
                if (activeCastRecur.finished()) {
                    activeCastRecur = null;
                }
                if (step != null) {
                    return step;
                }
                if (activeCastRecur != null) {
                    return null;
                }
            }
            if (activeBounceRecur != null) {
                List<SpellAbility> step = activeBounceRecur.next(turn);
                if (activeBounceRecur.finished()) {
                    activeBounceRecur = null;
                }
                if (step != null) {
                    return step;
                }
                if (activeBounceRecur != null) {
                    return null;
                }
            }
            if (activeManaLoop != null) {
                List<SpellAbility> step = activeManaLoop.next(turn);
                String imprint = activeManaLoop.pendingImprint();
                if (imprint != null) {
                    // the Scepter cast just returned — steer its imprint
                    // trigger through the proven PR-27a choice seam
                    pendingChoice = imprint;
                    pendingChoiceTurn = turn;
                }
                if (activeManaLoop.finished()) {
                    activeManaLoop = null;
                }
                if (step != null) {
                    return step;
                }
                if (activeManaLoop != null) {
                    return null;
                }
            }
            if (activeSelvalaLoop != null) {
                List<SpellAbility> step = activeSelvalaLoop.next(turn);
                if (activeSelvalaLoop.finished()) {
                    activeSelvalaLoop = null;
                }
                if (step != null) {
                    return step;
                }
                if (activeSelvalaLoop != null) {
                    return null;
                }
            }
            if (activeCastBounce != null) {
                List<SpellAbility> step = activeCastBounce.next(turn);
                if (activeCastBounce.finished()) {
                    activeCastBounce = null;
                }
                if (step != null) {
                    return step;
                }
                if (activeCastBounce != null) {
                    return null;
                }
            }
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
                        // PR-lambda (panel): an AURA program piece is as
                        // destructive misplayed as a spent one-shot — stock
                        // enchanting Power Artifact onto the wrong artifact
                        // dead-ends the compiled program for the game
                        boolean spends = sa.isForetelling()
                                || (sa.isSpell() && host != null
                                        && (!host.getType().isPermanent()
                                            || host.isAura()));
                        if (spends && host != null
                                && pilot.reservedCastNames(view).contains(host.getName())) {
                            return null; // pass — reserved for the pilot's play
                        }
                    }
                }
                return stock;
            }
            if (!action.isStep() && action.program() != null) {
                // Phase 11: hand the window to the interpreter. No drill, no
                // archetype — the program is the only path for this combo.
                // PR-lambda: the program's declared class picks the runner.
                String programClass = programClassOf(action.program().programPath());
                if (!"ping_loop".equals(programClass) && !"mana_loop".equals(programClass)
                        && !"cast_bounce".equals(programClass)
                        && !"cast_recur".equals(programClass)
                        && !"bounce_recur".equals(programClass)
                        && !"selvala_mana_loop".equals(programClass)
                        && !"unreadable".equals(programClass)) {
                    // a compiled program whose runner is not built yet ships
                    // FLAGGED: abort loudly, never misroute to ProgramRunner
                    pilot.observe(forge.arena.report.ArenaEvent.of(
                            "program_abort", turn, seatIndex)
                            .with("combo", action.program().comboId())
                            .with("reason", "program_class_unsupported: " + programClass));
                    return super.chooseSpellAbilityToPlay();
                }
                if ("unreadable".equals(programClass)) {
                    pilot.observe(forge.arena.report.ArenaEvent.of(
                            "program_abort", turn, seatIndex)
                            .with("combo", action.program().comboId())
                            .with("reason", "program_unreadable: "
                                    + action.program().programPath()));
                    return super.chooseSpellAbilityToPlay();
                }
                if ("bounce_recur".equals(programClass)) {
                    // PR: the mana-funded bounce/ETB-recursion sink
                    activeBounceRecur = new BounceRecurRunner(getGame(), player, pilot,
                            this, seatIndex, action.program().programPath());
                    List<SpellAbility> first = activeBounceRecur.next(turn);
                    if (activeBounceRecur.finished()) {
                        activeBounceRecur = null;
                    }
                    return first;
                }
                if ("cast_bounce".equals(programClass)) {
                    // PR-chi: the Tidespout family's interpreter
                    activeCastBounce = new CastBounceRunner(getGame(), player, pilot,
                            seatIndex, action.program().programPath());
                    List<SpellAbility> first = activeCastBounce.next(turn);
                    if (activeCastBounce.finished()) {
                        activeCastBounce = null;
                    }
                    return first;
                }
                if ("cast_recur".equals(programClass)) {
                    activeCastRecur = new CastRecurRunner(getGame(), player, pilot,
                            seatIndex, action.program().programPath());
                    List<SpellAbility> first = activeCastRecur.next(turn);
                    if (activeCastRecur.finished()) {
                        activeCastRecur = null;
                    }
                    return first;
                }
                if ("selvala_mana_loop".equals(programClass)) {
                    // PR: the forked variable-yield loop (producer != untapper)
                    activeSelvalaLoop = new SelvalaManaLoopRunner(getGame(), player, pilot,
                            seatIndex, action.program().programPath());
                    List<SpellAbility> first = activeSelvalaLoop.next(turn);
                    if (activeSelvalaLoop.finished()) {
                        activeSelvalaLoop = null;
                    }
                    return first;
                }
                if ("mana_loop".equals(programClass)) {
                    activeManaLoop = new ManaLoopRunner(getGame(), player, pilot,
                            seatIndex, action.program().programPath());
                    List<SpellAbility> first = activeManaLoop.next(turn);
                    String imprint = activeManaLoop.pendingImprint();
                    if (imprint != null) {
                        pendingChoice = imprint;
                        pendingChoiceTurn = turn;
                    }
                    if (activeManaLoop.finished()) {
                        activeManaLoop = null;
                    }
                    return first;
                }
                activeProgram = new ProgramRunner(getGame(), player, pilot,
                        seatIndex, action.program().programPath());
                return activeProgram.next(turn);
            }
            if (!action.isStep() && action.engine() != null) {
                // PR-kappa panel blocker: a gate-failed cycle must HAND THE
                // WINDOW BACK — returning the runner's null told PhaseHandler
                // 'I pass' and silently forfeited the seat's entire MAIN1
                // every turn the pieces were out with a failed gate. And an
                // armed drill outranks a card-advantage durdle: it IS the
                // conversion in progress.
                if (activeDrill == null) {
                    activeEngine = new EngineProgramRunner(getGame(), player, pilot,
                            seatIndex, action.engine().programPath());
                    List<SpellAbility> first = activeEngine.next(turn);
                    if (activeEngine.finished()) {
                        activeEngine = null;
                    }
                    if (first != null) {
                        return first;
                    }
                }
                List<SpellAbility> drill = drillStep(turn);
                if (drill != null) {
                    return drill;
                }
                return super.chooseSpellAbilityToPlay();
            }
            if (!action.isStep() && action.pairing() != null) {
                // PR-eta: wipe + shield, respond-on-stack, measured verify.
                activePairing = new PairingRunner(getGame(), player, pilot,
                        seatIndex, action.pairing().programPath());
                List<SpellAbility> first = activePairing.next(turn);
                if (activePairing.finished()) {
                    activePairing = null;
                }
                return first;
            }
            if (!action.isStep() && action.drill() != null) {
                // PR-38: the planner picked a single-target sink. PROVE it on
                // a copy first (an "any target" ability that cannot actually
                // drop a life total must never arm a 200-iteration drill),
                // then arm and fire the first activation in this same window.
                String outlet = action.drill().outletCard();
                if (GameSimHandle.copyOf(game, player).activateAtOpponent(outlet, null)) {
                    // PR-71: perform Spellbook's step 1 in the REAL game.
                    // Validation proved it on a copy; the live board still
                    // needs the grant, or the drill's first ping gains no
                    // life, the engine never triggers, and the counter never
                    // returns — a loop that was proven and then not run.
                    boolean grantedThisWindow = false;
                    if (action.drill().prereqCard() != null) {
                        SpellAbility grant = AbilityResolver.resolve(player,
                                action.drill().prereqCard(),
                                action.drill().prereqCost(), List.of(outlet));
                        if (grant != null) {
                            grantedThisWindow = ComputerUtil.handlePlayingSpellAbility(
                                    player, grant, () -> { });
                            pilot.observe(forge.arena.report.ArenaEvent.of(
                                    "loop_prereq", turn, seatIndex)
                                    .with("card", action.drill().prereqCard())
                                    .with("cost", action.drill().prereqCost())
                                    .with("target", outlet)
                                    .with("played", grantedThisWindow));
                        }
                    }
                    armDrill(new DrillOrder(outlet, null,
                            action.drill().prereqCard(), action.drill().prereqCost()));
                    // PR-74: do NOT ping in the same priority window as the
                    // grant. handlePlayingSpellAbility puts the lifelink
                    // ability on the STACK; it does not resolve it (which is
                    // why GameSimHandle calls resolveStack explicitly after
                    // its own activations). Firing the drill here stacks the
                    // ping ON TOP of the grant, and the stack resolves LIFO —
                    // so the ping resolved FIRST, with no lifelink, gaining
                    // no life, triggering nothing, and taking Ballista's last
                    // counter with it.
                    //
                    // Ben's read was right: lifelink was never actually on
                    // the Walker when it fired. Yield this window so the
                    // grant resolves; the drill starts next priority with
                    // lifelink genuinely active.
                    if (grantedThisWindow) {
                        return null;
                    }
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

        /**
         * An opponent's stack object aimed at one of our combo pieces -> the
         * cheapest covering instant we can cast in response, or null. Only the
         * TOP object (the imminent threat); our own spells/abilities are skipped
         * (so the cover we just cast never re-triggers this).
         */
        private SpellAbility reactiveProtect(int turn) {
            if (getGame().getStack().isEmpty()) {
                return null;
            }
            SpellAbility top = getGame().getStack().peekAbility();
            if (top == null || top.getActivatingPlayer() == null
                    || player.equals(top.getActivatingPlayer()) // our own spell/ability
                    || top.getTargets() == null) {
                return null;
            }
            forge.game.card.Card threatened = null;
            for (forge.game.card.Card t : top.getTargets().getTargetCards()) {
                if (player.equals(t.getController()) && pilot.isProgramPiece(t.getName())) {
                    threatened = t;
                    break;
                }
            }
            if (threatened == null) {
                return null;
            }
            String cover = pilot.reactiveCover(SeatViews.of(player, seatIndex, turn),
                    threatened.isCreature());
            if (cover == null) {
                return null;
            }
            SpellAbility sa = AbilityResolver.resolveCast(player, cover);
            if (sa != null) {
                pilot.observe(forge.arena.report.ArenaEvent.of("piece_protected", turn, seatIndex)
                        .with("piece", threatened.getName()).with("cover", cover)
                        .with("threat", top.getHostCard() != null
                                ? top.getHostCard().getName() : "?"));
            }
            return sa;
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
            } else if ("equip".equals(step.action())) {
                // assemble-and-deploy: attach a combo's equipment to its host
                // (Umbral Mantle -> Selvala) so the untapper combo comes online
                sa = AbilityResolver.resolveEquip(player, step.card(),
                        step.targets().isEmpty() ? null : step.targets().get(0));
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
            } else if (step.isCast() && sa.getPayCosts() != null
                    && sa.getPayCosts().hasXInAnyCostPart() && manaOnlyX(sa.getPayCosts())) {
                // PR-69: an ASSEMBLY cast with no scripted X defaults to X=0,
                // and X=0 is frequently fatal. Traced in a real game:
                //
                //   zone_change  Walking Ballista  Stack -> Battlefield
                //   combo_ready  1274-3693 (Heliod + Ballista)
                //   zone_change  Walking Ballista  Battlefield -> Graveyard
                //   line_aborted not_assemblable
                //
                // Ballista is ManaCost:X X, PT:0/0, K:etbCounter:P1P1:X — at
                // X=0 it enters as a 0/0 with no counters and state-based
                // actions bury it on resolution, destroying the combo it had
                // just completed. Giada's combo reached READY 11 times in 30
                // games and fired ZERO.
                //
                // Assembly wants the piece FUNCTIONAL, not large: X=1 gives
                // Ballista a body and one counter of ammunition, and leaves
                // mana for the payoff half (Heliod's {1}{W} lifelink). Paying
                // more would buy a bigger Ballista and no combo. Deck-
                // agnostic: any X-cost assembly piece gets minimum viability
                // rather than zero.
                sa.setXManaCostPaid(assemblyX(sa.getHostCard()));
            }
            // PR-27a: arm the resolution-choice hint (Sabertooth's bounce,
            // Scepter's imprint) — persists within the turn until consumed
            if (step.choice() != null) {
                pendingChoice = step.choice();
                pendingChoiceTurn = getGame().getPhaseHandler().getTurn();
            }
            return Collections.singletonList(sa);
        }

        /**
         * PR-69: X for an assembly cast that scripts none. One, not zero —
         * zero is a 0/0 that dies on resolution. Minimum viability, because
         * assembly must leave mana for the payoff.
         */
        static final int ASSEMBLY_MIN_X = 1;

        /**
         * PR-70: the X an assembly cast needs to be USABLE, not merely alive.
         *
         * <p>PR-69 fixed X=0 (a 0/0 that dies on resolution) by paying 1. That
         * was still not enough for a piece that SPENDS its own counters:
         * Walking Ballista at one counter pings once, becomes a 0/0, and dies
         * before the combo can hand the counter back. Commander Spellbook says
         * so outright — both of this deck's combos list the prerequisite
         * "Walking Ballista has at least two +1/+1 counters on it."
         *
         * <p>Derived from the card, not hardcoded: a permanent that enters
         * with X counters, has no base toughness of its own, and carries an
         * ability costing {@code SubCounter<N/P1P1>} needs X > N or using that
         * ability kills it. Any deck's equivalent piece gets the same
         * treatment; nothing here names a card.
         */
        private int assemblyX(forge.game.card.Card host) {
            if (host == null || host.getCurrentToughness() > 0) {
                return ASSEMBLY_MIN_X;
            }
            int mostCountersSpent = 0;
            for (SpellAbility ab : host.getSpellAbilities()) {
                mostCountersSpent = Math.max(mostCountersSpent, countersRemovedByCost(ab));
            }
            // survive spending them once: N counters spent needs N+1 present
            return Math.max(ASSEMBLY_MIN_X, mostCountersSpent + 1);
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
        /** PR-nu: host name of a modal CHARM the pilot cast AS a tutor, so the
         *  mode-choice hook forces its library-search mode (Archdruid's Charm).
         *  Set when findCastableTutor returns a charm; consumed once at the
         *  resolving chooseModeForAbility. */
        private String pilotCharmTutorHost;

        /** PR-nu: does this Charm have a mode that searches the LIBRARY (a
         *  ChangeZone from Library)? makePossibleOptions already drops modes
         *  that would be illegal now, so a returned search mode is castable. */
        private boolean charmHasLibrarySearch(SpellAbility charm) {
            for (forge.game.spellability.AbilitySub sub
                    : forge.game.ability.effects.CharmEffect.makePossibleOptions(charm)) {
                if (sub.getApi() == forge.game.ability.ApiType.ChangeZone
                        && String.valueOf(sub.getParam("Origin")).contains("Library")) {
                    return true;
                }
            }
            return false;
        }

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
                    if (!sa.isSpell()) {
                        continue;
                    }
                    boolean directTutor = sa.getApi() == forge.game.ability.ApiType.ChangeZone
                            && String.valueOf(sa.getParam("Origin")).contains("Library");
                    // PR-nu: a modal CHARM whose search mode is a library
                    // ChangeZone is a tutor too (Archdruid's Charm: creature/
                    // land search). getApi() is Charm, so the direct test above
                    // misses it — inspect the mode options. The search mode is
                    // forced at resolution by chooseModeForAbility below.
                    boolean charmTutor = false;
                    if (!directTutor && sa.getApi() == forge.game.ability.ApiType.Charm) {
                        sa.setActivatingPlayer(player);
                        charmTutor = charmHasLibrarySearch(sa);
                    }
                    if (!directTutor && !charmTutor) {
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
                    if (charmTutor) {
                        pilotCharmTutorHost = c.getName(); // steer the mode choice
                    }
                    return sa;
                }
            }
            // B6: activated-ability tutors already ON THE BATTLEFIELD (Inventors'
            // Fair {5},{T},Sac an artifact: search for an artifact) — the hand-
            // only scan above misses them, and for an artifact deck that is the
            // ONLY library route to Staff/Umbral. Same ChangeZone-from-Library
            // structure, activated rather than cast; the target is still steered
            // by rankTutor at resolution.
            for (forge.game.card.Card c : player.getCardsIn(forge.game.zone.ZoneType.Battlefield)) {
                if (tutorTried.contains(c.getName()) || reserved.contains(c.getName())) {
                    continue;
                }
                for (SpellAbility sa : c.getAllPossibleAbilities(player, true)) {
                    if (!sa.isActivatedAbility()
                            || sa.getApi() != forge.game.ability.ApiType.ChangeZone
                            || !String.valueOf(sa.getParam("Origin")).contains("Library")) {
                        continue;
                    }
                    sa.setActivatingPlayer(player);
                    if (sa.getPayCosts() != null && sa.getPayCosts().hasXInAnyCostPart()) {
                        int pool = player.getManaPool().totalMana();
                        int x = pool > 1 ? Math.min(pool - 1, POOL_TUTOR_X) : 0;
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
         * PR-C: apply our damage amplifiers to a projected damage figure.
         *
         * <p>The red deck's amplifiers were counted as nothing, so lethality
         * under-projected by up to 4x and declined attacks and drill
         * activations that were genuinely lethal.
         *
         * <p><b>Composition order is the whole subtlety.</b> When several
         * replacement effects apply to one damage event the AFFECTED PLAYER
         * chooses their order, and the two orders differ:
         *
         * <pre>
         *   additive first        (2+2) x 2 = 8
         *   multiplicative first  (2x2) + 2 = 6
         * </pre>
         *
         * The opponent picks whichever keeps them alive, so a projection that
         * must never over-claim has to assume the WORSE one — multipliers
         * first, then additions, and claim 6. Assuming 8 is the Phase 7
         * failure repeating: attack on a projection the opponent can
         * invalidate, they survive at 2, and we are tapped out against a
         * table of three.
         */
        private int amplified(int base) {
            if (base <= 0) {
                return base;
            }
            int multiplier = 1;
            int bonus = 0;
            for (forge.game.card.Card c : player.getCardsIn(
                    forge.game.zone.ZoneType.Battlefield)) {
                if (!pilot.amplifierNames().contains(c.getName())) {
                    continue;
                }
                String text = c.getOracleText() == null ? "" : c.getOracleText().toLowerCase();
                if (text.contains("double that damage") || text.contains("twice that much")) {
                    multiplier *= 2;
                } else {
                    java.util.regex.Matcher m = java.util.regex.Pattern
                            .compile("plus (\\d+)|(\\d+) more damage").matcher(text);
                    if (m.find()) {
                        bonus += Integer.parseInt(m.group(1) != null ? m.group(1) : m.group(2));
                    }
                }
            }
            // multipliers FIRST, then additions: the opponent's choice
            return base * multiplier + bonus;
        }

        /**
         * PR-34: a kill order when combat math GUARANTEES an elimination
         * right now, else null. Worst case per opponent: they block and
         * fully absorb our TOP-power B attackers (B = their untapped
         * creatures); if the remaining power still meets their life, the
         * kill cannot be combat-tricked below lethal by blocks alone. A
         * conservative lower bound — trample, menace, and flash blockers
         * all shift it in known directions; guarantee beats greed.
         */
        /**
         * PLAY-OBSERVATIONS finding 1 (chi30 game 17): the all-at-one-head
         * rule sent 50 power into a 9-life head — 41 damage of overkill —
         * and cleared the table in three combats where two sufficed. The
         * order now PARTITIONS: after the first head's worst-case-lethal
         * allocation is reserved, the remaining pool is tested against the
         * next head under the same worst-case rule, and only INDIVIDUALLY
         * guaranteed allocations split off. Leftover power piles onto the
         * first head as trick-buffer, so the single-head case is exactly
         * the old behavior. Greedy biggest-first per head — suboptimal
         * partitions are possible, but every claimed kill keeps the PR-34
         * guarantee semantics (worst case: the head's untapped creatures
         * absorb the TOP-B allocated attackers).
         */
        private java.util.Map<Integer, List<forge.game.card.Card>> lethalPartition;
        private int lethalPartitionTurn = -1;

        private ComboPilot.CombatOrder lethalAlphaOrder(int turn) {
            lethalPartition = null;
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
            // biggest-first pool; each head consumes its allocation
            List<forge.game.card.Card> pool = new java.util.ArrayList<>(ready);
            pool.sort(java.util.Comparator.comparingInt(
                    forge.game.card.Card::getNetPower).reversed());
            java.util.Map<Integer, List<forge.game.card.Card>> partition =
                    new java.util.LinkedHashMap<>();
            List<Player> killedHeads = new java.util.ArrayList<>();
            for (Player opp : alive) {
                int blockers = 0;
                for (forge.game.card.Card c : opp.getCreaturesInPlay()) {
                    if (!c.isTapped()) {
                        blockers++;
                    }
                }
                List<forge.game.card.Card> alloc = new java.util.ArrayList<>();
                int allocatedBeyondAbsorbers = 0;
                boolean lethal = false;
                for (forge.game.card.Card c : pool) {
                    if (!forge.game.combat.CombatUtil.canAttack(c, opp)) {
                        continue;
                    }
                    alloc.add(c);
                    if (alloc.size() > blockers) {
                        // pool is power-desc, so alloc is too: the first B
                        // are the worst-case absorbers, everything after
                        // them is guaranteed through
                        allocatedBeyondAbsorbers += Math.max(0, c.getNetPower());
                        int guaranteed = amplified(allocatedBeyondAbsorbers);
                        if (guaranteed >= opp.getLife() && guaranteed > 0) {
                            lethal = true;
                            break;
                        }
                    }
                }
                if (lethal) {
                    partition.put(opp.getId(), alloc);
                    killedHeads.add(opp);
                    pool.removeAll(alloc);
                }
            }
            if (killedHeads.isEmpty()) {
                return null;
            }
            // leftover, non-guaranteeing power piles onto the FIRST head as
            // buffer against tricks — with one guaranteed head this is
            // byte-for-byte the old all-in behavior
            Player head0 = killedHeads.get(0);
            partition.get(head0.getId()).addAll(pool);
            List<Integer> killOrder = new java.util.ArrayList<>();
            for (Player p : killedHeads) {
                killOrder.add(p.getId());
            }
            for (Player p : alive) {
                if (!killOrder.contains(p.getId())) {
                    killOrder.add(p.getId());
                }
            }
            int head0Blockers = 0;
            for (forge.game.card.Card c : head0.getCreaturesInPlay()) {
                if (!c.isTapped()) {
                    head0Blockers++;
                }
            }
            List<forge.game.card.Card> alloc0 = partition.get(head0.getId());
            alloc0.sort(java.util.Comparator.comparingInt(
                    forge.game.card.Card::getNetPower).reversed());
            int beyond = 0;
            for (int i = head0Blockers; i < alloc0.size(); i++) {
                beyond += Math.max(0, alloc0.get(i).getNetPower());
            }
            lethalPartition = partition;
            lethalPartitionTurn = turn;
            pilot.reportLethalAlpha(turn, head0.getId(), amplified(beyond), head0.getLife());
            return new ComboPilot.CombatOrder("LETHAL_ALPHA", killOrder);
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
            // PLAY-OBSERVATIONS finding 1: a LETHAL_ALPHA order computed
            // with a multi-head partition executes that exact partition —
            // each guaranteed head gets its worst-case-lethal allocation
            // instead of the whole board piling onto head[0]
            if ("LETHAL_ALPHA".equals(order.route()) && lethalPartition != null
                    && lethalPartitionTurn == getGame().getPhaseHandler().getTurn()) {
                java.util.Map<Integer, List<forge.game.card.Card>> plan = lethalPartition;
                lethalPartition = null;
                boolean anyPlanned = false;
                for (java.util.Map.Entry<Integer, List<forge.game.card.Card>> e
                        : plan.entrySet()) {
                    Player head = null;
                    for (Player p : targets) {
                        if (p.getId() == e.getKey()) {
                            head = p;
                        }
                    }
                    if (head == null) {
                        continue; // head died between order and declaration
                    }
                    for (forge.game.card.Card c : e.getValue()) {
                        if (forge.game.combat.CombatUtil.canAttack(c, head)) {
                            combat.addAttacker(c, head);
                            anyPlanned = true;
                        } else {
                            for (Player alt : targets) {
                                if (forge.game.combat.CombatUtil.canAttack(c, alt)) {
                                    combat.addAttacker(c, alt);
                                    anyPlanned = true;
                                    break;
                                }
                            }
                        }
                    }
                }
                if (anyPlanned) {
                    return true;
                }
                // partition unexecutable (mass removal mid-window): fall
                // through to the generic assignment below
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
            // While the Selvala loop is converting, DECLINE her optional
            // self-draw. A mass Genesis Wave flip fires her "draw if the
            // entering creature is the biggest" trigger many times; drawing
            // into a near-empty library decks us out mid-win. A human never
            // draws themselves to death while already assembling lethal — the
            // strict-max draw-sequencing synergy. Scoped to Draw APIs during
            // the loop only, so normal draws stay intact.
            // Decline our own OPTIONAL self-draw while the loop converts (a
            // human never draws themselves toward decking mid-win). NOTE: the
            // Genesis-Wave flip's real deck-out pressure is The Great Henge's
            // MANDATORY "creature enters -> draw", which never routes here — so
            // this only trims Selvala's own may-draw; the library_reserve is
            // what actually absorbs the forced Henge draws.
            if (activeSelvalaLoop != null && sa != null
                    && sa.getApi() == forge.game.ability.ApiType.Draw) {
                return false;
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
            // Steer Temur Sabertooth's / Kogla's HIDDEN "return a creature"
            // choice to the bounce_recur runner's recur creature (Eternal
            // Witness). The bounce is a choice, not a target, so the AI would
            // otherwise pick whatever it values — the runner sets
            // pendingRecurBounce for exactly one activation; consume it here.
            if (activeBounceRecur != null && pendingRecurBounce != null && fetchList != null) {
                for (forge.game.card.Card c : fetchList) {
                    if (c.getName().equals(pendingRecurBounce)) {
                        pendingRecurBounce = null; // one-shot
                        return c;
                    }
                }
            }
            // PR-kappa: Scroll Rack's exile choice reaches the AI ONE CARD
            // AT A TIME — ChangeZoneEffect.allowMultiSelect excludes AI
            // controllers, so the multi-select callback NEVER fires for us
            // (measured by the first diagnostic run; the dead branch was
            // deleted, the PR-72 lesson again). While OUR engine cycle
            // resolves its own rack: hand over excess basics one by one,
            // stopping while one remains for the land drop.
            if (activeEngine != null && sa != null && sa.getHostCard() != null
                    && sa.getHostCard().getName().equals(activeEngine.rackCard())
                    && destination == forge.game.zone.ZoneType.Exile
                    && origin != null && origin.contains(forge.game.zone.ZoneType.Hand)) {
                forge.game.card.Card pick = null;
                int basics = 0;
                for (forge.game.card.Card cd : fetchList) {
                    if (cd.isBasicLand()) {
                        basics++;
                        if (pick == null) {
                            pick = cd;
                        }
                    }
                }
                if (basics > 1 && pick != null) {
                    activeEngine.recordExiled();
                    return pick;
                }
                return null; // keep the last basic; never exile nonlands in v1
            }

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
                SeatView view = SeatViews.of(player, seatIndex, turn);
                var ranked = pilot.rankTutor(sa.getHostCard().getName(), names, view);
                // PR-nu power lever: with a POWER-loop producer on board, fetch
                // the biggest creature (>=5 power) to lift the loop's tap-yield
                // over the untap cost — unless the ranker has a strong pick
                // (>=0.98: a missing program piece or the outlet itself).
                if (pilot.wantsPowerCreature(view)
                        && (ranked.isEmpty() || ranked.get(0).score() < 0.98)) {
                    forge.game.card.Card big = powerCreaturePick(fetchList);
                    if (big != null) {
                        return big;
                    }
                }
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
                SeatView view = SeatViews.of(player, seatIndex, turn);
                var ranked = pilot.rankTutor(sa.getHostCard().getName(), names, view);
                // PR-nu power lever (same rule as the single-card path): feed a
                // POWER-loop producer a big creature when the ranker has no
                // strong assembly/outlet pick.
                if (pilot.wantsPowerCreature(view)
                        && (ranked.isEmpty() || ranked.get(0).score() < 0.98)) {
                    forge.game.card.Card big = powerCreaturePick(fetchList);
                    if (big != null) {
                        return List.of(big);
                    }
                }
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

        /** PR-nu: the highest-power creature in the fetch list worth fetching to
         *  power a POWER-scaling loop — at least 5 power (a real payoff, not a
         *  ramp dork) AND bigger than our current greatest creature (so it
         *  actually lifts the producer's tap-yield). null if none qualifies. */
        private forge.game.card.Card powerCreaturePick(forge.game.card.CardCollection fetchList) {
            int curMax = 0;
            for (forge.game.card.Card c
                    : player.getCardsIn(forge.game.zone.ZoneType.Battlefield)) {
                if (c.isCreature()) {
                    curMax = Math.max(curMax, c.getNetPower());
                }
            }
            forge.game.card.Card best = null;
            for (forge.game.card.Card c : fetchList) {
                if (c.isCreature() && c.getNetPower() >= 5 && c.getNetPower() > curMax
                        && (best == null || c.getNetPower() > best.getNetPower())) {
                    best = c;
                }
            }
            return best;
        }
    }
}
