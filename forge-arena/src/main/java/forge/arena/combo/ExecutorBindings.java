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

    /**
     * PR-48: fold a deck's generated paired plays into the global library.
     * Pairs are DECK-scoped by nature (they name two cards in one 99), so
     * they live in the dossier rather than the shared bindings file, and
     * the pilot sees one merged view. Hand-authored entries win on id
     * collision — a human decision is never silently overwritten.
     */
    public ExecutorBindings withPairedPlays(Path pairedPlaysJson) throws IOException {
        if (!Files.exists(pairedPlaysJson)) {
            return this;
        }
        JsonNode root = MAPPER.readTree(pairedPlaysJson.toFile());
        Map<String, Binding> merged = new LinkedHashMap<>(byComboId);
        for (JsonNode pair : root.path("pairs")) {
            String id = pair.path("id").asText();
            if (id.isBlank() || merged.containsKey(id)) {
                continue;
            }
            Map<String, String> params = new LinkedHashMap<>();
            params.put("trigger_card", pair.path("trigger_card").asText());
            params.put("protection_card", pair.path("protection_card").asText());
            params.put("trigger_mana_value", String.valueOf(
                    pair.path("combined_mana_value").asInt(0)));
            params.put("protection_mana_value", "0");
            // PR-49: the scope decides what this wipe actually destroys, and
            // therefore what it is worth against a given board
            params.put("wipe_scope", pair.path("wipe_scope").asText(""));
            merged.put(id, new Binding(id, PairedPlay.ARCHETYPE, params,
                    List.of(), "MAIN1", List.of()));
        }
        return new ExecutorBindings(merged, unbound);
    }

    public Optional<Binding> forCombo(String comboId) {
        return Optional.ofNullable(byComboId.get(comboId));
    }

    public List<String> unbound() {
        return unbound;
    }

    /** All bindings (PR-31: PairedPlay detection is binding-driven). */
    public java.util.Collection<Binding> all() {
        return byComboId.values();
    }

    public int size() {
        return byComboId.size();
    }

    /**
     * Build the executor a binding names. Empty when the archetype is
     * unknown — the combo stays detection-only (plan §6 generic fallback),
     * never a crash: an unknown name in data must not break a batch.
     */
    /**
     * Executors are immutable value objects built from a binding's params,
     * so building one per call was pure churn: the pilot asks for every
     * binding's executor at EVERY priority window, and a deck with 36
     * generated paired plays turned that into tens of thousands of
     * short-lived objects per game. Cached by identity of the binding.
     */
    private static final Map<Binding, Optional<LineExecutor>> EXECUTOR_CACHE =
            new java.util.concurrent.ConcurrentHashMap<>();

    public static Optional<LineExecutor> executorFor(Binding binding) {
        return EXECUTOR_CACHE.computeIfAbsent(binding, ExecutorBindings::buildExecutor);
    }

    private static Optional<LineExecutor> buildExecutor(Binding binding) {
        if (TapForManaUntapLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new TapForManaUntapLoop(binding.params(), binding.entryPhase()));
        }
        if (BounceRecastLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new BounceRecastLoop(binding.params(), binding.entryPhase()));
        }
        if (SpellCopyLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new SpellCopyLoop(binding.params(), binding.entryPhase()));
        }
        if (PairedPlay.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new PairedPlay(binding.params(), binding.entryPhase()));
        }
        if (ImprintCopyLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new ImprintCopyLoop(binding.params(), binding.entryPhase()));
        }
        if (LifegainPingLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new LifegainPingLoop(binding.params(), binding.entryPhase()));
        }
        if (SelfTopdeckRecastLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new SelfTopdeckRecastLoop(binding.params(), binding.entryPhase()));
        }
        if (CastBounceManaLoop.ARCHETYPE.equals(binding.archetype())) {
            return Optional.of(new CastBounceManaLoop(binding.params(), binding.entryPhase()));
        }
        return Optional.empty();
    }
}
