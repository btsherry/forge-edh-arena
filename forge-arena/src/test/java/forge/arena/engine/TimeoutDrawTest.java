package forge.arena.engine;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.util.List;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import forge.arena.bootstrap.ArenaBootstrap;

/**
 * Plan §8 TimeoutDrawTest: a turn-capped game must end as timeout_draw with
 * the limiting factor recorded — timeouts are data, never dropped.
 */
public class TimeoutDrawTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    @Test
    public void turnCapEndsGameAsTimeoutDrawWithFactorRecorded() {
        List<SeatSpec> seats = List.of(
                SeatSpec.of(new File("decks/giada-font-of-hope.dck")),
                SeatSpec.of(new File("decks/purphoros-god-of-the-forge.dck")),
                SeatSpec.of(new File("decks/selvala-heart-of-the-wilds.dck")),
                SeatSpec.of(new File("decks/urza-lord-high-artificer.dck")));

        ArenaGameResult result = EngineFacade.playCommanderGame(
                seats, 42L, new ArenaLimits(3, 300, 0));

        assertEquals(ArenaGameResult.ResultType.TIMEOUT_DRAW, result.type());
        assertEquals(ArenaGameResult.LimitingFactor.TURNS, result.limitingFactor());
        assertEquals("no winner in a timeout draw", -1, result.winnerSeat());
        assertTrue("game must stop right after the cap (turns=" + result.turns() + ")",
                result.turns() >= 3 && result.turns() <= 4);
        assertTrue("turn-capped game must finish well under the wall clock",
                result.durationMs() < 300_000);
    }
}
