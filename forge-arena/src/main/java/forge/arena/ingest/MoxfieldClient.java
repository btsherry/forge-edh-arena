package forge.arena.ingest;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Phase 6 / PR-45 — the front door for "drop in any deck": fetch a Moxfield
 * deck and emit the plain decklist text {@link DeckListParser} already
 * understands, so a URL becomes a dossier through the ordinary prep
 * pipeline with no special-casing downstream.
 *
 * <p>Design follows {@code SpellbookClient}: the transport is INJECTED, so
 * the conversion logic is unit-tested against a recorded fixture with zero
 * network, and the live path is one small method. Network calls belong to
 * prep only — never to a batch, never to the game loop.
 *
 * <p>Output is the canonical form the parser handles: a {@code Commander:}
 * header for the command zone, then {@code <qty> <name>} lines. Card names
 * are emitted verbatim from Moxfield; resolution against the Forge card DB
 * is Gate 0's job, and anything unresolvable is reported there rather than
 * silently dropped here.
 */
public final class MoxfieldClient {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Moxfield deck URLs: .../decks/<publicId>, with optional trailing bits. */
    private static final Pattern PUBLIC_ID =
            Pattern.compile("moxfield\\.com/decks/([A-Za-z0-9_-]+)");

    /** Injectable transport: URL in, response body out. */
    public interface Fetcher {
        String get(String url) throws IOException;
    }

    private MoxfieldClient() {
    }

    /**
     * The public id from a deck URL, or the input itself when it already
     * looks like a bare id (so both forms work on the command line).
     */
    public static String publicId(String urlOrId) {
        Matcher m = PUBLIC_ID.matcher(urlOrId);
        if (m.find()) {
            return m.group(1);
        }
        if (urlOrId.matches("[A-Za-z0-9_-]+")) {
            return urlOrId;
        }
        throw new IllegalArgumentException("not a Moxfield deck URL or id: " + urlOrId);
    }

    /** Real transport. Moxfield rejects default Java user agents. */
    public static Fetcher httpFetcher() {
        HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(20)).build();
        return url -> {
            HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                    .header("User-Agent", "forge-edh-arena/1.0 (deck ingest; prep-time only)")
                    .header("Accept", "application/json")
                    .timeout(Duration.ofSeconds(60))
                    .GET().build();
            try {
                HttpResponse<String> response =
                        client.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() != 200) {
                    throw new IOException("moxfield " + response.statusCode() + " for " + url);
                }
                return response.body();
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                throw new IOException("interrupted fetching " + url, ie);
            }
        };
    }

    /** Fetch a deck and convert it to decklist text lines. */
    public static List<String> fetchDeckList(String urlOrId, Fetcher fetcher) throws IOException {
        String id = publicId(urlOrId);
        String body = fetcher.get("https://api2.moxfield.com/v3/decks/all/" + id);
        return toDeckList(MAPPER.readTree(body));
    }

    /**
     * Convert Moxfield's deck JSON into decklist lines. v3 nests board
     * entries under {@code boards.<board>.cards.<id>.{quantity,card.name}};
     * the older shape put {@code mainboard}/{@code commanders} at the top
     * level keyed by card name. Both are read, because a deck source that
     * silently returns nothing on a schema change is worse than one that
     * fails loudly.
     */
    public static List<String> toDeckList(JsonNode deck) {
        List<String> lines = new ArrayList<>();
        List<String> commanders = new ArrayList<>();
        List<String> main = new ArrayList<>();

        JsonNode boards = deck.path("boards");
        if (boards.isObject()) {
            collectBoard(boards.path("commanders").path("cards"), commanders);
            collectBoard(boards.path("mainboard").path("cards"), main);
        }
        if (main.isEmpty()) { // legacy shape
            collectLegacy(deck.path("commanders"), commanders);
            collectLegacy(deck.path("mainboard"), main);
        }
        if (main.isEmpty() && commanders.isEmpty()) {
            throw new IllegalArgumentException(
                    "moxfield deck had no readable mainboard — schema change?");
        }
        if (!commanders.isEmpty()) {
            lines.add("Commander:");
            lines.addAll(commanders);
        }
        // an explicit "Deck:" header is REQUIRED, not cosmetic: the parser's
        // section is sticky and a blank line does not end it, so without this
        // the entire 99 is read as command-zone cards
        lines.add("Deck:");
        lines.addAll(main);
        return lines;
    }

    /** v3: cards keyed by an opaque id, name nested under {@code card}. */
    private static void collectBoard(JsonNode cards, List<String> out) {
        for (Iterator<Map.Entry<String, JsonNode>> it = cards.fields(); it.hasNext();) {
            JsonNode entry = it.next().getValue();
            String name = entry.path("card").path("name").asText("");
            int qty = entry.path("quantity").asInt(1);
            if (!name.isBlank()) {
                out.add(qty + " " + name);
            }
        }
    }

    /** Legacy: keyed by card name, quantity alongside. */
    private static void collectLegacy(JsonNode board, List<String> out) {
        for (Iterator<Map.Entry<String, JsonNode>> it = board.fields(); it.hasNext();) {
            Map.Entry<String, JsonNode> entry = it.next();
            String name = entry.getValue().path("card").path("name").asText(entry.getKey());
            int qty = entry.getValue().path("quantity").asInt(1);
            if (!name.isBlank()) {
                out.add(qty + " " + name);
            }
        }
    }
}
