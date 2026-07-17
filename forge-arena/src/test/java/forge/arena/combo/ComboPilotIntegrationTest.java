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
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.prep.ComboPrep;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;

/**
 * PR-15 end-to-end: a combo-aware seat in a LIVE seeded game detects the
 * scripted Selvala+Mantle board, validates on a copy, enters the line, and
 * physically runs the loop — line_entered and line_step telemetry recorded
 * and schema-valid, with the mana genuinely floated by real activations.
 */
public class ComboPilotIntegrationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    /** Scripts the combo board at turn 3 (the PR-14 programmatic pattern — T0 §4.4b). */
    static final class BoardProbe implements GameAware {
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
            forge.game.card.Card selvala = p0.getCommanders().get(0);
            game.getAction().moveToPlay(selvala, null, null);
            forge.game.card.Card mantle = addCard(p0, "Umbral Mantle");
            forge.game.card.Card craterhoof = addCard(p0, "Craterhoof Behemoth");
            for (int i = 0; i < 6; i++) {
                addCard(p0, "Forest");
            }
            mantle.attachToEntity(selvala, null, true);
            selvala.setSickness(false);
            craterhoof.setSickness(false);
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }

        private forge.game.card.Card addCard(Player owner, String name) {
            forge.game.card.Card card = forge.game.card.Card.fromPaperCard(
                    forge.StaticData.instance().getCommonCards().getCard(name), owner);
            game.getAction().moveToPlay(card, null, null);
            return card;
        }
    }

    @Test
    public void comboAwareSeatEntersAndRunsTheMantleLineLive() throws Exception {
        // dossier from the recorded fixture (no gitignored artifacts, no network)
        Path dossier = Files.createTempDirectory("pilot-e2e");
        Map<String, Object> deckCards = Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "t",
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1, "zone", "commander"),
                        Map.of("name", "Umbral Mantle", "qty", 1, "zone", "main")),
                "unresolved", List.of());
        MAPPER.writeValue(dossier.resolve("deck-cards.json").toFile(), deckCards);
        Files.writeString(dossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"d7498c0379debdfa\",\"status\":{},\"versions\":{}}");
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            Files.write(dossier.resolve("spellbook-raw.json"), in.readAllBytes());
        }
        ComboPrep.run(dossier, (url, body) -> {
            throw new IllegalStateException("no network in tests");
        });

        Path stallDir = Files.createTempDirectory("stalls");
        System.setProperty("arena.stall.dir", stallDir.toString());
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(6, 300, 2000), sink, new BoardProbe());

        List<ArenaEvent> entered = events.stream().filter(e -> e.t().equals("line_entered")).toList();
        assertTrue("the pilot must enter the Mantle line, events: "
                + events.stream().map(ArenaEvent::t).toList(), !entered.isEmpty());
        assertEquals("527-2816", entered.get(0).fields().get("combo"));
        assertEquals("binding", entered.get(0).fields().get("attempted_via"));
        assertEquals(Integer.valueOf(0), entered.get(0).seat());

        // PR-16: the proven loop compresses — planner trace + shortcut, no stepping
        assertTrue("route_selected must be recorded",
                events.stream().anyMatch(e -> e.t().equals("route_selected")));
        List<ArenaEvent> shortcuts = events.stream()
                .filter(e -> e.t().equals("combo_shortcut")).toList();
        assertEquals("exactly one shortcut per game here", 1, shortcuts.size());
        assertEquals("527-2816", shortcuts.get(0).fields().get("combo"));

        // Gate 3.6 logging half: 10k mana + a synthetic 2-card route plan does
        // not end the game within 2 turns -> the watchdog must say so, loudly
        List<ArenaEvent> stalled = events.stream()
                .filter(e -> e.t().equals("combo_stalled")).toList();
        assertEquals("proven-infinite with no end state = combo_stalled (never silence)",
                1, stalled.size());
        assertTrue("stall dump must exist: " + stalled.get(0).fields().get("dump_path"),
                Files.exists(Path.of((String) stalled.get(0).fields().get("dump_path"))));

        // every decision event validates against the taxonomy
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.events.1.schema.json"))) {
            var schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
            for (ArenaEvent e : events) {
                var errors = schema.validate(MAPPER.readTree(MAPPER.writeValueAsString(e.toJsonMap())));
                assertTrue("invalid event: " + e.toJsonMap() + " -> " + errors, errors.isEmpty());
            }
        }
    }
}
