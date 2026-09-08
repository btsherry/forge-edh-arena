#!/usr/bin/env python3
"""arena-config.py — the launch banner: every knob in effect for this table,
its value, and whether it is the default. Printed once by arena-play.sh to
the terminal, saved to runner/logs/launch-config.txt (archived at teardown),
and copied to the head of run_table.out and gui.out. Secrets are shown as
set/unset only.

Usage: arena-config.py [--mode all-ai|human] [--deck SLUG] [--model M] [--effort E]
                       [--timeout N] [--advisor 0|1] [--voice on|off]
                       [--stops quick|full|keep|restore] [--linger N] [--autostop 0|1]
                       [--out FILE]

The DEFAULTS table below mirrors the defaults in the code; tests/test_hardening.py
scans the sources and fails when they drift apart.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROSTER = "urza-lord-high-artificer giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds"

# (name, default, one-line meaning). Grouped for the banner.
KNOBS = {
    "seats (the AI brains)": [
        ("SEAT_MODEL", "opus", "Claude model for every AI seat (arena-play --model)"),
        ("SEAT_EFFORT", "medium", "reasoning effort pinned per seat (arena-play --effort)"),
        ("ARENA_MAILBOX_TIMEOUT", "90", "seconds the engine waits for a seat before stock answers (arena-play --timeout)"),
        ("ARENA_BRAIN_TRANSPORT", "persistent", "persistent = one long-lived claude process per seat; spawn = a process per call"),
        ("ARENA_REACT_LOW_EFFORT", "on", "unthreatened reaction windows are answered at low effort"),
        ("ARENA_ROTATE_TOKENS", "250000", "fresh session (dossier + game record) at the next turn boundary past this many tokens"),
        ("ARENA_ROTATE_HARD", "600000", "rotate mid-turn past this many tokens"),
        ("ARENA_SEAT_DECKS", ROSTER, "four deck slugs in seat order (the table roster)"),
        ("ARENA_SEAT_MODELS", "", "per-seat model overrides; or/<vendor>/<model> = OpenRouter (API-billed)"),
        ("SEAT_SPECULATIVE", "0", "brain-authored turn plans executed locally (experimental)"),
        ("SEAT_REACT_HOLD", "0", "brain-armed same-turn reaction hold posture (experimental)"),
    ],
    "human game (advisor + autopass)": [
        ("ARENA_AUTOPASS", "casts", "off | strict | casts — which of your priority stops the engine passes for you"),
        ("ARENA_AUTOPASS_RESOLVE_OWN", "off", "on = also pass while your own spell resolves in your main phase (mains are sacred: off)"),
        ("ARENA_AUTOPASS_RECEIPTS", "all", "all | summary | off — auto-pass receipts in the Advisor panel"),
        ("ARENA_ADVISOR_TOOLS", "on", "the advisor may read the public game state with its tool"),
        ("ARENA_ADVISOR_ROTATE_TOKENS", "400000", "advisor session rotation threshold"),
    ],
    "voice": [
        ("ARENA_VOICE", "on", "the advisor's voice (arena-play --no-voice = off)"),
        ("ELEVENLABS_API_KEY", "", "live spoken advice needs it; stock phrases play without it"),
        ("ARENA_VOICE_FORMAT", "pcm_24000", "ElevenLabs output; PCM needs no decoder"),
        ("ARENA_VOICE_FX", "on", "on = film effects (ffmpeg when present, else the lite chain) | lite | off"),
        ("ARENA_VOICE_MODEL", "eleven_flash_v2_5", "ElevenLabs model"),
        ("ARENA_VOICE_ID", "", "override the voice (id or library name); default from the stock manifest"),
        ("ARENA_VOICE_SFX", "on", "the bleeps before a line"),
        ("ARENA_VOICE_YOUR_MOVE", "on", "the 'your move' line at your priority"),
        ("ARENA_VOICE_COLOR", "some", "off | some | all — spoken recaps on opponents' turns"),
        ("ARENA_VOICE_COLOR_P", "0.5", "probability a recap is spoken when COLOR=some"),
        ("ARENA_VOICE_MIN_GAP", "8", "seconds between spoken lines"),
        ("ARENA_VOICE_MAX_CHARS", "20000", "live characters per run before the voice goes stock-only"),
        ("ARENA_VOICE_GLITCH", "light", "off | light | heavy — the radio glitch"),
    ],
    "backends (optional, API-billed)": [
        ("OPENROUTER_API_KEY", "", "needed by or/ seats"),
        ("ARENA_OAI_BASE_URL", "", "OpenAI-compatible endpoint for oai/ seats"),
    ],
    "teardown watcher": [
        ("ARENA_AUTOSTOP_POLL", "5", "seconds between game-over checks"),
        ("ARENA_AUTOSTOP_GUI_GONE_LINGER", "10", "seconds after the GUI vanishes before teardown"),
    ],
}
SECRET = {"ELEVENLABS_API_KEY", "OPENROUTER_API_KEY", "ARENA_OAI_API_KEY"}


def git_stamp() -> str:
    try:
        b = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{b} @ {h}" if h else "not a git checkout"
    except Exception:  # noqa: BLE001
        return "git unavailable"


def render(args, env=os.environ) -> str:
    out = []
    out.append(f"== ARENA LAUNCH CONFIG  {time.strftime('%Y-%m-%d %H:%M:%S %z')}  ({git_stamp()}) ==")
    if args.mode:
        line = f"  game: {args.mode}"
        if args.model:
            line += f" | model {args.model} | effort {args.effort} | timeout {args.timeout}s"
        out.append(line)
        if args.mode == "human":
            voice = args.voice or "on"
            if voice != "off":
                voice += " (live advice " + ("on" if env.get("ELEVENLABS_API_KEY", "").strip() else "off: no ELEVENLABS_API_KEY") + ")"
            out.append(f"  human: deck {args.deck} | advisor {'on' if args.advisor == '1' else 'off'} | voice {voice}"
                       f" | opponent-turn stops {args.stops or 'keep'} | linger {args.linger}s | auto-stop {'on' if args.autostop != '0' else 'off'}")
        else:
            out.append(f"  spectator: linger {args.linger}s | auto-stop {'on' if args.autostop != '0' else 'off'}")
    changed = []
    for group, rows in KNOBS.items():
        out.append(f"  -- {group}")
        for name, default, meaning in rows:
            raw = env.get(name)
            if name in SECRET:
                val = "set" if (raw or "").strip() else "unset"
                mark = ""
            elif raw is None or raw == "":
                val = default if default else "(unset)"
                mark = "  [default]"
            else:
                val = raw
                mark = "  [default]" if raw == default else f"  [SET — default {default or '(unset)'}]"
                if raw != default:
                    changed.append(name)
            out.append(f"     {name}={val}{mark}   {meaning}")
    out.append("  changed from defaults: " + (", ".join(changed) if changed else "none"))
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ("--mode", "--deck", "--model", "--effort", "--timeout", "--advisor", "--voice", "--stops", "--linger", "--autostop", "--out"):
        ap.add_argument(flag, default="")
    args = ap.parse_args()
    text = render(args)
    sys.stdout.write(text)
    if args.out:
        try:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text)
        except OSError as e:
            print(f"arena-config: could not write {args.out}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
