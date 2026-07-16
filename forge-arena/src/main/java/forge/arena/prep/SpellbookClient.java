package forge.arena.prep;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Gate 3 Commander Spellbook client (plan §3/§9 W5): one find-my-combos POST
 * per deck, snapshot cached in the dossier — a cache hit makes ZERO HTTP
 * calls. The cache is keyed by deck hash via a sidecar meta file
 * (spellbook-raw.meta.json: fetch date + deck_hash): a changed deck refetches
 * instead of silently reusing stale combos, and the fetch DATE survives
 * cache hits for W5 snapshot pinning. Snapshot writes are atomic (temp +
 * move) so an interrupted fetch cannot poison the cache. Prep-time only;
 * nothing in the game loop may reach here. The fetcher is injectable so
 * contract tests run on recorded fixtures.
 */
public final class SpellbookClient {

    public static final String ENDPOINT = "https://backend.commanderspellbook.com/find-my-combos";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Injectable transport: body in, response body out. */
    public interface Fetcher {
        String post(String url, String jsonBody) throws IOException;
    }

    /** Raw response plus its provenance (fetch date, deck hash it was fetched under). */
    public record Snapshot(JsonNode raw, String fetchedDate, String deckHash) {
    }

    /** Real transport. */
    public static Fetcher httpFetcher() {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(20)).build();
        return (url, body) -> {
            HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                    .timeout(Duration.ofSeconds(60))
                    .header("Content-Type", "application/json")
                    .header("User-Agent", "forge-edh-arena/0.1 (research; prep-time only)")
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            try {
                HttpResponse<String> resp = client.send(request, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() != 200) {
                    throw new IOException("spellbook HTTP " + resp.statusCode());
                }
                return resp.body();
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                throw new IOException("interrupted", ie);
            }
        };
    }

    private SpellbookClient() {
    }

    /**
     * Returns the raw find-my-combos response with provenance. Fetches when
     * the snapshot is missing OR was fetched under a different deck hash;
     * otherwise serves the cache (zero HTTP) with its original fetch date.
     */
    public static Snapshot fetchOrLoad(Path dossierDir, Fetcher fetcher) throws IOException {
        String currentHash = MAPPER.readTree(dossierDir.resolve("dossier.json").toFile())
                .path("deck_hash").asText("");
        Path snapshot = dossierDir.resolve("spellbook-raw.json");
        Path meta = dossierDir.resolve("spellbook-raw.meta.json");

        if (Files.exists(snapshot)) {
            String fetchedDate;
            String fetchedHash;
            if (Files.exists(meta)) {
                JsonNode m = MAPPER.readTree(meta.toFile());
                fetchedDate = m.path("fetched").asText("");
                fetchedHash = m.path("deck_hash").asText("");
            } else {
                // legacy snapshot without provenance: backfill from file mtime + current hash
                fetchedDate = LocalDate.ofInstant(
                        Files.getLastModifiedTime(snapshot).toInstant(), ZoneOffset.UTC).toString();
                fetchedHash = currentHash;
                writeMeta(meta, fetchedDate, fetchedHash);
            }
            if (fetchedHash.equals(currentHash)) {
                JsonNode parsed = MAPPER.readTree(snapshot.toFile());
                if (!parsed.has("results")) {
                    throw new IOException("cached spellbook snapshot has no 'results' key"
                            + " (schema-version drift or corrupt cache — W5): " + snapshot);
                }
                return new Snapshot(parsed, fetchedDate, fetchedHash);
            }
            // deck changed since fetch: fall through and refetch
        }

        JsonNode deckCards = MAPPER.readTree(dossierDir.resolve("deck-cards.json").toFile());
        List<Map<String, Object>> main = new ArrayList<>();
        List<Map<String, Object>> commanders = new ArrayList<>();
        for (JsonNode c : deckCards.get("cards")) {
            Map<String, Object> entry = Map.of(
                    "card", c.get("name").asText(),
                    "quantity", c.get("qty").asInt());
            if (c.get("zone").asText().equals("commander")) {
                commanders.add(entry);
            } else {
                main.add(entry);
            }
        }
        String body = MAPPER.writeValueAsString(Map.of("main", main, "commanders", commanders));
        String response = fetcher.post(ENDPOINT, body);
        JsonNode parsed = MAPPER.readTree(response);
        if (!parsed.has("results")) {
            throw new IOException("spellbook response shape changed: no 'results' key (schema-version drift — W5)");
        }
        Path tmp = Files.createTempFile(dossierDir, "spellbook-raw", ".tmp");
        Files.writeString(tmp, response);
        Files.move(tmp, snapshot, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        String fetchedDate = LocalDate.ofInstant(Instant.now(), ZoneOffset.UTC).toString();
        writeMeta(meta, fetchedDate, currentHash);
        return new Snapshot(parsed, fetchedDate, currentHash);
    }

    private static void writeMeta(Path meta, String fetchedDate, String deckHash) throws IOException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("fetched", fetchedDate);
        m.put("deck_hash", deckHash);
        m.put("endpoint", ENDPOINT);
        Files.writeString(meta, MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(m));
    }
}
