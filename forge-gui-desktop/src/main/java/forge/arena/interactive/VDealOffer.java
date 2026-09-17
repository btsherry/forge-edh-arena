package forge.arena.interactive;

import java.awt.Frame;
import java.awt.Rectangle;

import javax.swing.JOptionPane;
import javax.swing.SwingConstants;

import forge.toolbox.FButton;
import forge.toolbox.FLabel;
import forge.toolbox.FTextArea;
import forge.view.FDialog;

/**
 * The offer pane (plan docs/reviews/2026-09-16-offer-dialog-plan.md): a seat has
 * offered the player a deal and the player answers with a click. NON-modal and
 * never focusable — Forge's own confirms block because the engine is waiting on
 * the player; an offer arrives on a seat's turn, often mid-combat, and must not
 * steal a click or a keystroke. Nothing here touches the engine or its input
 * queue: Accept and Refuse send the same chat message the player would type
 * (through the Advisor panel), Counter… hands the chat field over, and the
 * title-bar close means "later" — the offer stays open in the panel.
 * The panel owns the pane: it opens one per question file, refreshes it when
 * Joshua's assessment lands, and disposes it when the file is gone.
 */
public final class VDealOffer extends FDialog {

    private final String offerId;
    private final FLabel headline;
    private final FTextArea words;
    private final FTextArea assessment;
    private final FLabel lapse;
    private final FButton accept = new FButton("Accept");
    private final FButton refuse = new FButton("Refuse");
    private final FButton counter = new FButton("Counter…");
    private boolean sent;

    public VDealOffer(final DealQuestion q, final Runnable onAccept, final Runnable onRefuse, final Runnable onCounter) {
        super(false, false, "12 14 12 14");
        this.offerId = q.offerId;
        setTitle("A deal is offered");
        setFocusableWindowState(false);              // the game keeps every keystroke
        headline = new FLabel.Builder().text(q.headline()).fontSize(15).fontAlign(SwingConstants.LEFT).build();
        words = new FTextArea(q.text.isEmpty() ? "" : "“" + q.text + "”");
        assessment = new FTextArea(q.assessment == null ? "Joshua is weighing it…" : q.assessment);
        lapse = new FLabel.Builder().text(q.lapseLine()).fontSize(11).fontAlign(SwingConstants.LEFT).build();
        add(headline, "w 380!, wrap");
        add(words, "w 380!, wrap, gaptop 4");
        add(assessment, "w 380!, wrap, gaptop 6");
        add(lapse, "w 380!, wrap, gaptop 6, gapbottom 8");
        add(accept, "split 3, w 110!, h 28!");
        add(refuse, "w 110!, h 28!");
        add(counter, "w 110!, h 28!, wrap");
        words.setVisible(!q.text.isEmpty());
        accept.addActionListener(e -> send(onAccept));
        refuse.addActionListener(e -> send(onRefuse));
        counter.addActionListener(e -> {
            if (onCounter != null) {
                onCounter.run();
            }
        });
        pack();
    }

    public String offerId() {
        return offerId;
    }

    private void send(final Runnable action) {
        if (sent) {
            return;
        }
        sent = true;
        accept.setEnabled(false);
        refuse.setEnabled(false);
        counter.setEnabled(false);
        accept.setText("Sending…");
        if (action != null) {
            action.run();
        }
    }

    /** The same offer, re-read: the assessment may have landed. */
    public void refresh(final DealQuestion q) {
        final String want = q.assessment == null ? "Joshua is weighing it…" : q.assessment;
        if (!want.equals(assessment.getText())) {
            assessment.setText(want);
            pack();
            placeBottomRight();
        }
    }

    /** Show without stealing focus, bottom-right over the match view (FDialog centres by default). */
    public void showBottomRight() {
        setVisible(true);
        placeBottomRight();
    }

    private void placeBottomRight() {
        final Frame owner = JOptionPane.getRootFrame();
        final Rectangle b = owner == null ? null : owner.getBounds();
        if (b == null || b.width <= 0) {
            return;
        }
        final int margin = 24;
        setLocation(b.x + b.width - getWidth() - margin, b.y + b.height - getHeight() - margin * 4);
    }
}
