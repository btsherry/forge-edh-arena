package forge.arena.ingest;

import java.io.File;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import forge.arena.bootstrap.ArenaBootstrap;

/**
 * CLI for Gate 0 ingest — the first slice of `arena prep <deck>` (v3.3).
 *
 * <p>Usage: {@code IngestMain <input> --id <deck-id> [--commander <name>]...
 * [--out <dir>=decks] [--source homebrew|netdeck] [--bracket N]
 * [--name <display name>] [--notes <text>]}. Assets dir via
 * {@code -Darena.assets.dir} (default ../forge-gui).
 */
public final class IngestMain {

    private IngestMain() {
    }

    public static void main(String[] args) throws Exception {
        Path input = Path.of(args[0]);
        String id = null;
        Path out = Path.of("decks");
        String source = "homebrew";
        Integer bracket = null;
        String name = null;
        String notes = null;
        List<String> commanders = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            switch (args[i]) {
                case "--id" -> id = args[++i];
                case "--commander" -> commanders.add(args[++i]);
                case "--out" -> out = Path.of(args[++i]);
                case "--source" -> source = args[++i];
                case "--bracket" -> bracket = Integer.parseInt(args[++i]);
                case "--name" -> name = args[++i];
                case "--notes" -> notes = args[++i];
                default -> throw new IllegalArgumentException("unknown option: " + args[i]);
            }
        }
        if (id == null) {
            throw new IllegalArgumentException("--id <deck-id> is required");
        }
        String assets = System.getProperty(ArenaBootstrap.ASSETS_DIR_PROPERTY, "../forge-gui");
        ArenaBootstrap.initialize(new File(assets));

        Ingest.Result result = Ingest.run(new Ingest.Spec(
                input, id, out, source, bracket, name, notes,
                commanders.isEmpty() ? null : commanders));
        System.out.println("dossier: " + result.dossierDir());
        System.out.println("cards: " + result.cards() + "  unresolved: " + result.unresolved().size());
        result.warnings().forEach(w -> System.out.println("warning: " + w));
    }
}
