package forge.arena.interactive;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.testng.Assert;
import org.testng.annotations.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;

import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.cost.Cost;
import forge.game.player.PlayerActionConfirmMode;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

/**
 * Interactive plan item 15: the mailbox wire contract, tested from both
 * sides. This class drives a representative set of decision surfaces through
 * the real controller, validates EVERY request the engine wrote against
 * {@code schemas/arena.mailbox-request.1.schema.json}, and writes the first
 * request of each decision type to {@code runner/tests/fixtures/engine/} —
 * engine-emitted fixtures the Python suite then feeds through
 * {@code rules.safe_default} and {@code rules.validate}. Before this, the two
 * sides were two hand-maintained readings of a prose spec, and the fixtures
 * the Python tests used were hand-written.
 */
public class ProtocolContractTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Path SCHEMA = Path.of("schemas", "arena.mailbox-request.1.schema.json");
    private static final Path ENGINE_FIXTURES = Path.of("runner", "tests", "fixtures", "engine");

    private static JsonSchema schema() throws Exception {
        try (InputStream in = Files.newInputStream(SCHEMA)) {
            return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(in);
        }
    }

    @Test(timeOut = 240_000)
    public void everyEmittedRequestValidatesAndBecomesAnEngineFixture() throws Exception {
        try (MailboxTestKit k = new MailboxTestKit(false)) {
            // answers that keep each surface moving; all shapes are exercised
            k.startBrain(body -> {
                if (body.contains("\"decisionType\":\"MULLIGAN\"")) {
                    return "{\"keep\": true}";
                }
                if (body.contains("\"decisionType\":\"CHOOSE_ENTITIES\"")
                        || body.contains("\"decisionType\":\"CHOOSE_CARDS\"")
                        || body.contains("\"decisionType\":\"CHOOSE_MODE\"")) {
                    return "{\"chosen\": []}";
                }
                if (body.contains("\"decisionType\":\"CHOOSE_NUMBER\"")) {
                    return "{\"chosen\": 1}";
                }
                if (body.contains("\"decisionType\":\"DECLARE_ATTACKERS\"")) {
                    return "{\"attackers\": []}";
                }
                if (body.contains("\"decisionType\":\"DECLARE_BLOCKERS\"")) {
                    return "{\"blocks\": []}";
                }
                return "{\"chosenId\": 0}";
            });
            // a board with something in every zone the state projects
            for (int i = 0; i < 3; i++) {
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Battlefield);
                MailboxTestKit.put("Swamp", k.seat, ZoneType.Library);
            }
            MailboxTestKit.put("Sol Ring", k.seat, ZoneType.Battlefield);
            Card bears = MailboxTestKit.put("Grizzly Bears", k.seat, ZoneType.Battlefield);
            Card elves = MailboxTestKit.put("Llanowar Elves", k.seat, ZoneType.Battlefield);
            MailboxTestKit.put("Dark Ritual", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Counterspell", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Divination", k.seat, ZoneType.Hand);
            MailboxTestKit.put("Island", k.seat, ZoneType.Graveyard);
            Card oppBears = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Battlefield);
            Card oppSpell = MailboxTestKit.put("Grizzly Bears", k.opp, ZoneType.Hand);
            SpellAbility oppSa = oppSpell.getSpellAbilities().get(0);
            oppSa.setActivatingPlayer(k.opp);
            MailboxController c = k.controller();

            // direct surfaces
            c.mulliganKeepHand(k.seat, 1);
            c.chooseSingleEntityForEffect(new CardCollection(List.of(bears, elves)), null, null,
                    "Choose a creature", true, null, null);
            c.chooseEntitiesForEffect(new CardCollection(List.of(bears, elves, oppBears)), 0, 2, null,
                    null, "Choose up to two", null, null);
            c.chooseSingleCardForZoneChange(ZoneType.Hand, List.of(ZoneType.Library), null,
                    new CardCollection(k.seat.getCardsIn(ZoneType.Library)), null, "Search", true, k.seat);
            c.chooseCardsToDiscardFrom(k.seat, null, new CardCollection(k.seat.getCardsIn(ZoneType.Hand)),
                    1, 1, null);
            c.chooseNumber(null, "Pick a number", 0, 3);
            c.payCostToPreventEffect(new Cost("1", false), oppSa, false, null);
            c.confirmAction(oppSa, PlayerActionConfirmMode.OptionalChoose, "Draw a card?", null, null, null);
            // the cast window: our main phase with a castable spell
            k.run(() -> k.seen.stream().anyMatch(s -> s.contains("\"decisionType\":\"CAST_SPELL\"")), 60);
            k.stopBrain();

            JsonSchema schema = schema();
            Map<String, JsonNode> firstByType = new LinkedHashMap<>();
            List<String> problems = new ArrayList<>();
            List<String> bodies = new ArrayList<>(k.seen);
            for (String body : bodies) {
                JsonNode node = MAPPER.readTree(body);
                Set<ValidationMessage> errors = schema.validate(node);
                String type = node.path("decisionType").asText();
                if (!errors.isEmpty()) {
                    problems.add(type + ": " + errors);
                }
                firstByType.putIfAbsent(type, node);
            }
            System.out.println("PROTOCOL-CONTRACT: " + bodies.size() + " requests, types "
                    + firstByType.keySet() + ", schema problems " + problems.size());
            Assert.assertTrue(problems.isEmpty(), "engine requests must validate:\n" + String.join("\n", problems));
            for (String must : new String[] {"MULLIGAN", "CHOOSE_ENTITY", "CHOOSE_ENTITIES", "CHOOSE_CARD",
                    "CHOOSE_CARDS", "CHOOSE_NUMBER", "PAY_UNLESS", "CONFIRM", "CAST_SPELL"}) {
                Assert.assertTrue(firstByType.containsKey(must), "surface not exercised: " + must);
            }

            // engine-emitted fixtures for the Python side
            Files.createDirectories(ENGINE_FIXTURES);
            for (Map.Entry<String, JsonNode> e : firstByType.entrySet()) {
                Path out = ENGINE_FIXTURES.resolve(e.getKey().toLowerCase() + ".json");
                Files.writeString(out, MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(e.getValue()) + "\n");
            }
        }
    }
}
