package forge.arena.bindgen;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

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
import forge.arena.prep.RouteLibrary;
import forge.arena.prep.RouteRules;

/**
 * Plan §8 StallAutopsyTest: distinct stalls are deduped by state hash (one
 * call each, EVER — the global ledger survives runs), repairs pass the same
 * lint + sim gates as Gate 3.5 before touching the library, payoff
 * discoveries land as INERT route-library proposals, and batch mode itself
 * made zero network calls (the autopsy consumes recorded dumps post-run).
 */
public class StallAutopsyTest {

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

    /** A batch dir with TWO games stalling on the SAME state hash. */
    private record Fixture(Path batchDir, Path bindings, Path routeLibrary) {
    }

    private Fixture fixture() throws Exception {
        Path batchDir = Files.createTempDirectory("autopsy-batch");
        Path dump = batchDir.resolve("stall-ab12.txt");
        Files.writeString(dump, "turn=9\nseat0 life=40 battlefield=Selvala, Heart of the Wilds;"
                + "Umbral Mantle;Forest;\n");
        Path dossier = Files.createTempDirectory("autopsy-dossier");
        MAPPER.writeValue(dossier.resolve("deck-cards.json").toFile(), Map.of(
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1, "zone", "commander",
                                "oracle_text", "{G}, {T}: Add X mana."),
                        Map.of("name", "Craterhoof Behemoth", "qty", 1, "zone", "main",
                                "oracle_text", "Haste\\nWhen it enters, creatures you control"
                                        + " gain trample and get +X/+X."))));
        MAPPER.writeValue(batchDir.resolve("worker-config.json").toFile(), Map.of(
                "seats", List.of(Map.of(
                        "deck_file", "/decks/selvala.dck",
                        "combo_aware", true,
                        "dossier", dossier.toString()))));
        String game = """
                {"t":"game_start","seats":["selvala"],"seed":1}
                {"t":"route_selected","turn":5,"seat":0,"route":"COMMANDER_DMG_SEQUENCE","predicates":{}}
                {"t":"combo_shortcut","turn":5,"seat":0,"combo":"527-2816","iterations_proven":3,"bounded_product":{}}
                {"t":"combo_stalled","turn":7,"seat":0,"binding":"527-2816","state_hash":"ab12","dump_path":"%s"}
                {"t":"game_end","turn":9,"win_condition":"Draw"}
                """.formatted(dump);
        Files.createDirectories(batchDir.resolve("events"));
        Files.writeString(batchDir.resolve("events").resolve("000000.jsonl"), game);
        Files.writeString(batchDir.resolve("events").resolve("000001.jsonl"), game);

        Path bindings = Files.createTempDirectory("autopsy-lib").resolve("executor-bindings.json");
        Files.copy(ExecutorBindings.defaultPath(), bindings);
        Path routeLibrary = bindings.resolveSibling("classifications.json");
        return new Fixture(batchDir, bindings, routeLibrary);
    }

    private static final String REPAIR = """
            {"kind": "binding_repair",
             "binding": {"archetype": "TapForManaUntapLoop",
               "params": {"engine": "Selvala, Heart of the Wilds", "untapper": "Umbral Mantle",
                          "activation_cost": "{G}", "untap_cost": "{3}",
                          "untap_ability_host": "engine", "attach_cost": "{0}",
                          "self_pump_per_cycle": "2", "pool_color": "G"},
               "payoffs": ["Craterhoof Behemoth"], "entry_phase": "MAIN1"}}""";

    @Test
    public void distinctStallsDedupeAndAVerifiedRepairReplacesTheBinding() throws Exception {
        Fixture f = fixture();
        AtomicInteger calls = new AtomicInteger();
        StallAutopsy.Result result = StallAutopsy.run(f.batchDir(), f.bindings(), f.routeLibrary(),
                client(calls, List.of(REPAIR)), binding -> SimResult.profitable(3));

        assertEquals("two identical stalls, ONE call", 1, calls.get());
        assertEquals(1, result.distinctStalls());
        assertEquals(1, result.repairedBindings());
        assertEquals(1, result.cachedSkips());

        var library = MAPPER.readTree(f.bindings().toFile());
        var repaired = library.get("bindings").get(0);
        assertEquals("527-2816", repaired.get("combo_id").asText());
        assertEquals("stall-autopsy/1", repaired.get("provenance").get("generated_by").asText());
        assertTrue(repaired.get("payoffs").toString().contains("Craterhoof"));

        // the ledger makes reprocessing free — forever
        AtomicInteger secondCalls = new AtomicInteger();
        StallAutopsy.Result second = StallAutopsy.run(f.batchDir(), f.bindings(), f.routeLibrary(),
                client(secondCalls, List.of(REPAIR)), binding -> SimResult.profitable(3));
        assertEquals(0, secondCalls.get());
        assertEquals(2, second.cachedSkips());
    }

    @Test
    public void unverifiedRepairNeverTouchesTheLibrary() throws Exception {
        Fixture f = fixture();
        byte[] before = Files.readAllBytes(f.bindings());
        AtomicInteger calls = new AtomicInteger();
        StallAutopsy.Result result = StallAutopsy.run(f.batchDir(), f.bindings(), f.routeLibrary(),
                client(calls, List.of(REPAIR)), binding -> SimResult.blocked("untapper"));

        assertEquals("one repair retry ran", 2, calls.get());
        assertEquals(1, result.failures());
        assertEquals(0, result.repairedBindings());
        assertTrue("library untouched by an unproven repair",
                java.util.Arrays.equals(before, Files.readAllBytes(f.bindings())));
    }

    @Test
    public void payoffDiscoveryLandsAsAnInertProposal() throws Exception {
        Fixture f = fixture();
        String discovery = """
                {"kind": "payoff_addition", "card": "Craterhoof Behemoth",
                 "payoff_class": "mass_pump", "rationale": "the stalled board lacked pump"}""";
        AtomicInteger calls = new AtomicInteger();
        StallAutopsy.Result result = StallAutopsy.run(f.batchDir(), f.bindings(), f.routeLibrary(),
                client(calls, List.of(discovery)), binding -> SimResult.profitable(3));

        assertEquals(1, result.payoffProposals());
        RouteLibrary lib = RouteLibrary.load(f.routeLibrary());
        assertTrue(lib.knowsPayoffCard("Craterhoof Behemoth"));
        // proposed, not approved: coverage behavior unchanged (PR-13 gate)
        assertTrue(lib.payoffOverrides().isEmpty());
        assertEquals(RouteLibrary.NO_LIBRARY, lib.effectiveVersion());
    }

    @Test
    public void honestNoRepairIsRecordedNotRetried() throws Exception {
        Fixture f = fixture();
        String diagnosis = "{\"kind\": \"no_repair\", \"diagnosis\": \"COMMANDER_DMG_SEQUENCE is"
                + " inherently multi-turn; the deck needs SPREAD_COMBAT payoffs in hand\"}";
        AtomicInteger calls = new AtomicInteger();
        StallAutopsy.Result result = StallAutopsy.run(f.batchDir(), f.bindings(), f.routeLibrary(),
                client(calls, List.of(diagnosis)), binding -> SimResult.profitable(3));
        assertEquals(1, calls.get());
        assertEquals(1, result.noRepair());
        assertFalse(result.notes().isEmpty());
        assertTrue(result.notes().get(0).contains("no repair"));
    }
}
