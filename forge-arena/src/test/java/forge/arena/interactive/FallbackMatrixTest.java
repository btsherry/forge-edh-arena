package forge.arena.interactive;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

import org.testng.Assert;
import org.testng.annotations.AfterClass;
import org.testng.annotations.BeforeClass;
import org.testng.annotations.BeforeMethod;
import org.testng.annotations.DataProvider;
import org.testng.annotations.Test;

import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.cost.Cost;
import forge.game.player.Player;
import forge.game.player.PlayerActionConfirmMode;
import forge.game.spellability.AbilitySub;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import forge.util.collect.FCollection;

/**
 * BL-25 (group {@code extended}): the malformed-answer matrix. Every decision
 * surface the seat drives with DIRECT controller calls (the shapes
 * {@link ProtocolContractTest} exercises) is crossed with every way a brain can
 * answer badly — silence, non-JSON, the wrong key, the wrong value type,
 * duplicate ids, an out-of-range number or index, an id from another zone —
 * and each cell must (1) return a LEGAL result (from the option list / within
 * bounds), (2) leave the board exactly as it was where the surface must not
 * mutate state, (3) let no exception escape, and (4) on the null-answer path
 * (silence, or unparsable text, which the protocol keeps polling past until
 * the timeout) count ONE stock fallback for the seat — a parsed-but-malformed
 * answer falls to stock too but is not a "brain did not answer" event.
 *
 * <p>One shared kit; {@link MailboxProtocol#TIMEOUT_PROPERTY} is set to 2 for
 * the class (before the kit's bus is created, since the bus fixes its timeout
 * at construction) so each null-answer cell costs about two seconds.
 */
public class FallbackMatrixTest {

    enum Kind { SILENT, NON_JSON, WRONG_KEY, WRONG_TYPE, DUPLICATE_IDS, OUT_OF_RANGE, FOREIGN_ID }

    private static MailboxTestKit k;
    private static String savedTimeout;
    private static volatile String surfaceUnderTest;
    private static volatile String nextAnswer;
    private static final AtomicBoolean APPLIED = new AtomicBoolean();
    private static final List<String> LOG = new ArrayList<>();

    // the board
    private static Card bears;
    private static Card elves;
    private static Card oppBears;
    private static Card libSwamp;
    private static Card darkRitual;
    private static SpellAbility bearsSa;   // seat's PermanentCreature SA (base-class AI defaults)
    private static SpellAbility oppSa;     // opp's spell: the "opponent's effect taxing you" shape
    private static SpellAbility drawSa;    // seat's Draw SA (number / discard source)
    private static SpellAbility scryingSa; // seat's ChangeZone Library->Hand SA (search source)
    private static SpellAbility charmSa;   // seat's Charm SA (modes)

    @BeforeClass(groups = "extended")
    public static void boot() throws Exception {
        savedTimeout = System.getProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, "2");
        k = new MailboxTestKit(false);
        for (int i = 0; i < 3; i++) {
            MailboxTestKit.put("Swamp", k.seat, ZoneType.Battlefield);
        }
        libSwamp = MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
        MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
        MailboxTestKit.put("Forest", k.seat, ZoneType.Library);
        MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
        bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
        elves = MailboxTestKit.put("Llanowar Elves", k.seat, ZoneType.Battlefield);
        darkRitual = MailboxTestKit.put("Dark Ritual", k.seat, ZoneType.Hand);
        MailboxTestKit.put("Counterspell", k.seat, ZoneType.Hand);
        Card div = MailboxTestKit.put("Divination", k.seat, ZoneType.Hand);
        Card scrying = MailboxTestKit.put("Sylvan Scrying", k.seat, ZoneType.Hand);
        Card charm = MailboxTestKit.put("Archdruid's Charm", k.seat, ZoneType.Hand);
        oppBears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
        MailboxTestKit.put("Sol Ring", k.opp, ZoneType.Battlefield);
        Card oppSpell = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Hand);
        oppSa = oppSpell.getSpellAbilities().get(0);
        oppSa.setActivatingPlayer(k.opp);
        bearsSa = bears.getSpellAbilities().get(0);
        bearsSa.setActivatingPlayer(k.seat);
        drawSa = div.getFirstSpellAbility();
        drawSa.setActivatingPlayer(k.seat);
        scryingSa = scrying.getFirstSpellAbility();
        scryingSa.setActivatingPlayer(k.seat);
        charmSa = charm.getFirstSpellAbility();
        charmSa.setActivatingPlayer(k.seat);

        k.startBrain(body -> {
            String s = surfaceUnderTest;
            if (s != null && body.contains("\"decisionType\":\"" + s + "\"")
                    && APPLIED.compareAndSet(false, true)) {
                return nextAnswer;
            }
            // Any OTHER window (a stock fallback re-entering a nested single
            // pick, e.g. chooseEntitiesForEffect's loop): the kit's legal
            // default answer. Never the malformed one twice.
            return null;
        });
    }

    @AfterClass(groups = "extended", alwaysRun = true)
    public static void shutdown() {
        if (k != null) {
            k.close();
        }
        if (savedTimeout == null) {
            System.clearProperty(MailboxProtocol.TIMEOUT_PROPERTY);
        } else {
            System.setProperty(MailboxProtocol.TIMEOUT_PROPERTY, savedTimeout);
        }
        System.out.println("FALLBACK-MATRIX: " + LOG.size() + " cells\n  " + String.join("\n  ", LOG));
    }

    /** Cells stay independent: a stock PAY_UNLESS may have tapped a land. */
    @BeforeMethod(groups = "extended")
    public void untapSeat() {
        for (Card c : k.seat.getCardsIn(ZoneType.Battlefield)) {
            c.setTapped(false);
        }
        charmSa.setChosenList(null);
    }

    @DataProvider(name = "cells")
    public static Object[][] cells() {
        List<Object[]> rows = new ArrayList<>();
        // the null-answer path once per surface (2 s each) — SILENT and
        // NON_JSON both end in a timeout: the protocol keeps polling past an
        // unparsable response file
        rows.add(new Object[] {"MULLIGAN", Kind.SILENT});
        rows.add(new Object[] {"CHOOSE_ENTITY", Kind.SILENT});
        rows.add(new Object[] {"CHOOSE_ENTITIES", Kind.NON_JSON});
        rows.add(new Object[] {"CHOOSE_CARD", Kind.NON_JSON});
        rows.add(new Object[] {"CHOOSE_CARDS", Kind.SILENT});
        rows.add(new Object[] {"CHOOSE_NUMBER", Kind.NON_JSON});
        rows.add(new Object[] {"PAY_UNLESS", Kind.NON_JSON});
        rows.add(new Object[] {"CONFIRM", Kind.SILENT});
        rows.add(new Object[] {"CHOOSE_MODE", Kind.SILENT});
        // parsed but malformed (fast): every applicable kind per surface
        for (String s : new String[] {"MULLIGAN", "CHOOSE_ENTITY", "CHOOSE_ENTITIES", "CHOOSE_CARD",
                "CHOOSE_CARDS", "CHOOSE_NUMBER", "PAY_UNLESS", "CONFIRM", "CHOOSE_MODE"}) {
            rows.add(new Object[] {s, Kind.WRONG_KEY});
            rows.add(new Object[] {s, Kind.WRONG_TYPE});
            if (!"MULLIGAN".equals(s)) {
                rows.add(new Object[] {s, Kind.OUT_OF_RANGE});
            }
        }
        for (String s : new String[] {"CHOOSE_ENTITIES", "CHOOSE_CARDS", "CHOOSE_MODE"}) {
            rows.add(new Object[] {s, Kind.DUPLICATE_IDS});
        }
        for (String s : new String[] {"CHOOSE_ENTITY", "CHOOSE_ENTITIES", "CHOOSE_CARD", "CHOOSE_CARDS"}) {
            rows.add(new Object[] {s, Kind.FOREIGN_ID});
        }
        return rows.toArray(new Object[0][]);
    }

    private static boolean listSurface(String s) {
        return "CHOOSE_ENTITIES".equals(s) || "CHOOSE_CARDS".equals(s) || "CHOOSE_MODE".equals(s);
    }

    /** The malformed answer for a cell; ids are live so foreign/duplicate ids are real. */
    private static String answerFor(String surface, Kind kind) {
        switch (kind) {
            case SILENT:
                return MailboxTestKit.SILENT;
            case NON_JSON:
                return "this is not json";
            case WRONG_KEY:
                return "{\"foo\": 1}";
            case WRONG_TYPE:
                if ("MULLIGAN".equals(surface)) {
                    return "{\"keep\": \"yes\"}";
                }
                if (listSurface(surface) || "CHOOSE_NUMBER".equals(surface)) {
                    return "{\"chosen\": \"x\"}";
                }
                return "{\"chosenId\": \"x\"}";
            case DUPLICATE_IDS:
                if ("CHOOSE_ENTITIES".equals(surface)) {
                    return "{\"chosen\": [" + bears.getId() + ", " + bears.getId() + "]}";
                }
                if ("CHOOSE_CARDS".equals(surface)) {
                    return "{\"chosen\": [" + darkRitual.getId() + ", " + darkRitual.getId() + "]}";
                }
                return "{\"chosen\": [0, 0]}";                       // CHOOSE_MODE
            case OUT_OF_RANGE:
                if ("CHOOSE_NUMBER".equals(surface)) {
                    return "{\"chosen\": 99}";
                }
                if ("CHOOSE_MODE".equals(surface)) {
                    return "{\"chosen\": [7]}";
                }
                if ("PAY_UNLESS".equals(surface) || "CONFIRM".equals(surface)) {
                    return "{\"chosenId\": 7}";
                }
                if (listSurface(surface)) {
                    return "{\"chosen\": [999999]}";
                }
                return "{\"chosenId\": 999999}";
            case FOREIGN_ID:
                if ("CHOOSE_ENTITY".equals(surface)) {
                    return "{\"chosenId\": " + libSwamp.getId() + "}";   // a library card, not an option
                }
                if ("CHOOSE_ENTITIES".equals(surface)) {
                    return "{\"chosen\": [" + libSwamp.getId() + "]}";
                }
                if ("CHOOSE_CARD".equals(surface)) {
                    return "{\"chosenId\": " + bears.getId() + "}";      // battlefield, not the fetch list
                }
                return "{\"chosen\": [" + bears.getId() + "]}";          // CHOOSE_CARDS: not in hand
            default:
                throw new IllegalArgumentException(String.valueOf(kind));
        }
    }

    /** Every zone's card ids for both players, both lives, the stack depth. */
    private static String snapshot() {
        StringBuilder sb = new StringBuilder();
        for (Player p : new Player[] {k.seat, k.opp}) {
            sb.append(p.getName()).append(" life=").append(p.getLife());
            for (ZoneType z : new ZoneType[] {ZoneType.Battlefield, ZoneType.Hand, ZoneType.Library,
                    ZoneType.Graveyard, ZoneType.Exile, ZoneType.Command}) {
                sb.append(' ').append(z).append('=');
                for (Card c : p.getCardsIn(z)) {
                    sb.append(c.getId()).append(',');
                }
            }
            sb.append('\n');
        }
        sb.append("stack=").append(k.game.getStack().size());
        return sb.toString();
    }

    private static int tappedSeat() {
        int n = 0;
        for (Card c : k.seat.getCardsIn(ZoneType.Battlefield)) {
            if (c.isTapped()) {
                n++;
            }
        }
        return n;
    }

    @Test(groups = "extended", dataProvider = "cells", timeOut = 60_000)
    public void malformedAnswerFallsToStockWithoutPartialApplication(String surface, Kind kind) {
        MailboxController c = k.controller();
        String answer = answerFor(surface, kind);
        APPLIED.set(false);
        nextAnswer = answer;
        surfaceUnderTest = surface;
        String before = snapshot();
        int tappedBefore = tappedSeat();
        int fallbacksBefore = MailboxController.stockFallbacksFor(k.seat);
        long requestsBefore = k.seen.size();
        boolean nullPath = kind == Kind.SILENT || kind == Kind.NON_JSON;

        String result;
        boolean mayTap = false;
        switch (surface) {
            case "MULLIGAN": {
                boolean keep = c.mulliganKeepHand(k.seat, 1);
                result = "keep=" + keep;
                break;
            }
            case "CHOOSE_ENTITY": {
                Card pick = c.chooseSingleEntityForEffect(new CardCollection(List.of(bears, elves)), null,
                        bearsSa, "Choose a creature", false, null, null);
                Assert.assertTrue(pick == bears || pick == elves,
                        surface + "/" + kind + ": a mandatory pick must come from the option list, got " + pick);
                result = String.valueOf(pick);
                break;
            }
            case "CHOOSE_ENTITIES": {
                List<Card> opts = List.of(bears, elves, oppBears);
                List<Card> picks = c.chooseEntitiesForEffect(new CardCollection(opts), 0, 2, null,
                        bearsSa, "Choose up to two", null, null);
                Assert.assertNotNull(picks, surface + "/" + kind + ": stock must still answer");
                Assert.assertTrue(picks.size() <= 2, surface + "/" + kind + ": at most two, got " + picks);
                Assert.assertEquals(new HashSet<>(picks).size(), picks.size(),
                        surface + "/" + kind + ": no duplicates may be applied: " + picks);
                Assert.assertTrue(opts.containsAll(picks),
                        surface + "/" + kind + ": every pick must be an option: " + picks);
                result = String.valueOf(picks);
                break;
            }
            case "CHOOSE_CARD": {
                CardCollection fetch = new CardCollection(k.seat.getCardsIn(ZoneType.Library));
                Card pick = c.chooseSingleCardForZoneChange(ZoneType.Hand, List.of(ZoneType.Library), scryingSa,
                        fetch, null, "Search", true, k.seat);
                Assert.assertTrue(pick == null || fetch.contains(pick),
                        surface + "/" + kind + ": an optional pick is none or from the fetch list, got " + pick);
                result = String.valueOf(pick);
                break;
            }
            case "CHOOSE_CARDS": {
                // stock's getCardsToDiscard CONSUMES the validCards argument it
                // is handed (removes what it picks), so membership is checked
                // against a snapshot; the real hand zone is covered by the
                // board snapshot below
                List<Card> hand = new ArrayList<>(k.seat.getCardsIn(ZoneType.Hand));
                CardCollection picks = c.chooseCardsToDiscardFrom(k.seat, drawSa, new CardCollection(hand), 1, 1, null);
                Assert.assertNotNull(picks, surface + "/" + kind + ": stock must still answer");
                Assert.assertEquals(picks.size(), 1, surface + "/" + kind + ": exactly one discard, got " + picks);
                Assert.assertTrue(hand.containsAll(picks),
                        surface + "/" + kind + ": the discard must come from the hand: " + picks);
                result = String.valueOf(picks);
                break;
            }
            case "CHOOSE_NUMBER": {
                int n = c.chooseNumber(drawSa, "Pick a number", 0, 3);
                Assert.assertTrue(n >= 0 && n <= 3, surface + "/" + kind + ": out of bounds: " + n);
                result = "n=" + n;
                break;
            }
            case "PAY_UNLESS": {
                boolean paid = c.payCostToPreventEffect(new Cost("1", false), oppSa, false,
                        new FCollection<>(List.of(k.seat)));
                mayTap = paid; // paying {1} legitimately taps one land — and nothing else
                result = "paid=" + paid;
                break;
            }
            case "CONFIRM": {
                boolean yes = c.confirmAction(oppSa, PlayerActionConfirmMode.OptionalChoose,
                        "Draw a card?", null, null, null);
                result = "yes=" + yes;
                break;
            }
            case "CHOOSE_MODE": {
                List<AbilitySub> possible = new ArrayList<>(charmSa.getAdditionalAbilityList("Choices"));
                Assert.assertEquals(possible.size(), 3, "Archdruid's Charm has three modes");
                List<AbilitySub> modes = c.chooseModeForAbility(charmSa, possible, 1, 1, false);
                // stock's CharmAi may decline a spell-speed charm outright (null
                // = no modes chained, the spell does nothing) — legal for
                // stock; anything it does return must be one option, once
                if (modes != null) {
                    Assert.assertTrue(modes.size() <= 1, surface + "/" + kind + ": one mode at most: " + modes);
                    Assert.assertTrue(possible.containsAll(modes),
                            surface + "/" + kind + ": modes must be options: " + modes);
                }
                result = String.valueOf(modes);
                break;
            }
            default:
                throw new IllegalArgumentException(surface);
        }

        // the window actually opened (the answer reached the surface under test)
        Assert.assertTrue(k.seen.size() > requestsBefore && APPLIED.get(),
                surface + "/" + kind + ": the surface must have opened a window and taken the answer");
        // no partial application: zones, lives, stack untouched
        Assert.assertEquals(snapshot(), before,
                surface + "/" + kind + ": a malformed answer must not move a card or change a life total");
        int tappedDelta = tappedSeat() - tappedBefore;
        if (mayTap) {
            Assert.assertTrue(tappedDelta >= 0 && tappedDelta <= 1,
                    surface + "/" + kind + ": paying {1} taps at most one land, tapped delta " + tappedDelta);
        } else {
            Assert.assertEquals(tappedDelta, 0, surface + "/" + kind + ": nothing may be tapped");
        }
        // the stock-fallback counter: exactly one for a null answer, none for a parsed one
        int fallbacks = MailboxController.stockFallbacksFor(k.seat) - fallbacksBefore;
        if (nullPath) {
            Assert.assertEquals(fallbacks, 1,
                    surface + "/" + kind + ": a null answer is ONE counted stock fallback");
        } else {
            Assert.assertEquals(fallbacks, 0,
                    surface + "/" + kind + ": a parsed answer is not a 'brain did not answer' event");
        }
        LOG.add(surface + " x " + kind + " -> " + result + (nullPath ? " (stock, counted)" : " (stock)"));
        surfaceUnderTest = null;
    }
}
