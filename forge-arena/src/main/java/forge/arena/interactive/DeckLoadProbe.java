package forge.arena.interactive;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import forge.StaticData;
import forge.arena.bootstrap.ArenaBootstrap;
import forge.card.CardDb;
import forge.card.CardEdition;
import forge.deck.Deck;
import forge.deck.DeckSection;
import forge.deck.io.DeckSerializer;
import forge.item.PaperCard;

/**
 * Loadability probe for a Commander .dck THROUGH THE REAL LOADER (2026-09-01).
 * Two consecutive new decks failed at their FIRST live launch on defects the
 * file-presence preflight cannot see: a raw Moxfield export (no sections) and
 * a transform commander written as "A // B" (Forge names transform cards by
 * their front face, so DeckSerializer resolved no commander). This probe is
 * arena-add-deck's final gate: it loads the deck exactly as GuiPilotMatch
 * will and fails loudly on missing commanders or dropped (unresolvable)
 * cards.
 *
 * <p>Interactive plan item 7 (2026-09-03) adds a <b>resolve mode</b>: the
 * ingester asks THIS database what Forge calls each Scryfall card, joining on
 * the PRINTING (set + collector number, Forge's edition data) first and on
 * name forms second, so no layout whitelist is ever maintained. Scryfall
 * stays canonical in every built file; Forge's name is the runtime encoding
 * written to the .dck.
 *
 * <pre>
 *   DeckLoadProbe &lt;deck.dck&gt; &lt;forge-gui-dir&gt;           # probe a deck
 *   DeckLoadProbe --resolve &lt;forge-gui-dir&gt; &lt; lines     # one JSON per line:
 *       {"name":"A // B","set":"dsk","collector_number":"10"}
 *     → {"name":…,"forge_name":…,"method":"printing|name|front|unresolved"}
 * </pre>
 */
public final class DeckLoadProbe {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private DeckLoadProbe() {
    }

    /** Names in the deck that resolved only to CardDb's unsupported placeholder
     *  ({@code CardRules.isUnsupported()}); empty string when the deck is clean. */
    public static String unsupportedNames(Deck deck) {
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<PaperCard, Integer> e : deck.getAllCardsInASinglePool()) {
            if (e.getKey().getRules() != null && e.getKey().getRules().isUnsupported()) {
                if (sb.length() > 0) {
                    sb.append(", ");
                }
                sb.append('\'').append(e.getKey().getName()).append('\'');
            }
        }
        return sb.toString();
    }

    /**
     * Everything that would make this deck play short or not at all, as
     * human-readable problems; empty when the deck is exactly what the loader
     * will seat. Shared by the probe's CLI and GuiPilotMatch's start invariant
     * (plan item 7: a game never starts with fewer than 100 real cards a seat).
     */
    public static List<String> playabilityProblems(Deck deck) {
        List<String> problems = new ArrayList<>();
        if (deck == null) {
            problems.add("DeckSerializer returned null (bad file format?)");
            return problems;
        }
        int commanders = deck.getCommanders().size();
        int main = deck.get(DeckSection.Main) != null ? deck.get(DeckSection.Main).countAll() : 0;
        int total = commanders + main;
        if (commanders < 1) {
            problems.add("no commander resolved — a double-faced commander must use "
                    + "Forge's FRONT-FACE name (e.g. 'Sheoldred', not "
                    + "'Sheoldred // The True Scriptures')");
        }
        if (total != 100) {
            problems.add(total + " cards resolved, expected 100");
        }
        String unsupported = unsupportedNames(deck);
        if (!unsupported.isEmpty()) {
            problems.add("unresolvable card names (the match would DROP them): "
                    + unsupported + " — double-faced cards (transform / modal DFC / "
                    + "adventure / disturb) must use Forge's FRONT-FACE name; only true "
                    + "split cards (and Rooms) keep 'A // B'");
        }
        return problems;
    }

    // ---- resolve mode (plan item 7) -------------------------------------------

    /** Forge's edition for a Scryfall set code: Forge's own code, an alias,
     *  or an edition whose ScryfallCode matches. */
    static CardEdition editionFor(String setCode) {
        if (setCode == null || setCode.isEmpty()) {
            return null;
        }
        CardEdition.Collection eds = StaticData.instance().getEditions();
        CardEdition ed = eds.get(setCode.toUpperCase(java.util.Locale.ROOT));
        if (ed != null) {
            return ed;
        }
        for (CardEdition e : eds) {
            try {
                // getScryfallCode() NPEs on editions with no ScryfallCode line
                // (found live, 2026-09-03: one such edition aborted a whole
                // resolve run and every later card read as "unresolved")
                if (setCode.equalsIgnoreCase(e.getScryfallCode())) {
                    return e;
                }
            } catch (RuntimeException ignore) {
                // edition without a Scryfall code — not a match
            }
        }
        return null;
    }

    private static PaperCard realCard(CardDb db, String name) {
        if (name == null || name.isEmpty()) {
            return null;
        }
        PaperCard pc = db.getCard(name);
        if (pc == null || pc.getRules() == null || pc.getRules().isUnsupported()) {
            return null;
        }
        return pc;
    }

    private static String front(String name) {
        return name != null && name.contains(" // ") ? name.split(" // ")[0].trim() : name;
    }

    /**
     * What Forge calls this card. Order: (1) the PRINTING — the edition for
     * the Scryfall set, its entry at the collector number, that entry's name
     * (combined, then front face) against the card database; (2) the name
     * forms — Scryfall's full name, then its front face; (3) unresolved.
     */
    static Map<String, Object> resolve(String name, String set, String collectorNumber) {
        CardDb db = StaticData.instance().getCommonCards();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", name);
        CardEdition ed = editionFor(set);
        out.put("edition", ed != null ? ed.getCode() : null);
        if (ed != null && collectorNumber != null && !collectorNumber.isEmpty()) {
            CardEdition.EditionEntry entry = ed.getCardFromCollectorNumber(collectorNumber);
            if (entry != null) {
                for (String cand : new String[] {entry.name(), front(entry.name())}) {
                    PaperCard pc = realCard(db, cand);
                    if (pc != null) {
                        out.put("forge_name", pc.getName());
                        out.put("method", "printing");
                        return out;
                    }
                }
            }
        }
        PaperCard pc = realCard(db, name);
        if (pc != null) {
            out.put("forge_name", pc.getName());
            out.put("method", "name");
            return out;
        }
        pc = realCard(db, front(name));
        if (pc != null) {
            out.put("forge_name", pc.getName());
            out.put("method", "front");
            return out;
        }
        out.put("forge_name", null);
        out.put("method", "unresolved");
        return out;
    }

    private static int runResolve(String forgeGuiDir) throws IOException {
        ArenaBootstrap.initialize(new File(forgeGuiDir));
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        int unresolved = 0;
        while ((line = in.readLine()) != null) {
            if (line.trim().isEmpty()) {
                continue;
            }
            JsonNode req = MAPPER.readTree(line);
            Map<String, Object> res;
            try {
                res = resolve(
                        req.path("name").asText(null),
                        req.path("set").asText(null),
                        req.path("collector_number").asText(null));
            } catch (RuntimeException e) {
                // one bad line must never silence the rest of the stream; the
                // caller sees an explicit error for THIS card
                res = new LinkedHashMap<>();
                res.put("name", req.path("name").asText(null));
                res.put("forge_name", null);
                res.put("method", "error");
                res.put("error", String.valueOf(e));
            }
            if (!"printing".equals(res.get("method")) && !"name".equals(res.get("method"))
                    && !"front".equals(res.get("method"))) {
                unresolved++;
            }
            System.out.println(MAPPER.writeValueAsString(res));
        }
        System.out.flush();
        return unresolved == 0 ? 0 : 1;
    }

    public static void main(String[] args) throws IOException {
        if (args.length >= 2 && "--resolve".equals(args[0])) {
            System.exit(runResolve(args[1]));
        }
        if (args.length < 2) {
            System.err.println("usage: DeckLoadProbe <deck.dck> <forge-gui-dir>  |  "
                    + "DeckLoadProbe --resolve <forge-gui-dir> < json-lines");
            System.exit(2);
        }
        ArenaBootstrap.initialize(new File(args[1]));
        Deck deck = DeckSerializer.fromFile(new File(args[0]));
        if (deck != null) {
            int commanders = deck.getCommanders().size();
            int main = deck.get(DeckSection.Main) != null
                    ? deck.get(DeckSection.Main).countAll() : 0;
            System.out.println("PROBE: '" + deck.getName() + "' commanders=" + commanders
                    + " main=" + main + " total=" + (commanders + main));
        }
        List<String> problems = playabilityProblems(deck);
        if (!problems.isEmpty()) {
            for (String p : problems) {
                System.err.println("PROBE FAIL: " + p);
            }
            System.exit(1);
        }
        System.out.println("PROBE OK");
    }
}
