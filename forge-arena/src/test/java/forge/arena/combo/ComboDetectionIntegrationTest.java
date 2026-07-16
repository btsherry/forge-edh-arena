package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.ComboDetectionBridge;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.SeatSpec;
import forge.arena.prep.ComboPrep;
import forge.arena.report.ArenaEvent;

/**
 * Detection end-to-end: combos.json (from the recorded fixture) drives a
 * live seeded game; the tracked seat emits schema-valid combo_state events
 * with the commander correctly located in the command zone.
 */
public class ComboDetectionIntegrationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void liveGameEmitsDistanceTracesForTheSelvalaCombo() throws Exception {
        // build combos.json from the recorded fixture (no gitignored artifacts, no network)
        Path dir = Files.createTempDirectory("combo-detect");
        Map<String, Object> deckCards = Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "t",
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1, "zone", "commander"),
                        Map.of("name", "Umbral Mantle", "qty", 1, "zone", "main")),
                "unresolved", List.of());
        MAPPER.writeValue(dir.resolve("deck-cards.json").toFile(), deckCards);
        Files.writeString(dir.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"d7498c0379debdfa\",\"status\":{},\"versions\":{}}");
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            Files.write(dir.resolve("spellbook-raw.json"), in.readAllBytes());
        }
        ComboPrep.run(dir, (url, body) -> {
            throw new IllegalStateException("no network in tests");
        });
        List<ComboDef> defs = ComboDef.load(dir.resolve("combos.json"));
        assertEquals(3, defs.size());

        // live seeded game: Selvala deck (seat 0) vs goldfish, short cap
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        ComboDetectionBridge bridge = new ComboDetectionBridge(0, new ComboTracker(defs), events::add);
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.of(new File("decks/selvala-heart-of-the-wilds.dck")),
                        SeatSpec.goldfish(new File("decks/purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(4, 300, 2000), bridge);

        List<ArenaEvent> mantleStates = events.stream()
                .filter(e -> e.t().equals("combo_state") && "527-2816".equals(e.fields().get("combo")))
                .toList();
        assertFalse("tracker must emit distance traces", mantleStates.isEmpty());

        ArenaEvent first = mantleStates.get(0);
        assertEquals(Integer.valueOf(0), first.seat());
        int distance = (Integer) first.fields().get("distance");
        assertTrue("commander is command-zone reachable, so distance <= 1, got " + distance,
                distance <= 1);
        @SuppressWarnings("unchecked")
        List<String> where = (List<String>) first.fields().get("where");
        assertTrue("where must place Selvala in COMMAND: " + where,
                where.contains("Selvala, Heart of the Wilds:COMMAND"));

        // the templated fixture combo must never report ready
        assertTrue(events.stream()
                .filter(e -> e.t().equals("combo_ready"))
                .noneMatch(e -> "4821-5261".equals(e.fields().get("combo"))));

        // every emitted combo event validates against arena.events/1
        JsonSchema schema;
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.events.1.schema.json"))) {
            schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
        for (ArenaEvent e : events) {
            var errors = schema.validate(MAPPER.readTree(MAPPER.writeValueAsString(e.toJsonMap())));
            assertTrue("invalid event: " + e.toJsonMap() + " -> " + errors, errors.isEmpty());
        }
    }
}
