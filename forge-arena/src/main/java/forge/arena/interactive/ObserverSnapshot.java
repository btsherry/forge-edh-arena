package forge.arena.interactive;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.collect.Multiset;
import com.google.common.eventbus.Subscribe;

import forge.game.Game;
import forge.game.GameOutcome;
import forge.game.card.Card;
import forge.game.card.CounterType;
import forge.game.event.GameEvent;
import forge.game.phase.PhaseHandler;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.spellability.SpellAbilityStackInstance;
import forge.game.zone.ZoneType;

/**
 * A continuously-updated, PUBLIC observer snapshot of the game, written for the
 * human operator watching an interactive mailbox match. Unlike the per-seat
 * mailbox requests (which only exist while a mailbox seat has a pending
 * decision), this snapshot is refreshed on every game event — so the dashboard
 * is never blind, including during the HUMAN's turn when no mailbox request is
 * pending.
 *
 * <p>It registers itself on the game's Guava event bus via
 * {@link Game#subscribeToEvents(Object)} (Game.java:1024, which delegates to a
 * {@code com.google.common.eventbus.EventBus}). The {@link Subscribe}-annotated
 * {@link #onGameEvent(GameEvent)} takes the base {@link GameEvent} type
 * (confirmed pattern: {@code forge.game.GameLogFormatter#recieve(GameEvent)} at
 * GameLogFormatter.java:316), so it receives every event the game posts.
 *
 * <p><b>Fairness / hidden info:</b> the snapshot is OBSERVER/PUBLIC only. It
 * exposes, for every seat, only PUBLIC information — life, poison, and the fully
 * public battlefield (per-card mechanical fields; see {@link #cardState}). Hand
 * and library are exposed as COUNTS only for every seat, including the human, so
 * the operator can never read anyone's hand. The stack is exposed as source
 * names (public).
 *
 * <p><b>Robustness:</b> the handler never throws — a snapshot failure must never
 * disrupt the game — and writes are atomic (temp file + rename) and debounced
 * (skipped if less than {@link #MIN_WRITE_INTERVAL_MS} since the last write) so
 * the bus firing many events in a burst does not thrash the disk. The final
 * event of a game (game outcome) always forces a write regardless of debounce.
 */
public final class ObserverSnapshot {

    /** Debounce window: skip writing if the previous write was this recent. */
    private static final long MIN_WRITE_INTERVAL_MS = 200L;

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * Guard against double-registration: at most one ObserverSnapshot is
     * registered per Game instance, keyed by Game identity. A WeakHashMap lets
     * finished games be collected. Guarded by its own monitor.
     */
    private static final Set<Game> REGISTERED =
            java.util.Collections.newSetFromMap(new WeakHashMap<>());

    private final Game game;
    private final Path outputFile;
    private volatile long lastWriteMs;

    private ObserverSnapshot(Game game, Path outputFile) {
        this.game = game;
        this.outputFile = outputFile;
    }

    /**
     * Ensure exactly one ObserverSnapshot is created and subscribed for
     * {@code game}. Safe to call from every mailbox seat's controller
     * construction; only the first call for a given Game actually registers.
     * Never throws — an observer that fails to attach must not stop the game.
     */
    public static void ensureRegistered(Game game, Path baseDir) {
        if (game == null) {
            return;
        }
        synchronized (REGISTERED) {
            if (REGISTERED.contains(game)) {
                return;
            }
            REGISTERED.add(game);
        }
        try {
            Path base = baseDir != null ? baseDir : MailboxProtocol.baseDir();
            Path out = base.resolve("observer-state.json");
            Files.createDirectories(out.getParent());
            ObserverSnapshot obs = new ObserverSnapshot(game, out);
            game.subscribeToEvents(obs);
            // Write an initial snapshot immediately so the dashboard has state
            // even before the first event fires.
            obs.write(true);
        } catch (RuntimeException | IOException e) {
            // registration failed — drop the guard so a later attempt can retry,
            // and never propagate.
            synchronized (REGISTERED) {
                REGISTERED.remove(game);
            }
            System.err.println("ObserverSnapshot: could not register: " + e.getMessage());
        }
    }

    /**
     * Bus entry point. Guava dispatches this because the game bus is a
     * {@code com.google.common.eventbus.EventBus} and this method is annotated
     * {@link Subscribe} with the base {@link GameEvent} type — matching every
     * event posted via {@code Game.fireEvent}. Must never throw.
     */
    @Subscribe
    public void onGameEvent(GameEvent ev) {
        try {
            // Force a write on the game-over event regardless of debounce so the
            // final board is always captured.
            boolean force = ev != null
                    && ev.getClass().getSimpleName().contains("GameOutcome");
            write(force);
        } catch (Throwable t) {
            // absolutely never let a snapshot failure escape into the game loop
        }
    }

    /** Build and atomically write the snapshot, honouring the debounce unless forced. */
    private void write(boolean force) {
        long now = System.currentTimeMillis();
        if (!force && (now - lastWriteMs) < MIN_WRITE_INTERVAL_MS) {
            return;
        }
        lastWriteMs = now;
        try {
            byte[] bytes = MAPPER.writeValueAsBytes(buildSnapshot());
            writeAtomic(outputFile, bytes);
        } catch (Throwable t) {
            // best effort; a failed snapshot must not disturb the game
        }
    }

    // ---- snapshot assembly (PUBLIC info only) ------------------------------

    private Map<String, Object> buildSnapshot() {
        Map<String, Object> snap = new LinkedHashMap<>();
        snap.put("kind", "observer-snapshot");
        snap.put("timestamp", System.currentTimeMillis());

        PhaseHandler ph = game.getPhaseHandler();
        int turn = ph != null ? ph.getTurn() : 0;
        Player active = ph != null ? ph.getPlayerTurn() : null;
        PhaseType phase = ph != null ? ph.getPhase() : null;
        snap.put("turn", turn);
        snap.put("activeSeat", active != null ? active.getId() : null);
        snap.put("phase", phase != null ? phase.name() : "");
        snap.put("gameOver", game.isGameOver());

        GameOutcome outcome = game.getOutcome();
        if (outcome != null && outcome.getWinningLobbyPlayer() != null) {
            snap.put("winner", outcome.getWinningLobbyPlayer().getName());
        }

        // Every seat: PUBLIC info only. Hand/library are COUNTS, never contents,
        // for ALL seats (including the human) so the operator sees a fair view.
        List<Map<String, Object>> seats = new ArrayList<>();
        for (Player p : game.getPlayers()) {
            Map<String, Object> s = new LinkedHashMap<>();
            s.put("seat", p.getId());
            s.put("name", p.getName());
            s.put("eliminated", p.hasLost());   // field note 16: push eliminations
            s.put("life", p.getLife());
            s.put("poison", p.getPoisonCounters());
            s.put("handSize", p.getCardsIn(ZoneType.Hand).size());
            s.put("librarySize", p.getCardsIn(ZoneType.Library).size());
            // item 12: liveness of this seat's brain from its heartbeat file
            // (true fresh / false stale / null no runner) — a dead seat reads
            // as dead on the dashboard instead of as a slow game
            s.put("brainAlive", MailboxProtocol.brainAlive(
                    outputFile.getParent().resolve("seat-" + p.getId())));
            List<Map<String, Object>> board = new ArrayList<>();
            for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
                board.add(cardState(c));
            }
            s.put("battlefield", board);
            seats.add(s);
        }
        snap.put("seats", seats);

        // PUBLIC stack (source names only), most-recent last.
        List<String> stack = new ArrayList<>();
        for (SpellAbilityStackInstance si : game.getStack()) {
            SpellAbility sa = si.getSpellAbility();
            Card host = sa != null ? sa.getHostCard() : null;
            stack.add(host != null ? host.getName() : String.valueOf(si));
        }
        snap.put("stack", stack);
        return snap;
    }

    /**
     * PUBLIC per-card projection, mirroring the shape of
     * {@code MailboxController.cardState(c, false)}: id, name, P/T + summoning
     * sickness for creatures, type line, tapped, counters, and attached-aura
     * names. All fields are public information. No abilities are listed (this is
     * the lean, opponent-visible shape).
     */
    private static Map<String, Object> cardState(Card c) {
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
        List<String> attached = new ArrayList<>();
        for (Card at : c.getAttachedCards()) {
            attached.add(at.getName());
        }
        if (!attached.isEmpty()) {
            m.put("auras", attached);
        }
        return m;
    }

    // ---- atomic write (mirrors MailboxProtocol.writeAtomic) ----------------

    private static void writeAtomic(Path target, byte[] bytes) throws IOException {
        Path tmp = target.resolveSibling(target.getFileName() + ".tmp");
        Files.write(tmp, bytes);
        try {
            Files.move(tmp, target, StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException atomicUnsupported) {
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
