package forge.arena.harness;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;

import forge.arena.engine.ArenaLimits;
import forge.arena.engine.SeatSpec;

/**
 * The Phase-1 invariant (plan §8, keep green forever): same seed ⇒
 * byte-identical event log, twice. Also validates the runner's GameRecord
 * against arena.game-record/1 and checks rotation is applied.
 */
public class SeedDeterminismTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private List<SeatSpec> pod;

    @BeforeClass
    public void bootstrap() {
        forge.arena.bootstrap.ArenaBootstrap.initialize(new File("..", "forge-gui"));
        pod = List.of(
                SeatSpec.of(new File("decks/giada-font-of-hope.dck")),
                SeatSpec.of(new File("decks/purphoros-god-of-the-forge.dck")),
                SeatSpec.of(new File("decks/selvala-heart-of-the-wilds.dck")),
                SeatSpec.of(new File("decks/urza-lord-high-artificer.dck")));
    }

    @Test
    public void sameSeedProducesByteIdenticalEventLogsTwice() throws Exception {
        ArenaLimits limits = new ArenaLimits(4, 300, 0);

        Path dirA = Files.createTempDirectory("arena-det-a");
        GameRecord recA = ArenaRunner.runOne(new RunConfig(42L, pod, limits, dirA, null), 3);
        String hashA = sha256(dirA.resolve("events").resolve("000003.jsonl"));

        Path dirB = Files.createTempDirectory("arena-det-b");
        GameRecord recB = ArenaRunner.runOne(new RunConfig(42L, pod, limits, dirB, null), 3);
        String hashB = sha256(dirB.resolve("events").resolve("000003.jsonl"));

        assertEquals("same seed must replay to a byte-identical event log", hashA, hashB);

        // records match too, modulo wall-clock duration
        Map<String, Object> a = new HashMap<>(recA.toJsonMap());
        Map<String, Object> b = new HashMap<>(recB.toJsonMap());
        a.remove("duration_ms");
        b.remove("duration_ms");
        assertEquals(a, b);

        // rotation applied: game 3 with 4 decks shifts by 3 — urza leads
        assertEquals("urza-lord-high-artificer", recA.seats().get(0));

        // the record itself is schema-valid
        JsonSchema schema;
        try (InputStream in = Files.newInputStream(Path.of("schemas", "arena.game-record.1.schema.json"))) {
            schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
        var errors = schema.validate(MAPPER.readTree(MAPPER.writeValueAsString(recA.toJsonMap())));
        assertTrue("game record must validate: " + errors, errors.isEmpty());

        // a different game index diverges (different seed, different rotation)
        Path dirC = Files.createTempDirectory("arena-det-c");
        ArenaRunner.runOne(new RunConfig(42L, pod, limits, dirC, null), 4);
        String hashC = sha256(dirC.resolve("events").resolve("000004.jsonl"));
        assertFalse("different game index must not replay the same stream", hashA.equals(hashC));
    }

    private static String sha256(Path file) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file));
        StringBuilder hex = new StringBuilder();
        for (byte b : digest) {
            hex.append(String.format("%02x", b));
        }
        return hex.toString();
    }
}
