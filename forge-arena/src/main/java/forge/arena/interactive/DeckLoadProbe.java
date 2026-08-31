package forge.arena.interactive;

import java.io.File;

import forge.arena.bootstrap.ArenaBootstrap;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.deck.DeckSection;

/**
 * Loadability probe for a Commander .dck THROUGH THE REAL LOADER (2026-09-01).
 * Two consecutive new decks failed at their FIRST live launch on defects the
 * file-presence preflight cannot see: a raw Moxfield export (no sections) and
 * a transform commander written as "A // B" (Forge names transform cards by
 * their front face, so DeckSerializer resolved no commander). This probe is
 * arena-add-deck's final gate: it loads the deck exactly as GuiPilotMatch
 * will and fails loudly on missing commanders or dropped (unresolvable)
 * cards.
 *
 * Usage: DeckLoadProbe &lt;deck.dck&gt; &lt;forge-gui-dir&gt;
 */
public final class DeckLoadProbe {

    private DeckLoadProbe() {
    }

    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("usage: DeckLoadProbe <deck.dck> <forge-gui-dir>");
            System.exit(2);
        }
        ArenaBootstrap.initialize(new File(args[1]));
        Deck deck = DeckSerializer.fromFile(new File(args[0]));
        if (deck == null) {
            System.err.println("PROBE FAIL: DeckSerializer returned null (bad file format?)");
            System.exit(1);
        }
        int commanders = deck.getCommanders().size();
        int main = deck.get(DeckSection.Main) != null
                ? deck.get(DeckSection.Main).countAll() : 0;
        int total = commanders + main;
        System.out.println("PROBE: '" + deck.getName() + "' commanders=" + commanders
                + " main=" + main + " total=" + total);
        if (commanders < 1) {
            System.err.println("PROBE FAIL: no commander resolved — for a "
                    + "double-faced commander the .dck must use Forge's FRONT-FACE "
                    + "name (e.g. 'Sheoldred', not 'Sheoldred // The True Scriptures')");
            System.exit(1);
        }
        if (total != 100) {
            System.err.println("PROBE FAIL: " + total + " cards resolved, expected 100 "
                    + "— unresolvable names are silently DROPPED by the loader; "
                    + "check spelling / DFC naming against Forge's card scripts");
            System.exit(1);
        }
        System.out.println("PROBE OK");
    }
}
