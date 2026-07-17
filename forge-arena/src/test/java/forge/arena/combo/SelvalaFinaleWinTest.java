package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.prep.ComboPrep;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * The PR-25 golden: batch game 78 recreated — and this time it must WIN.
 * At the fire the seat holds ONLY Finale of Devastation (no Craterhoof in
 * hand, no static haste anywhere), the obs-100 shape where stock squandered
 * Finale at a pool-blind small X. The pilot must: select SPREAD_COMBAT via
 * the haste-v2 oneshot-in-hand predicate, keep the priority (deploy-first),
 * cast Finale with the scripted X off the injected pool, have the tutor
 * hook fetch the payoff out of the library, and close with the forced
 * split alpha. A win is simultaneously the proof of the X plumbing: a
 * small X grants no haste and no pump, and the game cannot end in time.
 */
public class SelvalaFinaleWinTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    /** Turn 3: Mantle + Finale to hand (nothing else), mana on board. */
    static final class HandProbe implements GameAware {
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        @Override
        public void onGameCreated(Game game) {
            this.game = game;
        }

        @Subscribe
        public void onTurn(GameEventTurnBegan event) {
            if (event.turnNumber() < 3 || !applied.compareAndSet(false, true)) {
                return;
            }
            Player p0 = game.getPlayers().get(0);
            game.getTriggerHandler().setSuppressAllTriggers(true);
            for (String name : List.of("Umbral Mantle", "Finale of Devastation")) {
                forge.game.card.Card card = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard(name), p0);
                game.getAction().moveTo(ZoneType.Hand, card, null, null);
            }
            // 8 forests — MORE than assembly needs (Selvala 3 + Mantle 3):
            // stock could afford Finale in the pre-fire windows between the
            // sickness-refused first proof and the refire, and in PR-25 this
            // golden needed exactly 6 to close that hole. The PR-26 veto now
            // reserves one-shot payoffs while a bound combo exists, so the
            // surplus mana proves the veto live alongside the conversion chain
            for (int i = 0; i < 8; i++) {
                forge.game.card.Card forest = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard("Forest"), p0);
                game.getAction().moveToPlay(forest, null, null);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }
    }

    @Test
    public void finaleAloneConvertsTheProvenLoop() throws Exception {
        Path dossier = Files.createTempDirectory("finale-win");
        // real oracle text: PayoffRules must class Finale haste_oneshot +
        // mass_pump so SPREAD_COMBAT is an expressible route for the planner
        MAPPER.writeValue(dossier.resolve("deck-cards.json").toFile(), Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "t",
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1,
                                "zone", "commander",
                                "type_line", "Legendary Creature — Elf Scout",
                                "oracle_text", "Whenever another creature enters, its controller"
                                        + " may draw a card if its power is greater than each"
                                        + " other creature's power.\n{T}: Add X {G}, where X is"
                                        + " the greatest power among creatures you control."),
                        Map.of("name", "Umbral Mantle", "qty", 1, "zone", "main",
                                "type_line", "Artifact — Equipment",
                                "oracle_text", "Equipped creature has \"{3}, {Q}: Untap this"
                                        + " creature and it gets +2/+2 until end of turn.\""),
                        Map.of("name", "Finale of Devastation", "qty", 1, "zone", "main",
                                "type_line", "Sorcery",
                                "oracle_text", "Search your library and/or graveyard for a"
                                        + " creature card with mana value X or less and put it"
                                        + " onto the battlefield. If you search your library"
                                        + " this way, shuffle. If X is 10 or more, creatures"
                                        + " you control get +X/+X and gain haste until end of"
                                        + " turn."),
                        Map.of("name", "Craterhoof Behemoth", "qty", 1, "zone", "main",
                                "type_line", "Creature — Beast",
                                "oracle_text", "Haste\nWhen Craterhoof Behemoth enters,"
                                        + " creatures you control gain trample and get +X/+X"
                                        + " until end of turn, where X is the number of"
                                        + " creatures you control.")),
                "unresolved", List.of()));
        Files.writeString(dossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"d7498c0379debdfa\",\"status\":{},\"versions\":{}}");
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            Files.write(dossier.resolve("spellbook-raw.json"), in.readAllBytes());
        }
        ComboPrep.run(dossier, (url, body) -> {
            throw new IllegalStateException("no network in tests");
        });

        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("finale-stalls").toString());
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(12, 300, 2000), sink, new HandProbe());

        assertEquals("exactly one shortcut", 1,
                events.stream().filter(e -> e.t().equals("combo_shortcut")).count());

        // the route came from the haste-v2 predicate: Finale in hand
        ArenaEvent spread = events.stream()
                .filter(e -> e.t().equals("route_selected")
                        && "SPREAD_COMBAT".equals(e.fields().get("route")))
                .findFirst().orElseThrow(() -> new AssertionError(
                        "SPREAD_COMBAT never selected; events: "
                                + events.stream().map(ArenaEvent::t).toList()));
        @SuppressWarnings("unchecked")
        Map<String, Object> predicates = (Map<String, Object>) spread.fields().get("predicates");
        assertEquals("oneshot_in_hand", predicates.get("haste_kind"));

        // deploy-first: the pilot spent the pool itself (Finale, scripted X)
        assertTrue("a DEPLOY cast must run in the fire priority",
                events.stream().anyMatch(e -> e.t().equals("line_step")
                        && "DEPLOY".equals(e.fields().get("stage"))));

        // the forced alpha closed it — game 78's missing ending
        assertTrue("the pilot must steer at least one combat",
                events.stream().anyMatch(e -> e.t().equals("line_step")
                        && "FORCED_ATTACK".equals(e.fields().get("stage"))));
        assertEquals("Selvala must WIN (got " + result.type() + ", "
                + result.winCondition() + ")", ArenaGameResult.ResultType.WIN, result.type());
        assertEquals(0, result.winnerSeat());
    }
}
