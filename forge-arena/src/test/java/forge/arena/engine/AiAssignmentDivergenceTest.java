package forge.arena.engine;

import static org.testng.AssertJUnit.assertFalse;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.List;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.harness.ArenaRunner;
import forge.arena.harness.GameRecord;
import forge.arena.harness.RunConfig;

/**
 * Phase 2 exit criterion: per-seat AI assignment must produce OBSERVABLY
 * different behavior in the logs. Same seed, one knob flipped ⇒ the event
 * stream must diverge (if it doesn't, the profile/simulation plumbing is
 * not actually binding).
 */
public class AiAssignmentDivergenceTest {

    private List<File> decks;

    @BeforeClass
    public void bootstrap() {
        forge.arena.bootstrap.ArenaBootstrap.initialize(new File("..", "forge-gui"));
        decks = List.of(
                new File("decks/giada-font-of-hope.dck"),
                new File("decks/purphoros-god-of-the-forge.dck"),
                new File("decks/selvala-heart-of-the-wilds.dck"),
                new File("decks/urza-lord-high-artificer.dck"));
    }

    private String runAndHash(long seedBase, List<SeatSpec> seats, ArenaLimits limits) throws Exception {
        Path dir = Files.createTempDirectory("arena-div");
        GameRecord rec = ArenaRunner.runOne(new RunConfig(seedBase, seats, limits, dir, null), 0);
        byte[] bytes = Files.readAllBytes(dir.resolve("events").resolve("000000.jsonl"));
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder hex = new StringBuilder();
        for (byte b : digest) {
            hex.append(String.format("%02x", b));
        }
        return hex + ":" + rec.result();
    }

    /**
     * A single short game can legitimately play out identically under two
     * profiles (early turns are lands and passes), so search a handful of
     * seeds for a divergence — mulligan thresholds alone should split within
     * a few seeds if the knob binds.
     */
    private boolean divergesAcrossSeeds(java.util.function.Function<Long, List<SeatSpec>> a,
            java.util.function.Function<Long, List<SeatSpec>> b, ArenaLimits limits, int seedTries)
            throws Exception {
        for (long seed = 1; seed <= seedTries; seed++) {
            if (!runAndHash(seed, a.apply(seed), limits).equals(runAndHash(seed, b.apply(seed), limits))) {
                return true;
            }
        }
        return false;
    }

    @Test
    public void personalityProfilesChangeTheEventStream() throws Exception {
        ArenaLimits limits = new ArenaLimits(3, 300, 2000);
        boolean diverged = divergesAcrossSeeds(
                s -> decks.stream().map(d -> new SeatSpec(d, "Reckless", false, false)).toList(),
                s -> decks.stream().map(d -> new SeatSpec(d, "Cautious", false, false)).toList(),
                limits, 10);
        assertFalse("profile flip changed nothing across 10 seeds (profiles not binding?)", !diverged);
    }

    @Test
    public void simulationAiToggleChangesTheEventStream() throws Exception {
        // 2-player vs goldfish so the sim seat actually takes turns under a low cap
        ArenaLimits limits = new ArenaLimits(8, 300, 2000);
        boolean diverged = divergesAcrossSeeds(
                s -> List.of(SeatSpec.of(decks.get(2)), SeatSpec.goldfish(decks.get(1))),
                s -> List.of(new SeatSpec(decks.get(2), "Default", true, false),
                        SeatSpec.goldfish(decks.get(1))),
                limits, 5);
        assertFalse("simulation toggle changed nothing across 5 seeds", !diverged);
    }
}
