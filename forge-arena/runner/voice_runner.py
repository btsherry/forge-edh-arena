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
sys.path.insert(0, str(HERE))
from chains import ChainTable, plan_reply  # noqa: E402
ARENA = HERE.parent
STOCK = HERE / "voice" / "stock"
VOICES_DIR = STOCK / "voices"               # seat-bark libraries: voices/<name>/manifest.json + <id>[-N].wav
DEFAULT_VOICE_ID = ""                        # resolved from stock/manifest.json ("voice_id") unless ARENA_VOICE_ID is set
POLL_S = 0.5
CHAIN_POLL_S = 0.1          # while an exchange hop is pending: a retort's beat is ~0.5 s, so poll fast
FIRST_SENTENCE_MAX = 220
ASK_MAX = 300
PRIORITY = {"game_over": 0, "human_out": 0, "startup": 1, "ask": 2, "advice": 3, "quip": 4, "event": 5, "color": 6, "your_move": 7, "bark": 8}
# A reply inside an exchange must not be separated from the line it answers: game 44
# (20:43) Joshua's "your move" cut between Harry's jab and Lily's "shut it", so the
# retort landed on Joshua. Hops rank just below advice; if advice or a question
# does interrupt, the pending hop is dropped rather than played orphaned.
CHAIN_HOP_PRIORITY = 3.5
# An AI seat's elimination is voiced ONCE: by the dying seat itself (its `eliminated`
# bark, at once) with this probability, else by Joshua's "A player has been eliminated."
ELIM_SEAT_P = 0.7
RECENT_S = 240.0          # a line said within this window is stale for the patter pick and for replies
RECENT_WEIGHT = 0.15      # its patter weight is multiplied by this
# Seat barks, the table-talk design (Ben, 2026-09-10 — "playing with the AI should
# feel like sitting at the table with people"): every turn boundary has ONE owner.
# The recap of an AI seat's turn belongs to that seat (its retrospective line,
# authored by the advisor, rolled at ARENA_BARKS_P); the recap of the human's turn
# belongs to Joshua's colour line (its own dice) plus, optionally, one seat's
# reaction. Instant reactions come from the snapshot's public event ring — an
# attack of ARENA_BARKS_SWING power, a hit of ARENA_BARKS_HIT, a countered spell —
# with no LLM in the loop. Openers ("my turn") fire mechanically at a seat's turn
# start, rarely. A (seat, line) already said this turn is never said again.


CHATTER_LEVELS = {"quiet": 0.5, "normal": 1.0, "lively": 1.5, "rowdy": 2.0}


def chatter_level(raw: str | None) -> float:
    """ARENA_CHATTER — one master dial for how much the table talks (Ben,
    2026-09-10: "instead of trying to bake all of this just right anecdotally").
    A name (quiet .5 / normal 1 / lively 1.5 / rowdy 2) or a number; 1 = the
    knobs as written. Every frequency knob is multiplied by it (capped at 1),
    the gap between lines divided by it (floor 3 s), the instant-reaction
    thresholds divided by it (floors 3 power / 4 damage). Advice frequency —
    model calls — is not chatter and is untouched."""
    v = (raw or "normal").strip().lower()
    if v in CHATTER_LEVELS:
        return CHATTER_LEVELS[v]
    try:
        return max(0.0, min(4.0, float(v)))
    except ValueError:
        return 1.0


def load_libraries(voices_dir: Path | None = None) -> dict[str, dict]:
    """{library: {"library", "voice", "temperament", "seat"}} from every
    voices/<name>/manifest.json; `seat` is the library's default seat."""
    out: dict[str, dict] = {}
    d = voices_dir or VOICES_DIR
    try:
        mans = sorted(d.glob("*/manifest.json"))
    except OSError:
        return out
    for mp in mans:
        try:
            m = json.loads(mp.read_text())
            seat = int(m["seat"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out[mp.parent.name] = {"library": mp.parent.name, "voice": str(m.get("voice_name", mp.parent.name)).split(" - ")[0],
                               "temperament": str(m.get("temperament", "")), "seat": seat}
    return out


def load_assignments(voices_dir: Path | None = None) -> dict[str, str]:
    """voices/assign.json by_deck: deck slug -> library (Ben's associations)."""
    try:
        return dict((json.loads(((voices_dir or VOICES_DIR) / "assign.json").read_text()).get("by_deck") or {}))
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def assign_voices(libraries: dict[str, dict], seat_decks: dict[int, str] | None, by_deck: dict[str, str] | None) -> dict[int, dict]:
    """{seat: library info}. A seat whose deck is in by_deck gets that library
    (lower seat wins a clash); every other seat takes a free library in seat
    order — the library's default seat first, then whatever is left. With no
    seat->deck knowledge every library sits at its default seat."""
    if not libraries:
        return {}
    seat_decks = seat_decks or {}
    by_deck = by_deck or {}
    out: dict[int, dict] = {}
    used: set[str] = set()
    for seat in sorted(seat_decks):
        lib = by_deck.get(seat_decks[seat])
        if lib in libraries and lib not in used:
            out[seat] = libraries[lib]; used.add(lib)
    defaults = {info["seat"]: name for name, info in libraries.items()}
    seats = sorted(set(seat_decks) | set(defaults))
    for seat in seats:
        if seat in out:
            continue
        lib = defaults.get(seat)
        if lib is None or lib in used:
            free = [n for n in sorted(libraries, key=lambda n: libraries[n]["seat"]) if n not in used]
            lib = free[0] if free else None
        if lib is not None:
            out[seat] = libraries[lib]; used.add(lib)
    return out


def load_seat_libraries(voices_dir: Path | None = None, seat_decks: dict[int, str] | None = None) -> dict[int, dict]:
    """{seat: {"library", "voice", "temperament", "seat"}} — the voices at the table,
    by deck when the table is known (voices/assign.json), by default seat otherwise.
    Missing dir -> {} (barks silently off)."""
    return assign_voices(load_libraries(voices_dir), seat_decks, load_assignments(voices_dir))


DEFAULT_TABLE = "urza-lord-high-artificer giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds"


def seat_decks_from_roster(human_deck: str | None, roster: str | None) -> dict[int, str]:
    """{1..3: deck} the way GuiPilotMatch/run_table.sh/the advisor seat a human
    table: the roster minus the human's deck, in roster order, first three.
    Empty when the human deck is unknown (an all-AI table, or an old launcher)."""
    if not human_deck:
        return {}
    slugs = (roster or "").split() or DEFAULT_TABLE.split()
    return {i + 1: d for i, d in enumerate([d for d in slugs if d != human_deck][:3])}


def seat_decks_from_game_log(game_log: Path) -> dict[int, str]:
    """{seat: deck slug} from the runners' shared game log (each record carries
    seat + deck); empty until the first decisions land."""
    out: dict[int, str] = {}
    try:
        with game_log.open("rb") as f:
            for raw in f:
                try:
                    r = json.loads(raw)
                except ValueError:
                    continue
                if r.get("seat") is not None and r.get("deck"):
                    out.setdefault(int(r["seat"]), str(r["deck"]))
                if len(out) >= 4:
                    break
    except OSError:
        pass
    return out


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
        self.rng = random.Random()
        self.renderer = Renderer(logs_dir / "cache" / "voice", log=self.say, fake_tts=fake_tts,
                                 record=self.record, clock=clock, rng=self.rng)
        self.player = player or Player(dry_run=dry_run, log=self.say)
        self.chatter = chatter_level(os.environ.get("ARENA_CHATTER", "normal"))
        self.min_gap = float(os.environ.get("ARENA_VOICE_MIN_GAP", "8"))
        self.sfx_on = os.environ.get("ARENA_VOICE_SFX", "on").lower() != "off"
        # "Your move" (Ben, 2026-09-10: "cool the first time, okay the second, lame
        # every time after"): on = every turn | some = about YOUR_MOVE_P of turns |
        # off; the wordings come from a shuffle bag either way.
        self.your_move_mode = os.environ.get("ARENA_VOICE_YOUR_MOVE", "some").lower()
        if self.your_move_mode not in ("on", "some", "off"):
            self.your_move_mode = "some"
        self.your_move_p = float(os.environ.get("ARENA_VOICE_YOUR_MOVE_P", "0.6"))
        # Seat barks (2026-09-10): the advisor tags [bark:<seat>:<id>] on its
        # replies; the seat's static voice (voices/<lib>/) says its own wording.
        # Advisor off or muted => nothing (both already silence this runner).
        self.barks_mode = os.environ.get("ARENA_BARKS", "some").lower()
        if self.barks_mode not in ("off", "some", "all"):
            self.barks_mode = "some"
        self.barks_p = float(os.environ.get("ARENA_BARKS_P", "0.85"))
        self.barks_cooldown = float(os.environ.get("ARENA_BARKS_COOLDOWN", "10"))
        self.barks_opener_p = float(os.environ.get("ARENA_BARKS_OPENER_P", "0.35"))
        self.barks_swing = int(os.environ.get("ARENA_BARKS_SWING", "6"))
        self.barks_hit = int(os.environ.get("ARENA_BARKS_HIT", "8"))
        self._said_this_turn: set[tuple[int, str]] = set()
        self._said_turn = None
        # Recency (game 44: "cards in hand" ten times in sixteen minutes, "good hand"
        # seven): a line said in the last RECENT_S is a weak candidate for anyone,
        # and a seat avoids a reply it used recently. The per-turn rule stays hard.
        self._said_at: dict[str, float] = {}                 # line id -> last time it was spoken (any seat)
        self._seat_said_at: dict[tuple[int, str], float] = {}
        self._event_seq = None      # last snapshot event seq consumed; None until the first read
        # The patter clock (Ben, 2026-09-10: "someone should say something every 5-7
        # seconds"): when the queue is empty and nothing has played for a randomized
        # gap, the runner itself picks a speaker and a line from what the board says
        # (a slow seat, the leader, a low seat, a big hand, a big board) or filler.
        # Five Game Knights episodes measured ~190 words/min with a silence over 4 s
        # only every ~78 s. Quieter on the human's turn; never over the advisor.
        self.patter_on = os.environ.get("ARENA_VOICE_PATTER", "on").lower() != "off"
        lo, _, hi = os.environ.get("ARENA_VOICE_PATTER_GAP", "5-7").partition("-")
        try:
            self.patter_gap = (float(lo), float(hi or lo))
        except ValueError:
            self.patter_gap = (5.0, 7.0)
        self.patter_human = float(os.environ.get("ARENA_VOICE_PATTER_HUMAN", "0.33"))     # rate on the human's turn
        self.patter_after_advice = float(os.environ.get("ARENA_VOICE_PATTER_AFTER_ADVICE", "6"))
        self.barks_slow = float(os.environ.get("ARENA_BARKS_SLOW", "20"))                  # a seat thinking this long gets told
        self.barks_mana = int(os.environ.get("ARENA_BARKS_MANA", "8"))                       # floating this much is "big mana"
        self._last_hit_by: dict[int, tuple[list[int], object]] = {}   # seat -> (hitters, turn) from the ring: kill attribution
        self._casts: dict[int, list[float]] = {}                      # seat -> recent cast times (a flurry earns "play slower")
        self._pool_high: set[int] = set()                             # seats currently over the big-mana line
        self._patter_anchor = None
        self._patter_due = 0.0
        self._advisor_spoke_at = -1e9
        # interaction chains (Ben, 2026-09-10): a spoken line invites replies; see chains.py
        self.chains = ChainTable.load(VOICES_DIR)
        self._chain: dict | None = None      # {"origin": seat, "hop": n, "turn": t} while an exchange is running
        self._last_snapshot: dict = {}
        # the table: from the launcher at startup (ARENA_HUMAN_DECK + the roster), else
        # default seats until the game log names all three AI decks
        self._seat_decks: dict[int, str] = seat_decks_from_roster(os.environ.get("ARENA_HUMAN_DECK"), os.environ.get("ARENA_SEAT_DECKS", ""))
        self.seat_libraries = load_seat_libraries(seat_decks=self._seat_decks or None)
        self._bark_spoken_at: dict[int, float] = {}
        # Colour commentary (Ben, 2026-09-07: "it could say a thing during
        # opponents' turns some of the time"): the advisor's per-turn recap
        # arrives after every turn, the opponents' included. off | some | all;
        # "some" voices each recap with probability ARENA_VOICE_COLOR_P (0.5).
        self.color_mode = os.environ.get("ARENA_VOICE_COLOR", "some").lower()
        if self.color_mode not in ("off", "some", "all"):
            self.color_mode = "some"
        self.color_p = float(os.environ.get("ARENA_VOICE_COLOR_P", "0.5"))
        self.apply_chatter()
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
        self._state_published = None
        self._live_published = None

    def apply_chatter(self) -> None:
        """Scale the frequency knobs by the chatter dial (see chatter_level)."""
        k = self.chatter
        if k == 1.0:
            return
        scale = lambda p: min(1.0, p * k)   # noqa: E731
        self.barks_p, self.barks_opener_p = scale(self.barks_p), scale(self.barks_opener_p)
        self.color_p, self.your_move_p = scale(self.color_p), scale(self.your_move_p)
        if self.chains is not None:
            self.chains.first_hop_p = scale(self.chains.first_hop_p)
        if k > 0:
            self.min_gap = max(3.0, self.min_gap / k)
            self.barks_swing = max(3, round(self.barks_swing / k))
            self.barks_hit = max(4, round(self.barks_hit / k))
            self.patter_gap = (max(2.0, self.patter_gap[0] / k), max(2.5, self.patter_gap[1] / k))
            self.barks_cooldown = max(3.0, self.barks_cooldown / k)   # game 44: the 10 s guard silenced 15 barks at rowdy
        if k >= 1.5 and self.chains is not None:
            self.chains.max_hops += 1           # a livelier table talks back one more time

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

    def executive_on(self) -> bool:
        """control/executive.json {"on": true}: the advisor is playing the
        human's seat, so "Your move." would be addressed to nobody."""
        try:
            return bool(json.loads((self._control.parent / "executive.json").read_text()).get("on", False))
        except (OSError, ValueError):
            return False

    # -- queue
    def enqueue(self, kind: str, *, text: str = "", stock: str = "", seq: int | None = None, ttl: float = 25.0,
                library: str = "", seat: int | None = None, ctx: dict | None = None, gap: float | None = None,
                chain: dict | None = None) -> None:
        item = {"kind": kind, "text": text, "stock": stock, "seq": seq,
                "prio": CHAIN_HOP_PRIORITY if chain else PRIORITY.get(kind, 9),
                "at": self.clock(), "expires": self.clock() + ttl, "library": library, "seat": seat,
                "ctx": ctx or {}, "gap": gap, "chain": chain}
        # one pending item per kind for the chatty kinds: newest wins
        if kind in ("advice", "your_move", "quip", "event", "color", "bark"):
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
        if item["kind"] in ("advice", "ask") and any(q.get("chain") for q in live[1:]):
            for q in [q for q in live[1:] if q.get("chain")]:
                self.record("dropped", kind=q["kind"], why="exchange interrupted by the advisor", stock=q["stock"], seat=q.get("seat"))
            live = [q for q in live if not q.get("chain")]
            self.queue = live
        # the rate limit applies to everything but game start / game over; a chain
        # hop brings its own shorter, conversational gap
        gap = item.get("gap") or self.min_gap
        if item["kind"] not in ("startup", "game_over", "human_out") and now - self.last_spoken_at < gap:
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
            path = self.renderer.stock(item["stock"], item.get("library") or "")
        elif item["text"]:
            path = self.renderer.render(item["text"])
        if path is None:
            self.record("skipped", kind=item["kind"], why="no audio (stock missing or live off)", text=item["text"][:80], stock=item["stock"])
            return False
        # the typing bleeps belong to the mainframe: never before a seat's own voice (Ben, 2026-09-10)
        if self.sfx_on and not item.get("library"):
            bleep = self.renderer.sfx()
            if bleep is not None:
                self._play(bleep)
        self.publish_speaking(item, wav_seconds(path))
        self._play(path)
        self.publish_speaking(None, 0.0)
        self.last_spoken_at = self.clock()
        if item["kind"] in ("advice", "ask"):
            self._advisor_spoke_at = self.clock()
        if item.get("seat") is not None and item.get("library"):
            self._bark_spoken_at[int(item["seat"])] = self.clock()
            self._said_at[item["stock"]] = self.clock()
            self._seat_said_at[(int(item["seat"]), item["stock"])] = self.clock()
        self.record("spoke", kind=item["kind"], text=item["text"][:200], stock=item["stock"], seconds=round(wav_seconds(path), 2),
                    chars_used=self.renderer.chars_used, library=item.get("library") or "", seat=item.get("seat"),
                    file=path.name)
        who = f" seat {item['seat']} ({item['library']})" if item.get("library") else ""
        hop = f" (chain hop {item['chain']['hop']})" if item.get("chain") else ""
        self.say(f"[voice] {item['kind']}{who}{hop}: {item['stock'] or item['text'][:90]}" + (f" [{path.name}]" if item["stock"] and path.name != f"{item['stock']}.wav" else ""))
        self.after_spoken(item)
        return True

    # -- interaction chains
    def leader_of(self, speaker: int):
        """The highest-life seat still in the game, other than the speaker and the human."""
        best, best_life = None, -1
        for s in self._last_snapshot.get("seats") or []:
            sid = s.get("seat")
            if sid is None or sid == speaker or sid == self.human_seat or s.get("eliminated"):
                continue
            if (s.get("life") or 0) > best_life:
                best, best_life = int(sid), s.get("life") or 0
        return best

    def after_spoken(self, item: dict) -> None:
        """A seat's line may invite a reply (chains.py). One reply at most, rolled
        here so the outcome is recorded; a chain dies when the turn changes."""
        if self.chains is None or self.barks_mode == "off":
            return
        if item.get("seat") is None or not item.get("library"):
            return                                       # Joshua spoke: the seats ignore him
        turn = self._said_turn
        chain = item.get("chain") if item.get("chain") and item["chain"].get("turn") == turn else None
        voiced = {int(k): v["library"] for k, v in self.seat_libraries.items() if int(k) not in self.eliminated}
        now = self.clock()
        recent = {k for k, t in self._seat_said_at.items() if now - t < RECENT_S}
        plan = plan_reply(self.chains, item, chain, voiced, self.human_seat, self.leader_of, self._said_this_turn, self.rng, turn, recent)
        if plan is None:
            self._chain = None
            return
        if self.rng.random() >= plan["p"]:
            self.record("skipped", kind="bark", why=f"dice (chain hop {plan['hop']}, p={plan['p']:.2f})", stock=plan["id"],
                        seat=plan["seat"], source="chain")
            self._chain = None
            return
        link = {"origin": plan["origin"], "hop": plan["hop"], "turn": turn, "parent": item.get("stock")}
        if plan["seat"] == "joshua":
            self.enqueue("quip", stock=plan["id"], ttl=15.0, gap=self.chains.gap_s)
            self.record("queued", kind="quip", stock=plan["id"], source="chain", hop=plan["hop"], parent=item.get("stock"))
            self._chain = None                           # nobody answers Joshua
            return
        seat = int(plan["seat"])
        self._said_this_turn.add((seat, plan["id"]))
        self.enqueue("bark", stock=plan["id"], library=voiced[seat], seat=seat, ttl=15.0, gap=self.chains.gap_s,
                     ctx={"targets": [int(item["seat"])], "aggressor": int(item["seat"])}, chain=link)
        self.record("queued", kind="bark", stock=plan["id"], seat=seat, source="chain", hop=plan["hop"], parent=item.get("stock"))
        self._chain = link

    # -- seat barks
    def learn_table(self) -> None:
        """Once the game log names the decks at the table, re-seat the voices by
        deck (Ben, 2026-09-10: Purphoros fiery, Urza cool, Giada warm)."""
        if getattr(self, "_table_confirmed", False):
            return
        decks = seat_decks_from_game_log(self.logs / "game.jsonl")
        ai = {k: v for k, v in decks.items() if k != self.human_seat}
        if len(ai) >= 3:                                      # the whole table: confirm, or correct the launcher's roster
            self._table_confirmed = True
            if ai != self._seat_decks:
                self._seat_decks = ai
                self.seat_libraries = load_seat_libraries(seat_decks=ai)
            self.say("[voice] table: " + ", ".join(f"seat {k} {ai.get(k, '?')} -> {v['voice']}" for k, v in sorted(self.seat_libraries.items())))

    def library_for_seat(self, seat: int) -> str:
        info = self.seat_libraries.get(int(seat))
        return info["library"] if info else ""

    def maybe_bark(self, seat: int, pid: str, turn=None, source: str = "advice", p: float | None = None, ctx: dict | None = None) -> bool:
        """A bark for an AI seat — from the advisor's recap ("recap"), an advice
        window ("advice"), a snapshot event ("event") or a turn start ("opener") —
        subject to the knob, the per-turn no-repeat rule, the short per-seat
        guard and one roll of the dice. Records why when it does not play."""
        if self.barks_mode == "off":
            self.record("skipped", kind="bark", why="barks off (ARENA_BARKS=off)", stock=pid, seat=seat, source=source)
            return False
        lib = self.library_for_seat(seat)
        if not lib:
            self.record("skipped", kind="bark", why=f"no voice library for seat {seat}", stock=pid, seat=seat, source=source)
            return False
        if int(seat) in self.eliminated:
            # Ben (2026-09-10): dead players should not talk — the exit line was their last
            self.record("skipped", kind="bark", why="eliminated", stock=pid, seat=seat, source=source)
            return False
        self._roll_turn(turn)
        if (int(seat), pid) in self._said_this_turn:
            self.record("skipped", kind="bark", why="already said this turn", stock=pid, seat=seat, source=source)
            return False
        since = self.clock() - self._bark_spoken_at.get(int(seat), -1e9)
        if since < self.barks_cooldown:
            self.record("skipped", kind="bark", why=f"seat guard ({since:.0f}s < {self.barks_cooldown:.0f}s)", stock=pid, seat=seat, source=source)
            return False
        # an explicit p (the opener's own knob) always applies; otherwise "all" means always, "some" means ARENA_BARKS_P
        chance = p if p is not None else (1.0 if self.barks_mode == "all" else self.barks_p)
        if self.rng.random() >= chance:
            self.record("skipped", kind="bark", why=f"dice ({source}, p={chance:.2f})", stock=pid, seat=seat, source=source)
            return False
        self._said_this_turn.add((int(seat), pid))
        self.enqueue("bark", stock=pid, library=lib, seat=int(seat), ttl=20.0, ctx=ctx)
        self.record("queued", kind="bark", stock=pid, seat=seat, source=source)
        return True

    def _roll_turn(self, turn) -> None:
        """The no-repeat set is per game turn."""
        if turn is not None and turn != self._said_turn:
            self._said_turn = turn
            self._said_this_turn = set()
            self._chain = None                           # a new turn ends any exchange

    # -- colour: Joshua speaks after the human's turn
    def _voice_color(self, r: dict) -> None:
        """Joshua's colour line. A recap of an AI seat's turn belongs to that seat
        (the advisor stamps `owner`); the human's turn is Joshua's, under his dice."""
        owner = r.get("owner")
        if self.barks_mode != "off" and owner is not None and int(owner) != self.human_seat and self.library_for_seat(int(owner)):
            self.record("skipped", kind="color", why=f"seat {owner}'s turn — the seat speaks", text=r["text"][:80], seq=r.get("seq"))
            return
        if self.color_mode == "all" or self.rng.random() < self.color_p:
            self.enqueue("color", text=first_sentence(r["text"]), ttl=40.0)
        else:
            self.record("skipped", kind="color", why="dice (ARENA_VOICE_COLOR=some)", text=r["text"][:80])

    # -- the patter clock
    def _patter_gap_s(self, human_turn: bool) -> float:
        g = self.rng.uniform(*self.patter_gap)
        return g / self.patter_human if human_turn and self.patter_human > 0 else g

    def slow_seats(self) -> list[int]:
        """AI seats with a decision pending in their mailbox longer than ARENA_BARKS_SLOW."""
        out = []
        now = time.time()
        for seat in self.seat_libraries:
            if int(seat) in self.eliminated:
                continue
            try:
                inbox = self.mailbox / f"seat-{seat}" / "inbox"
                ages = [now - f.stat().st_mtime for f in inbox.glob("req-*.json")]
            except OSError:
                ages = []
            if ages and max(ages) >= self.barks_slow:
                out.append(int(seat))
        return out

    def patter_candidates(self, snap: dict, living: list[int]) -> list[tuple[int, str, int | None, float]]:
        """(speaker, line, target, weight) — what the board gives the table to talk
        about. Board lines are addressed to a target (the human included, as a
        target only); filler is always available at low weight."""
        seats = [x for x in (snap.get("seats") or []) if isinstance(x, dict) and not x.get("eliminated")]
        by_id = {int(x["seat"]): x for x in seats if x.get("seat") is not None}
        active = snap.get("activeSeat")
        out: list[tuple[int, str, int | None, float]] = []

        def others(target):
            return [sp for sp in living if sp != target]

        def add(pid, target, w, speakers=None):
            for sp in (speakers if speakers is not None else others(target)):
                out.append((sp, pid, target, w / max(1, len(speakers if speakers is not None else others(target)))))

        for slow in self.slow_seats():
            add("play-faster", slow, 3.0); add("thinking-hard", slow, 1.0)
        if len(by_id) >= 2:
            lead = max(by_id.values(), key=lambda x: x.get("life") or 0)
            if [x for x in by_id.values() if (x.get("life") or 0) == (lead.get("life") or 0)] == [lead]:
                add("youre-the-threat", int(lead["seat"]), 2.0); add("whats-your-life", int(lead["seat"]), 1.0)
        for sid, x in by_id.items():
            life, hand = x.get("life") or 0, x.get("handSize") or 0
            if 0 < life <= 10:
                add("low-life-jab", sid, 2.0); add("whats-your-life", sid, 1.0)
            if hand >= 6:
                add("cards-in-hand", sid, 2.0)
            if hand <= 1 and sid != active:
                add("empty-hand", sid, 1.0)
            creatures = [c for c in (x.get("battlefield") or []) if isinstance(c, dict) and c.get("power") is not None]
            if any((c.get("power") or 0) >= 6 for c in creatures):
                add("kill-that", sid, 2.0)
        boards = {sid: sum(1 for c in (x.get("battlefield") or []) if isinstance(c, dict) and c.get("power") is not None) for sid, x in by_id.items()}
        if boards:
            big = max(boards, key=boards.get)
            if boards[big] >= 3 and list(boards.values()).count(boards[big]) == 1:
                add("board-envy", big, 1.0)
        # filler, always (a bluff about one's hand is rarer than the rest — game 44)
        for sp in living:
            out.append((sp, "nothing-happening", None, 1.0 / len(living)))
            out.append((sp, "this-is-fine", None, 1.0 / len(living)))
            out.append((sp, "good-hand", None, 0.3 / len(living)))
            out.append((sp, "what-turn", None, 0.4 / len(living)))
            tgt = [t for t in living if t != sp]
            if tgt:
                out.append((sp, "deal", self.rng.choice(tgt), 0.8 / len(living)))
        if active is not None and int(active) in living:
            add("pass-already", int(active), 0.8)
        now = self.clock()
        return [(sp, pid, tgt, w * (RECENT_WEIGHT if now - self._said_at.get(pid, -1e9) < RECENT_S else 1.0))
                for sp, pid, tgt, w in out]

    def patter(self) -> None:
        if not self.patter_on or self.barks_mode == "off" or self.queue:
            return
        now = self.clock()
        snap = self._last_snapshot
        human_turn = snap.get("activeSeat") == self.human_seat
        if self._patter_anchor != self.last_spoken_at:          # a line just played: rearm from its end
            self._patter_anchor = self.last_spoken_at
            self._patter_due = self.last_spoken_at + self._patter_gap_s(human_turn)
        if now < self._patter_due or now - self._advisor_spoke_at < self.patter_after_advice:
            return
        living = [int(x) for x in self.seat_libraries if int(x) not in self.eliminated]
        cands = self.patter_candidates(snap, living) if living and snap.get("seats") else []
        self._patter_due = now + self._patter_gap_s(human_turn)   # whatever happens, wait another gap
        if not cands:
            return
        total = sum(w for *_, w in cands)
        pick = self.rng.random() * total
        for speaker, pid, target, w in cands:
            pick -= w
            if pick <= 0:
                break
        self.maybe_bark(speaker, pid, turn=snap.get("turn"), source="patter",
                        ctx={"targets": [target] if target is not None else []})

    # -- instant reactions from the snapshot's public event ring
    def scan_events(self, d: dict) -> None:
        events = d.get("events") or []
        if self._event_seq is None:
            # first read (fresh start or restart): never replay history
            self._event_seq = max((int(e.get("seq", 0)) for e in events), default=0)
            return
        for e in events:
            try:
                seq = int(e.get("seq", 0))
            except (TypeError, ValueError):
                continue
            if seq <= self._event_seq:
                continue
            self._event_seq = seq
            if self.barks_mode == "off":
                continue
            kind, turn = e.get("kind"), e.get("turn")
            try:
                if kind == "attack":
                    seat = int(e.get("seat"))
                    if seat != self.human_seat and (int(e.get("power", 0)) >= self.barks_swing or int(e.get("attackers", 0)) >= 3):
                        self.maybe_bark(seat, "big-swing", turn=turn, source="event",
                                        ctx={"targets": [int(x) for x in (e.get("defenders") or [])], "aggressor": None})
                elif kind == "damage":
                    victim = int(e.get("seat"))
                    froms = [int(x) for x in (e.get("from") or [])]
                    if froms:
                        self._last_hit_by[victim] = (froms, turn)
                    if int(e.get("amount", 0)) < self.barks_hit:
                        continue
                    if victim != self.human_seat:
                        self.maybe_bark(victim, "that-hurt", turn=turn, source="event",
                                        ctx={"targets": [], "aggressor": froms[0] if froms else None, "human_cause": self.human_seat in froms})
                    else:
                        hitters = [x for x in froms if x != self.human_seat and self.library_for_seat(x)]
                        if hitters:
                            self.maybe_bark(hitters[0], "landed-hit", turn=turn, source="event",
                                            ctx={"targets": [self.human_seat], "aggressor": None})
                elif kind == "cast":
                    seat = int(e.get("seat"))
                    if seat != self.human_seat and self.library_for_seat(seat):
                        if e.get("commander"):
                            self.maybe_bark(seat, "commander-cast", turn=turn, source="event", ctx={"targets": []})
                        elif int(e.get("cmc", 0)) >= 5:
                            # a big spell draws a bystander's reaction: wow at seven-plus, else admiration / read that / oh no
                            by = [x for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
                            if by:
                                line = "wow" if int(e.get("cmc", 0)) >= 7 else self.rng.choice(["nice-play", "read-that", "oh-no"])
                                self.maybe_bark(int(self.rng.choice(by)), line, turn=turn, source="event", ctx={"targets": [seat]})
                    # a flurry — three spells inside thirty seconds — earns "slow down" from someone else
                    now_t = time.time()
                    recent = [t for t in self._casts.get(seat, []) if now_t - t < 30] + [now_t]
                    self._casts[seat] = recent
                    if len(recent) >= 3 and seat != self.human_seat:
                        by = [x for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
                        if by:
                            self.maybe_bark(int(self.rng.choice(by)), "play-slower", turn=turn, source="event", ctx={"targets": [seat]})
                elif kind == "left":
                    by = e.get("by"); owners = [int(x) for x in (e.get("seats") or [])]
                    n, tokens = int(e.get("n", 0)), int(e.get("tokens", 0))
                    commanders = e.get("commanders") or []
                    ai_owners = [o for o in owners if o != self.human_seat and self.library_for_seat(o)]
                    if n >= 3 and len(set(owners)) >= 2:
                        if by is not None and int(by) != self.human_seat and self.library_for_seat(int(by)):
                            self.maybe_bark(int(by), "sweep", turn=turn, source="event", ctx={"targets": [o for o in owners if o != int(by)]})
                        for o in ai_owners:
                            if by is None or o != int(by):
                                self.maybe_bark(o, "got-swept", turn=turn, source="event",
                                                ctx={"aggressor": int(by) if by is not None else None, "human_cause": by is not None and int(by) == self.human_seat})
                    elif commanders:
                        for o in ai_owners:
                            self.maybe_bark(o, "lost-commander", turn=turn, source="event",
                                            ctx={"aggressor": int(by) if by is not None and int(by) != o else None,
                                                 "human_cause": by is not None and int(by) == self.human_seat})
                    elif by is not None and n > tokens and all(int(by) != o for o in owners):
                        if int(by) != self.human_seat and self.library_for_seat(int(by)):
                            self.maybe_bark(int(by), "removal", turn=turn, source="event", ctx={"targets": owners})
                elif kind == "gameover":
                    w = e.get("winner")
                    if w is not None and int(w) != self.human_seat and self.library_for_seat(int(w)):
                        self.maybe_bark(int(w), "win", turn=turn, source="event", ctx={"targets": []})
                elif kind == "countered":
                    by, victim = e.get("by"), e.get("seat")
                    if by is not None and int(by) != self.human_seat and self.library_for_seat(int(by)):
                        self.maybe_bark(int(by), "counter", turn=turn, source="event",
                                        ctx={"targets": [int(victim)] if victim is not None else [], "aggressor": None})
                    elif victim is not None and int(victim) != self.human_seat:
                        self.maybe_bark(int(victim), "got-countered", turn=turn, source="event",
                                        ctx={"targets": [], "aggressor": int(by) if by is not None else None,
                                             "human_cause": by is not None and int(by) == self.human_seat})
            except (TypeError, ValueError):
                continue

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
                self._voice_color(r)
            elif k == "quip" and r.get("id"):
                self.enqueue("quip", stock=str(r["id"]), ttl=20.0)
            elif k == "bark" and r.get("id") and r.get("seat") is not None:
                try:
                    seat, pid = int(r["seat"]), str(r["id"])
                except (TypeError, ValueError):
                    continue
                self.maybe_bark(seat, pid, turn=r.get("turn"), source="recap" if r.get("with") == "color" else "advice")
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
        self._last_snapshot = d
        self.scan_events(d)
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
                    # one line, at once: the dying seat's own exit bark (ELIM_SEAT_P) or Joshua's
                    lib = self.library_for_seat(s.get("seat")) if self.barks_mode != "off" else ""
                    if lib and self.rng.random() < ELIM_SEAT_P:
                        self.enqueue("event", stock="eliminated", library=lib, seat=int(s.get("seat")), ttl=20.0, ctx={"targets": []})
                    else:
                        self.enqueue("event", stock="player-eliminated", ttl=20.0)
                    # who finished them? the last seat to hit them this turn gets the kill line
                    hit = self._last_hit_by.get(int(s.get("seat")))
                    if hit and hit[1] == turn:
                        killers = [h for h in hit[0] if h != self.human_seat and self.library_for_seat(h) and h not in self.eliminated]
                        if killers:
                            self.maybe_bark(killers[-1], "kill", turn=turn, source="event", ctx={"targets": []})
        for s in seats:
            sid, pool = s.get("seat"), s.get("pool") or 0
            if sid is None or sid == self.human_seat:
                continue
            if pool >= self.barks_mana and sid not in self._pool_high:
                self._pool_high.add(sid)
                if self.library_for_seat(sid):
                    self.maybe_bark(int(sid), "big-mana", turn=turn, source="event", ctx={"targets": []})
            elif pool < self.barks_mana:
                self._pool_high.discard(sid)
        if turn is not None and (turn, active) != (self.seen_turn, self.seen_active):
            if active == self.human_seat and self.your_move_mode != "off" and self.seen_turn is not None and not self.executive_on():
                if self.your_move_mode == "on" or self.rng.random() < self.your_move_p:
                    self.enqueue("your_move", stock="your-move", ttl=12.0)   # not while the advisor plays the seat
                else:
                    self.record("skipped", kind="your_move", why="dice (ARENA_VOICE_YOUR_MOVE=some)", stock="your-move")
            elif (active is not None and active != self.human_seat and self.seen_turn is not None
                  and self.barks_opener_p > 0 and self.barks_mode != "off"):
                # option A: an opener at a seat's turn start — rare, like a person who sometimes says "right, me"
                self.maybe_bark(int(active), "my-turn", turn=turn, source="opener", p=self.barks_opener_p)
            self.seen_turn, self.seen_active = turn, active
        if d.get("gameOver") and not self.game_over_said:
            self.game_over_said = True
            human = next((s for s in seats if s.get("seat") == self.human_seat), None)
            won = human is not None and not human.get("eliminated")
            self.enqueue("game_over", stock="you-win" if won else "strange-game", ttl=120.0)
            # the sign-off follows as its own item so both play in order
            self.queue.append({"kind": "game_over", "text": "", "stock": "game-over-gg", "seq": None,
                               "prio": PRIORITY["game_over"], "at": self.clock() + 0.001, "expires": self.clock() + 120.0})

    def publish_speaking(self, item: dict | None, seconds: float) -> None:
        """logs/voice-speaking.json — {"seat": N, "until": epoch_ms} while one of
        the SEATS is talking, {} otherwise. The match screen (VAdvisor) brings
        that seat's field tab forward for the line and puts the old tab back
        (Ben, 2026-09-10). Joshua and the human never move the tabs."""
        try:
            f = self.logs / "voice-speaking.json"
            if item is not None and item.get("seat") is not None and item.get("library"):
                body = {"seat": int(item["seat"]), "library": item["library"], "stock": item.get("stock", ""),
                        "until": int((time.time() + seconds) * 1000)}
            else:
                body = {}
            tmp = f.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(body))
            tmp.replace(f)
        except OSError:
            pass

    # -- loop
    def publish_state(self) -> None:
        """mailbox/seat-0-voice/state.json {"live": bool, "reason": str,
        "enabled": bool} — rewritten only when it changes."""
        live, reason = self.renderer.state()
        cur = {"live": live, "reason": reason, "enabled": self.enabled()}
        if cur == self._state_published:
            return
        self._state_published = cur
        try:
            d = self.mailbox / "seat-0-voice"
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "state.json.tmp"
            tmp.write_text(json.dumps(cur))
            tmp.replace(d / "state.json")
        except OSError:
            pass
        # log LIVE transitions only — a mute/unmute also changes the state file
        # (game 32: "live lines back on" printed on a mute click)
        if self._live_published is None or live != self._live_published:
            if not live:
                self.say(f"[voice] live lines off ({reason}) — stock phrases only; the advisor will quip more often")
            elif self._live_published is not None:
                self.say("[voice] live lines back on")
        self._live_published = live

    def step(self) -> None:
        self.publish_state()
        if not self.enabled():
            if self.queue:
                self.say(f"[voice] disabled — dropping {len(self.queue)} queued line(s)")
                self.queue = []
            return
        self.learn_table()
        self.scan_advisor()
        self.scan_observer()
        self.patter()
        item = self.next_item()
        if item is not None:
            self.speak(item)

    def run(self) -> None:
        self.say(f"[voice] up — chatter={self.chatter:g}, stock {len(self.renderer.manifest.get('phrases', {}))} phrases, "
                 f"live={'on' if self.renderer.live else 'off (no ELEVENLABS_API_KEY)'}, min_gap={self.min_gap}s, "
                 f"fx={self.renderer.fx_mode}, format={self.renderer.format}, glitch={self.renderer.glitch}, sfx={'on' if self.sfx_on else 'off'}, color={self.color_mode}, "
                 f"your_move={self.your_move_mode}, barks={self.barks_mode}, patter={'off' if not self.patter_on else f'{self.patter_gap[0]:g}-{self.patter_gap[1]:g}s'}" + (f", chains p={self.chains.first_hop_p}/decay {self.chains.decay}/max {self.chains.max_hops}/gap {self.chains.gap_s}s" if self.chains else ", chains=off (no chains.json)")
                 + (f" (p={self.barks_p}, opener_p={self.barks_opener_p}, swing>={self.barks_swing}, hit>={self.barks_hit}, guard={self.barks_cooldown:.0f}s; " + ", ".join(f"seat {k} {v['voice']}" for k, v in sorted(self.seat_libraries.items())) + ")"
                    if self.barks_mode != "off" and self.seat_libraries else (" (no seat voice libraries found)" if self.barks_mode != "off" else "")))
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
            time.sleep(CHAIN_POLL_S if any(q.get("chain") for q in self.queue) else POLL_S)


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
