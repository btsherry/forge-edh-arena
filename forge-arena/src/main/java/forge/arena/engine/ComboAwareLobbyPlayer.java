package forge.arena.engine;

import java.util.Collections;
import java.util.List;

import forge.LobbyPlayer;
import forge.ai.ComputerUtil;
import forge.ai.LobbyPlayerAi;
import forge.ai.PlayerControllerAi;
import forge.arena.combo.ComboPilot;
import forge.arena.combo.LineExecutor;
import forge.game.Game;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.PlayerController;
import forge.game.spellability.SpellAbility;

/**
 * The combo-aware seat (plan §6, PR-15): stock AI everywhere, except that
 * each priority first asks the {@link ComboPilot} whether to enter or
 * continue a combo line. Inert without artifacts by construction — a pilot
 * with no ready bound combo always defers to {@code super}, so a seat with
 * empty artifacts is behaviorally the stock AI (the §8 inertness property).
 *
 * <p>Uses the same controller-injection seam GoldfishLobbyPlayer proved
 * (subclass LobbyPlayerAi, replace the controller), and the same play
 * mechanics validation was proven on: steps resolve through
 * {@link AbilityResolver}, mana abilities play off-stack via
 * {@code ComputerUtil.playNoStack} (they must never touch the stack), stack
 * abilities go through the stock {@code playChosenSpellAbility} path.
 */
public final class ComboAwareLobbyPlayer extends LobbyPlayerAi {

    /** Builds the seat's pilot once the in-game Player exists. */
    public interface PilotFactory {
        ComboPilot create(Player player);
    }

    private final PilotFactory pilotFactory;

    public ComboAwareLobbyPlayer(String name, PilotFactory pilotFactory) {
        super(name, Collections.emptySet());
        this.pilotFactory = pilotFactory;
    }

    private ComboAwareController controllerFor(Player p) {
        return new ComboAwareController(p.getGame(), p, this, pilotFactory.create(p));
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
    }

    static final class ComboAwareController extends PlayerControllerAi {

        private final ComboPilot pilot;
        private final int seatIndex;

        ComboAwareController(Game game, Player p, ComboAwareLobbyPlayer lobby, ComboPilot pilot) {
            super(game, p, lobby);
            this.pilot = pilot;
            this.seatIndex = p.getId();
        }

        private int shortcutTurn = -1;
        private String shortcutCombo;
        private boolean stallReported;

        @Override
        public List<SpellAbility> chooseSpellAbilityToPlay() {
            Game game = getGame();
            int turn = game.getPhaseHandler().getTurn();
            watchForStall(game, turn);
            SeatView view = SeatViews.of(player, seatIndex, turn);
            boolean entryWindowOpen = game.getPhaseHandler().is(PhaseType.MAIN1, player)
                    && game.getStack().isEmpty();
            ComboPilot.Action action = pilot.nextAction(view, entryWindowOpen,
                    executor -> executor.validate(GameSimHandle.copyOf(game, player)))
                    .orElse(null);
            if (action == null) {
                return super.chooseSpellAbilityToPlay();
            }
            if (!action.isStep()) {
                // loop shortcut (plan §6): the proof already ran on a copy —
                // compress the loop to its bounded product and let stock AI
                // convert along the planner's selected route
                injectPool(action.shortcut());
                shortcutTurn = turn;
                shortcutCombo = action.shortcut().comboId();
                return super.chooseSpellAbilityToPlay();
            }
            LineExecutor.Step step = action.step();
            SpellAbility sa = AbilityResolver.resolve(player, step.card(), step.costHint(),
                    step.targets());
            if (sa == null) {
                // a piece the proven line relied on is gone or changed —
                // graceful fallback, recorded, never a crash (plan §8)
                pilot.abortLine(turn, "interaction", step.card());
                return super.chooseSpellAbilityToPlay();
            }
            return Collections.singletonList(sa);
        }

        private void injectPool(ComboPilot.ShortcutOrder order) {
            forge.game.card.Card source = AbilityResolver.findBattlefield(player, order.engineCard());
            byte color = forge.card.MagicColor.fromName(order.color().toLowerCase());
            forge.game.mana.Mana[] mana = new forge.game.mana.Mana[order.amount()];
            for (int i = 0; i < order.amount(); i++) {
                mana[i] = new forge.game.mana.Mana(color, source, null, player);
            }
            player.getManaPool().addMana(mana);
        }

        /** Gate 3.6 logging half: proven-infinite with no end state within 2 turns. */
        private void watchForStall(Game game, int turn) {
            if (shortcutTurn < 0 || stallReported || game.isGameOver()
                    || turn < shortcutTurn + 2) {
                return;
            }
            stallReported = true;
            StringBuilder dump = new StringBuilder("turn=").append(turn).append('\n');
            for (forge.game.player.Player p : game.getPlayers()) {
                dump.append(p.getName()).append(" life=").append(p.getLife())
                        .append(" battlefield=");
                for (forge.game.card.Card c : p.getCardsIn(forge.game.zone.ZoneType.Battlefield)) {
                    dump.append(c.getName()).append(';');
                }
                dump.append('\n');
            }
            try {
                String hash = Integer.toHexString(dump.toString().hashCode());
                java.nio.file.Path dir = java.nio.file.Path.of(
                        System.getProperty("arena.stall.dir", "stalls"));
                java.nio.file.Files.createDirectories(dir);
                java.nio.file.Path file = dir.resolve(hash + ".txt");
                java.nio.file.Files.writeString(file, dump.toString());
                pilot.reportStalled(turn, shortcutCombo, hash, file.toString());
            } catch (java.io.IOException e) {
                pilot.reportStalled(turn, shortcutCombo, "unhashed", "dump_failed:" + e.getMessage());
            }
        }

        @Override
        public boolean playChosenSpellAbility(SpellAbility sa) {
            if (sa.isManaAbility()) {
                // same off-stack path validation used (GameSimHandle):
                // mana abilities never stack, and the stock path would
                return ComputerUtil.playNoStack(player, sa, getGame(), false);
            }
            return super.playChosenSpellAbility(sa);
        }
    }
}
