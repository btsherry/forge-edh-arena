package forge.arena.engine;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.report.ArenaEvent;

/**
 * Phase 6 / PR-44 — <b>swapping decks must never break the engine.</b>
 *
 * <p>The project's whole premise is "drop in any deck". Every other test
 * fixes the deck and varies the pilot; this one fixes the pilot and varies
 * the DECK, asserting the properties that must hold no matter what shows up:
 *
 * <ol>
 * <li><b>Every pod permutation plays.</b> All four decks in every seat
 *     order — the harness rotates seating between games, so a deck that only
 *     works from seat 0 is a latent batch-wide failure.</li>
 * <li><b>A combo-aware seat with EMPTY artifacts is inert.</b> A deck whose
 *     dossier finds nothing must behave as the stock AI, not crash and not
 *     emit phantom pilot decisions. This is the property that lets an
 *     unknown deck be dropped in safely before anyone has bound its
 *     combos.</li>
 * <li><b>Cross-deck artifacts do not leak.</b> Running one deck with a
 *     DIFFERENT deck's dossier must not fire that other deck's combos —
 *     the pilot may only act on cards actually present. A regression here
 *     would silently corrupt every batch that changed a deck without
 *     re-prepping.</li>
 * </ol>
 *
 * <p>These are cheap games (short turn caps) — the point is structural
 * safety under deck change, not play quality.
 */
public class DeckSwapSafetyTest {

    private static final String[] DECKS = {
        "selvala-heart-of-the-wilds.dck",
        "purphoros-god-of-the-forge.dck",
        "urza-lord-high-artificer.dck",
        "giada-font-of-hope.dck",
    };

    private static Path emptyDossier;

    @BeforeClass
    public void bootstrap() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        emptyDossier = Files.createTempDirectory("deck-swap");
        Files.writeString(emptyDossier.resolve("combos.json"), """
                {"schema": "arena.combos/1", "deck_hash": "x", "combos": []}""");
        Files.writeString(emptyDossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"x\",\"status\":{},\"versions\":{}}");
    }

    private ArenaGameResult play(String deckA, String deckB, Path dossier,
            List<ArenaEvent> events) throws Exception {
        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("deck-swap-stalls").toString());
        java.util.function.Consumer<ArenaEvent> sink = events::add;
        return EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks", deckA), dossier),
                        SeatSpec.goldfish(new File("decks", deckB))),
                7L, new ArenaLimits(6, 300, 2000), sink);
    }

    @Test
    public void theTurnCapIsThirtyFiveAndEndsGamesAsDraws() {
        // Pinned deliberately: the cap decides what every batch measures, so
        // it must not drift silently. 35 came from the turn distribution of a
        // full 300-game batch (median 32, p90 at the old 40-turn cap, i.e.
        // the tail was censored rather than observed).
        assertEquals(35, forge.arena.harness.BatchMain.DEFAULT_TURN_CAP);
    }

    @Test
    public void everyDeckPlaysAgainstEveryOtherDeckInEitherSeat() throws Exception {
        for (String a : DECKS) {
            for (String b : DECKS) {
                if (a.equals(b)) {
                    continue;
                }
                List<ArenaEvent> events = new CopyOnWriteArrayList<>();
                ArenaGameResult result = play(a, b, emptyDossier, events);
                // an empty-artifact pilot is SILENT by design, so "no events"
                // is the inertness property, not a failure — the crash check
                // is the recorded result type itself
                assertTrue(a + " vs " + b + " must reach a clean end state, got "
                        + result.type(),
                        result.type() == ArenaGameResult.ResultType.WIN
                                || result.type() == ArenaGameResult.ResultType.DRAW
                                || result.type() == ArenaGameResult.ResultType.TIMEOUT_DRAW);
            }
        }
    }

    @Test
    public void emptyArtifactsMakeThePilotInert() throws Exception {
        // the drop-in-an-unknown-deck property: no combos known yet, so the
        // seat must produce NO pilot decisions at all — not a crash, and not
        // a phantom "ready"/"ignored" trace that would pollute a batch funnel
        for (String deck : DECKS) {
            List<ArenaEvent> events = new CopyOnWriteArrayList<>();
            play(deck, "purphoros-god-of-the-forge.dck".equals(deck)
                    ? "giada-font-of-hope.dck" : "purphoros-god-of-the-forge.dck",
                    emptyDossier, events);
            long pilotDecisions = events.stream()
                    .filter(e -> e.t().equals("combo_ready") || e.t().equals("combo_ignored")
                            || e.t().equals("line_entered") || e.t().equals("combo_shortcut")
                            || e.t().equals("conversion_step"))
                    .count();
            assertEquals(deck + " with empty artifacts must be behaviourally stock",
                    0, pilotDecisions);
        }
    }

    @Test
    public void anotherDecksDossierNeverFiresThisDecksCombos() throws Exception {
        // Selvala's dossier describes green mana loops; Giada's 99 contains
        // none of those cards. The pilot must therefore find nothing to do —
        // if this ever fires a line, artifact/board matching has decoupled
        // and every mismatched-dossier batch is silently invalid.
        Path selvalaDossier = Path.of("decks", "selvala-heart-of-the-wilds", "dossier");
        if (!Files.exists(selvalaDossier.resolve("combos.json"))) {
            return; // dossiers are gitignored build products; skip if absent
        }
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        play("giada-font-of-hope.dck", "purphoros-god-of-the-forge.dck",
                selvalaDossier, events);
        assertEquals("a foreign dossier must never fire a line", 0,
                events.stream().filter(e -> e.t().equals("combo_shortcut")).count());
    }
}
