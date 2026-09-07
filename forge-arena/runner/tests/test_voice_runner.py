"""The advisor's voice (2026-09-07): voice_runner speaks stock phrases and
first-sentence advice, one utterance at a time, rate-limited, never for a
window the human already answered, live only with a key, cached forever.
Run: python3 -m unittest discover -s tests"""
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
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(b"\x00\x00" * int(44100 * seconds))
    return buf.getvalue()


class FakePlayer:
    def __init__(self):
        self.played = []

    def play(self, path):
        self.played.append(Path(path).name)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class VoiceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.logs, self.mailbox = base / "logs", base / "mailbox"
        self.logs.mkdir(); self.mailbox.mkdir()
        self._env = dict(os.environ)
        os.environ.pop("ELEVENLABS_API_KEY", None)
        os.environ["ARENA_VOICE_MIN_GAP"] = "8"
        os.environ["ARENA_VOICE_SFX"] = "off"
        os.environ["ARENA_VOICE_FX"] = "off"
        self.clock = Clock()
        self.calls = []

        def fake_tts(text):
            self.calls.append(text)
            return silent_wav()
        self.player = FakePlayer()
        self.r = vr.VoiceRunner(self.logs, self.mailbox, fake_tts=fake_tts, player=self.player, clock=self.clock)

    def tearDown(self):
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

    # ---- pure helpers
    def test_first_sentence_is_clean_and_bounded(self):
        self.assertEqual(vr.first_sentence("**Hold** the Boots. Cast Selvala next turn."), "Hold the Boots.")
        self.assertEqual(vr.first_sentence("[t12 · you] why? Because Urza has [quip:ouch] a counter ready!"),
                         "why?")
        long = "This is a very long single sentence " * 12
        s = vr.first_sentence(long)
        self.assertLessEqual(len(s), vr.FIRST_SENTENCE_MAX + 1)
        self.assertTrue(s.endswith("."))
        self.assertEqual(vr.first_sentence(""), "")

    def test_cache_key_covers_voice_model_fx(self):
        k = vr.cache_key("hi", "v1", "m1", "fx")
        self.assertNotEqual(k, vr.cache_key("hi", "v2", "m1", "fx"))
        self.assertNotEqual(k, vr.cache_key("hi", "v1", "m2", "fx"))
        self.assertNotEqual(k, vr.cache_key("hi", "v1", "m1", ""))
        self.assertEqual(k, vr.cache_key("hi", "v1", "m1", "fx"))

    # ---- rendering
    def test_live_line_renders_once_then_hits_the_cache(self):
        p1 = self.r.renderer.render("Your Selvala can tap for six.")
        p2 = self.r.renderer.render("Your Selvala can tap for six.")
        self.assertIsNotNone(p1)
        self.assertEqual(p1, p2)
        self.assertEqual(len(self.calls), 1, "a repeated line never costs again")
        self.assertGreater(self.r.renderer.chars_used, 0)

    def test_without_key_or_fake_the_daemon_is_stock_only(self):
        r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.assertFalse(r.renderer.live)
        self.assertIsNone(r.renderer.render("anything"))
        self.assertIsNotNone(r.renderer.stock("startup"), "stock phrases ship with the tree")

    def test_char_cap_turns_live_off(self):
        self.r.renderer.max_chars = 10
        self.assertIsNotNone(self.r.renderer.render("twelve chars!"))
        self.assertFalse(self.r.renderer.live)
        self.assertIsNone(self.r.renderer.render("another line"))

    # ---- queue discipline
    def test_rate_limit_one_utterance_per_gap_except_start_and_end(self):
        self._observer(1, 1)
        self.r.step()                                  # startup line, no gap applies
        self.assertEqual(self.player.played, ["startup.wav"])
        self._advisor(kind="advice", seq=5, text="Play the Forest. Then Boots.")
        self.r.step()
        self.assertEqual(len(self.player.played), 1, "advice waits for the gap")
        self.clock.t += 9
        self.r.step()
        self.assertEqual(len(self.player.played), 2)
        self.assertIn("advice", [j["kind"] for j in self._records("spoke")])

    def test_stale_advice_is_dropped_when_the_human_already_chose(self):
        self.clock.t += 100
        self._advisor(kind="advice", seq=7, text="Attack with everything.")
        self._advisor(kind="chosen", seq=7, decisionType="DECLARE_ATTACKERS")
        self.r.step()
        self.assertEqual(self.player.played, [])
        self.assertEqual([d["why"] for d in self._records("dropped")], ["already answered"])

    def test_newest_advice_replaces_pending_advice_and_expiry_drops_it(self):
        self.clock.t += 100
        self.r.last_spoken_at = self.clock.t        # inside the gap: nothing plays yet
        self._advisor(kind="advice", seq=1, text="Old advice.")
        self._advisor(kind="advice", seq=2, text="New advice.")
        self.r.step()
        self.assertEqual(len(self.r.queue), 1)
        self.assertEqual(self.r.queue[0]["text"], "New advice.")
        self.clock.t += 30                            # past the 25 s ttl
        self.r.step()
        self.assertEqual(self.player.played, [])
        self.assertEqual([d["why"] for d in self._records("dropped")], ["expired"])

    def test_quip_records_play_the_stock_phrase(self):
        self.clock.t += 100
        self._advisor(kind="quip", id="nice-combo", turn=4)
        self.r.step()
        self.assertEqual(self.player.played, ["nice-combo.wav"])

    def test_game_events_your_move_elimination_and_game_over_order(self):
        self._observer(1, 1); self.r.step()                      # startup
        self.clock.t += 10; self._observer(2, 0); self.r.step()  # human's turn
        self.assertEqual(self.player.played[-1], "your-move.wav")
        self.clock.t += 10; self._observer(3, 1, elim=(2,)); self.r.step()
        self.assertEqual(self.player.played[-1], "player-eliminated.wav")
        self.clock.t += 1; self._observer(9, 1, game_over=True, elim=(1, 2, 3)); self.r.step(); self.r.step()
        self.assertEqual(self.player.played[-2:], ["you-win.wav", "game-over-gg.wav"],
                         "the win line then the sign-off, ignoring the gap")

    def test_loss_says_the_strange_game_line(self):
        self._observer(1, 1); self.r.step()
        self.clock.t += 1; self._observer(12, 2, game_over=True, elim=(0,)); self.r.step(); self.r.step()
        self.assertEqual(self.player.played[-2:], ["strange-game.wav", "game-over-gg.wav"])

    def test_mute_file_silences_everything(self):
        (self.logs / "control").mkdir()
        (self.logs / "control" / "voice.json").write_text('{"enabled": false}')
        self._observer(1, 1); self.r.step()
        self.assertEqual(self.player.played, [])

    # ---- glitch pass
    def test_glitch_is_deterministic_bounded_and_off_is_identity(self):
        raw = silent_wav(3.0)
        self.assertEqual(vr.glitch_wav(raw, "off", 1), raw)
        g1, g2, g3 = vr.glitch_wav(raw, "light", 42), vr.glitch_wav(raw, "light", 42), vr.glitch_wav(raw, "light", 43)
        self.assertEqual(g1, g2, "same seed, same hitches — a cached line never changes")
        self.assertNotEqual(g1, g3)
        with wave.open(io.BytesIO(g1)) as w:
            secs = w.getnframes() / w.getframerate()
        self.assertTrue(2.4 <= secs <= 3.6, f"length stays within ±20% (got {secs:.2f}s)")
        self.assertEqual(vr.glitch_wav(silent_wav(0.3), "heavy", 1), silent_wav(0.3), "sub-half-second lines are left alone")

    def test_glitch_level_is_part_of_the_cache_key(self):
        os.environ["ARENA_VOICE_GLITCH"] = "heavy"
        r = vr.VoiceRunner(self.logs, self.mailbox, fake_tts=lambda t: silent_wav(1.0), player=self.player, clock=self.clock)
        self.assertEqual(r.renderer.glitch, "heavy")
        p_heavy = r.renderer.render("Same words.")
        os.environ["ARENA_VOICE_GLITCH"] = "off"
        r2 = vr.VoiceRunner(self.logs, self.mailbox, fake_tts=lambda t: silent_wav(1.0), player=self.player, clock=self.clock)
        p_off = r2.renderer.render("Same words.")
        self.assertNotEqual(p_heavy, p_off, "different glitch levels never share a cache entry")

    def test_restart_reads_only_new_advisor_lines(self):
        self._advisor(kind="quip", id="ouch", turn=3)               # history from before the (re)start
        r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.clock.t += 100
        r.step()
        self.assertEqual(self.player.played, [], "history is never replayed")
        self._advisor(kind="quip", id="nice-combo", turn=4)          # new line after the start
        r.step()
        self.assertEqual(self.player.played, ["nice-combo.wav"])

    def test_restart_mid_game_does_not_greet_again(self):
        self._observer(7, 2)            # a game already at turn 7 when the runner (re)starts
        self.r.step()
        self.assertEqual(self.player.played, [])
        self.clock.t += 10; self._observer(8, 0); self.r.step()
        self.assertEqual(self.player.played, ["your-move.wav"], "it resumes with the next real event")

    # ---- colour recaps on opponents' turns
    def test_color_recaps_are_voiced_per_mode(self):
        self.clock.t += 100
        os.environ["ARENA_VOICE_COLOR"] = "all"
        r = vr.VoiceRunner(self.logs, self.mailbox, fake_tts=lambda t: silent_wav(0.5), player=self.player, clock=self.clock)
        self._advisor(kind="color", turn=3, text="Urza pitched a land to Mox Diamond. Three artifacts on turn two.")
        r.step()
        self.assertEqual(len(self.player.played), 1, "mode all voices every recap")
        os.environ["ARENA_VOICE_COLOR"] = "off"
        r2 = vr.VoiceRunner(self.logs, self.mailbox, fake_tts=lambda t: silent_wav(0.5), player=self.player, clock=self.clock)
        self._advisor(kind="color", turn=4, text="Giada played a Plains.")
        self.clock.t += 20; r2.step()
        self.assertEqual(len(self.player.played), 1, "mode off never does")
        os.environ["ARENA_VOICE_COLOR"] = "some"; os.environ["ARENA_VOICE_COLOR_P"] = "0.5"
        r3 = vr.VoiceRunner(self.logs, self.mailbox, fake_tts=lambda t: silent_wav(0.5), player=self.player, clock=self.clock)
        r3.rng.seed(1)
        spoken = 0
        for n in range(20):
            self._advisor(kind="color", turn=10 + n, text=f"Recap number {n}.")
            self.clock.t += 20; r3.step()
        spoken = len(self.player.played) - 1
        self.assertTrue(4 <= spoken <= 16, f"'some' voices roughly half (got {spoken}/20)")

    def _records(self, kind):
        p = self.logs / "voice-0.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if json.loads(l).get("event") == kind]


if __name__ == "__main__":
    unittest.main()
