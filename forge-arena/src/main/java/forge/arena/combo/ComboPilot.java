package forge.arena.combo;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Consumer;
import java.util.function.Function;

import forge.arena.engine.SeatView;
import forge.arena.report.ArenaEvent;

/**
 * The pure decision core behind the PR-15 ComboAwareController (plan §6):
 * given the tracker's view of the world, decide — and RECORD — whether to
 * enter a combo line, keep stepping one, ignore a ready combo, or abort.
 * Engine-free by construction (SeatView + injected validator only), so every
 * decision path is unit-testable without a game.
 *
 * <p>Telemetry contract (plan §5 v3.2 — "silence is never a valid record of
 * a decision"): a ready combo that is not attempted emits {@code
 * combo_ignored} with a reason, at most once per combo per turn (the per-turn
 * main-phase opportunity is the decision point); entering emits {@code
 * line_entered}; every step emits {@code line_step}; a line that cannot
 * continue emits {@code line_aborted}. Detection events (combo_state /
 * combo_ready) belong to ComboDetectionBridge — the pilot records decisions,
 * the bridge records observations, and they never double-report.
 *
 * <p>The patience knob (0 = fire asap .. 1 = hold) is a deterministic
 * primitive here: hold {@code round(patience * 3)} turns after first seeing
 * a combo ready, recording {@code patience_gate} each held turn. The PR-16
 * LethalityPlanner replaces holding-by-count with holding-for-protection.
 */
public final class ComboPilot {

    /** One pilot output: a scripted step, a mana shortcut, or a token flood. */
    public record Action(LineExecutor.Step step, ShortcutOrder shortcut, TokenFlood flood,
            DrillOrder drill, ProgramOrder program, PairingOrder pairing, EngineOrder engine) {
        public Action(LineExecutor.Step step, ShortcutOrder shortcut, TokenFlood flood) {
            this(step, shortcut, flood, null, null, null, null);
        }

        public Action(LineExecutor.Step step, ShortcutOrder shortcut) {
            this(step, shortcut, null, null, null, null, null);
        }

        public boolean isStep() {
            return step != null;
        }

        static Action play(LineExecutor.Step step) {
            return new Action(step, null, null, null, null, null, null);
        }

        static Action shortcut(ShortcutOrder order) {
            return new Action(null, order, null, null, null, null, null);
        }

        static Action flood(TokenFlood order) {
            return new Action(null, null, order, null, null, null, null);
        }

        static Action drill(DrillOrder order) {
            return new Action(null, null, null, order, null, null, null);
        }

        static Action program(ProgramOrder order) {
            return new Action(null, null, null, null, order, null, null);
        }

        static Action pairing(PairingOrder order) {
            return new Action(null, null, null, null, null, order, null);
        }

        static Action engine(EngineOrder order) {
            return new Action(null, null, null, null, null, null, order);
        }
    }

    /** PR-eta: dispatch a compiled pairing program (wipe + shield, respond-on-stack). */
    public record PairingOrder(String pairingId, String programPath) {
    }

    /** PR-kappa: dispatch one cycle of a compiled engine program. */
    public record EngineOrder(String engineId, String programPath) {
    }

    /**
     * PR-38: arm the PR-37 loop-to-lethal drill on a battlefield sink. The
     * controller validates one activation on a game copy before committing
     * and discovers the ability structurally (no cost hint travels here —
     * the pilot names the OUTLET, the engine layer knows the mechanics).
     */
    public record DrillOrder(String outletCard, String prereqCard, String prereqCost) {
        public DrillOrder(String outletCard) {
            this(outletCard, null, null);
        }
    }

    /** Phase 11: run the combo's COMPILED PROGRAM (engine-side runner). */
    public record ProgramOrder(String comboId, String programPath) {
    }

    /**
     * PR-27b: the compressed order for a proven token loop — put {@code
     * count} real copies of {@code copier} onto the battlefield with
     * triggers ACTIVE; the rules engine prices every ping and amplifier.
     */
    public record TokenFlood(String comboId, String copier, int count) {
    }

    /**
     * PR-16 loop shortcut (plan §5/§6): the proven loop compresses to a
     * bounded pool injection; the planner already chose the route.
     */
    public record ShortcutOrder(String comboId, String engineCard, String color, int amount,
            String route) {
    }

    /**
     * Bounded product of a proven-infinite loop. PR-29 sizing: each floating
     * mana is a pool OBJECT the engine's payment prober walks — at 10^4,
     * stock's X evaluators (determineLeftoverMana: 99 probes) burned the
     * game clock (the analysis-100 "crash" signature). 1,000 covers
     * DEPLOY_X (500) plus every deploy with headroom, 10x cheaper.
     */
    public static final int SHORTCUT_POOL = 1_000;

    /**
     * Scripted X for conversion casts (PR-25): lethal pump for any table
     * (+500/+500), ≥ 10 for Finale's haste rider, and cheap against the
     * {@link #SHORTCUT_POOL}. The AI's own X choice is pool-blind — game 78
     * cast Finale at small X with 10^4 floating and fetched a Dreadnought
     * that died to its own trigger.
     */
    public static final int DEPLOY_X = 500;

    /**
     * PR-25: the pilot's combat instruction while conversion is pending —
     * the selected route plus the opponent kill order (seat indices,
     * lowest life first). The controller translates it into declared
     * attackers with engine data; an empty directive means stock combat.
     */
    public record CombatOrder(String route, List<Integer> killOrder) {
    }

    private final ComboTracker tracker;
    private final ExecutorBindings bindings;
    private final RoutePlan routePlan;
    private final TutorRanker tutorRanker;
    private final double patience;
    private final int seat;
    private final Consumer<ArenaEvent> events;

    private String activeComboId;
    private LineExecutor activeExecutor;
    private ExecutorBindings.Binding activeBinding;
    private LineExecutor.LineState lineState;
    private final Map<String, Integer> firstReadyTurn = new HashMap<>();
    private final Map<String, Integer> lastIgnoredTurn = new HashMap<>();
    private final Set<String> attemptedThisTurn = new HashSet<>();
    private final Set<String> firedShortcuts = new HashSet<>();
    // PR-35 (stall-autopsy find): the fire turn per combo — the re-fire
    // suppression is WINDOW-bounded, not permanent; a t21 reservation was
    // still suppressing the engine at t33 while the seat ground out
    // unpumped commander attacks
    private final Map<String, Integer> firedTurns = new HashMap<>();
    private int seenTurn = -1;
    private String lastAssemblySignature;
    private int assemblyRepeats;
    // PR-25 conversion state: the fired binding survives line exit (its
    // payoffs stay deploy candidates), the planner re-runs once per turn
    // while the pool is banked, and same-turn deploy retries are deduped
    private ExecutorBindings.Binding firedBinding;
    private String currentRoute;
    private int lastPlanTurn = -1;
    private final Set<String> attemptedDeploys = new HashSet<>();
    /** Phase 11: combo id -> compiled program path (strings only — W8 pure). */
    private Map<String, String> programPaths = Map.of();
    /**
     * PR-gamma: every card that is a PIECE of some compiled program. A
     * program is the ONLY execution path for its pieces (no dual paths —
     * the post-abort phantom drill on the Ballista was the legacy
     * conversion machinery arming on a program's outlet). Names come from
     * the programs themselves, never from code.
     */
    private Set<String> programPieces = Set.of();
    /** PR-aa: each program's declared conversion OUTLET (Aetherflux class)
     *  — from the program JSONs, never from code. */
    private Set<String> programOutlets = Set.of();

    /**
     * PR-sweep: per program, the assembly its preconditions require — pieces
     * that must be ON THE BATTLEFIELD and equip->host attachments — so the
     * pilot disambiguates combos that SHARE a piece. Four Selvala combos share
     * Umbral Mantle; without this the pilot burns turn after turn dispatching a
     * sibling whose OTHER piece is in hand (Fanatic) or whose Umbral sits on the
     * wrong host, each only to abort piece_lost/piece_misattached, and never
     * reaches the one combo that IS assembled. Skipped for programs with a
     * non-empty setup (their setup places pieces). From the JSONs, not code.
     */
    private Map<String, Set<String>> programOnBattlefield = Map.of();
    private Map<String, List<String[]>> programAttach = Map.of();
    private Set<String> programHasSetup = Set.of();

    public void setProgramPaths(Map<String, String> paths) {
        this.programPaths = paths == null ? Map.of() : paths;
        Set<String> pieces = new HashSet<>();
        Set<String> outlets = new HashSet<>();
        Map<String, Set<String>> onBattlefield = new HashMap<>();
        Map<String, List<String[]>> attach = new HashMap<>();
        Set<String> hasSetup = new HashSet<>();
        for (String path : this.programPaths.values()) {
            try {
                com.fasterxml.jackson.databind.JsonNode program =
                        new com.fasterxml.jackson.databind.ObjectMapper()
                                .readTree(new java.io.File(path));
                for (com.fasterxml.jackson.databind.JsonNode piece : program.path("pieces")) {
                    String card = piece.path("card").asText();
                    if (!card.isEmpty()) {
                        pieces.add(card);
                    }
                }
                // assembly preconditions: which pieces must be in play and how
                // they must be attached — the pilot's dispatch gate reads these
                // to skip a shared-piece sibling that is not actually assembled
                String comboId = program.path("combo_id").asText("");
                if (!comboId.isEmpty()) {
                    Set<String> bf = new HashSet<>();
                    List<String[]> att = new ArrayList<>();
                    for (com.fasterxml.jackson.databind.JsonNode pc
                            : program.path("preconditions")) {
                        String check = pc.path("check").asText("");
                        if ("on_battlefield".equals(check)) {
                            bf.add(pc.path("card").asText());
                        } else if ("attached".equals(check)) {
                            att.add(new String[] {pc.path("card").asText(),
                                    pc.path("host").asText()});
                        }
                    }
                    if (!bf.isEmpty()) {
                        onBattlefield.put(comboId, bf);
                    }
                    if (!att.isEmpty()) {
                        attach.put(comboId, att);
                    }
                    if (program.path("setup").isArray() && program.path("setup").size() > 0) {
                        hasSetup.add(comboId);
                    }
                }
                // the outlet is a structured OBJECT in the cast_bounce
                // programs ({card, target_cumulative_lifegain, why}) and
                // may be plain text elsewhere — read both shapes. asText()
                // on an object returns "" — the aa30 batch measured the
                // lever dead-wired for exactly that reason (0 boosts/30).
                for (com.fasterxml.jackson.databind.JsonNode node
                        : java.util.List.of(program.path("outlet"),
                                program.path("sink").path("outlet"))) {
                    String outlet = node.isObject()
                            ? node.path("card").asText("") : node.asText("");
                    if (!outlet.isEmpty()) {
                        outlets.add(outlet);
                    }
                }
            } catch (Exception unreadable) {
                // the runner aborts loudly on use; nothing to do here
            }
        }
        this.programPieces = pieces;
        this.programOutlets = outlets;
        this.programOnBattlefield = Map.copyOf(onBattlefield);
        this.programAttach = Map.copyOf(attach);
        this.programHasSetup = Set.copyOf(hasSetup);
    }

    /**
     * A program combo is dispatchable only when its declared pieces are truly
     * ASSEMBLED: no piece stuck in the command zone (an uncast commander), every
     * on_battlefield piece actually on the battlefield, and every required equip
     * on its declared host. Programs with a setup step place their own pieces, so
     * they keep the looser command-zone-only gate. This is what lets four combos
     * that share Umbral Mantle coexist: only the one whose Umbral is on the right
     * host — and whose other piece is in play, not still in hand — dispatches.
     */
    private boolean programAssembled(String comboId, ComboTracker.ComboStatus status,
            SeatView view) {
        // baseline (smoke-batch fix #73): never dispatch with a piece still in
        // the command zone — no runner casts the commander in setup
        if (status.where().values().stream().anyMatch("COMMAND"::equals)) {
            return false;
        }
        if (programHasSetup.contains(comboId)) {
            return true; // setup places the remaining pieces
        }
        for (String piece : programOnBattlefield.getOrDefault(comboId, Set.of())) {
            if (!"BATTLEFIELD".equals(status.where().get(piece))) {
                return false;
            }
        }
        Map<String, String> attachments = view.ownAttachments();
        for (String[] pair : programAttach.getOrDefault(comboId, List.of())) {
            if (!pair[1].equals(attachments.get(pair[0]))) {
                return false; // equip absent or on the wrong host
            }
        }
        return true;
    }

    /**
     * PR-eta: compiled pairing programs (wipe + shield). What the pilot
     * needs for the ENTRY decision only — the runner re-verifies everything
     * against the live game. Names come from the programs, never from code.
     */
    public record PairingSpec(String id, String path, String wipe, String protection,
            String policyType, int minPower, int manaEstimate) {
    }

    private java.util.List<PairingSpec> pairingSpecs = java.util.List.of();
    private final Set<String> firedPairings = new HashSet<>();

    /**
     * PR-eta panel finding: a PREFLIGHT abort spends NOTHING — burning the
     * once-per-game pair on it contradicted fresh evaluation. The runner
     * calls this to hand the pair back; attemptedThisTurn still prevents a
     * same-turn spin.
     */
    public void pairingPreflightFailed(String pairingId) {
        firedPairings.remove(pairingId);
    }

    /**
     * PR-lambda (panel): a program whose SETUP could not proceed spent
     * NOTHING — it must not burn the ~8-turn refire lockout nor leave the
     * pilot in a phantom conversion state (currentRoute/bankedPhase set for
     * a loop that never ran). The runner defers; the pilot hands the combo
     * back; attemptedThisTurn still blocks a same-turn spin.
     */
    public void programDeferred(String comboId) {
        firedShortcuts.remove(comboId);
        firedTurns.remove(comboId);
        currentRoute = null;
        bankedPhase = null;
    }

    public void setPairingPrograms(Map<String, String> paths) {
        java.util.List<PairingSpec> specs = new java.util.ArrayList<>();
        for (Map.Entry<String, String> e : (paths == null ? Map.<String, String>of() : paths)
                .entrySet()) {
            try {
                com.fasterxml.jackson.databind.JsonNode program =
                        new com.fasterxml.jackson.databind.ObjectMapper()
                                .readTree(new java.io.File(e.getValue()));
                String wipe = program.path("wipe").path("card").asText(null);
                String protection = program.path("protection").path("card").asText(null);
                if (wipe == null || protection == null) {
                    continue;
                }
                boolean free = program.path("protection").hasNonNull("free_condition");
                int estimate = symbolCount(program.path("wipe").path("cost").asText(""))
                        + (free ? 0
                                : symbolCount(program.path("protection").path("cost").asText("")));
                specs.add(new PairingSpec(e.getKey(), e.getValue(), wipe, protection,
                        program.path("fire_policy").path("type").asText("threat_gated"),
                        program.path("fire_policy")
                                .path("min_combined_opponent_creature_power").asInt(6),
                        estimate));
            } catch (Exception unreadable) {
                // the runner aborts loudly on use; nothing to do here
            }
        }
        // PR-49's lesson, pairing form: cheapest-first meant the strongest
        // play (land destruction) never fired in 300 games. assembly_gated
        // MLD outranks threat_gated creature wipes (Ben: it puts you so far
        // ahead most opponents can't catch back up); stable by id within.
        specs.sort(java.util.Comparator
                .comparing((PairingSpec sp) -> !"assembly_gated".equals(sp.policyType()))
                .thenComparing(PairingSpec::id));
        this.pairingSpecs = specs;
    }

    /**
     * PR-protect: reactive INSTANT covers (Heroic Intervention class), cheapest
     * first, from protection-priorities.json. The controller casts one to save a
     * threatened combo piece — the offensive counterpart of keeping the pieces
     * alive long enough to loop. From the deck's own card text, never from code.
     */
    public record ProtectionSpec(String card, forge.arena.prep.ProtectionFinder.Scope scope,
            int manaValue) {
    }

    private java.util.List<ProtectionSpec> protectionSpecs = java.util.List.of();

    public void setProtection(java.util.List<ProtectionSpec> specs) {
        this.protectionSpecs = specs == null ? java.util.List.of()
                : specs.stream().sorted(java.util.Comparator.comparingInt(ProtectionSpec::manaValue))
                        .toList();
    }

    /** Every protection card, so the controller reserves them from stock casts. */
    public Set<String> protectionCards() {
        Set<String> cards = new HashSet<>();
        for (ProtectionSpec spec : protectionSpecs) {
            cards.add(spec.card());
        }
        return cards;
    }

    /** Is this card a piece of some compiled PROGRAM combo — a thing worth
     *  saving when an opponent targets it? */
    public boolean isProgramPiece(String cardName) {
        return programPieces.contains(cardName);
    }

    /** The cheapest reactive cover we hold that saves a piece of the given kind,
     *  or null when we hold none. */
    public String reactiveCover(SeatView view, boolean pieceIsCreature) {
        Set<String> hand = view.cardsIn(SeatView.Zone.HAND);
        for (ProtectionSpec spec : protectionSpecs) { // cheapest first
            if (spec.scope().covers(pieceIsCreature) && hand.contains(spec.card())) {
                return spec.card();
            }
        }
        return null;
    }

    /**
     * PR-kappa: compiled engine programs — background card-advantage cycles.
     * The pilot knows only what the ENTRY decisions need: which cards to
     * cast early and when a cycle is worth dispatching; the runner
     * re-verifies everything live.
     */
    public record EngineSpec(String id, String path, java.util.List<String> pieces,
            Map<String, Integer> castCosts) {
    }

    private java.util.List<EngineSpec> engineSpecs = java.util.List.of();

    public void setEnginePrograms(Map<String, String> paths) {
        java.util.List<EngineSpec> specs = new java.util.ArrayList<>();
        for (Map.Entry<String, String> e : (paths == null ? Map.<String, String>of() : paths)
                .entrySet()) {
            try {
                com.fasterxml.jackson.databind.JsonNode program =
                        new com.fasterxml.jackson.databind.ObjectMapper()
                                .readTree(new java.io.File(e.getValue()));
                java.util.List<String> pieces = new java.util.ArrayList<>();
                Map<String, Integer> costs = new java.util.LinkedHashMap<>();
                for (com.fasterxml.jackson.databind.JsonNode piece : program.path("pieces")) {
                    String card = piece.path("card").asText();
                    if (!card.isEmpty()) {
                        pieces.add(card);
                        costs.put(card, symbolCount(piece.path("cost").asText("")));
                    }
                }
                // a program the runner cannot cycle (no activate card) must
                // not dispatch daily re-aborts (panel event-hygiene finding)
                if (!pieces.isEmpty()
                        && program.path("cycle").path("action").hasNonNull("activate")) {
                    specs.add(new EngineSpec(e.getKey(), e.getValue(), pieces, costs));
                }
            } catch (Exception unreadable) {
                // the runner aborts loudly on use
            }
        }
        specs.sort(java.util.Comparator.comparing(EngineSpec::id)); // determinism
        this.engineSpecs = specs;
    }

    /**
     * PR-kappa setup: cast engine pieces EARLY — the measured stock failure
     * was Land Tax at turn 15 (condition dead) and Scroll Rack never
     * (AI:RemoveDeck:All). Cheap casts that fill otherwise-idle early
     * windows; runs BELOW combos and pairings, so it never delays a kill.
     */
    private Optional<Action> engineSetup(SeatView view) {
        Set<String> hand = view.cardsIn(SeatView.Zone.HAND);
        Set<String> battlefield = view.cardsIn(SeatView.Zone.BATTLEFIELD);
        for (EngineSpec spec : engineSpecs) {
            for (String piece : spec.pieces()) {
                if (!hand.contains(piece) || battlefield.contains(piece)
                        || attemptedDeploys.contains(piece)) {
                    continue;
                }
                if (view.manaPool() + view.untappedManaSources()
                        < spec.castCosts().getOrDefault(piece, 0)) {
                    continue;
                }
                attemptedDeploys.add(piece);
                return Optional.of(Action.play(LineExecutor.Step.cast(piece)));
            }
        }
        return Optional.empty();
    }

    /** PR-kappa cycle: both pieces out — dispatch one gated cycle per turn. */
    private Optional<Action> engineCycle(SeatView view) {
        Set<String> battlefield = view.cardsIn(SeatView.Zone.BATTLEFIELD);
        for (EngineSpec spec : engineSpecs) {
            if (attemptedThisTurn.contains(spec.id())
                    || !battlefield.containsAll(spec.pieces())) {
                continue;
            }
            attemptedThisTurn.add(spec.id());
            return Optional.of(Action.engine(new EngineOrder(spec.id(), spec.path())));
        }
        return Optional.empty();
    }

    /** Mana-value estimate of a canonical brace cost string ("{3}{W}{W}" -> 5). */
    private static int symbolCount(String cost) {
        int total = 0;
        for (String sym : cost.replace("{", " ").replace("}", " ").trim().split("\\s+")) {
            if (sym.isEmpty()) {
                continue;
            }
            total += sym.chars().allMatch(Character::isDigit) ? Integer.parseInt(sym) : 1;
        }
        return total;
    }

    /**
     * PR-eta entry decision: a compiled pairing fires at the first legal
     * window once both cards are in hand, the mana estimate is coverable,
     * and its fire policy holds — threat_gated needs opponents' combined
     * creature power at the program's floor (Ben: "as soon as mana is
     * available and our opponents have significant threats");
     * assembly_gated (mass land destruction) needs nothing beyond assembly
     * ("as soon as its assembled and we can afford it"). Marked fired at
     * dispatch: once per pair per game, exactly like the legacy path.
     */
    private Optional<Action> compiledPairings(SeatView view) {
        Set<String> hand = view.cardsIn(SeatView.Zone.HAND);
        for (PairingSpec spec : pairingSpecs) {
            if (firedPairings.contains(spec.id()) || attemptedThisTurn.contains(spec.id())
                    || !hand.contains(spec.wipe()) || !hand.contains(spec.protection())) {
                continue;
            }
            if (view.manaPool() + view.untappedManaSources() < spec.manaEstimate()) {
                continue;
            }
            if ("threat_gated".equals(spec.policyType())) {
                int threat = view.opponents().stream()
                        .mapToInt(SeatView.OpponentView::creaturePower).sum();
                if (threat < spec.minPower()) {
                    continue;
                }
            }
            attemptedThisTurn.add(spec.id());
            firedPairings.add(spec.id());
            events.accept(ArenaEvent.of("pairing_entered", view.turn(), seat)
                    .with("pairing", spec.id())
                    .with("wipe", spec.wipe())
                    .with("protection", spec.protection())
                    .with("policy", spec.policyType()));
            return Optional.of(Action.pairing(new PairingOrder(spec.id(), spec.path())));
        }
        return Optional.empty();
    }
    /**
     * PR-C: the deck's own damage amplifiers, from its route-coverage
     * artifact. Names come from prep, never from code.
     */
    public java.util.List<String> amplifierNames() {
        return routePlan.payoffCards(forge.arena.prep.PayoffRules.DAMAGE_AMPLIFIER);
    }

    /**
     * Engine-layer observation sink (PR-58). The pilot owns the seat's event
     * stream, so an observation made down in the engine — where the game
     * objects live — still lands in the one ordered record of what this seat
     * saw and did. Observations only: this never feeds a decision.
     */
    public void observe(ArenaEvent event) {
        events.accept(event);
    }

    /** State fingerprint the live route was computed from (PR-56). */
    private String lastPlanState;
    /** Phase the banked pool was created in (PR-A) — mana has a lifetime. */
    private String bankedPhase;

    /**
     * The decision-relevant state behind a route verdict (PR-56). Two views
     * with the same fingerprint cannot produce different verdicts, so the
     * plan only needs recomputing when this changes — which makes replanning
     * driven by the board rather than by the clock.
     */
    private static String planState(SeatView view) {
        return view.attackReadyPower() + "/" + view.ownBoardPower() + "/" + view.handSize()
                + "/" + view.manaPool() + "/" + view.cardsIn(SeatView.Zone.BATTLEFIELD).size()
                + "/" + view.opponents().stream().mapToInt(SeatView.OpponentView::life).sum();
    }

    public ComboPilot(ComboTracker tracker, ExecutorBindings bindings, double patience,
            int seat, Consumer<ArenaEvent> events) {
        this(tracker, bindings, RoutePlan.empty(), null, patience, seat, events);
    }

    public ComboPilot(ComboTracker tracker, ExecutorBindings bindings, RoutePlan routePlan,
            double patience, int seat, Consumer<ArenaEvent> events) {
        this(tracker, bindings, routePlan, null, patience, seat, events);
    }

    public ComboPilot(ComboTracker tracker, ExecutorBindings bindings, RoutePlan routePlan,
            TutorRanker tutorRanker, double patience, int seat, Consumer<ArenaEvent> events) {
        this.tracker = tracker;
        this.bindings = bindings;
        this.routePlan = routePlan;
        this.tutorRanker = tutorRanker != null ? tutorRanker
                : new TutorRanker(Map.of(), tracker);
        this.patience = patience;
        this.seat = seat;
        this.events = events;
    }

    /**
     * Rank a search effect's options (PR-17): empty list = the ranker has no
     * opinion, stock heuristics decide (and no event — the situation carried
     * no combo information). A real opinion is RECORDED: tutor_decision with
     * the full ranking and per-candidate why (plan §5 / §7 tutor audit).
     */
    public List<TutorRanker.Ranked> rankTutor(String source, List<String> options, SeatView view) {
        List<TutorRanker.Ranked> ranked = tutorRanker.rank(options, view, tutorUrgency(view));
        // PR-aa (omega100: 104 cast_bounce entries deferred quietly on the
        // outlet gate — engines assembled, Aetherflux a 1-of nowhere in
        // reach): when any program PIECE is already on our battlefield and
        // a declared program OUTLET is in neither hand nor battlefield,
        // fetching that outlet outranks everything — it is the difference
        // between a durdle and a kill. Names from program JSONs only.
        if (!programOutlets.isEmpty()
                && view.cardsIn(SeatView.Zone.BATTLEFIELD).stream()
                        .anyMatch(programPieces::contains)) {
            Set<String> reach = new java.util.HashSet<>(view.cardsIn(SeatView.Zone.HAND));
            reach.addAll(view.cardsIn(SeatView.Zone.BATTLEFIELD));
            for (String option : options) {
                if (programOutlets.contains(option) && !reach.contains(option)) {
                    List<TutorRanker.Ranked> boosted = new java.util.ArrayList<>();
                    boosted.add(new TutorRanker.Ranked(option, 0.99,
                            "program outlet missing while pieces deployed (PR-aa)"));
                    for (TutorRanker.Ranked r : ranked) {
                        if (!r.card().equals(option)) {
                            boosted.add(r);
                        }
                    }
                    ranked = boosted;
                    break;
                }
            }
        }
        if (ranked.isEmpty() || ranked.get(0).score() <= 0) {
            return List.of();
        }
        List<Map<String, Object>> rankedRows = new java.util.ArrayList<>();
        for (TutorRanker.Ranked r : ranked.subList(0, Math.min(8, ranked.size()))) {
            Map<String, Object> row = new java.util.LinkedHashMap<>();
            row.put("c", r.card());
            row.put("score", Math.round(r.score() * 1000.0) / 1000.0);
            row.put("why", r.why());
            rankedRows.add(row);
        }
        events.accept(ArenaEvent.of("tutor_decision", view.turn(), seat)
                .with("source", source)
                .with("chosen", ranked.get(0).card())
                .with("ranked", rankedRows));
        return ranked;
    }

    /** True while a line is being stepped (the controller is in line mode). */
    public boolean lineActive() {
        return activeExecutor != null;
    }

    /**
     * PR-33: the active line's operating cards, or empty when no line runs.
     * The controller answers YES to optional confirms hosted by these cards
     * while the line is live (the urza find: Isochron Scepter's Play effect
     * is Optional$ True and stock declines it).
     */
    public Set<String> activeLineCards() {
        return activeExecutor == null ? Set.of()
                : new java.util.LinkedHashSet<>(activeExecutor.lineCards());
    }

    /**
     * PR-24 payoff visibility: how urgently this seat needs win conversion.
     * CONVERSION once a shortcut fired or a line is deploying (the floated
     * pool needs a payoff, not a second engine); IMMINENT while a bound,
     * fully-specified combo sits at distance ≤ 1; NONE otherwise — which
     * reproduces the PR-17 ranking exactly (inertness).
     */
    private TutorRanker.Urgency tutorUrgency(SeatView view) {
        if (!firedShortcuts.isEmpty() || (lineActive() && lineState.stage() == 2)) {
            return TutorRanker.Urgency.CONVERSION;
        }
        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (status.fullySpecified() && status.distance() <= 1 && executorExists(status.id())) {
                return TutorRanker.Urgency.IMMINENT;
            }
        }
        return TutorRanker.Urgency.NONE;
    }

    private boolean executorExists(String comboId) {
        // PR-kappa (Ben's weights-freshness check found this): a combo whose
        // binding was DELETED when its compiled program landed (PR-beta,
        // one-path rule) must still count as executable — this gate feeds
        // the mulligan keep, mulligan protection, hasBoundCombo, and the
        // TUTOR PUSH, all of which had been blind to Giada's programmed
        // combos since the migration. Giada was assembling on natural draws
        // alone.
        return programPaths.containsKey(comboId)
                || bindings.forCombo(comboId).flatMap(ExecutorBindings::executorFor).isPresent();
    }

    /**
     * PR-24 mulligan policy (plan §6 "distance-aware keep"): keep a hand that
     * holds a piece of a BOUND combo behind a playable land count, or a
     * payoff with the lands to cast toward it; spend the free 4-player
     * mulligan digging when the hand carries neither; defer to the stock
     * evaluator everywhere else (land screw/flood judgment stays stock's).
     * Every checkpoint is RECORDED as mulligan_decision (§5 taxonomy) — with
     * one exception: a pilot with no combo assets at all returns stock's
     * verdict silently, because the situation carries no combo information
     * (the rankTutor no-opinion precedent, §8 inertness).
     */
    public boolean mulliganKeep(SeatView view, int mulligansTaken, boolean firstMullFree,
            boolean stockKeeps) {
        ComboTracker.Snapshot snap = tracker.recompute(view);
        Set<String> boundPieces = boundPieces(snap);
        Set<String> deckPayoffs = deckPayoffs(snap);
        if (boundPieces.isEmpty() && deckPayoffs.isEmpty()) {
            return stockKeeps;
        }
        Set<String> hand = view.cardsIn(SeatView.Zone.HAND);
        List<String> pieces = hand.stream().filter(boundPieces::contains).sorted().toList();
        List<String> payoffs = hand.stream().filter(deckPayoffs::contains).sorted().toList();
        int lands = view.handLands();
        int nonlands = view.handSize() - lands;

        boolean keep;
        String reason;
        if (!pieces.isEmpty() && lands >= 2 && nonlands >= 2) {
            keep = true;
            reason = "combo_piece_hand";
        } else if (!payoffs.isEmpty() && lands >= 3 && nonlands >= 2) {
            keep = true;
            reason = "payoff_with_lands";
        } else if (!pieces.isEmpty() && lands >= 2 && outletReachable(view)) {
            // PR-51 (playbook §5): weight OUTLET presence as a keep reason.
            // A hand that assembles the engine and can never cash it is this
            // project's headline failure reproduced at the mulligan — the
            // green deck fired 58 times and converted twice, every route
            // rejection reading "no payoff available".
            keep = true;
            reason = "piece_with_outlet";
        } else if (pieces.isEmpty() && payoffs.isEmpty() && mulligansTaken == 0 && firstMullFree) {
            keep = false;
            reason = "dig_for_pieces";
        } else {
            keep = stockKeeps;
            reason = stockKeeps ? "stock_keep" : "stock_mulligan";
        }

        int bestDistance = snap.statuses().stream()
                .filter(s -> s.fullySpecified() && executorExists(s.id()))
                .mapToInt(ComboTracker.ComboStatus::distance)
                .min().orElse(-1);
        Map<String, Object> handDistance = new java.util.LinkedHashMap<>();
        handDistance.put("best_bound_distance", bestDistance);
        handDistance.put("pieces", pieces);
        handDistance.put("payoffs", payoffs);
        handDistance.put("lands", lands);
        handDistance.put("hand_size", view.handSize());
        handDistance.put("mulligans_taken", mulligansTaken);
        events.accept(ArenaEvent.of("mulligan_decision", view.turn(), seat)
                .with("decision", keep ? "keep" : "mulligan")
                .with("reason", reason)
                .with("hand_distance", handDistance));
        return keep;
    }

    /**
     * Cards the London-mulligan tuck must never bottom (PR-24): a hand kept
     * FOR a piece or payoff must not have its reason tucked away.
     */
    public Set<String> protectedMulliganCards(SeatView view) {
        ComboTracker.Snapshot snap = tracker.recompute(view);
        Set<String> out = new java.util.LinkedHashSet<>(boundPieces(snap));
        out.addAll(deckPayoffs(snap));
        out.addAll(pairedPlayCards()); // PR-31: pairs survive discard/tuck too
        return out;
    }

    /** Piece names of every bound, fully-specified combo (static per deck). */
    private Set<String> boundPieces(ComboTracker.Snapshot snap) {
        // program pieces ride along even when no binding remains
        Set<String> pieces = new java.util.LinkedHashSet<>();
        for (ComboTracker.ComboStatus status : snap.statuses()) {
            if (status.fullySpecified() && executorExists(status.id())) {
                pieces.addAll(status.where().keySet());
            }
        }
        return pieces;
    }

    /** The deck's payoff cards: route-coverage deck layer ∪ binding payoffs (DEPLOY breadth). */
    private Set<String> deckPayoffs(ComboTracker.Snapshot snap) {
        Set<String> payoffs = new java.util.LinkedHashSet<>();
        routePlan.payoffs().values().forEach(payoffs::addAll);
        for (ComboTracker.ComboStatus status : snap.statuses()) {
            bindings.forCombo(status.id()).ifPresent(b -> payoffs.addAll(b.payoffs()));
        }
        return payoffs;
    }

    /**
     * The pilot's one decision entry, called each time the seat has priority.
     * Returns the next scripted step to play, or empty = no combo action
     * (stock AI decides). {@code validator} runs the executor against a fresh
     * game copy — injected so this class never touches the engine.
     */
    public Optional<Action> nextAction(SeatView view, boolean entryWindowOpen,
            Function<LineExecutor, SimResult> validator) {
        if (view.turn() != seenTurn) {
            seenTurn = view.turn();
            attemptedThisTurn.clear();
            attemptedDeploys.clear();
        }

        if (lineActive()) {
            // ASSEMBLY and DEPLOY are sorcery-speed stages (casts, equips):
            // outside the window the engine refuses them silently and the
            // line would spin — wait for our next main phase instead
            if ((lineState.stage() == 0 || lineState.stage() == 2) && !entryWindowOpen) {
                return Optional.empty();
            }
            if (lineState.stage() == 0) {
                return assemblyAction(view, validator);
            }
            if (lineState.stage() == 2) {
                return deployAction(view);
            }
            LineExecutor.Step step = activeExecutor.next(lineState, view);
            if (step.isDone()) {
                exitLine();
                return Optional.empty();
            }
            events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                    .with("stage", activeExecutor.stages().get(lineState.stage()))
                    .with("iteration", lineState.iteration()));
            lineState = lineState.advance();
            return Optional.of(Action.play(step));
        }

        if (!entryWindowOpen) {
            return Optional.empty(); // not a decision point — no phantom events
        }

        // PR-25 re-plan: while conversion is pending (pool banked, no line
        // running), re-evaluate routes ONCE per turn — a payoff drawn or
        // tutored after the fire flips BANK_AND_HOLD into a real route
        // instead of a stall — and keep deploying payoffs as they arrive
        if (!firedShortcuts.isEmpty() && !lineActive()) {
            // PR-56 (research: receding-horizon replanning) — the verdict used
            // to be computed once, at the turn's FIRST priority window, and
            // then reused for the whole turn including declareAttackers. But
            // the turn is exactly when the board changes: cast the pump, draw
            // the payoff, untap the team. A seat that opened the turn with
            // nothing and assembled a lethal board by the combat step still
            // read BANK_AND_HOLD from before it did any of that, and declined
            // to attack. Replan whenever the state a verdict depends on has
            // actually moved — board-driven, not clock-driven, so it stays
            // bounded (no change, no recompute, no event).
            String state = planState(view);
            if (view.turn() != lastPlanTurn || !state.equals(lastPlanState)) {
                lastPlanTurn = view.turn();
                lastPlanState = state;
                currentRoute = LethalityPlanner.choose(routePlan, view, events).route();
            }
            // PR-38 (Phase 6 A2): the conversion state machine runs BEFORE
            // the route gate. A banked pool with a reachable outlet is a win
            // regardless of which combat route the planner picked, and
            // BANK_AND_HOLD — the most common post-fire route in the
            // long-200 batch (30 of 94 selections) — used to mean "do
            // nothing at all", which is precisely the 25% conversion rate.
            Optional<Action> converted = convert(view);
            if (converted.isPresent()) {
                return converted;
            }
            if (!"BANK_AND_HOLD".equals(currentRoute)) {
                Optional<Action> deploy = conversionDeploy(view);
                if (deploy.isPresent()) {
                    return deploy;
                }
            }
        }

        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            // PR-psi: a TEMPLATE combo (Spellbook template_requirements —
            // never `ready` in detection-only mode) becomes dispatchable
            // once a COMPILED PROGRAM carries its template resolution: the
            // compiler resolved the unnamed piece against the deck
            // (resolve_from), and the runner re-verifies it against the
            // LIVE game at entry, deferring quietly when it is absent.
            // Found the hard way: 513-5034--46 — the deck's most popular
            // Spellbook line — was structurally undispatchable, program or
            // not, while its prose-prerequisite sibling 513-3682 fired.
            // Non-program combos keep the old semantics exactly.
            boolean hasProgram = programPaths.containsKey(status.id());
            // ASSEMBLY GATE (smoke-batch fix #73, extended for shared pieces): a
            // program runner needs its pieces IN PLAY and correctly attached, but
            // detection counts command/hand as "reachable". programAssembled()
            // reads the program's own on_battlefield/attached preconditions so a
            // combo dispatches only when it is TRULY assembled — not while its
            // commander is uncast (COMMAND), a piece sits in hand, or its equip is
            // on the wrong host. Without this the pilot spins on Umbral-sharing
            // siblings (Fanatic/Selvala variants) and never reaches the ready one.
            boolean dispatchable = (status.ready()
                    || (status.distance() == 0 && hasProgram))
                    && (!hasProgram || programAssembled(status.id(), status, view));
            if (!dispatchable || attemptedThisTurn.contains(status.id())) {
                continue;
            }
            if (firedShortcuts.contains(status.id())) {
                // pool already ordered — conversion is pending and the stall
                // watchdog owns the window; re-firing inside it is noise.
                // PR-35: but ONLY inside it — past 2 own turns with no win,
                // conversion has failed and the engine is still on the
                // battlefield; re-enter, re-prove, re-fire (fresh pool on
                // the attack/deploy turn). The old permanent suppression
                // left proven engines idle for the rest of the game.
                Integer firedAt = firedTurns.get(status.id());
                int refireWindow = 2 * (view.opponents().size() + 1);
                if (firedAt == null || view.turn() - firedAt < refireWindow) {
                    ignore(status.id(), view.turn(), "mana_reserved",
                            Map.of("cause", "refire_lockout",
                                    "fired_at", firedAt == null ? -1 : firedAt));
                    continue;
                }
            }
            // Phase 11: a combo with a compiled program runs ONLY through it
            // — never the archetype path (one execution route per combo).
            if (programPaths.containsKey(status.id())) {
                String comboId = status.id();
                attemptedThisTurn.add(comboId);
                firedShortcuts.add(comboId);
                firedTurns.put(comboId, view.turn());
                bankedPhase = view.phase();
                currentRoute = "DIRECT_DAMAGE_LOOP";
                lastPlanTurn = view.turn();
                lastPlanState = planState(view);
                events.accept(ArenaEvent.of("line_entered", view.turn(), seat)
                        .with("combo", comboId).with("attempted_via", "program")
                        .with("entry_phase", "MAIN1"));
                Map<String, Object> product = new HashMap<>();
                product.put("program", programPaths.get(comboId));
                events.accept(ArenaEvent.of("combo_shortcut", view.turn(), seat)
                        .with("combo", comboId).with("iterations_proven", 0)
                        .with("bounded_product", product));
                return Optional.of(Action.program(
                        new ProgramOrder(comboId, programPaths.get(comboId))));
            }
            Optional<ExecutorBindings.Binding> binding = bindings.forCombo(status.id());
            Optional<LineExecutor> executor = binding.flatMap(ExecutorBindings::executorFor);
            if (executor.isEmpty()) {
                // no binding / unknown archetype: detection-only until a
                // generic fallback can convert proven resources
                ignore(status.id(), view.turn(), "no_viable_route");
                continue;
            }
            // PR-18 (first e2e finding): tracker readiness is REACHABILITY;
            // an unassemblable line (piece in graveyard/unseen) is no route.
            // PR-40: this is a TRANSIENT state, not a coverage gap, and
            // reporting both as "no_viable_route" badly overstated how many
            // combos lack an executor — the first funnel showed a fully
            // bound combo (the Scepter loop) as the top "unrouted" entry 13
            // times, when it was simply mid-assembly.
            List<LineExecutor.Step> assembly = executor.get().assemblySteps(view);
            if (assembly == null) {
                ignore(status.id(), view.turn(), "not_assemblable");
                continue;
            }
            // PR-19 (second e2e batch finding): don't attempt a line whose
            // first cast is plainly unpayable — that was 12 aborts of noise
            if (!assembly.isEmpty() && assembly.get(0).isCast()
                    && view.manaPool() + view.untappedManaSources()
                            < executor.get().castCostEstimate(assembly.get(0).card())) {
                ignore(status.id(), view.turn(), "mana_reserved",
                        Map.of("cause", "first_cast_unaffordable",
                                "first_cast", assembly.get(0).card(),
                                "estimate", executor.get()
                                        .castCostEstimate(assembly.get(0).card()),
                                "pool", view.manaPool(),
                                "untapped", view.untappedManaSources()));
                continue;
            }
            firstReadyTurn.putIfAbsent(status.id(), view.turn());
            int holdTurns = (int) Math.round(patience * 3);
            if (view.turn() - firstReadyTurn.get(status.id()) < holdTurns) {
                ignore(status.id(), view.turn(), "patience_gate");
                continue;
            }
            attemptedThisTurn.add(status.id());
            activeComboId = status.id();
            activeExecutor = executor.get();
            activeBinding = binding.get();
            lineState = new LineExecutor.LineState(0, 0);
            events.accept(ArenaEvent.of("line_entered", view.turn(), seat)
                    .with("combo", status.id())
                    .with("binding", binding.get().comboId())
                    .with("attempted_via", "binding")
                    .with("entry_phase", executor.get().entryPhase()));
            return assemblyAction(view, validator);
        }
        return deployProgram(view).or(() -> compiledPairings(view)).or(() -> pairedPlays(view))
                .or(() -> engineCycle(view)).or(() -> engineSetup(view))
                .or(() -> preAssembly(view));
    }

    // PR-31: paired plays (wipe + instant shield) — binding-driven, no loop
    private String pendingProtection;
    private int pendingProtectionTurn = -1;
    private final Set<String> firedPairs = new HashSet<>();

    /** The shield the controller must cast while our trigger is on the stack. */
    public String pendingProtection() {
        return pendingProtection;
    }

    /**
     * PR-eta panel finding: a legacy shield armed for a wipe whose cast
     * silently failed dangles FOREVER (the epsilon Final Showdown dangle)
     * and then fires into the first non-empty stack it sees — including a
     * compiled pairing's own wipe. Armed protection is only live the turn
     * it was armed; the controller expires it after that.
     */
    public boolean pendingProtectionFresh(int turn) {
        return pendingProtection != null && pendingProtectionTurn == turn;
    }

    public void expireStaleProtection(int turn) {
        if (pendingProtection != null && pendingProtectionTurn != turn) {
            events.accept(ArenaEvent.of("line_aborted", turn, seat)
                    .with("cause", "stale_protection")
                    .with("piece_lost", pendingProtection));
            pendingProtection = null;
        }
    }

    /** The controller reports the response cast (or its failure); the pair ends. */
    public void protectionResolved(int turn, boolean cast) {
        if (pendingProtection == null) {
            return;
        }
        if (cast) {
            events.accept(ArenaEvent.of("line_step", turn, seat)
                    .with("stage", "PAIRED_PROTECT")
                    .with("iteration", 0));
        } else {
            events.accept(ArenaEvent.of("line_aborted", turn, seat)
                    .with("cause", "interaction")
                    .with("piece_lost", pendingProtection));
        }
        pendingProtection = null;
    }

    /**
     * PR-31: fire a paired play — both cards in hand, mana for BOTH, a board
     * worth punishing — casting the trigger now and arming the protection
     * for the on-stack response. Once per pair per game.
     */
    private Optional<Action> pairedPlays(SeatView view) {
        if (pendingProtection != null) {
            return Optional.empty();
        }
        // PR-49: pick the pair with the highest BOARD VALUE, not the first
        // affordable one. Pairs arrive cheapest-first, and the 300-game
        // batch showed that meant the cheapest sweeper won every time — the
        // white deck's land-destruction lines, its strongest play, never
        // fired once in 300 games.
        ExecutorBindings.Binding bestBinding = null;
        PairedPlay bestPair = null;
        int bestValue = 0;
        for (ExecutorBindings.Binding binding : bindings.all()) {
            if (!PairedPlay.ARCHETYPE.equals(binding.archetype())
                    || firedPairs.contains(binding.comboId())
                    || attemptedThisTurn.contains(binding.comboId())
                    // PR-eta: a pair with a compiled program runs ONLY
                    // through it (one execution path, same rule as combos)
                    || pairingSpecs.stream().anyMatch(
                            sp -> sp.id().equals(binding.comboId()))) {
                continue;
            }
            Optional<LineExecutor> executor = ExecutorBindings.executorFor(binding);
            if (executor.isEmpty() || !(executor.get() instanceof PairedPlay pair)
                    || !pair.playable(view)) {
                continue;
            }
            int value = pair.valueAgainst(view);
            if (value > bestValue) {
                bestValue = value;
                bestPair = pair;
                bestBinding = binding;
            }
        }
        if (bestPair == null) {
            return Optional.empty();
        }
        attemptedThisTurn.add(bestBinding.comboId());
        firedPairs.add(bestBinding.comboId());
        pendingProtection = bestPair.protectionCard();
        pendingProtectionTurn = view.turn();
        events.accept(ArenaEvent.of("line_entered", view.turn(), seat)
                .with("combo", bestBinding.comboId())
                .with("binding", bestBinding.comboId())
                .with("attempted_via", "binding")
                .with("entry_phase", bestPair.entryPhase()));
        events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                .with("stage", "PAIRED_CAST")
                .with("iteration", 0)
                .with("board_value", bestValue));
        return Optional.of(Action.play(LineExecutor.Step.cast(bestPair.triggerCard())));
    }

    /**
     * PR-26 pre-assembly (the obs-100 t14 finding: stock casts the commander
     * at median turn 14 in a deck whose plan needs her on turn 3): when no
     * line can enter, cast a bound combo's COMMAND-zone piece on curve —
     * driven entirely by the combos.json piece locations and the binding's
     * cost estimate, so a deck with no bound combos never deviates from
     * stock (inertness). Soft decision: no event (the cast itself is
     * recorded as spell_cast), and a live refusal is skipped, not aborted.
     */
    /**
     * ASSEMBLE-AND-DEPLOY for PROGRAM combos — the offensive counterpart to the
     * assembly gate. When a program combo's pieces are all REACHABLE (in hand,
     * command, or on the battlefield) but not yet ASSEMBLED (a piece still in
     * hand/command, or its equipment on the wrong host), proactively cast the
     * missing piece or attach the equipment so the combo actually comes online —
     * instead of waiting on stock AI's generic sequencing, which is why the
     * ~1/30 win rate was dominated by pieces that never assembled (14x Selvala in
     * the command zone, 7x Umbral unattached in the smoke batch). One deploy
     * action per window; reuses each program's own on_battlefield/attached
     * preconditions (the same data the assembly gate reads). Deck-agnostic.
     */
    private Optional<Action> deployProgram(SeatView view) {
        ComboTracker.Snapshot snap = tracker.recompute(view);
        // pick the CLOSEST deployable program combo: every piece reachable
        // (status.ready()) but not yet assembled, fewest casts remaining
        ComboTracker.ComboStatus best = null;
        int bestOffBoard = Integer.MAX_VALUE;
        for (ComboTracker.ComboStatus status : snap.statuses()) {
            if (!programPaths.containsKey(status.id())
                    || firedShortcuts.contains(status.id())
                    || !status.ready()                                   // a piece is unreachable
                    || programAssembled(status.id(), status, view)) {    // assembled -> dispatch path owns it
                continue;
            }
            int offBoard = (int) programOnBattlefield.getOrDefault(status.id(), Set.of())
                    .stream().filter(p -> !"BATTLEFIELD".equals(status.where().get(p))).count();
            if (offBoard < bestOffBoard) {
                bestOffBoard = offBoard;
                best = status;
            }
        }
        if (best == null) {
            return Optional.empty();
        }
        String id = best.id();
        // 1) cast a required piece not yet in play (commander from COMMAND, or a
        //    combo piece from HAND). An unaffordable cast resolves to null in the
        //    controller and soft-skips; attemptedDeploys stops a same-turn retry.
        for (String piece : programOnBattlefield.getOrDefault(id, Set.of())) {
            String zone = best.where().get(piece);
            if ("BATTLEFIELD".equals(zone) || attemptedDeploys.contains(piece)) {
                continue;
            }
            if ("HAND".equals(zone) || "COMMAND".equals(zone)) {
                attemptedDeploys.add(piece);
                events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                        .with("stage", "PROGRAM_DEPLOY").with("combo", id)
                        .with("deploy", "cast").with("card", piece));
                return Optional.of(Action.play(LineExecutor.Step.cast(piece)));
            }
        }
        // 2) every piece is in play -> attach the equipment to its declared host
        Map<String, String> attachments = view.ownAttachments();
        for (String[] pair : programAttach.getOrDefault(id, List.of())) {
            String equip = pair[0];
            String host = pair[1];
            if (host.equals(attachments.get(equip))
                    || attemptedDeploys.contains("equip:" + equip)) {
                continue;
            }
            if ("BATTLEFIELD".equals(best.where().get(equip))
                    && "BATTLEFIELD".equals(best.where().get(host))) {
                attemptedDeploys.add("equip:" + equip);
                events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                        .with("stage", "PROGRAM_DEPLOY").with("combo", id)
                        .with("deploy", "equip").with("card", equip).with("host", host));
                return Optional.of(Action.play(LineExecutor.Step.equip(equip, host)));
            }
        }
        return Optional.empty();
    }

    private Optional<Action> preAssembly(SeatView view) {
        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (!status.fullySpecified() || firedShortcuts.contains(status.id())) {
                continue;
            }
            Optional<LineExecutor> executor = bindings.forCombo(status.id())
                    .flatMap(ExecutorBindings::executorFor);
            if (executor.isEmpty()) {
                continue;
            }
            for (Map.Entry<String, String> piece : status.where().entrySet()) {
                if (!"COMMAND".equals(piece.getValue())
                        || attemptedDeploys.contains(piece.getKey())) {
                    continue;
                }
                int estimate = executor.get().castCostEstimate(piece.getKey());
                if (estimate > 0
                        && view.manaPool() + view.untappedManaSources() < estimate) {
                    continue;
                }
                attemptedDeploys.add(piece.getKey());
                return Optional.of(Action.play(LineExecutor.Step.cast(piece.getKey())));
            }
        }
        return Optional.empty();
    }

    /** PR-26: does any bound, fully-specified combo exist? (The pilot has business.) */
    public boolean hasBoundCombo(SeatView view) {
        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (status.fullySpecified() && executorExists(status.id())) {
                return true;
            }
        }
        return false;
    }

    /**
     * PR-26 veto set: the deck's conversion payoffs. The controller adds the
     * engine-side spell-ness test — only ONE-SHOT payoffs (instant/sorcery)
     * are reserved; permanents deploy freely (early Crossroads on the
     * battlefield makes SPREAD_COMBAT better, not worse).
     */
    public Set<String> conversionPayoffNames(SeatView view) {
        return deckPayoffs(tracker.recompute(view));
    }

    /** PR-31: both halves of every paired play — stock must never cast them. */
    private Set<String> pairedPlayCards() {
        Set<String> cards = new java.util.LinkedHashSet<>();
        for (ExecutorBindings.Binding binding : bindings.all()) {
            if (PairedPlay.ARCHETYPE.equals(binding.archetype())
                    && ExecutorBindings.executorFor(binding).orElse(null)
                            instanceof PairedPlay pair) {
                cards.add(pair.triggerCard());
                cards.add(pair.protectionCard());
            }
        }
        // PR-eta panel finding: compiled pairs must reserve their own cards —
        // reservation through the legacy artifact alone breaks the day prep
        // stops emitting a compiled pair there
        for (PairingSpec spec : pairingSpecs) {
            cards.add(spec.wipe());
            cards.add(spec.protection());
        }
        // PR-kappa: engine pieces too — stock casts Land Tax 12+ turns late
        // and would waste it; the pilot owns these casts
        for (EngineSpec spec : engineSpecs) {
            cards.addAll(spec.pieces());
        }
        return cards;
    }

    /** PR-31: everything the veto reserves — one-shot payoffs ∪ paired plays. */
    public Set<String> reservedCastNames(SeatView view) {
        Set<String> reserved = new java.util.LinkedHashSet<>(conversionPayoffNames(view));
        reserved.addAll(pairedPlayCards());
        return reserved;
    }

    /** PR-31: does the veto have anything to guard? */
    public boolean hasReservedPlays(SeatView view) {
        return hasBoundCombo(view) || !pairedPlayCards().isEmpty();
    }

    /**
     * PR-26: worth casting a tutor now? Any bound combo (missing pieces are
     * fetchable, payoffs stageable at IMMINENT) or a pending conversion (the
     * fetch runs at CONVERSION urgency and pulls the payoff). Stock cast
     * zero tutors in 100 observed games — the pilot initiates.
     */
    public boolean wantsTutor(SeatView view) {
        return !firedShortcuts.isEmpty() || hasBoundCombo(view);
    }

    /**
     * PR-30 (research survey: "set a mana-runway target; ramp before
     * durdle"): the cheapest bound line's total entry cost — the sum of its
     * pieces' cast estimates, minimized over bound combos. Below this in
     * untapped sources, the pilot prefers casting mana producers. 0 = no
     * bound combo or no estimates = no runway opinion.
     */
    public int entryRunway(SeatView view) {
        int runway = 0;
        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (!status.fullySpecified()) {
                continue;
            }
            Optional<LineExecutor> executor = bindings.forCombo(status.id())
                    .flatMap(ExecutorBindings::executorFor);
            if (executor.isEmpty()) {
                continue;
            }
            int total = 0;
            for (String piece : status.where().keySet()) {
                total += executor.get().castCostEstimate(piece);
            }
            if (total > 0 && (runway == 0 || total < runway)) {
                runway = total;
            }
        }
        return runway;
    }

    /**
     * The ASSEMBLY stage (PR-18): deploy reachable pieces until the line is
     * executable, THEN prove it on a copy. Validation failure after assembly
     * is a line abort (the attempt happened and is recorded), not an ignore.
     */
    private Optional<Action> assemblyAction(SeatView view,
            Function<LineExecutor, SimResult> validator) {
        List<LineExecutor.Step> assembly = activeExecutor.assemblySteps(view);
        if (assembly == null) {
            // PR-40: say WHY. A batch that logs only "validation" cannot
            // distinguish "the pieces moved out from under us" from "the
            // proof ran and the loop was unprofitable" — and the first live
            // funnel showed 48 of these against 6 fires, the single largest
            // loss in the whole pipeline, with no way to diagnose it.
            abortLine(view.turn(), "validation", null, "not_assemblable");
            return Optional.empty();
        }
        if (!assembly.isEmpty()) {
            // no-progress watchdog: a step that plays but changes nothing
            // (silent engine refusal) must abort, never spin priorities away
            String signature = assembly.toString();
            if (signature.equals(lastAssemblySignature)) {
                if (++assemblyRepeats > 8) {
                    abortLine(view.turn(), "engine_error", assembly.get(0).card());
                    return Optional.empty();
                }
            } else {
                lastAssemblySignature = signature;
                assemblyRepeats = 0;
            }
            events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                    .with("stage", "ASSEMBLY")
                    .with("iteration", lineState.iteration()));
            lineState = lineState.advance();
            return Optional.of(Action.play(assembly.get(0)));
        }

        // assembled — the engine proves the loop before anything fires
        SimResult proof = validator.apply(activeExecutor);
        if (!proof.isProfitable()) {
            // PR-29 (the gauntlet finding): the line is CORRECT but its yield
            // needs help — Staff/Sabertooth loops want a big body the deck
            // has in hand. Deploy toward the prerequisite once per turn
            // (Selvala's yield reads power, not readiness — a sick fatty
            // still counts), then re-prove; only then abort.
            if (activeExecutor.yieldPrereq() != null
                    && !attemptedDeploys.contains("__prereq__")) {
                attemptedDeploys.add("__prereq__");
                events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                        .with("stage", "PREREQ_DEPLOY")
                        .with("iteration", lineState.iteration()));
                lineState = lineState.advance();
                return Optional.of(Action.play(LineExecutor.Step.prereqDeploy()));
            }
            // the proof RAN and refused: carry its verdict out so a batch can
            // be triaged (which piece blocked, or "the loop simply does not
            // net positive from here") instead of 48 anonymous aborts
            abortLine(view.turn(), "validation", null,
                    proof.blockedBy() != null
                            ? "blocked:" + proof.blockedBy()
                                    + (proof.diagnostic() != null
                                            ? " (" + proof.diagnostic() + ")" : "")
                            : "unprofitable");
            return Optional.empty();
        }
        if (activeExecutor instanceof SpellCopyLoop copyLoop) {
            // PR-27b: token product — compress to a flood order; the route
            // is DIRECT damage through the battlefield engine
            String comboId = activeComboId;
            LethalityPlanner.Verdict verdict = LethalityPlanner.choose(routePlan, view, events);
            firedShortcuts.add(comboId);
            firedTurns.put(comboId, view.turn());
            bankedPhase = view.phase();
            firedBinding = activeBinding;
            currentRoute = verdict.route();
            lastPlanTurn = view.turn();
            lastPlanState = planState(view);
            Map<String, Object> boundedProduct = new HashMap<>();
            boundedProduct.put("token_entries", copyLoop.floodCount());
            events.accept(ArenaEvent.of("combo_shortcut", view.turn(), seat)
                    .with("combo", comboId)
                    .with("iterations_proven", proof.cycles())
                    .with("bounded_product", boundedProduct));
            TokenFlood order = new TokenFlood(comboId, copyLoop.copier(), copyLoop.floodCount());
            exitLine();
            return Optional.of(Action.flood(order));
        }
        // PR-51: the compression is LOSSY, and sometimes the discarded part
        // is the win. A mana shortcut replaces N real iterations with one
        // pool injection, which silently throws away every side effect those
        // iterations would have produced — cast triggers above all. Urza's
        // Aetherflux Reservoir costs 50 life to fire and the deck starts at
        // 40; the only thing that ever pays for it is Aetherflux's OWN cast
        // trigger gaining life once per spell cast this turn. Compress the
        // loop and those casts never happen, so the outlet is unusable and
        // the seat banks a thousand mana it can never spend.
        //
        // So: when the deck holds a payoff that feeds on the very thing the
        // compression discards, step the loop for real instead.
        if (activeExecutor instanceof ShortcutSource loop && loop.shortcutEligible()
                && !castTriggerPayoffPresent(view)) {
            String comboId = activeComboId;
            // PR-33: the executor names its own pool source (the old
            // engine→tapper params-guess was null for the Scepter loop and
            // NPE'd Mana's constructor mid-game)
            String engineCard = loop.poolSourceCard();
            LethalityPlanner.Verdict verdict = LethalityPlanner.choose(routePlan, view, events);
            Map<String, Object> boundedProduct = new HashMap<>();
            boundedProduct.put("mana_" + loop.poolColor(), SHORTCUT_POOL);
            firedShortcuts.add(comboId);
            firedTurns.put(comboId, view.turn());
            bankedPhase = view.phase();
            // PR-25: conversion state — the binding's payoffs stay deploy
            // candidates after the line exits, and the verdict feeds combat
            firedBinding = activeBinding;
            currentRoute = verdict.route();
            lastPlanTurn = view.turn();
            lastPlanState = planState(view);
            events.accept(ArenaEvent.of("combo_shortcut", view.turn(), seat)
                    .with("combo", comboId)
                    .with("iterations_proven", proof.cycles())
                    .with("bounded_product", boundedProduct));
            // PR-18 (second e2e finding): stock AI's DECISION layer never sees
            // floating mana (only battlefield sources) — the pool must be
            // SPENT by script. DEPLOY follows: cast the binding's payoffs.
            lineState = new LineExecutor.LineState(2, 0);
            return Optional.of(Action.shortcut(new ShortcutOrder(comboId, engineCard,
                    loop.poolColor(), SHORTCUT_POOL, verdict.route())));
        }
        lineState = lineState.nextStage(); // MANA_LOOP stepping (banking path)
        return nextAction(view, true, validator);
    }

    /**
     * The DEPLOY stage (PR-18/19): convert the injected pool by casting
     * payoffs from hand, one per priority — the binding's own payoffs first
     * (Craterhoof, Finale class), then ANY card the route-coverage deck
     * layer identified as a payoff (PR-19 breadth: the one shortcut game of
     * batch #3 had no binding payoffs in hand while route payoffs sat
     * there). Hand exhausted = line complete; combat conversion is the
     * stock attack logic's job (haste creatures attack).
     */
    private Optional<Action> deployAction(SeatView view) {
        for (String payoff : deployCandidates(activeBinding)) {
            if (view.cardsIn(SeatView.Zone.HAND).contains(payoff)
                    && !attemptedDeploys.contains(payoff)) {
                attemptedDeploys.add(payoff);
                events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                        .with("stage", "DEPLOY")
                        .with("iteration", lineState.iteration()));
                lineState = lineState.advance();
                return Optional.of(Action.play(
                        LineExecutor.Step.castX(payoff, DEPLOY_X)));
            }
        }
        exitLine();
        return Optional.empty();
    }

    /**
     * PR-38 (Phase 6 A2): route the banked pool through the conversion state
     * machine — table-wide killer, else loop-to-lethal drill, else dig for
     * an outlet. Every choice is recorded so a batch can be audited for
     * WHY a conversion did or did not happen (the long-200 post-mortem had
     * to infer this from route names alone).
     */
    /**
     * PR-A: has the banked pool survived to now?
     *
     * <p>Mana empties as each step and phase ends (CR 500.4). A pool banked
     * in a main phase is GONE by combat unless an unspent-mana permanent
     * (Omnath's {@code S:Mode$ UnspentMana}) is on the battlefield. We were
     * asserting the opposite: the shortcut injected a pool and the pilot
     * went on trying to spend it in later phases, which the engine simply
     * refuses. That is the green deck floating a thousand mana and passing
     * the turn, in every game.
     */
    private boolean pooledManaStillLive(SeatView view) {
        if (bankedPhase == null || bankedPhase.equals(view.phase())) {
            return true;
        }
        for (String keeper : routePlan.payoffCards(
                forge.arena.prep.PayoffRules.UNSPENT_MANA_GRANT)) {
            if (view.locate(keeper) == SeatView.Presence.BATTLEFIELD) {
                return true;
            }
        }
        return false;
    }

    private Optional<Action> convert(SeatView view) {
        if (!pooledManaStillLive(view)) {
            // the pool expired with the phase; spending it is not a legal
            // plan, and pretending otherwise burns every priority window
            events.accept(ArenaEvent.of("pool_expired", view.turn(), seat)
                    .with("banked_phase", bankedPhase)
                    .with("current_phase", view.phase()));
            bankedPhase = null;
            firedShortcuts.clear();
            return Optional.empty();
        }
        java.util.LinkedHashSet<String> bindingPayoffs = deployCandidates(firedBinding);
        // PR-55: the planner needs to know a kill is already routable, so it
        // can decline to dig instead of taking it. Outlet kills (TABLE_WIDE,
        // DRILL) still outrank everything — they ARE the kill.
        boolean killRouteLive = currentRoute != null && !"BANK_AND_HOLD".equals(currentRoute);
        ConversionPlanner.Plan plan = ConversionPlanner.choose(
                view, routePlan, bindingPayoffs, attemptedDeploys, killRouteLive);
        if (plan.kind() == ConversionPlanner.Kind.NONE) {
            return Optional.empty();
        }
        attemptedDeploys.add(plan.card());
        events.accept(ArenaEvent.of("conversion_step", view.turn(), seat)
                .with("kind", plan.kind().name())
                .with("card", plan.card())
                .with("outlet_class", plan.outletClass())
                .with("x", plan.x()));
        return switch (plan.kind()) {
            case TABLE_WIDE, DIG, X_SPELL -> Optional.of(Action.play(
                    LineExecutor.Step.castX(plan.card(), plan.x())));
            // PR-gamma: a program piece is never drilled by the legacy path —
            // the program is its one execution path (fresh evaluation after
            // an interruption re-enters the PROGRAM, not a fallback)
            case DRILL -> {
                if (programPieces.contains(plan.card())) {
                    events.accept(ArenaEvent.of("drill_suppressed", view.turn(), seat)
                            .with("card", plan.card())
                            .with("reason", "program_owns_piece"));
                    yield Optional.empty();
                }
                yield Optional.of(Action.drill(new DrillOrder(plan.card())));
            }
            // a deployed draw engine is ACTIVATED, not cast: the controller
            // finds its draw ability structurally (ApiType.Draw), and tries a
            // real tutor first — fetching the payoff beats drawing one card
            case DIG_ACTIVATE -> Optional.of(Action.play(
                    LineExecutor.Step.digActivate(plan.card())));
            default -> Optional.empty();
        };
    }

    /**
     * PR-25 conversion deploy: after the line has exited (hand was empty at
     * fire time), payoffs that arrive later still get cast off the banked
     * pool, one per priority, deduped per turn — with the scripted X.
     */
    private Optional<Action> conversionDeploy(SeatView view) {
        for (String payoff : deployCandidates(firedBinding)) {
            if (view.cardsIn(SeatView.Zone.HAND).contains(payoff)
                    && !attemptedDeploys.contains(payoff)) {
                attemptedDeploys.add(payoff);
                events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                        .with("stage", "DEPLOY_WIN")
                        .with("iteration", 0));
                return Optional.of(Action.play(
                        LineExecutor.Step.castX(payoff, DEPLOY_X)));
            }
        }
        return Optional.empty();
    }

    /**
     * PR-51: does this seat hold a payoff that only works if the loop's
     * iterations REALLY HAPPEN? Today that means a life-cost damage outlet
     * (the Aetherflux class): its cost is paid by a cast trigger, so the
     * casts must occur rather than being compressed away. Deck-agnostic —
     * it reads the route-coverage payoff classes, like everything else.
     */
    private boolean castTriggerPayoffPresent(SeatView view) {
        for (String card : routePlan.payoffCards(
                forge.arena.prep.PayoffRules.LIFE_COST_OUTLET)) {
            if (view.locate(card) == SeatView.Presence.BATTLEFIELD) {
                return true;
            }
        }
        return false;
    }

    /**
     * PR-51: can this hand actually CASH an engine — is any outlet class
     * reachable from hand, battlefield or command zone? Artifact-driven, so
     * a dropped-in deck is judged by its own payoff classes.
     */
    private boolean outletReachable(SeatView view) {
        for (String outletClass : List.of(
                forge.arena.prep.PayoffRules.X_DRAIN_EACH_OPPONENT,
                forge.arena.prep.PayoffRules.PING_ANY_TARGET,
                forge.arena.prep.PayoffRules.LIFE_COST_OUTLET,
                forge.arena.prep.PayoffRules.PING_EACH_OPPONENT,
                forge.arena.prep.PayoffRules.MASS_PUMP)) {
            for (String card : routePlan.payoffCards(outletClass)) {
                SeatView.Presence where = view.locate(card);
                if (where == SeatView.Presence.HAND
                        || where == SeatView.Presence.BATTLEFIELD
                        || where == SeatView.Presence.COMMAND) {
                    return true;
                }
            }
        }
        return false;
    }

    /**
     * PR-51 (architecture survey §Q4, the Churchill-Buro landmark bound):
     * MIN TURNS UNTIL SOME BOUND LINE COULD FIRE — the count of pieces not
     * yet reachable plus the mana still to find, taken over the closest
     * line. It is an admissible lower bound (never optimistic), which is
     * what makes it usable as a planning signal rather than a guess.
     *
     * <p>Deliberately NOT emitted from the decision path. Distance is an
     * OBSERVATION, and this codebase separates those from decisions — the
     * detection bridge records what is TRUE, the pilot records what it
     * CHOSE. Emitting it here shifted every positional assertion in the
     * decision tests, which is the suite correctly defending that split.
     * Exposed as API for the arbiter (architecture survey Q3/Q4, where it
     * is the dominant signal) and for the observation side to publish.
     */
    public int distanceToFire(SeatView view) {
        int best = Integer.MAX_VALUE;
        for (ComboTracker.ComboStatus status : tracker.recompute(view).statuses()) {
            if (!status.fullySpecified() || !executorExists(status.id())) {
                continue;
            }
            int missing = status.distance();
            int manaGap = 0;
            Optional<ExecutorBindings.Binding> binding = bindings.forCombo(status.id());
            if (binding.isPresent()) {
                Optional<LineExecutor> executor = binding.flatMap(ExecutorBindings::executorFor);
                if (executor.isPresent()) {
                    int need = 0;
                    for (String piece : status.where().keySet()) {
                        need += executor.get().castCostEstimate(piece);
                    }
                    manaGap = Math.max(0,
                            need - (view.manaPool() + view.untappedManaSources()));
                }
            }
            // one turn per missing piece (a draw or a tutor), one per land
            // drop still needed — the admissible floor, not a forecast
            best = Math.min(best, missing + manaGap);
        }
        return best == Integer.MAX_VALUE ? -1 : best;
    }

    /** Binding payoffs (live or fired) ∪ the route plan's payoff classes. */
    private java.util.LinkedHashSet<String> deployCandidates(ExecutorBindings.Binding binding) {
        java.util.LinkedHashSet<String> candidates = new java.util.LinkedHashSet<>();
        if (binding != null) {
            candidates.addAll(binding.payoffs());
        }
        routePlan.payoffs().values().forEach(candidates::addAll);
        return candidates;
    }

    /**
     * PR-25 forced close: the combat instruction while conversion is pending.
     * Only the combat routes produce one — SPREAD_COMBAT (all-in, split
     * lowest-life-first) and COMMANDER_DMG_SEQUENCE (commander at the
     * lowest-life head). Empty = stock combat, untouched (inertness: a
     * pilot that never fired never steers an attack). Recorded as a
     * FORCED_ATTACK line_step each combat it steers.
     */
    public Optional<CombatOrder> combatOrder(SeatView view) {
        if (firedShortcuts.isEmpty() || currentRoute == null
                || !("SPREAD_COMBAT".equals(currentRoute)
                        || "COMMANDER_DMG_SEQUENCE".equals(currentRoute))) {
            return Optional.empty();
        }
        List<Integer> killOrder = view.opponents().stream()
                .sorted(java.util.Comparator.comparingInt(SeatView.OpponentView::life))
                .map(SeatView.OpponentView::seatIndex)
                .toList();
        if (killOrder.isEmpty()) {
            return Optional.empty();
        }
        events.accept(ArenaEvent.of("line_step", view.turn(), seat)
                .with("stage", "FORCED_ATTACK")
                .with("iteration", 0));
        return Optional.of(new CombatOrder(currentRoute, killOrder));
    }

    /**
     * PR-34 (research adoption: continuous lethal-check at every combat —
     * the survey's first lesson from every competition it covered): the
     * controller found a GUARANTEED kill by combat math and forces the
     * alpha; the pilot records the decision. Telemetry only — the math
     * needs per-creature engine data SeatView deliberately hides.
     */
    public void reportLethalAlpha(int turn, int targetSeat, int guaranteed, int targetLife) {
        events.accept(ArenaEvent.of("lethal_alpha", turn, seat)
                .with("target_seat", targetSeat)
                .with("guaranteed_damage", guaranteed)
                .with("target_life", targetLife));
    }

    /**
     * PR-37 (Phase 6 A3): one loop-to-lethal drill activation was returned —
     * the outlet fired at a specific opponent. Telemetry only.
     */
    public void reportDrillStep(int turn, String outlet, int targetSeat) {
        reportDrillStep(turn, outlet, targetSeat, -1, -1, -1);
    }

    /**
     * PR-70 loop-health telemetry. A ping-loop only SUSTAINS when the
     * resource it spends comes back: Ballista removes a +1/+1 counter to
     * deal damage, lifelink turns that damage into life, and the engine's
     * life-gain trigger returns the counter. If counters fall monotonically
     * the "loop" is a pinger eating itself — which is exactly what was
     * happening, invisibly, because we only logged that a drill step fired.
     *
     * <p>Deck-agnostic in shape (a counter count and a life total), and
     * temporary in intent: this is the instrumentation that tells us the
     * loop is real, and can be dropped once it demonstrably is.
     */
    public void reportDrillStep(int turn, String outlet, int targetSeat,
            int iteration, int outletCounters, int ownLife) {
        reportDrillStep(turn, outlet, targetSeat, iteration, outletCounters, ownLife, false);
    }

    public void reportDrillStep(int turn, String outlet, int targetSeat,
            int iteration, int outletCounters, int ownLife, boolean lifelink) {
        ArenaEvent e = ArenaEvent.of("outlet_drill", turn, seat)
                .with("outlet", outlet)
                .with("target_seat", targetSeat);
        if (iteration >= 0) {
            e = e.with("iteration", iteration)
                    .with("outlet_counters", outletCounters)
                    .with("own_life", ownLife)
                    .with("outlet_lifelink", lifelink);
        }
        events.accept(e);
    }

    /** Gate 3.6 logging half: the controller's stall watchdog reports through the pilot. */
    public void reportStalled(int turn, String binding, String stateHash, String dumpPath) {
        events.accept(ArenaEvent.of("combo_stalled", turn, seat)
                .with("binding", binding)
                .with("state_hash", stateHash)
                .with("dump_path", dumpPath));
    }

    /** The controller couldn't produce a step's ability — the line ends here. */
    public void abortLine(int turn, String cause, String pieceLost) {
        abortLine(turn, cause, pieceLost, null);
    }

    /**
     * @param detail PR-40: WHY the line ended, when the cause alone is not
     *               actionable. For a validation abort this is the
     *               {@link SimResult}'s blocked-by reason (which piece or
     *               quantity refused) or {@code unprofitable} — without it a
     *               batch reports 48 identical "validation" lines and no
     *               path to a fix.
     */
    public void abortLine(int turn, String cause, String pieceLost, String detail) {
        ArenaEvent event = ArenaEvent.of("line_aborted", turn, seat).with("cause", cause);
        if (pieceLost != null) {
            event.with("piece_lost", pieceLost);
        }
        if (detail != null) {
            event.with("detail", detail);
        }
        events.accept(event);
        exitLine();
    }

    private void exitLine() {
        activeComboId = null;
        activeExecutor = null;
        activeBinding = null;
        lineState = null;
        lastAssemblySignature = null;
        assemblyRepeats = 0;
    }

    private void ignore(String comboId, int turn, String reason) {
        ignore(comboId, turn, reason, null);
    }

    /**
     * PLAY-OBSERVATIONS finding 2: chi30 measured 11 ready-combos entering
     * 2+ turns late (worst +18), every one attributed to a bare
     * "mana_reserved" — indistinguishable between a genuine mana wait and
     * an estimate over-pricing the line. The detailed form carries the
     * gate's own numbers so the NEXT batch adjudicates; the fix, if any,
     * follows the measurement.
     */
    private void ignore(String comboId, int turn, String reason,
            Map<String, Object> details) {
        if (Integer.valueOf(turn).equals(lastIgnoredTurn.get(comboId))) {
            return; // one decision record per combo per turn, not per priority
        }
        lastIgnoredTurn.put(comboId, turn);
        ArenaEvent e = ArenaEvent.of("combo_ignored", turn, seat)
                .with("combo", comboId)
                .with("reason", reason);
        if (details != null) {
            for (Map.Entry<String, Object> d : details.entrySet()) {
                e = e.with(d.getKey(), d.getValue());
            }
        }
        events.accept(e);
    }

    public String activeComboId() {
        return activeComboId;
    }
}
