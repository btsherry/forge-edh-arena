package forge.arena.bootstrap;

import java.io.File;

import forge.GuiDesktop;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.util.MyRandom;

/**
 * Headless initialization of the Forge card database from an explicit assets
 * location (plan §2: bootstrap/). Replaces the cwd-sensitive
 * {@code GuiDesktop.getAssetsDir()} heuristic with an explicit path so callers
 * (tests, arena prep, batch workers) do not depend on their working directory.
 *
 * <p>Must be called before any Forge class that touches
 * {@code forge.localinstance.properties.ForgeConstants} is loaded — that class
 * captures the assets dir in static finals at class-load time.
 */
public final class ArenaBootstrap {

    /** System property overriding the forge-gui assets directory. */
    public static final String ASSETS_DIR_PROPERTY = "arena.assets.dir";

    private static boolean initialized = false;

    private ArenaBootstrap() {
    }

    /**
     * Initialize using {@link #ASSETS_DIR_PROPERTY} if set, else
     * {@code ../forge-gui} relative to the working directory (the layout when
     * running from any module directory of the fork).
     */
    public static synchronized void initialize() {
        String prop = System.getProperty(ASSETS_DIR_PROPERTY);
        initialize(prop != null ? new File(prop) : new File("..", "forge-gui"));
    }

    /** Initialize from an explicit forge-gui directory (the one containing {@code res/}). */
    public static synchronized void initialize(File forgeGuiDir) {
        if (initialized) {
            return;
        }
        File cards = new File(forgeGuiDir, "res" + File.separator + "cardsfolder");
        if (!cards.isDirectory()) {
            throw new IllegalStateException(
                    "Not a forge-gui assets dir (no res/cardsfolder): " + forgeGuiDir.getAbsolutePath());
        }
        String assetsDir = forgeGuiDir.getPath();
        if (!assetsDir.endsWith(File.separator)) {
            assetsDir += File.separator;
        }
        GuiBase.setInterface(new ExplicitAssetsGuiDesktop(assetsDir));
        FModel.initialize(null, null);
        initialized = true;
    }

    public static synchronized boolean isInitialized() {
        return initialized;
    }

    /**
     * Seed Forge's single RNG seam for a deterministic game.
     *
     * <p>All engine and AI randomness routes through {@link MyRandom} — verified
     * 2026-07-15 against commit 0eec0a16d0: every {@code Collections.shuffle} in
     * forge-game/forge-ai passes {@code MyRandom.getRandom()}, and there are no
     * {@code new Random()}, {@code ThreadLocalRandom}, or {@code Math.random}
     * call sites in those modules. The seam is a <b>global static</b>, so
     * determinism requires one game per JVM process (the worker-pool model).
     */
    public static void seedRng(long seed) {
        // ARENA-PATCH 2: setSeed, not setRandom. setRandom binds only the
        // CALLING thread, and the game runs on its own thread — so the seed
        // has to be set for every thread that will draw, not just this one.
        MyRandom.setSeed(seed);
    }

    /** GuiDesktop with the assets dir pinned to an explicit path. */
    private static final class ExplicitAssetsGuiDesktop extends GuiDesktop {
        private final String assetsDir;

        private ExplicitAssetsGuiDesktop(String assetsDir) {
            this.assetsDir = assetsDir;
        }

        @Override
        public String getAssetsDir() {
            return assetsDir;
        }
    }
}
