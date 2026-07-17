package forge.arena.combo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The executor binding library (plan §5 executor-bindings.json, §9 W1):
 * per-combo parameterizations of hand-written archetypes. Hand-authored for
 * now; Gate 3.5 bindgen will write the same format once its sim-verifier
 * exists (this PR's {@code validate} IS that verifier's oracle). Bindings
 * are global — keyed by Spellbook combo id, not by deck.
 *
 * <p>Unknown archetypes never bind (the combo stays detection-only with the
 * generic fallback); a malformed file fails loudly.
 */
public final class ExecutorBindings {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public record Binding(String comboId, String archetype, Map<String, String> params,
            List<String> payoffs, String entryPhase, List<String> stages) {
    }

    private final Map<String, Binding> byComboId;
    private final List<String> unbound;

    private ExecutorBindings(Map<String, Binding> byComboId, List<String> unbound) {
        this.byComboId = byComboId;
        this.unbound = unbound;
    }

    /** Default in-repo location, resolved from either repo root or module dir. */
    public static Path defaultPath() {
        Path fromRoot = Path.of("forge-arena", "bindings", "executor-bindings.json");
        return Files.exists(fromRoot) ? fromRoot
                : Path.of("bindings", "executor-bindings.json");
    }

    public static ExecutorBindings load(Path file) throws IOException {
        if (!Files.exists(file)) {
            return new ExecutorBindings(Map.of(), List.of());
        }
        JsonNode root = MAPPER.readTree(file.toFile());
        if (!root.has("bindings")) {
            throw new IOException("executor bindings malformed (want bindings[]): " + file);
        }
        Map<String, Binding> byId = new LinkedHashMap<>();
        for (JsonNode b : root.get("bindings")) {
            if (!b.hasNonNull("combo_id") || !b.hasNonNull("archetype") || !b.has("params")) {
                throw new IOException("binding needs combo_id/archetype/params: " + b + " in " + file);
            }
            Map<String, String> params = new LinkedHashMap<>();
            for (Iterator<Map.Entry<String, JsonNode>> it = b.get("params").fields(); it.hasNext();) {
                Map.Entry<String, JsonNode> e = it.next();
                params.put(e.getKey(), e.getValue().asText());
            }
            List<String> payoffs = new ArrayList<>();
            if (b.has("payoffs")) {
                b.get("payoffs").forEach(p -> payoffs.add(p.asText()));
            }
            List<String> stages = new ArrayList<>();
            if (b.has("stages")) {
                b.get("stages").forEach(s -> stages.add(s.asText()));
            }
            String comboId = b.get("combo_id").asText();
            byId.put(comboId, new Binding(comboId, b.get("archetype").asText(), params,
                    payoffs, b.path("entry_phase").asText("MAIN1"), stages));
        }
        List<String> unbound = new ArrayList<>();
        if (root.has("unbound")) {
            root.get("unbound").forEach(u -> unbound.add(u.asText()));
        }
        return new ExecutorBindings(byId, unbound);
    }

    public Optional<Binding> forCombo(String comboId) {
        return Optional.ofNullable(byComboId.get(comboId));
    }

    public List<String> unbound() {
        return unbound;
    }

    public int size() {
        return byComboId.size();
    }

    /**
     * Build the executor a binding names. Empty when the archetype is
     * unknown — the combo stays detection-only (plan §6 generic fallback),
     * never a crash: an unknown name in data must not break a batch.
     */
    public static Optional<LineExecutor> executorFor(Binding binding) {
        if (TapForManaUntapLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new TapForManaUntapLoop(binding.params(), binding.entryPhase()));
        }
        if (BounceRecastLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new BounceRecastLoop(binding.params(), binding.entryPhase()));
        }
        return Optional.empty();
    }
}
