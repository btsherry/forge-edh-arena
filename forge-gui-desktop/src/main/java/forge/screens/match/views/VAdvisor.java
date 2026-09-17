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
import forge.arena.interactive.VoiceFocus;
import forge.gui.framework.ICDoc;
import forge.gui.framework.SDisplayUtil;
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
    // The tabs follow the voices (VoiceFocus): 250 ms poll of logs/voice-speaking.json.
    private final Timer focusTimer;
    private static final boolean FOCUS_ON = VoiceFocus.enabled(System.getenv("ARENA_VOICE_FOCUS"));
    private IVDoc<? extends ICDoc> focusRestore;   // the tab the player had in front before we moved it
    private DragCell focusCell;
    private int focusSeat = -1;
    private long focusQuietSince;

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
        // Voice mute (Ben, 2026-09-08): a speaker icon in the panel's upper
        // right — light grey outline on black, struck through when muted.
        // Writes logs/control/voice.json; the voice runner silences EVERY line,
        // stock or live, and cuts one already playing. Pausing the advisor does
        // the same through advisor.json.
        mute.setFocusable(false);
        mute.setBorderPainted(false);
        mute.setContentAreaFilled(false);
        mute.setMargin(new java.awt.Insets(0, 0, 0, 0));
        mute.addActionListener(e -> {
            final boolean next = !forge.arena.interactive.AiControlFile.voiceEnabled();
            forge.arena.interactive.AiControlFile.setVoiceEnabled(next);
            syncMute();
        });
        final JPanel statusRow = new JPanel(new MigLayout("insets 0, gap 4, fill", "[grow][]", "[]"));
        statusRow.setOpaque(false);
        statusRow.add(status, "growx");
        statusRow.add(mute, "w 24!, h 24!");
        body.add(statusRow, "growx");
        body.add(scroll, "grow, push");
        // Chat with the advisor (Ben, 2026-09-04): one field, one button. The text
        // becomes logs/control/ask/ask-<ts>-<n>.json; the advisor runner
        // deletes the file when it picks the question up and answers in the
        // stream this panel already tails — one-way files, no engine thread.
        askRow = new JPanel(new MigLayout("insets 0, gap 4, fill", "[grow][]", "[]"));
        askRow.setOpaque(false);
        askField.setToolTipText("Ask the advisor a question — Enter or Chat sends it");
        // Black field on the dark dock (Ben, 2026-09-04): the skin's white
        // JTextField glared beside the transparent feed.
        askField.setOpaque(true);
        askField.setBackground(Color.BLACK);
        askField.setForeground(Color.WHITE);
        askField.setCaretColor(Color.WHITE);
        askField.setBorder(javax.swing.BorderFactory.createLineBorder(Color.DARK_GRAY));
        askButton.setFocusable(false);
        askButton.setMargin(new java.awt.Insets(1, 8, 1, 8));
        final java.awt.event.ActionListener sendAsk = e -> sendAsk();
        askField.addActionListener(sendAsk);
        askButton.addActionListener(sendAsk);
        // Typed letters must not fire Forge's window-level match hotkeys
        // (T arrows, S stack, C combat, Y/N yield, P auto-pass …) — see
        // HotkeyGuard. Escape leaves the field without sending; after a send
        // the focus goes back to the game so a deliberate hotkey works again.
        askField.addKeyListener(new java.awt.event.KeyAdapter() {
            @Override
            public void keyPressed(final java.awt.event.KeyEvent e) {
                if (e.getKeyCode() == java.awt.event.KeyEvent.VK_ESCAPE) {
                    releaseFocus();
                    e.consume();
                } else if (forge.arena.interactive.HotkeyGuard.swallow(e)) {
                    e.consume();
                }
            }
        });
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
        // Advisor Executive (Ben, 2026-09-07): the advisor PLAYS your seat until
        // clicked again. Writes logs/control/executive.json; the engine installs
        // or removes the override at your next priority (ExecutiveSwitch).
        executive.setFocusable(false);
        executive.setMargin(new java.awt.Insets(1, 8, 1, 8));
        executive.addActionListener(e -> {
            final boolean next = !forge.arena.interactive.AiControlFile.executiveOn();
            forge.arena.interactive.AiControlFile.setExecutive(next);
            syncExecutive();
        });
        // Ben (2026-09-08): both toggles on ONE row, short labels
        toggleRow = new JPanel(new MigLayout("insets 0, gap 4, fill", "[grow][grow]", "[]"));
        toggleRow.setOpaque(false);
        toggleRow.add(toggle, "growx");
        toggleRow.add(executive, "growx");
        body.add(toggleRow, "growx, gaptop 2");
        refresh = new Timer(1000, e -> poll());
        refresh.setRepeats(true);
        focusTimer = new Timer(250, e -> followVoice());
        focusTimer.setRepeats(true);
    }

    private final javax.swing.JButton toggle =
            new javax.swing.JButton("Advisor: OFF");
    private final javax.swing.JButton executive =
            new javax.swing.JButton("Advisor Exec: OFF - clk to tgl");
    private final javax.swing.JButton mute = new javax.swing.JButton();
    private static final javax.swing.Icon VOICE_ON = loadIcon("voice-on");
    private static final javax.swing.Icon VOICE_OFF = loadIcon("voice-off");

    /** forge-arena's resources: /forge/arena/icons/<name>.png (24 px) — null
     *  when missing, and the button falls back to a text label. */
    private static javax.swing.Icon loadIcon(final String name) {
        try {
            final java.net.URL u = VAdvisor.class.getResource("/forge/arena/icons/" + name + ".png");
            return u == null ? null : new javax.swing.ImageIcon(u);
        } catch (final RuntimeException e) {
            return null;
        }
    }

    private final javax.swing.JTextField askField = new javax.swing.JTextField();
    private final javax.swing.JButton askButton = new javax.swing.JButton("Chat");
    /** The question file until the runner deletes it (= picked up). */
    private java.io.File pendingAsk;
    private long pendingSince;
    // The offer pane (plan 2026-09-16-offer-dialog-plan.md): one per question file the advisor runner
    // publishes under logs/control/deal/questions/, oldest first; closed with the file, or dismissed by
    // the player ("later" — the offer stays open in the panel for a typed answer).
    private forge.arena.interactive.VDealOffer offerPane;
    // Ben, 2026-09-16 (game 56, a spectator table): the chat row exists only when an advisor or the relay answers
    // it; the Advisor/Executive toggles only with an advisor. What stays is the status line and the mute.
    private JPanel askRow;
    private JPanel toggleRow;
    private final java.util.Set<String> offerDismissed = new java.util.HashSet<>();
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
        releaseFocus();
    }

    /** Hand keyboard focus back to the game: Forge's card panels are not
     *  focusable, so without this the field would keep every later keystroke. */
    private void releaseFocus() {
        java.awt.KeyboardFocusManager.getCurrentKeyboardFocusManager().clearFocusOwner();
    }

    private void syncAsk() {
        if (!forge.arena.interactive.AiControlFile.relayAttached()) {
            askField.setEnabled(false);
            askButton.setEnabled(false);
            askButton.setText("Chat");
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
        askButton.setText(pendingAsk == null ? "Chat" : "Sending…");
    }

    private void syncOffers() {
        if (!forge.arena.interactive.AiControlFile.relayAttached()) {   // no relay: a pane's Accept would write an ask nobody reads
            if (offerPane != null) {
                offerPane.dispose();
                offerPane = null;
            }
            return;
        }
        final java.util.List<forge.arena.interactive.DealQuestion> qs =
                forge.arena.interactive.DealQuestion.list(forge.arena.interactive.DealQuestion.dir());
        final java.util.Set<String> live = new java.util.HashSet<>();
        for (final forge.arena.interactive.DealQuestion q : qs) {
            live.add(q.offerId);
        }
        offerDismissed.retainAll(live);                       // a file that went away frees its id
        if (offerPane != null) {
            forge.arena.interactive.DealQuestion cur = null;
            for (final forge.arena.interactive.DealQuestion q : qs) {
                if (q.offerId.equals(offerPane.offerId())) {
                    cur = q;
                }
            }
            if (cur != null && offerPane.isVisible()) {
                offerPane.refresh(cur);                       // Joshua's assessment may have landed
                return;
            }
            if (cur != null) {
                offerDismissed.add(cur.offerId);              // closed by the player: later, not no
            }
            offerPane.dispose();
            offerPane = null;
        }
        for (final forge.arena.interactive.DealQuestion q : qs) {
            if (!offerDismissed.contains(q.offerId)) {
                openOffer(q);
                return;
            }
        }
    }

    private void openOffer(final forge.arena.interactive.DealQuestion q) {
        offerPane = new forge.arena.interactive.VDealOffer(q,
                () -> answerOffer(q.acceptAsk(), q.offerId),
                () -> answerOffer(q.refuseAsk(), q.offerId),
                () -> counterOffer(q));
        offerPane.showBottomRight();
    }

    /** The click sends exactly the chat message the player would type, plus the id of the offer on screen, so the
     *  runner answers THAT offer (a typed answer means the seat's newest). */
    private void answerOffer(final String ask, final String offerId) {
        if (forge.arena.interactive.AiControlFile.askAdvisor(ask, offerId) == null) {
            text.append("\n[advisor] could not send your answer — the runner logs directory is not writable.\n");
        }
        releaseFocus();
    }

    private void counterOffer(final forge.arena.interactive.DealQuestion q) {
        if (offerPane != null) {
            offerDismissed.add(q.offerId);
            offerPane.dispose();
            offerPane = null;
        }
        askField.setText(q.counterPrefix());
        askField.requestFocusInWindow();
        askField.setCaretPosition(askField.getText().length());
    }

    private void syncToggle() {
        // Three states, not two: an all-AI or --no-advisor game has no advisor
        // to pause, and advisorEnabled() (the pause flag) defaults to true —
        // so without this gate the button read "ON" in advisor-less games.
        if (!forge.arena.interactive.AiControlFile.advisorAttached()) {
            toggle.setText("Advisor: OFF - not attached");
            toggle.setEnabled(false);
            return;
        }
        toggle.setEnabled(true);
        final boolean on = forge.arena.interactive.AiControlFile.advisorEnabled();
        toggle.setText(on ? "Advisor: ON - clk to pause"
                          : "Advisor: PAUSED - clk to resume");
    }

    private void syncExecutive() {
        if (!forge.arena.interactive.AiControlFile.advisorAttached()) {
            executive.setText("Advisor Exec: OFF - not attached");
            executive.setEnabled(false);
            return;
        }
        executive.setEnabled(true);
        final boolean on = forge.arena.interactive.AiControlFile.executiveOn();
        executive.setText(on ? "Advisor Exec: ON - clk to tgl"
                             : "Advisor Exec: OFF - clk to tgl");
    }

    private void syncMute() {
        final boolean attached = forge.arena.interactive.AiControlFile.voiceAttached();
        final boolean on = !attached || forge.arena.interactive.AiControlFile.voiceEnabled();
        mute.setEnabled(attached);
        final javax.swing.Icon icon = on ? VOICE_ON : VOICE_OFF;
        if (icon != null) {
            mute.setIcon(icon);
            mute.setDisabledIcon(icon);
            mute.setText(null);
        } else {
            mute.setText(on ? "Voice" : "Muted");   // icon resource missing: a plain label still works
        }
        mute.setToolTipText(!attached ? "Voice: no voice runner in this game"
                : on ? "Voice on — click to mute every spoken line"
                     : "Voice muted — click to unmute");
    }

    /** Bring the speaking seat's field tab forward for the line, and put the old
     *  tab back once the table has been quiet for a moment — unless the player
     *  clicked another tab in the meantime. Never touches keyboard focus. */
    private void followVoice() {
        long[] speaking = new long[] {-1, 0};
        int active = -1;
        try {
            final java.io.File f = new java.io.File(forge.arena.interactive.AiControlFile.logsDir(), "voice-speaking.json");
            if (f.isFile()) {
                final String json = java.nio.file.Files.readString(f.toPath());
                speaking = VoiceFocus.parseSpeaking(json);
                active = VoiceFocus.parseActive(json);
            }
        } catch (final java.io.IOException | RuntimeException e) {
            speaking = new long[] {-1, 0};
        }
        final long now = System.currentTimeMillis();
        if (VoiceFocus.speakingNow(speaking, now)) {
            final int seat = (int) speaking[0];
            final VField target = fieldForSeat(seat);
            final DragCell cell = target != null ? target.getParentCell() : null;
            if (cell == null) {
                return;
            }
            focusQuietSince = 0;
            final IVDoc<? extends ICDoc> current = cell.getSelected();
            if (current == target) {
                focusSeat = seat;
                return;                                    // already in front
            }
            if (focusSeat == seat) {
                return;                                    // brought forward once for this line; the player clicked away — theirs to keep (hygiene pass, 2026-09-17)
            }
            if (focusRestore == null || focusCell != cell) {
                focusRestore = current;                    // remember where the player was looking
                focusCell = cell;
            }
            focusSeat = seat;
            SDisplayUtil.showTab(target);
            return;
        }
        if (focusRestore == null) {
            focusSeat = -1;                                // nothing to restore: forget the seat, so its next line is followed again
            return;
        }
        if (focusQuietSince == 0) {
            focusQuietSince = now;
            return;
        }
        if (now - focusQuietSince < VoiceFocus.QUIET_MS) {
            return;                                        // the exchange may not be over
        }
        try {
            final VField last = fieldForSeat(focusSeat);
            if (focusCell != null && focusCell.getSelected() == last && focusRestore.getParentCell() == focusCell) {
                // Ben (2026-09-16): back to the ACTIVE player's board, not to wherever the player had been; the
                // remembered tab is the fallback when the runner did not say who is active
                final VField home = active >= 0 ? fieldForActive(active) : null;
                SDisplayUtil.showTab(home != null && home.getParentCell() == focusCell ? home : focusRestore);   // only if nobody clicked elsewhere meanwhile
            }
        } catch (final RuntimeException ignored) {
            // a tab that moved cells or a closed match: nothing to restore
        }
        focusRestore = null;
        focusCell = null;
        focusSeat = -1;
        focusQuietSince = 0;
    }

    /** The active player's field: a mailbox seat's field by its title, or — for the human, whose tab carries no
     *  seat suffix — the first field that names no seat. */
    private VField fieldForActive(final int seat) {
        final VField named = fieldForSeat(seat);
        if (named != null) {
            return named;
        }
        try {
            for (final VField f : controller.getMatchUI().getFieldViews()) {
                if (f.getTabLabel() != null && VoiceFocus.seatOfTab(f.getTabLabel().getText()) == -1) {
                    return f;
                }
            }
        } catch (final RuntimeException ignored) {
            // no match yet
        }
        return null;
    }

    /** The field whose tab title names this mailbox seat, or null. */
    private VField fieldForSeat(final int seat) {
        try {
            for (final VField f : controller.getMatchUI().getFieldViews()) {
                if (f.getTabLabel() != null && VoiceFocus.seatOfTab(f.getTabLabel().getText()) == seat) {
                    return f;
                }
            }
        } catch (final RuntimeException ignored) {
            // no match yet
        }
        return null;
    }

    private void poll() {
        if (askRow != null) {
            askRow.setVisible(forge.arena.interactive.AiControlFile.relayAttached());
        }
        if (toggleRow != null) {
            toggleRow.setVisible(forge.arena.interactive.AiControlFile.advisorAttached());
        }
        syncToggle();
        syncExecutive();
        syncMute();
        syncAsk();
        syncOffers();
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
        } else if (!forge.arena.interactive.AiControlFile.advisorAttached()) {
            status.setText("● Table relay — advisor off (deals and table talk only)");
            status.setForeground(age < 60_000 ? new Color(0x3D, 0xC8, 0x5C) : Color.DARK_GRAY);
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
        if (FOCUS_ON && forge.arena.interactive.AiControlFile.voiceAttached()) {   // no voice runner: nothing to follow
            focusTimer.start();
        }
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
