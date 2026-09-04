/*
 * Forge: Play Magic: the Gathering.
 * Arena addition: the AI Advisor panel — streaming play advice for the human seat.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */
package forge.screens.match.views;

import java.awt.Color;
import java.awt.Font;

import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextArea;
import javax.swing.Timer;

import forge.arena.interactive.AdvisorLogTail;
import forge.gui.framework.DragCell;
import forge.gui.framework.DragTab;
import forge.gui.framework.EDocID;
import forge.gui.framework.IVDoc;
import forge.screens.match.controllers.CAdvisor;
import net.miginfocom.swing.MigLayout;

/**
 * Streaming teaching commentary from the seat-0 advisor brain. Pure file
 * I/O: the advisor runner appends to {@code logs/advisor-0.log} and this
 * panel tails it on a Swing timer — advice, turn color commentary, and
 * auto-pass narrations all land here — and answers to the questions typed
 * into the field below the feed. Works only when the advisor runner is
 * attached ({@code arena-play.sh --advisor}); shows offline otherwise.
 */
public class VAdvisor implements IVDoc<CAdvisor> {

    private DragCell parentCell;
    private final DragTab tab = new DragTab("Advisor");
    private final CAdvisor controller;
    private final AdvisorLogTail tail = new AdvisorLogTail();

    private final JPanel body = new JPanel();
    private final JLabel status = new JLabel("● Advisor offline — launch with arena-play.sh --advisor");
    private final JTextArea text = new JTextArea();
    private final Timer refresh;

    public VAdvisor(final CAdvisor controller) {
        this.controller = controller;
        body.setOpaque(false);
        body.setLayout(new MigLayout("insets 4, gapy 2, wrap 1, fill", "[grow]", "[][grow]"));
        status.setForeground(Color.GRAY);
        status.setFont(status.getFont().deriveFont(status.getFont().getSize2D() - 1f));
        text.setEditable(false);
        text.setLineWrap(true);
        text.setWrapStyleWord(true);
        text.setOpaque(false);
        text.setForeground(Color.WHITE);
        text.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, text.getFont().getSize()));
        final JScrollPane scroll = new JScrollPane(text,
                JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,
                JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);
        scroll.setOpaque(false);
        scroll.getViewport().setOpaque(false);
        scroll.setBorder(null);
        body.add(status, "growx");
        body.add(scroll, "grow, push");
        // Ask the advisor (Ben, 2026-09-04): one field, one button. The text
        // becomes logs/control/ask/ask-<ts>-<n>.json; the advisor runner
        // deletes the file when it picks the question up and answers in the
        // stream this panel already tails — one-way files, no engine thread.
        final JPanel askRow = new JPanel(new MigLayout("insets 0, gap 4, fill", "[grow][]", "[]"));
        askRow.setOpaque(false);
        askField.setToolTipText("Ask the advisor a question — Enter or Ask sends it");
        askButton.setFocusable(false);
        askButton.setMargin(new java.awt.Insets(1, 8, 1, 8));
        final java.awt.event.ActionListener sendAsk = e -> sendAsk();
        askField.addActionListener(sendAsk);
        askButton.addActionListener(sendAsk);
        askRow.add(askField, "growx");
        askRow.add(askButton);
        body.add(askRow, "growx, gaptop 2");
        // In-game advisor on/off (plan §13b): writes logs/control/advisor.json,
        // which advisor_runner honors at its next poll (paused = no scanning,
        // no model calls; the engine's one-way feed keeps writing harmlessly).
        // The AI tab's seat-0 row reflects the same state on its own refresh.
        toggle.setFocusable(false);
        toggle.setMargin(new java.awt.Insets(1, 8, 1, 8));
        toggle.addActionListener(e -> {
            final boolean next = !forge.arena.interactive.AiControlFile.advisorEnabled();
            forge.arena.interactive.AiControlFile.setAdvisorEnabled(next);
            syncToggle();
        });
        body.add(toggle, "gaptop 2");
        refresh = new Timer(1000, e -> poll());
        refresh.setRepeats(true);
    }

    private final javax.swing.JButton toggle =
            new javax.swing.JButton("Advisor: OFF");

    private final javax.swing.JTextField askField = new javax.swing.JTextField();
    private final javax.swing.JButton askButton = new javax.swing.JButton("Ask");
    /** The question file until the runner deletes it (= picked up). */
    private java.io.File pendingAsk;
    private long pendingSince;
    private static final long ASK_PICKUP_MS = 20_000;

    private void sendAsk() {
        if (pendingAsk != null) {
            return; // one question at a time — the button says "Sending…"
        }
        final String typed = askField.getText();
        if (forge.arena.interactive.AiControlFile.sanitizeAsk(typed).isEmpty()) {
            return;
        }
        final java.io.File f = forge.arena.interactive.AiControlFile.askAdvisor(typed);
        if (f == null) {
            text.append("\n[advisor] could not send — the runner logs directory is not writable.\n");
            return;
        }
        askField.setText("");
        pendingAsk = f;
        pendingSince = System.currentTimeMillis();
        syncAsk();
    }

    private void syncAsk() {
        if (!forge.arena.interactive.AiControlFile.advisorAttached()) {
            askField.setEnabled(false);
            askButton.setEnabled(false);
            askButton.setText("Ask");
            return;
        }
        askField.setEnabled(true);
        if (pendingAsk != null) {
            if (!pendingAsk.exists()) {
                pendingAsk = null;   // picked up — the answer arrives in the stream
            } else if (System.currentTimeMillis() - pendingSince > ASK_PICKUP_MS) {
                pendingAsk = null;   // nobody home; let the human retry
                text.append("\n[advisor] nobody picked up your question — is the advisor running?\n");
            }
        }
        askButton.setEnabled(pendingAsk == null);
        askButton.setText(pendingAsk == null ? "Ask" : "Sending…");
    }

    private void syncToggle() {
        // Three states, not two: an all-AI or --no-advisor game has no advisor
        // to pause, and advisorEnabled() (the pause flag) defaults to true —
        // so without this gate the button read "ON" in advisor-less games.
        if (!forge.arena.interactive.AiControlFile.advisorAttached()) {
            toggle.setText("Advisor: OFF — not attached this game");
            toggle.setEnabled(false);
            return;
        }
        toggle.setEnabled(true);
        final boolean on = forge.arena.interactive.AiControlFile.advisorEnabled();
        toggle.setText(on ? "Advisor: ON — click to pause"
                          : "Advisor: PAUSED — click to resume");
    }

    private void poll() {
        syncToggle();
        syncAsk();
        final String fresh = tail.readNew();
        if (!fresh.isEmpty()) {
            text.append(fresh);
            // keep the feed bounded so a marathon game can't bloat the EDT
            final int over = text.getDocument().getLength() - 200_000;
            if (over > 0) {
                text.replaceRange("", 0, over);
            }
            text.setCaretPosition(text.getDocument().getLength());
        }
        final long age = AdvisorLogTail.ageMillis();
        if (age == Long.MAX_VALUE) {
            status.setText("● Advisor offline — launch with arena-play.sh --advisor");
            status.setForeground(Color.DARK_GRAY);
        } else {
            status.setText("● Advisor" + (age < 60_000 ? " — live" : ""));
            status.setForeground(age < 60_000 ? new Color(0x3D, 0xC8, 0x5C)
                    : age < 300_000 ? new Color(0xD8, 0xB4, 0x2A) : Color.DARK_GRAY);
        }
    }

    //========== IVDoc

    @Override
    public void populate() {
        parentCell.getBody().removeAll();
        parentCell.getBody().setLayout(new MigLayout("insets 0, gap 0, fill"));
        parentCell.getBody().add(body, "grow");
        poll();
        refresh.start();
    }

    @Override
    public void setParentCell(final DragCell cell0) {
        this.parentCell = cell0;
    }

    @Override
    public DragCell getParentCell() {
        return this.parentCell;
    }

    @Override
    public EDocID getDocumentID() {
        return EDocID.REPORT_ADVISOR;
    }

    @Override
    public DragTab getTabLabel() {
        return tab;
    }

    @Override
    public CAdvisor getLayoutControl() {
        return controller;
    }
}
