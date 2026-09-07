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


def voiced_mask(x: np.ndarray, sr: int, lo: float, hi: float, hop_s: float = 0.02, win_s: float = 0.04,
                min_periodicity: float = 0.6) -> tuple[np.ndarray, np.ndarray]:
    """Per-hop: is this frame periodic with F0 in [lo, hi]? Returns the mask
    and the F0 per frame (nan where unvoiced). Joshua sits around 80–130 Hz
    with a flat contour; the film's music bed and the other actors mostly do
    not, so runs of in-band voiced frames pick his lines out of a mixed
    soundtrack far better than a level gate."""
    win, hop = int(sr * win_s), int(sr * hop_s)
    n = max(0, (len(x) - win) // hop)
    mask = np.zeros(n, dtype=bool)
    f0 = np.full(n, np.nan, dtype=np.float32)
    lag_lo, lag_hi = int(sr / hi), int(sr / lo)
    for i in range(n):
        fr = x[i * hop:i * hop + win]
        if np.sqrt((fr ** 2).mean()) < 0.003:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, mode="full")[win - 1:]
        ac = ac / (ac[0] + 1e-9)
        seg = ac[lag_lo:lag_hi]
        if len(seg) == 0:
            continue
        k = int(np.argmax(seg))
        if seg[k] >= min_periodicity:
            mask[i] = True
            f0[i] = sr / (lag_lo + k)
    # median-smooth the mask over 5 hops (100 ms) to bridge consonants
    sm = np.convolve(mask.astype(np.float32), np.ones(5) / 5, mode="same") >= 0.5
    return sm, f0


def runs(mask: np.ndarray, hop_s: float, min_seg: float, min_gap: float, pad: float) -> list[tuple[float, float]]:
    segs: list[list[float]] = []
    i = 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
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
    return [(max(0.0, s - pad), e + pad) for s, e in merged if e - s >= min_seg]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--mode", choices=["level", "f0"], default="level",
                    help="f0: segments are runs of periodic frames with F0 in --f0 (default); level: RMS gate")
    ap.add_argument("--target", type=float, default=30.0, help="montage length in seconds")
    ap.add_argument("--gate-db", type=float, default=15.0)
    ap.add_argument("--min-seg", type=float, default=0.35)
    ap.add_argument("--min-gap", type=float, default=0.25)
    ap.add_argument("--pad", type=float, default=0.12)
    ap.add_argument("--gap", type=float, default=0.15, help="silence inserted between montage segments")
    ap.add_argument("--skip-until", type=float, default=0.0, help="ignore everything before this second (ads, intro)")
    ap.add_argument("--until", type=float, default=None, help="ignore everything after this second")
    ap.add_argument("--f0", default="70-135", help="F0 band (Hz) that counts as the target voice")
    ap.add_argument("--keep", help="comma-separated segment numbers to use instead of auto-pick")
    ap.add_argument("--max-iqr", type=float, default=20.0, help="auto-pick: max F0 interquartile spread (Hz) — flat delivery")
    ap.add_argument("--min-pick", type=float, default=0.6, help="auto-pick: skip segments shorter than this")
    ap.add_argument("--max-seg", type=float, default=12.0, help="auto-pick: skip segments longer than this (music beds)")
    ap.add_argument("--out", type=Path, help="output directory (default: <wav>.cut/)")
    a = ap.parse_args()

    x, sr = load(a.wav)
    if a.until is not None:
        x = x[: int(a.until * sr)]
    lo, hi = (float(v) for v in a.f0.split("-"))
    if a.mode == "f0":
        mask, _ = voiced_mask(x, sr, lo, hi)
        mask[: int(a.skip_until / 0.02)] = False
        segs = segments_from_mask = runs(mask, 0.02, a.min_seg, a.min_gap, a.pad)
    else:
        rms, hop = frame_rms(x, sr)
        segs = segments(rms, hop, sr, a.gate_db, a.min_seg, a.min_gap, a.pad, a.skip_until)
    out = a.out or a.wav.with_suffix(".cut")
    (out / "segments").mkdir(parents=True, exist_ok=True)
    rows = []
    for n, (s, e) in enumerate(segs, 1):
        seg = x[int(s * sr):int(e * sr)]
        med, spread = f0_stats(seg, sr)
        level = 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9)
        m, _ = voiced_mask(seg, sr, lo, hi)
        josh = float(m.mean()) if len(m) else 0.0
        rows.append({"n": n, "start": round(s, 2), "end": round(e, 2), "dur": round(e - s, 2),
                     "rms_db": round(float(level), 1), "f0_med": round(med, 1) if med == med else "",
                     "f0_iqr": round(spread, 1) if spread == spread else "", "josh": round(josh, 2)})
        sf.write(str(out / "segments" / f"{n:03d}.wav"), seg, sr)
    with (out / "segments.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["n"])
        w.writeheader()
        w.writerows(rows)
    total = sum(r["dur"] for r in rows)
    print(f"[cut] {len(rows)} speech segments, {total:.1f}s of speech in {len(x) / sr:.1f}s of audio -> {out}")
    for r in rows:
        print(f"  #{r['n']:>3}  {r['start']:>7.2f}-{r['end']:>7.2f}  {r['dur']:>5.2f}s  {r['rms_db']:>6.1f} dB"
              f"  f0 {r['f0_med'] or '  -  '} ±{r['f0_iqr'] or ' - '}  in-band {r['josh']:.2f}")

    if a.keep:
        chosen = [int(k) for k in a.keep.split(",") if k.strip()]
    else:
        # Joshua rule (take 3, 2026-09-07): a low, FLAT register — median F0 in
        # --f0 and an interquartile spread at most --max-iqr — separates his
        # lines from the other actors and the music bed far better than the
        # periodicity fraction did on this processed voice. Longest first.
        cands = [r for r in rows if r["f0_med"] != "" and lo <= r["f0_med"] <= hi
                 and r["f0_iqr"] != "" and r["f0_iqr"] <= a.max_iqr
                 and a.min_pick <= r["dur"] <= a.max_seg]
        cands.sort(key=lambda r: -r["dur"])
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
