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
    """Blocking playback of a WAV on the default output, via whatever the OS has."""

    def __init__(self, dry_run: bool = False, log=print):
        self.dry_run = dry_run
        self.log = log
        self.cmd = None
        for cand in (["afplay"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]):
            if shutil.which(cand[0]):
                self.cmd = cand
                break

    def play(self, path: Path) -> None:
        if self.dry_run or self.cmd is None:
            self.log(f"[voice] (dry) play {path.name} {wav_seconds(path):.1f}s")
            time.sleep(min(wav_seconds(path), 0.05) if self.dry_run else 0)
            return
        subprocess.run(self.cmd + [str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=120)


# ---- renderer -------------------------------------------------------------------

class Renderer:
    """stock → cache → live. Live is ElevenLabs Flash v2.5; MP3 back, ffmpeg to
    WAV with the stock FX chain when ffmpeg exists; the result is cached."""

    def __init__(self, cache_dir: Path, log=print, fake_tts=None):
        self.cache_dir = cache_dir
        self.log = log
        self.manifest = json.loads((STOCK / "manifest.json").read_text()) if (STOCK / "manifest.json").exists() else {"phrases": {}, "sfx": []}
        self.api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        self.voice_id = os.environ.get("ARENA_VOICE_ID") or self.manifest.get("voice_id") or DEFAULT_VOICE_ID
        self.model = os.environ.get("ARENA_VOICE_MODEL", "eleven_flash_v2_5")
        self.fx_on = os.environ.get("ARENA_VOICE_FX", "on").lower() != "off" and shutil.which("ffmpeg") is not None
        fx_file = STOCK / self.manifest.get("fx_chain_file", "fx-chain.txt")
        self.fx_chain = fx_file.read_text().strip() if (self.fx_on and fx_file.exists()) else ""
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
        key = cache_key(text, self.voice_id, self.model, self.fx_chain + "|glitch=" + self.glitch)
        out = self.cache_dir / f"{key}.wav"
        if out.exists():
            return out
        if not self.live:
            return None
        try:
            if self.fake_tts is not None:
                mp3 = self.fake_tts(text)
                cost = len(text)
            else:
                mp3, cost = self._elevenlabs(text)
        except Exception as e:  # noqa: BLE001 — a failed render is a skipped line, never a crash
            self.log(f"[voice] live render failed: {str(e)[:160]}")
            return None
        self.chars_used += cost
        tmp_in = self.cache_dir / f"{key}.in"
        tmp_in.write_bytes(mp3)
        tmp_out = self.cache_dir / f"{key}.tmp.wav"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_in), "-ar", "44100", "-ac", "1"]
        if self.fx_chain:
            cmd += ["-af", self.fx_chain]
        cmd.append(str(tmp_out))
        try:
            if shutil.which("ffmpeg"):
                subprocess.run(cmd, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                tmp_out.write_bytes(mp3)  # tests / no ffmpeg: keep what we got
            if self.glitch != "off":
                tmp_out.write_bytes(glitch_wav(tmp_out.read_bytes(), self.glitch, int(key[:8], 16)))
            tmp_out.replace(out)
        finally:
            tmp_in.unlink(missing_ok=True)
        return out

    def _elevenlabs(self, text: str) -> tuple[bytes, int]:
        body = json.dumps({"text": text, "model_id": self.model,
                           "voice_settings": {"stability": 0.9, "similarity_boost": 0.8, "style": 0.0,
                                              "use_speaker_boost": True, "speed": 0.92}}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?output_format=mp3_44100_128",
            data=body, headers={"xi-api-key": self.api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            cost = int(resp.headers.get("character-cost") or len(text))
        return data, cost


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
        self.renderer = Renderer(logs_dir / "cache" / "voice", log=self.say, fake_tts=fake_tts)
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
        try:
            return bool(json.loads(self._control.read_text()).get("enabled", True))
        except (OSError, ValueError):
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
                self.player.play(bleep)
        self.player.play(path)
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
            return
        self.scan_advisor()
        self.scan_observer()
        item = self.next_item()
        if item is not None:
            self.speak(item)

    def run(self) -> None:
        self.say(f"[voice] up — stock {len(self.renderer.manifest.get('phrases', {}))} phrases, "
                 f"live={'on' if self.renderer.live else 'off (no ELEVENLABS_API_KEY)'}, min_gap={self.min_gap}s, "
                 f"fx={'on' if self.renderer.fx_chain else 'off'}, glitch={self.renderer.glitch}, sfx={'on' if self.sfx_on else 'off'}, color={self.color_mode}")
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
