#!/usr/bin/env python3
"""Voice runner — the advisor's voice (Joshua / W.O.P.R. register).

A stdlib-only daemon on the same one-way file seam as everything else: it
READS the advisor's structured stream and the engine's observer snapshot,
decides what deserves a spoken line, and plays it on the Mac's default
output. It never writes to the mailbox, so the game can never wait on it.

Sources
  runner/logs/advisor-0.jsonl   advice (first sentence, LIVE), ask answers
                                (LIVE), quip records the advisor emits
                                (STOCK phrase by id), colour recaps (LIVE, some
                                of them — this is what speaks on opponents' turns)
  mailbox/observer-state.json   game start → "startup" stock line; the human's
                                turn beginning → "your-move" (low priority);
                                eliminations → "player-eliminated"; the human's own
                                elimination → one of manifest.human_out; game over →
                                win: "you-win" + "game-over-gg", loss:
                                "strange-game" + "game-over-gg"
  runner/logs/control/voice.json  {"enabled": false} mutes (written by
                                --mute / --unmute or the GUI later)

Rendering
  STOCK  runner/voice/stock/<id>.wav — shipped, pre-rendered, FX baked in.
  CACHE  runner/logs/cache/voice/<sha1>.wav — every live line is kept, keyed
         by text+voice+model+fx; a repeated line never costs again.
  LIVE   ElevenLabs Flash v2.5 (`eleven_flash_v2_5`) over HTTPS, MP3 in,
         ffmpeg → WAV + the stock FX chain (skipped when ffmpeg is absent).
         Only with ELEVENLABS_API_KEY set; otherwise the daemon is stock-only.

Discipline (Ben, 2026-09-07): it should not talk constantly — at most one
utterance per ARENA_VOICE_MIN_GAP seconds (default 8), one at a time, newest
high-priority item wins, advice for a window the human already answered is
dropped, a random terminal bleep precedes each line (ARENA_VOICE_SFX=off to
silence them).

Env knobs
  ELEVENLABS_API_KEY        live rendering on (never logged)
  ARENA_VOICE_ID            voice to render with (default: the shipped voice id)
  ARENA_VOICE_MODEL         default eleven_flash_v2_5
  ARENA_VOICE_MIN_GAP       seconds between utterances (8)
  ARENA_VOICE_MAX_CHARS     live characters per game before stock-only (20000)
  ARENA_VOICE_SFX           on|off bleeps (on)
  ARENA_VOICE_FX            on|off the film FX chain on live lines (on)
  ARENA_VOICE_GLITCH        off|light|heavy stutters and hitches on every line (light)
  ARENA_VOICE_YOUR_MOVE     on|off "Your move." at the human's turns (on)
  ARENA_VOICE_COLOR         off|some|all — voice the per-turn recap (opponents' turns too); some = probability ARENA_VOICE_COLOR_P (0.5)

CLI
  voice_runner.py                       run the daemon
  voice_runner.py --play startup        play a stock phrase and exit
  voice_runner.py --say "text"          render (cache/live) + play one line, exit
  voice_runner.py --mute | --unmute     flip control/voice.json
  voice_runner.py --dry-run             log what would be spoken, play nothing

Layout (2026-09-14, voicework2 hardening plan Phase 0a) — split with no behaviour change:
  runner/voice/renderer.py    Player, Renderer, the WAV/FX/glitch helpers, STOCK/VOICES_DIR
  runner/voice/table.py       seat <-> voice assignment, addressing, decks' cards and combos
  runner/voice/scheduler.py   SchedulerMixin — the queue, the governor, the guards, chains, patter
  runner/voice/events.py      EventsMixin — the advisor stream, the snapshot, the event ring, the game log
  this file                   VoiceRunner (state, the play step, the loop) and the CLI; it
                              re-exports every public name, so `voice_runner.X` keeps working.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil        # kept importable as voice_runner.shutil / .subprocess / .urllib: the tests patch
import subprocess    # the stdlib modules through these attributes (the renderer sees the same objects)
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent          # forge-arena/runner
sys.path.insert(0, str(HERE))
from chains import ChainTable, plan_reply  # noqa: E402
ARENA = HERE.parent
from voice.renderer import (  # noqa: E402,F401 — re-exported (voice_runner.X)
    STOCK, VOICES_DIR, DEFAULT_VOICE_ID, cache_key, wav_seconds, GLITCH_LEVELS, pcm_to_wav, lite_fx_wav, glitch_wav,
    Player, Renderer)
from voice.table import (  # noqa: E402,F401 — re-exported
    TABLE_LIB, TABLE_P, LIFE_STEPS, CARD_LIB, CARD_SWAP, CARD_REACTIONS, load_libraries, load_assignments,
    assign_voices, load_seat_libraries, DEFAULT_TABLE, seat_decks_from_roster, game_changers_of, deck_cards_of,
    card_kind, load_address, who_for_deck, card_slug, load_combo_index, deck_combos_of, life_pid, hand_pid,
    seat_decks_from_game_log)
from voice.scheduler import (  # noqa: E402,F401 — re-exported
    PRIORITY, CHAIN_HOP_PRIORITY, BARK_PRIORITY, DUTY_BASE, DUTY_WINDOW_S, DUTY_HUMAN_MULT, SILENCE_FLOOR_S,
    QUESTION_LINES, QUESTION_PREFIXES, PROPOSAL_LINES, PROPOSAL_PREFIXES, PROPOSAL_P, PROPOSAL_TARGET_P,
    PROPOSAL_REPLIES, PROPOSAL_TARGET_REPLIES, OPTIONAL_FLOOR, OPTIONAL_SOURCES, RARE_REPEATS, OWN_ACTION_LINES,
    LIFE_FOLLOWUP, STATE_ANSWERS, ADDRESS_SWAP, DEAL_TURNS, LONG_GAME_TURN, LETHAL_POWER, IDLE_S, IDLE_SLOWDOWN,
    MULL_LINE, MULL_P, MULL_SCREW_WORDS, MULL_DIG_WORDS, RECENT_S, PATTER_REPEAT_S, RECENT_WEIGHT, CHATTER_LEVELS,
    chatter_level, SchedulerMixin)
from voice.events import (  # noqa: E402,F401 — re-exported
    FIRST_SENTENCE_MAX, ASK_MAX, LOOP_AT, THINK_S, NARRATIONS_PER_TURN, GRUDGE_EVERY, ELIM_SEAT_P, first_sentence,
    EventsMixin)
from voice.atoms import AtomsMixin
POLL_S = 0.5
CHAIN_POLL_S = 0.1          # while an exchange hop is pending: a retort's beat is ~0.5 s, so poll fast


# ---- the daemon --------------------------------------------------------------------

class VoiceRunner(SchedulerMixin, EventsMixin, AtomsMixin):
    """The daemon: the state every mixin reads, the play step (speak), the loop (step/run).
    Queue policy lives in voice.scheduler.SchedulerMixin, the sources in voice.events.EventsMixin."""

    def __init__(self, logs_dir: Path, mailbox_dir: Path, dry_run: bool = False, fake_tts=None, player=None, clock=time.monotonic):
        self.logs = logs_dir
        self.mailbox = mailbox_dir
        self.dry_run = dry_run
        self.clock = clock
        self.human_seat = 0
        self._log_path = logs_dir / "voice-0.log"
        self._jsonl = logs_dir / "voice-0.jsonl"
        self._control = logs_dir / "control" / "voice.json"
        self.rng = random.Random()
        self.renderer = Renderer(logs_dir / "cache" / "voice", log=self.say, fake_tts=fake_tts,
                                 record=self.record, clock=clock, rng=self.rng)
        self.player = player or Player(dry_run=dry_run, log=self.say)
        self.chatter = chatter_level(os.environ.get("ARENA_CHATTER", "normal"))
        self.min_gap = float(os.environ.get("ARENA_VOICE_MIN_GAP", "8"))
        self.sfx_on = os.environ.get("ARENA_VOICE_SFX", "on").lower() != "off"
        # "Your move" (Ben, 2026-09-10: "cool the first time, okay the second, lame
        # every time after"): on = every turn | some = about YOUR_MOVE_P of turns |
        # off; the wordings come from a shuffle bag either way.
        self.your_move_mode = os.environ.get("ARENA_VOICE_YOUR_MOVE", "some").lower()
        if self.your_move_mode not in ("on", "some", "off"):
            self.your_move_mode = "some"
        self.your_move_p = float(os.environ.get("ARENA_VOICE_YOUR_MOVE_P", "0.6"))
        # Seat barks (2026-09-10): the advisor tags [bark:<seat>:<id>] on its
        # replies; the seat's static voice (voices/<lib>/) says its own wording.
        # Advisor off or muted => nothing (both already silence this runner).
        self.barks_mode = os.environ.get("ARENA_BARKS", "some").lower()
        if self.barks_mode not in ("off", "some", "all"):
            self.barks_mode = "some"
        self.barks_p = float(os.environ.get("ARENA_BARKS_P", "0.85"))
        self.barks_cooldown = float(os.environ.get("ARENA_BARKS_COOLDOWN", "10"))
        self.barks_opener_p = float(os.environ.get("ARENA_BARKS_OPENER_P", "0.35"))
        self.barks_swing = int(os.environ.get("ARENA_BARKS_SWING", "6"))
        self.barks_hit = int(os.environ.get("ARENA_BARKS_HIT", "8"))
        # reactions to the HUMAN's plays (round 31: before this the seats ignored every card Ben cast)
        self.barks_human_p = float(os.environ.get("ARENA_BARKS_HUMAN_P", "0.7"))
        # the talk budget: ARENA_VOICE_DUTY overrides the dial's derived goal
        try:
            self.duty_target = float(os.environ.get("ARENA_VOICE_DUTY", "") or 0) or min(0.45, DUTY_BASE * self.chatter)
        except ValueError:
            self.duty_target = min(0.45, DUTY_BASE * self.chatter)
        self.duty_human = float(os.environ.get("ARENA_VOICE_DUTY_HUMAN", str(DUTY_HUMAN_MULT)))
        self._spoken_log: list[tuple[float, float]] = []       # (start, seconds) of every line played
        self.table_mult = float(os.environ.get("ARENA_TABLE_P", "1.0"))
        self._turn_start: dict[int, dict] = {}                 # seat -> {"lands", "casts", "narrations"} for the turn it is playing
        self._prev_snapshot: dict = {}
        self._stack_seen: set[tuple] = set()
        self._thought: set[str] = set()                        # decision requests already muttered about
        self._cards: dict[int, dict[str, dict]] = {}           # seat -> name -> card record (lazy)
        # memory (phase D): who keeps hitting whom, how often a seat was countered, how many wipes, who promised whom
        self._hits_from: dict[int, dict[int, int]] = {}
        self._countered_n: dict[int, int] = {}
        self._sweeps = 0
        self._deals: dict[tuple[int, int], object] = {}       # (a, b) -> the turn the truce was struck (both directions)
        self._heads_up_said = False
        self._gc_cast_seen: set[tuple[int, str]] = set()       # (seat, card) game changers already crowed about this game
        self._card_events_turn: dict[tuple[int, str], int] = {}  # (seat, card) -> casts + self-bounces this turn (a loop past LOOP_AT)
        self._mulls: dict[int, int] = {}                       # seat -> mulligans taken (from game.jsonl MULLIGAN records)
        self._kept_seven: list[int] = []
        self._human_mull_done = False
        self._game_log_pos = self._game_log_size()             # a (re)started runner never replays old decisions
        self._board_fp = None                                  # what the table sees; unchanged for IDLE_S = an idle table
        self._board_changed_at = self.clock()
        self._idle_noted = False
        self._said_this_turn: set[tuple[int, str]] = set()
        self._said_turn = None
        # Recency (game 44: "cards in hand" ten times in sixteen minutes, "good hand"
        # seven): a line said in the last RECENT_S is a weak candidate for anyone,
        # and a seat avoids a reply it used recently. The per-turn rule stays hard.
        self._said_at: dict[str, float] = {}                 # line id -> last time it was spoken (any seat)
        self._seat_said_at: dict[tuple[int, str], float] = {}
        self._event_seq = None      # last snapshot event seq consumed; None until the first read
        # The patter clock (Ben, 2026-09-10: "someone should say something every 5-7
        # seconds"): when the queue is empty and nothing has played for a randomized
        # gap, the runner itself picks a speaker and a line from what the board says
        # (a slow seat, the leader, a low seat, a big hand, a big board) or filler.
        # Five Game Knights episodes measured ~190 words/min with a silence over 4 s
        # only every ~78 s. Quieter on the human's turn; never over the advisor.
        self.patter_on = os.environ.get("ARENA_VOICE_PATTER", "on").lower() != "off"
        lo, _, hi = os.environ.get("ARENA_VOICE_PATTER_GAP", "5-7").partition("-")
        try:
            self.patter_gap = (float(lo), float(hi or lo))
        except ValueError:
            self.patter_gap = (5.0, 7.0)
        self.patter_human = float(os.environ.get("ARENA_VOICE_PATTER_HUMAN", "0.33"))     # rate on the human's turn
        self.patter_after_advice = float(os.environ.get("ARENA_VOICE_PATTER_AFTER_ADVICE", "6"))
        self.barks_slow = float(os.environ.get("ARENA_BARKS_SLOW", "20"))                  # a seat thinking this long gets told
        self.barks_mana = int(os.environ.get("ARENA_BARKS_MANA", "6"))                       # floating this much is "big mana"
        self._last_hit_by: dict[int, tuple[list[int], object]] = {}   # seat -> (hitters, turn) from the ring: kill attribution
        self._casts: dict[int, list[float]] = {}                      # seat -> recent cast times (a flurry earns "play slower")
        self._pool_high: set[int] = set()                             # seats currently over the big-mana line
        self._patter_anchor = None
        self._patter_due = 0.0
        self._advisor_spoke_at = -1e9
        # Game over (Ben, game 44: "they kept talking after the game was over"): the
        # winner's line, then Joshua's pair, then NOTHING — the runner locks.
        self.final_locked = False
        # interaction chains (Ben, 2026-09-10): a spoken line invites replies; see chains.py
        self.chains = ChainTable.load(VOICES_DIR)
        self._chain: dict | None = None      # {"origin": seat, "hop": n, "turn": t} while an exchange is running
        self._last_snapshot: dict = {}
        # the table: from the launcher at startup (ARENA_HUMAN_DECK + the roster), else
        # default seats until the game log names all three AI decks
        self._human_deck: str = os.environ.get("ARENA_HUMAN_DECK") or ""
        self._seat_decks: dict[int, str] = seat_decks_from_roster(self._human_deck, os.environ.get("ARENA_SEAT_DECKS", ""))
        self.seat_libraries = load_seat_libraries(seat_decks=self._seat_decks or None)
        self.game_changers: dict[int, set[str]] = self._table_game_changers()
        self.address = load_address()
        self._who: dict[int, str] = self._table_who()
        self.table_ids, self.card_ids = self._load_sub_ids()
        self._combo_index = load_combo_index()
        self._combo_sets: dict[int, list[tuple[frozenset, str]]] = {}   # seat -> the deck's combos (lazy)
        self._combos_done: dict[int, set[frozenset]] = {}
        self._bark_spoken_at: dict[int, float] = {}
        # Colour commentary (Ben, 2026-09-07: "it could say a thing during
        # opponents' turns some of the time"): the advisor's per-turn recap
        # arrives after every turn, the opponents' included. off | some | all;
        # "some" voices each recap with probability ARENA_VOICE_COLOR_P (0.5).
        self.color_mode = os.environ.get("ARENA_VOICE_COLOR", "some").lower()
        if self.color_mode not in ("off", "some", "all"):
            self.color_mode = "some"
        self.color_p = float(os.environ.get("ARENA_VOICE_COLOR_P", "0.5"))
        self.apply_chatter()
        self.queue: list[dict] = []
        self.last_spoken_at = -1e9
        # Start at the END of the advisor's stream: a (re)started runner speaks
        # new lines only — replaying history re-said the last quip after the
        # 2026-09-07 mid-game restart. A brand-new game's file is empty anyway.
        self._adv_pos, self._adv_inode = 0, None
        try:
            st = (logs_dir / "advisor-0.jsonl").stat()
            self._adv_pos, self._adv_inode = st.st_size, st.st_ino
        except OSError:
            pass
        self.answered: set[int] = set()     # advisor request seqs the human already answered
        self.game_id = None
        self.seen_turn = None
        self.seen_active = None
        self.eliminated: set[int] = set()
        self._seen_seats: set[int] = set()                    # every seat the snapshot has ever listed
        self.game_over_said = False
        self.started_said = self._startup_already_spoken()   # a restart never replays "would you like to play a game?"
        self._state_published = None
        self._live_published = None

    def apply_chatter(self) -> None:
        """The chatter dial sets the mechanical pace — the gap, the seat guard, the
        reaction thresholds, the patter clock, one more chain hop at lively+. It no
        longer pre-scales the probability knobs (round 31): the governor spends the
        dial's headroom at roll time, so the knobs stay what the operator wrote."""
        k = self.chatter
        if k == 1.0:
            return
        if k > 0:
            self.min_gap = max(3.0, self.min_gap / k)
            self.barks_swing = max(3, round(self.barks_swing / k))
            self.barks_hit = max(4, round(self.barks_hit / k))
            self.patter_gap = (max(2.0, self.patter_gap[0] / k), max(2.5, self.patter_gap[1] / k))
            self.barks_cooldown = max(3.0, self.barks_cooldown / k)   # game 44: the 10 s guard silenced 15 barks at rowdy
        if k >= 1.5 and self.chains is not None:
            self.chains.max_hops += 1           # a livelier table talks back one more time

    def _game_log_size(self) -> int:
        try:
            return (self.logs / "game.jsonl").stat().st_size
        except OSError:
            return 0

    def _startup_already_spoken(self) -> bool:
        try:
            with self._jsonl.open("rb") as f:
                return any(b'"event": "spoke"' in line and b'"stock": "startup"' in line for line in f)
        except OSError:
            return False

    def _table_who(self) -> dict[int, str]:
        out = {k: who_for_deck(self.address, v) for k, v in self._seat_decks.items()}
        if self._human_deck:
            out[self.human_seat] = who_for_deck(self.address, self._human_deck)
        return {k: v for k, v in out.items() if v}

    def _load_sub_ids(self) -> tuple[set[str], set[str]]:
        """The ids of the table and cards sub-libraries (the union over the seated voices)."""
        out = {TABLE_LIB: set(), CARD_LIB: set()}
        for info in self.seat_libraries.values():
            for sub in out:
                try:
                    out[sub] |= set(json.loads((VOICES_DIR / info["library"] / sub / "manifest.json").read_text()).get("phrases") or {})
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        return out[TABLE_LIB], out[CARD_LIB]

    def lib_for(self, seat: int, pid: str) -> str:
        """The library a seat says a line from: its own, or the sub-library that carries the id."""
        lib = self.library_for_seat(seat)
        if not lib:
            return ""
        if pid in self.table_ids:
            return f"{lib}/{TABLE_LIB}"
        if pid in self.card_ids:
            return f"{lib}/{CARD_LIB}"
        return lib

    def combos_of(self, seat: int) -> list[tuple[frozenset, str]]:
        seat = int(seat)
        if seat not in self._combo_sets:
            slug = self._human_deck if seat == self.human_seat else self._seat_decks.get(seat, "")
            self._combo_sets[seat] = deck_combos_of(slug, self._combo_index) if slug else []
        return self._combo_sets[seat]

    def cards_of(self, seat: int) -> dict[str, dict]:
        seat = int(seat)
        if seat not in self._cards:
            slug = self._human_deck if seat == self.human_seat else self._seat_decks.get(seat, "")
            self._cards[seat] = deck_cards_of(slug) if slug else {}
        return self._cards[seat]

    def table_p(self, key: str) -> float:
        return min(1.0, TABLE_P.get(key, 0.3) * self.table_mult)

    def _table_game_changers(self) -> dict[int, set[str]]:
        out = {k: game_changers_of(v) for k, v in self._seat_decks.items()}
        if self._human_deck:
            out[self.human_seat] = game_changers_of(self._human_deck)     # the table reacts to the human's game changers too
        return out

    # -- output
    def say(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            self.logs.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def record(self, event: str, **body) -> None:
        """voice-0.jsonl: {"event": spoke|dropped|skipped, "kind": <item kind>, …}."""
        try:
            with self._jsonl.open("a") as f:
                f.write(json.dumps({"ts": round(time.time(), 3), "event": event, **body}) + "\n")
        except OSError:
            pass

    # -- control
    def enabled(self) -> bool:
        """Voice is on unless control/voice.json mutes it OR the Advisor panel's
        pause toggle (control/advisor.json {"enabled": false}) is set — pausing
        the advisor silences EVERY line: advice, quips, colour, your-move, the
        elimination and game-over lines, the bleeps (Ben, 2026-09-08)."""
        try:
            if not bool(json.loads(self._control.read_text()).get("enabled", True)):
                return False
        except (OSError, ValueError):
            pass
        try:
            adv = self._control.parent / "advisor.json"
            if adv.exists() and not bool(json.loads(adv.read_text()).get("enabled", True)):
                return False
        except (OSError, ValueError):
            pass
        return True

    def executive_on(self) -> bool:
        """control/executive.json {"on": true}: the advisor is playing the
        human's seat, so "Your move." would be addressed to nobody."""
        try:
            return bool(json.loads((self._control.parent / "executive.json").read_text()).get("on", False))
        except (OSError, ValueError):
            return False

    def _play(self, path: Path) -> None:
        """Play through the configured player; a player that does not take the
        stop poll (test fakes, custom players) is called the old way."""
        try:
            self.player.play(path, should_stop=lambda: not self.enabled())
        except TypeError:
            self.player.play(path)

    def speak(self, item: dict) -> bool:
        path = None
        if item["stock"]:
            path = self.renderer.stock(item["stock"], item.get("library") or "")
        elif item["text"]:
            path = self.renderer.render(item["text"])
        if path is None:
            self.record("skipped", kind=item["kind"], why="no audio (stock missing or live off)", text=item["text"][:80], stock=item["stock"])
            return False
        # the typing bleeps belong to the mainframe: never before a seat's own voice (Ben, 2026-09-10)
        if self.sfx_on and not item.get("library"):
            bleep = self.renderer.sfx()
            if bleep is not None:
                self._play(bleep)
        secs = wav_seconds(path)
        self.publish_speaking(item, secs)
        self.start_backchannel(item, secs)              # a listener may murmur under the line (voice/atoms.py)
        self._play(path)
        self.publish_speaking(None, 0.0)
        self.last_spoken_at = self.clock()
        self._spoken_log.append((self.last_spoken_at - secs, secs))
        if item["kind"] in ("advice", "ask"):
            self._advisor_spoke_at = self.clock()
        if self.final_locked and not self.queue:
            self.publish_final()                      # the sign-off just played: the watcher may tear down
        if item.get("seat") is not None and item.get("library"):
            self._bark_spoken_at[int(item["seat"])] = self.clock()
            self._said_at[item["stock"]] = self.clock()
            self._seat_said_at[(int(item["seat"]), item["stock"])] = self.clock()
            generic = (item.get("ctx") or {}).get("generic")
            if generic:                                             # "deal-urza" was a "deal": the recency memory knows both
                self._said_at[generic] = self.clock()
                self._seat_said_at[(int(item["seat"]), generic)] = self.clock()
        self.record("spoke", kind=item["kind"], text=item["text"][:200], stock=item["stock"], seconds=round(secs, 2),
                    chars_used=self.renderer.chars_used, library=item.get("library") or "", seat=item.get("seat"),
                    file=path.name, duty=round(self.duty(), 2), goal=round(self.duty_goal(), 2), source=item.get("source", ""))
        who = f" seat {item['seat']} ({item['library']})" if item.get("library") else ""
        hop = f" (chain hop {item['chain']['hop']})" if item.get("chain") else ""
        self.say(f"[voice] {item['kind']}{who}{hop}: {item['stock'] or item['text'][:90]}" + (f" [{path.name}]" if item["stock"] and path.name != f"{item['stock']}.wav" else ""))
        self.after_spoken(item)
        return True

    # -- seat barks
    def learn_table(self) -> None:
        """Once the game log names the decks at the table, re-seat the voices by
        deck (Ben, 2026-09-10: Purphoros fiery, Urza cool, Giada warm)."""
        if getattr(self, "_table_confirmed", False):
            return
        decks = seat_decks_from_game_log(self.logs / "game.jsonl")
        ai = {k: v for k, v in decks.items() if k != self.human_seat}
        if len(ai) >= 3:                                      # the whole table: confirm, or correct the launcher's roster
            self._table_confirmed = True
            if ai != self._seat_decks:
                self._seat_decks = ai
                self.seat_libraries = load_seat_libraries(seat_decks=ai)
            self._human_deck = decks.get(self.human_seat) or self._human_deck
            self.game_changers = self._table_game_changers()
            self._who = self._table_who()
            self.table_ids, self.card_ids = self._load_sub_ids()
            self._cards.clear()
            self._combo_sets.clear()
            self.say("[voice] table: " + ", ".join(f"seat {k} {ai.get(k, '?')} -> {v['voice']}" for k, v in sorted(self.seat_libraries.items())))

    def library_for_seat(self, seat: int) -> str:
        info = self.seat_libraries.get(int(seat))
        return info["library"] if info else ""

    # -- loop
    def step(self) -> None:
        self.publish_state()
        if not self.enabled():
            self.stop_atoms()                            # a pending murmur or an under-line dies with the mute
            if self.queue:
                self.say(f"[voice] disabled — dropping {len(self.queue)} queued line(s)")
                self.queue = []
            return
        self.learn_table()
        self.scan_advisor()
        self.scan_observer()
        self.scan_game_log()
        self.mutter()
        self.heckle_human()                          # "we're waiting on you" (Ben: heckles are welcome; Joshua never answers)
        self.patter()
        item = self.next_item()
        if item is not None:
            self.speak(item)
        if self.final_locked and not self.queue:
            self.publish_final()                      # spoken or skipped, the sequence has drained

    def run(self) -> None:
        self.say(f"[voice] up — chatter={self.chatter:g}, stock {len(self.renderer.manifest.get('phrases', {}))} phrases, "
                 f"live={'on' if self.renderer.live else 'off (no ELEVENLABS_API_KEY)'}, min_gap={self.min_gap}s, "
                 f"fx={self.renderer.fx_mode}, format={self.renderer.format}, glitch={self.renderer.glitch}, sfx={'on' if self.sfx_on else 'off'}, color={self.color_mode}, "
                 f"your_move={self.your_move_mode}, barks={self.barks_mode}, patter={'off' if not self.patter_on else f'{self.patter_gap[0]:g}-{self.patter_gap[1]:g}s'}" + (f", chains p={self.chains.first_hop_p}/decay {self.chains.decay}/max {self.chains.max_hops}/gap {self.chains.gap_s}s" if self.chains else ", chains=off (no chains.json)")
                 + (f" (p={self.barks_p}, opener_p={self.barks_opener_p}, swing>={self.barks_swing}, hit>={self.barks_hit}, guard={self.barks_cooldown:.0f}s; " + ", ".join(f"seat {k} {v['voice']}" for k, v in sorted(self.seat_libraries.items())) + ")"
                    if self.barks_mode != "off" and self.seat_libraries else (" (no seat voice libraries found)" if self.barks_mode != "off" else "")))
        hb = self.mailbox / "seat-0-voice" / "heartbeat"
        hb.parent.mkdir(parents=True, exist_ok=True)

        def beat():
            while True:
                try:
                    hb.touch()
                except OSError:
                    pass
                time.sleep(5.0)
        threading.Thread(target=beat, name="voice-heartbeat", daemon=True).start()
        while True:
            try:
                self.step()
            except Exception as e:  # noqa: BLE001 — bookkeeping never ends the voice
                self.say(f"[voice] step error: {str(e)[:160]}")
            time.sleep(CHAIN_POLL_S if any(q.get("chain") for q in self.queue) else POLL_S)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=str(HERE / "logs"))
    ap.add_argument("--mailbox", default=str(ARENA / "mailbox"))
    ap.add_argument("--play", metavar="ID", help="play a stock phrase and exit")
    ap.add_argument("--say", metavar="TEXT", help="render (cache/live) and play one line, then exit")
    ap.add_argument("--mute", action="store_true")
    ap.add_argument("--unmute", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    vr = VoiceRunner(Path(a.logs), Path(a.mailbox), dry_run=a.dry_run)
    if a.mute or a.unmute:
        vr._control.parent.mkdir(parents=True, exist_ok=True)
        vr._control.write_text(json.dumps({"enabled": bool(a.unmute)}))
        print(f"[voice] {'unmuted' if a.unmute else 'muted'} ({vr._control})")
        return
    if a.play:
        vr.min_gap = 0
        ok = vr.speak({"kind": "quip", "text": "", "stock": a.play, "seq": None})
        sys.exit(0 if ok else 1)
    if a.say:
        vr.min_gap = 0
        ok = vr.speak({"kind": "ask", "text": a.say, "stock": "", "seq": None})
        sys.exit(0 if ok else 1)
    vr.run()


if __name__ == "__main__":
    main()
