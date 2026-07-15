package forge.arena.engine;

import java.util.Collections;
import java.util.List;

import forge.LobbyPlayer;
import forge.ai.LobbyPlayerAi;
import forge.ai.PlayerControllerAi;
import forge.game.Game;
import forge.game.player.Player;
import forge.game.player.PlayerController;
import forge.game.spellability.SpellAbility;

/**
 * The goldfish seat (plan §3 Gate 2, §9 W3): a non-interactive opponent that
 * keeps every hand and never acts — it exists so a deck under test can be
 * exercised solo. Also the first proof of the controller-injection seam
 * (subclass LobbyPlayerAi, replace the controller) that Phase 4's
 * ComboAwareController will use.
 */
public final class GoldfishLobbyPlayer extends LobbyPlayerAi {

    public GoldfishLobbyPlayer(String name) {
        super(name, Collections.emptySet());
    }

    private GoldfishController controllerFor(Player p) {
        return new GoldfishController(p.getGame(), p, this);
    }

    @Override
    public Player createIngamePlayer(Game game, int id) {
        Player p = new Player(getName(), game, id);
        p.setFirstController(controllerFor(p));
        return p;
    }

    @Override
    public PlayerController createMindSlaveController(Player master, Player slave) {
        return controllerFor(slave);
    }

    @Override
    public void hear(LobbyPlayer player, String message) {
        // goldfish are deaf too
    }

    /** Passes every priority, keeps every hand; everything else falls back to stock AI. */
    static final class GoldfishController extends PlayerControllerAi {

        GoldfishController(Game game, Player p, GoldfishLobbyPlayer lobby) {
            super(game, p, lobby);
        }

        @Override
        public List<SpellAbility> chooseSpellAbilityToPlay() {
            return null; // null = pass priority (the stock AI's own "nothing to do" signal)
        }

        @Override
        public boolean mulliganKeepHand(Player firstPlayer, int cardsToReturn) {
            return true;
        }
    }
}
