package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

/** The hand-authored binding library loads, validates, and builds executors. */
public class ExecutorBindingsTest {

    @Test
    public void shippedBindingsFileValidatesAndBuildsTheSelvalaExecutors() throws Exception {
        Path file = ExecutorBindings.defaultPath();
        assertTrue("bindings file missing: " + file, Files.exists(file));

        // schema-valid (the Gate 3.5 output contract starts here)
        try (InputStream in = Files.newInputStream(
                Path.of("schemas", "arena.executor-bindings.1.schema.json"))) {
            var errors = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
                    .getSchema(in).validate(new ObjectMapper().readTree(file.toFile()));
            assertTrue("schema errors: " + errors, errors.isEmpty());
        }

        ExecutorBindings bindings = ExecutorBindings.load(file);
        assertEquals(2, bindings.size());

        // Mantle line: untap ability hosted on the ENGINE (granted by equipment)
        ExecutorBindings.Binding mantle = bindings.forCombo("527-2816").orElseThrow();
        LineExecutor executor = ExecutorBindings.executorFor(mantle).orElseThrow();
        assertEquals(TapForManaUntapLoop.ARCHETYPE, executor.archetype());
        assertEquals("MAIN1", executor.entryPhase());
        // the binding's math must reproduce the plan's Selvala numbers
        TapForManaUntapLoop loop = (TapForManaUntapLoop) executor;
        assertTrue(loop.mathProfitable(4, 0, 0).isProfitable());

        // Staff line: staged, validated at math level until targets are scriptable
        ExecutorBindings.Binding staff = bindings.forCombo("527-2645").orElseThrow();
        assertEquals(java.util.List.of("MANA_LOOP", "DRAW_LOOP", "DEPLOY_WIN"), staff.stages());
        TapForManaUntapLoop staffLoop =
                (TapForManaUntapLoop) ExecutorBindings.executorFor(staff).orElseThrow();
        assertTrue(!staffLoop.mathProfitable(5, 0, 0).isProfitable());
    }

    @Test
    public void unknownArchetypeStaysDetectionOnlyNeverCrashes() throws Exception {
        Path dir = Files.createTempDirectory("bindings");
        Files.writeString(dir.resolve("executor-bindings.json"), """
                {"schema": "arena.executor-bindings/1",
                 "bindings": [{"combo_id": "c1", "archetype": "SomeFutureArchetype",
                               "params": {"x": "y"}}],
                 "unbound": ["c9"]}""");
        ExecutorBindings bindings = ExecutorBindings.load(dir.resolve("executor-bindings.json"));
        ExecutorBindings.Binding binding = bindings.forCombo("c1").orElseThrow();
        Optional<LineExecutor> executor = ExecutorBindings.executorFor(binding);
        assertTrue("unknown archetype must yield empty, not throw", executor.isEmpty());
        assertEquals(java.util.List.of("c9"), bindings.unbound());
    }

    @Test
    public void missingFileIsEmptyMalformedFailsLoudly() throws Exception {
        assertEquals(0, ExecutorBindings.load(Path.of("/nonexistent/bindings.json")).size());
        Path dir = Files.createTempDirectory("bindings-bad");
        Files.writeString(dir.resolve("executor-bindings.json"), "{\"nope\": true}");
        try {
            ExecutorBindings.load(dir.resolve("executor-bindings.json"));
            throw new AssertionError("malformed bindings must fail loudly");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("malformed"));
        }
    }
}
