package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.prep.ComboPrep;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * The plan §8 golden, PR-18 form (SelvalaMantleWins): given only REACHABLE
 * pieces — Selvala in the command zone, Umbral Mantle in hand, payoffs in
 * hand, mana on board — the pilot must assemble the line itself (cast, cast,
 * equip), prove it, fire the shortcut, and WIN the game. No pre-attached
 * boards: this is the exact gap the first e2e run exposed.
 */
public class SelvalaGoldenWinTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    /** Turn 3: payoff-stacked hand + mana base; Selvala stays in the command zone. */
    static final class HandProbe implements GameAware {
        private Game game;
        private final AtomicBoolean applied = new AtomicBoolean();

        @Override
        public void onGameCreated(Game game) {
            this.game = game;
        }

        @Subscribe
        public void onTurn(GameEventTurnBegan event) {
            if (event.turnNumber() < 3 || !applied.compareAndSet(false, true)) {
                return;
            }
            Player p0 = game.getPlayers().get(0);
            game.getTriggerHandler().setSuppressAllTriggers(true);
            for (String name : List.of("Umbral Mantle", "Craterhoof Behemoth",
                    "Finale of Devastation")) {
                forge.game.card.Card card = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard(name), p0);
                game.getAction().moveTo(ZoneType.Hand, card, null, null);
            }
            for (int i = 0; i < 8; i++) {
                forge.game.card.Card forest = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard("Forest"), p0);
                game.getAction().moveToPlay(forest, null, null);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }
    }

    @Test
    public void selvalaAssemblesTheLineHerselfAndWins() throws Exception {
        Path dossier = Files.createTempDirectory("golden-win");
        MAPPER.writeValue(dossier.resolve("deck-cards.json").toFile(), Map.of(
                "schema", "arena.deck-cards/1", "deck_id", "t",
                "cards", List.of(
                        Map.of("name", "Selvala, Heart of the Wilds", "qty", 1, "zone", "commander"),
                        Map.of("name", "Umbral Mantle", "qty", 1, "zone", "main")),
                "unresolved", List.of()));
        Files.writeString(dossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"d7498c0379debdfa\",\"status\":{},\"versions\":{}}");
        try (InputStream in = getClass().getResourceAsStream("/fixtures/spellbook-recorded.json")) {
            Files.write(dossier.resolve("spellbook-raw.json"), in.readAllBytes());
        }
        ComboPrep.run(dossier, (url, body) -> {
            throw new IllegalStateException("no network in tests");
        });

        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("golden-stalls").toString());
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/selvala-heart-of-the-wilds.dck"), dossier),
                        SeatSpec.goldfish(new File("decks/purphoros-god-of-the-forge.dck"))),
                42L, new ArenaLimits(12, 300, 2000), sink, new HandProbe());

        // the pilot assembled (stock AI may pre-deploy some pieces; at least
        // one assembly step must be the pilot's own, recorded)
        long assemblySteps = events.stream()
                .filter(e -> e.t().equals("line_step")
                        && "ASSEMBLY".equals(e.fields().get("stage")))
                .count();
        assertTrue("assembly must run, got " + assemblySteps + " steps in "
                + events.stream().map(ArenaEvent::t).toList(), assemblySteps >= 1);

        // the pool was SPENT by script (stock AI cannot see floating mana —
        // the PR-18 engine finding): at least one DEPLOY cast
        long deploySteps = events.stream()
                .filter(e -> e.t().equals("line_step")
                        && "DEPLOY".equals(e.fields().get("stage")))
                .count();
        assertTrue("DEPLOY must cast payoffs, got " + deploySteps, deploySteps >= 1);

        // the proven loop fired
        assertEquals("exactly one shortcut", 1,
                events.stream().filter(e -> e.t().equals("combo_shortcut")).count());

        // and the game ENDED in a seat-0 win — the Phase 4 exit criterion
        assertEquals("Selvala must WIN (got " + result.type() + ", "
                + result.winCondition() + ")", ArenaGameResult.ResultType.WIN, result.type());
        assertEquals(0, result.winnerSeat());
    }
}
