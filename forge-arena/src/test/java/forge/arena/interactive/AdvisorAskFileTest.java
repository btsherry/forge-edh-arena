package forge.arena.interactive;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Stream;

import org.testng.Assert;
import org.testng.annotations.AfterMethod;
import org.testng.annotations.BeforeMethod;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The Advisor tab's "Ask" field (Ben, 2026-09-04) publishes one JSON file per
 * question under {@code logs/control/ask/}; {@code advisor_runner.py} scans
 * {@code ask-<millis>-<serial>.json}, deletes on pickup and answers in the
 * stream. These tests pin the file contract the two sides share: name shape,
 * numeric order, JSON the runner can load, sanitisation, and "empty writes
 * nothing" — all without a display.
 */
public class AdvisorAskFileTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private Path tmp;
    private String prevLogsDir;

    @BeforeMethod
    public void setUp() throws IOException {
        tmp = Files.createTempDirectory("advisor-ask");
        prevLogsDir = System.getProperty("arena.runner.logs.dir");
        System.setProperty("arena.runner.logs.dir", tmp.toString());
    }

    @AfterMethod(alwaysRun = true)
    public void tearDown() throws IOException {
        if (prevLogsDir == null) {
            System.clearProperty("arena.runner.logs.dir");
        } else {
            System.setProperty("arena.runner.logs.dir", prevLogsDir);
        }
        if (tmp != null && Files.exists(tmp)) {
            try (Stream<Path> walk = Files.walk(tmp)) {
                walk.sorted(Comparator.reverseOrder()).forEach(p -> p.toFile().delete());
            }
        }
    }

    private static List<String> names(final File dir) {
        final List<String> out = new ArrayList<>();
        final String[] ls = dir.list();
        if (ls != null) {
            for (final String s : ls) {
                out.add(s);
            }
        }
        out.sort(null);
        return out;
    }

    @Test
    public void questionLandsAsOneJsonFileTheRunnerCanLoad() throws IOException {
        final File f = AiControlFile.askAdvisor("  Should I hold\n Teferi's \"Protection\"\tthis turn?  ");
        Assert.assertNotNull(f, "a non-empty question is written");
        Assert.assertEquals(f.getParentFile(), new File(tmp.toFile(), "control/ask"),
                "questions live under logs/control/ask so arena-stop's control/ wipe clears them");
        Assert.assertTrue(f.getName().matches("ask-\\d+-\\d{3}\\.json"), f.getName());
        final JsonNode n = MAPPER.readTree(f);
        Assert.assertEquals(n.get("ask").asText(), "Should I hold Teferi's \"Protection\" this turn?",
                "whitespace runs collapse to one space; quotes survive the escape round-trip");
        Assert.assertTrue(n.get("ts").asLong() > 0L);
        Assert.assertEquals(names(f.getParentFile()).size(), 1, "no .tmp left behind by the atomic move");
    }

    @Test
    public void emptyOrBlankQuestionsWriteNothing() {
        Assert.assertNull(AiControlFile.askAdvisor(""));
        Assert.assertNull(AiControlFile.askAdvisor("  \n\t "));
        Assert.assertNull(AiControlFile.askAdvisor(null));
        Assert.assertFalse(AiControlFile.askDir().exists(), "no directory is created for nothing");
    }

    @Test
    public void controlCharactersNeverReachTheFileAndLongTextIsCapped() throws IOException {
        final File f = AiControlFile.askAdvisor("abc\r\nd");
        Assert.assertEquals(MAPPER.readTree(f).get("ask").asText(), "ab c d");
        final StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 700; i++) {
            sb.append('x');
        }
        final File g = AiControlFile.askAdvisor(sb.toString());
        Assert.assertEquals(MAPPER.readTree(g).get("ask").asText().length(), AiControlFile.ASK_MAX_CHARS);
    }

    @Test
    public void filesSortInSendOrderByNumericParts() {
        final File a = AiControlFile.askAdvisor("first");
        final File b = AiControlFile.askAdvisor("second");
        final File c = AiControlFile.askAdvisor("third");
        // The runner orders by (millis, serial) as integers; the serial is
        // zero-padded so even a plain lexical sort agrees within one millisecond.
        Assert.assertTrue(a.getName().compareTo(b.getName()) < 0, a.getName() + " < " + b.getName());
        Assert.assertTrue(b.getName().compareTo(c.getName()) < 0, b.getName() + " < " + c.getName());
    }

    @Test
    public void jsonStringEscapesExactlyWhatJsonNeeds() throws IOException {
        final String raw = "quote \" backslash \\ tab\t nl\n end";
        final JsonNode n = MAPPER.readTree("{\"v\": " + AiControlFile.jsonString(raw) + "}");
        Assert.assertEquals(n.get("v").asText(), raw);
    }
}
