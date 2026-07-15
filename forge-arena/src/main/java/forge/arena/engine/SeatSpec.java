package forge.arena.engine;

import java.io.File;

/**
 * One seat of a pod: a Commander .dck file plus the AI configuration —
 * personality profile, the per-seat simulation-AI toggle (Forge's
 * {@code AIOption.USE_SIMULATION}, off in stock CLI runs, T0 §3), and the
 * goldfish flag (non-interactive seat: keeps every hand, never acts).
 */
public record SeatSpec(File deckFile, String aiProfile, boolean simulationAi, boolean goldfish) {

    public static SeatSpec of(File deckFile) {
        return new SeatSpec(deckFile, "Default", false, false);
    }

    public static SeatSpec goldfish(File deckFile) {
        return new SeatSpec(deckFile, "Default", false, true);
    }
}
