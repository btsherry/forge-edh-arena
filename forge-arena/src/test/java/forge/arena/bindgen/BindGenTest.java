package forge.arena.bindgen;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.combo.ExecutorBindings;
import forge.arena.combo.SimResult;
import forge.arena.prep.ClaudeClient;
import forge.arena.prep.ComboPrep;

/**
 * Plan §8 BindingGenerationVerificationTest + BindingLibraryCacheTest, on
 * recorded fixtures (zero network) with a scripted verifier: a plausible but
 * WRONG binding fails verification, the repair retry runs, a second failure
 * lands detection-only — a hallucinated binding can never reach executable —
 * and a fully-cached run makes zero calls and leaves identical bytes.
 */
public class BindGenTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static String apiResponse(String text) throws Exception {
        return MAPPER.writeValueAsString(Map.of(
                "content", List.of(Map.of("type", "text", "text", text)),
                "stop_reason", "end_turn"));
    }

    private static ClaudeClient client(AtomicInteger calls, List<String> texts) {
        return new ClaudeClient((url, body) -> {
            int n = calls.getAndIncrement();
            try {
                return apiResponse(texts.get(Math.min(n, texts.size() - 1)));
            } catch (Exception e) {
                throw new java.io.IOException(e);
            }
        }, "test-model");
    }

    /** Dossier from the recorded fixture + a library holding the two hand bindings. */
    private Path[] fixtures() throws Exception {
        Path dossier = Files.createTempDirectory("bindgen");
        MAPPER.writeValue(dossier.resolve("deck-cards.json").toFile(), Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "t",
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1, "zone", "commander",
                                "oracle_text", "{G}, {T}: Add X mana."),
                        Map.of("name", "Umbral Mantle", "qty", 1, "zone", "main",
                                "oracle_text", "Equipped creature has \"{3}, {Q}: +2/+2\"")),
                "unresolved", List.of()));
        Files.writeString(dossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"d7498c0379debdfa\",\"status\":{},\"versions\":{}}");
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            Files.write(dossier.resolve("spellbook-raw.json"), in.readAllBytes());
        }
        ComboPrep.run(dossier, (url, body) -> {
            throw new IllegalStateException("no network");
        });
        Path bindings = Files.createTempDirectory("bindgen-lib").resolve("executor-bindings.json");
        Files.copy(ExecutorBindings.defaultPath(), bindings);
        return new Path[] { dossier, bindings };
    }

    private static final String WRONG = """
            {"archetype": "TapForManaUntapLoop",
             "params": {"engine": "Fake Pinger", "untapper": "Fake Untapper",
                        "activation_cost": "{T}", "untap_cost": "{9}",
                        "untap_ability_host": "untapper"},
             "payoffs": [], "entry_phase": "MAIN1"}""";
    private static final String RIGHT = WRONG.replace("{9}", "{2}");

    @Test
    public void wrongBindingFailsVerificationAndTheRepairRetrySucceeds() throws Exception {
        Path[] f = fixtures();
        AtomicInteger calls = new AtomicInteger();
        AtomicInteger verifications = new AtomicInteger();
        BindGen.Verifier verifier = binding -> {
            verifications.incrementAndGet();
            return "{9}".equals(binding.params().get("untap_cost"))
                    ? SimResult.blocked("untapper")
                    : SimResult.profitable(3);
        };
        BindGen.Result result = BindGen.run(f[0], f[1], client(calls, List.of(WRONG, RIGHT)), verifier);

        assertEquals("one repair retry ran", 2, calls.get());
        assertEquals(2, verifications.get());
        assertEquals(1, result.generated());
        assertEquals(0, result.failedVerification());
        // the fixture contains 527-2816 AND (since PR-32) 4821-5261, both
        // present in the shipped library copy -> two cache hits
        assertEquals(2, result.cached());

        ExecutorBindings reloaded = ExecutorBindings.load(f[1]);
        assertTrue(reloaded.forCombo("9999-1111").isPresent());
        assertEquals("{2}", reloaded.forCombo("9999-1111").orElseThrow().params().get("untap_cost"));
        // provenance travels with the generated binding (found by id — the
        // shipped library grows over time and indices are not stable)
        var raw = MAPPER.readTree(f[1].toFile());
        com.fasterxml.jackson.databind.JsonNode generated = null;
        for (var b : raw.get("bindings")) {
            if ("9999-1111".equals(b.get("combo_id").asText())) {
                generated = b;
            }
        }
        assertTrue("generated binding must be in the file", generated != null);
        assertEquals("bindgen/1", generated.get("provenance").get("generated_by").asText());
        assertEquals(64, generated.get("provenance").get("request_sha256").asText().length());
    }

    @Test
    public void twoFailuresLandDetectionOnlyNeverExecutable() throws Exception {
        Path[] f = fixtures();
        AtomicInteger calls = new AtomicInteger();
        BindGen.Verifier alwaysBlocked = binding -> SimResult.blocked("untapper");
        BindGen.Result result = BindGen.run(f[0], f[1], client(calls, List.of(WRONG)), alwaysBlocked);

        assertEquals(2, calls.get());
        assertEquals(0, result.generated());
        assertEquals(1, result.failedVerification());
        ExecutorBindings reloaded = ExecutorBindings.load(f[1]);
        assertFalse("hallucination must never reach executable",
                reloaded.forCombo("9999-1111").isPresent());
        assertTrue(reloaded.unbound().contains("9999-1111"));
        assertTrue(result.notes().toString().contains("binding_gen_failed"));
    }

    @Test
    public void cachedRunMakesZeroCallsAndLeavesIdenticalBytes() throws Exception {
        Path[] f = fixtures();
        AtomicInteger calls = new AtomicInteger();
        BindGen.Verifier verifier = binding -> SimResult.profitable(3);
        BindGen.run(f[0], f[1], client(calls, List.of(RIGHT)), verifier);
        int callsAfterFirst = calls.get();
        byte[] bytes = Files.readAllBytes(f[1]);

        BindGen.Result second = BindGen.run(f[0], f[1], client(calls, List.of(RIGHT)), verifier);
        assertEquals("zero calls on the cached run", callsAfterFirst, calls.get());
        assertEquals(0, second.generated());
        assertTrue(second.cached() >= 2); // the hand binding + the generated one
        assertTrue("library bytes identical (BindingLibraryCacheTest)",
                java.util.Arrays.equals(bytes, Files.readAllBytes(f[1])));
    }

    @Test
    public void nullArchetypeBecomesAProposalNotABinding() throws Exception {
        Path[] f = fixtures();
        AtomicInteger calls = new AtomicInteger();
        String proposal = "{\"archetype\": null, \"proposal\": \"sacrifice-loop archetype needed\"}";
        BindGen.Result result = BindGen.run(f[0], f[1], client(calls, List.of(proposal)),
                binding -> SimResult.profitable(3));
        assertEquals(1, result.proposals());
        assertEquals(0, result.generated());
        Path proposals = f[1].resolveSibling("bindgen-proposals.jsonl");
        assertTrue(Files.exists(proposals));
        assertTrue(Files.readString(proposals).contains("sacrifice-loop"));
        // proposals are not failures: the combo stays eligible for a future pass
        assertFalse(ExecutorBindings.load(f[1]).unbound().contains("9999-1111"));
    }
}
