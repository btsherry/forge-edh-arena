package forge.arena;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import org.testng.Assert;
import org.testng.SkipException;
import org.testng.annotations.Test;

/**
 * UPSTREAM-SYNC.md's marker rule as a gate step (Ben, 2026-09-09, before the
 * v4.0 merge): every upstream file this fork MODIFIED outside forge-arena/
 * (Java sources and the root pom) must carry an {@code [arena]} or
 * {@code ARENA-PATCH} comment at the edit site, so a future sync can find
 * every divergence by grep. The list comes from git against the recorded
 * upstream base; without git or outside a checkout the test is skipped.
 */
public class UpstreamMarkerTest {

    static final String UPSTREAM_BASE = "0eec0a16d0a";

    @Test
    public void everyModifiedUpstreamSourceCarriesAMarker() throws Exception {
        Path repo = repoRoot();
        List<String> modified = gitModifiedOutsideArena(repo);
        if (modified == null) {
            throw new SkipException("git unavailable or not a checkout — marker rule not checked");
        }
        List<String> unmarked = new ArrayList<>();
        int checked = 0;
        for (String f : modified) {
            if (!(f.endsWith(".java") || f.equals("pom.xml"))) {
                continue;
            }
            Path p = repo.resolve(f);
            if (!Files.exists(p)) {
                continue;
            }
            checked++;
            String text = new String(Files.readAllBytes(p), StandardCharsets.UTF_8);
            if (!text.contains("[arena]") && !text.contains("ARENA-PATCH")) {
                unmarked.add(f);
            }
        }
        Assert.assertTrue(checked > 0, "expected at least one modified upstream source vs " + UPSTREAM_BASE);
        Assert.assertTrue(unmarked.isEmpty(), "modified upstream files without an [arena]/ARENA-PATCH marker "
                + "(see docs/UPSTREAM-SYNC.md, INVENTORY.md 1a): " + unmarked);
    }

    private static Path repoRoot() {
        Path p = Paths.get("").toAbsolutePath();
        for (Path cur = p; cur != null; cur = cur.getParent()) {
            if (Files.isDirectory(cur.resolve(".git")) && Files.isDirectory(cur.resolve("forge-arena"))) {
                return cur;
            }
        }
        return p;
    }

    /** Modified (M) paths outside forge-arena/ vs the upstream base; null when git cannot answer. */
    private static List<String> gitModifiedOutsideArena(Path repo) {
        try {
            Process proc = new ProcessBuilder("git", "diff", "--name-status", "--diff-filter=M", UPSTREAM_BASE, "HEAD",
                    "--", ".", ":(exclude)forge-arena").directory(repo.toFile()).redirectErrorStream(true).start();
            List<String> out = new ArrayList<>();
            try (BufferedReader r = new BufferedReader(new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = r.readLine()) != null) {
                    String[] parts = line.split("\t");
                    if (parts.length >= 2 && "M".equals(parts[0].trim())) {
                        out.add(parts[1].trim());
                    }
                }
            }
            if (proc.waitFor() != 0) {
                return null;
            }
            return out;
        } catch (Exception e) {   // no git, sandbox, timeout: skip rather than fail
            return null;
        }
    }
}
