package forge.arena.harness;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Deck identity hash (plan §3): sha256 over the sorted card lines of the
 * Commander + Main sections of a .dck file. Order-insensitive,
 * count-sensitive, commander-inclusive; sideboard and metadata excluded.
 * Parses the .dck as plain text — no Forge imports (ArchUnit).
 */
public final class DeckHash {

    private static final Pattern CARD_LINE = Pattern.compile("^(\\d+)\\s+(.+?)\\s*$");

    private DeckHash() {
    }

    public static String of(Path dckFile) throws IOException {
        List<String> entries = new ArrayList<>();
        String section = "";
        for (String raw : Files.readAllLines(dckFile, StandardCharsets.UTF_8)) {
            String line = raw.strip();
            if (line.isEmpty()) {
                continue;
            }
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.substring(1, line.length() - 1).toLowerCase();
                continue;
            }
            if (!section.equals("commander") && !section.equals("main")) {
                continue;
            }
            Matcher m = CARD_LINE.matcher(line);
            if (m.matches()) {
                entries.add(m.group(1) + "x" + m.group(2));
            }
        }
        if (entries.isEmpty()) {
            throw new IOException("no card lines found in " + dckFile);
        }
        entries.sort(String::compareTo);
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(String.join("|", entries).getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
