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

    # ---- the human's own elimination
    def test_human_elimination_plays_a_rotation_line_at_once(self):
        self._observer(1, 1); self.r.step()                          # startup
        self.clock.t += 1                                             # inside the gap: human_out ignores it
        self._observer(14, 2, elim=(0,)); self.r.step()
        self.assertIn(self.player.played[-1], {"winner-none.wav", "whats-the-difference.wav", "meatbag-out.wav"})
        self.clock.t += 10; self._observer(15, 3, elim=(0,)); self.r.step()
        self.assertEqual(len(self.player.played), 2, "said once per death, not per snapshot")

    def test_human_elimination_that_ends_the_game_uses_the_loss_pair_only(self):
        self._observer(1, 1); self.r.step()
        self.clock.t += 1; self._observer(20, 2, game_over=True, elim=(0,)); self.r.step(); self.r.step(); self.r.step()
        self.assertEqual(self.player.played[1:], ["strange-game.wav", "game-over-gg.wav"])

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



class AdvisorPauseSilencesVoice(unittest.TestCase):
    """Ben, 2026-09-08: pausing the advisor in the panel must silence EVERY
    voice line (advice, quips, colour, your-move, elimination, game over,
    bleeps), drop what is queued, and cut a line already playing."""
    def _runner(self):
        import tempfile, json as _json
        from pathlib import Path as _P
        import voice_runner as vr
        tmp = _P(tempfile.mkdtemp(prefix="vpause-"))
        (tmp / "logs" / "control").mkdir(parents=True)
        (tmp / "mailbox").mkdir()
        r = vr.VoiceRunner(tmp / "logs", tmp / "mailbox", dry_run=True)
        return r, tmp, _json

    def test_advisor_pause_disables_and_drops_the_queue(self):
        r, tmp, js = self._runner()
        self.assertTrue(r.enabled())
        r.enqueue("game_over", stock="game-over-gg")
        r.enqueue("your_move", stock="your-move")
        (tmp / "logs" / "control" / "advisor.json").write_text(js.dumps({"enabled": False}))
        self.assertFalse(r.enabled(), "the advisor pause silences the voice")
        r.step()
        self.assertEqual(r.queue, [], "queued lines are dropped, nothing plays late on resume")
        (tmp / "logs" / "control" / "advisor.json").write_text(js.dumps({"enabled": True}))
        self.assertTrue(r.enabled())
        (tmp / "logs" / "control" / "voice.json").write_text(js.dumps({"enabled": False}))
        self.assertFalse(r.enabled(), "the voice's own mute still works")

    def test_player_polls_should_stop(self):
        import voice_runner as vr
        calls = []
        p = vr.Player(dry_run=True, log=calls.append)
        p.play(__import__("pathlib").Path("/nonexistent.wav"), should_stop=lambda: True)  # dry run: no process, no error
        self.assertTrue(calls and "(dry)" in calls[0])


class PcmAndLiteChain(unittest.TestCase):
    """Ben, 2026-09-08: ElevenLabs PCM wrapped in our own WAV header (no ffmpeg
    to decode), a pure-Python effects chain when ffmpeg is absent, and the
    voice resolved by NAME from the account's library on a 404."""
    def test_pcm_to_wav_header(self):
        import voice_runner as vr, wave, io, array
        pcm = array.array("h", [0, 1000, -1000, 0] * 600).tobytes()
        wav = vr.pcm_to_wav(pcm, 24000)
        self.assertEqual(wav[:4], b"RIFF")
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()), (24000, 1, 2, 2400))

    def test_lite_fx_is_deterministic_bounded_and_keeps_length(self):
        import voice_runner as vr, wave, io, array, math
        sr = 24000; n = sr // 2
        pcm = array.array("h", (int(12000 * math.sin(2 * math.pi * 220 * i / sr)) for i in range(n))).tobytes()
        wav = vr.pcm_to_wav(pcm, sr)
        a = vr.lite_fx_wav(wav); b = vr.lite_fx_wav(wav)
        self.assertEqual(a, b, "deterministic")
        with wave.open(io.BytesIO(a)) as w:
            self.assertEqual(w.getnframes(), n); self.assertEqual(w.getframerate(), sr)
            out = array.array("h"); out.frombytes(w.readframes(n))
        peak = max(abs(s) for s in out) / 32768.0
        self.assertLessEqual(peak, 10 ** (-3 / 20) + 0.002, "peak at -3 dBFS")
        self.assertGreater(peak, 0.5, "not silenced")
        self.assertEqual(vr.lite_fx_wav(b"not a wav"), b"not a wav", "non-WAV passes through")

    def _renderer(self, tmp, fake_http):
        import voice_runner as vr, os
        os.environ["ELEVENLABS_API_KEY"] = "test-key"
        os.environ["ARENA_VOICE_FX"] = "off"
        try:
            r = vr.Renderer(tmp / "cache", log=lambda m: self.logs.append(m))
        finally:
            os.environ.pop("ELEVENLABS_API_KEY", None); os.environ.pop("ARENA_VOICE_FX", None)
        r.manifest = dict(r.manifest, voice_id="old-id", voice_name="Jousha-W.O.P.R.")
        r.voice_id = "old-id"
        vr.urllib.request.urlopen = fake_http
        self.addCleanup(lambda: setattr(vr.urllib.request, "urlopen", self._orig_urlopen))
        return r

    def setUp(self):
        import voice_runner as vr
        self.logs = []
        self._orig_urlopen = vr.urllib.request.urlopen

    def test_pcm_response_is_wrapped_and_cached_as_wav(self):
        import voice_runner as vr, tempfile, io, array, wave
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp(prefix="pcm-"))
        pcm = array.array("h", [500, -500] * 2400).tobytes()

        class Resp:
            headers = {"character-cost": "12"}
            def __init__(self, data): self.data = data
            def read(self): return self.data
            def __enter__(self): return self
            def __exit__(self, *a): return False
        seen = {}
        def fake_http(req, timeout=30):
            seen["url"] = req.full_url; return Resp(pcm)
        r = self._renderer(tmp, fake_http)
        out = r.render("Would you like to play a game?")
        self.assertIn("output_format=pcm_24000", seen["url"])
        self.assertTrue(out and out.suffix == ".wav")
        with wave.open(str(out)) as w:
            self.assertEqual(w.getframerate(), 24000); self.assertEqual(w.getnframes(), 4800)
        self.assertEqual(r.chars_used, 12)

    def test_404_resolves_the_voice_by_library_name(self):
        import voice_runner as vr, tempfile, json as js, array, urllib.error
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp(prefix="v404-"))
        pcm = array.array("h", [1, -1] * 1200).tobytes()

        class Resp:
            headers = {}
            def __init__(self, data): self.data = data
            def read(self): return self.data
            def __enter__(self): return self
            def __exit__(self, *a): return False
        calls = []
        def fake_http(req, timeout=30):
            calls.append(req.full_url)
            if "/v1/voices" in req.full_url and "text-to-speech" not in req.full_url:
                return Resp(js.dumps({"voices": [{"voice_id": "new-id", "name": "Jousha-W.O.P.R."}]}).encode())
            if "old-id" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 404, "voice_not_found", {}, None)
            return Resp(pcm)
        r = self._renderer(tmp, fake_http)
        out = r.render("Greetings, Professor Falken.")
        self.assertIsNotNone(out)
        self.assertEqual(r.voice_id, "new-id")
        self.assertTrue(any("found in this account" in l for l in self.logs))
        self.assertEqual(sum(1 for c in calls if "text-to-speech" in c), 2, "one failed call, one retry")

    def test_rejected_pcm_format_falls_back_to_mp3_for_the_run(self):
        import voice_runner as vr, tempfile, urllib.error
        from pathlib import Path as _P
        tmp = _P(tempfile.mkdtemp(prefix="vfmt-"))

        class Resp:
            headers = {}
            def __init__(self, data): self.data = data
            def read(self): return self.data
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Err(urllib.error.HTTPError):
            def read(self): return b'{"detail": {"message": "output_format pcm_24000 requires a higher tier"}}'
        def fake_http(req, timeout=30):
            if "pcm_24000" in req.full_url:
                raise Err(req.full_url, 403, "forbidden", {}, None)
            return Resp(b"ID3fakemp3bytes")
        r = self._renderer(tmp, fake_http)
        orig_which = vr.shutil.which
        vr.shutil.which = lambda name: None          # no ffmpeg: the raw MP3 is kept as-is
        self.addCleanup(lambda: setattr(vr.shutil, "which", orig_which))
        out = r.render("A strange game.")
        self.assertEqual(r.format, "mp3_44100_128")
        self.assertIsNotNone(out)
        self.assertTrue(any("falling back to mp3" in l for l in self.logs))


class PlayerStopsAProcess(unittest.TestCase):
    """Gemini pass 3: the stop poll must actually kill the player process."""
    def test_should_stop_kills_the_player(self):
        import voice_runner as vr
        class FakeProc:
            def __init__(self): self.killed = False; self._rc = None
            def poll(self): return self._rc
            def kill(self): self.killed = True; self._rc = -9
            def wait(self, timeout=None): return self._rc
        made = []
        orig_popen = vr.subprocess.Popen
        vr.subprocess.Popen = lambda *a, **k: made.append(FakeProc()) or made[-1]
        try:
            logs = []
            p = vr.Player(dry_run=False, log=logs.append)
            p.cmd = ["afplay"]; p.winsound = None; p.windows = False
            p.play(__import__("pathlib").Path("/x.wav"), should_stop=lambda: True)
            self.assertTrue(made and made[0].killed, "the process is killed when the poll says stop")
            self.assertTrue(any("cut" in l for l in logs))
        finally:
            vr.subprocess.Popen = orig_popen

    def test_lite_fx_tolerates_an_odd_byte_count(self):
        import voice_runner as vr, wave, io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\x00\x10" * 100 + b"\x7f")
        out = vr.lite_fx_wav(buf.getvalue())
        self.assertTrue(out[:4] == b"RIFF")
