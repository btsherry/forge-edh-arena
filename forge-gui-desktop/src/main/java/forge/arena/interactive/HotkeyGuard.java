package forge.arena.interactive;

import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;

/**
 * Forge binds its match hotkeys on the frame with
 * {@code WHEN_IN_FOCUSED_WINDOW} (T = targeting arrows, S = stack, C = combat,
 * Y/N = auto-yield, P = yield auto-pass, L = console, D = dev). A Swing text
 * field does not consume the KEY_PRESSED half of a typed letter, so typing a
 * question into the Advisor tab's Chat field fired every matching hotkey —
 * game 23 (2026-09-06): the targeting overlay went dark after a question with
 * an odd number of t's. The field consumes the KEY_PRESSED of every printable,
 * unmodified key; the separate KEY_TYPED event still inserts the character,
 * and control keys (Enter, Backspace, arrows, Escape) and modifier chords
 * pass through untouched, so the field keeps its own behaviour.
 */
public final class HotkeyGuard {

    private HotkeyGuard() {
    }

    private static final int CHORD_MASK = InputEvent.CTRL_DOWN_MASK | InputEvent.META_DOWN_MASK
            | InputEvent.ALT_DOWN_MASK | InputEvent.ALT_GRAPH_DOWN_MASK;

    /** True when a KEY_PRESSED with this char/modifiers is a typed character
     *  the field must keep to itself (so the window's hotkey does not fire). */
    public static boolean swallow(final char keyChar, final int modifiersEx) {
        if (keyChar == KeyEvent.CHAR_UNDEFINED || Character.isISOControl(keyChar)) {
            return false; // Enter, Backspace, Escape, arrows, function keys
        }
        return (modifiersEx & CHORD_MASK) == 0; // Ctrl/Cmd/Alt chords stay hotkeys
    }

    public static boolean swallow(final KeyEvent e) {
        return e.getID() == KeyEvent.KEY_PRESSED && swallow(e.getKeyChar(), e.getModifiersEx());
    }
}
