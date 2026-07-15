package forge.arena.report;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

import org.testng.annotations.Test;

/**
 * Concurrent writers with SEPARATE RunLog handles on the same file (the
 * worker-process model) must never tear lines — each line is a single
 * O_APPEND write.
 */
public class RunLogAtomicAppendTest {

    private static final int WRITERS = 4;
    private static final int LINES_PER_WRITER = 300;

    @Test
    public void concurrentSeparateHandlesNeverTearLines() throws Exception {
        Path file = Files.createTempDirectory("arena-runlog").resolve("run.log");
        List<Thread> threads = new ArrayList<>();
        for (int w = 0; w < WRITERS; w++) {
            final int workerId = w;
            threads.add(new Thread(() -> {
                try (RunLog log = new RunLog(file, String.valueOf(workerId), RunLogRenderer.Tier.DEFAULT)) {
                    for (int i = 0; i < LINES_PER_WRITER; i++) {
                        log.event(i, ArenaEvent.of("combo_ready", i % 30, workerId % 4)
                                .with("combo", "csb-" + workerId + "-" + i)
                                .with("window", "sorcery_speed_main1"));
                    }
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            }));
        }
        threads.forEach(Thread::start);
        for (Thread t : threads) {
            t.join();
        }

        List<String> lines = Files.readAllLines(file);
        assertEquals(WRITERS * LINES_PER_WRITER, lines.size());
        Pattern intact = Pattern.compile(
                "^\\[w\\d g\\d{4} t\\d+ s\\d\\] READY {2}csb-\\d+-\\d+ {2}\\(sorcery_speed_main1\\)$");
        for (String line : lines) {
            assertTrue("torn or malformed line: " + line, intact.matcher(line).matches());
        }
    }
}
