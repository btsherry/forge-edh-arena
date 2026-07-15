package forge.arena.report;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertFalse;
import static org.testng.AssertJUnit.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.testng.annotations.Test;

/** Golden test for the run.log line format (plan §5 v3.2 example block). */
public class RunLogRendererTest {

    @Test
    public void gameStartLineMatchesGoldenFormat() {
        ArenaEvent e = ArenaEvent.of("game_start", null, null)
                .with("seats", List.of("selvala-b3", "net-krenko"))
                .with("seed", 4200417L);
        Optional<String> line = RunLogRenderer.render(e, "2", 417, RunLogRenderer.Tier.DEFAULT);
        assertEquals("[w2 g0417] game start  seats: [selvala-b3, net-krenko]  seed=4200417", line.orElseThrow());
    }

    @Test
    public void winLineCarriesFullAttribution() {
        ArenaEvent e = ArenaEvent.of("game_end", 7, null)
                .with("result", "win")
                .with("winner_seat", 0)
                .with("winner", "seat0-Selvala")
                .with("win_condition", "AllOpponentsLost")
                .with("turns", 7);
        String line = RunLogRenderer.render(e, "2", 417, RunLogRenderer.Tier.DEFAULT).orElseThrow();
        assertEquals("[w2 g0417 t7] WIN    seat 0 seat0-Selvala  (AllOpponentsLost, 7 turns)", line);
    }

    @Test
    public void timeoutDrawLineNamesTheLimitingFactor() {
        ArenaEvent e = ArenaEvent.of("game_end", 30, null)
                .with("result", "timeout_draw")
                .with("win_condition", "Draw")
                .with("turns", 30)
                .with("limiting_factor", "turns");
        String line = RunLogRenderer.render(e, "0", 3, RunLogRenderer.Tier.DEFAULT).orElseThrow();
        assertEquals("[w0 g0003 t30] TIMEOUT_DRAW  (limit: turns, 30 turns)", line);
    }

    @Test
    public void routeRejectionShowsPredicateNumbers() {
        ArenaEvent e = ArenaEvent.of("route_rejected", 7, 0)
                .with("route", "SPREAD_COMBAT")
                .with("failed_predicate", "alpha>=table_life+blockers")
                .with("predicates", Map.of("alpha", 34));
        String line = RunLogRenderer.render(e, "2", 417, RunLogRenderer.Tier.DEFAULT).orElseThrow();
        assertEquals("[w2 g0417 t7 s0] route  SPREAD_COMBAT rejected  (alpha>=table_life+blockers)", line);
    }

    @Test
    public void verbosityTiersGateEngineTicks() {
        ArenaEvent turn = ArenaEvent.of("turn_begin", 5, 1);
        assertFalse("default tier must drop turn ticks",
                RunLogRenderer.render(turn, "1", 1, RunLogRenderer.Tier.DEFAULT).isPresent());
        assertEquals("[w1 g0001 t5 s1] turn 5 begins",
                RunLogRenderer.render(turn, "1", 1, RunLogRenderer.Tier.VERBOSE).orElseThrow());

        ArenaEvent tutor = ArenaEvent.of("tutor_decision", 5, 0)
                .with("source", "Green Sun's Zenith").with("chosen", "Temur Sabertooth");
        assertTrue("combo-layer decisions always render",
                RunLogRenderer.render(tutor, "1", 1, RunLogRenderer.Tier.DEFAULT).isPresent());
    }
}
