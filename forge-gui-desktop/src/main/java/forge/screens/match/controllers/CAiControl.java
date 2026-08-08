package forge.screens.match.controllers;

import forge.gui.framework.ICDoc;
import forge.screens.match.CMatchUI;
import forge.screens.match.views.VAiControl;

/**
 * Controller for the AI seat-control panel (seatd runners). The view is
 * self-refreshing (file-driven); this controller only satisfies the
 * IVDoc/ICDoc pairing contract.
 *
 * <br><br><i>(C at beginning of class name denotes a control class.)</i>
 */
public class CAiControl implements ICDoc {

    @SuppressWarnings("unused")
    private final CMatchUI matchUI;
    private final VAiControl view;

    public CAiControl(final CMatchUI cMatchUI) {
        view = new VAiControl(this);
        matchUI = cMatchUI;
    }

    public VAiControl getView() {
        return view;
    }

    @Override
    public void register() {
    }

    @Override
    public void initialize() {
    }

    @Override
    public void update() {
    }
}
