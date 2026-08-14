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
    private final JLabel[] usageLbl = new JLabel[SEATS];
    private final JLabel[] eloLbl = new JLabel[SEATS];
    // Stepper buttons are hidden (not just inert) whenever a click would be a
    // no-op — out-of-cycle backend models, clamped cycle ends. A dead button
    // overlaying a long or:/oai: label was unreadable noise (Ben, 2026-08-13).
    private final JButton[] modelMinus = new JButton[SEATS];
    private final JButton[] modelPlus = new JButton[SEATS];
    private final JButton[] effortMinus = new JButton[SEATS];
    private final JButton[] effortPlus = new JButton[SEATS];
    private final JLabel totalLbl = new JLabel(" ");
    private final Timer refresh;

    public VAiControl(final CAiControl controller) {
        this.controller = controller;
        body.setOpaque(false);
        body.setLayout(new MigLayout("insets 6, gapy 4, wrap 7",
                "[40!][20!][60:110:170][24!][24!][60:80:120][24!]"));
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
            modelMinus[n] = stepBtn("−", () -> step(n, true, -1));
            modelPlus[n] = stepBtn("+", () -> step(n, true, +1));
            effortMinus[n] = stepBtn("−", () -> step(n, false, -1));
            effortPlus[n] = stepBtn("+", () -> step(n, false, +1));
            body.add(header("  " + n));
            body.add(status[n]);
            body.add(modelLbl[n]);
            body.add(modelMinus[n]);
            body.add(modelPlus[n]);
            body.add(effortLbl[n]);
            final JPanel eBtns = new JPanel(new MigLayout("insets 0, gap 2"));
            eBtns.setOpaque(false);
            eBtns.add(effortMinus[n]);
            eBtns.add(effortPlus[n]);
            body.add(eBtns, "wrap");
            // per-seat usage line, spanning the full row under the controls
            usageLbl[n] = dim("—");
            body.add(usageLbl[n], "span 7, gapleft 20, gaptop 0, wrap");
            // per-seat ELO line (plan §13.4): fed by runner/ratings.py's flat
            // digests; blank until a first game has been rated.
            eloLbl[n] = dim(" ");
            body.add(eloLbl[n], "span 7, gapleft 20, gaptop 0, gapbottom 4, wrap");
        }
        totalLbl.setForeground(java.awt.Color.LIGHT_GRAY);
        body.add(totalLbl, "span 7, gaptop 6");
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

    private static JLabel dim(final String s) {
        final JLabel l = new JLabel(s);
        l.setForeground(java.awt.Color.GRAY);
        l.setFont(l.getFont().deriveFont(l.getFont().getSize2D() - 1f));
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
            // Backend model strings are long: show or:<segment> / oai:<segment>
            // ellipsized to the column, full string in the tooltip. Claude
            // names display exactly as before (displayModel passes them through).
            final String rawModel = AiControlFile.model(n, "—");
            String shown = AiControlFile.displayModel(rawModel);
            // 13 chars + ellipsis stays safely inside the 170px column at the
            // panel font — 20 was measured too wide and painted under the "−"
            // button (Ben's screenshot, 2026-08-13 evening game).
            if (shown != null && shown.length() > 14) {
                shown = shown.substring(0, 13) + "…";
            }
            modelLbl[n].setText(shown);
            modelLbl[n].setToolTipText(shown != null && shown.equals(rawModel)
                    ? null : rawModel);
            effortLbl[n].setText(AiControlFile.effort(n, "—"));
            // Hide dead steppers instead of rendering no-op buttons over the
            // label (out-of-cycle backend model: both model buttons vanish;
            // clamped ends: just the dead direction).
            modelMinus[n].setVisible(AiControlFile.canStep(n, true, -1));
            modelPlus[n].setVisible(AiControlFile.canStep(n, true, +1));
            effortMinus[n].setVisible(AiControlFile.canStep(n, false, -1));
            effortPlus[n].setVisible(AiControlFile.canStep(n, false, +1));
            final long age = AiControlFile.usageAgeMillis(n);
            // green: decided recently; yellow: alive-ish; gray: offline/unknown
            status[n].setForeground(age < 60_000 ? new java.awt.Color(0x3D, 0xC8, 0x5C)
                    : age < 300_000 ? new java.awt.Color(0xD8, 0xB4, 0x2A)
                    : java.awt.Color.DARK_GRAY);
            final String usage = AiControlFile.usageSummary(n);
            String usageText = usage != null ? usage : "— no decisions yet";
            // Seat 0 doubles as the advisor's row in advised games: reflect
            // the in-game toggle so a paused advisor never looks live (§13b).
            if (n == 0 && AiControlFile.advisorToggleFile().exists()
                    && !AiControlFile.advisorEnabled()) {
                usageText = "advisor paused · " + usageText;
            }
            usageLbl[n].setText(usageText);
            final String elo = AiControlFile.eloSummary(n);
            eloLbl[n].setText(elo != null ? elo : " ");
        }
        final String totals = AiControlFile.tableTotals();
        totalLbl.setText(totals != null ? totals : " ");
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
