package forge.arena.engine;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

import com.google.common.eventbus.Subscribe;

import forge.game.Game;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

/**
 * PR-delta: applies a program-derived goldfish fixture to seat 0, once, at
 * the given turn — battlefield pieces into play, castable pieces into HAND
 * (so the interpreter performs its own casts), basic lands for the program's
 * declared costs. Engine-side because it moves real cards in a real game;
 * the DERIVATION (which cards, which lands) lives with the gate in prep,
 * which is why this class takes plain lists and knows nothing about
 * programs. Mirrors the probes the combo tests force boards with.
 */
public final class ProgramFixtureProbe implements GameAware {

    private final int applyTurn;
    private final List<String> battlefield;
    private final List<String> hand;
    private final String basicLand;
    private final int landCount;
    private Game game;
    private final AtomicBoolean applied = new AtomicBoolean();

    public ProgramFixtureProbe(int applyTurn, List<String> battlefield, List<String> hand,
            String basicLand, int landCount) {
        this.applyTurn = applyTurn;
        this.battlefield = battlefield;
        this.hand = hand;
        this.basicLand = basicLand;
        this.landCount = landCount;
    }

    @Override
    public void onGameCreated(Game game) {
        this.game = game;
    }

    @Subscribe
    public void onTurn(GameEventTurnBegan event) {
        if (event.turnNumber() < applyTurn || !applied.compareAndSet(false, true)) {
            return;
        }
        Player p0 = game.getPlayers().get(0);
        game.getTriggerHandler().setSuppressAllTriggers(true);
        for (String name : battlefield) {
            game.getAction().moveToPlay(card(name, p0), null, null);
        }
        for (String name : hand) {
            game.getAction().moveTo(ZoneType.Hand, card(name, p0), null, null);
        }
        for (int i = 0; i < landCount; i++) {
            game.getAction().moveToPlay(card(basicLand, p0), null, null);
        }
        game.getTriggerHandler().setSuppressAllTriggers(false);
        game.getAction().checkStateEffects(true);
    }

    private static forge.game.card.Card card(String name, Player owner) {
        return forge.game.card.Card.fromPaperCard(
                forge.StaticData.instance().getCommonCards().getCard(name), owner);
    }

    /**
     * A card's canonical mana-cost string ("{2}{W}{W}", "{X}{X}") — the
     * structured form the gate's land derivation parses. Here because the
     * card-DB walk crosses forge.item, which only the engine package may
     * touch.
     */
    public static String manaCostOf(String cardName) {
        return forge.StaticData.instance().getCommonCards().getCard(cardName)
                .getRules().getManaCost().toString();
    }
}
