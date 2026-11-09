"""Offline test defaults.

- The persistent Claude transport is the production default (2026-09-08) but tests monkeypatch
  `_run`, so they run the spawn path unless a test opts in explicitly (ARENA_BRAIN_TRANSPORT set
  before import).
- The runners under test print their log lines to stdout (`SeatRunner._say`, `VoiceRunner.say`,
  `AdvisorRunner._say`, build_stock); the suite swallows stdout so a run shows the results alone.
  `ARENA_TEST_STDOUT=1` keeps it (debugging with print()). unittest's own output is on stderr.
"""
import os as _os
import sys as _sys

_os.environ.setdefault("ARENA_BRAIN_TRANSPORT", "spawn")
if not _os.environ.get("ARENA_TEST_STDOUT"):
    _sys.stdout = open(_os.devnull, "w")
