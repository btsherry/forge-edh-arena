"""Seat barks at run time (experimental/voicework2, 2026-09-10).

The advisor tags [bark:<seat>:<id>]; its record reaches the voice runner, which
plays the seat's own static voice (voices/<lib>/<id>[-N].wav) — last in
priority, behind the dice, a per-seat cooldown and the global gap, and dropped
outright when the advisor is paused or the voice muted. Several wordings of a
line play from a shuffle bag. An AI seat's elimination is voiced once, by the
seat itself 70 % of the time, else by Joshua. "Your move" gained on|some|off.

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
        # a synthetic stock tree: Joshua with four "your move" wordings, two seat libraries
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
            for n in ("big-swing", "big-swing-2", "big-swing-3", "big-swing-4", "eliminated"):
                (d / f"{n}.wav").write_bytes(silent_wav())
        self._stock, self._voices = vr.STOCK, vr.VOICES_DIR
        vr.STOCK, vr.VOICES_DIR = stock, voices
        self._env = dict(os.environ)
        os.environ.pop("ELEVENLABS_API_KEY", None)
        for k, v in {"ARENA_VOICE_MIN_GAP": "8", "ARENA_VOICE_SFX": "off", "ARENA_VOICE_FX": "off",
                     "ARENA_BARKS": "all", "ARENA_BARKS_COOLDOWN": "30", "ARENA_VOICE_YOUR_MOVE": "on"}.items():
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
        with (self.logs / "advisor-0.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, **rec}) + "\n")

    def _observer(self, turn, active, game_over=False, elim=()):
        seats = [{"seat": i, "name": f"s{i}", "eliminated": i in elim, "life": 40} for i in range(4)]
        (self.mailbox / "observer-state.json").write_text(json.dumps(
            {"turn": turn, "activeSeat": active, "gameOver": game_over, "seats": seats}))

    def _records(self, event=None, kind=None):
        out = []
        for l in (self.logs / "voice-0.jsonl").read_text().splitlines():
            r = json.loads(l)
            if (event is None or r.get("event") == event) and (kind is None or r.get("kind") == kind):
                out.append(r)
        return out

    def _step(self, n=1, dt=9.0):
        for _ in range(n):
            self.clock.t += dt
            self.r.step()

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
        # the -creep line is a different phrase, never a wording of your-move
        self.assertNotIn("your-move-creep.wav", picks)
        # a single-wording phrase is just itself; a seat library has its own bag
        self.assertEqual(self.r.renderer.stock("player-eliminated").name, "player-eliminated.wav")
        seat_picks = {self.r.renderer.stock("big-swing", "harry").name for _ in range(4)}
        self.assertEqual(len(seat_picks), 4, seat_picks)

    # ---- the advisor's bark reaches the seat's voice
    def test_bark_record_plays_the_seats_own_library_and_records_who_spoke(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self._step()
        self.assertEqual(len(self.player.played), 1)
        self.assertTrue(self.player.played[0].startswith("big-swing"), self.player.played)
        spoke = self._records("spoke")[0]
        self.assertEqual((spoke["kind"], spoke["library"], spoke["seat"]), ("bark", "harry", 1))
        self.assertTrue(spoke["file"].startswith("big-swing"))

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

    def test_barks_sort_last_and_one_pending_bark_newest_wins(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self._advisor(kind="bark", seat=2, id="big-swing", turn=4)
        self.r.scan_advisor()
        self._observer(5, 0); self.r.seen_turn, self.r.seen_active = 4, 3
        self.r.scan_observer()                      # "your move" queued after the barks
        kinds = [q["kind"] for q in self.r.queue]
        self.assertEqual(kinds.count("bark"), 1, "newest bark replaces the pending one")
        self.assertEqual(self.r.queue[[q["kind"] for q in self.r.queue].index("bark")]["seat"], 2)
        self._step()
        self.assertTrue(self.player.played[0].startswith("your-move"), "your move outranks a bark")
        self._step(dt=8.5)                          # inside the bark's 20 s life
        self.assertTrue(self.player.played[1].startswith("big-swing"))

    def test_knob_off_some_and_seat_cooldown_are_recorded_reasons(self):
        self.r.barks_mode = "off"
        self.assertFalse(self.r.maybe_bark(1, "big-swing"))
        self.assertIn("barks off", self._records("skipped", "bark")[-1]["why"])
        self.r.barks_mode = "some"; self.r.barks_p = 0.75
        self.r.rng.random = lambda: 0.9
        self.assertFalse(self.r.maybe_bark(1, "big-swing"))
        self.assertIn("dice", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.1
        self.assertTrue(self.r.maybe_bark(1, "big-swing"))
        self._step()                                # spoken -> cooldown stamped
        self.assertFalse(self.r.maybe_bark(1, "big-swing"))
        self.assertIn("seat cooldown", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(self.r.maybe_bark(2, "big-swing"), "another seat is not on cooldown")
        self.clock.t += 31
        self.assertTrue(self.r.maybe_bark(1, "big-swing"), "cooldown over")
        self.assertFalse(self.r.maybe_bark(3, "big-swing"))
        self.assertIn("no voice library", self._records("skipped", "bark")[-1]["why"])

    def test_mute_or_advisor_pause_drops_a_queued_bark(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self.r.scan_advisor()
        self.assertEqual(len(self.r.queue), 1)
        (self.logs / "control").mkdir()
        (self.logs / "control" / "voice.json").write_text(json.dumps({"enabled": False}))
        self._step()
        self.assertEqual(self.r.queue, []); self.assertEqual(self.player.played, [])

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
        # a seat without a library (3) always gets Joshua; barks off always gets Joshua
        self.r.rng.random = lambda: 0.1
        self._observer(6, 0, elim=(1, 2, 3)); self.r.scan_observer()
        self.assertEqual([q["stock"] for q in self.r.queue if q["kind"] == "event"], ["player-eliminated"])
        self.r.queue.clear(); self.r.barks_mode = "off"; self.r.eliminated.clear()
        self._observer(7, 0, elim=(1,)); self.r.scan_observer()
        self.assertEqual([q["stock"] for q in self.r.queue if q["kind"] == "event"], ["player-eliminated"])

    # ---- your move: on | some | off
    def test_your_move_modes(self):
        self._observer(3, 1); self.r.scan_observer(); self._step()       # startup, seen turn set
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
        for k in ("ARENA_BARKS", "ARENA_VOICE_YOUR_MOVE", "ARENA_BARKS_P", "ARENA_BARKS_COOLDOWN", "ARENA_VOICE_YOUR_MOVE_P"):
            os.environ.pop(k, None)
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_mode, r.barks_p, r.barks_cooldown), ("some", 0.75, 30.0))
        self.assertEqual((r.your_move_mode, r.your_move_p), ("some", 0.6))
        os.environ["ARENA_BARKS"] = "bogus"; os.environ["ARENA_VOICE_YOUR_MOVE"] = "bogus"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_mode, r.your_move_mode), ("some", "some"))


if __name__ == "__main__":
    unittest.main()
