package forge.arena.harness;

import java.io.Closeable;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Shared game-records.jsonl sink: one O_APPEND write per record line, safe
 * across concurrent worker processes (same pattern as RunLog).
 */
public final class RecordWriter implements Closeable {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final FileOutputStream out;

    public RecordWriter(Path file) throws IOException {
        this.out = new FileOutputStream(file.toFile(), true);
    }

    public synchronized void write(Map<String, Object> recordJson) throws IOException {
        out.write((MAPPER.writeValueAsString(recordJson) + "\n").getBytes(StandardCharsets.UTF_8));
        out.flush();
    }

    @Override
    public void close() throws IOException {
        out.close();
    }
}
