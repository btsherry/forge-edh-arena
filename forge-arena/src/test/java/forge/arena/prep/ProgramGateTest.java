package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;

/**
 * PR-delta: the program executability gate, end to end on the real Giada
 * dossier (copied to a temp dir — the gate writes fixtures, the backlog, and
 * dossier status, and a test must not mutate committed artifacts).
 *
 * <p>Both of the dossier's combos now carry compiled programs and must gate
 * EXECUTABLE on engine evidence: 1274-3693 (Heliod, proven by
 * GiadaHeliodLoopTest) and 2919-3693 (Archangel — the backlog's first
 * compiled entry, whose granter piece Heliod brings a TARGETED trigger the
 * adversarial verify panel caught the first draft omitting). The gate never
 * fails prep; it measures.
 */
public class ProgramGateTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void gateProvesTheProgramAndFlagsTheGap() throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("program-gate-stalls").toString());
        Path source = Path.of("decks", "giada-font-of-hope", "dossier");
        Path dossier = Files.createTempDirectory("program-gate-dossier");
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

        Map<String, ProgramGate.Verdict> byId = report.verdicts().stream()
                .collect(Collectors.toMap(ProgramGate.Verdict::comboId, Function.identity()));
        assertTrue("both combos must be judged, got " + byId.keySet(),
                byId.containsKey("1274-3693") && byId.containsKey("2919-3693"));

        for (String comboId : List.of("1274-3693", "2919-3693")) {
            ProgramGate.Verdict v = byId.get(comboId);
            assertTrue("compiled program " + comboId + " must gate EXECUTABLE,"
                    + " got " + v.status() + " — " + v.reason(),
                    "executable".equals(v.status()));
            assertTrue("executability must come from the ENGINE (win or"
                    + " sustained iterations), got win=" + v.win()
                    + " iterations=" + v.iterations(),
                    v.win() || v.iterations() >= 5);
        }
        assertEquals(2, report.executable());
        assertEquals(0, report.noProgram());
        assertEquals(0, report.flagged());

        // the gate leaves artifacts behind: the fixture it derived, the
        // backlog it judged, and a dossier that tells the truth about both
        assertTrue("fixture artifacts must be emitted",
                Files.exists(dossier.resolve("fixtures").resolve("fixture-1274-3693.json"))
                        && Files.exists(dossier.resolve("fixtures").resolve("fixture-2919-3693.json")));
        assertTrue("backlog artifact must be emitted",
                Files.exists(dossier.resolve("program-backlog.json")));
        String index = Files.readString(dossier.resolve("dossier.json"));
        assertTrue("dossier status must record the program tally",
                index.contains("\"programs\"") && index.contains("2 executable"));
    }
}
