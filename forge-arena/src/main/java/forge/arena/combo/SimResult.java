package forge.arena.combo;

/**
 * Outcome of a sandbox validation run (plan §6): PROFITABLE with the cycle
 * that proved it, BLOCKED naming what refused (the reason a hallucinated or
 * stale binding can never reach executable — §9 W1), or UNPROFITABLE when
 * the loop runs but never nets resources.
 */
public record SimResult(Status status, int cycles, String blockedBy) {

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
