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
 * auto-pass narrations all land here. Works only when the advisor runner is
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
            new javax.swing.JButton("Advisor: ON");

    private void syncToggle() {
        final boolean on = forge.arena.interactive.AiControlFile.advisorEnabled();
        toggle.setText(on ? "Advisor: ON — click to pause"
                          : "Advisor: PAUSED — click to resume");
    }

    private void poll() {
        syncToggle();
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
