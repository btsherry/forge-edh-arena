package forge.arena.report;

import static org.testng.AssertJUnit.assertEquals;
import static org.testng.AssertJUnit.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

import org.testng.annotations.Test;

/**
 * §7 reducers on synthetic fixtures: Wilson intervals against known values,
 * the funnel (ready→attempted→shortcut→converted + hesitation + reasons),
 * fingerprints from turn_summary, and the paired-seed A/B contract.
 */
public class BatchStatsTest {

    @Test
    public void wilsonMatchesKnownValues() {
        double[] empty = BatchStats.wilson(0, 0);
        assertEquals(0.0, empty[0], 1e-9);
        assertEquals(1.0, empty[1], 1e-9);
        // 5/20 = 25%: the small-n interval is honestly wide
        double[] ci = BatchStats.wilson(5, 20);
        assertEquals(0.1118, ci[0], 1e-3);
        assertEquals(0.4687, ci[1], 1e-3);
        // certainty shrinks it
        double[] big = BatchStats.wilson(250, 1000);
        assertTrue(big[1] - big[0] < 0.06);
    }

    private Path syntheticBatch() throws Exception {
        Path dir = Files.createTempDirectory("batchstats");
        Files.writeString(dir.resolve("run-manifest.json"), """
                {"seats": [{"deck": "selvala"}, {"deck": "purphoros"}]}""");
        Files.createDirectories(dir.resolve("events"));
        Files.writeString(dir.resolve("events").resolve("000000.jsonl"), """
                {"t":"game_start","seats":["selvala","purphoros"],"seed":1}
                {"t":"combo_ready","turn":3,"seat":0,"combo":"c1","window":"MAIN1"}
                {"t":"combo_ignored","turn":3,"seat":0,"combo":"c1","reason":"mana_reserved"}
                {"t":"route_selected","turn":5,"seat":0,"route":"SPREAD_COMBAT","predicates":{}}
                {"t":"combo_shortcut","turn":5,"seat":0,"combo":"c1","iterations_proven":3,"bounded_product":{}}
                {"t":"turn_summary","turn":5,"seats":[{"seat":0,"damage_dealt":{"combat":7,"other":3},"damage_taken":0,"drawn":2,"discarded":[],"spells":4,"lands":1,"creatures_entered":2,"creatures_died":0}]}
                {"t":"turn_summary","turn":6,"seats":[{"seat":0,"damage_dealt":{"combat":10,"other":0},"damage_taken":2,"drawn":1,"discarded":[],"spells":2,"lands":0,"creatures_entered":1,"creatures_died":1}]}
                {"t":"game_end","turn":7,"win_condition":"AllOpponentsLost","winner_seat":0}
                """);
        Files.writeString(dir.resolve("events").resolve("000001.jsonl"), """
                {"t":"game_start","seats":["purphoros","selvala"],"seed":2}
                {"t":"combo_ready","turn":4,"seat":1,"combo":"c1","window":"MAIN1"}
                {"t":"game_end","turn":31,"win_condition":"Draw"}
                """);
        Files.writeString(dir.resolve("game-records.jsonl"), """
                {"game_index":0,"seed":1,"seats":["selvala","purphoros"],"result":"win","winner_seat":0,"win_condition":"AllOpponentsLost","turns":7,"event_log":"events/000000.jsonl"}
                {"game_index":1,"seed":2,"seats":["purphoros","selvala"],"result":"timeout_draw","limiting_factor":"turns","turns":31,"event_log":"events/000001.jsonl"}
                """);
        return dir;
    }

    @Test
    public void reduceComputesRatesFunnelAndFingerprints() throws Exception {
        Map<String, BatchStats.DeckStats> decks = BatchStats.reduce(syntheticBatch());
        BatchStats.DeckStats selvala = decks.get("selvala");

        assertEquals(2, selvala.games);
        assertEquals(1, selvala.wins);
        assertEquals(1, selvala.timeouts);
        assertEquals(1, selvala.winsBySeat[0]);
        assertEquals(Map.of("AllOpponentsLost", 1), selvala.winConditions);

        // funnel: game 0 ready t3 -> shortcut t5 (hesitation 2, converted);
        // game 1 ready with no attempt
        assertEquals(2, selvala.readyGames);
        assertEquals(1, selvala.attemptedGames);
        assertEquals(1, selvala.shortcutGames);
        assertEquals(1, selvala.convertedGames);
        assertEquals(java.util.List.of(2), selvala.hesitations);
        assertEquals(Map.of("mana_reserved", 1), selvala.ignoredReasons);
        assertEquals(Map.of("SPREAD_COMBAT", 1), selvala.routesSelected);

        // fingerprints: 2 summary turns, 20 dmg, 3 drawn, 6 spells, 1 land
        assertEquals(2, selvala.summaryTurns);
        assertEquals(20, selvala.dmgDealt);
        assertEquals(3, selvala.drawn);
        assertEquals(6, selvala.spells);
        assertEquals(1, selvala.landDrops);

        String rendered = BatchStats.render(decks);
        assertTrue(rendered.contains("selvala"));
        assertTrue(rendered.contains("funnel"));
        assertTrue(rendered.contains("dmg/turn=10.00"));
    }

    @Test
    public void pairedCompareCountsFlipsAndRefusesUnpairedSeeds() throws Exception {
        Path a = syntheticBatch();
        Path b = syntheticBatch();
        // flip game 0's winner in B: selvala -> purphoros
        String records = Files.readString(b.resolve("game-records.jsonl"))
                .replace("\"winner_seat\":0", "\"winner_seat\":1");
        Files.writeString(b.resolve("game-records.jsonl"), records);

        String report = BatchStats.compare(a, b);
        assertTrue(report.contains("paired games: 2"));
        assertTrue("selvala won in A only", report.matches(
                "(?s).*selvala\\s+1\\s+0\\s+0.*"));
        assertTrue("purphoros won in B only", report.matches(
                "(?s).*purphoros\\s+0\\s+1\\s+0.*"));

        // different seeds must refuse loudly, never mislead
        String mismatched = Files.readString(b.resolve("game-records.jsonl"))
                .replace("\"seed\":1", "\"seed\":99");
        Files.writeString(b.resolve("game-records.jsonl"), mismatched);
        assertTrue(BatchStats.compare(a, b).startsWith("NOT PAIRED"));
    }
}
