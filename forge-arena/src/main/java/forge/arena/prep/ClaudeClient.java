package forge.arena.prep;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Minimal Anthropic Messages API client for PREP-TIME classification calls
 * only (plan §3 Gate 3.5 constraints: API key via environment variable,
 * never in-repo; nothing in the game loop may reach here; batches read
 * artifacts only). The transport is injectable so every test runs on
 * recorded fixtures with zero network.
 *
 * <p>Temperature 0 and a pinned model keep responses as reproducible as the
 * API allows; the caller stores the request hash and verbatim response with
 * every library entry (W5-style provenance).
 */
public final class ClaudeClient {

    public static final String ENDPOINT = "https://api.anthropic.com/v1/messages";
    public static final String DEFAULT_MODEL = "claude-fable-5";
    /** Env override for the classification model. */
    public static final String MODEL_ENV = "ARENA_AUTOPSY_MODEL";
    public static final String API_KEY_ENV = "ANTHROPIC_API_KEY";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Injectable transport: request JSON in, response JSON out. */
    public interface Transport {
        String post(String url, String jsonBody) throws IOException;
    }

    private final Transport transport;
    private final String model;

    public ClaudeClient(Transport transport, String model) {
        this.transport = transport;
        this.model = model;
    }

    /** Real client: key from the environment (fails loudly and early without it). */
    public static ClaudeClient fromEnvironment() {
        String key = System.getenv(API_KEY_ENV);
        if (key == null || key.isBlank()) {
            throw new IllegalStateException(API_KEY_ENV + " is not set — the prep autopsy needs an"
                    + " Anthropic API key (prep-time only; batches never make network calls)");
        }
        String model = System.getenv().getOrDefault(MODEL_ENV, DEFAULT_MODEL);
        return new ClaudeClient(httpTransport(key), model);
    }

    static Transport httpTransport(String apiKey) {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(20)).build();
        return (url, body) -> {
            HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                    .timeout(Duration.ofSeconds(120))
                    .header("Content-Type", "application/json")
                    .header("x-api-key", apiKey)
                    .header("anthropic-version", "2023-06-01")
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            try {
                HttpResponse<String> resp = client.send(request, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() != 200) {
                    throw new IOException("anthropic HTTP " + resp.statusCode() + ": "
                            + resp.body().substring(0, Math.min(300, resp.body().length())));
                }
                return resp.body();
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                throw new IOException("interrupted", ie);
            }
        };
    }

    public String model() {
        return model;
    }

    /** The request body for (system, user) — exposed so callers can hash it (provenance). */
    public String requestBody(String system, String user) throws IOException {
        // insertion-ordered maps: the request hash must be byte-deterministic
        Map<String, Object> message = new java.util.LinkedHashMap<>();
        message.put("role", "user");
        message.put("content", user);
        Map<String, Object> body = new java.util.LinkedHashMap<>();
        body.put("model", model);
        body.put("max_tokens", 4096);
        body.put("temperature", 0);
        body.put("system", system);
        body.put("messages", List.of(message));
        return MAPPER.writeValueAsString(body);
    }

    /** One completion; returns the concatenated text blocks of the response. */
    public String complete(String system, String user) throws IOException {
        String response = transport.post(ENDPOINT, requestBody(system, user));
        JsonNode parsed = MAPPER.readTree(response);
        JsonNode content = parsed.get("content");
        if (content == null || !content.isArray() || content.isEmpty()) {
            throw new IOException("anthropic response shape changed: no content[] blocks");
        }
        StringBuilder text = new StringBuilder();
        for (JsonNode block : content) {
            if ("text".equals(block.path("type").asText())) {
                text.append(block.path("text").asText());
            }
        }
        if (text.length() == 0) {
            throw new IOException("anthropic response had no text blocks (stop_reason="
                    + parsed.path("stop_reason").asText("?") + ")");
        }
        return text.toString();
    }
}
