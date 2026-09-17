"""Restart memory, record stamps, the muted teardown and the replay (voicework2 hardening
plan 2026-09-14, lane E2: §1A A1/A2, §1B B1, §1C C1, §4.1, §4.3 — Ben: "a hot-swapped runner
is normal and must not forget").

  C1   every record carries turn / phase / active / clock; a spoken line carries the ring seq and its channel
  A1   logs/voice-state.json: a seat dies, a combo is announced, lines are spoken; a SECOND runner on the
       same logs directory with a DIFFERENT fake-clock base adopts it at its first snapshot — the dead seat
       stays silent, the combo is not re-announced, the line said two minutes ago is no candidate, the
       turn's no-repeat set holds, every clock is rebased; a checkpoint from another game is ignored;
       without a checkpoint the dead and the recency come back from voice-0.jsonl
  A2   nothing is forced at once: the floor re-arms from the restart, a fresh start waits the normal gap
  B1   a muted runner still sees the game end: final.json at once, nothing played
  4.3  --replay drives the runner from a tape with a fake clock and a dry player, the same under one seed

Everything runs against the synthetic stock tree of test_barks_runtime. Run:
python3 -m unittest discover -s tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402
from test_barks_runtime import _TreeCase, Clock, FakePlayer  # noqa: E402

COMBO = (frozenset({"Alpha", "Beta"}), "alpha-beta")


def _combos(seat):
    return [COMBO] if int(seat) == 1 else []


class _RestartCase(_TreeCase):
    """The tree case plus a snapshot writer with battlefields and a game id."""

    def _snap(self, turn, active, elim=(), game_over=False, bf1=(), game_id="g1", events=()):
        seats = []
        for i in range(4):
            bf = [{"name": n, "types": "Artifact", "tapped": False} for n in (bf1 if i == 1 else ())]
            seats.append({"seat": i, "name": f"s{i}", "eliminated": i in elim, "life": 40, "handSize": 3, "battlefield": bf})
        d = {"turn": turn, "phase": "MAIN1", "activeSeat": active, "gameOver": game_over, "seats": seats, "events": list(events)}
        if game_id is not None:
            d["gameId"] = game_id
        (self.mailbox / "observer-state.json").write_text(json.dumps(d))

    def _bark_item(self, seat, pid, source="event", ctx=None):
        return {"kind": "bark", "text": "", "stock": pid, "seq": None, "seat": seat, "library": self.r.lib_for(seat, pid),
                "ctx": ctx or {}, "chain": None, "source": source}

    def _state(self):
        return json.loads((self.logs / vr.STATE_FILE).read_text())

    def _second_runner(self, base=50000.0):
        """A (re)started runner on the same logs directory, its monotonic clock on another base."""
        clock2, player2 = Clock(), FakePlayer()
        clock2.t = base
        return vr.VoiceRunner(self.logs, self.mailbox, player=player2, clock=clock2, tuning=self.tuning), clock2, player2

    def _half_game(self):
        """The first runner plays half a game: seat 2 dies (its own exit line), seat 1 says "big swing" and a
        filler, seat 1's combo lands and is announced, (1, respect) is in the turn's set; then two minutes pass."""
        r = self.r
        r.rng.random = lambda: 0.0                                     # dice pass; the dying seat says its own line
        r.combos_of = _combos
        self._snap(3, 1); self._step()                                  # 1009: first snapshot (fresh start, no checkpoint yet)
        self.assertTrue(r.speak(self._bark_item(1, "big-swing")))       # said at 1009
        self._snap(4, 2, elim=(2,), bf1=("Alpha", "Beta")); self._step()   # 1018: seat 2 falls, the combo lands
        self.assertEqual(r.eliminated, {2})
        self.assertIn("eliminated.wav", self.player.played, "seat 2's own exit line")
        self.assertIn("engine-online", [q["stock"] for q in self._records("queued", "bark")], "the combo announced once")
        self.assertEqual(r._combos_done, {1: {COMBO[0]}})
        r.queue.clear()
        self.clock.t += 9
        self.assertTrue(r.speak(self._bark_item(1, "nothing-happening", source="patter")))   # said at 1027
        r._said_this_turn.add((1, "respect"))
        self.clock.t += 120                                              # two quiet minutes
        r.step()                                                         # the checkpoint follows the durable change
        return r


class RecordStamps(_RestartCase):
    def test_every_record_carries_the_board_and_the_clock(self):
        self.r.record("noted", kind="x", why="before any snapshot")
        early = self._records("noted")[-1]
        self.assertEqual((early["turn"], early["phase"], early["active"], early["clock"]), (None, None, None, 1000.0))
        self._snap(3, 1); self.r.scan_observer()
        self.clock.t = 1004.5
        self.r.record("noted", kind="x", why="after")
        rec = self._records("noted")[-1]
        self.assertEqual((rec["turn"], rec["phase"], rec["active"], rec["clock"]), (3, "MAIN1", 1, 1004.5))
        self.r.record("noted", kind="x", why="own turn", turn=7)
        self.assertEqual(self._records("noted")[-1]["turn"], 7, "a caller's own value stands")
        for q in self._records("queued"):
            self.assertIn("turn", q, "the scheduler's queued records carry the stamp too")

    def test_a_spoken_line_carries_the_ring_seq_and_the_channel(self):
        self._snap(3, 1); self.r.scan_observer()
        self.clock.t += 9
        self.assertTrue(self.r.speak(self._bark_item(1, "big-swing", ctx={"seq": 42, "targets": [2]})))
        spoke = self._records("spoke")[-1]
        self.assertEqual((spoke["seq"], spoke["channel"], spoke["turn"], spoke["active"]), (42, "main", 3, 1))
        self.assertEqual(spoke["stock"], "big-swing")
        self.assertTrue(self.r.speak(self._bark_item(1, "that-hurt")))
        spoke = self._records("spoke")[-1]
        self.assertNotIn("seq", spoke, "no ring event behind it: no seq")
        self.assertEqual(spoke["channel"], "main")


class Checkpoint(_RestartCase):
    def test_the_checkpoint_is_valid_json_written_atomically(self):
        self._snap(3, 1); self._step()
        st = self._state()
        self.assertEqual(st["schema"], vr.STATE_SCHEMA)
        self.assertEqual(st["gameId"], "g1")
        for key in ("saved_at", "clock", "eliminated", "combos_done", "said_at", "seat_said_at", "last_spoken_at", "tails", "seen_turn"):
            self.assertIn(key, st)
        self.assertFalse((self.logs / "voice-state.json.tmp").exists(), "tmp + os.replace: no temp file left behind")
        self.assertTrue(self.r.save_state(force=True))
        self.assertFalse((self.logs / "voice-state.json.tmp").exists())
        json.loads((self.logs / vr.STATE_FILE).read_text())

    def test_a_durable_change_saves_at_once_and_recency_waits(self):
        self._snap(3, 1); self._step()
        before = self._state()["saved_at"]
        self.clock.t += 1; self.r.step()                                 # nothing durable moved, 1 s: no save
        self.assertEqual(self._state()["saved_at"], before)
        self.r._sweeps += 1; self.clock.t += 1; self.r.step()            # a durable field: saved now
        self.assertEqual(self._state()["sweeps"], 1)
        self.clock.t += vr.STATE_SAVE_S; self.r.step()                   # five seconds: the recency maps
        self.assertEqual(self._state()["clock"], self.clock.t)

    def test_a_second_runner_adopts_the_checkpoint_and_forgets_nothing(self):
        r1 = self._half_game()
        st = self._state()
        self.assertEqual(st["eliminated"], [2]); self.assertEqual(st["combos_done"], {"1": [["Alpha", "Beta"]]})
        self.assertIn([1, "respect"], st["said_this_turn"])
        r2, clock2, player2 = self._second_runner(base=50000.0)          # a new process: a new monotonic base
        r2.combos_of = _combos
        r2.patter_on, r2.patter_gap = True, (5.0, 5.0)
        r2.rng.uniform = lambda a, b: a
        self.assertIsNotNone(r2._pending_state, "held until the first snapshot names the game")
        self._snap(4, 2, elim=(2,), bf1=("Alpha", "Beta"))
        r2.scan_observer()
        self.assertIsNone(r2._pending_state)
        noted = [n["why"] for n in self._records("noted") if n.get("kind") == "state"]
        self.assertTrue(any(w.startswith("checkpoint adopted: 1 dead, 1 combos") for w in noted), noted)
        # the dead seat stays silent
        self.assertEqual(r2.eliminated, {2})
        self.assertFalse(r2.maybe_bark(2, "counter", turn=4, source="event", p=1.0))
        self.assertEqual(self._records("skipped", "bark")[-1]["why"], "eliminated")
        # the combo is not re-announced
        self.assertEqual(r2._combos_done, {1: {COMBO[0]}})
        self.assertNotIn("engine-online", [q["stock"] for q in r2.queue])
        # the turn's no-repeat set holds
        self.assertEqual(r2._said_turn, 4)
        self.assertFalse(r2.maybe_bark(1, "respect", turn=4, source="event", p=1.0))
        self.assertEqual(self._records("skipped", "bark")[-1]["why"], "already said this turn")
        # the line said two minutes ago is no candidate; one never said is
        living = [1]
        cands = {pid for _, pid, _, _ in r2.patter_candidates(r2._last_snapshot, living)}
        self.assertNotIn("nothing-happening", cands); self.assertIn("this-is-fine", cands)
        # every clock is rebased: "how long ago" is the same on both bases
        for pid in ("big-swing", "nothing-happening"):
            self.assertAlmostEqual(clock2.t - r2._said_at[pid], self.clock.t - r1._said_at[pid], delta=1.0, msg=pid)
        self.assertAlmostEqual(clock2.t - r2._bark_spoken_at[1], self.clock.t - r1._bark_spoken_at[1], delta=1.0)
        self.assertAlmostEqual(clock2.t - r2._seat_said_at[(1, "big-swing")], self.clock.t - r1._seat_said_at[(1, "big-swing")], delta=1.0)
        self.assertEqual(r2.seen_turn, 4); self.assertTrue(r2.started_said)
        # A2: the last line was two minutes ago — the floor must not read that as a long silence and fire now
        self.assertEqual(r2.last_spoken_at, clock2.t - r2.min_gap)
        self.assertEqual(r2._floor_rearmed_at, clock2.t)
        self.assertGreaterEqual(r2._patter_due, clock2.t + 5.0)
        for _ in range(4):
            clock2.t += 1.0; r2.step()
        self.assertEqual(player2.played, [], "nothing plays in the first seconds after a restart")
        self.assertFalse(any("silence floor" in (x.get("why") or "") for x in self._records("skipped", "bark") if x["clock"] >= 50000),
                         "the floor did not fire at the restart")

    def test_a_checkpoint_from_another_game_is_ignored(self):
        r1 = self.r
        self._snap(3, 1); self._step()
        r1._combos_done[1] = {COMBO[0]}; r1._sweeps = 2
        self.clock.t += 1; r1.step()
        self.assertEqual(self._state()["gameId"], "g1")
        r2, clock2, _ = self._second_runner()
        self._snap(3, 1, game_id="g2")
        r2.scan_observer()
        self.assertEqual((r2._combos_done, r2._sweeps, r2.eliminated), ({}, 0, set()))
        self.assertTrue(any(n["why"].startswith("checkpoint from another game ignored") for n in self._records("noted") if n.get("kind") == "state"))
        self.clock.t += 1
        self.assertEqual(r2.save_state(force=True), True)
        self.assertEqual(self._state()["gameId"], "g2", "the new game's checkpoint replaces it")

    def test_without_a_checkpoint_the_log_rebuilds_the_dead_and_the_recency(self):
        with (self.logs / "voice-0.jsonl").open("a") as f:                # an opener from long ago: never replayed
            f.write(json.dumps({"ts": 1.0, "event": "spoke", "kind": "startup", "stock": "startup"}) + "\n")
        r1 = self.r
        r1.rng.random = lambda: 0.0
        self._snap(3, 1); self._step()
        self._snap(4, 2, elim=(2,)); self._step()
        self.assertIn("eliminated.wav", self.player.played)
        self.assertTrue(r1.speak(self._bark_item(1, "big-swing")))
        (self.logs / vr.STATE_FILE).unlink()                                # a crash before the first save
        r2, clock2, _ = self._second_runner()
        self.assertIsNone(r2._pending_state)
        self.assertTrue(r2.started_said, "_startup_already_spoken, generalised")
        self.assertEqual(r2.eliminated, set(), "the dead wait for the first snapshot (a game past turn 1)")
        self._snap(4, 2, elim=(2,)); r2.scan_observer()
        self.assertEqual(r2.eliminated, {2})
        self.assertTrue(any(n["why"].startswith("no checkpoint: 1 dead seat(s) rebuilt") for n in self._records("noted") if n.get("kind") == "state"))
        self.assertIn("big-swing", r2._said_at)
        self.assertLess(clock2.t - r2._said_at["big-swing"], 5.0, "rebased by wall age onto the new clock")
        self.assertIn((1, "big-swing"), r2._seat_said_at)
        self.assertLessEqual(clock2.t - r2.last_spoken_at, r2.min_gap)

    def test_a_fresh_start_waits_the_normal_gap(self):
        self.assertEqual(self.r.last_spoken_at, 1000.0, "never -1e9")
        self._snap(3, 1); self.r.scan_observer()
        self.assertTrue(self.r.maybe_bark(1, "big-swing", turn=3, source="event", p=1.0))
        self.assertIsNone(self.r.next_item(), "the gap since 'a line just played' is not up")
        self.r.patter_on = True
        self.clock.t += 2; self.r.patter()
        self.assertFalse(any("silence floor" in (x.get("why") or "") for x in self._records("skipped", "bark")), "no astronomical silence")
        self.clock.t = 1008.0
        self.assertIsNotNone(self.r.next_item())


class MutedTeardown(_RestartCase):
    def test_a_muted_game_over_publishes_final_and_plays_nothing(self):
        (self.logs / "control").mkdir(parents=True, exist_ok=True)
        (self.logs / "control" / "voice.json").write_text(json.dumps({"enabled": False}))
        self.assertFalse(self.r.enabled())
        self._snap(3, 1); self._step()
        self.assertEqual(self.r.seen_turn, 3, "muted, the runner still reads the snapshot")
        self._snap(9, 1, elim=(0, 2, 3), game_over=True); self._step()
        self.assertTrue(self.r.final_locked)
        self.assertTrue((self.mailbox / "seat-0-voice" / "final.json").exists(), "the watcher is told at once")
        self.assertEqual(self.player.played, [], "nothing plays while disabled")
        self.assertEqual(self.r.queue, [])
        dropped = [d for d in self._records("dropped") if d["why"] == "voice disabled"]
        self.assertTrue(any(d["kind"] == "game_over" for d in dropped), "the final sequence was dropped with a record, not played")
        self.assertEqual(self._state()["final_locked"], True)


class Replay(_TreeCase):
    def _archive(self):
        base = Path(tempfile.mkdtemp(prefix="tape-", dir=self.tmp.name))
        t0, c0 = 1.7e9, 100.0

        def seat(i, life=40, hand=3, bf=()):
            return {"seat": i, "life": life, "handSize": hand, "pool": 0, "eliminated": False,
                    "battlefield": [{"name": n, "power": 3, "toughness": 3} for n in bf]}
        snaps = [
            (0, 3, 1, None, [seat(i) for i in range(4)]),
            (10, 3, 1, 1, [seat(0), seat(1, bf=("Bear",)), seat(2), seat(3)]),
            (25, 3, 1, 2, [seat(0), seat(1, bf=("Bear", "Ox")), seat(2, life=33), seat(3)]),
            (40, 4, 2, 2, [seat(0), seat(1, bf=("Bear", "Ox")), seat(2, life=33, hand=8), seat(3)]),
            (60, 4, 2, 3, [seat(0), seat(1, bf=("Bear", "Ox")), seat(2, life=33, hand=7), seat(3, life=8)]),
            (90, 5, 0, 3, [seat(0, hand=1), seat(1, bf=("Bear", "Ox")), seat(2, life=33, hand=7), seat(3, life=8)]),
        ]
        with (base / vr.OBSERVER_TAPE).open("w") as f:
            for dt, turn, active, seq, seats in snaps:
                f.write(json.dumps({"ts": t0 + dt, "clock": c0 + dt, "gameId": "g9", "turn": turn, "phase": "MAIN1", "activeSeat": active,
                                    "gameOver": False, "stack": [], "seq": seq, "seats": seats}) + "\n")
        with (base / vr.EVENTS_TAPE).open("w") as f:
            f.write(json.dumps({"seq": 1, "kind": "cast", "turn": 3, "seat": 1, "spell": "Bear", "cmc": 2, "ts": t0 + 10, "clock": c0 + 10}) + "\n")
            f.write(json.dumps({"seq": 2, "kind": "attack", "turn": 3, "seat": 1, "power": 7, "attackers": 2, "defenders": [2], "ts": t0 + 25, "clock": c0 + 25}) + "\n")
            f.write(json.dumps({"seq": 3, "kind": "damage", "turn": 4, "seat": 3, "amount": 9, "combat": True, "from": [2], "ts": t0 + 60, "clock": c0 + 60}) + "\n")
        (base / "game.jsonl").write_text(json.dumps({"ts": t0 + 5, "seat": 1, "gameId": "g9", "type": "MULLIGAN", "turn": 0, "answer": {"keep": True}, "why": "fine"}) + "\n")
        (base / "advisor-0.jsonl").write_text(json.dumps({"ts": t0 + 42, "kind": "bark", "seat": 2, "id": "respect", "turn": 4}) + "\n")
        return base

    def test_a_replay_is_deterministic_under_a_seed_and_touches_no_live_log(self):
        # the replay's runner takes tuning.json as shipped (patter on); the tree case's override is not passed to it
        archive = self._archive()
        quiet = lambda s: None  # noqa: E731
        a = vr.replay(archive, seed=3, out=quiet)
        b = vr.replay(archive, seed=3, out=quiet)
        self.assertEqual(a, b, "two runs under one seed are identical")
        spoken = [l for l in a if l.startswith("[t+")]
        self.assertTrue(spoken, a)
        self.assertTrue(any("<big-swing>" in l and "seat 1" in l and "(event)" in l for l in spoken), spoken)
        for line in spoken:
            self.assertRegex(line, r"^\[t\+\d\d:\d\d turn \d+\] seat \S+ <[^>]+> \([a-z_]+\)$")
        self.assertTrue(any("lines/min" in l for l in a))
        self.assertTrue(any("gap median" in l for l in a) or len(spoken) < 2)
        self.assertFalse((self.logs / "voice-0.jsonl").exists(), "the replay logs into its own temp directory")
        self.assertFalse((self.logs / vr.STATE_FILE).exists())


if __name__ == "__main__":
    unittest.main()
