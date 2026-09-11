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
import forge.game.event.EventValueChangeType;
import forge.game.event.GameEventAttackersDeclared;
import forge.game.event.GameEventGameOutcome;
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
 * disrupt the game — and writes are atomic (temp file + rename). BL-07
 * (2026-09-04): no debounce timer; every event serializes the snapshot and a
 * write happens only when the state (timestamp aside) differs from the last
 * write, so the last event of a burst is never lost and an event that changes
 * nothing visible costs no I/O. The game-outcome event always forces a write.
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

    /** BL-07 (2026-09-04): no debounce timer. Every event serializes the
     *  snapshot and writes it only when the state (timestamp aside) differs
     *  from the last write — so the last event of a burst is never lost and a
     *  22-trigger loop that changes nothing visible costs one write. */
    static final java.util.concurrent.atomic.AtomicInteger WRITES =
            new java.util.concurrent.atomic.AtomicInteger();

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
    private byte[] lastKey;  // last written snapshot, timestamp removed
    private final java.util.ArrayDeque<Map<String, Object>> events = new java.util.ArrayDeque<>();
    private long eventSeq;
    private int lastResolvedId = -1;   // TrackableObject id of the last SpellAbilityView that RESOLVED

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
            synchronized (this) {
                noteEvent(ev);
                write(force);
            }
        } catch (Throwable t) {
            // absolutely never let a snapshot failure escape into the game loop
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
        while (events.size() > EVENT_RING) {
            events.removeFirst();
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

    /** Build the snapshot; write it when it differs from the last write (or
     *  when forced). Synchronized: game events can arrive from more than one
     *  thread and a torn pair of writes is the one thing this must never do. */
    private synchronized void write(boolean force) {
        try {
            Map<String, Object> snap = buildSnapshot();
            Object ts = snap.remove("timestamp");
            byte[] key = MAPPER.writeValueAsBytes(snap);
            if (!force && lastKey != null && java.util.Arrays.equals(lastKey, key)) {
                return;
            }
            lastKey = key;
            snap.put("timestamp", ts);
            writeAtomic(outputFile, MAPPER.writeValueAsBytes(snap));
            WRITES.incrementAndGet();
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
            try {
                s.put("pool", p.getManaPool() != null ? p.getManaPool().totalMana() : 0);   // floating mana is public
            } catch (RuntimeException ignored) {
                s.put("pool", 0);
            }
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
        for (SpellAbilityStackInstance si : game.getStack()) {
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
