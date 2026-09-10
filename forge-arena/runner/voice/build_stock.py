#!/usr/bin/env python3
"""build_stock.py — render and bake a stock voice library.

manifest.json phrases  --render (ElevenLabs, missing only)-->  raw/<id>[-N].wav
raw/<id>[-N].wav  --bake-->  <id>[-N].wav

Libraries (2026-09-10, seat barks): the default library is the Joshua/W.O.P.R.
set in runner/voice/stock/; a seat-bark library lives in
runner/voice/stock/voices/<name>/ with its own manifest. `--library` takes the
name (harry, bill, lily) or a directory. Every knob comes from the manifest:

  "render": {"model": "eleven_v3", "voice_settings": {"stability": 1.0, "speed": 0.92},
             "formats": ["pcm_44100", "pcm_24000"]}
  "bake":   {"rate": 44100, "fx": "chain" | "none", "glitch": "light|heavy|off",
             "gain": "library", "target_lufs": -24.0, "true_peak_max": -1.0}

Absent fields fall back to the Joshua settings the original 63 lines were made
with (eleven_v3, stability 1.0, speed 0.92; fx-chain.txt + light glitch at 44.1 kHz),
so the shipped manifest needs no edits. A seat library bakes with fx "none":
ONE gain for the whole library (its mean integrated loudness moved to
target_lufs — the Joshua library measures -24.3 LUFS, peaks under -5.8 dBTP),
then a resample to its rate. No per-line normalisation, no compressor, no film
effects, no glitch: a shout stays louder than a sigh (Ben, 2026-09-10: "be
careful not to squash the delivery … or over boost a tired sigh"). A take whose
true peak would pass true_peak_max after the gain gets that much less gain,
alone, and says so.

Variants: a phrase's "text" may be a string or a list. Wording 1 is <id>.wav,
wording N>1 is <id>-N.wav (raw takes likewise). The voice runner draws a
wording from a shuffle bag at play time.

Bake only (the default; stdlib + ffmpeg), after editing fx-chain.txt or the glitch level:
  python3 runner/voice/build_stock.py [--library NAME] [--glitch light|heavy|off] [--ids a,b,c]

Render the dry takes for manifest wordings that have no raw take yet, then bake them.
The key is read from the environment only; nothing about it is ever printed:
  ELEVENLABS_API_KEY=... python3 runner/voice/build_stock.py --library harry --render [--ids a,b,c] [--limit N]

--limit N renders at most N missing takes (the first probe batch of a new voice:
listen for tags read aloud before spending the rest). The formats list is tried in
order; a rejected format falls back to the next for the run. The sfx/ bleeps are
left untouched (they are the reference, not the voice).
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
VOICES = STOCK / "voices"
# the settings of the original 25 Joshua takes — the defaults when a manifest says nothing
RENDER_MODEL = "eleven_v3"
RENDER_SETTINGS = {"stability": 1.0, "speed": 0.92}
RENDER_FORMATS = ("pcm_44100", "pcm_24000")
BAKE_DEFAULTS = {"rate": 44100, "fx": "chain", "glitch": "light", "target_lufs": -24.0, "true_peak_max": -1.0}


def resolve_library(name: str | None) -> Path:
    """None/"" -> the Joshua library; a bare name -> stock/voices/<name>; a path -> itself."""
    if not name:
        return STOCK
    p = Path(name)
    if p.is_dir() and (p / "manifest.json").exists():
        return p.resolve()
    cand = VOICES / name
    if (cand / "manifest.json").exists():
        return cand
    sys.exit(f"[build_stock] no library '{name}' (looked for {cand}/manifest.json)")


def manifest(lib: Path) -> dict:
    return json.loads((lib / "manifest.json").read_text())


def variant_name(pid: str, n: int) -> str:
    """Wording 1 keeps the bare id (the shipped files); N>1 gets -N."""
    return pid if n == 1 else f"{pid}-{n}"


def variants(m: dict) -> list[tuple[str, int, str, str]]:
    """Every (phrase id, wording number, text, file stem) in manifest order."""
    out: list[tuple[str, int, str, str]] = []
    for pid, ph in m.get("phrases", {}).items():
        text = ph.get("text", "")
        texts = text if isinstance(text, list) else [text]
        for n, t in enumerate(texts, 1):
            out.append((pid, n, t, variant_name(pid, n)))
    return out


def selected(ids: set[str] | None, pid: str, n: int) -> bool:
    """--ids entries: "pid" selects every wording of that phrase, "pid:N" one wording."""
    return ids is None or pid in ids or f"{pid}:{n}" in ids


def render_settings(m: dict) -> tuple[str, dict, tuple[str, ...]]:
    r = m.get("render") or {}
    return (r.get("model") or RENDER_MODEL,
            dict(r.get("voice_settings") or RENDER_SETTINGS),
            tuple(r.get("formats") or RENDER_FORMATS))


def bake_settings(m: dict, glitch_override: str | None = None) -> dict:
    b = dict(BAKE_DEFAULTS)
    b.update(m.get("bake") or {})
    if glitch_override is not None:
        b["glitch"] = glitch_override
    return b


def bake_argv(raw: Path, tmp: Path, lib: Path, m: dict, b: dict, gain_db: float | None = None) -> list[str]:
    """The ffmpeg command for one take. fx "chain": the library's fx-chain.txt at
    44.1 kHz (the mainframe). fx "none": a plain gain (the library's, see
    library_gain) and a resample to the library rate — a seat voice stays clean."""
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw)]
    if b.get("fx", "chain") == "chain":
        chain = (lib / m.get("fx_chain_file", "fx-chain.txt")).read_text().strip()
        af = chain
    else:
        af = f"volume={gain_db or 0.0:.2f}dB"
    return base + ["-af", af, "-ar", str(b.get("rate", 44100)), "-ac", "1", str(tmp)]


def parse_loudnorm(stderr: str) -> tuple[float, float]:
    """(integrated LUFS, true peak dBTP) from ffmpeg's loudnorm print_format=json
    block — it is the last {...} in stderr, followed by trailing lines."""
    a = stderr.rindex("{")
    j = json.loads(stderr[a:stderr.index("}", a) + 1])
    return float(j["input_i"]), float(j["input_tp"])


def measure(path: Path) -> tuple[float, float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    return parse_loudnorm(r.stderr)


def library_gain(measures: list[tuple[float, float]], target_lufs: float) -> float:
    """One gain for the library: target minus the mean integrated loudness of
    its takes (silent/unmeasurable takes below -70 LUFS are ignored)."""
    vals = [i for i, _tp in measures if i > -70]
    if not vals:
        return 0.0
    return round(target_lufs - sum(vals) / len(vals), 2)


def file_gain(gain_db: float, true_peak: float, ceiling: float) -> float:
    """The library gain, reduced for this take only if it would clip the ceiling."""
    return round(min(gain_db, ceiling - true_peak), 2) if true_peak > -70 else gain_db


def render_missing(lib: Path, ids: set[str] | None, limit: int | None = None) -> tuple[int, int]:
    """Render raw/<stem>.wav for every manifest wording without one (or only `ids`,
    at most `limit` takes). Returns (rendered, characters billed)."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        sys.exit("[build_stock] --render needs ELEVENLABS_API_KEY in the environment")
    m = manifest(lib)
    voice_id = m["voice_id"]
    model, settings, formats = render_settings(m)
    (lib / "raw").mkdir(exist_ok=True)
    fmt_i = 0
    n = chars = 0
    for pid, num, text, stem in variants(m):
        if not selected(ids, pid, num):
            continue
        raw = lib / "raw" / f"{stem}.wav"
        if raw.exists():
            continue
        if limit is not None and n >= limit:
            break
        body = json.dumps({"text": text, "model_id": model, "voice_settings": settings}).encode("utf-8")
        while True:
            fmt = formats[fmt_i]
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
                if e.code in (400, 402, 403) and fmt_i + 1 < len(formats) and (
                        "output_format" in detail or "format" in detail.lower() or "tier" in detail.lower()):
                    print(f"[build_stock] {fmt} rejected ({e.code}) — trying {formats[fmt_i + 1]}")
                    fmt_i += 1
                    continue
                sys.exit(f"[build_stock] render failed for {stem}: HTTP {e.code} {detail}")
        rate = int(fmt.split("_")[1])
        raw.write_bytes(pcm_to_wav(data, rate))
        n += 1
        chars += cost
        print(f"[build_stock] rendered {stem}: {len(data) / (2 * rate):.2f}s, {cost} chars")
    print(f"[build_stock] {n} takes rendered, {chars} characters billed ({lib.name})")
    return n, chars


def bake(lib: Path, ids: set[str] | None, glitch_override: str | None = None) -> int:
    m = manifest(lib)
    b = bake_settings(m, glitch_override)
    stems = {stem: (pid, n) for pid, n, _t, stem in variants(m)}
    raws = sorted((lib / "raw").glob("*.wav"))
    gain = None
    peaks: dict[str, float] = {}
    if b.get("fx", "chain") != "chain" and raws:
        measures = {r.stem: measure(r) for r in raws}           # the WHOLE library, not just --ids:
        gain = library_gain(list(measures.values()), float(b.get("target_lufs", -24.0)))   # the gain is a library constant
        peaks = {k: tp for k, (_i, tp) in measures.items()}
        print(f"[build_stock] library gain {gain:+.2f} dB ({len(measures)} takes -> {b.get('target_lufs', -24.0)} LUFS mean)")
    n = 0
    for raw in raws:
        stem = raw.stem
        pid, num = stems.get(stem, (stem, 1))
        if not selected(ids, pid, num):
            continue
        g = None
        if gain is not None:
            g = file_gain(gain, peaks.get(stem, -99.0), float(b.get("true_peak_max", -1.0)))
            if g != gain:
                print(f"[build_stock] {stem}: gain held to {g:+.2f} dB (true peak would pass {b.get('true_peak_max', -1.0)} dBTP)")
        tmp = lib / f"{stem}.tmp.wav"
        subprocess.run(bake_argv(raw, tmp, lib, m, b, g), check=True)
        seed = int(hashlib.sha1(stem.encode()).hexdigest()[:8], 16)
        (lib / f"{stem}.wav").write_bytes(glitch_wav(tmp.read_bytes(), b.get("glitch", "off"), seed))
        tmp.unlink()
        n += 1
    print(f"[build_stock] {n} takes baked (fx={b.get('fx')}, rate={b.get('rate')}, glitch={b.get('glitch')}) -> {lib}")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default="", help="stock library: a name under voice/stock/voices/ (harry, bill, lily) or a directory; default = the Joshua library")
    ap.add_argument("--glitch", default=None, choices=["off", "light", "heavy"], help="override the manifest's bake glitch level")
    ap.add_argument("--render", action="store_true", help="render missing raw takes from the manifest first (needs ELEVENLABS_API_KEY)")
    ap.add_argument("--ids", default="", help="comma-separated selectors: a phrase id (every wording) or id:N (one wording); default: all")
    ap.add_argument("--limit", type=int, default=None, help="render at most N missing takes (probe batch)")
    a = ap.parse_args()
    lib = resolve_library(a.library)
    ids = {s.strip() for s in a.ids.split(",") if s.strip()} or None
    if a.render:
        render_missing(lib, ids, a.limit)
    bake(lib, ids, a.glitch)


if __name__ == "__main__":
    main()
