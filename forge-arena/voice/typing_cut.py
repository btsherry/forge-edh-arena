#!/usr/bin/env python3
"""typing_cut.py — find the terminal-typing bursts in a recording and cut them
as the voice's lead-in sound effects.

A WarGames terminal "types" a line as a rapid train of clicks/beeps, one per
character: high-frequency energy whose envelope is modulated at roughly the
character rate (8–30 Hz), with no voicing underneath. Music, speech and
explosions do not look like that. Per 0.5 s window (10 ms hops) we score:
  - HF share: energy above 1.5 kHz vs total (typing is bright);
  - modulation peak: the envelope's spectrum peak in 8–30 Hz relative to
    everything below 60 Hz (the character clock);
  - voicing: autocorrelation periodicity in 70–400 Hz (speech → reject).
Windows passing the thresholds are merged into bursts of --min..--max seconds,
faded 5 ms at both ends, peak-normalised to −3 dBFS, resampled to 44.1 kHz and
written as sfx/typing-NN.wav with a table so the pick can be audited.

Usage: typing_cut.py samples/trailer-raw.wav [--out runner/voice/stock/sfx] [--hf 0.35] [--mod 3.0]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "runner" / "voice" / "stock" / "sfx")
    ap.add_argument("--hf", type=float, default=0.35, help="min share of energy above 1.5 kHz")
    ap.add_argument("--mod", type=float, default=3.0, help="min modulation peak ratio (peak must sit in --band)")
    ap.add_argument("--band-lo", type=float, default=8.0, help="character-rate band, Hz")
    ap.add_argument("--band-hi", type=float, default=22.0)
    ap.add_argument("--min", type=float, default=0.35)
    ap.add_argument("--max", type=float, default=2.0)
    ap.add_argument("--keep", type=int, default=8, help="how many bursts to write (best scores)")
    ap.add_argument("--prefix", default="typing")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    x, sr = sf.read(str(a.wav), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    hop = int(sr * 0.01)
    win = int(sr * 0.5)
    hf_sos = butter(4, 1500 / (sr / 2), btype="highpass", output="sos")
    xh = sosfilt(hf_sos, x)
    n = (len(x) - win) // hop
    scores = []
    for i in range(n):
        s = i * hop
        seg, segh = x[s:s + win], xh[s:s + win]
        tot = float((seg ** 2).mean()) + 1e-12
        if tot < 1e-7:
            scores.append((0, 0, 0)); continue
        hf_share = float((segh ** 2).mean()) / tot
        # envelope of the HF band at 2 ms → modulation spectrum
        e_hop = int(sr * 0.002)
        m = len(segh) // e_hop
        env = np.sqrt((segh[: m * e_hop].reshape(m, e_hop) ** 2).mean(axis=1))
        env = env - env.mean()
        E = np.abs(np.fft.rfft(env * np.hanning(m))) ** 2
        f = np.fft.rfftfreq(m, 0.002)
        sel = (f >= 3) & (f <= 60)
        peak_hz = float(f[sel][np.argmax(E[sel])]) if sel.any() else 0.0
        in_band = a.band_lo <= peak_hz <= a.band_hi
        rest = np.median(E[(f > 0.5) & (f < 60)]) + 1e-12
        mod_ratio = float(E[sel].max() / rest) if in_band else 0.0   # music beats peak at 4–6 Hz → 0
        # voicing
        fr = seg[: int(sr * 0.04)] - seg[: int(sr * 0.04)].mean()
        ac = np.correlate(fr, fr, mode="full")[len(fr) - 1:]
        ac = ac / (ac[0] + 1e-9)
        lo, hi = int(sr / 400), int(sr / 70)
        voiced = float(ac[lo:hi].max()) if hi > lo else 0.0
        scores.append((hf_share, mod_ratio, voiced))
    hf = np.array([s[0] for s in scores]); mod = np.array([s[1] for s in scores]); vo = np.array([s[2] for s in scores])
    ok = (hf >= a.hf) & (mod >= a.mod) & (vo < 0.55)
    # merge runs of ok windows
    bursts, i = [], 0
    while i < n:
        if ok[i]:
            j = i
            while j < n and ok[j]:
                j += 1
            start, end = i * 0.01, j * 0.01 + 0.5
            score = float(np.mean(mod[i:j] * hf[i:j]))
            bursts.append([start, end, score])
            i = j
        else:
            i += 1
    bursts = [b for b in bursts if a.min <= b[1] - b[0] <= a.max + 0.5]
    bursts.sort(key=lambda b: -b[2])
    print(f"[typing] {len(bursts)} typing-like bursts in {len(x) / sr:.0f}s (hf≥{a.hf}, mod≥{a.mod}):")
    for k, (s, e, sc) in enumerate(bursts[:20]):
        print(f"  {'*' if k < a.keep else ' '} {s:7.2f}-{e:7.2f} {e - s:4.2f}s score {sc:6.1f}")
    if a.dry_run:
        return
    a.out.mkdir(parents=True, exist_ok=True)
    fade = int(sr * 0.005)
    written = []
    for k, (s, e, sc) in enumerate(bursts[: a.keep], 1):
        e = min(e, s + a.max)
        seg = x[int(s * sr):int(e * sr)].copy()
        seg[:fade] *= np.linspace(0, 1, fade); seg[-fade:] *= np.linspace(1, 0, fade)
        if sr != 44100:
            seg = resample_poly(seg, 147, 160) if sr == 48000 else resample_poly(seg, 44100, sr)
        seg = seg / (np.abs(seg).max() + 1e-9) * 0.7
        name = f"{a.prefix}-{k:02d}.wav"
        sf.write(str(a.out / name), seg.astype(np.float32), 44100, subtype="PCM_16")
        written.append(name)
    print(f"[typing] wrote {len(written)} -> {a.out}: {', '.join(written)}")


if __name__ == "__main__":
    main()
