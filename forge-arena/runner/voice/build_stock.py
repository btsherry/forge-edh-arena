#!/usr/bin/env python3
"""build_stock.py — bake the shipped stock phrases from the dry renders.

raw/<id>.wav  --ffmpeg (fx-chain.txt)-->  --glitch (seeded by id)-->  <id>.wav

Run after editing fx-chain.txt or changing the glitch level; stdlib + ffmpeg.
  python3 runner/voice/build_stock.py [--glitch light|heavy|off]
The sfx/ bleeps are left untouched (they are the reference, not the voice).
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from voice_runner import glitch_wav  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glitch", default="light", choices=["off", "light", "heavy"])
    a = ap.parse_args()
    stock = HERE / "stock"
    chain = (stock / "fx-chain.txt").read_text().strip()
    n = 0
    for raw in sorted((stock / "raw").glob("*.wav")):
        pid = raw.stem
        tmp = stock / f"{pid}.tmp.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
                        "-af", chain, "-ar", "44100", "-ac", "1", str(tmp)], check=True)
        seed = int(hashlib.sha1(pid.encode()).hexdigest()[:8], 16)
        (stock / f"{pid}.wav").write_bytes(glitch_wav(tmp.read_bytes(), a.glitch, seed))
        tmp.unlink()
        n += 1
    print(f"[build_stock] {n} phrases baked (fx chain + glitch={a.glitch}) -> {stock}")


if __name__ == "__main__":
    main()
