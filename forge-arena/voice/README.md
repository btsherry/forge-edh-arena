# voice/ — Joshua reference and advisor voice work (experimental/voicework)

Goal: an ElevenLabs voice for the arena's advisor in the spirit of Joshua/WOPR
(WarGames, 1983). The film audio is a **listening reference only**: it is
captured through Ben's USB-C analog loop, kept under `samples/` (gitignored),
and never uploaded. The voice itself is built with Voice Design (text
description) and Voice Changer (your own performance), not by cloning.

## Tools (run with `voice/.venv/bin/python`)

| Script | What |
|---|---|
| `capture.py` | Routes the Mac's output to the "Cable Creation" loop, fixes the level, records the loop's input with PortAudio (48 kHz mono WAV), restores the output. `--tone` level test, `--url` to open a page, `--seconds`, `--volume`. |
| `cut.py` | Splits a recording into speech segments (level gate, or `--mode f0`), writes one WAV per segment + `segments.csv` (start, end, duration, level, median F0, F0 spread), and assembles a dense montage of `--target` seconds: auto-pick = flat low register (F0 in `--f0`, spread ≤ `--max-iqr`), or `--keep n,n,n` after auditioning. |
| `measure.py` | Cadence and register numbers for a sample: syllable rate (~wpm), pause structure, F0 median/IQR/range, spectral centroid and band, level. |

Setup once: `uv venv --python 3.12 voice/.venv && uv pip install --python voice/.venv/bin/python numpy soundfile scipy sounddevice`;
`brew install switchaudio-osx nowplaying-cli`; ffmpeg on PATH.

## Capture lessons (2026-09-07)

- **ffmpeg's avfoundation input drops ~15% of the audio** on this Mac at every
  setting tried; PortAudio (`sounddevice`) is drop-free. `capture.py` uses it.
- **Safari autoplay** starts an unattended video muted; a `/watch` URL opened
  with `open` only plays with sound once the site has been interacted with.
  `nowplaying-cli pause|seek 0|get title` drives the current player without
  any Automation permission prompt — use it to stop a runaway autoplay tab
  and to rewind before recording.
- YouTube **autoplays the next video** when one ends; pause before the
  capture window closes or the take fills with whatever came next.
- The WOPR compilation is quiet: at 100% output the loop reads about −40 dBFS
  RMS; the floor is −89 dBFS, so normalise after cutting.

## Where the take stands

`samples/wopr-take3.wav` = the full 9 min 24 s compilation, clean.
`cut.py --mode level --gate-db 15` gave 125 speech segments. Two flat-pitch
families came out, and only ears can say which is Joshua:

- **A, low and flat** (F0 70–135 Hz, spread ≤ 20 Hz): 44 segments, 83.5 s.
  `samples/joshua-30s.wav` (30 s, 94% speech) and
  `samples/joshua-candidate-A-lowflat-90s.wav` (the whole pool).
- **B, machine-flat mid register** (F0 ≈ 232 Hz, spread ≤ 5 Hz):
  `samples/joshua-candidate-B-flat232.wav`.

Audition: `afplay voice/samples/joshua-30s.wav`, the per-segment files are in
`samples/take3.level/segments/NNN.wav`. Then either accept, or rebuild with
`cut.py samples/wopr-take3.wav --keep <numbers> --target 30`.

## The voice in the game (2026-09-07)

The advisor now speaks: `runner/voice_runner.py` (stdlib only; supervised by
`runner/run_voice.sh`; started by `arena-play.sh` in advised human games,
`--no-voice` to silence). Stock lines live in `runner/voice/stock/` — 20
rendered from Ben's ElevenLabs voice `Jousha-W.O.P.R.` with `eleven_v3`
(stability 1.0, speed 0.92) plus his two v3 files from Downloads (`startup`,
`game-over-gg`); `raw/` holds the dry renders, the shipped WAVs carry the
film-match FX chain in `fx-chain.txt` (third-octave match-EQ against
`samples/joshua-30s.wav`, 50 Hz tremolo, slap echo, compressor — centroid
1176 Hz vs the reference's 1120). `sfx/` = seven terminal typing-to-Joshua beeps cut from take 3 (the 19–20 char/s clock at
900–1200 Hz, found by `typing_cut.py`-style steady-tone + pulse-rate detection; levelled 6 dB under
the voice lines, peaks ≤ −6 dBFS; the first tonal bloops are in `sfx/legacy/`). Re-render stock after editing the chain:
`for f in raw/*.wav; do ffmpeg -i $f -af "$(cat fx-chain.txt)" ../$(basename $f); done`.
Live lines: Flash v2.5, first sentence of each advice, cached under
`runner/logs/cache/voice/`. Tests: `runner/tests/test_voice_runner.py`,
`test_advisor_quips.py`.
