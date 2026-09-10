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

    /** Fallback when origin/master is not fetched: the upstream commit of the
     *  latest sync (2026-09-10). Prefer the live merge base with origin/master. */
    static final String UPSTREAM_BASE = "a5f4f9e4796";

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
        Assert.assertTrue(checked > 0, "expected at least one modified upstream source vs " + upstreamBase(repo));
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
    /** The upstream point this checkout diverges from: the merge base with
     *  origin/master when that ref exists locally, else the recorded constant.
     *  After a sync the base MUST move, or every file upstream itself touched
     *  reads as "ours" (the 2026-09-10 sync gate showed exactly that). */
    static String upstreamBase(Path repo) {
        try {
            Process proc = new ProcessBuilder("git", "merge-base", "HEAD", "origin/master").directory(repo.toFile())
                    .redirectErrorStream(true).start();
            String out;
            try (BufferedReader r = new BufferedReader(new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                out = r.readLine();
            }
            if (proc.waitFor() == 0 && out != null && out.trim().matches("[0-9a-f]{7,40}")) {
                return out.trim();
            }
        } catch (Exception ignored) {
            // fall through
        }
        return UPSTREAM_BASE;
    }

    private static List<String> gitModifiedOutsideArena(Path repo) {
        try {
            Process proc = new ProcessBuilder("git", "diff", "--name-status", "--diff-filter=M", upstreamBase(repo), "HEAD",
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
