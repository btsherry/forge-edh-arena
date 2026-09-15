"""Playback and rendering for the voice runner (runner/voice_runner.py): Player
(blocking WAV playback through whatever the OS has), Renderer (stock → cache →
live ElevenLabs, the film-match FX chain, the glitch pass), the WAV helpers and
the stock/voices paths. Pre-branch and stable. Split out of voice_runner.py on
2026-09-14 (voicework2 hardening plan, Phase 0a) with no behaviour change;
voice_runner re-exports every public name here, so `voice_runner.X` still works."""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent   # forge-arena/runner
ARENA = HERE.parent
STOCK = HERE / "voice" / "stock"
VOICES_DIR = STOCK / "voices"               # seat-bark libraries: voices/<name>/manifest.json + <id>[-N].wav
DEFAULT_VOICE_ID = ""                        # resolved from stock/manifest.json ("voice_id") unless ARENA_VOICE_ID is set


# ---- helpers ------------------------------------------------------------------

def cache_key(text: str, voice: str, model: str, fx: str) -> str:
    return hashlib.sha1(f"{voice}|{model}|{fx}|{text}".encode("utf-8")).hexdigest()


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 44100)
    except (wave.Error, OSError):
        return 0.0


# ---- glitch pass: stutters and hitches (Ben, 2026-09-07) -----------------------

GLITCH_LEVELS = {
    # events per second of audio: (stutter, hitch/dropout, skip, chatter)
    "off":   (0.0, 0.0, 0.0, 0.0),
    "light": (0.30, 0.20, 0.10, 0.12),
    "heavy": (0.70, 0.45, 0.25, 0.30),
}


def pcm_to_wav(pcm: bytes, rate: int, channels: int = 1, width: int = 2) -> bytes:
    """Wrap raw 16-bit PCM (ElevenLabs pcm_* output) in a WAV header — stdlib only,
    no ffmpeg (Ben, 2026-09-08)."""
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def lite_fx_wav(data: bytes) -> bytes:
    """The film-match effects chain WITHOUT ffmpeg, pure stdlib, 16-bit mono WAV:
    one-pole low-pass (~3.4 kHz, the W.O.P.R. loudspeaker), 50 Hz tremolo at
    25 % depth (the machine buzz), a 90 ms slap echo at -9 dB, a soft-knee
    compressor with makeup, then a -3 dBFS peak. Deterministic. Used only when
    ffmpeg is absent; stock lines were rendered with the full chain."""
    import array
    import io
    import math
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                return data
            sr = w.getframerate()
            frames = w.readframes(w.getnframes())
            pcm = array.array("h")
            pcm.frombytes(frames[: len(frames) - (len(frames) % 2)])   # a torn odd byte never raises
            if sys.byteorder == "big":
                pcm.byteswap()                                         # WAV payload is little-endian
    except (wave.Error, EOFError, OSError, ValueError):
        return data
    n = len(pcm)
    if n == 0:
        return data
    x = [s / 32768.0 for s in pcm]
    # 1) one-pole low-pass at ~3.4 kHz
    rc = 1.0 / (2 * math.pi * 3400.0)
    dt = 1.0 / sr
    alpha = dt / (rc + dt)
    y = [0.0] * n
    acc = 0.0
    for i in range(n):
        acc += alpha * (x[i] - acc)
        y[i] = acc
    # 2) tremolo 50 Hz, depth 0.25
    step = 2 * math.pi * 50.0 / sr
    for i in range(n):
        y[i] *= 1.0 - 0.25 * (0.5 - 0.5 * math.cos(step * i))
    # 3) slap echo 90 ms at -9 dB
    d = int(0.09 * sr)
    if d < n:
        g = 10 ** (-9 / 20)
        for i in range(n - 1, d - 1, -1):
            y[i] += g * y[i - d]
    # 4) soft-knee compressor + makeup, then peak to -3 dBFS
    for i in range(n):
        v = y[i] * 1.6
        y[i] = math.tanh(v)
    peak = max(1e-9, max(abs(v) for v in y))
    factor = (10 ** (-3 / 20)) / peak * 32767      # |v*factor| <= 23197: no clamp needed
    out = array.array("h", [int(v * factor) for v in y])
    if sys.byteorder == "big":
        out.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(out.tobytes())
    return buf.getvalue()


def glitch_wav(data: bytes, level: str, seed: int) -> bytes:
    """W.O.P.R. digital hitches on a 16-bit mono WAV, pure stdlib.
    - stutter: a 35–75 ms slice repeats 2–3 times (a word catching)
    - hitch:   15–40 ms goes silent (a dropout)
    - skip:    20–50 ms is cut (the tape jumps)
    - chatter: an 8–12 ms slice repeats 4–6 times (machine buzz)
    Deterministic for (level, seed) so a cached line always sounds the same;
    never touches the first/last 120 ms; total length stays within ±20%."""
    rates = GLITCH_LEVELS.get(level, GLITCH_LEVELS["light"])
    if not any(rates):
        return data
    import array
    import io

    try:
        wave.open(io.BytesIO(data), "rb").close()
    except (wave.Error, EOFError, OSError):
        return data   # not a WAV (ffmpeg absent -> raw mp3): leave it untouched
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            return data
        sr = w.getframerate()
        pcm = array.array("h")
        pcm.frombytes(w.readframes(w.getnframes()))
    n = len(pcm)
    seconds = n / sr
    if seconds < 0.5:
        return data
    rng = random.Random(seed)
    ms = lambda x: int(sr * x / 1000)  # noqa: E731
    guard = ms(120)

    def fade(seg, k):
        k = min(k, len(seg) // 2)
        for i in range(k):
            g = i / k
            seg[i] = int(seg[i] * g)
            seg[-1 - i] = int(seg[-1 - i] * g)
        return seg

    events = []
    for kind, rate in zip(("stutter", "hitch", "skip", "chatter"), rates):
        count = int(rate * seconds) + (1 if rng.random() < (rate * seconds) % 1 else 0)
        for _ in range(count):
            events.append((rng.randint(guard, max(guard + 1, n - guard)), kind))
    events.sort()
    out = array.array("h")
    pos = 0
    for at, kind in events:
        if at <= pos:
            continue
        out.extend(pcm[pos:at])
        if kind == "stutter":
            L = ms(rng.randint(35, 75)); reps = rng.randint(2, 3)
            seg = fade(pcm[at:at + L], ms(3))
            for _ in range(reps):
                out.extend(seg)
            pos = at
        elif kind == "hitch":
            L = ms(rng.randint(15, 40))
            out.extend(array.array("h", [0] * L))
            pos = at + L
        elif kind == "skip":
            pos = at + ms(rng.randint(20, 50))
        else:  # chatter
            L = ms(rng.randint(8, 12)); reps = rng.randint(4, 6)
            seg = fade(pcm[at:at + L], ms(1))
            for _ in range(reps):
                out.extend(seg)
            pos = at + L
    out.extend(pcm[pos:])
    # bound the length change
    if not (0.8 * n <= len(out) <= 1.2 * n):
        return data
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(out.tobytes())
    return buf.getvalue()


# ---- players -----------------------------------------------------------------

class Player:
    """Blocking playback of a WAV on the default output, via whatever the OS has:
    afplay (macOS), paplay/aplay (Linux), ffplay (anywhere with ffmpeg), or
    PowerShell's .NET SoundPlayer (Windows, WAV only). Plus the UNDER channel
    (2026-09-14, the atoms): a second, quieter playback beneath the main line —
    one at a time, never blocking, killed together with the main channel."""

    def __init__(self, dry_run: bool = False, log=print):
        self.dry_run = dry_run
        self.log = log
        self.cmd = None
        self.windows = False
        for cand in (["afplay"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]):
            if shutil.which(cand[0]):
                self.cmd = cand
                break
        self.winsound = None
        if self.cmd is None and sys.platform == "win32":
            # Windows (Ben, 2026-09-08): the stdlib winsound module plays a WAV with
            # no process spawn; SND_ASYNC + SND_PURGE make it interruptible.
            try:
                import winsound as _ws
                self.winsound = _ws
            except ImportError:
                pass
        if self.cmd is None and self.winsound is None and shutil.which("powershell"):
            # last resort on Windows-like shells: .NET's SoundPlayer from PowerShell
            self.cmd = ["powershell", "-NoProfile", "-Command"]
            self.windows = True
        self._under: subprocess.Popen | None = None
        self._under_dry_until = 0.0        # dry run / no player: the under line "plays" for its length
        self._under_lock = threading.Lock()
        self._under_warned = False

    def play(self, path: Path, should_stop=None) -> None:
        """Play one file. `should_stop()` is polled every 200 ms; when it turns
        true the player process is killed (Ben, 2026-09-08: pausing the advisor
        must silence playback at once, not after the line)."""
        if self.dry_run or (self.cmd is None and self.winsound is None):
            self.log(f"[voice] (dry) play {path.name} {wav_seconds(path):.1f}s")
            time.sleep(min(wav_seconds(path), 0.05) if self.dry_run else 0)
            return
        if self.winsound is not None:
            ws = self.winsound
            ws.PlaySound(str(path), ws.SND_FILENAME | ws.SND_ASYNC | ws.SND_NODEFAULT)
            end = time.time() + max(0.1, wav_seconds(path))
            while time.time() < end:
                if should_stop is not None and should_stop():
                    ws.PlaySound(None, ws.SND_PURGE)
                    self.stop_under()
                    self.log("[voice] playback cut: voice disabled")
                    break
                time.sleep(0.1)
            return
        if self.windows:
            safe = str(path).replace("'", "''")
            argv = self.cmd + [f"(New-Object Media.SoundPlayer '{safe}').PlaySync()"]
        else:
            argv = self.cmd + [str(path)]
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        deadline = time.time() + 120
        try:
            while proc.poll() is None and time.time() < deadline:
                if should_stop is not None and should_stop():
                    proc.kill()
                    self.stop_under()                     # the atom beneath the line goes with it
                    self.log("[voice] playback cut: voice disabled")
                    break
                time.sleep(0.2)
            if proc.poll() is None:
                proc.kill()
        finally:
            try:
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass

    # -- the under channel (the atoms, voicework2 hardening plan 4.5)
    def _under_argv(self, path: Path, volume: float) -> list[str] | None:
        """The argv for a quiet second playback, or None when this backend cannot
        overlap at a volume: afplay -v (0..1), ffplay -volume (0..100 %), paplay
        --volume (0..65536). aplay has no volume flag; winsound and .NET's
        SoundPlayer play one file at a time."""
        if self.cmd is None or self.windows:
            return None
        v = max(0.0, min(1.0, float(volume)))
        tool = self.cmd[0]
        if tool == "afplay":
            return ["afplay", "-v", f"{v:.2f}", str(path)]
        if tool == "ffplay":
            return self.cmd + ["-volume", str(int(round(v * 100))), str(path)]
        if tool == "paplay":
            return ["paplay", f"--volume={int(round(v * 65536))}", str(path)]
        return None

    def _under_alive(self) -> bool:
        """Caller holds _under_lock. A finished process is reaped here."""
        if self._under is not None:
            if self._under.poll() is None:
                return True
            self._under = None
        return time.time() < self._under_dry_until

    def under_playing(self) -> bool:
        with self._under_lock:
            return self._under_alive()

    def play_under(self, path: Path, volume: float = 0.5) -> bool:
        """Start a second playback BENEATH whatever the main channel is doing and
        return at once. At most one under-line at a time: False while one plays,
        False on a backend that cannot overlap at a volume (aplay, winsound,
        PowerShell — said once), True when the process started (or, dry, was logged)."""
        with self._under_lock:
            if self._under_alive():
                return False
            if self.dry_run or (self.cmd is None and self.winsound is None):
                secs = wav_seconds(path)
                self.log(f"[voice] (dry) under {path.name} {secs:.1f}s")
                self._under_dry_until = time.time() + secs
                return True
            argv = self._under_argv(path, volume)
            if argv is None:
                if not self._under_warned:
                    self._under_warned = True
                    tool = self.cmd[0] if self.cmd else "winsound"
                    self.log(f"[voice] under channel off: {tool} cannot overlap at a volume — the atoms need afplay, ffplay or paplay")
                return False
            try:
                self._under = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL)
            except OSError as e:
                self.log(f"[voice] under channel failed: {str(e)[:120]}")
                return False
            # reap the child when the take is over instead of leaving a zombie until the next poll
            reap = threading.Timer(wav_seconds(path) + 0.5, self.under_playing)
            reap.daemon = True
            reap.start()
            return True

    def stop_under(self) -> None:
        """Kill the under-line, if one is playing. Called with the main channel's
        kill (mute, advisor pause) and at the game-over lock."""
        with self._under_lock:
            self._under_dry_until = 0.0
            proc, self._under = self._under, None
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass


# ---- renderer -------------------------------------------------------------------

class Renderer:
    """stock → cache → live. Live is ElevenLabs Flash v2.5: PCM back (wrapped in
    our own WAV header, no ffmpeg needed), the film-match effects via ffmpeg when
    present or the pure-Python lite chain when not; the result is cached."""

    # After this many consecutive live failures the renderer stops calling
    # ElevenLabs for a while (60 s, doubling to 10 min) and says so ONCE;
    # a quota that ran out mid-game no longer writes a failure per line.
    FAIL_PAUSE_AFTER = 3
    PAUSE_FIRST_S = 60.0
    PAUSE_MAX_S = 600.0

    def __init__(self, cache_dir: Path, log=print, fake_tts=None, record=None, clock=time.monotonic, rng=None):
        self.cache_dir = cache_dir
        self.rng = rng or random.Random()
        self._bags: dict[tuple[str, str], list[Path]] = {}     # (library, id) -> wordings still to play this round
        self._last_variant: dict[tuple[str, str], Path] = {}
        self.log = log
        self.record = record          # callable(event, **body) -> the voice jsonl; optional
        self.clock = clock
        self.renders = 0              # live renders that produced audio
        self.fails_total = 0
        self.fail_streak = 0
        self.paused_until = 0.0
        self.pause_s = self.PAUSE_FIRST_S
        self.stock_only_reason = ""   # set when live lines are switched off for the run
        self.manifest = json.loads((STOCK / "manifest.json").read_text()) if (STOCK / "manifest.json").exists() else {"phrases": {}, "sfx": []}
        self.api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        self.voice_id = os.environ.get("ARENA_VOICE_ID") or self.manifest.get("voice_id") or DEFAULT_VOICE_ID
        self.model = os.environ.get("ARENA_VOICE_MODEL", "eleven_flash_v2_5")
        # Output format (Ben, 2026-09-08): raw PCM wrapped in our own WAV header
        # removes ffmpeg as a decode dependency; pcm_24000 is available on the
        # Creator tier (pcm_44100 is Pro-only — the 09-07 failure). A rejected
        # format falls back to MP3 once, for this run.
        self.format = os.environ.get("ARENA_VOICE_FORMAT", "pcm_24000")
        # Effects: "full" = ffmpeg + the stock chain (when ffmpeg exists), "lite"
        # = pure-Python chain (no ffmpeg), "off". ARENA_VOICE_FX=on picks full
        # when ffmpeg is present, lite otherwise.
        fx_env = os.environ.get("ARENA_VOICE_FX", "on").lower()
        have_ffmpeg = shutil.which("ffmpeg") is not None
        if fx_env == "off":
            self.fx_mode = "off"
        elif fx_env == "lite" or (fx_env == "on" and not have_ffmpeg):
            self.fx_mode = "lite"
        else:
            self.fx_mode = "full" if have_ffmpeg else "lite"
        self.fx_on = self.fx_mode != "off"
        fx_file = STOCK / self.manifest.get("fx_chain_file", "fx-chain.txt")
        self.fx_chain = fx_file.read_text().strip() if (self.fx_mode == "full" and fx_file.exists()) else ""
        self.voice_resolved = False   # set after a 404 sent us to the voice library by name
        self.max_chars = int(os.environ.get("ARENA_VOICE_MAX_CHARS", "20000"))
        self.glitch = os.environ.get("ARENA_VOICE_GLITCH", "light").lower()
        if self.glitch not in GLITCH_LEVELS:
            self.glitch = "light"
        self.chars_used = 0
        self.fake_tts = fake_tts  # tests: callable(text) -> wav bytes
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def live(self) -> bool:
        return bool(self.api_key or self.fake_tts) and self.chars_used < self.max_chars

    def state(self) -> tuple[bool, str]:
        """(live lines available now?, reason when not) — published for the
        advisor (Ben, 2026-09-08): with live lines down the advisor tags a
        stock quip on about one line in two to fill the silence."""
        if not (self.api_key or self.fake_tts):
            return False, self.stock_only_reason or "no ELEVENLABS_API_KEY"
        if self.chars_used >= self.max_chars:
            return False, f"character cap {self.max_chars} reached"
        if self.clock() < self.paused_until:
            return False, "paused after repeated failures"
        return True, "ok"

    def variants(self, pid: str, library: str = "") -> list[Path]:
        """<id>.wav plus <id>-N.wav (N numeric) in the Joshua library or voices/<library>/."""
        d = (VOICES_DIR / library) if library else STOCK
        files = [d / f"{pid}.wav"] + sorted(d.glob(f"{pid}-[0-9]*.wav"))
        return [f for f in files if f.exists()]

    def stock(self, pid: str, library: str = "") -> Path | None:
        """One wording of a stock line. Several wordings (2026-09-10: four for the
        lines that repeat) play from a shuffle bag — every wording once, in random
        order, before any repeats, and never the same one twice running."""
        files = self.variants(pid, library)
        if not files:
            return None
        if len(files) == 1:
            return files[0]
        key = (library, pid)
        bag = self._bags.get(key)
        if not bag:
            bag = files[:]
            self.rng.shuffle(bag)
            last = self._last_variant.get(key)
            if last is not None and bag[0] == last:
                bag.append(bag.pop(0))
            self._bags[key] = bag
        pick = bag.pop(0)
        self._last_variant[key] = pick
        return pick

    def sfx(self) -> Path | None:
        names = self.manifest.get("sfx") or []
        if not names:
            return None
        p = STOCK / "sfx" / random.choice(names)
        return p if p.exists() else None

    def render(self, text: str) -> Path | None:
        """A WAV for this text: cache hit, else live (if allowed), else None."""
        text = text.strip()
        if not text:
            return None
        fx_tag = (self.fx_chain if self.fx_mode == "full" else self.fx_mode) + "|glitch=" + self.glitch
        key = cache_key(text, self.voice_id, self.model, fx_tag)
        out = self.cache_dir / f"{key}.wav"
        if out.exists():
            return out
        if not self.live:
            return None
        if self.clock() < self.paused_until:
            return None   # backing off after repeated failures; stock phrases still play
        try:
            if self.fake_tts is not None:
                raw = self.fake_tts(text)
                cost = len(text)
            else:
                raw, cost = self._elevenlabs(text)
        except Exception as e:  # noqa: BLE001 — a failed render is a skipped line, never a crash
            self._render_failed(str(e)[:160])
            return None
        if self.fail_streak:
            self.log(f"[voice] live render recovered after {self.fail_streak} failure(s)")
            self.fail_streak = 0
            self.pause_s = self.PAUSE_FIRST_S
        self.renders += 1
        self.chars_used += cost
        # what did we get? WAV (a fake, or PCM already wrapped), or MP3 (fallback)
        is_wav = raw[:4] == b"RIFF"
        tmp_out = self.cache_dir / f"{key}.tmp.wav"
        try:
            if self.fx_mode == "full" and shutil.which("ffmpeg"):
                tmp_in = self.cache_dir / f"{key}.in"
                tmp_in.write_bytes(raw)
                try:
                    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_in),
                           "-ar", "44100", "-ac", "1"]
                    if self.fx_chain:
                        cmd += ["-af", self.fx_chain]
                    cmd.append(str(tmp_out))
                    subprocess.run(cmd, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                finally:
                    tmp_in.unlink(missing_ok=True)
            elif is_wav:
                tmp_out.write_bytes(lite_fx_wav(raw) if self.fx_mode == "lite" else raw)
            elif shutil.which("ffmpeg"):
                # MP3 fallback with ffmpeg present but fx off/lite: decode only
                tmp_in = self.cache_dir / f"{key}.in"
                tmp_in.write_bytes(raw)
                try:
                    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_in),
                                    "-ar", "44100", "-ac", "1", str(tmp_out)], check=True, timeout=60,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                finally:
                    tmp_in.unlink(missing_ok=True)
                if self.fx_mode == "lite":
                    tmp_out.write_bytes(lite_fx_wav(tmp_out.read_bytes()))
            elif sys.platform == "darwin":
                tmp_out.write_bytes(raw)  # raw MP3, no ffmpeg: afplay decodes it anyway
            else:
                self.log("[voice] MP3 fallback needs ffmpeg on this platform — live lines off for this run")
                self.api_key = ""
                self.stock_only_reason = "MP3 fallback needs ffmpeg"
                tmp_out.unlink(missing_ok=True)
                return None
            if self.glitch != "off":
                tmp_out.write_bytes(glitch_wav(tmp_out.read_bytes(), self.glitch, int(key[:8], 16)))
            tmp_out.replace(out)
        except Exception as e:  # noqa: BLE001
            self.log(f"[voice] post-processing failed: {str(e)[:160]}")
            tmp_out.unlink(missing_ok=True)
            return None
        return out

    def _render_failed(self, detail: str) -> None:
        """Count a live failure; log the first of a streak in full, then one
        line per pause instead of one per attempt."""
        self.fails_total += 1
        self.fail_streak += 1
        if self.record is not None:
            try:
                self.record("render-failed", streak=self.fail_streak, detail=detail[:120])
            except Exception:  # noqa: BLE001
                pass
        if self.fail_streak == 1:
            self.log(f"[voice] live render failed: {detail}")
        if self.fail_streak >= self.FAIL_PAUSE_AFTER:
            self.paused_until = self.clock() + self.pause_s
            self.log(f"[voice] live render failed {self.fail_streak}x in a row (last: {detail}) — "
                     f"live lines paused {int(self.pause_s)}s; stock phrases continue")
            if self.record is not None:
                try:
                    self.record("live-paused", failures=self.fail_streak, seconds=int(self.pause_s), detail=detail[:120])
                except Exception:  # noqa: BLE001
                    pass
            self.pause_s = min(self.pause_s * 2, self.PAUSE_MAX_S)

    def _elevenlabs(self, text: str) -> tuple[bytes, int]:
        """One TTS call. PCM comes back as raw 16-bit samples and is wrapped in a
        WAV header here; MP3 (fallback) is returned as-is. A 404 on the voice
        resolves the voice by NAME from the account's library once (a shared
        library voice gets a different id in each account); a rejected output
        format (tier) falls back to MP3 for the rest of the run."""
        body = json.dumps({"text": text, "model_id": self.model,
                           "voice_settings": {"stability": 0.9, "similarity_boost": 0.8, "style": 0.0,
                                              "use_speaker_boost": True, "speed": 0.92}}).encode("utf-8")
        for attempt in range(3):
            req = urllib.request.Request(
                f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?output_format={self.format}",
                data=body, headers={"xi-api-key": self.api_key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                    cost = int(resp.headers.get("character-cost") or len(text))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001
                    pass
                if e.code == 404 and not self.voice_resolved and self._resolve_voice_by_name():
                    continue   # retry with the resolved id
                if e.code in (400, 402, 403) and self.format.startswith("pcm") and (
                        "output_format" in detail or "format" in detail.lower() or "tier" in detail.lower()):
                    self.log(f"[voice] {self.format} rejected ({e.code}) — falling back to mp3_44100_128 for this run")
                    self.format = "mp3_44100_128"
                    continue
                raise RuntimeError(f"HTTP {e.code} {detail}") from None
            if self.format.startswith("pcm_"):
                rate = int(self.format.split("_")[1])
                return pcm_to_wav(data, rate), cost
            return data, cost
        raise RuntimeError("ElevenLabs: retries exhausted")

    def _resolve_voice_by_name(self) -> bool:
        """The manifest's voice id belongs to the account that rendered the
        stock lines. Another account that added the shared voice (or made its
        own) has it under a different id: look it up by the manifest's
        voice_name in GET /v1/voices. False when nothing matches — the log then
        says how to set ARENA_VOICE_ID."""
        self.voice_resolved = True
        name = (self.manifest.get("voice_name") or "").strip().lower()
        try:
            req = urllib.request.Request("https://api.elevenlabs.io/v1/voices",
                                         headers={"xi-api-key": self.api_key})
            with urllib.request.urlopen(req, timeout=30) as resp:
                voices = json.loads(resp.read().decode("utf-8")).get("voices") or []
        except Exception as e:  # noqa: BLE001
            self.log(f"[voice] voice lookup failed: {str(e)[:120]}")
            return False
        for v in voices:
            if name and str(v.get("name", "")).strip().lower() == name and v.get("voice_id"):
                self.log(f"[voice] voice '{v.get('name')}' found in this account's library — using it "
                         f"(set ARENA_VOICE_ID to pin a voice)")
                self.voice_id = v["voice_id"]
                return True
        self.log(f"[voice] voice {str(self.voice_id or '')[:6]}… not in this account and no library voice named "
                 f"'{self.manifest.get('voice_name')}' — add it from the ElevenLabs Voice Library or set "
                 f"ARENA_VOICE_ID to any voice you own; live lines are off until then")
        self.api_key = ""   # stock only from here: no more failing calls
        self.stock_only_reason = "no usable voice in this account"
        return False
