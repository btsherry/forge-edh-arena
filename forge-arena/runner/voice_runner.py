#!/usr/bin/env python3
"""Voice runner — the advisor's voice (Joshua / W.O.P.R. register).

A stdlib-only daemon on the same one-way file seam as everything else: it
READS the advisor's structured stream and the engine's observer snapshot,
decides what deserves a spoken line, and plays it on the Mac's default
output. It never writes to the mailbox, so the game can never wait on it.

Sources
  runner/logs/advisor-0.jsonl   advice (first sentence, LIVE), ask answers
                                (LIVE), quip records the advisor emits
                                (STOCK phrase by id), colour recaps (LIVE, some
                                of them — this is what speaks on opponents' turns)
  mailbox/observer-state.json   game start → "startup" stock line; the human's
                                turn beginning → "your-move" (low priority);
                                eliminations → "player-eliminated"; the human's own
                                elimination → one of manifest.human_out; game over →
                                win: "you-win" + "game-over-gg", loss:
                                "strange-game" + "game-over-gg"
  runner/logs/control/voice.json  {"enabled": false} mutes (written by
                                --mute / --unmute or the GUI later)

Rendering
  STOCK  runner/voice/stock/<id>.wav — shipped, pre-rendered, FX baked in.
  CACHE  runner/logs/cache/voice/<sha1>.wav — every live line is kept, keyed
         by text+voice+model+fx; a repeated line never costs again.
  LIVE   ElevenLabs Flash v2.5 (`eleven_flash_v2_5`) over HTTPS, MP3 in,
         ffmpeg → WAV + the stock FX chain (skipped when ffmpeg is absent).
         Only with ELEVENLABS_API_KEY set; otherwise the daemon is stock-only.

Discipline (Ben, 2026-09-07): it should not talk constantly — at most one
utterance per ARENA_VOICE_MIN_GAP seconds (default 8), one at a time, newest
high-priority item wins, advice for a window the human already answered is
dropped, a random terminal bleep precedes each line (ARENA_VOICE_SFX=off to
silence them).

Env knobs
  ELEVENLABS_API_KEY        live rendering on (never logged)
  ARENA_VOICE_ID            voice to render with (default: the shipped voice id)
  ARENA_VOICE_MODEL         default eleven_flash_v2_5
  ARENA_VOICE_MIN_GAP       seconds between utterances (8)
  ARENA_VOICE_MAX_CHARS     live characters per game before stock-only (20000)
  ARENA_VOICE_SFX           on|off bleeps (on)
  ARENA_VOICE_FX            on|off the film FX chain on live lines (on)
  ARENA_VOICE_GLITCH        off|light|heavy stutters and hitches on every line (light)
  ARENA_VOICE_YOUR_MOVE     on|off "Your move." at the human's turns (on)
  ARENA_VOICE_COLOR         off|some|all — voice the per-turn recap (opponents' turns too); some = probability ARENA_VOICE_COLOR_P (0.5)

CLI
  voice_runner.py                       run the daemon
  voice_runner.py --play startup        play a stock phrase and exit
  voice_runner.py --say "text"          render (cache/live) + play one line, exit
  voice_runner.py --mute | --unmute     flip control/voice.json
  voice_runner.py --dry-run             log what would be spoken, play nothing
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent          # forge-arena/runner
ARENA = HERE.parent
STOCK = HERE / "voice" / "stock"
DEFAULT_VOICE_ID = ""                        # resolved from stock/manifest.json ("voice_id") unless ARENA_VOICE_ID is set
POLL_S = 0.5
FIRST_SENTENCE_MAX = 220
ASK_MAX = 300
PRIORITY = {"game_over": 0, "human_out": 0, "startup": 1, "ask": 2, "advice": 3, "quip": 4, "event": 5, "color": 6, "your_move": 7}


# ---- helpers ------------------------------------------------------------------

def first_sentence(text: str, limit: int = FIRST_SENTENCE_MAX) -> str:
    """The first sentence, cleaned for speech: no markdown, no brackets, no
    card-id noise; cut at a sentence end or the limit."""
    t = re.sub(r"\[[^\]]*\]", " ", text or "")           # [t12 · you], [quip:x], (ids)
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    m = re.search(r"^(.+?[.!?])(\s|$)", t)
    s = m.group(1) if m else t
    if len(s) > limit:
        cut = s[:limit]
        s = cut[: cut.rfind(" ")] if " " in cut else cut
        s = s.rstrip(",;:") + "."
    return s


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
    PowerShell's .NET SoundPlayer (Windows, WAV only)."""

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

    def __init__(self, cache_dir: Path, log=print, fake_tts=None, record=None, clock=time.monotonic):
        self.cache_dir = cache_dir
        self.log = log
        self.record = record          # callable(event, **body) -> the voice jsonl; optional
        self.clock = clock
        self.renders = 0              # live renders that produced audio
        self.fails_total = 0
        self.fail_streak = 0
        self.paused_until = 0.0
        self.pause_s = self.PAUSE_FIRST_S
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

    def stock(self, pid: str) -> Path | None:
        p = STOCK / f"{pid}.wav"
        return p if p.exists() else None

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
        return False


# ---- the daemon --------------------------------------------------------------------

class VoiceRunner:
    def __init__(self, logs_dir: Path, mailbox_dir: Path, dry_run: bool = False, fake_tts=None, player=None, clock=time.monotonic):
        self.logs = logs_dir
        self.mailbox = mailbox_dir
        self.dry_run = dry_run
        self.clock = clock
        self._log_path = logs_dir / "voice-0.log"
        self._jsonl = logs_dir / "voice-0.jsonl"
        self._control = logs_dir / "control" / "voice.json"
        self.renderer = Renderer(logs_dir / "cache" / "voice", log=self.say, fake_tts=fake_tts,
                                 record=self.record, clock=clock)
        self.player = player or Player(dry_run=dry_run, log=self.say)
        self.min_gap = float(os.environ.get("ARENA_VOICE_MIN_GAP", "8"))
        self.sfx_on = os.environ.get("ARENA_VOICE_SFX", "on").lower() != "off"
        self.your_move_on = os.environ.get("ARENA_VOICE_YOUR_MOVE", "on").lower() != "off"
        # Colour commentary (Ben, 2026-09-07: "it could say a thing during
        # opponents' turns some of the time"): the advisor's per-turn recap
        # arrives after every turn, the opponents' included. off | some | all;
        # "some" voices each recap with probability ARENA_VOICE_COLOR_P (0.5).
        self.color_mode = os.environ.get("ARENA_VOICE_COLOR", "some").lower()
        if self.color_mode not in ("off", "some", "all"):
            self.color_mode = "some"
        self.color_p = float(os.environ.get("ARENA_VOICE_COLOR_P", "0.5"))
        self.rng = random.Random()
        self.queue: list[dict] = []
        self.last_spoken_at = -1e9
        # Start at the END of the advisor's stream: a (re)started runner speaks
        # new lines only — replaying history re-said the last quip after the
        # 2026-09-07 mid-game restart. A brand-new game's file is empty anyway.
        self._adv_pos, self._adv_inode = 0, None
        try:
            st = (logs_dir / "advisor-0.jsonl").stat()
            self._adv_pos, self._adv_inode = st.st_size, st.st_ino
        except OSError:
            pass
        self.answered: set[int] = set()     # advisor request seqs the human already answered
        self.game_id = None
        self.seen_turn = None
        self.seen_active = None
        self.eliminated: set[int] = set()
        self.game_over_said = False
        self.started_said = False
        self.human_seat = 0

    # -- output
    def say(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            self.logs.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def record(self, event: str, **body) -> None:
        """voice-0.jsonl: {"event": spoke|dropped|skipped, "kind": <item kind>, …}."""
        try:
            with self._jsonl.open("a") as f:
                f.write(json.dumps({"ts": round(time.time(), 3), "event": event, **body}) + "\n")
        except OSError:
            pass

    # -- control
    def enabled(self) -> bool:
        """Voice is on unless control/voice.json mutes it OR the Advisor panel's
        pause toggle (control/advisor.json {"enabled": false}) is set — pausing
        the advisor silences EVERY line: advice, quips, colour, your-move, the
        elimination and game-over lines, the bleeps (Ben, 2026-09-08)."""
        try:
            if not bool(json.loads(self._control.read_text()).get("enabled", True)):
                return False
        except (OSError, ValueError):
            pass
        try:
            adv = self._control.parent / "advisor.json"
            if adv.exists() and not bool(json.loads(adv.read_text()).get("enabled", True)):
                return False
        except (OSError, ValueError):
            pass
        return True

    # -- queue
    def enqueue(self, kind: str, *, text: str = "", stock: str = "", seq: int | None = None, ttl: float = 25.0) -> None:
        item = {"kind": kind, "text": text, "stock": stock, "seq": seq, "prio": PRIORITY.get(kind, 9),
                "at": self.clock(), "expires": self.clock() + ttl}
        # one pending item per kind for the chatty kinds: newest wins
        if kind in ("advice", "your_move", "quip", "event", "color"):
            self.queue = [q for q in self.queue if q["kind"] != kind]
        self.queue.append(item)

    def next_item(self) -> dict | None:
        now = self.clock()
        live = []
        for q in self.queue:
            if q["expires"] < now:
                self.record("dropped", kind=q["kind"], why="expired", text=q["text"][:80], stock=q["stock"])
                continue
            if q["kind"] == "advice" and q["seq"] is not None and q["seq"] in self.answered:
                self.record("dropped", kind="advice", why="already answered", seq=q["seq"])
                continue
            live.append(q)
        self.queue = live
        if not live:
            return None
        live.sort(key=lambda q: (q["prio"], q["at"]))
        item = live[0]
        # the rate limit applies to everything but game start / game over
        if item["kind"] not in ("startup", "game_over", "human_out") and now - self.last_spoken_at < self.min_gap:
            return None
        self.queue.remove(item)
        return item

    def _play(self, path: Path) -> None:
        """Play through the configured player; a player that does not take the
        stop poll (test fakes, custom players) is called the old way."""
        try:
            self.player.play(path, should_stop=lambda: not self.enabled())
        except TypeError:
            self.player.play(path)

    def speak(self, item: dict) -> bool:
        path = None
        if item["stock"]:
            path = self.renderer.stock(item["stock"])
        elif item["text"]:
            path = self.renderer.render(item["text"])
        if path is None:
            self.record("skipped", kind=item["kind"], why="no audio (stock missing or live off)", text=item["text"][:80], stock=item["stock"])
            return False
        if self.sfx_on:
            bleep = self.renderer.sfx()
            if bleep is not None:
                self._play(bleep)
        self._play(path)
        self.last_spoken_at = self.clock()
        self.record("spoke", kind=item["kind"], text=item["text"][:200], stock=item["stock"], seconds=round(wav_seconds(path), 2),
                    chars_used=self.renderer.chars_used)
        self.say(f"[voice] {item['kind']}: {item['stock'] or item['text'][:90]}")
        return True

    # -- sources
    def scan_advisor(self) -> None:
        path = self.logs / "advisor-0.jsonl"
        try:
            st = path.stat()
        except OSError:
            return
        if self._adv_inode != st.st_ino or st.st_size < self._adv_pos:
            self._adv_inode, self._adv_pos = st.st_ino, 0     # new session file (arena-stop archived the old one)
        with path.open("rb") as f:
            f.seek(self._adv_pos)
            chunk = f.read()
            # only complete lines advance the cursor: a line caught mid-write
            # is re-read whole next scan instead of being lost (Gemini P1)
            cut = chunk.rfind(b"\n")
            if cut < 0:
                return
            chunk = chunk[:cut + 1]
            self._adv_pos += len(chunk)
        for raw in chunk.decode("utf-8", "replace").splitlines():
            try:
                r = json.loads(raw)
            except ValueError:
                continue
            k = r.get("kind")
            if k == "advice" and r.get("text"):
                self.enqueue("advice", text=first_sentence(r["text"]), seq=r.get("seq"), ttl=25.0)
            elif k == "ask" and r.get("answer"):
                self.enqueue("ask", text=first_sentence(r["answer"], ASK_MAX), ttl=60.0)
            elif k == "color" and r.get("text") and self.color_mode != "off":
                if self.color_mode == "all" or self.rng.random() < self.color_p:
                    self.enqueue("color", text=first_sentence(r["text"]), ttl=40.0)
                else:
                    self.record("skipped", kind="color", why="dice (ARENA_VOICE_COLOR=some)", text=r["text"][:80])
            elif k == "quip" and r.get("id"):
                self.enqueue("quip", stock=str(r["id"]), ttl=20.0)
            elif k == "chosen" and r.get("seq") is not None:
                self.answered.add(int(r["seq"]))

    def scan_observer(self) -> None:
        path = self.mailbox / "observer-state.json"
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        gid = d.get("gameId") or d.get("timestamp") and "live"
        if not self.started_said:
            self.started_said = True
            if (d.get("turn") or 0) <= 1 and not d.get("gameOver"):
                self.enqueue("startup", stock="startup", ttl=30.0)
            # a restart mid-game (supervisor, code reload) says nothing until the next event
        turn, active = d.get("turn"), d.get("activeSeat")
        seats = d.get("seats") or []
        for s in seats:
            if s.get("eliminated") and s.get("seat") not in self.eliminated:
                self.eliminated.add(s.get("seat"))
                if d.get("gameOver"):
                    continue  # the game-over pair covers the last elimination
                if s.get("seat") == self.human_seat:
                    # the human's own death (Ben, 2026-09-07): one line from the
                    # rotation, straight away, ahead of the rate limit
                    rotation = self.renderer.manifest.get("human_out") or ["winner-none"]
                    self.enqueue("human_out", stock=self.rng.choice(rotation), ttl=60.0)
                else:
                    self.enqueue("event", stock="player-eliminated", ttl=20.0)
        if self.your_move_on and turn is not None and (turn, active) != (self.seen_turn, self.seen_active):
            if active == self.human_seat and self.seen_turn is not None:
                self.enqueue("your_move", stock="your-move", ttl=12.0)
            self.seen_turn, self.seen_active = turn, active
        if d.get("gameOver") and not self.game_over_said:
            self.game_over_said = True
            human = next((s for s in seats if s.get("seat") == self.human_seat), None)
            won = human is not None and not human.get("eliminated")
            self.enqueue("game_over", stock="you-win" if won else "strange-game", ttl=120.0)
            # the sign-off follows as its own item so both play in order
            self.queue.append({"kind": "game_over", "text": "", "stock": "game-over-gg", "seq": None,
                               "prio": PRIORITY["game_over"], "at": self.clock() + 0.001, "expires": self.clock() + 120.0})

    # -- loop
    def step(self) -> None:
        if not self.enabled():
            if self.queue:
                self.say(f"[voice] disabled — dropping {len(self.queue)} queued line(s)")
                self.queue = []
            return
        self.scan_advisor()
        self.scan_observer()
        item = self.next_item()
        if item is not None:
            self.speak(item)

    def run(self) -> None:
        self.say(f"[voice] up — stock {len(self.renderer.manifest.get('phrases', {}))} phrases, "
                 f"live={'on' if self.renderer.live else 'off (no ELEVENLABS_API_KEY)'}, min_gap={self.min_gap}s, "
                 f"fx={self.renderer.fx_mode}, format={self.renderer.format}, glitch={self.renderer.glitch}, sfx={'on' if self.sfx_on else 'off'}, color={self.color_mode}")
        hb = self.mailbox / "seat-0-voice" / "heartbeat"
        hb.parent.mkdir(parents=True, exist_ok=True)

        def beat():
            while True:
                try:
                    hb.touch()
                except OSError:
                    pass
                time.sleep(5.0)
        threading.Thread(target=beat, name="voice-heartbeat", daemon=True).start()
        while True:
            try:
                self.step()
            except Exception as e:  # noqa: BLE001 — bookkeeping never ends the voice
                self.say(f"[voice] step error: {str(e)[:160]}")
            time.sleep(POLL_S)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=str(HERE / "logs"))
    ap.add_argument("--mailbox", default=str(ARENA / "mailbox"))
    ap.add_argument("--play", metavar="ID", help="play a stock phrase and exit")
    ap.add_argument("--say", metavar="TEXT", help="render (cache/live) and play one line, then exit")
    ap.add_argument("--mute", action="store_true")
    ap.add_argument("--unmute", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    vr = VoiceRunner(Path(a.logs), Path(a.mailbox), dry_run=a.dry_run)
    if a.mute or a.unmute:
        vr._control.parent.mkdir(parents=True, exist_ok=True)
        vr._control.write_text(json.dumps({"enabled": bool(a.unmute)}))
        print(f"[voice] {'unmuted' if a.unmute else 'muted'} ({vr._control})")
        return
    if a.play:
        vr.min_gap = 0
        ok = vr.speak({"kind": "quip", "text": "", "stock": a.play, "seq": None})
        sys.exit(0 if ok else 1)
    if a.say:
        vr.min_gap = 0
        ok = vr.speak({"kind": "ask", "text": a.say, "stock": "", "seq": None})
        sys.exit(0 if ok else 1)
    vr.run()


if __name__ == "__main__":
    main()
