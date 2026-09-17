# scripts/research/sound — the effects crackle, measured (BL-56)

**Research tooling only.** It needs a loopback device and a hand-set output level, so by Ben's rule
(2026-09-17) it is never part of a gate, the suite or a sync step. The lasting arbiter for the fix is
`AudioDecodeFormatTest` (device-free). Run this when you want to *hear the numbers* after a change.

`SoundProbe.java` plays Forge's 39 effect assets through Forge's own sound code (the `Clip` pool of
`forge.sound.AudioClip`, or the alternate streaming path) or through `afplay`; `run_probe.py` records the
machine's output from a loopback device and scores each play. Run it after any change to Forge's sound
loading or a sync from upstream: with the 16-bit decode in place, the seven-draw burst through `clip`
shows 0 impulses and a peak near 0.31, like `afplay`; with the 8-bit decode it shows 2–6 impulses, 5–10
held-sample runs and a peak of 0.73–0.83. Recordings land in `out/` (gitignored).
