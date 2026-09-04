package forge.arena.interactive;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.testng.Assert;
import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.deck.Deck;

/**
 * BL-12 (group {@code extended}), GUI-free: the launcher's two extracted
 * invariants. {@link GuiPilotMatch#buildRoster} is item R's one source of
 * truth for the seat order (all-AI: Urza, Giada, Purphoros, Selvala; human:
 * the human's deck at seat 0 then the first three roster decks that are not
 * it; exactly four seats or loud failure). {@link GuiPilotMatch#verifyRoster}
 * is plan item 7's start invariant: every deck loads at 100 real cards or the
 * launch is refused with {@code launch-status.json} naming the deck.
 *
 * <p>The human seat's lobby-player wiring ({@code advisorLobbyOrGuiPlayer})
 * is NOT exercised here: its plain branch is {@code GamePlayerUtil.getGuiPlayer()},
 * which needs the desktop {@code GuiBase} interface installed.
 */
public class GuiPilotMatchRosterTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String URZA = "urza-lord-high-artificer.dck";
    private static final String GIADA = "giada-font-of-hope.dck";
    private static final String PURPHOROS = "purphoros-god-of-the-forge.dck";
    private static final String SELVALA = "selvala-heart-of-the-wilds.dck";

    /** A temp copy of the shipped forge-arena/decks/*.dck (surefire runs in forge-arena/). */
    private static Path decksDir;
    private static List<String> shipped;

    @BeforeClass(groups = "extended")
    public static void boot() throws Exception {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
        decksDir = Files.createTempDirectory("roster-decks");
        shipped = new ArrayList<>();
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(Path.of("decks"), "*.dck")) {
            for (Path p : ds) {
                Files.copy(p, decksDir.resolve(p.getFileName().toString()));
                shipped.add(p.getFileName().toString());
            }
        }
        shipped.sort(null);
        Assert.assertEquals(shipped.size(), 10, "ten shipped decks expected, saw " + shipped);
    }

    // ---- buildRoster ----------------------------------------------------------

    @Test(groups = "extended", timeOut = 30_000)
    public void rosterConstantsAreTheDefaultTable() {
        Assert.assertEquals(Arrays.asList(GuiPilotMatch.DECKS), List.of(URZA, GIADA, PURPHOROS, SELVALA));
        Assert.assertEquals(GuiPilotMatch.DEFAULT_HUMAN_DECK, SELVALA);
    }

    @Test(groups = "extended", timeOut = 30_000)
    public void allAiRosterIsTheDefaultTableInSeatOrder() {
        List<String> r = GuiPilotMatch.buildRoster(GuiPilotMatch.DECKS, GuiPilotMatch.DEFAULT_HUMAN_DECK, true);
        Assert.assertEquals(r, List.of(URZA, GIADA, PURPHOROS, SELVALA));
    }

    @Test(groups = "extended", timeOut = 30_000)
    public void humanOnSelvalaSitsAtSeatZeroWithTheOtherThreeBehind() {
        List<String> r = GuiPilotMatch.buildRoster(GuiPilotMatch.DECKS, SELVALA, false);
        Assert.assertEquals(r, List.of(SELVALA, URZA, GIADA, PURPHOROS));
    }

    @Test(groups = "extended", timeOut = 30_000)
    public void humanOnANonRosterDeckBumpsTheLastRosterDeck() {
        List<String> r = GuiPilotMatch.buildRoster(GuiPilotMatch.DECKS, "sheoldreds-sacrifice.dck", false);
        Assert.assertEquals(r, List.of("sheoldreds-sacrifice.dck", URZA, GIADA, PURPHOROS));
    }

    @Test(groups = "extended", timeOut = 30_000)
    public void humanOnGiadaKeepsTheRemainingRosterOrder() {
        List<String> r = GuiPilotMatch.buildRoster(GuiPilotMatch.DECKS, GIADA, false);
        Assert.assertEquals(r, List.of(GIADA, URZA, PURPHOROS, SELVALA));
        // the slug rule: a path or a bare slug still identifies the human's deck
        Assert.assertEquals(GuiPilotMatch.buildRoster(GuiPilotMatch.DECKS, "some/dir/" + GIADA, false).subList(1, 4),
                List.of(URZA, PURPHOROS, SELVALA));
    }

    @Test(groups = "extended", timeOut = 30_000)
    public void threeEntryRosterThrowsNamingTheProperty() {
        String[] three = {URZA, GIADA, PURPHOROS};
        for (boolean allAi : new boolean[] {true, false}) {
            try {
                GuiPilotMatch.buildRoster(three, URZA, allAi);
                Assert.fail("a three-deck roster must not build a pod (allAi=" + allAi + ")");
            } catch (IllegalStateException e) {
                Assert.assertTrue(e.getMessage().contains("arena.seat.decks"),
                        "the failure must name the property to fix: " + e.getMessage());
                Assert.assertTrue(e.getMessage().contains("built 3"), e.getMessage());
            }
        }
    }

    // ---- verifyRoster ---------------------------------------------------------

    private static JsonNode status(Path statusFile) throws Exception {
        Assert.assertTrue(Files.isRegularFile(statusFile), "launch-status.json must be written: " + statusFile);
        return MAPPER.readTree(Files.readString(statusFile, StandardCharsets.UTF_8));
    }

    @Test(groups = "extended", timeOut = 120_000)
    public void defaultTableVerifiesAtOneHundredCardsEach() throws Exception {
        Path status = Files.createTempDirectory("roster-ok").resolve("launch-status.json");
        List<Deck> decks = GuiPilotMatch.verifyRoster(decksDir.toFile(), Arrays.asList(GuiPilotMatch.DECKS), status);
        Assert.assertEquals(decks.size(), 4);
        for (Deck d : decks) {
            Assert.assertTrue(DeckLoadProbe.playabilityProblems(d).isEmpty(), d.getName());
        }
        JsonNode st = status(status);
        Assert.assertTrue(st.get("ok").asBoolean(), st.toString());
        Assert.assertTrue(st.get("detail").asText().contains("4 decks verified"), st.toString());
    }

    @Test(groups = "extended", timeOut = 120_000)
    public void allTenShippedDecksVerify() throws Exception {
        Path status = Files.createTempDirectory("roster-ten").resolve("launch-status.json");
        List<Deck> decks = GuiPilotMatch.verifyRoster(decksDir.toFile(), shipped, status);
        Assert.assertEquals(decks.size(), 10);
        JsonNode st = status(status);
        Assert.assertTrue(st.get("ok").asBoolean(), st.toString());
        Assert.assertTrue(st.get("detail").asText().contains("10 decks verified"), st.toString());
    }

    @Test(groups = "extended", timeOut = 120_000)
    public void aNinetyNineCardDeckRefusesTheLaunchAndNamesTheDeck() throws Exception {
        // drop ONE single-copy main-deck line from Giada -> 99 cards
        List<String> lines = Files.readAllLines(decksDir.resolve(GIADA), StandardCharsets.UTF_8);
        List<String> out = new ArrayList<>();
        boolean inMain = false;
        boolean dropped = false;
        for (String line : lines) {
            if (line.startsWith("[")) {
                inMain = "[Main]".equals(line.trim());
            } else if (inMain && !dropped && line.startsWith("1 ")) {
                dropped = true;
                continue;
            }
            out.add(line);
        }
        Assert.assertTrue(dropped, "no single-copy main-deck line found in " + GIADA);
        Files.write(decksDir.resolve("giada-99.dck"), out, StandardCharsets.UTF_8);

        Path status = Files.createTempDirectory("roster-99").resolve("launch-status.json");
        try {
            GuiPilotMatch.verifyRoster(decksDir.toFile(), List.of("giada-99.dck", URZA, PURPHOROS, SELVALA), status);
            Assert.fail("a 99-card deck must refuse the launch");
        } catch (IllegalStateException e) {
            Assert.assertTrue(e.getMessage().contains("giada-99.dck"), e.getMessage());
            Assert.assertTrue(e.getMessage().contains("99 cards resolved, expected 100"), e.getMessage());
        }
        JsonNode st = status(status);
        Assert.assertFalse(st.get("ok").asBoolean(), st.toString());
        String detail = st.get("detail").asText();
        Assert.assertTrue(detail.contains("seat 0 deck giada-99.dck"), detail);
        Assert.assertTrue(detail.contains("99 cards resolved, expected 100"), detail);
    }

    @Test(groups = "extended", timeOut = 120_000)
    public void aMissingDeckFileRefusesTheLaunch() throws Exception {
        Path status = Files.createTempDirectory("roster-missing").resolve("launch-status.json");
        try {
            GuiPilotMatch.verifyRoster(decksDir.toFile(), List.of(URZA, "no-such-deck.dck", PURPHOROS, SELVALA), status);
            Assert.fail("a missing deck file must refuse the launch");
        } catch (IllegalStateException e) {
            Assert.assertTrue(e.getMessage().contains("missing or unreadable"), e.getMessage());
        }
        JsonNode st = status(status);
        Assert.assertFalse(st.get("ok").asBoolean(), st.toString());
        String detail = st.get("detail").asText();
        Assert.assertTrue(detail.contains("seat 1 deck no-such-deck.dck"), detail);
        Assert.assertTrue(detail.contains("missing or unreadable"), detail);
    }
}
