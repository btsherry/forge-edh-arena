package forge.arena.interactive;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;

import org.testng.Assert;
import org.testng.annotations.Test;

/**
 * The observer snapshot's cadence (2026-09-14, Ben: "at most one write a
 * second — something cheap that is mostly right"): a changed fingerprint
 * writes only once the window since the last write has passed; a change
 * inside the window is ONE deferred write when it expires, so the LAST event
 * of a burst is always on disk; an unchanged board never writes; the first
 * snapshot and game over write at once. Uses the kit's game (the mailbox
 * lobby player registers the snapshot under the kit's base dir); the window
 * is the {@code arena.observer.ms} property, read at registration.
 *
 * <p>Real clock (2026-09-16): every "no write YET" assertion runs under a 60 s
 * window, so a GC stall cannot expire the window under it; every "writes
 * AFTER the window" assertion runs under a short explicit window (300 ms)
 * with a generous wait. Nothing here measures the default 1000 ms window.
 */
public class ObserverSnapshotWriteTest {

    /** A kit whose observer window is {@code ms}. */
    private static MailboxTestKit kit(long ms) throws Exception {
        System.setProperty(ObserverSnapshot.INTERVAL_PROPERTY, Long.toString(ms));
        try {
            return new MailboxTestKit(false);
        } finally {
            System.clearProperty(ObserverSnapshot.INTERVAL_PROPERTY);
        }
    }

    /** The snapshot body once it contains {@code needle} (a deferred write may
     *  still be in flight), else the last body read when {@code timeoutMs} ran out. */
    private static String awaitBody(Path snap, String needle, long timeoutMs) throws Exception {
        long deadline = System.nanoTime() + timeoutMs * 1_000_000L;
        String body;
        do {
            body = Files.readString(snap);
            if (body.contains(needle)) {
                return body;
            }
            Thread.sleep(10);
        } while (System.nanoTime() < deadline);
        return body;
    }

    /** This game's write count once it reaches {@code atLeast}, or whatever it
     *  is when {@code timeoutMs} runs out. Per game, not {@link ObserverSnapshot#WRITES}:
     *  in the full suite an earlier test's game can still have a deferred write
     *  pending on its own timer, and that moves the JVM-wide counter. */
    private static int awaitWrites(ObserverSnapshot obs, int atLeast, long timeoutMs) throws Exception {
        long deadline = System.nanoTime() + timeoutMs * 1_000_000L;
        while (obs.writes() < atLeast && System.nanoTime() < deadline) {
            Thread.sleep(10);
        }
        return obs.writes();
    }

    /** A burst right after the first snapshot is no write at all inside the
     *  window: ONE deferred write is scheduled and the changes stay off disk.
     *  A 60 s window, so the clock cannot expire it under the assertions. */
    @Test(timeOut = 120_000)
    public void aBurstInsideTheWindowWaitsAsOneDeferredWrite() throws Exception {
        try (MailboxTestKit k = kit(60_000)) {
            Path snap = k.base.resolve("observer-state.json");
            Assert.assertTrue(Files.exists(snap), "initial snapshot written at registration");
            Assert.assertTrue(Files.readString(snap).contains("\"gameId\":\"" + MailboxController.gameIdFor(k.game) + "\""),
                    "the snapshot names its game with the id the seat requests carry (2026-09-18)");
            ObserverSnapshot obs = ObserverSnapshot.of(k.game);
            Assert.assertNotNull(obs, "the kit's game has its observer");
            int before = obs.writes();
            k.seat.setLife(33, null);
            k.seat.setLife(31, null);
            k.seat.setLife(29, null);
            Assert.assertEquals(obs.writes(), before, "inside the window: no write yet");
            Assert.assertEquals(obs.deferredWrites(), 1, "the burst scheduled exactly one deferred write");
            Assert.assertFalse(Files.readString(snap).contains("\"life\":29"), "not on disk yet");
            Assert.assertFalse(Files.readString(snap).contains("\"life\":33"), "nor the first change of the burst");
        }
    }

    /** Short window (300 ms): the deferred write lands once the window expires,
     *  exactly one for the burst, carrying the LAST change. The clock is reset by
     *  a priming write just before the burst, so the burst is inside the window
     *  by microseconds, not by whatever the kit's construction left of it. */
    @Test(timeOut = 120_000)
    public void aBurstIsOneWriteCarryingTheLastChangeAfterTheWindow() throws Exception {
        try (MailboxTestKit k = kit(300)) {
            Path snap = k.base.resolve("observer-state.json");
            ObserverSnapshot obs = ObserverSnapshot.of(k.game);
            int w0 = obs.writes();      // counted BEFORE the prime: it may land at once (critic, 2026-09-16)
            k.seat.setLife(35, null);   // priming change: lands at once or at the window's end
            awaitWrites(obs, w0 + 1, 5_000);
            int before = obs.writes();
            Assert.assertTrue(Files.readString(snap).contains("\"life\":35"), "primed");
            k.seat.setLife(33, null);
            k.seat.setLife(31, null);
            k.seat.setLife(29, null);
            Assert.assertEquals(awaitWrites(obs, before + 1, 5_000), before + 1, "one deferred write when the window expires");
            Assert.assertTrue(Files.readString(snap).contains("\"life\":29"), "the LAST change of the burst is on disk");
            Thread.sleep(1_000);   // three further windows
            Assert.assertEquals(obs.writes(), before + 1, "the burst was exactly one write");
        }
    }

    /** 2026-09-16 (critic): a tap, a counter, poison — changes the fingerprint
     *  does not READ — still write at the next window, through the mutation
     *  tick. Before this a permanent tapped by an ability that resolved inside
     *  one window stayed untapped on disk until an unrelated change. */
    @Test(timeOut = 120_000)
    public void aTapAloneWritesAfterTheWindow() throws Exception {
        try (MailboxTestKit k = kit(300)) {
            Path snap = k.base.resolve("observer-state.json");
            ObserverSnapshot obs = ObserverSnapshot.of(k.game);
            forge.game.card.Card bear = MailboxTestKit.put("Grizzly Bears", k.opp, forge.game.zone.ZoneType.Battlefield);
            String body = awaitBody(snap, "\"name\":\"Grizzly Bears\"", 5_000);
            Assert.assertTrue(body.contains("\"tapped\":false"), "untapped on arrival: " + body);
            Assert.assertFalse(body.contains("\"tapped\":true"), body);
            // the tap: same battlefield size, same life, same stack, no ring entry
            Assert.assertTrue(bear.tap(false, null, k.opp), "the bear taps");
            body = awaitBody(snap, "\"tapped\":true", 5_000);
            Assert.assertTrue(body.contains("\"tapped\":true"), "the tap alone reached the disk: " + body);
            // poison: read by no fingerprint field either
            k.seat.setPoisonCounters(3, k.opp);
            body = awaitBody(snap, "\"poison\":3", 5_000);
            Assert.assertTrue(body.contains("\"poison\":3"), "poison alone reached the disk: " + body);
            // and back: the untap is a further tick, not a return to an older key
            int writes = obs.writes();
            Assert.assertTrue(bear.untap(), "the bear untaps");
            Assert.assertEquals(awaitWrites(obs, writes + 1, 5_000), writes + 1, "the untap writes too");
            Assert.assertFalse(Files.readString(snap).contains("\"tapped\":true"), "untapped on disk again");
        }
    }

    /** Events that change nothing in the fingerprint never write; a change
     *  after the window has passed writes at once. */
    @Test(timeOut = 120_000)
    public void anUnchangedBoardNeverWrites() throws Exception {
        try (MailboxTestKit k = kit(100)) {
            Path snap = k.base.resolve("observer-state.json");
            k.seat.setLife(29, null);
            Assert.assertTrue(awaitBody(snap, "\"life\":29", 3_000).contains("\"life\":29"));
            ObserverSnapshot obs = ObserverSnapshot.of(k.game);
            int writes = obs.writes();
            // the same life again: events, but no visible change -> no write, ever
            k.seat.setLife(29, null);
            k.seat.setLife(29, null);
            Thread.sleep(350);   // three windows
            Assert.assertEquals(obs.writes(), writes, "identical state never rewrites");
            // the window has long passed: a real change writes at once
            k.seat.setLife(27, null);
            Assert.assertEquals(obs.writes(), writes + 1, "a change after the window writes at once");
            Assert.assertTrue(Files.readString(snap).contains("\"life\":27"));
        }
    }

    /** Game over ignores the window: the final board (with any change still
     *  waiting for its deferred write) lands at once, and the game's one
     *  summary line goes to stderr. */
    @Test(timeOut = 120_000)
    public void gameOverWritesImmediatelyAndPrintsTheSummary() throws Exception {
        try (MailboxTestKit k = kit(60_000)) {
            Path snap = k.base.resolve("observer-state.json");
            ObserverSnapshot obs = ObserverSnapshot.of(k.game);
            int before = obs.writes();
            k.seat.setLife(21, null);
            Assert.assertEquals(obs.writes(), before, "a long window: the change waits");
            Assert.assertEquals(obs.deferredWrites(), 1, "one deferred write scheduled");
            ByteArrayOutputStream err = new ByteArrayOutputStream();
            PrintStream old = System.err;
            System.setErr(new PrintStream(err, true));
            try {
                k.game.fireEvent(new forge.game.event.GameEventGameOutcome(1, java.util.List.of(), k.opp.getName(), ""));
            } finally {
                System.setErr(old);
            }
            Assert.assertEquals(obs.writes(), before + 1, "game over writes at once");
            String body = Files.readString(snap);
            Assert.assertTrue(body.contains("\"kind\":\"gameover\""), body);
            Assert.assertTrue(body.contains("\"life\":21"), "the waiting change lands in the final write: " + body);
            Assert.assertTrue(body.contains("\"seq\":1,\"events\":[{\"seq\":1,\"kind\":\"gameover\""),
                    "top-level seq is the last ring entry's: " + body);
            String line = err.toString();
            Assert.assertTrue(line.contains("[arena] observer: game over"), line);
            Assert.assertTrue(line.contains("gameover 1"), line);
            Assert.assertTrue(line.contains("deferred 1"), line);
            Assert.assertTrue(line.contains("rebuilt 0"), "a single-threaded game never tears a build: " + line);
            Assert.assertTrue(line.contains("window 60000 ms"), line);
        }
    }

    /** 2026-09-07 (Ben: "shouldn't the imprint on Isochron Scepter be public
     *  knowledge?"): the snapshot carries every public zone and what each
     *  permanent holds; a face-down exiled card stays nameless. */
    @Test(timeOut = 120_000)
    public void publicZonesAndImprintsAreInTheSnapshot() throws Exception {
        try (MailboxTestKit k = kit(100)) {
            Path snap = k.base.resolve("observer-state.json");
            forge.game.card.Card scepter = MailboxTestKit.put("Isochron Scepter", k.opp, forge.game.zone.ZoneType.Battlefield);
            forge.game.card.Card pact = MailboxTestKit.put("Pact of Negation", k.opp, forge.game.zone.ZoneType.Exile);
            scepter.addImprintedCard(pact);
            MailboxTestKit.put("Beast Within", k.seat, forge.game.zone.ZoneType.Graveyard);
            forge.game.card.Card hidden = MailboxTestKit.put("Craterhoof Behemoth", k.seat, forge.game.zone.ZoneType.Exile);
            hidden.turnFaceDown();
            k.seat.setLife(35, null);   // a fingerprint change, so the snapshot rewrites
            String body = awaitBody(snap, "\"life\":35", 3_000);
            Assert.assertTrue(body.contains("\"imprinted\":[\"Pact of Negation\"]"), body);
            Assert.assertTrue(body.contains("\"graveyard\":[\"Beast Within\"]"), body);
            Assert.assertTrue(body.contains("\"exile\":[\"Pact of Negation\"]"), body);
            Assert.assertTrue(body.contains("\"commandZone\":["), body);
            Assert.assertTrue(body.contains("(face-down card)"), "face-down exile is a count, not a name: " + body);
            Assert.assertFalse(body.contains("Craterhoof Behemoth"), "a face-down card is never named: " + body);
            Assert.assertTrue(body.contains("\"stackDetail\":[]"), body);
        }
    }

    /** 2026-09-10 (seat barks): the snapshot carries a ring of public notable
     *  events — an attack with its total power and defenders, combat damage
     *  coalesced per step, and a spell countered (removed without resolving) —
     *  and a spell that resolved and then left the stack is NOT a counter. */
    @Test(timeOut = 120_000)
    public void attackDamageAndCounterEventsAreRecordedInTheRing() throws Exception {
        try (MailboxTestKit k = kit(100)) {
            Path snap = k.base.resolve("observer-state.json");
            forge.game.card.Card bear = MailboxTestKit.put("Grizzly Bears", k.opp, forge.game.zone.ZoneType.Battlefield);
            forge.game.card.Card hoof = MailboxTestKit.put("Craterhoof Behemoth", k.opp, forge.game.zone.ZoneType.Battlefield);
            com.google.common.collect.Multimap<forge.game.GameEntity, forge.game.card.Card> map =
                    com.google.common.collect.HashMultimap.create();
            map.put(k.seat, bear);
            map.put(k.seat, hoof);
            k.game.fireEvent(new forge.game.event.GameEventAttackersDeclared(k.opp, map));
            String body = awaitBody(snap, "\"kind\":\"attack\"", 3_000);
            Assert.assertTrue(body.contains("\"kind\":\"attack\""), body);
            Assert.assertTrue(body.contains("\"attackers\":2"), body);
            Assert.assertTrue(body.contains("\"power\":7"), "2/2 + 5/5: " + body);
            Assert.assertTrue(body.contains("\"defenders\":[" + k.seat.getId() + "]"), body);
            // two attackers connect in one damage step: one coalesced event of 7
            k.game.fireEvent(new forge.game.event.GameEventPlayerDamaged(
                    forge.game.player.PlayerView.get(k.seat), forge.game.card.CardView.get(bear), 2, true, false));
            k.game.fireEvent(new forge.game.event.GameEventPlayerDamaged(
                    forge.game.player.PlayerView.get(k.seat), forge.game.card.CardView.get(hoof), 5, true, false));
            body = awaitBody(snap, "\"amount\":7", 3_000);
            Assert.assertTrue(body.contains("\"kind\":\"damage\",\"turn\""), body);
            Assert.assertTrue(body.contains("\"amount\":7"), "coalesced: " + body);
            Assert.assertFalse(body.contains("\"amount\":2"), "not two events: " + body);
            Assert.assertTrue(body.contains("\"from\":[" + k.opp.getId() + "]"), body);
            // a spell leaving the stack WITHOUT having resolved = countered
            forge.game.card.Card bw = MailboxTestKit.put("Beast Within", k.seat, forge.game.zone.ZoneType.Hand);
            forge.game.spellability.SpellAbility sa = bw.getFirstSpellAbility();
            k.game.fireEvent(new forge.game.event.GameEventSpellRemovedFromStack(
                    forge.game.spellability.SpellAbilityView.get(sa)));
            body = awaitBody(snap, "\"kind\":\"countered\"", 3_000);
            Assert.assertTrue(body.contains("\"kind\":\"countered\""), body);
            Assert.assertTrue(body.contains("\"spell\":\"Beast Within\""), body);
            Assert.assertTrue(body.contains("\"seat\":" + k.seat.getId() + ",\"by\":"), body);
            // resolved, then removed: merely leaving — no second counter
            forge.game.card.Card bw2 = MailboxTestKit.put("Beast Within", k.opp, forge.game.zone.ZoneType.Hand);
            forge.game.spellability.SpellAbility sa2 = bw2.getFirstSpellAbility();
            k.game.fireEvent(new forge.game.event.GameEventSpellResolved(sa2, false));
            k.game.fireEvent(new forge.game.event.GameEventSpellRemovedFromStack(
                    forge.game.spellability.SpellAbilityView.get(sa2)));
            Thread.sleep(250);   // past the window: anything deferred has landed
            body = Files.readString(snap);
            Assert.assertEquals(body.split("\"kind\":\"countered\"", -1).length - 1, 1, "still exactly one counter: " + body);
        }
    }

    /** Later the same evening: casts (commander flag, mana value), permanents leaving
     *  the battlefield coalesced per resolution, the winner at game over, and each
     *  seat's floating mana. */
    @Test(timeOut = 120_000)
    public void castLeftGameOverAndPoolAreRecorded() throws Exception {
        try (MailboxTestKit k = kit(100)) {
            Path snap = k.base.resolve("observer-state.json");
            forge.game.card.Card bw = MailboxTestKit.put("Beast Within", k.opp, forge.game.zone.ZoneType.Hand);
            forge.game.spellability.SpellAbility sa = bw.getFirstSpellAbility();
            sa.setActivatingPlayer(k.opp);   // a cast spell has a caster; the view reads it off the instance
            forge.game.spellability.SpellAbilityStackInstance si = new forge.game.spellability.SpellAbilityStackInstance(sa);
            k.game.fireEvent(new forge.game.event.GameEventSpellAbilityCast(
                    forge.game.spellability.SpellAbilityView.get(sa), forge.game.spellability.StackItemView.get(si), 0, null));
            String body = awaitBody(snap, "\"kind\":\"cast\"", 3_000);
            Assert.assertTrue(body.contains("\"kind\":\"cast\""), body);
            Assert.assertTrue(body.contains("\"seat\":" + k.opp.getId() + ",\"spell\""), body);
            Assert.assertTrue(body.contains("\"spell\":\"Beast Within\""), body);
            Assert.assertTrue(body.contains("\"commander\":false"), body);
            Assert.assertTrue(body.contains("\"cmc\":3"), "Beast Within costs three: " + body);
            // two permanents leave the battlefield in one step: one coalesced event
            forge.game.card.Card bear = MailboxTestKit.put("Grizzly Bears", k.seat, forge.game.zone.ZoneType.Battlefield);
            forge.game.card.Card hoof = MailboxTestKit.put("Craterhoof Behemoth", k.opp, forge.game.zone.ZoneType.Battlefield);
            k.game.fireEvent(new forge.game.event.GameEventZone(forge.game.zone.ZoneType.Battlefield, k.seat,
                    forge.game.event.EventValueChangeType.Removed, bear));
            k.game.fireEvent(new forge.game.event.GameEventZone(forge.game.zone.ZoneType.Battlefield, k.opp,
                    forge.game.event.EventValueChangeType.Removed, hoof));
            body = awaitBody(snap, "\"n\":2", 3_000);
            Assert.assertEquals(body.split("\"kind\":\"left\"", -1).length - 1, 1, "one coalesced 'left' event: " + body);
            Assert.assertTrue(body.contains("\"cards\":[\"Grizzly Bears\",\"Craterhoof Behemoth\"]"), body);
            Assert.assertTrue(body.contains("\"seats\":[" + k.seat.getId() + "," + k.opp.getId() + "]"), body);
            Assert.assertTrue(body.contains("\"n\":2"), body);
            // a card ADDED to the battlefield, or leaving a graveyard, is not a 'left'
            k.game.fireEvent(new forge.game.event.GameEventZone(forge.game.zone.ZoneType.Battlefield, k.seat,
                    forge.game.event.EventValueChangeType.Added, bear));
            k.game.fireEvent(new forge.game.event.GameEventZone(forge.game.zone.ZoneType.Graveyard, k.seat,
                    forge.game.event.EventValueChangeType.Removed, bear));
            Thread.sleep(250);   // past the window: anything deferred has landed
            Assert.assertEquals(Files.readString(snap).split("\"kind\":\"left\"", -1).length - 1, 1);
            // floating mana is in every seat row
            Assert.assertTrue(Files.readString(snap).contains("\"pool\":0"), body);
            // game over names the winning seat — and writes at once, window or not
            ObserverSnapshot obs = ObserverSnapshot.of(k.game);
            Thread.sleep(250);          // let any deferred write from the zone events land first (critic: a timer stall counted as +2)
            int before = obs.writes();
            k.game.fireEvent(new forge.game.event.GameEventGameOutcome(1, java.util.List.of(), k.opp.getName(), ""));
            Assert.assertEquals(obs.writes(), before + 1, "game over writes at once");
            body = Files.readString(snap);
            Assert.assertTrue(body.contains("\"kind\":\"gameover\",\"turn\""), body);
            Assert.assertTrue(body.contains("\"winner\":" + k.opp.getId()), body);
        }
    }
}
