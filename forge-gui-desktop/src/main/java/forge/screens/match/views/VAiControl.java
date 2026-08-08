/*
 * Forge: Play Magic: the Gathering.
 * Arena addition: live per-seat AI brain controls (seatd runners).
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */
package forge.screens.match.views;

import javax.swing.JButton;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.Timer;

import forge.arena.interactive.AiControlFile;
import forge.gui.framework.DragCell;
import forge.gui.framework.DragTab;
import forge.gui.framework.EDocID;
import forge.gui.framework.IVDoc;
import forge.screens.match.controllers.CAiControl;
import net.miginfocom.swing.MigLayout;

/**
 * Live controls for the seatd AI runners: one row per seat with an
 * alive-indicator and model / effort steppers. State is exchanged through
 * the runners' control files ({@code logs/control/seat-N.json}); the runner
 * is the reconciler and applies changes at its next decision boundary. The
 * panel is pure file I/O — it works only when seatd runners are attached,
 * and shows seats as offline otherwise.
 */
public class VAiControl implements IVDoc<CAiControl> {

    private static final int SEATS = 4;

    private DragCell parentCell;
    private final DragTab tab = new DragTab("AI");
    private final CAiControl controller;

    private final JPanel body = new JPanel();
    private final JLabel[] status = new JLabel[SEATS];
    private final JLabel[] modelLbl = new JLabel[SEATS];
    private final JLabel[] effortLbl = new JLabel[SEATS];
    private final Timer refresh;

    public VAiControl(final CAiControl controller) {
        this.controller = controller;
        body.setOpaque(false);
        body.setLayout(new MigLayout("insets 6, gapy 4, wrap 7",
                "[40!][20!][60:80:120][24!][24!][60:80:120][24!]"));
        body.add(header("Seat"));
        body.add(header(""));
        body.add(header("Model"));
        body.add(header(""));
        body.add(header(""));
        body.add(header("Effort"));
        body.add(header(""));
        for (int seat = 0; seat < SEATS; seat++) {
            final int n = seat;
            status[n] = new JLabel("●");
            modelLbl[n] = value("—");
            effortLbl[n] = value("—");
            body.add(header("  " + n));
            body.add(status[n]);
            body.add(modelLbl[n]);
            body.add(stepBtn("−", () -> step(n, true, -1)));
            body.add(stepBtn("+", () -> step(n, true, +1)));
            body.add(effortLbl[n]);
            final JPanel eBtns = new JPanel(new MigLayout("insets 0, gap 2"));
            eBtns.setOpaque(false);
            eBtns.add(stepBtn("−", () -> step(n, false, -1)));
            eBtns.add(stepBtn("+", () -> step(n, false, +1)));
            body.add(eBtns);
        }
        refresh = new Timer(2000, e -> refreshFromFiles());
        refresh.setRepeats(true);
    }

    private static JLabel header(final String s) {
        final JLabel l = new JLabel(s);
        l.setForeground(java.awt.Color.LIGHT_GRAY);
        return l;
    }

    private static JLabel value(final String s) {
        final JLabel l = new JLabel(s);
        l.setForeground(java.awt.Color.WHITE);
        return l;
    }

    private static JButton stepBtn(final String txt, final Runnable action) {
        final JButton b = new JButton(txt);
        b.setMargin(new java.awt.Insets(0, 4, 0, 4));
        b.setFocusable(false);
        b.addActionListener(e -> action.run());
        return b;
    }

    // ---- file plumbing (delegated to the Swing-free AiControlFile) ----------

    private void step(final int seat, final boolean isModel, final int dir) {
        AiControlFile.step(seat, isModel, dir);
        refreshFromFiles();
    }

    private void refreshFromFiles() {
        for (int n = 0; n < SEATS; n++) {
            modelLbl[n].setText(AiControlFile.model(n, "—"));
            effortLbl[n].setText(AiControlFile.effort(n, "—"));
            final long age = AiControlFile.usageAgeMillis(n);
            // green: decided recently; yellow: alive-ish; gray: offline/unknown
            status[n].setForeground(age < 60_000 ? new java.awt.Color(0x3D, 0xC8, 0x5C)
                    : age < 300_000 ? new java.awt.Color(0xD8, 0xB4, 0x2A)
                    : java.awt.Color.DARK_GRAY);
        }
    }

    //========== IVDoc

    @Override
    public void populate() {
        parentCell.getBody().removeAll();
        parentCell.getBody().setLayout(new MigLayout("insets 0, gap 0, wrap"));
        parentCell.getBody().add(body, "w 96%!, gapleft 2%, gaptop 1%");
        refreshFromFiles();
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
        return EDocID.REPORT_AI;
    }

    @Override
    public DragTab getTabLabel() {
        return tab;
    }

    @Override
    public CAiControl getLayoutControl() {
        return controller;
    }
}
