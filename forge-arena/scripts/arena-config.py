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
        ("ARENA_AUTOPASS_RECEIPTS", "summary", "summary (one line per turn) | all (every stop) | off — auto-pass receipts in the Advisor panel"),
        ("ARENA_ADVISOR_TOOLS", "on", "the advisor may read the public game state with its tool"),
        ("ARENA_ADVISOR_ROTATE_TOKENS", "400000", "advisor session rotation threshold"),
    ],
    "voice": [
        ("ARENA_VOICE", "on", "the advisor's voice (arena-play --no-voice = off)"),
        ("ARENA_CHATTER", "normal", "quiet | normal | lively | rowdy (or a number) — one dial for how much the table talks: sets the talk budget (speaking fraction of the last minute: .09 / .18 / .27 / .36) the governor spends, shortens the gap, lowers the reaction thresholds; advice frequency is untouched"),
        ("ARENA_VOICE_DUTY", "", "talk budget override: the fraction of the last minute somebody may be speaking (e.g. 0.25); empty = derived from ARENA_CHATTER"),
        ("ARENA_VOICE_DUTY_HUMAN", "0.4", "the talk budget on the human's turn, as a multiple of the budget (0.4 = well under half)"),
        ("ARENA_BARKS_HUMAN_P", "0.7", "chance a seat reacts to the HUMAN's play — a big attack, a game changer, the commander, a big spell, spot removal"),
        ("ELEVENLABS_API_KEY", "", "live spoken advice needs it; stock phrases play without it"),
        ("ARENA_VOICE_FORMAT", "pcm_24000", "ElevenLabs output; PCM needs no decoder"),
        ("ARENA_VOICE_FX", "on", "on = film effects (ffmpeg when present, else the lite chain) | lite | off"),
        ("ARENA_VOICE_MODEL", "eleven_flash_v2_5", "ElevenLabs model"),
        ("ARENA_VOICE_ID", "", "override the voice (id or library name); default from the stock manifest"),
        ("ARENA_VOICE_SFX", "on", "the bleeps before a line"),
        ("ARENA_VOICE_YOUR_MOVE", "some", "on | some | off — the 'your move' line at your priority (some = about six turns in ten; four wordings, never the same twice running)"),
        ("ARENA_VOICE_YOUR_MOVE_P", "0.6", "probability 'your move' is spoken on a turn when YOUR_MOVE=some"),
        ("ARENA_VOICE_COLOR", "some", "off | some | all — spoken recaps on opponents' turns"),
        ("ARENA_VOICE_COLOR_P", "0.5", "probability a recap is spoken when COLOR=some"),
        ("ARENA_VOICE_MIN_GAP", "8", "seconds between spoken lines"),
        ("ARENA_VOICE_MAX_CHARS", "20000", "live characters per run before the voice goes stock-only"),
        ("ARENA_VOICE_GLITCH", "light", "off | light | heavy — the radio glitch"),
        ("ARENA_VOICE_FOCUS", "on", "on | off — the match screen brings a talking seat's field tab forward, then puts your tab back"),
    ],
    "seat barks (the AI seats' voices; advisor on + unmuted)": [
        ("ARENA_BARKS", "some", "off | some | all — the AI seats speak in their own voices (seat 1 Harry, 2 Bill, 3 Lily): after their own turns, at big attacks, hits and counters"),
        ("ARENA_BARKS_P", "0.85", "probability a bark that was called for is spoken when BARKS=some"),
        ("ARENA_BARKS_OPENER_P", "0.35", "probability a seat opens its turn with a line (0 = never)"),
        ("ARENA_BARKS_SWING", "6", "total attacking power that earns an instant 'big swing' (or three attackers)"),
        ("ARENA_BARKS_HIT", "8", "damage to a player in one step that earns an instant reaction"),
        ("ARENA_BARKS_COOLDOWN", "10", "seconds before the same seat speaks again (a guard, not a pacing knob)"),
        ("ARENA_BARKS_CHAIN_P", "0.6", "interaction chains: chance a spoken line gets a reply (the first hop)"),
        ("ARENA_BARKS_CHAIN_DECAY", "0.5", "each further hop multiplies the chance by this"),
        ("ARENA_BARKS_CHAIN_MAX", "3", "most hops in one exchange (reply, counter-reply, last word)"),
        ("ARENA_BARKS_CHAIN_GAP", "0.25", "seconds between the lines of an exchange, a retort's beat (the normal gap is ARENA_VOICE_MIN_GAP)"),
        ("ARENA_BARKS_CHAIN_HUMAN_P", "0.5", "multiplier on a chain the human's own play started (so the table doesn't feel like it gangs up)"),
        ("ARENA_VOICE_PATTER", "on", "on | off — the patter clock: when nothing has played for a while a seat says something about the board, or filler"),
        ("ARENA_VOICE_PATTER_GAP", "5-7", "seconds of silence (a range, drawn each time) before the table fills it"),
        ("ARENA_VOICE_PATTER_HUMAN", "0.33", "patter rate during the human's turn (0.33 = a third as often; reactions to the human's plays are unaffected)"),
        ("ARENA_VOICE_PATTER_AFTER_ADVICE", "6", "seconds of patter silence after an advisor line, so advice is never talked over"),
        ("ARENA_BARKS_SLOW", "20", "a seat with a decision pending this many seconds gets told to play faster"),
        ("ARENA_BARKS_MANA", "8", "floating this much mana earns an instant 'big mana' line"),
    ],
    "backends (optional, API-billed)": [
        ("OPENROUTER_API_KEY", "", "needed by or/ seats"),
        ("ARENA_OAI_BASE_URL", "", "OpenAI-compatible endpoint for oai/ seats"),
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
