#!/usr/bin/env python3
"""measure.py — cadence and register numbers for a reference voice sample.

Turns a montage (or any WAV of one speaker) into the figures the Voice Design
prompt and the speech-to-speech performance are steered by:
  - syllable rate: peaks of the 300–3400 Hz envelope (≈ one per syllable),
    reported per second of speech and as a rough words-per-minute (÷1.5);
  - pause structure: gaps below the level gate, their count, median and
    longest, and the speech/pause ratio ("evenly spaced words" is a Joshua
    signature — expect many short, similar gaps);
  - register: median F0 and interquartile spread over voiced frames (a flat
    delivery has a small spread), plus the 5th–95th percentile range;
  - spectral centre of mass and the −20 dB bandwidth of the long-term
    spectrum (where the modulation chain needs to sit);
  - level: RMS and peak.

Usage: measure.py samples/joshua-30s.wav [--gate-db 25]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, find_peaks, sosfilt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--gate-db", type=float, default=25.0, help="pause = envelope this far below the speech level")
    a = ap.parse_args()
    x, sr = sf.read(str(a.wav), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    dur = len(x) / sr

    # envelope of the speech band, 10 ms hops
    sos = butter(4, [300 / (sr / 2), 3400 / (sr / 2)], btype="band", output="sos")
    b = sosfilt(sos, x)
    hop = int(sr * 0.01)
    n = len(b) // hop
    env = np.sqrt((b[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    env_db = 20 * np.log10(env)
    speech_level = np.percentile(env_db, 90)
    speaking = env_db > speech_level - a.gate_db

    # syllables: envelope peaks at least 120 ms apart, above the gate
    sm = np.convolve(env, np.ones(5) / 5, mode="same")
    peaks, _ = find_peaks(sm, distance=12, height=10 ** ((speech_level - a.gate_db + 6) / 20))
    speech_s = speaking.sum() * 0.01
    syl_rate = len(peaks) / max(speech_s, 1e-6)

    # pauses
    gaps, i = [], 0
    while i < n:
        if not speaking[i]:
            j = i
            while j < n and not speaking[j]:
                j += 1
            if 0.08 <= (j - i) * 0.01 <= 3.0:
                gaps.append((j - i) * 0.01)
            i = j
        else:
            i += 1

    # F0 over 40 ms voiced frames
    win = int(sr * 0.04)
    f0s = []
    for s in range(0, len(x) - win, win // 2):
        fr = x[s:s + win]
        if np.sqrt((fr ** 2).mean()) < 0.01:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, mode="full")[win - 1:]
        ac /= ac[0] + 1e-9
        lo, hi = int(sr / 400), int(sr / 60)
        k = int(np.argmax(ac[lo:hi]))
        if ac[lo + k] > 0.55:
            f0s.append(sr / (lo + k))
    f0s = np.array(f0s) if f0s else np.array([np.nan])

    # long-term spectrum
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    band = (freqs >= 60) & (freqs <= 8000)
    centroid = float((freqs[band] * spec[band]).sum() / spec[band].sum())
    sdb = 10 * np.log10(spec[band] + 1e-18)
    top = sdb.max()
    inb = freqs[band][sdb > top - 20]

    rms = 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)
    peak = 20 * np.log10(np.abs(x).max() + 1e-9)
    print(f"file            {a.wav}  ({dur:.1f} s, {sr} Hz)")
    print(f"speech / pause  {speech_s:.1f} s speaking ({100 * speech_s / dur:.0f}%), {len(gaps)} pauses, "
          f"median {np.median(gaps) if gaps else 0:.2f} s, longest {max(gaps) if gaps else 0:.2f} s")
    print(f"syllable rate   {syl_rate:.2f} /s of speech  (~{syl_rate * 60 / 1.5:.0f} words per minute)")
    print(f"register        F0 median {np.nanmedian(f0s):.0f} Hz, IQR {np.nanpercentile(f0s, 75) - np.nanpercentile(f0s, 25):.0f} Hz, "
          f"5–95% {np.nanpercentile(f0s, 5):.0f}–{np.nanpercentile(f0s, 95):.0f} Hz, {len(f0s)} voiced frames")
    print(f"spectrum        centroid {centroid:.0f} Hz, −20 dB band {inb.min():.0f}–{inb.max():.0f} Hz")
    print(f"level           RMS {rms:.1f} dBFS, peak {peak:.1f} dBFS")


if __name__ == "__main__":
    main()
