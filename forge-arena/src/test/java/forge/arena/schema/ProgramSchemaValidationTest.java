package forge.arena.schema;

import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import org.testng.annotations.DataProvider;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;

/**
 * Plan §8.2 — the program family carries no schema until now, so a malformed
 * compiled program silently dispatches as {@code unreadable} and aborts. This
 * sweep validates every on-disk dossier program file against its reverse-
 * engineered schema (docs/atlas/*), so an author-time typo (a bad program_class,
 * a mistyped body key, a missing id) fails loudly here instead of at runtime.
 *
 * <p>Dossiers are gitignored (plan §11): on a clean checkout the {@code decks/}
 * globs are empty and every case passes trivially. On a dev machine it validates
 * the real 90+ program files — the "validate the existing set, expect ~all pass"
 * check, and thereafter an ongoing local gate.
 */
public class ProgramSchemaValidationTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Path firstExisting(String... candidates) {
        for (String c : candidates) {
            Path p = Path.of(c);
            if (Files.exists(p)) {
                return p;
            }
        }
        return null;
    }

    private static final Path SCHEMA_DIR = firstExisting("schemas", "forge-arena/schemas");
    private static final Path DECKS_DIR = firstExisting("decks", "forge-arena/decks");

    private JsonSchema schema(String name) throws Exception {
        try (InputStream in = Files.newInputStream(SCHEMA_DIR.resolve(name))) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }

    /** Every dossier program file, grouped by kind → schema. */
    @DataProvider(name = "programKinds")
    public Object[][] programKinds() {
        return new Object[][] {
                { "combo-program",   "arena.combo-program.1.schema.json",   false },
                { "engine-program",  "arena.engine-program.1.schema.json",  false },
                { "pairing-program", "arena.pairing-program.1.schema.json", false },
                { "fixture",         "arena.program-fixture.1.schema.json",  true },
        };
    }

    @Test(dataProvider = "programKinds")
    public void everyProgramFileValidates(String prefix, String schemaFile, boolean underFixtures)
            throws Exception {
        if (DECKS_DIR == null) {
            return; // clean checkout — no dossiers to validate
        }
        List<Path> files = programFiles(prefix, underFixtures);
        JsonSchema schema = schema(schemaFile);
        List<String> failures = new ArrayList<>();
        for (Path f : files) {
            Set<ValidationMessage> errors = schema.validate(MAPPER.readTree(f.toFile()));
            if (!errors.isEmpty()) {
                failures.add(DECKS_DIR.relativize(f) + " -> " + errors);
            }
        }
        assertTrue(prefix + ": " + failures.size() + "/" + files.size() + " failed:\n"
                + String.join("\n", failures), failures.isEmpty());
    }

    /** Glob decks/<deck>/dossier[/fixtures]/<prefix>*.json across every deck. */
    private List<Path> programFiles(String prefix, boolean underFixtures) throws Exception {
        try (Stream<Path> walk = Files.walk(DECKS_DIR)) {
            return walk
                    .filter(Files::isRegularFile)
                    .filter(p -> {
                        String name = p.getFileName().toString();
                        if (!name.startsWith(prefix + "-") || !name.endsWith(".json")) {
                            return false;
                        }
                        Path parent = p.getParent();
                        String parentName = parent == null ? "" : parent.getFileName().toString();
                        return parentName.equals(underFixtures ? "fixtures" : "dossier");
                    })
                    .collect(Collectors.toList());
        }
    }

    /**
     * The single-file-per-dossier artifacts whose schemas §8.2 adds (the ones the
     * existing integration tests don't already validate). Same skip-when-absent
     * contract as the program sweep.
     */
    @DataProvider(name = "dossierArtifacts")
    public Object[][] dossierArtifacts() {
        return new Object[][] {
                { "advisory-combos.json",                "arena.advisory-combos.1.schema.json" },
                { "discovered-combos.json",              "arena.discovered-combos.1.schema.json" },
                { "protection-priorities.json",          "arena.protection-priorities.1.schema.json" },
                { "paired-plays.json",                   "arena.paired-plays.1.schema.json" },
                { "program-backlog.json",                "arena.program-backlog.1.schema.json" },
                { "build-manifest.json",                 "arena.build-manifest.1.schema.json" },
                { "discovered-synergies-wholedeck.json", "arena.discovered-synergies-wholedeck.1.schema.json" },
        };
    }

    @Test(dataProvider = "dossierArtifacts")
    public void everyDossierArtifactValidates(String filename, String schemaFile) throws Exception {
        if (DECKS_DIR == null) {
            return; // clean checkout — no dossiers to validate
        }
        List<Path> files = dossierFiles(filename);
        JsonSchema schema = schema(schemaFile);
        List<String> failures = new ArrayList<>();
        for (Path f : files) {
            Set<ValidationMessage> errors = schema.validate(MAPPER.readTree(f.toFile()));
            if (!errors.isEmpty()) {
                failures.add(DECKS_DIR.relativize(f) + " -> " + errors);
            }
        }
        assertTrue(filename + ": " + failures.size() + "/" + files.size() + " failed:\n"
                + String.join("\n", failures), failures.isEmpty());
    }

    /** Every decks/<deck>/dossier/<filename> across every deck (exact filename). */
    private List<Path> dossierFiles(String filename) throws Exception {
        try (Stream<Path> walk = Files.walk(DECKS_DIR)) {
            return walk
                    .filter(Files::isRegularFile)
                    .filter(p -> p.getFileName().toString().equals(filename))
                    .filter(p -> {
                        Path parent = p.getParent();
                        return parent != null && parent.getFileName().toString().equals("dossier");
                    })
                    .collect(Collectors.toList());
        }
    }
}
