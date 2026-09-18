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
scans the sources and fails when they drift apart. The voice's tuning numbers are
not knobs: they live in runner/voice/stock/voices/tuning.json (one row below points
at it; tests/test_tuning.py holds that file to the code).
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
TUNING_FILE = "runner/voice/stock/voices/tuning.json"     # the voice numbers live here, not in the environment (2026-09-16)

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
        ("ARENA_AUTOPASS_RECEIPTS", "summary", "summary (one line per turn) | all (every stop) | off — auto-pass receipts in the Advisor panel"),
        ("ARENA_ADVISOR_TOOLS", "on", "the advisor may read the public game state with its tool"),
        ("ARENA_ADVISOR_ROTATE_TOKENS", "400000", "advisor session rotation threshold"),
    ],
    "voice": [
        ("ARENA_VOICE", "on", "the table's voices — the seat voices, Joshua's lines, and Joshua at the fourth seat on an all-AI table (arena-play --no-voice = start muted; the runner still keeps the deal ledger)"),
        ("ARENA_CHATTER", "normal", "quiet | normal | lively | rowdy (or a number) — one dial for how much the table talks (measured: rowdy ≈ 6 seat lines/min at a human table, 7–8 all-AI; normal ≈ 2.5–3): sets the talk budget (speaking fraction of the last minute: .09 / .18 / .27 / .36) the governor spends, shortens the gap, lowers the reaction thresholds; advice frequency is untouched"),
        ("ELEVENLABS_API_KEY", "", "only Joshua's LIVE lines (advice, colour, deal reads) need it; every seat voice and every baked take plays without it (game 52)"),
        ("ARENA_VOICE_FORMAT", "pcm_24000", "ElevenLabs output; PCM needs no decoder"),
        ("ARENA_VOICE_FX", "on", "on = film effects (ffmpeg when present, else the lite chain) | lite | off"),
        ("ARENA_VOICE_MODEL", "eleven_flash_v2_5", "ElevenLabs model"),
        ("ARENA_VOICE_ID", "", "override the voice (id or library name); default from the stock manifest"),
        ("ARENA_VOICE_SFX", "on", "the bleeps before a line"),
        ("ARENA_VOICE_YOUR_MOVE", "some", "on | some | off — the 'your move' line at your priority (some = about six turns in ten; four wordings, never the same twice running)"),
        ("ARENA_VOICE_MAX_CHARS", "20000", "live characters per run before the voice goes stock-only"),
        ("ARENA_VOICE_GLITCH", "light", "off | light | heavy — the radio glitch"),
        ("ARENA_VOICE_FOCUS", "on", "on | off — the match screen brings a talking seat's field tab forward, then puts your tab back"),
    ],
    "seat barks (the AI seats' voices; any mode, whenever ARENA_VOICE is on)": [
        ("ARENA_BARKS", "some", "off | some | all — the AI seats speak in their own voices (Harry, Bill, Lily, and Joshua on an all-AI table; by deck via voices/assign.json): openers, reactions, table talk, card lines, deals, exchanges; no advisor needed"),
        # Not a variable: the file that holds every number the talk runs on (2026-09-16, hardening plan §2 —
        # the 24 ARENA_BARKS_* / ARENA_VOICE_PATTER* / DUTY / COLOR / MIN_GAP / TABLE_P knobs retired into it).
        (TUNING_FILE, "", "the numbers the talk runs on, as data — the gap between lines (8 s), the odds of a bark, an opener, a reaction to your play, a recap or 'your move', the swing/hit thresholds, the seat guard, the human-turn budget, the patter clock's gap and rate, the slow-seat and big-mana lines, the chains' odds, decay, hop cap and beat; edit the file, not the environment (ARENA_CHATTER scales the pace ones)"),
    ],
    "backends (optional, API-billed)": [
        ("OPENROUTER_API_KEY", "", "needed by or/ seats"),
        ("ARENA_OAI_BASE_URL", "", "OpenAI-compatible endpoint for oai/ seats"),
    ],
    "diagnostics": [
        ("ARENA_JFR", "0", "1 = the GUI JVM records a Java Flight Recorder profile for the whole game (runner/logs/gui.jfr, archived with the game; `jfr summary <file>`)"),
    ],
    "teardown watcher": [
        ("ARENA_AUTOSTOP_POLL", "5", "seconds between game-over checks"),
        ("ARENA_AUTOSTOP_GUI_GONE_LINGER", "10", "seconds after the GUI vanishes before teardown"),
        ("ARENA_AUTOSTOP_VOICE_WAIT", "60", "at game over, how long to wait for the voice's final sign-off before tearing down"),
        ("ARENA_AUTOSTOP_AFTER_VOICE", "5", "seconds after the voice's last line before teardown (replaces the linger when a voice runner is up)"),
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


def _voices_line(env) -> str:
    """Who speaks as whom on an all-AI table (2026-09-16): the roster seated in order, Ben's associations, then the
    fallback order (Joshua sits only here). Best effort — a banner never fails a launch."""
    try:
        sys.path.insert(0, str(ROOT / "runner"))
        import voice.table as T  # noqa: E402
        decks = T.table_from_launcher("", env.get("ARENA_SEAT_DECKS") or ROSTER, all_ai=True)
        voices = T.load_seat_libraries(seat_decks=decks, human_seat=None)          # the one rule (voice/table.py, 2026-09-17)
        who = {d: c.get("say") or d for d, c in (T.load_address().get("commanders") or {}).items()}
        return ", ".join(f"{who.get(decks[s], decks[s]).split(',')[0]}={v['voice']}" for s, v in sorted(voices.items()) if s in decks)
    except Exception:  # noqa: BLE001
        return ""


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
            advisor = "on" if args.advisor == "1" else "off (table relay on)"
            out.append(f"  human: deck {args.deck} | advisor {advisor} | voice {voice}"
                       f" | opponent-turn stops {args.stops or 'keep'} | linger {args.linger}s | auto-stop {'on' if args.autostop != '0' else 'off'}")
        else:
            voice = args.voice or "on"
            if voice != "off":
                voice += f" (chatter {env.get('ARENA_CHATTER') or 'normal'}, barks {env.get('ARENA_BARKS') or 'some'})"
                voices = _voices_line(env)
                if voices:
                    voice += f" | voices {voices}"
            out.append(f"  spectator: four brains, no advisor | voice {voice} | linger {args.linger}s | auto-stop {'on' if args.autostop != '0' else 'off'}")
    changed = []
    for group, rows in KNOBS.items():
        if args.mode == "all-ai" and group.startswith("human game"):
            continue                                          # game 55: the human section has no meaning at a four-brain table
        out.append(f"  -- {group}")
        for name, default, meaning in rows:
            if "/" in name:                                   # a file the numbers live in, not a variable to set
                out.append(f"     {name}   {meaning}")
                continue
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
