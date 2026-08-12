package forge.arena.interactive;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;

/**
 * Pure (Swing-free) incremental tail of the advisor runner's stream file,
 * {@code <logsDir>/advisor-0.log}. The GUI panel polls {@link #readNew()} on
 * a Swing timer; this class tracks the read offset and survives the file
 * being rotated or truncated (teardown archives it) by resetting to zero.
 * Kept out of the view class so the logic is unit-testable without a display.
 */
public final class AdvisorLogTail {

    private long offset;

    /** The advisor stream file, resolved via the shared logs-dir contract. */
    public static File streamFile() {
        return new File(AiControlFile.logsDir(), "advisor-0.log");
    }

    /** Age in ms of the stream's last write (Long.MAX_VALUE if absent) — liveness. */
    public static long ageMillis() {
        final File f = streamFile();
        return f.exists() ? System.currentTimeMillis() - f.lastModified() : Long.MAX_VALUE;
    }

    /** Text appended since the last call, or {@code ""} when nothing is new. */
    public String readNew() {
        final File f = streamFile();
        if (!f.exists()) {
            offset = 0;
            return "";
        }
        try (RandomAccessFile raf = new RandomAccessFile(f, "r")) {
            final long len = raf.length();
            if (len < offset) {
                offset = 0; // rotated/truncated by teardown — start over
            }
            if (len == offset) {
                return "";
            }
            raf.seek(offset);
            final byte[] chunk = new byte[(int) Math.min(len - offset, 512 * 1024)];
            final int read = raf.read(chunk);
            if (read <= 0) {
                return "";
            }
            offset += read;
            return new String(chunk, 0, read, StandardCharsets.UTF_8);
        } catch (IOException e) {
            return ""; // panel shows stale content; next poll retries
        }
    }
}
