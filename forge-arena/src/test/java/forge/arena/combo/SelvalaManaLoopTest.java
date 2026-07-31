package forge.arena.combo;

import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.card.Card;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * The forked Selvala variable-yield loop through its own runner
 * (SelvalaManaLoopRunner), one gate per yield model:
 * <ul>
 *   <li>527-2645 Selvala + Staff — POWER_CONSTANT golden path (a power body
 *       seeds the constant yield), banks to the governor's target and force-
 *       casts Genesis Wave at X = library - reserve;</li>
 *   <li>527-2816 Selvala + Umbral — POWER_RAMPING: the loop opens NEGATIVE
 *       (Selvala starts small, +2/+2 per untap) and diverges, then converts;</li>
 *   <li>1355-2816 Weaver + Umbral — ENCHANTMENT_COUNT threshold regression:
 *       at E=3 the net is 0 and the runner must REFUSE the break-even loop
 *       (the dossier's "3 enchantments" prereq is wrong; E>=4 is correct).</li>
 * </ul>
 * Selvala/Weaver make "any combination of colours" — the controller pins it
 * green so the pool pays their own coloured activation and Genesis Wave's
 * {G}{G}{G}; the mass flip's optional draws are declined so it never decks out.
 */
public class SelvalaManaLoopTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    /** Fixture: optional command-zone commander into play, battlefield cards,
     * equipment attachments, hand cards, and Forests — all at turn 4. */
    static final class SelvalaBoardProbe implements GameAware {
        private final String commander;
        private final List<String> battlefield;
        private final List<String[]> attachments; // {equipName, hostName}
        private final List<String> hand;
        private final int forests;
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();
        final Map<String, Integer> libraryOut = new java.util.concurrent.ConcurrentHashMap<>();

        @Subscribe
        public void onZone(forge.game.event.GameEventCardChangeZone e) {
            if (e.from() != null && e.to() != null
                    && String.valueOf(e.from().zoneType()).equals("Library")) {
                libraryOut.merge(String.valueOf(e.to().zoneType()), 1, Integer::sum);
            }
        }

        SelvalaBoardProbe(String commander, List<String> battlefield,
                List<String[]> attachments, List<String> hand, int forests) {
            this.commander = commander;
            this.battlefield = battlefield;
            this.attachments = attachments;
            this.hand = hand;
            this.forests = forests;
        }

        @Override
        public void onGameCreated(Game game) {
            this.game = game;
        }

        @Subscribe
        public void onTurn(GameEventTurnBegan event) {
            if (event.turnNumber() < 4 || !applied.compareAndSet(false, true)) {
                return;
            }
            Player p0 = game.getPlayers().get(0);
            game.getTriggerHandler().setSuppressAllTriggers(true);
            Map<String, Card> byName = new HashMap<>();
            if (commander != null && !p0.getCommanders().isEmpty()) {
                Card c = p0.getCommanders().get(0);
                Card moved = game.getAction().moveToPlay(c, null, null);
                moved.setSickness(false);
                byName.put(moved.getName(), moved);
            }
            for (String name : battlefield) {
                Card c = game.getAction().moveToPlay(card(name, p0), null, null);
                c.setSickness(false);
                byName.put(name, c);
            }
            for (String name : hand) {
                game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
            }
            for (String[] a : attachments) {
                Card equip = byName.get(a[0]);
                Card host = byName.get(a[1]);
                if (equip != null && host != null) {
                    equip.attachToEntity(host, null, true);
                }
            }
            for (int i = 0; i < forests; i++) {
                game.getAction().moveToPlay(card("Forest", p0), null, null);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }

        private Card card(String name, Player owner) {
            return Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard(name), owner);
        }
    }

    private List<ArenaEvent> runGate(String label, SelvalaBoardProbe probe) throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("selvala-" + label + "-stalls").toString());
        Path dossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        List<ArenaEvent> events =
                java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(
                            new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/giada-font-of-hope.dck"))),
                42L, new ArenaLimits(14, 400, 4000), sink, probe);
        System.out.println("[" + label + "] result=" + result.type()
                + " winnerSeat=" + result.winnerSeat() + " libraryOut=" + probe.libraryOut);
        java.util.Set<String> keep = java.util.Set.of("governor_plan", "outlet_fired",
                "program_complete", "program_abort", "program_deferred");
        for (ArenaEvent e : events) {
            if (keep.contains(e.t())) {
                System.out.println("[" + label + "-ev] T" + e.turn() + " " + e.t()
                        + " " + e.fields());
            }
        }
        return events;
    }

    /** Gate 1 — POWER_CONSTANT golden path (Staff), banks then flips the deck. */
    @Test
    public void goldenPathStaffLoopBanksAndFiresGenesisWave() throws Exception {
        List<ArenaEvent> events = runGate("gate1", new SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Staff of Domination", "Ghalta, Primal Hunger"),
                List.of(),
                List.of("Genesis Wave"),
                15));
        assertConverts(events, "527-2645");
    }

    /** Gate 2 — POWER_RAMPING (Umbral): opens negative, diverges, converts. */
    @Test
    public void rampingUmbralLoopDivergesAndFiresGenesisWave() throws Exception {
        List<ArenaEvent> events = runGate("gate2", new SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Umbral Mantle"),
                List.<String[]>of(new String[] {"Umbral Mantle", "Selvala, Heart of the Wilds"}),
                List.of("Genesis Wave"),
                8));
        var plan = firstPlan(events, "527-2816");
        assertTrue("ramping plan must be POWER_RAMPING, got " + plan,
                "POWER_RAMPING".equals(String.valueOf(plan.get("yield_model"))));
        assertConverts(events, "527-2816");
    }

    /** Gate 3 — ENCHANTMENT_COUNT at E=3: the runner must REFUSE (net 0). */
    @Test
    public void weaverAtThreeEnchantmentsRefusesZeroYield() throws Exception {
        List<ArenaEvent> events = runGate("gate3", new SelvalaBoardProbe(
                null,
                List.of("Sanctum Weaver", "Umbral Mantle", "Sylvan Library", "Ghostly Prison"),
                List.<String[]>of(new String[] {"Umbral Mantle", "Sanctum Weaver"}),
                List.of(),
                8));
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort")
                        && "1355-2816".equals(String.valueOf(e.fields().get("combo"))))
                .map(e -> String.valueOf(e.fields().get("reason"))).toList();
        assertTrue("the E=3 loop must abort zero_yield, aborts=" + aborts,
                aborts.stream().anyMatch(r -> r.contains("zero_yield")));
    }

    // --- SWEEP: the remaining four tap-untap pairings ---------------------
    // Each proves a DIFFERENT producer/untapper shape banks through the forked
    // runner and force-casts Genesis Wave, exercising the untap FIXPOINT that
    // readies a board stock pre-tapped (the pieces enter tapped/sick in a real
    // game). Forests fund the untap costs during the fixpoint (the producer is
    // tapped, so the pool is empty until the first normal tap).

    /** Sweep A — Sanctum Weaver + Staff of Domination (ENCHANTMENT_COUNT).
     * Weaver taps for one mana per enchantment; six enchantments -> net +2. */
    @Test
    public void weaverStaffEnchantmentLoopBanksAndFires() throws Exception {
        List<ArenaEvent> events = runGate("sweepA-weaver-staff", new SelvalaBoardProbe(
                null,
                List.of("Sanctum Weaver", "Staff of Domination",
                        "Sylvan Library", "Ghostly Prison", "Propaganda",
                        "Rhystic Study", "Mystic Remora", "Sterling Grove"),
                List.of(),
                List.of("Genesis Wave"),
                10));
        assertConverts(events, "1355-2645");
    }

    /** Sweep B — Fanatic of Rhonas + Umbral Mantle (CONSTANT GGGG).
     * Ghalta supplies the Ferocious power-4 body; Umbral's {3}{Q} self-untaps. */
    @Test
    public void fanaticUmbralConstantLoopBanksAndFires() throws Exception {
        List<ArenaEvent> events = runGate("sweepB-fanatic-umbral", new SelvalaBoardProbe(
                null,
                List.of("Fanatic of Rhonas", "Umbral Mantle", "Ghalta, Primal Hunger"),
                List.<String[]>of(new String[] {"Umbral Mantle", "Fanatic of Rhonas"}),
                List.of("Genesis Wave"),
                10));
        assertConverts(events, "2816-5711");
    }

    /** Sweep C — Voyaging Satyr + Gaea's Cradle + Staff (CREATURE_COUNT, the
     * DEEP 3-link chain: Satyr untaps Cradle, Staff untaps Satyr + itself).
     * Six creatures -> Cradle yields 6, net +2; the fixpoint must ready a
     * three-piece stock-tapped chain. */
    @Test
    public void satyrCradleStaffCreatureLoopBanksAndFires() throws Exception {
        List<ArenaEvent> events = runGate("sweepC-satyr-cradle-staff", new SelvalaBoardProbe(
                null,
                List.of("Gaea's Cradle", "Staff of Domination", "Voyaging Satyr",
                        "Llanowar Elves", "Elvish Mystic", "Birds of Paradise",
                        "Fyndhorn Elves", "Arbor Elf"),
                List.of(),
                List.of("Genesis Wave"),
                8));
        assertConverts(events, "2026-2404-2645");
    }

    /** Sweep D — Voyaging Satyr + Gaea's Cradle + Umbral Mantle (CREATURE_COUNT,
     * Umbral self-untaps Satyr). Five creatures -> net +2. */
    @Test
    public void satyrCradleUmbralCreatureLoopBanksAndFires() throws Exception {
        List<ArenaEvent> events = runGate("sweepD-satyr-cradle-umbral", new SelvalaBoardProbe(
                null,
                List.of("Gaea's Cradle", "Umbral Mantle", "Voyaging Satyr",
                        "Llanowar Elves", "Elvish Mystic", "Birds of Paradise",
                        "Fyndhorn Elves"),
                List.<String[]>of(new String[] {"Umbral Mantle", "Voyaging Satyr"}),
                List.of("Genesis Wave"),
                8));
        assertConverts(events, "2026-2404-2816");
    }

    // --- ASSEMBLE-AND-DEPLOY --------------------------------------------
    // The win-rate frontier: pieces that never assemble organically. Leave
    // Selvala in the COMMAND zone and Umbral Mantle in HAND (as in a real game
    // pre-assembly), give mana, and prove the pilot PROACTIVELY casts the
    // commander + the equipment and ATTACHES it, so the combo comes online
    // instead of waiting on stock AI (which produced 14x piece_lost in the
    // smoke batch).

    /** Deploy from hand+command: cast Selvala, cast Umbral, equip, then the
     * 527-2816 combo assembles and the runner plans it. */
    @Test
    public void deployAssemblesUmbralComboFromHandAndCommand() throws Exception {
        List<ArenaEvent> events = runGate("deploy-umbral", new SelvalaBoardProbe(
                null, // leave Selvala in the command zone
                List.of(),
                List.of(),
                List.of("Umbral Mantle", "Genesis Wave"),
                14));
        // the deploy phase fired the right actions
        var deploys = events.stream()
                .filter(e -> e.t().equals("line_step")
                        && "PROGRAM_DEPLOY".equals(String.valueOf(e.fields().get("stage"))))
                .map(e -> String.valueOf(e.fields().get("deploy")) + ":"
                        + String.valueOf(e.fields().get("card"))).toList();
        System.out.println("[deploy-umbral] deploys=" + deploys);
        assertTrue("must CAST Selvala from the command zone, deploys=" + deploys,
                deploys.contains("cast:Selvala, Heart of the Wilds"));
        assertTrue("must CAST Umbral Mantle from hand, deploys=" + deploys,
                deploys.contains("cast:Umbral Mantle"));
        assertTrue("must EQUIP Umbral Mantle (attach to Selvala), deploys=" + deploys,
                deploys.contains("equip:Umbral Mantle"));
        // and the combo actually assembled -> the runner planned it
        boolean planned = events.stream().anyMatch(e -> e.t().equals("governor_plan")
                && "527-2816".equals(String.valueOf(e.fields().get("combo"))));
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        assertTrue("deployed combo 527-2816 must ASSEMBLE and be planned, aborts=" + aborts,
                planned);
    }

    // --- GOD WIN-PLAN (Rhonas/Nylea flood-pump pairing) -----------------

    /** With infinite mana + Rhonas + Nylea + Concordant Crossroads, the runner
     * digs creatures, casts them (hasty), pumps the board with Rhonas (+2/+0
     * trample) and alpha-strikes lethal — no Genesis Wave. This is a two-card
     * "pairing" (powerful play), the first executed as a first-class win-plan. */
    @Test
    public void rhonasNyleaFloodPumpWinsWithoutGenesisWave() throws Exception {
        List<ArenaEvent> events = runGate("god-winplan", new SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Staff of Domination", "Ghalta, Primal Hunger",
                        "Rhonas the Indomitable", "Nylea, Keen-Eyed",
                        "Concordant Crossroads", "Llanowar Elves", "Elvish Mystic"),
                List.of(),
                List.of(),
                40));
        // with both Gods up, whichever closes first fires: Nylea's flood can be
        // lethal on its own before Rhonas needs to pump, so accept either outlet
        java.util.Set<String> godOutlets = java.util.Set.of(
                "Rhonas the Indomitable", "Nylea, Keen-Eyed", "God win-plan");
        boolean godFired = events.stream().anyMatch(e -> e.t().equals("outlet_fired")
                && godOutlets.contains(String.valueOf(e.fields().get("outlet"))));
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        System.out.println("[god-winplan] godFired=" + godFired + " aborts=" + aborts);
        assertTrue("the Rhonas/Nylea win-plan must fire as the outlet, aborts=" + aborts,
                godFired);
    }

    /** Rhonas ALONE (no Nylea): pump the existing board +2/+0 trample to lethal. */
    @Test
    public void rhonasAlonePumpsExistingBoardToLethal() throws Exception {
        List<ArenaEvent> events = runGate("god-rhonas", new SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Staff of Domination", "Ghalta, Primal Hunger",
                        "Rhonas the Indomitable", "Concordant Crossroads",
                        "Llanowar Elves", "Elvish Mystic", "Birds of Paradise"),
                List.of(), List.of(), 40));
        boolean fired = events.stream().anyMatch(e -> e.t().equals("outlet_fired")
                && "Rhonas the Indomitable".equals(String.valueOf(e.fields().get("outlet"))));
        List<String> aborts = events.stream().filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        System.out.println("[god-rhonas] fired=" + fired + " aborts=" + aborts);
        assertTrue("Rhonas alone must pump the board to lethal, aborts=" + aborts, fired);
    }

    /** Nylea ALONE (no Rhonas): dig the deck's creatures, cast them wide (hasty),
     * and swing lethal — no pump. Proves each God closes independently. */
    @Test
    public void nyleaAloneFloodsWideAndWins() throws Exception {
        List<ArenaEvent> events = runGate("god-nylea", new SelvalaBoardProbe(
                "Selvala, Heart of the Wilds",
                List.of("Staff of Domination", "Ghalta, Primal Hunger",
                        "Nylea, Keen-Eyed", "Concordant Crossroads"),
                List.of(), List.of(), 40));
        boolean fired = events.stream().anyMatch(e -> e.t().equals("outlet_fired")
                && "Nylea, Keen-Eyed".equals(String.valueOf(e.fields().get("outlet"))));
        List<String> aborts = events.stream().filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        System.out.println("[god-nylea] fired=" + fired + " aborts=" + aborts);
        assertTrue("Nylea alone must flood a wide board and fire, aborts=" + aborts, fired);
    }

    // --- assertion helpers ----------------------------------------------

    private Map<String, Object> firstPlan(List<ArenaEvent> events, String combo) {
        return events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && combo.equals(String.valueOf(e.fields().get("combo"))))
                .map(ArenaEvent::fields).findFirst()
                .orElseThrow(() -> new AssertionError("no governor_plan for " + combo));
    }

    /** Assert the loop banked and Genesis Wave flipped the majority of the deck. */
    private void assertConverts(List<ArenaEvent> events, String combo) {
        var plans = events.stream()
                .filter(e -> e.t().equals("governor_plan")
                        && combo.equals(String.valueOf(e.fields().get("combo")))).toList();
        // outlet_drill carries no combo field; each gate is its own game, so
        // every mana_pair drill in this run belongs to this combo
        long pairs = events.stream()
                .filter(e -> e.t().equals("outlet_drill")
                        && "mana_pair".equals(String.valueOf(e.fields().get("kind")))).count();
        var fired = events.stream()
                .filter(e -> e.t().equals("outlet_fired")
                        && combo.equals(String.valueOf(e.fields().get("combo")))).toList();
        List<String> aborts = events.stream()
                .filter(e -> e.t().equals("program_abort"))
                .map(e -> String.valueOf(e.fields())).toList();
        assertTrue("governor must plan the bank for " + combo + ", aborts=" + aborts,
                !plans.isEmpty());
        assertTrue("the variable-yield loop must run MEASURED cycles (pairs="
                + pairs + ") aborts=" + aborts, pairs >= 5);
        assertTrue("Genesis Wave must force-cast and flip the board (fired="
                + fired.size() + ") aborts=" + aborts, !fired.isEmpty());
        var f = fired.get(0).fields();
        int before = ((Number) f.get("permanents_before")).intValue();
        int after = ((Number) f.get("permanents_after")).intValue();
        int libAfter = ((Number) f.get("library_after")).intValue();
        assertTrue("Genesis Wave must flip the MAJORITY of the library (before="
                + before + " after=" + after + ")", after - before >= 20);
        assertTrue("must LEAVE the reserve, not deck out (library_after="
                + libAfter + ")", libAfter >= 5);
    }
}
