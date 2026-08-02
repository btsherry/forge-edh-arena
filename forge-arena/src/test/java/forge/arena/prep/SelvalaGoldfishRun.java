package forge.arena.prep;

import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;

/**
 * Goldfish diagnostic (not a gate): run ProgramGate over the WHOLE Selvala
 * dossier on a temp copy and print every program's verdict, so the new-shape
 * programs (dreadnought_window, seedborn_engine) and the existing selvala
 * mana loops are all exercised in-engine at once. Prints; asserts only that
 * the run produced verdicts.
 */
public class SelvalaGoldfishRun {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void goldfishAllSelvalaPrograms() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("selvala-goldfish-stalls").toString());
        Path source = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        Path dossier = Files.createTempDirectory("selvala-goldfish-dossier");
        try (var files = Files.walk(source)) {
            for (Path p : files.toList()) {
                Path dest = dossier.resolve(source.relativize(p).toString());
                if (Files.isDirectory(p)) {
                    Files.createDirectories(dest);
                } else {
                    Files.copy(p, dest);
                }
            }
        }

        ProgramGate.Report report = ProgramGate.run(dossier);

        System.out.println("\n===== SELVALA GOLDFISH VERDICTS =====");
        report.verdicts().stream()
                .sorted((a, b) -> a.status().compareTo(b.status()))
                .forEach(v -> System.out.println(String.format(
                        "  [%-10s] %-52s it=%-3d win=%-5s  %s",
                        v.status(), v.comboId(), v.iterations(), v.win(), v.reason())));
        System.out.println(String.format("===== TALLY: %d executable, %d flagged, %d no_program =====%n",
                report.executable(), report.flagged(), report.noProgram()));

        assertTrue("gate produced verdicts", !report.verdicts().isEmpty());
    }
}
