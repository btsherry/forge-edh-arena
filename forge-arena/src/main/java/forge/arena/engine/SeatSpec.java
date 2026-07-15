package forge.arena.engine;

import java.io.File;

/**
 * One seat of a pod: a Commander .dck file plus the AI configuration
 * (personality profile and the per-seat simulation-AI toggle, which maps to
 * Forge's {@code AIOption.USE_SIMULATION} — off in stock CLI runs, T0 §3).
 */
public record SeatSpec(File deckFile, String aiProfile, boolean simulationAi) {

    public static SeatSpec of(File deckFile) {
        return new SeatSpec(deckFile, "Default", false);
    }
}
