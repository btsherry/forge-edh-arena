package forge.arena.interactive;

import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;

import org.testng.Assert;
import org.testng.annotations.Test;

/**
 * BL-29 (game 23, 2026-09-06): letters typed into the Advisor tab's Chat field
 * fired Forge's window-level match hotkeys (T toggled the targeting arrows,
 * Y set an auto-yield). The guard decides which KEY_PRESSED events the field
 * keeps to itself. Pure predicate, no display needed.
 */
public class HotkeyGuardTest {

    @Test
    public void typedLettersAndDigitsAreSwallowed() {
        for (final char c : "tscynpldTSCYNP0123456789 ?!,.'".toCharArray()) {
            Assert.assertTrue(HotkeyGuard.swallow(c, 0), "plain '" + c + "' must not reach the window hotkeys");
            Assert.assertTrue(HotkeyGuard.swallow(c, InputEvent.SHIFT_DOWN_MASK), "shifted '" + c + "' is still typing");
        }
    }

    @Test
    public void editingAndNavigationKeysPassThrough() {
        Assert.assertFalse(HotkeyGuard.swallow('\n', 0), "Enter sends the question");
        Assert.assertFalse(HotkeyGuard.swallow('\b', 0), "Backspace edits");
        Assert.assertFalse(HotkeyGuard.swallow((char) 27, 0), "Escape leaves the field");
        Assert.assertFalse(HotkeyGuard.swallow('\t', 0), "Tab navigates");
        Assert.assertFalse(HotkeyGuard.swallow(KeyEvent.CHAR_UNDEFINED, 0), "arrows / function keys have no char");
    }

    @Test
    public void modifierChordsStayHotkeys() {
        Assert.assertFalse(HotkeyGuard.swallow('e', InputEvent.CTRL_DOWN_MASK), "Ctrl+E (end turn) is deliberate");
        Assert.assertFalse(HotkeyGuard.swallow('a', InputEvent.META_DOWN_MASK), "Cmd+A is not typing");
        Assert.assertFalse(HotkeyGuard.swallow('q', InputEvent.ALT_DOWN_MASK));
    }

    @Test
    public void onlyKeyPressedEventsAreConsidered() {
        final java.awt.Component src = new java.awt.Canvas();
        final KeyEvent pressed = new KeyEvent(src, KeyEvent.KEY_PRESSED, 0L, 0, KeyEvent.VK_T, 't');
        final KeyEvent typed = new KeyEvent(src, KeyEvent.KEY_TYPED, 0L, 0, KeyEvent.VK_UNDEFINED, 't');
        final KeyEvent released = new KeyEvent(src, KeyEvent.KEY_RELEASED, 0L, 0, KeyEvent.VK_T, 't');
        Assert.assertTrue(HotkeyGuard.swallow(pressed), "the pressed half is what the window bindings key on");
        Assert.assertFalse(HotkeyGuard.swallow(typed), "the typed half must still insert the character");
        Assert.assertFalse(HotkeyGuard.swallow(released));
    }
}
