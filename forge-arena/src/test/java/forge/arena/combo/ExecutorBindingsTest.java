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
        // A bare count pins nothing worth protecting — it breaks on every
        // addition and says nothing about whether the library is correct. It
        // is a FLOOR instead: bindings may be added freely, and losing one
        // still fails loudly.
        // Floor updated deliberately, THREE times, under the one-path rule:
        // PR-mu removed 4821-5261 (compiled as the float_then_copy mana-loop
        // program — the deck's primary line).
        // PR (cast_recur) removed 411-3101 (SelfBounceRecastLoop -> compiled as
        // the Ignus self_recast program, one-path rule).
        // PR-lambda removed 4131-5149 (compiled as the mana-loop program)
        // and 2585-5149 (Grim+PA — TapForManaUntapLoop ignores cost_reducer,
        // PA never attaches to Grim, so the binding entered and
        // validation-aborted EVERY turn, burning a window; unbound-by-design
        // backlog until compiled as a mana_loop program).
        assertTrue("binding library shrank: " + bindings.size(), bindings.size() >= 26);
        // PR-61: the cast-bounce family now covers Hullbreaker Horror as
        // well as Tidespout Tyrant. Both are "whenever you cast a spell,
        // return a permanent to its owner's hand" plus a rock that produces
        // more than it costs to recast — one archetype, five more of Urza's
        // eleven unbound combos, and no new code.
        for (String id : java.util.List.of("542-5034", "542-2364", "542-2585",
                "513-5034--46", "513-2364--47", "513-3682", "542-3682", "542-4009")) {
            ExecutorBindings.Binding tidespout = bindings.forCombo(id).orElseThrow();
            assertEquals(CastBounceManaLoop.ARCHETYPE, ExecutorBindings.executorFor(tidespout)
                    .orElseThrow().archetype());
        }
        // Sol Ring nets +1 per cycle ({C}{C} for a {1} recast); a rock that
        // only broke even would be refused before any line fired
        CastBounceManaLoop solRing = (CastBounceManaLoop) ExecutorBindings.executorFor(
                bindings.forCombo("542-5034").orElseThrow()).orElseThrow();
        assertTrue("Sol Ring nets +1", solRing.mathProfitable().isProfitable());
        assertEquals(PairedPlay.ARCHETYPE, ExecutorBindings.executorFor(
                bindings.forCombo("pp-doomskar-maneuver").orElseThrow()).orElseThrow().archetype());
        for (String id : java.util.List.of("147-1235", "147-6785")) {
            assertEquals(SpellCopyLoop.ARCHETYPE, ExecutorBindings.executorFor(
                    bindings.forCombo(id).orElseThrow()).orElseThrow().archetype());
        }

        // PR-27a: every Sabertooth-family binding builds its executor, and
        // the Crossroads variant reproduces the proposal's arithmetic
        for (String id : java.util.List.of("215-527-876", "215-527-1322",
                "215-527-713", "215-1322-1355")) {
            ExecutorBindings.Binding b = bindings.forCombo(id).orElseThrow();
            assertEquals(BounceRecastLoop.ARCHETYPE,
                    ExecutorBindings.executorFor(b).orElseThrow().archetype());
        }
        BounceRecastLoop crossroads = (BounceRecastLoop) ExecutorBindings.executorFor(
                bindings.forCombo("215-527-1322").orElseThrow()).orElseThrow();
        assertTrue("X=7 nets +1", crossroads.mathProfitable(7, 0).isProfitable());
        assertTrue("X=6 breaks even — refused",
                !crossroads.mathProfitable(6, 0).isProfitable());

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
