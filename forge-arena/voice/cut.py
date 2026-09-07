#!/usr/bin/env python3
"""cut.py — split a captured recording into speech segments and assemble a
dense reference sample of a target length.

Steps:
  1. load the WAV (mono; stereo is averaged), high-pass at 80 Hz;
  2. frame RMS (20 ms hop); the noise floor is the 15th percentile; speech is
     frames above floor + `--gate-db` (default 12 dB); merge gaps shorter than
     `--min-gap`, drop islands shorter than `--min-seg`, pad each edge;
  3. per segment: start, end, duration, RMS, an autocorrelation pitch estimate
     (median F0 and its spread — a flat, monotone delivery has a small spread);
  4. write every segment as its own WAV (audition them), a CSV, and a montage:
     segments in original order, chosen to fill `--target` seconds as densely
     as possible — `--keep` picks by number after you have listened,
     otherwise the longest segments whose median F0 sits in `--f0` win.

Usage:
  cut.py samples/wopr-raw.wav --target 30                      # auto pick, writes samples/wopr-raw.cut/
  cut.py samples/wopr-raw.wav --target 30 --keep 3,5,8,12      # your pick, same order as the CSV
  cut.py samples/wopr-raw.wav --skip-until 12                  # ignore a pre-roll ad/intro (seconds)
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt


def load(path: Path) -> tuple[np.ndarray, int]:
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    sos = butter(4, 80.0 / (sr / 2), btype="highpass", output="sos")
    return sosfilt(sos, x).astype(np.float32), sr


def frame_rms(x: np.ndarray, sr: int, hop_s: float = 0.02) -> tuple[np.ndarray, int]:
    hop = int(sr * hop_s)
    n = len(x) // hop
    frames = x[: n * hop].reshape(n, hop)
    return np.sqrt((frames ** 2).mean(axis=1) + 1e-12), hop


def segments(rms: np.ndarray, hop: int, sr: int, gate_db: float, min_seg: float, min_gap: float, pad: float,
             skip_until: float) -> list[tuple[float, float]]:
    db = 20 * np.log10(rms)
    floor = np.percentile(db, 15)
    on = db > floor + gate_db
    hop_s = hop / sr
    on[: int(skip_until / hop_s)] = False
    segs: list[list[float]] = []
    i = 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            segs.append([i * hop_s, j * hop_s])
            i = j
        else:
            i += 1
    merged: list[list[float]] = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < min_gap:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    out = [(max(0.0, s - pad), e + pad) for s, e in merged if e - s >= min_seg]
    return out


def f0_stats(x: np.ndarray, sr: int, lo: float = 60.0, hi: float = 400.0) -> tuple[float, float]:
    """Median F0 and its interquartile spread over 40 ms voiced-ish frames,
    by autocorrelation. Rough, but enough to tell a flat synthetic delivery
    from a natural one and a male register from a female one."""
    win = int(sr * 0.04)
    hop = win // 2
    f0s = []
    for start in range(0, len(x) - win, hop):
        fr = x[start:start + win]
        if np.sqrt((fr ** 2).mean()) < 0.01:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, mode="full")[win - 1:]
        ac /= ac[0] + 1e-9
        lag_lo, lag_hi = int(sr / hi), int(sr / lo)
        seg = ac[lag_lo:lag_hi]
        if len(seg) == 0:
            continue
        k = int(np.argmax(seg))
        if seg[k] > 0.5:
            f0s.append(sr / (lag_lo + k))
    if len(f0s) < 3:
        return float("nan"), float("nan")
    q1, med, q3 = np.percentile(f0s, [25, 50, 75])
    return float(med), float(q3 - q1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--target", type=float, default=30.0, help="montage length in seconds")
    ap.add_argument("--gate-db", type=float, default=12.0)
    ap.add_argument("--min-seg", type=float, default=0.35)
    ap.add_argument("--min-gap", type=float, default=0.25)
    ap.add_argument("--pad", type=float, default=0.12)
    ap.add_argument("--gap", type=float, default=0.15, help="silence inserted between montage segments")
    ap.add_argument("--skip-until", type=float, default=0.0, help="ignore everything before this second (ads, intro)")
    ap.add_argument("--f0", default="70-220", help="median-F0 band (Hz) a segment must sit in for auto-pick")
    ap.add_argument("--keep", help="comma-separated segment numbers to use instead of auto-pick")
    ap.add_argument("--out", type=Path, help="output directory (default: <wav>.cut/)")
    a = ap.parse_args()

    x, sr = load(a.wav)
    rms, hop = frame_rms(x, sr)
    segs = segments(rms, hop, sr, a.gate_db, a.min_seg, a.min_gap, a.pad, a.skip_until)
    out = a.out or a.wav.with_suffix(".cut")
    (out / "segments").mkdir(parents=True, exist_ok=True)
    rows = []
    for n, (s, e) in enumerate(segs, 1):
        seg = x[int(s * sr):int(e * sr)]
        med, spread = f0_stats(seg, sr)
        level = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9)
        rows.append({"n": n, "start": round(s, 2), "end": round(e, 2), "dur": round(e - s, 2),
                     "rms_db": round(float(level), 1), "f0_med": round(med, 1) if med == med else "",
                     "f0_iqr": round(spread, 1) if spread == spread else ""})
        sf.write(str(out / "segments" / f"{n:03d}.wav"), seg, sr)
    with (out / "segments.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["n"])
        w.writeheader()
        w.writerows(rows)
    total = sum(r["dur"] for r in rows)
    print(f"[cut] {len(rows)} speech segments, {total:.1f}s of speech in {len(x) / sr:.1f}s of audio -> {out}")
    for r in rows:
        print(f"  #{r['n']:>3}  {r['start']:>7.2f}-{r['end']:>7.2f}  {r['dur']:>5.2f}s  {r['rms_db']:>6.1f} dB"
              f"  f0 {r['f0_med'] or '  -  '} ±{r['f0_iqr'] or ' - '}")

    if a.keep:
        chosen = [int(k) for k in a.keep.split(",") if k.strip()]
    else:
        lo, hi = (float(v) for v in a.f0.split("-"))
        cands = [r for r in rows if r["f0_med"] != "" and lo <= r["f0_med"] <= hi]
        cands.sort(key=lambda r: (-r["dur"], r["f0_iqr"] if r["f0_iqr"] != "" else 1e9))
        chosen, acc = [], 0.0
        for r in cands:
            if acc + r["dur"] + a.gap > a.target:
                continue
            chosen.append(r["n"])
            acc += r["dur"] + a.gap
        chosen.sort()
    pieces = []
    gap = np.zeros(int(a.gap * sr), dtype=np.float32)
    for n in chosen:
        r = rows[n - 1]
        pieces.append(x[int(r["start"] * sr):int(r["end"] * sr)])
        pieces.append(gap)
    if not pieces:
        sys.exit("[cut] nothing to assemble — loosen --f0 or pass --keep")
    y = np.concatenate(pieces)
    y = y / (np.abs(y).max() + 1e-9) * 0.89  # peak -1 dBFS
    target_path = out / f"montage-{int(a.target)}s.wav"
    sf.write(str(target_path), y, sr)
    print(f"[cut] montage: segments {chosen} -> {target_path} ({len(y) / sr:.1f}s)")


if __name__ == "__main__":
    main()
