package forge.arena.engine;

import java.util.List;

import org.testng.annotations.Test;

/** The scripted-state loader must accept multiplayer (p0..p3) state text. */
public class ArenaGameStateTest {

    @Test
    public void parsesMultiplayerStateKeys() {
        ArenaGameState state = new ArenaGameState();
        state.parse(List.of(
                "turn=3",
                "removesummoningsickness=true",
                "p0life=25",
                "p1life=40",
                "p2life=13",
                "p3life=40",
                "p0battlefield=Forest;Forest;Selvala, Heart of the Wilds",
                "p0hand=Umbral Mantle"));
        // parse stores text without resolving cards (resolution happens at apply,
        // against the card DB) — reaching here without an exception is the assertion.
    }
}
