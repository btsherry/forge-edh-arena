package forge.arena.interactive;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.collect.Multiset;
import com.google.common.eventbus.Subscribe;

import forge.game.Game;
import forge.game.GameOutcome;
import forge.game.GameStage;
import forge.game.card.Card;
import forge.game.card.CounterType;
import forge.game.event.GameEvent;
import forge.game.event.EventValueChangeType;
import forge.game.event.GameEventAttackersDeclared;
import forge.game.event.GameEventCardAttachment;
import forge.game.event.GameEventCardChangeZone;
import forge.game.event.GameEventCardCounters;
import forge.game.event.GameEventCardPhased;
import forge.game.event.GameEventCardStatsChanged;
import forge.game.event.GameEventCardTapped;
import forge.game.event.GameEventGameOutcome;
import forge.game.event.GameEventPlayerCounters;
import forge.game.event.GameEventPlayerPoisoned;
import forge.game.event.GameEventSpellAbilityCast;
import forge.game.event.GameEventZone;
import forge.game.spellability.StackItemView;
import forge.game.event.GameEventPlayerDamaged;
import forge.game.event.GameEventSpellRemovedFromStack;
import forge.game.event.GameEventSpellResolved;
import forge.game.card.CardView;
import forge.game.player.PlayerView;
import forge.game.spellability.SpellAbilityView;
import forge.game.phase.PhaseHandler;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.spellability.SpellAbilityStackInstance;
import forge.game.zone.MagicStack;
import forge.game.zone.ZoneType;

/**
 * A continuously-updated, PUBLIC observer snapshot of the game, written for the
 * human operator watching an interactive mailbox match. Unlike the per-seat
 * mailbox requests (which only exist while a mailbox seat has a pending
 * decision), this snapshot follows every game event (at most one write a
 * second, see below) — so the dashboard is never blind, including during the
 * HUMAN's turn when no mailbox request is pending.
 *
 * <p>It registers itself on the game's Guava event bus via
 * {@link Game#subscribeToEvents(Object)} (Game.java:1024, which delegates to a
 * {@code com.google.common.eventbus.EventBus}). The {@link Subscribe}-annotated
 * {@link #onGameEvent(GameEvent)} takes the base {@link GameEvent} type
 * (confirmed pattern: {@code forge.game.GameLogFormatter#recieve(GameEvent)} at
 * GameLogFormatter.java:316), so it receives every event the game posts.
 *
 * <p><b>Fairness / hidden info:</b> the snapshot is OBSERVER/PUBLIC only. It
 * exposes, for every seat, only PUBLIC information — life, poison, the fully
 * public battlefield (per-card mechanical fields; see {@link #cardState}), and
 * since 2026-09-07 the other public zones: graveyard, face-up exile, command
 * zone, plus what each permanent imprinted or exiled. Hand and library are
 * exposed as COUNTS only for every seat, including the human, so the operator
 * can never read anyone's hand. The stack is exposed as source names plus a
 * detail list (kind, owner, targets). {@code scripts/arena-public-state.py}
 * renders this file for the advisor.
 *
 * <p><b>Robustness:</b> the handler never throws — a snapshot failure must never
 * disrupt the game — and writes are atomic (temp file + rename).
 *
 * <p><b>Cadence (2026-09-14, Ben: "at most one write a second — something
 * cheap that is mostly right"):</b> an event costs a cheap {@link #fingerprint}
 * (turn, phase, active seat, stack ids, last ring seq, and per seat life, hand
 * size, floating mana, battlefield size, eliminated — plus a per-game
 * {@link #mutationTick} that the handler bumps for the events that change a
 * SERIALIZED field the key itself does not read: a tap, a counter, a P/T or
 * type change, an attachment, poison, a zone move; see {@link #mutates}). A
 * write happens when the fingerprint differs from the last write's AND at least
 * {@link #DEFAULT_INTERVAL_MS} (property {@link #INTERVAL_PROPERTY}) has passed
 * since it; a change inside the window schedules ONE deferred write for when
 * the window expires, on a per-game daemon timer thread, so the last change of a
 * burst always lands. The first snapshot of a game and the game-outcome event
 * always write at once. The fingerprint is taken again AFTER the snapshot is
 * built: the timer thread builds against live zone lists the game thread may
 * be mutating, so a build whose key moved is filed as nothing ("rebuilt",
 * counted) and a deferred write is left pending for the settled board. The ring
 * keeps accumulating between writes; only more than {@link #EVENT_RING} ring
 * entries inside one window lose the oldest (an "overrun", counted). Before this (BL-07, 2026-09-04) every event serialized
 * the whole snapshot and wrote whenever a byte differed — a tap, a counter, a
 * phase step — which ran to many writes a second on an AI turn. Per-game
 * counters (writes, deferred, skipped, failures, ring entries by kind, overruns,
 * swallowed exceptions) print as one {@code [arena] observer:} line on stderr at
 * game over.
 *
 * <p><b>Recent events (2026-09-10, seat barks):</b> besides the state, the
 * snapshot carries a short ring of PUBLIC notable events — {@code attack}
 * (attackers declared: seat, count, total power, defenders), {@code damage}
 * (a player damaged; combat damage from several sources in one step is
 * coalesced), {@code countered} (a spell removed from the stack without
 * having resolved: the victim's seat and, when the counterspell is on top of
 * the stack, who countered it), and since the same evening {@code cast} (a
 * spell cast: caster, name, commander flag, mana value), {@code left}
 * (permanents leaving the battlefield in one resolution, coalesced: owners,
 * names, commanders, and the seat whose effect was resolving) and
 * {@code gameover} (the winning seat). The voice runner turns these into the
 * seats' instant reactions. Every field is public information a spectator sees.
 */
public final class ObserverSnapshot {

    /** Ring size for {@code events}; the voice runner reads by {@code seq}. */
    static final int EVENT_RING = 30;

    /** System property naming the write window in milliseconds (default
     *  {@link #DEFAULT_INTERVAL_MS}); {@code 0} writes every change at once. */
    static final String INTERVAL_PROPERTY = "arena.observer.ms";

    /** The write window: a changed fingerprint writes only this long after the
     *  previous write (the first snapshot and game over excepted). */
    static final long DEFAULT_INTERVAL_MS = 1000L;

    /** Total writes across every game in this JVM (the tests read it); the
     *  per-game counters live on the instance and print at game over. */
    static final AtomicInteger WRITES = new AtomicInteger();

    /** Names the per-game timer threads. */
    private static final AtomicInteger TIMERS = new AtomicInteger();

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * Guard against double-registration: at most one ObserverSnapshot is
     * registered per Game instance, keyed by Game identity. A WeakHashMap lets
     * finished games be collected; the value is weak too, because the observer
     * holds its game and a strong value would pin the key. Guarded by its own
     * monitor.
     */
    private static final Map<Game, java.lang.ref.WeakReference<ObserverSnapshot>> REGISTERED =
            new WeakHashMap<>();

    private final Game game;
    private final Path outputFile;
    private final long intervalNanos;
    private final long startedNanos = System.nanoTime();
    private final java.util.ArrayDeque<Map<String, Object>> events = new java.util.ArrayDeque<>();
    private long eventSeq;
    private long mutationTick;   // bumped per fingerprint-invariant mutation event; folded into the key
    private int lastResolvedId = -1;   // TrackableObject id of the last SpellAbilityView that RESOLVED

    // ---- cadence state (guarded by this) ------------------------------------
    private String lastWrittenFp;                // fingerprint of the last successful write
    private long lastWriteNanos;
    private boolean everWritten;
    private boolean finished;                    // the outcome event has been seen
    private long lastWrittenSeq;                 // highest ring seq on disk
    private ScheduledThreadPoolExecutor timer;   // lazy; one daemon thread; down at game over
    private ScheduledFuture<?> pending;          // the one deferred write, if any
    private int consecutiveFailures;

    // ---- per-game counters (E2; guarded by this; one line at game over) ------
    private int eventsSeen, writes, deferred, skippedUnchanged, writeFailures, handlerFailures;
    private int ringOverruns, merged, rebuilt;
    private final Map<String, Integer> ringByKind = new LinkedHashMap<>();
    private int swallowedNote, swallowedResolving, swallowedCmc, swallowedPool, swallowedFingerprint;
    private String lastFailure;   // the most recent swallowed write/fingerprint exception, for the summary

    private ObserverSnapshot(Game game, Path outputFile) {
        this.game = game;
        this.outputFile = outputFile;
        this.intervalNanos = TimeUnit.MILLISECONDS.toNanos(
                Math.max(0L, Long.getLong(INTERVAL_PROPERTY, DEFAULT_INTERVAL_MS)));
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
            if (REGISTERED.containsKey(game)) {
                return;
            }
            REGISTERED.put(game, null);
        }
        try {
            Path base = baseDir != null ? baseDir : MailboxProtocol.baseDir();
            Path out = base.resolve("observer-state.json");
            Files.createDirectories(out.getParent());
            ObserverSnapshot obs = new ObserverSnapshot(game, out);
            synchronized (REGISTERED) {
                REGISTERED.put(game, new java.lang.ref.WeakReference<>(obs));
            }
            game.subscribeToEvents(obs);
            // Write an initial snapshot immediately so the dashboard has state
            // even before the first event fires.
            obs.writeInitial();
        } catch (RuntimeException | IOException e) {
            // registration failed — drop the guard so a later attempt can retry,
            // and never propagate.
            synchronized (REGISTERED) {
                REGISTERED.remove(game);
            }
            System.err.println("ObserverSnapshot: could not register: " + e.getMessage());
        }
    }

    /** The observer registered for {@code game}, or null (the tests read the
     *  per-game counters through it; {@link #WRITES} is JVM-wide and another
     *  game's timer can move it). */
    static ObserverSnapshot of(Game game) {
        synchronized (REGISTERED) {
            java.lang.ref.WeakReference<ObserverSnapshot> ref = REGISTERED.get(game);
            return ref != null ? ref.get() : null;
        }
    }

    /** This game's successful writes so far. */
    synchronized int writes() {
        return writes;
    }

    /** This game's deferred writes scheduled so far. */
    synchronized int deferredWrites() {
        return deferred;
    }

    /**
     * Bus entry point. Guava dispatches this because the game bus is a
     * {@code com.google.common.eventbus.EventBus} and this method is annotated
     * {@link Subscribe} with the base {@link GameEvent} type — matching every
     * event posted via {@code Game.fireEvent}. Must never throw.
     */
    @Subscribe
    public void onGameEvent(GameEvent ev) {
        synchronized (this) {
            try {
                eventsSeen++;
                if (mutates(ev)) {
                    mutationTick++;
                }
                noteEvent(ev);
                // Game over writes at once, window or not, so the final board is
                // always captured; everything else goes through the cadence.
                if (ev instanceof GameEventGameOutcome
                        || (ev != null && ev.getClass().getSimpleName().contains("GameOutcome"))) {
                    finish();
                } else {
                    maybeWrite();
                }
            } catch (Throwable t) {
                // absolutely never let a snapshot failure escape into the game loop
                handlerFailures++;
            }
        }
    }

    // ---- recent notable events (PUBLIC) ------------------------------------

    /** Append the events the seats react to; everything else is ignored.
     *  Caller holds the monitor. Never throws to the caller. */
    private void noteEvent(GameEvent ev) {
        try {
            if (ev instanceof GameEventSpellResolved r) {
                lastResolvedId = r.spell() != null ? r.spell().getId() : -1;
            } else if (ev instanceof GameEventAttackersDeclared a) {
                noteAttack(a);
            } else if (ev instanceof GameEventPlayerDamaged d) {
                noteDamage(d);
            } else if (ev instanceof GameEventSpellRemovedFromStack rm) {
                noteRemoved(rm);
            } else if (ev instanceof GameEventSpellAbilityCast c) {
                noteCast(c);
            } else if (ev instanceof GameEventZone z) {
                noteLeft(z);
            } else if (ev instanceof GameEventGameOutcome o) {
                noteGameOver(o);
            }
        } catch (RuntimeException ignored) {
            // an event we could not read is not worth a snapshot failure
            swallowedNote++;
        }
    }

    private Map<String, Object> newEvent(String kind) {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("seq", ++eventSeq);
        e.put("kind", kind);
        PhaseHandler ph = game.getPhaseHandler();
        e.put("turn", ph != null ? ph.getTurn() : 0);
        e.put("phase", ph != null && ph.getPhase() != null ? ph.getPhase().name() : "");
        return e;
    }

    private void push(Map<String, Object> e) {
        events.addLast(e);
        ringByKind.merge((String) e.get("kind"), 1, Integer::sum);
        while (events.size() > EVENT_RING) {
            Map<String, Object> dropped = events.removeFirst();
            if (((Long) dropped.get("seq")) > lastWrittenSeq) {
                ringOverruns++;   // fell off the ring before any write carried it
            }
        }
    }

    private void noteAttack(GameEventAttackersDeclared a) {
        if (a.player() == null || a.attackersMap() == null || a.attackersMap().isEmpty()) {
            return;
        }
        Map<String, Object> e = newEvent("attack");
        e.put("seat", a.player().getId());
        int power = 0;
        List<String> names = new ArrayList<>();
        java.util.LinkedHashSet<Integer> defenders = new java.util.LinkedHashSet<>();
        for (Map.Entry<forge.game.GameEntityView, CardView> en : a.attackersMap().entries()) {
            CardView cv = en.getValue();
            if (cv != null) {
                names.add(cv.getName());
                if (cv.getCurrentState() != null) {
                    power += Math.max(0, cv.getCurrentState().getPower());
                }
            }
            forge.game.GameEntityView def = en.getKey();
            if (def instanceof PlayerView pv) {
                defenders.add(pv.getId());
            } else if (def instanceof CardView dc && dc.getController() != null) {
                defenders.add(dc.getController().getId());   // a planeswalker or battle: its controller
            }
        }
        e.put("attackers", names.size());
        e.put("power", power);
        e.put("defenders", new ArrayList<>(defenders));
        e.put("names", names);
        push(e);
    }

    private void noteDamage(GameEventPlayerDamaged d) {
        if (d.target() == null || d.amount() <= 0) {
            return;
        }
        int target = d.target().getId();
        Integer source = d.source() != null && d.source().getController() != null
                ? d.source().getController().getId() : null;
        PhaseHandler ph = game.getPhaseHandler();
        int turn = ph != null ? ph.getTurn() : 0;
        String phase = ph != null && ph.getPhase() != null ? ph.getPhase().name() : "";
        Map<String, Object> last = events.peekLast();
        // combat damage from several attackers lands as several events in one
        // step: fold them into one so a 14-power swing reads as 14, not 5+9
        if (last != null && "damage".equals(last.get("kind")) && d.combat()
                && Boolean.TRUE.equals(last.get("combat"))
                && Integer.valueOf(target).equals(last.get("seat"))
                && Integer.valueOf(turn).equals(last.get("turn")) && phase.equals(last.get("phase"))) {
            last.put("amount", ((Integer) last.get("amount")) + d.amount());
            @SuppressWarnings("unchecked")
            List<Integer> from = (List<Integer>) last.get("from");
            if (source != null && !from.contains(source)) {
                from.add(source);
            }
            merged++;
            return;
        }
        Map<String, Object> e = newEvent("damage");
        e.put("seat", target);
        e.put("amount", d.amount());
        e.put("combat", d.combat());
        List<Integer> from = new ArrayList<>();
        if (source != null) {
            from.add(source);
        }
        e.put("from", from);
        push(e);
    }

    /** Whose effect is resolving right now: the activator on top of the stack, or null. */
    private Integer resolvingSeat() {
        try {
            if (!game.getStack().isEmpty()) {
                SpellAbilityStackInstance top = game.getStack().peek();
                Player p = top != null ? top.getActivatingPlayer() : null;
                return p != null ? p.getId() : null;
            }
        } catch (RuntimeException ignored) {
            // no stack access: unknown
            swallowedResolving++;
        }
        return null;
    }

    private void noteCast(GameEventSpellAbilityCast c) {
        StackItemView si = c.si();
        if (si == null || si.isAbility() || si.getActivatingPlayer() == null) {
            return;   // spells only; abilities are noise at this level
        }
        CardView host = si.getSourceCard();
        Map<String, Object> e = newEvent("cast");
        e.put("seat", si.getActivatingPlayer().getId());
        e.put("spell", host != null ? host.getName() : String.valueOf(si));
        e.put("commander", host != null && host.isCommander());
        int cmc = 0;
        try {
            if (host != null && host.getCurrentState() != null && host.getCurrentState().getManaCost() != null) {
                cmc = host.getCurrentState().getManaCost().getCMC();
            }
        } catch (RuntimeException ignored) {
            cmc = 0;
            swallowedCmc++;
        }
        e.put("cmc", cmc);
        push(e);
    }

    private void noteLeft(GameEventZone z) {
        if (z.zoneType() != ZoneType.Battlefield || z.mode() != EventValueChangeType.Removed || z.card() == null || z.player() == null) {
            return;
        }
        CardView card = z.card();
        int owner = z.player().getId();
        Integer by = resolvingSeat();
        PhaseHandler ph = game.getPhaseHandler();
        int turn = ph != null ? ph.getTurn() : 0;
        String phase = ph != null && ph.getPhase() != null ? ph.getPhase().name() : "";
        Map<String, Object> last = events.peekLast();
        // one resolution (or one state-based sweep) takes several permanents: fold them
        if (last != null && "left".equals(last.get("kind")) && Integer.valueOf(turn).equals(last.get("turn"))
                && phase.equals(last.get("phase")) && java.util.Objects.equals(by, last.get("by"))) {
            @SuppressWarnings("unchecked") List<String> cards = (List<String>) last.get("cards");
            @SuppressWarnings("unchecked") List<Integer> seats = (List<Integer>) last.get("seats");
            @SuppressWarnings("unchecked") List<String> commanders = (List<String>) last.get("commanders");
            cards.add(card.getName());
            if (!seats.contains(owner)) {
                seats.add(owner);
            }
            if (card.isCommander()) {
                commanders.add(card.getName());
            }
            last.put("n", cards.size());
            last.put("tokens", ((Integer) last.get("tokens")) + (card.isToken() ? 1 : 0));
            merged++;
            return;
        }
        Map<String, Object> e = newEvent("left");
        e.put("by", by);
        List<String> cards = new ArrayList<>(); cards.add(card.getName());
        List<Integer> seats = new ArrayList<>(); seats.add(owner);
        List<String> commanders = new ArrayList<>();
        if (card.isCommander()) {
            commanders.add(card.getName());
        }
        e.put("cards", cards);
        e.put("seats", seats);
        e.put("commanders", commanders);
        e.put("n", 1);
        e.put("tokens", card.isToken() ? 1 : 0);
        push(e);
    }

    private void noteGameOver(GameEventGameOutcome o) {
        Map<String, Object> e = newEvent("gameover");
        Integer winner = null;
        String name = o.winningPlayerName();
        if (name != null) {
            for (Player p : game.getPlayers()) {
                if (name.equals(p.getName())) {
                    winner = p.getId();
                }
            }
        }
        e.put("winner", winner);
        e.put("winnerName", name);
        push(e);
    }

    private void noteRemoved(GameEventSpellRemovedFromStack rm) {
        SpellAbilityView sa = rm.sa();
        if (sa == null || !sa.isSpell() || sa.getId() == lastResolvedId) {
            return;   // an ability, or a spell that resolved (or fizzled) and is merely leaving
        }
        Map<String, Object> e = newEvent("countered");
        CardView host = sa.getHostCard();
        e.put("spell", host != null ? host.getName() : sa.getDescription());
        e.put("seat", host != null && host.getController() != null ? host.getController().getId() : null);
        e.put("by", resolvingSeat());   // the counterspell is resolving right now: it is on top of the stack
        push(e);
    }

    // ---- cadence: fingerprint + window + one deferred write -----------------

    /** The events that change what {@link #buildSnapshot} serializes WITHOUT
     *  moving any field {@link #fingerprint} reads directly — each bumps
     *  {@link #mutationTick}, which is in the key, so the change writes at the
     *  next window instead of waiting for an unrelated one (2026-09-16: an
     *  ability that tapped a permanent and resolved inside one window left the
     *  untapped board on disk for a whole main phase). Per class, the field it
     *  protects: tapped -> {@code tapped}; counters -> {@code counters};
     *  stats/state changed (animate, clone, transform, control change — a plain P/T
     *  boost from a resolved effect fires no event and rides on the next change,
     *  static-ability layer) -> {@code power}/{@code toughness}/{@code types}/
     *  {@code name}/{@code sick}; attachment -> {@code auras}; player counters
     *  and poisoned -> {@code poison}; zone (any zone, any mode) and change-zone
     *  -> {@code graveyard}/{@code exile}/{@code commandZone}/{@code librarySize}/
     *  {@code imprinted}/{@code exiledWith} and a same-size battlefield swap;
     *  phased -> the battlefield list when one permanent phases in as another
     *  phases out. Floating mana is already read by the key ({@link #pool}),
     *  life, hand size and elimination too; card damage is not serialized. */
    private static boolean mutates(GameEvent ev) {
        return ev instanceof GameEventCardTapped
                || ev instanceof GameEventCardCounters
                || ev instanceof GameEventCardStatsChanged
                || ev instanceof GameEventCardAttachment
                || ev instanceof GameEventPlayerCounters
                || ev instanceof GameEventPlayerPoisoned
                || ev instanceof GameEventZone
                || ev instanceof GameEventCardChangeZone
                || ev instanceof GameEventCardPhased;
    }

    /** The cheap "did anything the readers care about change" key: turn, phase,
     *  active seat, game over, last ring seq, the mutation tick, the stack's
     *  instance ids, and per seat life / hand size / floating mana / battlefield
     *  size / eliminated. A tap or a counter is not READ here — it reaches the
     *  key through {@link #mutationTick} ("mostly right", cheaply). Caller holds
     *  the monitor. Never throws: an unreadable state counts as changed. */
    private String fingerprint() {
        try {
            StringBuilder sb = new StringBuilder(128);
            PhaseHandler ph = game.getPhaseHandler();
            Player active = ph != null ? ph.getPlayerTurn() : null;
            sb.append(ph != null ? ph.getTurn() : 0).append('|')
              .append(ph != null && ph.getPhase() != null ? ph.getPhase().ordinal() : -1).append('|')
              .append(active != null ? active.getId() : -1).append('|')
              .append(game.getAge() == GameStage.GameOver ? 1 : 0).append('|')
              .append(eventSeq).append('|')
              .append(mutationTick).append('|');
            MagicStack st = game.getStack();   // null while the Game constructor is still building the players
            if (st != null) {
                for (SpellAbilityStackInstance si : st) {
                    sb.append(si.getId()).append(',');
                }
            }
            sb.append('|');
            for (Player p : game.getPlayers()) {
                sb.append(p.getId()).append(':').append(p.getLife()).append(',')
                  .append(p.getCardsIn(ZoneType.Hand).size()).append(',')
                  .append(pool(p)).append(',')
                  .append(p.getCardsIn(ZoneType.Battlefield).size()).append(',')
                  .append(p.hasLost() ? 1 : 0).append(';');
            }
            return sb.toString();
        } catch (RuntimeException e) {
            swallowedFingerprint++;
            lastFailure = "fingerprint: " + e;
            return "?" + System.nanoTime();
        }
    }

    /** After an event: unchanged fingerprint = no write; changed and the window
     *  has passed (or nothing written yet, or the game is over) = write now;
     *  changed inside the window = one deferred write when it expires. Caller
     *  holds the monitor. */
    private void maybeWrite() {
        String fp = fingerprint();
        if (fp.equals(lastWrittenFp)) {
            skippedUnchanged++;
            return;
        }
        long since = System.nanoTime() - lastWriteNanos;
        if (!everWritten || finished || since >= intervalNanos) {
            writeNow(fp);
            return;
        }
        if (pending == null) {
            schedule(intervalNanos - since);
        }
    }

    private void schedule(long delayNanos) {
        try {
            pending = timer().schedule(this::flushDeferred, Math.max(1L, delayNanos), TimeUnit.NANOSECONDS);
            deferred++;
        } catch (RuntimeException rejected) {
            pending = null;   // the next event writes: its window has passed by then
            writeFailures++;
        }
    }

    /** The deferred write, on the timer thread: re-key the state and write if it
     *  still differs from the disk. A failed write (the game thread was mutating
     *  a zone under us) retries once per window, three times at most; an event
     *  meanwhile writes at once because the window has passed. */
    private void flushDeferred() {
        synchronized (this) {
            pending = null;
            if (finished) {
                return;
            }
            String fp = fingerprint();
            if (fp.equals(lastWrittenFp)) {
                skippedUnchanged++;
                return;
            }
            if (!writeNow(fp) && consecutiveFailures <= 3) {
                schedule(intervalNanos);
            }
        }
    }

    /** Build and write the snapshot now; on success the clock and the counters
     *  move. The fingerprint is taken AGAIN once the bytes exist: only if it still
     *  equals {@code fp} (the key the caller decided on, before the build) is it
     *  committed as {@link #lastWrittenFp}. The game thread mutates live zone
     *  lists without the monitor (a fail-fast iterator throws and is retried
     *  below; a non-throwing torn build does not), so a build whose key moved
     *  may hold neither the before nor the after state: it is filed under NO key
     *  ("rebuilt", counted) and, unless the game is over, one deferred write is
     *  left pending so the settled board lands at the next window. Synchronized
     *  (re-entrant from the callers above): game events can arrive from more than
     *  one thread, the deferred write runs on the timer thread, and a torn pair
     *  of writes is the one thing this must never do. Never throws. */
    private synchronized boolean writeNow(String fp) {
        try {
            byte[] bytes = MAPPER.writeValueAsBytes(buildSnapshot());
            String after = fingerprint();
            writeAtomic(outputFile, bytes);
            lastWriteNanos = System.nanoTime();
            everWritten = true;
            lastWrittenSeq = eventSeq;
            consecutiveFailures = 0;
            writes++;
            WRITES.incrementAndGet();
            if (after.equals(fp)) {
                lastWrittenFp = fp;
            } else {
                lastWrittenFp = null;   // matches nothing: the next key always differs
                rebuilt++;
                if (!finished && pending == null) {
                    schedule(intervalNanos);
                }
            }
            return true;
        } catch (Throwable t) {
            // best effort; a failed snapshot must not disturb the game
            writeFailures++;
            consecutiveFailures++;
            lastFailure = "write: " + t;
            return false;
        }
    }

    /** The first snapshot of the game, at registration: always immediate. */
    private synchronized void writeInitial() {
        writeNow(fingerprint());
    }

    private ScheduledThreadPoolExecutor timer() {
        if (timer == null) {
            ScheduledThreadPoolExecutor t = new ScheduledThreadPoolExecutor(1, r -> {
                Thread th = new Thread(r, "arena-observer-" + TIMERS.incrementAndGet());
                th.setDaemon(true);
                return th;
            });
            t.setRemoveOnCancelPolicy(true);
            t.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
            // an idle thread dies on its own, so a game that never reaches its
            // outcome event (a closed table, the test kit) leaks nothing
            t.setKeepAliveTime(30, TimeUnit.SECONDS);
            t.allowCoreThreadTimeOut(true);
            timer = t;
        }
        return timer;
    }

    /** Game over: the final board writes at once, the timer goes down, and the
     *  game's one summary line goes to stderr. Caller holds the monitor. */
    private void finish() {
        if (finished) {
            maybeWrite();   // a second outcome event: its ring entry lands, the line stays one
            return;
        }
        finished = true;
        if (pending != null) {
            pending.cancel(false);
            pending = null;
        }
        if (writeNow(fingerprint()) && lastWrittenFp == null) {
            writeNow(fingerprint());   // the final board moved under the build: once more, nothing else will
        }
        if (timer != null) {
            timer.shutdownNow();
            timer = null;
        }
        System.err.println(summary());
    }

    /** One line (E2): the game's write cadence, ring traffic and swallowed failures. */
    private String summary() {
        PhaseHandler ph = game.getPhaseHandler();
        long secs = TimeUnit.NANOSECONDS.toSeconds(System.nanoTime() - startedNanos);
        StringBuilder ring = new StringBuilder();
        for (Map.Entry<String, Integer> e : ringByKind.entrySet()) {
            ring.append(ring.length() == 0 ? "" : ", ").append(e.getKey()).append(' ').append(e.getValue());
        }
        return "[arena] observer: game over turn " + (ph != null ? ph.getTurn() : 0) + ", " + secs + " s"
                + "; writes " + writes + " (deferred " + deferred + ", skipped " + skippedUnchanged
                + ", rebuilt " + rebuilt + ", failed " + writeFailures + ", handler " + handlerFailures
                + ") from " + eventsSeen
                + " events; ring " + eventSeq + " (" + ring + "; merged " + merged + "), overruns " + ringOverruns
                + "; swallowed note " + swallowedNote + ", resolving " + swallowedResolving
                + ", cmc " + swallowedCmc + ", pool " + swallowedPool + ", fingerprint " + swallowedFingerprint
                + "; window " + TimeUnit.NANOSECONDS.toMillis(intervalNanos) + " ms"
                + (lastFailure != null ? "; last failure " + lastFailure : "");
    }

    /** A seat's floating mana (public). Read on every event for the
     *  fingerprint, so an unreadable pool is counted, not thrown. */
    private int pool(Player p) {
        try {
            return p.getManaPool() != null ? p.getManaPool().totalMana() : 0;
        } catch (RuntimeException ignored) {
            swallowedPool++;
            return 0;
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
        // getAge(), not isGameOver(): the latter is synchronized on the Game, and
        // the deferred write runs on the timer thread while the game thread may
        // be inside the synchronized setGameOver posting the outcome event — the
        // Game monitor under the observer's would invert the lock order.
        snap.put("gameOver", game.getAge() == GameStage.GameOver);

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
            s.put("pool", pool(p));   // floating mana is public
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
            // Ben (2026-09-07, "shouldn't the imprint on Isochron Scepter be
            // public knowledge?"): every public zone, not just the battlefield.
            // Graveyards and command zones are public (CR 400.2); exile is public
            // face up (CR 406.3) — a card exiled FACE DOWN stays a count.
            s.put("graveyard", names(p.getCardsIn(ZoneType.Graveyard), false));
            s.put("exile", names(p.getCardsIn(ZoneType.Exile), true));
            s.put("commandZone", names(p.getCardsIn(ZoneType.Command), false));
            seats.add(s);
        }
        snap.put("seats", seats);

        // PUBLIC stack (source names only), most-recent last — kept as-is for
        // the dashboard; "stackDetail" adds owner, kind and targets (all
        // public once an item is on the stack, CR 601.2c).
        List<String> stack = new ArrayList<>();
        List<Map<String, Object>> detail = new ArrayList<>();
        // The first mailbox seat registers the observer from inside the Game
        // constructor (createIngamePlayer), before the stack exists: the
        // registration snapshot used to NPE here and be swallowed, so the
        // dashboard's "initial snapshot" was in fact the first event's.
        MagicStack st = game.getStack();
        for (SpellAbilityStackInstance si : st != null ? st : java.util.List.<SpellAbilityStackInstance>of()) {
            SpellAbility sa = si.getSpellAbility();
            Card host = sa != null ? sa.getHostCard() : null;
            String name = host != null ? host.getName() : String.valueOf(si);
            stack.add(name);
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("kind", si.isTrigger() ? "trigger" : si.isSpell() ? "spell" : "ability");
            d.put("name", name);
            Player owner = si.getActivatingPlayer();
            d.put("owner", owner != null ? owner.getId() : null);
            List<String> targets = new ArrayList<>();
            forge.game.spellability.TargetChoices tc = si.getTargetChoices();
            if (tc != null) {
                for (Card tgt : tc.getTargetCards()) {
                    targets.add(tgt.getName());
                }
                for (Player tgt : tc.getTargetPlayers()) {
                    targets.add("seat " + tgt.getId());
                }
                for (SpellAbility tgt : tc.getTargetSpells()) {   // a counterspell's target (Gemini P2)
                    Card th = tgt.getHostCard();
                    targets.add((th != null ? th.getName() : String.valueOf(tgt)) + " (on the stack)");
                }
            }
            if (!targets.isEmpty()) {
                d.put("targets", targets);
            }
            detail.add(d);
        }
        snap.put("stack", stack);
        snap.put("stackDetail", detail);
        // "seq" (2026-09-14): the last ring entry's seq at top level, so a reader
        // can tell "new events" from "same events, new board" without walking the ring
        snap.put("seq", eventSeq);
        snap.put("events", new ArrayList<>(events));
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
        // What this permanent holds: imprinted cards (Isochron Scepter, Chrome
        // Mox) and cards it exiled (Banishing Light, Grafdigger's-Cage-style
        // "until it leaves") — public unless exiled face down.
        List<String> imprinted = names(c.getImprintedCards(), true);
        if (!imprinted.isEmpty()) {
            m.put("imprinted", imprinted);
        }
        List<String> held = names(c.getExiledCards(), true);
        if (!held.isEmpty()) {
            m.put("exiledWith", held);
        }
        return m;
    }

    /** Card names in zone order; a face-down card (when {@code hideFaceDown})
     *  is reported as such, never by name — that is hidden information. */
    static List<String> names(Iterable<Card> cards, boolean hideFaceDown) {
        List<String> out = new ArrayList<>();
        if (cards == null) {
            return out;
        }
        for (Card c : cards) {
            out.add(hideFaceDown && c.isFaceDown() ? "(face-down card)" : c.getName());
        }
        return out;
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
