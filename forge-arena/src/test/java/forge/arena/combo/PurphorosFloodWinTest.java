package forge.arena.combo;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

import org.testng.annotations.BeforeClass;
import org.testng.annotations.Test;

import com.google.common.eventbus.Subscribe;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.arena.engine.ArenaGameResult;
import forge.arena.engine.ArenaLimits;
import forge.arena.engine.EngineFacade;
import forge.arena.engine.GameAware;
import forge.arena.engine.SeatSpec;
import forge.arena.report.ArenaEvent;
import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * The PR-27b golden: the SECOND deck wins deliberately. Purphoros on the
 * battlefield, Dualcaster + Twinflame in hand — the pilot must detect the
 * loop, prove one entry's pings on the game copy, select DIRECT damage, and
 * flood the table to death with the rules engine pricing every trigger. The
 * generality thesis in one game: an archetype, a route, and a conversion
 * shape Selvala never used.
 */
public class PurphorosFloodWinTest {

    @BeforeClass
    public void bootstrap() {
        ArenaBootstrap.initialize(new File("..", "forge-gui"));
    }

    /** Turn 3: Purphoros deployed, loop pieces in hand, mana on board. */
    static final class BoardProbe implements GameAware {
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
            forge.game.card.Card purphoros = p0.getCommanders().get(0);
            game.getAction().moveToPlay(purphoros, null, null);
            for (String name : List.of("Twinflame", "Dualcaster Mage")) {
                forge.game.card.Card card = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard(name), p0);
                game.getAction().moveTo(ZoneType.Hand, card, null, null);
            }
            for (int i = 0; i < 5; i++) {
                forge.game.card.Card mountain = forge.game.card.Card.fromPaperCard(
                        forge.StaticData.instance().getCommonCards().getCard("Mountain"), p0);
                game.getAction().moveToPlay(mountain, null, null);
            }
            game.getTriggerHandler().setSuppressAllTriggers(false);
            game.getAction().checkStateEffects(true);
        }
    }

    @Test
    public void purphorosFloodsTheTableToDeath() throws Exception {
        // hand-crafted dossier: the artifacts EngineFacade loads for a combo
        // seat, minimal and self-contained (the recorded Spellbook fixture is
        // Selvala's — this golden must not depend on local prep state)
        Path dossier = Files.createTempDirectory("flood-win");
        Files.writeString(dossier.resolve("combos.json"), """
                {"schema": "arena.combos/1", "deck_hash": "x",
                 "combos": [{"id": "147-1235", "cards": [
                     {"name": "Dualcaster Mage"}, {"name": "Twinflame"}]}]}""");
        Files.writeString(dossier.resolve("route-coverage.json"), """
                {"schema": "arena.route-coverage/2",
                 "deck": {
                   "payoffs": {"ping_each_opponent": ["Purphoros, God of the Forge",
                                                      "Agate Instigator"]},
                   "routes": [{"route": "DIRECT_DAMAGE_LOOP", "origin": "direct",
                               "support": "intrinsic"}]}}""");
        Files.writeString(dossier.resolve("dossier.json"),
                "{\"deck_id\":\"t\",\"deck_hash\":\"x\",\"status\":{},\"versions\":{}}");

        System.setProperty("arena.stall.dir",
                Files.createTempDirectory("flood-stalls").toString());
        List<ArenaEvent> events = new CopyOnWriteArrayList<>();
        Consumer<ArenaEvent> sink = events::add;
        ArenaGameResult result = EngineFacade.playCommanderGame(
                List.of(SeatSpec.comboAware(new File("decks/purphoros-god-of-the-forge.dck"),
                                dossier),
                        SeatSpec.goldfish(new File("decks/selvala-heart-of-the-wilds.dck"))),
                42L, new ArenaLimits(10, 300, 2000), sink, new BoardProbe());

        ArenaEvent shortcut = events.stream()
                .filter(e -> e.t().equals("combo_shortcut")).findFirst()
                .orElseThrow(() -> new AssertionError("flood never fired; events: "
                        + events.stream().map(ArenaEvent::t).toList()));
        assertEquals("147-1235", shortcut.fields().get("combo"));
        assertTrue(events.stream().anyMatch(e -> e.t().equals("route_selected")
                && "DIRECT_DAMAGE_LOOP".equals(e.fields().get("route"))));

        assertEquals("Purphoros must WIN by flood (got " + result.type() + ", "
                + result.winCondition() + ")", ArenaGameResult.ResultType.WIN, result.type());
        assertEquals(0, result.winnerSeat());
    }
}
