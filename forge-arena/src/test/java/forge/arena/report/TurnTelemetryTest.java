package forge.arena.report;

import static org.testng.AssertJUnit.assertEquals;
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
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameEventBridge;
import forge.arena.engine.SeatSpec;

/**
 * PR-22 play-pattern telemetry, live: every turn of a real game emits one
 * schema-valid turn_state (where things stand) and one turn_summary (what
 * happened), the flow counters are internally consistent with the raw
 * events, and land plays are no longer mislabeled as spells.
 */
public class TurnTelemetryTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void everyTurnCarriesStateAndSummaryAndTheyAddUp() throws Exception {
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        GameEventBridge bridge = new GameEventBridge(events::add);
        EngineFacade.playCommanderGame(
                List.of(SeatSpec.of(new File("decks/selvala-heart-of-the-wilds.dck")),
                        SeatSpec.goldfish(new File("decks/purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(6, 300, 2000), bridge);

        long turns = events.stream().filter(e -> e.t().equals("turn_begin")).count();
        long states = events.stream().filter(e -> e.t().equals("turn_state")).count();
        long summaries = events.stream().filter(e -> e.t().equals("turn_summary")).count();
        assertTrue("game must run some turns", turns >= 4);
        assertEquals("one state per turn", turns, states);
        assertTrue("one summary per completed turn (the capped turn may not end)",
                summaries >= turns - 1 && summaries <= turns);

        // state sanity: turn-1 snapshot shows 40 life and full-ish libraries
        ArenaEvent first = events.stream().filter(e -> e.t().equals("turn_state"))
                .findFirst().orElseThrow();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> seats = (List<Map<String, Object>>) first.fields().get("seats");
        assertEquals(2, seats.size());
        for (Map<String, Object> seat : seats) {
            assertEquals(40, seat.get("life"));
            assertTrue((int) seat.get("library") > 80);
            assertTrue((int) seat.get("hand") >= 7 - 2); // mulligans happen
        }

        // flow consistency: summed drawn/spells match the raw events
        int drawnFromSummaries = 0;
        int spellsFromSummaries = 0;
        for (ArenaEvent e : events) {
            if (!e.t().equals("turn_summary")) {
                continue;
            }
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows = (List<Map<String, Object>>) e.fields().get("seats");
            for (Map<String, Object> row : rows) {
                if ((Integer) row.get("seat") == 0) {
                    drawnFromSummaries += (int) row.get("drawn");
                    spellsFromSummaries += (int) row.get("spells");
                }
            }
        }
        long drawZoneChanges = events.stream().filter(e -> e.t().equals("zone_change")
                && Integer.valueOf(0).equals(e.seat())
                && "Library".equals(e.fields().get("from"))
                && "Hand".equals(e.fields().get("to"))).count();
        assertTrue("summaries must reflect real draws (summaries " + drawnFromSummaries
                + " vs zone events " + drawZoneChanges + ")",
                drawnFromSummaries > 0 && drawnFromSummaries <= drawZoneChanges);
        long spellCasts = events.stream().filter(e -> e.t().equals("spell_cast")
                && Integer.valueOf(0).equals(e.seat())).count();
        // the capped final turn never emits its summary, so <= not ==
        assertTrue("spell counters (" + spellsFromSummaries + ") must not exceed raw casts ("
                + spellCasts + ")", spellsFromSummaries <= spellCasts);

        // land plays are their own event type now (previously mislabeled spell_cast)
        assertTrue(events.stream().anyMatch(e -> e.t().equals("land_played")));

        // every event validates against the widened taxonomy
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.events.1.schema.json"))) {
            JsonSchema schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
                    .getSchema(in);
            for (ArenaEvent e : events) {
                var errors = schema.validate(MAPPER.readTree(MAPPER.writeValueAsString(e.toJsonMap())));
                assertTrue("invalid event: " + e.toJsonMap() + " -> " + errors, errors.isEmpty());
            }
        }
    }
}
