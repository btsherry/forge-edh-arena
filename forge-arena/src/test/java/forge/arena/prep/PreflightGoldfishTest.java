package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameEventBridge;
import forge.arena.engine.SeatSpec;
import forge.arena.ingest.Ingest;
import forge.arena.report.ArenaEvent;

/** Plan §8 PreflightGoldfishTest + goldfish-seat behavior proof. */
public class PreflightGoldfishTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void unimplementedCardFailsGate2WithCardNamed() throws Exception {
        Path out = Files.createTempDirectory("gate2-fake");
        Path list = out.resolve("list.txt");
        Files.write(list, List.of("1 Selvala, Heart of the Wilds", "1 Totally Fake Card Xyz", "30 Forest"));
        Ingest.Result ing = Ingest.run(new Ingest.Spec(list, "fake", out, "homebrew", null, null, null,
                List.of("Selvala, Heart of the Wilds")));

        GoldfishCompile.Report r = GoldfishCompile.run(ing.dossierDir(), 1, 5);
        assertFalse(r.pass());
        assertEquals(List.of("Totally Fake Card Xyz"), r.unimplemented());
        assertTrue("games must not run when cards are missing", r.games().isEmpty());
        List<String> txt = Files.readAllLines(ing.dossierDir().resolve("unimplemented-cards.txt"));
        assertEquals(List.of("Totally Fake Card Xyz"), txt);
        var index = MAPPER.readTree(ing.dossierDir().resolve("dossier.json").toFile());
        assertEquals("fail", index.get("status").get("implementability").asText());
    }

    @Test
    public void selvalaPassesGoldfishCompile() throws Exception {
        Path out = Files.createTempDirectory("gate2-real");
        Ingest.Result ing = Ingest.run(new Ingest.Spec(
                Path.of("decks", "selvala-heart-of-the-wilds.dck"), "selvala-b3", out,
                "homebrew", 3, null, null, null));

        GoldfishCompile.Report r = GoldfishCompile.run(ing.dossierDir(), 2, 10);
        assertTrue("expected pass, failure: " + r.failure(), r.pass());
        assertEquals(2, r.games().size());
        var index = MAPPER.readTree(ing.dossierDir().resolve("dossier.json").toFile());
        assertEquals("pass", index.get("status").get("implementability").asText());
        assertTrue(Files.exists(ing.dossierDir().resolve("implementability-report.json")));
    }

    @Test
    public void goldfishSeatNeverActsWhileTestSeatPlays() throws Exception {
        File deck = new File("decks", "selvala-heart-of-the-wilds.dck");
        List<ArenaEvent> events = new java.util.concurrent.CopyOnWriteArrayList<>();
        GameEventBridge bridge = new GameEventBridge(events::add);
        ArenaGameResult r = EngineFacade.playCommanderGame(
                List.of(SeatSpec.of(deck), SeatSpec.goldfish(deck)), 101L,
                new ArenaLimits(8, 300, 2000), bridge);

        long testSeatPlays = events.stream()
                .filter(e -> e.t().equals("spell_cast") && Integer.valueOf(0).equals(e.seat())).count();
        long goldfishPlays = events.stream()
                .filter(e -> e.t().equals("spell_cast") && Integer.valueOf(1).equals(e.seat())).count();
        assertTrue("test seat must actually play (got " + testSeatPlays + ")", testSeatPlays > 0);
        assertEquals("goldfish must never act", 0, goldfishPlays);
        assertTrue("goldfish can't win", r.winnerSeat() != 1);
    }
}
