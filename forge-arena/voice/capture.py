#!/usr/bin/env python3
"""capture.py — record what the Mac plays, through Ben's USB-C analog loop.

The "Cable Creation" USB-C dongle has its line-out cabled into its own mic-in,
so anything routed to that OUTPUT comes back on its INPUT. This script:
  1. remembers the current default output device,
  2. switches the default output to the loop (browser audio follows it),
  3. sets a fixed output volume (the analog level into the ADC),
  4. optionally opens a URL (YouTube autoplays a /watch URL),
  5. records the loop's input with ffmpeg to a mono 44.1 kHz WAV,
  6. restores the previous output device — also on Ctrl-C or error.

Usage:
  capture.py --seconds 30 --out samples/test.wav              # record whatever is playing
  capture.py --url https://www.youtube.com/watch?v=ID --seconds 572 --out samples/wopr-raw.wav
  capture.py --tone --seconds 5 --out samples/level-test.wav  # play a 440 Hz tone + speech into the loop

Requires: ffmpeg (avfoundation), SwitchAudioSource (brew install switchaudio-osx).
Reference audio recorded this way is a LISTENING reference for the voice
design work; it is gitignored (voice/.gitignore) and never uploaded anywhere.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LOOP = "Cable Creation"


def sh(*cmd: str, check: bool = True) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"ERROR: {' '.join(cmd)} -> {p.returncode}: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def current_output() -> str:
    return sh("SwitchAudioSource", "-c", "-t", "output")


def set_output(name: str) -> None:
    sh("SwitchAudioSource", "-s", name, "-t", "output")


def set_volume(pct: int) -> None:
    sh("osascript", "-e", f"set volume output volume {pct}")


def get_volume() -> int:
    try:
        return int(sh("osascript", "-e", "output volume of (get volume settings)"))
    except (SystemExit, ValueError):
        return 50


def make_tone(path: Path, seconds: float) -> None:
    """440 Hz tone for the first half, macOS speech for the rest — a level
    check with both a steady signal and a voice-shaped one."""
    sh("ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
       "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds / 2:.2f}",
       "-ar", "44100", "-ac", "1", str(path))


def record(out: Path, seconds: float, device: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "avfoundation", "-i", f":{device}",
           "-t", f"{seconds:.1f}", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"ERROR: ffmpeg recording failed: {p.stderr.strip()[:400]}")


def stats(path: Path) -> str:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    keep = [ln.split("] ")[-1] for ln in p.stderr.splitlines() if "mean_volume" in ln or "max_volume" in ln]
    return "; ".join(keep) or "(no level stats)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--url", help="open this URL in the default browser right before recording")
    ap.add_argument("--tone", action="store_true", help="play a test tone + 'say' into the loop while recording")
    ap.add_argument("--volume", type=int, default=75, help="output volume percent during capture (analog level)")
    ap.add_argument("--lead", type=float, default=0.0, help="extra seconds recorded before opening the URL")
    ap.add_argument("--device", default=LOOP)
    a = ap.parse_args()

    prev_out = current_output()
    prev_vol = get_volume()
    print(f"[capture] output was '{prev_out}' at {prev_vol}% — routing to '{a.device}' at {a.volume}%")

    def restore(*_):
        try:
            set_output(prev_out)
            set_volume(prev_vol)
        finally:
            print(f"[capture] output restored to '{prev_out}' at {prev_vol}%")

    signal.signal(signal.SIGINT, lambda *s: (restore(), sys.exit(130)))
    signal.signal(signal.SIGTERM, lambda *s: (restore(), sys.exit(143)))
    try:
        set_output(a.device)
        set_volume(a.volume)
        time.sleep(0.5)
        player = None
        if a.tone:
            tone = Path(tempfile.gettempdir()) / "capture-tone.wav"
            make_tone(tone, a.seconds)
            player = subprocess.Popen(["sh", "-c", f"afplay '{tone}'; say 'Greetings, Professor Falken. Shall we play a game?'"])
        elif a.url:
            if a.lead > 0:
                # start recording first so the opening is never clipped
                rec = subprocess.Popen([sys.executable, __file__, "--out", str(a.out), "--seconds",
                                        str(a.seconds), "--device", a.device, "--volume", str(a.volume)],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                time.sleep(a.lead)
                subprocess.run(["open", a.url], check=False)
                out, _ = rec.communicate()
                print(out.strip())
                return
            subprocess.run(["open", a.url], check=False)
        print(f"[capture] recording {a.seconds:.0f}s from '{a.device}' -> {a.out}")
        record(a.out, a.seconds, a.device)
        if player is not None:
            player.wait(timeout=30)
        print(f"[capture] done: {a.out} ({a.out.stat().st_size} bytes) — {stats(a.out)}")
    finally:
        restore()


if __name__ == "__main__":
    main()
