#!/usr/bin/env python3
"""build_stock.py — render and bake the shipped stock phrases.

manifest.json phrases  --render (ElevenLabs v3, missing only)-->  raw/<id>.wav
raw/<id>.wav  --ffmpeg (fx-chain.txt)-->  --glitch (seeded by id)-->  <id>.wav

Bake only (the default; stdlib + ffmpeg), after editing fx-chain.txt or the glitch level:
  python3 runner/voice/build_stock.py [--glitch light|heavy|off] [--ids a,b,c]

Render the dry takes for manifest phrases that have no raw/<id>.wav yet, then bake them
(2026-09-08, the RoboCop + HK-47 batch). The key is read from the environment only:
  ELEVENLABS_API_KEY=... python3 runner/voice/build_stock.py --render [--ids a,b,c]
The voice id and model settings come from the manifest ("voice_id"; eleven_v3, stability
1.0, speed 0.92 — the settings of the original 25 takes). pcm_44100 is asked for first (the
raw takes are 44.1 kHz mono); a rejected format falls back to pcm_24000, and the bake
step resamples anyway. Nothing about the key is ever printed.
The sfx/ bleeps are left untouched (they are the reference, not the voice).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from voice_runner import glitch_wav, pcm_to_wav  # noqa: E402

STOCK = HERE / "stock"
RENDER_MODEL = "eleven_v3"
RENDER_SETTINGS = {"stability": 1.0, "speed": 0.92}
RENDER_FORMATS = ("pcm_44100", "pcm_24000")


def manifest() -> dict:
    return json.loads((STOCK / "manifest.json").read_text())


def render_missing(ids: set[str] | None) -> tuple[int, int]:
    """Render raw/<id>.wav for every manifest phrase without one (or only `ids`).
    Returns (rendered, characters billed)."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        sys.exit("[build_stock] --render needs ELEVENLABS_API_KEY in the environment")
    m = manifest()
    voice_id = m["voice_id"]
    fmt_i = 0
    n = chars = 0
    for pid, ph in sorted(m["phrases"].items()):
        if ids is not None and pid not in ids:
            continue
        raw = STOCK / "raw" / f"{pid}.wav"
        if raw.exists():
            continue
        text = ph["text"]
        body = json.dumps({"text": text, "model_id": RENDER_MODEL, "voice_settings": RENDER_SETTINGS}).encode("utf-8")
        while True:
            fmt = RENDER_FORMATS[fmt_i]
            req = urllib.request.Request(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={fmt}",
                data=body, headers={"xi-api-key": key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                    cost = int(resp.headers.get("character-cost") or len(text))
                break
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001
                    pass
                if e.code in (400, 402, 403) and fmt_i + 1 < len(RENDER_FORMATS) and (
                        "output_format" in detail or "format" in detail.lower() or "tier" in detail.lower()):
                    print(f"[build_stock] {fmt} rejected ({e.code}) — trying {RENDER_FORMATS[fmt_i + 1]}")
                    fmt_i += 1
                    continue
                sys.exit(f"[build_stock] render failed for {pid}: HTTP {e.code} {detail}")
        rate = int(fmt.split("_")[1])
        raw.write_bytes(pcm_to_wav(data, rate))
        n += 1
        chars += cost
        print(f"[build_stock] rendered {pid}: {len(data) / (2 * rate):.2f}s, {cost} chars")
    print(f"[build_stock] {n} phrases rendered, {chars} characters billed")
    return n, chars


def bake(glitch: str, ids: set[str] | None) -> int:
    chain = (STOCK / "fx-chain.txt").read_text().strip()
    n = 0
    for raw in sorted((STOCK / "raw").glob("*.wav")):
        pid = raw.stem
        if ids is not None and pid not in ids:
            continue
        tmp = STOCK / f"{pid}.tmp.wav"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
                        "-af", chain, "-ar", "44100", "-ac", "1", str(tmp)], check=True)
        seed = int(hashlib.sha1(pid.encode()).hexdigest()[:8], 16)
        (STOCK / f"{pid}.wav").write_bytes(glitch_wav(tmp.read_bytes(), glitch, seed))
        tmp.unlink()
        n += 1
    print(f"[build_stock] {n} phrases baked (fx chain + glitch={glitch}) -> {STOCK}")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glitch", default="light", choices=["off", "light", "heavy"])
    ap.add_argument("--render", action="store_true", help="render missing raw takes from the manifest first (needs ELEVENLABS_API_KEY)")
    ap.add_argument("--ids", default="", help="comma-separated phrase ids to render/bake (default: all)")
    a = ap.parse_args()
    ids = {s.strip() for s in a.ids.split(",") if s.strip()} or None
    if a.render:
        render_missing(ids)
    bake(a.glitch, ids)


if __name__ == "__main__":
    main()
