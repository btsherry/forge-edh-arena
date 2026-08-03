package forge.arena.schema;

import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;

import org.testng.annotations.DataProvider;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;

/**
 * Schemas are load-bearing (plan §11): every artifact fixture must validate,
 * and known-bad fixtures must fail loudly.
 */
public class SchemaValidationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Path SCHEMA_DIR = Path.of("schemas");

    private JsonSchema schema(String name) throws Exception {
        try (InputStream in = Files.newInputStream(SCHEMA_DIR.resolve(name))) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }

    private JsonNode fixture(String name) throws Exception {
        try (InputStream in = getClass().getResourceAsStream("/fixtures/" + name)) {
            return MAPPER.readTree(in);
        }
    }

    @DataProvider(name = "validPairs")
    public Object[][] validPairs() {
        return new Object[][] {
                { "arena.run-manifest.1.schema.json", "run-manifest-valid.json" },
                { "arena.game-record.1.schema.json", "game-record-win-valid.json" },
                { "arena.game-record.1.schema.json", "game-record-timeout-valid.json" },
                { "arena.dossier.1.schema.json", "dossier-valid.json" },
                { "arena.route-coverage.2.schema.json", "route-coverage-valid.json" },
                { "arena.tutor-priorities.1.schema.json", "tutor-priorities-valid.json" },
                { "arena.route-library.1.schema.json", "route-library-valid.json" },
                { "arena.autopsy-proposals.1.schema.json", "autopsy-proposals-valid.json" },
                // §8.2: the hand-authored program family
                { "arena.combo-program.1.schema.json", "combo-program-valid.json" },
                { "arena.engine-program.1.schema.json", "engine-program-valid.json" },
                { "arena.pairing-program.1.schema.json", "pairing-program-valid.json" },
                { "arena.program-fixture.1.schema.json", "program-fixture-valid.json" },
        };
    }

    @Test(dataProvider = "validPairs")
    public void validFixturesValidate(String schemaFile, String fixtureFile) throws Exception {
        Set<ValidationMessage> errors = schema(schemaFile).validate(fixture(fixtureFile));
        assertTrue(fixtureFile + " should validate, got: " + errors, errors.isEmpty());
    }

    @DataProvider(name = "invalidPairs")
    public Object[][] invalidPairs() {
        return new Object[][] {
                // missing seed_base + unknown rotation value
                { "arena.run-manifest.1.schema.json", "run-manifest-invalid.json" },
                // result=timeout_draw but no limiting_factor
                { "arena.game-record.1.schema.json", "game-record-timeout-invalid.json" },
                // v2 requires the deck-level layer — a v1-shaped file must not pass as v2
                { "arena.route-coverage.2.schema.json", "route-coverage-missing-deck-invalid.json" },
                // the route set is CLOSED — a classification cannot invent a route
                { "arena.route-library.1.schema.json", "route-library-invented-route-invalid.json" },
                // §8.2: program_class typo == the runtime program_class_unsupported abort
                { "arena.combo-program.1.schema.json", "combo-program-bad-class-invalid.json" },
                // an engine with no per-turn cycle is inert
                { "arena.engine-program.1.schema.json", "engine-program-no-cycle-invalid.json" },
                // a wipe with no self-shield is not a one-sided pairing
                { "arena.pairing-program.1.schema.json", "pairing-program-no-protection-invalid.json" },
                // the fixture shape is closed — an unknown zone key is a typo
                { "arena.program-fixture.1.schema.json", "program-fixture-unknown-key-invalid.json" },
        };
    }

    @Test(dataProvider = "invalidPairs")
    public void invalidFixturesFailLoudly(String schemaFile, String fixtureFile) throws Exception {
        Set<ValidationMessage> errors = schema(schemaFile).validate(fixture(fixtureFile));
        assertFalse(fixtureFile + " must NOT validate", errors.isEmpty());
    }

    @Test
    public void everyEventTaxonomyLineValidates() throws Exception {
        JsonSchema events = schema("arena.events.1.schema.json");
        List<String> lines = Files.readAllLines(
                Path.of(getClass().getResource("/fixtures/events-valid.jsonl").toURI()));
        for (String line : lines) {
            if (line.isBlank()) {
                continue;
            }
            Set<ValidationMessage> errors = events.validate(MAPPER.readTree(line));
            assertTrue("line should validate: " + line + " -> " + errors, errors.isEmpty());
        }
    }

    @Test
    public void comboIgnoredWithoutReasonFails() throws Exception {
        JsonSchema events = schema("arena.events.1.schema.json");
        JsonNode bad = MAPPER.readTree("{\"t\":\"combo_ignored\",\"turn\":7,\"seat\":0,\"combo\":\"csb-4131\"}");
        assertFalse("combo_ignored without reason must fail (silence is not a decision record)",
                events.validate(bad).isEmpty());
        JsonNode badReason = MAPPER.readTree(
                "{\"t\":\"combo_ignored\",\"turn\":7,\"seat\":0,\"combo\":\"csb-4131\",\"reason\":\"felt_like_it\"}");
        assertFalse("combo_ignored with unknown reason enum must fail",
                events.validate(badReason).isEmpty());
    }

    @Test
    public void routeRejectedRequiresFailedPredicate() throws Exception {
        JsonSchema events = schema("arena.events.1.schema.json");
        JsonNode bad = MAPPER.readTree("{\"t\":\"route_rejected\",\"turn\":7,\"seat\":0,\"route\":\"SPREAD_COMBAT\"}");
        assertFalse(events.validate(bad).isEmpty());
    }
}
