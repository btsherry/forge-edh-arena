package forge.arena.engine;

import java.io.File;
import java.nio.file.Path;

/**
 * One seat of a pod: a Commander .dck file plus the AI configuration —
 * personality profile, the per-seat simulation-AI toggle (Forge's
 * {@code AIOption.USE_SIMULATION}, off in stock CLI runs, T0 §3), the
 * goldfish flag (non-interactive seat: keeps every hand, never acts), and
 * the combo-aware flag (PR-15: ComboPilot fed by the deck's dossier
 * artifacts — {@code dossierDir} must contain combos.json).
 */
public record SeatSpec(File deckFile, String aiProfile, boolean simulationAi, boolean goldfish,
        boolean comboAware, Path dossierDir) {

    /** Pre-PR-15 shape: stock seat configuration. */
    public SeatSpec(File deckFile, String aiProfile, boolean simulationAi, boolean goldfish) {
        this(deckFile, aiProfile, simulationAi, goldfish, false, null);
    }

    public static SeatSpec of(File deckFile) {
        return new SeatSpec(deckFile, "Default", false, false);
    }

    public static SeatSpec goldfish(File deckFile) {
        return new SeatSpec(deckFile, "Default", false, true);
    }

    public static SeatSpec comboAware(File deckFile, Path dossierDir) {
        return new SeatSpec(deckFile, "Default", false, false, true, dossierDir);
    }
}
