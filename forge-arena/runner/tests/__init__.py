"""Offline test defaults: the persistent Claude transport is the production
default (2026-09-08) but tests monkeypatch `_run`, so they run the spawn path
unless a test opts in explicitly (ARENA_BRAIN_TRANSPORT set before import)."""
import os as _os
_os.environ.setdefault("ARENA_BRAIN_TRANSPORT", "spawn")
