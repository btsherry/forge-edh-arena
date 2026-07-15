package forge.arena.prep;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Gate 3 Commander Spellbook client (plan §3/§9 W5): one find-my-combos POST
 * per deck, snapshot cached in the dossier — a cache hit makes ZERO HTTP
 * calls. Prep-time only; nothing in the game loop may reach here. The fetcher
 * is injectable so contract tests run on recorded fixtures.
 */
public final class SpellbookClient {

    public static final String ENDPOINT = "https://backend.commanderspellbook.com/find-my-combos";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Injectable transport: body in, response body out. */
    public interface Fetcher {
        String post(String url, String jsonBody) throws IOException;
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
     * Returns the raw find-my-combos response for the dossier's deck,
     * fetching only when {@code snapshotFile} does not exist.
     */
    public static JsonNode fetchOrLoad(Path dossierDir, Fetcher fetcher) throws IOException {
        Path snapshot = dossierDir.resolve("spellbook-raw.json");
        if (Files.exists(snapshot)) {
            return MAPPER.readTree(snapshot.toFile());
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
        Files.writeString(snapshot, response);
        return parsed;
    }
}
