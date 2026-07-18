package forge.arena.combo;

/**
 * An executor whose proven loop compresses to a bounded pool injection
 * (PR-16 shortcut, PR-27a generalized): any archetype producing unbounded
 * MANA implements this and rides the same ShortcutOrder → injectPool →
 * DEPLOY machinery. Non-mana products (token floods, PR-27b) need their own
 * injection seam and do NOT belong here.
 */
public interface ShortcutSource {

    /** False = the line banks physical cycles instead (bank_cycles). */
    boolean shortcutEligible();

    /** Color of the injected pool (the loop's production color). */
    String poolColor();

    /**
     * PR-33 (urza find): the battlefield card the injected pool's Mana
     * objects cite as their source. The old params-guess ("engine" then
     * "tapper") returned null for the Scepter loop and NPE'd Mana's
     * constructor mid-game — the executor names its own source instead.
     */
    String poolSourceCard();
}
