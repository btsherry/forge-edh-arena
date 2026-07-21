package forge.arena.combo;

/**
 * Outcome of a sandbox validation run (plan §6): PROFITABLE with the cycle
 * that proved it, BLOCKED naming what refused (the reason a hallucinated or
 * stale binding can never reach executable — §9 W1), or UNPROFITABLE when
 * the loop runs but never nets resources.
 */
public record SimResult(Status status, int cycles, String blockedBy, String diagnostic) {

    public SimResult(Status status, int cycles, String blockedBy) {
        this(status, cycles, blockedBy, null);
    }

    /**
     * PR-68: attach WHY the sandbox refused, from the sim handle.
     *
     * <p>{@code blockedBy} names the ROLE that refused ("engine", "rock") —
     * useful for grouping, useless for fixing. Seven of Urza's nine line
     * entries died on {@code blocked:engine} with no way to tell whether the
     * binding asked for an ability the card does not have, the card was not
     * on the battlefield, or the cost simply could not be paid. Those are
     * three different bugs wearing one label.
     */
    public SimResult withDiagnostic(String detail) {
        return detail == null ? this : new SimResult(status, cycles, blockedBy, detail);
    }

    public boolean isBlocked() {
        return status == Status.BLOCKED;
    }

    public enum Status {
        PROFITABLE, BLOCKED, UNPROFITABLE
    }

    public static SimResult profitable(int cycles) {
        return new SimResult(Status.PROFITABLE, cycles, null);
    }

    public static SimResult blocked(String what) {
        return new SimResult(Status.BLOCKED, 0, what);
    }

    public static SimResult unprofitable() {
        return new SimResult(Status.UNPROFITABLE, 0, null);
    }

    public boolean isProfitable() {
        return status == Status.PROFITABLE;
    }
}
