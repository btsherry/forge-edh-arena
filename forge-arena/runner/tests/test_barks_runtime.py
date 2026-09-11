"""Seat barks at run time (experimental/voicework2, 2026-09-10) — the table-talk
design: every turn boundary has one owner (an AI seat's recap -> that seat's
retrospective line; the human's recap -> Joshua's colour line plus at most one
seat's reaction); instant reactions come from the snapshot's public event ring
(attack / damage / countered) with no LLM; openers at a seat's turn start are
rare; a (seat, line) is never said twice in one turn; every bark rolls one
dice (ARENA_BARKS_P) behind a short per-seat guard; mute or advisor pause
drops everything. Several wordings of a line play from a shuffle bag. An AI
seat's elimination is voiced once, by the seat itself 70 % of the time.

Everything here runs against a synthetic stock tree so it never depends on the
rendered libraries. Run: python3 -m unittest discover -s tests
"""
import io
import json
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402

LINES = ("big-swing", "eliminated", "my-turn", "that-hurt", "landed-hit", "counter", "got-countered", "slow-turn", "respect")


def silent_wav(seconds: float = 0.2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\x00\x00" * int(22050 * seconds))
    return buf.getvalue()


class FakePlayer:
    def __init__(self):
        self.played = []

    def play(self, path, should_stop=None):
        self.played.append(Path(path).name)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class BarkRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.logs, self.mailbox = base / "logs", base / "mailbox"
        self.logs.mkdir(); self.mailbox.mkdir()
        # a synthetic stock tree: Joshua with four "your move" wordings, two seat libraries (seat 3 has none)
        stock = base / "stock"; voices = stock / "voices"
        (stock / "sfx").mkdir(parents=True)
        (stock / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "phrases": {
            "your-move": {"text": ["Your move.", "b", "c", "d"]}, "player-eliminated": {"text": "x"}, "startup": {"text": "s"}}, "sfx": []}))
        for n in ("your-move", "your-move-2", "your-move-3", "your-move-4", "player-eliminated", "startup", "your-move-creep"):
            (stock / f"{n}.wav").write_bytes(silent_wav())
        for lib, seat, name in (("harry", 1, "Harry - Fierce Warrior"), ("bill", 2, "Bill - Wise, Mature, Balanced")):
            d = voices / lib; d.mkdir(parents=True)
            (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": lib, "seat": seat,
                                                         "voice_name": name, "temperament": f"{lib} temper", "phrases": {}}))
            for n in LINES + ("big-swing-2", "big-swing-3", "big-swing-4"):
                (d / f"{n}.wav").write_bytes(silent_wav())
        self._stock, self._voices = vr.STOCK, vr.VOICES_DIR
        vr.STOCK, vr.VOICES_DIR = stock, voices
        self._env = dict(os.environ)
        os.environ.pop("ELEVENLABS_API_KEY", None)
        for k, v in {"ARENA_VOICE_MIN_GAP": "8", "ARENA_VOICE_SFX": "off", "ARENA_VOICE_FX": "off",
                     "ARENA_BARKS": "all", "ARENA_BARKS_COOLDOWN": "10", "ARENA_VOICE_YOUR_MOVE": "on",
                     "ARENA_BARKS_OPENER_P": "0"}.items():
            os.environ[k] = v
        self.clock = Clock()
        self.player = FakePlayer()
        self.r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)

    def tearDown(self):
        vr.STOCK, vr.VOICES_DIR = self._stock, self._voices
        os.environ.clear(); os.environ.update(self._env)
        self.tmp.cleanup()

    # ---- helpers
    def _advisor(self, **rec):
        if "with_" in rec:
            rec["with"] = rec.pop("with_")
        with (self.logs / "advisor-0.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, **rec}) + "\n")

    def _observer(self, turn, active, game_over=False, elim=(), events=()):
        seats = [{"seat": i, "name": f"s{i}", "eliminated": i in elim, "life": 40} for i in range(4)]
        (self.mailbox / "observer-state.json").write_text(json.dumps(
            {"turn": turn, "activeSeat": active, "gameOver": game_over, "seats": seats, "events": list(events)}))

    def _records(self, event=None, kind=None):
        out = []
        f = self.logs / "voice-0.jsonl"
        for l in (f.read_text().splitlines() if f.exists() else []):
            r = json.loads(l)
            if (event is None or r.get("event") == event) and (kind is None or r.get("kind") == kind):
                out.append(r)
        return out

    def _step(self, n=1, dt=9.0):
        for _ in range(n):
            self.clock.t += dt
            self.r.step()

    def _queued(self):
        return [(q["kind"], q["stock"], q.get("library") or "", q.get("seat")) for q in self.r.queue]

    # ---- libraries + shuffle bag
    def test_seat_libraries_are_read_from_the_manifests(self):
        self.assertEqual({k: v["library"] for k, v in self.r.seat_libraries.items()}, {1: "harry", 2: "bill"})
        self.assertEqual(self.r.seat_libraries[1]["voice"], "Harry")
        self.assertEqual(self.r.library_for_seat(3), "", "no library, no bark")
        self.assertEqual(vr.load_seat_libraries(Path(self.tmp.name) / "nowhere"), {})

    def test_shuffle_bag_plays_every_wording_before_repeating_and_never_twice_running(self):
        picks = [self.r.renderer.stock("your-move").name for _ in range(12)]
        for i in range(0, 12, 4):
            self.assertEqual(sorted(picks[i:i + 4]), ["your-move-2.wav", "your-move-3.wav", "your-move-4.wav", "your-move.wav"], picks)
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])), picks)
        self.assertNotIn("your-move-creep.wav", picks, "a different phrase, never a wording of your-move")
        self.assertEqual(self.r.renderer.stock("player-eliminated").name, "player-eliminated.wav")
        seat_picks = {self.r.renderer.stock("big-swing", "harry").name for _ in range(4)}
        self.assertEqual(len(seat_picks), 4, seat_picks)

    # ---- the advisor's recap: owner by turn
    def test_recap_bark_plays_the_seats_own_library_and_records_who_spoke(self):
        self._advisor(kind="bark", seat=1, id="slow-turn", turn=4, with_="color")
        self._step()
        self.assertEqual(self.player.played, ["slow-turn.wav"])
        spoke = self._records("spoke")[0]
        self.assertEqual((spoke["kind"], spoke["library"], spoke["seat"], spoke["file"]), ("bark", "harry", 1, "slow-turn.wav"))
        self.assertEqual(self._records("queued", "bark")[0]["source"], "recap")

    def test_colour_belongs_to_joshua_only_after_the_humans_turn(self):
        self.r.color_mode = "all"
        self._advisor(kind="color", seq=1, turn=5, owner=1, text="Urza had a turn.")
        self._advisor(kind="color", seq=2, turn=6, owner=0, text="You had a turn.")
        self._advisor(kind="color", seq=3, turn=7, owner=3, text="Seat 3 has no voice library.")
        self._advisor(kind="color", seq=4, turn=8, text="An old record without an owner.")
        self.r.scan_advisor()
        texts = [q["text"] for q in self.r.queue]
        self.assertNotIn("Urza had a turn.", texts, "seat 1's turn is seat 1's line, not Joshua's")
        self.assertEqual(texts, ["An old record without an owner."], "one pending colour line: newest wins")
        skipped = [r["why"] for r in self._records("skipped", "color")]
        self.assertEqual(len(skipped), 1); self.assertIn("seat 1's turn", skipped[0])
        # a seat without a voice cannot speak for itself, so Joshua does; with barks off Joshua comments on every turn
        self.r.queue.clear()
        self._advisor(kind="color", seq=5, turn=9, owner=3, text="Seat 3 again.")
        self.r.scan_advisor()
        self.assertEqual([q["text"] for q in self.r.queue], ["Seat 3 again."])
        self.r.queue.clear(); self.r.barks_mode = "off"
        self._advisor(kind="color", seq=6, turn=10, owner=2, text="Barks off.")
        self.r.scan_advisor()
        self.assertEqual([q["text"] for q in self.r.queue], ["Barks off."])

    def test_one_dice_a_short_guard_and_never_the_same_line_twice_in_a_turn(self):
        self.r.barks_mode = "some"; self.r.barks_p = 0.85
        self.r.rng.random = lambda: 0.9
        self.assertFalse(self.r.maybe_bark(1, "big-swing", turn=3, source="recap"))
        self.assertIn("dice (recap, p=0.85)", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.1
        self.assertTrue(self.r.maybe_bark(1, "big-swing", turn=3, source="event"))
        self.assertFalse(self.r.maybe_bark(1, "big-swing", turn=3, source="recap"), "the same line twice in one turn is a repeat")
        self.assertIn("already said this turn", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(self.r.maybe_bark(1, "that-hurt", turn=3, source="event"), "a different line is fine")
        self._step()                                                            # spoken -> the 10 s guard
        self.assertFalse(self.r.maybe_bark(1, "counter", turn=3, source="event"))
        self.assertIn("seat guard", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(self.r.maybe_bark(2, "counter", turn=3, source="event"), "another seat is not guarded")
        self.clock.t += 11
        self.assertTrue(self.r.maybe_bark(1, "big-swing", turn=4, source="recap"), "a new turn forgets what was said")
        self.assertFalse(self.r.maybe_bark(3, "big-swing", turn=4))
        self.assertIn("no voice library", self._records("skipped", "bark")[-1]["why"])
        self.r.barks_mode = "off"
        self.assertFalse(self.r.maybe_bark(1, "big-swing", turn=5))
        self.assertIn("barks off", self._records("skipped", "bark")[-1]["why"])

    def test_barks_sort_last_behind_your_move_and_a_pending_bark_is_replaced_by_the_newest(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4, with_="color")
        self._advisor(kind="bark", seat=2, id="counter", turn=4, with_="advice")
        self.r.scan_advisor()
        self._observer(5, 0); self.r.seen_turn, self.r.seen_active = 4, 3
        self.r.scan_observer()                      # "your move" queued after the barks
        kinds = [q["kind"] for q in self.r.queue]
        self.assertEqual(kinds.count("bark"), 1, "newest bark replaces the pending one")
        self.assertEqual([q for q in self.r.queue if q["kind"] == "bark"][0]["seat"], 2)
        self._step()
        self.assertTrue(self.player.played[0].startswith("your-move"), "your move outranks a bark")
        self._step(dt=8.5)
        self.assertEqual(self.player.played[1], "counter.wav")

    def test_bleeps_precede_joshua_only_never_a_seat_voice(self):
        (Path(vr.STOCK) / "sfx" / "typing-01.wav").write_bytes(silent_wav())
        self.r.renderer.manifest["sfx"] = ["typing-01.wav"]
        self.r.sfx_on = True
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self._step()
        self.assertEqual(len(self.player.played), 1, self.player.played)
        self.assertTrue(self.player.played[0].startswith("big-swing"), "a bark plays bare — no typing bleep")
        self._observer(5, 0); self.r.seen_turn, self.r.seen_active = 4, 3; self.r.scan_observer()
        self._step()
        self.assertEqual(self.player.played[1], "typing-01.wav", "Joshua's lines keep their bleep")
        self.assertTrue(self.player.played[2].startswith("your-move"))

    def test_mute_or_advisor_pause_drops_a_queued_bark(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self.r.scan_advisor()
        self.assertEqual(len(self.r.queue), 1)
        (self.logs / "control").mkdir()
        (self.logs / "control" / "voice.json").write_text(json.dumps({"enabled": False}))
        self._step()
        self.assertEqual(self.r.queue, []); self.assertEqual(self.player.played, [])

    # ---- instant reactions from the snapshot's event ring
    def _prime(self):
        """First snapshot read: the runner learns the current event seq and never replays history."""
        self._observer(3, 1, events=[{"seq": 1, "kind": "attack", "turn": 2, "seat": 1, "attackers": 5, "power": 30, "defenders": [0]}])
        self.r.scan_observer(); self.r.queue.clear()
        self.assertEqual(self.r._event_seq, 1)
        self.assertEqual(self._records("queued", "bark"), [], "history is not replayed on a (re)start")

    def test_attack_event_fires_big_swing_above_the_thresholds(self):
        self._prime()
        ev = [{"seq": 2, "kind": "attack", "turn": 3, "seat": 1, "attackers": 1, "power": 3, "defenders": [0]},
              {"seq": 3, "kind": "attack", "turn": 3, "seat": 2, "attackers": 1, "power": 6, "defenders": [0]}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "big-swing", "bill", 2)], "3 power is a poke; 6 power is a swing")
        self.r.queue.clear()
        ev.append({"seq": 4, "kind": "attack", "turn": 3, "seat": 1, "attackers": 3, "power": 3, "defenders": [2]})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "big-swing", "harry", 1)], "three attackers count too")
        self.r.queue.clear()
        ev.append({"seq": 5, "kind": "attack", "turn": 4, "seat": 0, "attackers": 4, "power": 20, "defenders": [1]})
        self._observer(4, 0, events=ev); self.r.scan_observer()
        self.assertEqual([q for q in self._queued() if q[0] == "bark"], [], "the human's attack is not a bark")

    def test_damage_event_the_victim_speaks_or_the_hitter_when_the_victim_is_the_human(self):
        self._prime()
        ev = [{"seq": 2, "kind": "damage", "turn": 3, "seat": 2, "amount": 7, "combat": True, "from": [1]},
              {"seq": 3, "kind": "damage", "turn": 3, "seat": 2, "amount": 8, "combat": True, "from": [1]}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "that-hurt", "bill", 2)], "7 is not a big hit; 8 is, and the victim speaks")
        self.r.queue.clear()
        ev.append({"seq": 4, "kind": "damage", "turn": 3, "seat": 0, "amount": 12, "combat": True, "from": [1]})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "landed-hit", "harry", 1)], "the human took it: the hitter gloats")
        self.r.queue.clear()
        ev.append({"seq": 5, "kind": "damage", "turn": 3, "seat": 0, "amount": 12, "combat": False, "from": [3]})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "seat 3 has no voice; nobody speaks")

    def test_countered_event_the_counterer_speaks_else_the_victim(self):
        self._prime()
        ev = [{"seq": 2, "kind": "countered", "turn": 3, "seat": 0, "by": 2, "spell": "Beast Within"}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "counter", "bill", 2)])
        self.r.queue.clear()
        ev.append({"seq": 3, "kind": "countered", "turn": 3, "seat": 1, "by": 0, "spell": "Thopter Foundry"})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "got-countered", "harry", 1)], "the human countered: the victim grumbles")
        self.r.queue.clear()
        ev.append({"seq": 4, "kind": "countered", "turn": 3, "seat": 2, "by": None, "spell": "Sol Ring"})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "got-countered", "bill", 2)], "unknown counterer: still the victim")
        self.r.queue.clear()
        ev.append({"seq": 5, "kind": "countered", "turn": 3, "seat": 1, "by": 0, "spell": "Sol Ring"})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "seat 1 already grumbled this turn — no repeat")

    def test_opener_fires_at_a_seats_turn_start_at_its_own_probability(self):
        self.r.barks_opener_p = 0.35
        self._observer(3, 0); self.r.scan_observer(); self._step()          # startup, seen turn set
        self.r.rng.random = lambda: 0.9
        self._observer(4, 1); self.r.scan_observer()
        self.assertEqual(self._queued(), [])
        self.assertIn("dice (opener, p=0.35)", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.1
        self._observer(5, 2); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "my-turn", "bill", 2)])
        self.r.queue.clear(); self.r.barks_opener_p = 0
        self._observer(6, 1); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "opener_p 0 = never")

    # ---- elimination: the seat itself or Joshua, one line, at once
    def test_ai_elimination_is_voiced_once_by_the_seat_or_by_joshua(self):
        self._observer(3, 1); self.r.scan_observer()          # startup line
        self._step()
        self.r.rng.random = lambda: 0.1                        # < ELIM_SEAT_P -> the seat speaks
        self._observer(4, 2, elim=(1,)); self.r.scan_observer()
        self.assertEqual([(q["kind"], q["stock"], q["library"]) for q in self.r.queue], [("event", "eliminated", "harry")])
        self._step()
        self.assertEqual(self.player.played[-1], "eliminated.wav")
        self.r.rng.random = lambda: 0.9                        # >= ELIM_SEAT_P -> Joshua
        self._observer(5, 3, elim=(1, 2)); self.r.scan_observer()
        self.assertEqual([(q["kind"], q["stock"], q["library"]) for q in self.r.queue], [("event", "player-eliminated", "")])
        self.r.rng.random = lambda: 0.1
        self._observer(6, 0, elim=(1, 2, 3)); self.r.scan_observer()
        self.assertEqual([q["stock"] for q in self.r.queue if q["kind"] == "event"], ["player-eliminated"], "seat 3 has no voice")
        self.r.queue.clear(); self.r.barks_mode = "off"; self.r.eliminated.clear()
        self._observer(7, 0, elim=(1,)); self.r.scan_observer()
        self.assertEqual([q["stock"] for q in self.r.queue if q["kind"] == "event"], ["player-eliminated"])

    # ---- your move: on | some | off
    def test_your_move_modes(self):
        self._observer(3, 1); self.r.scan_observer(); self._step()
        self.r.your_move_mode = "some"; self.r.your_move_p = 0.6
        self.r.rng.random = lambda: 0.9
        self._observer(4, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue, [])
        self.assertIn("dice", self._records("skipped", "your_move")[-1]["why"])
        self.r.rng.random = lambda: 0.1
        self._observer(8, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue[-1]["kind"], "your_move")
        self.r.queue.clear(); self.r.your_move_mode = "off"
        self._observer(12, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue, [])
        self.r.your_move_mode = "on"; self.r.rng.random = lambda: 0.99
        self._observer(16, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue[-1]["kind"], "your_move")

    def test_defaults_from_the_environment(self):
        for k in ("ARENA_BARKS", "ARENA_VOICE_YOUR_MOVE", "ARENA_BARKS_P", "ARENA_BARKS_COOLDOWN", "ARENA_VOICE_YOUR_MOVE_P",
                  "ARENA_BARKS_OPENER_P", "ARENA_BARKS_SWING", "ARENA_BARKS_HIT"):
            os.environ.pop(k, None)
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_mode, r.barks_p, r.barks_cooldown, r.barks_opener_p, r.barks_swing, r.barks_hit),
                         ("some", 0.85, 10.0, 0.35, 6, 8))
        self.assertEqual((r.your_move_mode, r.your_move_p), ("some", 0.6))
        os.environ["ARENA_BARKS"] = "bogus"; os.environ["ARENA_VOICE_YOUR_MOVE"] = "bogus"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_mode, r.your_move_mode), ("some", "some"))


if __name__ == "__main__":
    unittest.main()
