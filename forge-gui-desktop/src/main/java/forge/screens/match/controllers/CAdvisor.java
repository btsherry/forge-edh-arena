package forge.screens.match.controllers;

import forge.gui.framework.ICDoc;
import forge.screens.match.CMatchUI;
import forge.screens.match.views.VAdvisor;

/**
 * Controller for the AI Advisor panel. The view is self-refreshing
 * (file-driven tail); this controller only satisfies the IVDoc/ICDoc
 * pairing contract.
 *
 * <br><br><i>(C at beginning of class name denotes a control class.)</i>
 */
public class CAdvisor implements ICDoc {

    @SuppressWarnings("unused")
    private final CMatchUI matchUI;
    private final VAdvisor view;

    public CAdvisor(final CMatchUI cMatchUI) {
        view = new VAdvisor(this);
        matchUI = cMatchUI;
    }

    public VAdvisor getView() {
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
