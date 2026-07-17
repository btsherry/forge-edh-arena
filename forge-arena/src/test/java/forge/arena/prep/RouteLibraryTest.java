package forge.arena.prep;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import org.testng.annotations.Test;

/**
 * PR-13 route library: proposed entries are inert, approved entries drive
 * coverage, and the effective version tracks exactly the approved content —
 * so proposals invalidate nothing and approvals stale old dossiers.
 */
public class RouteLibraryTest {

    private Path write(String json) throws IOException {
        Path dir = Files.createTempDirectory("route-lib");
        Path file = dir.resolve("classifications.json");
        Files.writeString(file, json);
        return file;
    }

    @Test
    public void missingFileIsAnEmptyLibraryNotAnError() throws Exception {
        RouteLibrary lib = RouteLibrary.load(Path.of("/nonexistent/classifications.json"));
        assertEquals(RouteLibrary.NO_LIBRARY, lib.effectiveVersion());
        assertTrue(lib.lookupFeature("Anything").isEmpty());
        assertTrue(lib.payoffOverrides().isEmpty());
    }

    @Test(expectedExceptions = IOException.class,
            expectedExceptionsMessageRegExp = ".*malformed.*")
    public void malformedLibraryFailsLoudlyNeverSilentlySkips() throws Exception {
        RouteLibrary.load(write("{\"totally\": \"different\"}"));
    }

    @Test
    public void onlyApprovedCurrentRulesEntriesAffectAnything() throws Exception {
        RouteLibrary lib = RouteLibrary.load(write("""
                {"schema": "arena.route-library/1",
                 "features": [
                   {"feature": "Infinite gremlin polkas", "category": "RESOURCE", "routes": [],
                    "status": "proposed", "win_routes_version": "%V%"},
                   {"feature": "Infinite kobold waltzes", "category": "LETHAL",
                    "routes": ["DIRECT_DAMAGE_LOOP"], "status": "approved", "win_routes_version": "%V%"},
                   {"feature": "Infinite stale entry", "category": "LETHAL",
                    "routes": ["DIRECT_DAMAGE_LOOP"], "status": "approved", "win_routes_version": "win-routes/1"}
                 ],
                 "payoffs": [
                   {"card": "Some Card", "payoff_class": "x_damage",
                    "status": "proposed", "win_routes_version": "%V%"},
                   {"card": "Real Payoff", "payoff_class": "haste_static",
                    "status": "approved", "win_routes_version": "%V%"}
                 ]}""".replace("%V%", RouteRules.VERSION)));

        // proposed: known (cache) but never consumed
        assertTrue(lib.knowsFeature("Infinite gremlin polkas"));
        assertTrue(lib.lookupFeature("Infinite gremlin polkas").isEmpty());
        assertTrue(lib.knowsPayoffCard("Some Card"));
        assertFalse(lib.payoffOverrides().containsKey("Some Card"));
        // approved + current rules: consumed (case-insensitive lookup)
        RouteRules.Verdict v = lib.lookupFeature("infinite KOBOLD waltzes").orElseThrow();
        assertEquals("LETHAL", v.category());
        assertEquals(List.of("DIRECT_DAMAGE_LOOP"), v.routes());
        assertEquals("library", v.ruleId());
        assertEquals(List.of("haste_static"), lib.payoffOverrides().get("Real Payoff"));
        // approved under OLD rules: orphaned on purpose
        assertTrue(lib.lookupFeature("Infinite stale entry").isEmpty());
    }

    @Test
    public void effectiveVersionTracksApprovedContentOnly() throws Exception {
        String proposedOnly = """
                {"schema": "arena.route-library/1",
                 "features": [{"feature": "F", "category": "RESOURCE", "routes": [],
                    "status": "proposed", "win_routes_version": "%V%"}],
                 "payoffs": []}""".replace("%V%", RouteRules.VERSION);
        assertEquals("proposals must not change the effective version",
                RouteLibrary.NO_LIBRARY, RouteLibrary.load(write(proposedOnly)).effectiveVersion());

        String approved = proposedOnly.replace("proposed", "approved");
        String version = RouteLibrary.load(write(approved)).effectiveVersion();
        assertFalse(RouteLibrary.NO_LIBRARY.equals(version));
        // deterministic: same approved content -> same version
        assertEquals(version, RouteLibrary.load(write(approved)).effectiveVersion());
        // different approved content -> different version
        String different = approved.replace("\"RESOURCE\"", "\"LETHAL\"");
        assertFalse(version.equals(RouteLibrary.load(write(different)).effectiveVersion()));
    }

    @Test
    public void appendProposalsDedupsAndPreservesApproved() throws Exception {
        Path file = write("""
                {"schema": "arena.route-library/1",
                 "features": [{"feature": "Known Feature", "category": "LETHAL",
                    "routes": ["DIRECT_DAMAGE_LOOP"], "status": "approved", "win_routes_version": "%V%"}],
                 "payoffs": []}""".replace("%V%", RouteRules.VERSION));
        RouteLibrary lib = RouteLibrary.load(file);
        String versionBefore = lib.effectiveVersion();

        lib.appendProposals(
                List.of(new RouteLibrary.FeatureEntry("Known Feature", "RESOURCE", List.of(),
                                "proposed", RouteRules.VERSION), // dup: must be skipped
                        new RouteLibrary.FeatureEntry("New Feature", "GUARD", List.of(),
                                "proposed", RouteRules.VERSION)),
                List.of(new RouteLibrary.PayoffEntry("New Card", "alt_win",
                        "proposed", RouteRules.VERSION)));

        RouteLibrary reloaded = RouteLibrary.load(file);
        // the approved entry survives untouched and still wins lookups
        assertEquals("LETHAL", reloaded.lookupFeature("Known Feature").orElseThrow().category());
        // new proposals are known (cache hits) but inert
        assertTrue(reloaded.knowsFeature("New Feature"));
        assertTrue(reloaded.lookupFeature("New Feature").isEmpty());
        assertTrue(reloaded.knowsPayoffCard("New Card"));
        // and the effective version did not move
        assertEquals(versionBefore, reloaded.effectiveVersion());
    }
}
