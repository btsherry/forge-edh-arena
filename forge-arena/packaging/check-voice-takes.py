#!/usr/bin/env python3
"""check-voice-takes.py — packager preflight (C5, 2026-09-14). Every phrase id in
every manifest under <DEST>/forge-arena/runner/voice/stock/voices/**/manifest.json
must have its baked take(s) beside the manifest: wording 1 is <id>.wav, wording
N>1 is <id>-N.wav (the names build_stock.py bakes — see variant_name() there; a
phrase's "text" is one string or a list of wordings). A manifest line with no
audio would ship as a bark the runner can never play.

Usage: check-voice-takes.py <DEST>     exit 0 when complete, 1 listing every missing take
"""
from __future__ import annotations

import json
import os
import sys

VOICES_REL = os.path.join("forge-arena", "runner", "voice", "stock", "voices")


def expected_stems(manifest: dict) -> list[str]:
    """Every take stem a manifest promises, in manifest order."""
    stems = []
    for pid, ph in (manifest.get("phrases") or {}).items():
        text = ph.get("text", "") if isinstance(ph, dict) else ""
        n = len(text) if isinstance(text, list) else 1
        stems += [pid if k == 1 else f"{pid}-{k}" for k in range(1, max(n, 1) + 1)]
    return stems


def missing_takes(dest: str) -> list[str]:
    """"<library>: <stem>" for every promised take with no .wav in DEST; an
    unreadable manifest is reported as missing too (it would fail the runner)."""
    root = os.path.join(dest, VOICES_REL)
    out = []
    for dirpath, dirnames, filenames in sorted(os.walk(root)):
        dirnames.sort()
        if "manifest.json" not in filenames:
            continue
        lib = os.path.relpath(dirpath, root)
        try:
            with open(os.path.join(dirpath, "manifest.json"), encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError) as e:
            out.append(f"{lib}: manifest.json unreadable ({e})")
            continue
        have = set(filenames)
        out += [f"{lib}: {stem}" for stem in expected_stems(m) if f"{stem}.wav" not in have]
    return out


def main() -> int:
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        print(__doc__, file=sys.stderr)
        return 2
    if not os.path.isdir(os.path.join(sys.argv[1], VOICES_REL)):
        print(f"check-voice-takes: no voice tree under {sys.argv[1]} — nothing to check", file=sys.stderr)
        return 1
    missing = missing_takes(sys.argv[1])
    if missing:
        print(f"check-voice-takes: {len(missing)} take(s) promised by a manifest are missing from the package:", file=sys.stderr)
        for line in missing:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("check-voice-takes: every manifest phrase has its baked take(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
