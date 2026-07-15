package forge.arena.ingest;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Gate 0 list parser (v3.3: files/paste only — URL fetching deferred).
 * Accepts Forge .dck sections, plain "1 Card Name" lists, Moxfield text
 * exports ("1 Card Name (SET) 123 *F*"), and Archidekt text exports
 * ("1x Card Name (set) [Commander{top}]"). Commander is identified by a
 * [Commander] section, a "Commander:" header line, an Archidekt
 * [Commander...] category tag, or a trailing *CMDR* marker.
 */
public final class DeckListParser {

    public record Entry(String name, int qty) {
    }

    public record Parsed(List<Entry> commanders, List<Entry> main, List<String> warnings) {
    }

    /** "1x Name" or "1 Name", with optional (SET) collector suffix and [tags]. */
    private static final Pattern LINE = Pattern.compile(
            "^(\\d+)\\s*x?\\s+(.+?)\\s*$", Pattern.CASE_INSENSITIVE);
    /** Moxfield/Archidekt suffixes: (SET) 123, foil flags, category tags. */
    private static final Pattern SET_SUFFIX = Pattern.compile(
            "\\s*\\(([A-Za-z0-9]{2,6})\\)\\s*[A-Za-z0-9-]*\\s*(\\*[A-Z]+\\*)?\\s*$");
    private static final Pattern TAG_SUFFIX = Pattern.compile("\\s*\\[([^]]*)]\\s*$");
    private static final Pattern CMDR_MARKER = Pattern.compile("\\s*\\*CMDR\\*\\s*$", Pattern.CASE_INSENSITIVE);

    private DeckListParser() {
    }

    public static Parsed parse(List<String> lines) {
        List<Entry> commanders = new ArrayList<>();
        List<Entry> main = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        String section = "main";

        for (String raw : lines) {
            String line = raw.strip();
            if (line.isEmpty() || line.startsWith("#") || line.startsWith("//")) {
                continue;
            }
            String header = headerOf(line);
            if (header != null) {
                section = header;
                continue;
            }
            if (section.equals("skip") || section.equals("metadata")) {
                continue;
            }

            boolean isCommander = section.equals("commander");
            // Archidekt category tags: [Commander{top}], [Land], ...
            Matcher tag = TAG_SUFFIX.matcher(line);
            if (tag.find()) {
                if (tag.group(1).toLowerCase().startsWith("commander")) {
                    isCommander = true;
                }
                line = line.substring(0, tag.start()).strip();
            }
            Matcher cmdr = CMDR_MARKER.matcher(line);
            if (cmdr.find()) {
                isCommander = true;
                line = line.substring(0, cmdr.start()).strip();
            }

            Matcher m = LINE.matcher(line);
            if (!m.matches()) {
                warnings.add("unparsed line: " + raw.strip());
                continue;
            }
            int qty = Integer.parseInt(m.group(1));
            String name = m.group(2);
            Matcher set = SET_SUFFIX.matcher(name);
            if (set.find()) {
                name = name.substring(0, set.start()).strip();
            }
            name = name.replaceAll("\\s+", " ");
            (isCommander ? commanders : main).add(new Entry(name, qty));
        }
        return new Parsed(commanders, main, warnings);
    }

    private static String headerOf(String line) {
        String l = line.toLowerCase();
        if (l.equals("[commander]") || l.equals("commander:") || l.equals("commander")) {
            return "commander";
        }
        if (l.equals("[main]") || l.equals("deck") || l.equals("deck:") || l.equals("mainboard:")
                || l.equals("main:")) {
            return "main";
        }
        if (l.equals("[metadata]") || l.equals("[general]")) {
            return "metadata";
        }
        if (l.equals("[sideboard]") || l.equals("sideboard:") || l.equals("sideboard")
                || l.equals("considering:") || l.equals("maybeboard:")
                || (l.startsWith("[") && l.endsWith("]"))) {
            return "skip"; // unknown .dck sections (Avatar, Schemes, ...) are not the 99
        }
        return null;
    }
}
