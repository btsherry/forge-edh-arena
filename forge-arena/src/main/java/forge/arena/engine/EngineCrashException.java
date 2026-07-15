package forge.arena.engine;

/** Engine failure during a game — recorded as a crash GameRecord, never dropped. */
public class EngineCrashException extends RuntimeException {

    public EngineCrashException(String message, Throwable cause) {
        super(message, cause);
    }
}
