#!/usr/bin/env python3
"""Voice runner — the table's one throat: Joshua (the advisor's voice, W.O.P.R.
register) and the three seat voices (Harry, Bill, Lily) the AI seats speak in.

A stdlib-only daemon on the same one-way file seam as everything else: it
READS the advisor's structured stream, the engine's observer snapshot (board
and public event ring), the seat runners' game log and the brains' own `say`
intents, decides what deserves a spoken line and who says it, and plays it on
the default output. It never writes anything the engine waits on: its one mailbox
output is the deal notes (mailbox/seat-<n>/notes/, below), advisory files a seat
runner folds into its next prompt.

Sources
  runner/logs/advisor-0.jsonl   advice (first sentence, LIVE), ask answers
                                (LIVE), quip records the advisor emits
                                (STOCK phrase by id), colour recaps (LIVE, some
                                of them — this is what speaks on opponents' turns),
                                the advisor's [bark:<seat>:<id>] tags
  mailbox/observer-state.json   game start → "startup" stock line; the human's
                                turn beginning → "your-move" (low priority);
                                eliminations → "player-eliminated" or the seat's
                                own exit line; the human's own elimination → one
                                of manifest.human_out; game over → the winner's
                                line, then win: "you-win" + "game-over-gg", loss:
                                "strange-game" + "game-over-gg", then NOTHING; the
                                event ring → instant seat reactions (a big swing, a
                                hit, a counter, a game changer, a combo online)
  runner/logs/game.jsonl        mulligans, the seat brains' `say` intents, the game id,
                                the brains' DEAL answers (accept / refuse / counter)
  runner/logs/control/voice.json  {"enabled": false} mutes (written by
                                --mute / --unmute or the GUI later)
  runner/logs/control/deal/     <ts>-accept.json {"offer_id"}: the player accepts a
                                seat's counter-offer (the advisor writes it; consumed)

Table deals (plan 2026-09-16 §11) — this runner OWNS the deal ledger: the live map (checkpointed), the
append-only runner/logs/deals.jsonl (struck / refused / counter / lapsed / broken / expired; archived
by arena-stop) and the notes that tell a seat's brain what was agreed — mailbox/seat-<n>/notes/
<ts_ms>-deal-struck|deal-broken|deal-lapsed.json, one JSON object each, which the seat runner renders
as a RUNNER NOTE and deletes (seat 0's only while the Executive plays it). The seat's answer is voiced
from the table sub-library (deal-with-you / no-deal-with-you / counter-offer; deal-over at a lapse;
you-broke-it at the human breaking one; i-broke-it when a seat breaks its own); under the Executive a
seat-0 answer is Joshua's (joshua-deal-yes/no/counter). See voice/scheduler.py (the ledger) and
voice/events.py (the sources and the break detection).

Rendering
  STOCK  runner/voice/stock/<id>.wav — shipped, pre-rendered, FX baked in;
         voices/<lib>/… the seat libraries (table/ and cards/ sub-libraries).
  CACHE  runner/logs/cache/voice/<sha1>.wav — every live line is kept, keyed
         by text+voice+model+fx; a repeated line never costs again.
  LIVE   ElevenLabs Flash v2.5 (`eleven_flash_v2_5`) over HTTPS, MP3 in,
         ffmpeg → WAV + the stock FX chain (skipped when ffmpeg is absent).
         Only with ELEVENLABS_API_KEY set; otherwise the daemon is stock-only.

Discipline (Ben, 2026-09-07): it should not talk constantly — at most one
utterance per min_gap_s (8 s, tuning.json), one at a time, newest
high-priority item wins, advice for a window the human already answered is
dropped, a random terminal bleep precedes each line (ARENA_VOICE_SFX=off to
silence them). The seats (2026-09-10 →): one owner per turn boundary, a
per-seat guard, a talk budget the chatter dial sets and the governor spends,
a patter clock with a silence floor, exchanges composed one hop at a time.

Knobs (2026-09-16, hardening plan §2 — five for the operator; the rest is data)
  ARENA_CHATTER             quiet|normal|lively|rowdy or a number (normal) — the ONE dial:
                            the pace (gap, guard, thresholds, patter gap) and the talk budget
  ARENA_BARKS               off|some|all — the seat voices (some)
  ARENA_VOICE_YOUR_MOVE     on|some|off — "Your move." at the human's turns (some)
  ARENA_VOICE_SFX           on|off the bleeps (on)
  ARENA_VOICE_FOCUS         on|off — the GUI brings a talking seat's tab forward (read by the GUI, not here)
  Joshua's render settings, not tuning: ELEVENLABS_API_KEY (never logged), ARENA_VOICE_ID,
  ARENA_VOICE_MODEL (eleven_flash_v2_5), ARENA_VOICE_FORMAT (pcm_24000), ARENA_VOICE_MAX_CHARS
  (20000), ARENA_VOICE_FX (on|lite|off), ARENA_VOICE_GLITCH (off|light|heavy).
  Launch plumbing: ARENA_HUMAN_DECK, ARENA_SEAT_DECKS (who sits where, so which voice is whose).
  EVERY OTHER NUMBER — the gap, the odds of a bark / opener / reaction / recap / "your move",
  the swing and hit thresholds, the seat guard, the human-turn budget, the patter clock, the
  slow-seat and big-mana lines, the chains — is runner/voice/stock/voices/tuning.json, read once
  by voice.table.load_tuning() (VoiceRunner(tuning={...}) overrides a value; the tests do).

CLI
  voice_runner.py                       run the daemon
  voice_runner.py --play startup        play a stock phrase and exit
  voice_runner.py --say "text"          render (cache/live) + play one line, exit
  voice_runner.py --mute | --unmute     flip control/voice.json
  voice_runner.py --dry-run             log what would be spoken, play nothing
  voice_runner.py --replay <archive>    drive the runner from an archived observer tape (fake clock, dry
                                        player, temp logs); print every line it would have said and a
                                        summary; --seed N (1) makes two runs identical

Restart memory (2026-09-14, hardening plan §4.1, A1/A2 — Ben: "a hot-swapped runner is normal and must
not forget"): logs/voice-state.json is a checkpoint of everything durable (the dead, the combos announced,
the game changers seen, the deals, the grudges, the turn's no-repeat set) and recent (what was said and
when, the seat guards, the patter clock, the tail cursors), written atomically on every change of the
durable set and at most every STATE_SAVE_S otherwise. A (re)started runner adopts it at its first snapshot
when the game is the same one (the snapshot's gameId, else the seat runners' gameId in game.jsonl) and
resumes as if it had never stopped — the first line comes when the clock says so, never at once. Without
a checkpoint it rebuilds what it can from the last LOG_MEMORY_S of its own voice-0.jsonl. Every record
carries `turn`, `phase`, `active` and `clock` (C1); a spoken line carries the ring `seq` that caused it
and its `channel`. A muted runner still reads the snapshot, so a game over publishes final.json at once
and the teardown watcher never waits on a voice that will not speak (B1).

Tapes and replay (§4.3, C1): every ring event the runner consumed goes to logs/events.jsonl (as-is,
plus turn and ts) and every CHANGED snapshot it read, compacted, to logs/observer-tape.jsonl (both
archived with the game; EVENTS_TAPE / OBSERVER_TAPE in voice/events.py). `--replay <archive>` drives
a fresh runner from that tape under a fake clock and a dry player and prints what it would have said
— the way a game's talk is re-examined without the game.

Layout (2026-09-14, voicework2 hardening plan Phase 0a) — split with no behaviour change:
  runner/voice/renderer.py    Player, Renderer, the WAV/FX/glitch helpers, STOCK/VOICES_DIR
  runner/voice/table.py       seat <-> voice assignment, addressing, decks' cards and combos, load_tuning
  runner/voice/scheduler.py   SchedulerMixin — the queue, the governor, the guards, chains, patter
  runner/voice/events.py      EventsMixin — the advisor stream, the snapshot, the event ring, the game log
  runner/voice/atoms.py       AtomsMixin — the non-verbal atoms and the under channel (§4.5)
  runner/chains.py            ChainTable and the reply planner (pure functions; the runner enqueues)
  runner/voice/stock/voices/  the seat libraries, assign/address/combos/chains.json, tuning.json
  this file                   VoiceRunner (state, the checkpoint, the play step, the loop) and the
                              CLI; it re-exports every public name, so `voice_runner.X` keeps working.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil        # kept importable as voice_runner.shutil / .subprocess / .urllib: the tests patch
import subprocess    # the stdlib modules through these attributes (the renderer sees the same objects)
import statistics
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent          # forge-arena/runner
sys.path.insert(0, str(HERE))
from chains import ChainTable  # noqa: E402
ARENA = HERE.parent
from voice.renderer import (  # noqa: E402,F401 — re-exported (voice_runner.X)
    STOCK, VOICES_DIR, DEFAULT_VOICE_ID, cache_key, wav_seconds, GLITCH_LEVELS, pcm_to_wav, lite_fx_wav, glitch_wav,
    Player, Renderer)
from voice.table import (  # noqa: E402,F401 — re-exported
    TABLE_LIB, TABLE_P, LIFE_STEPS, CARD_LIB, CARD_SWAP, CARD_REACTIONS, load_libraries, load_assignments,
    assign_voices, load_seat_libraries, DEFAULT_TABLE, table_from_launcher, game_changers_of, deck_cards_of,
    card_kind, load_address, who_for_deck, card_slug, load_combo_index, deck_combos_of, life_pid, hand_pid,
    TUNING_FILE, TUNING_SCHEMA, load_tuning)
from voice.scheduler import (  # noqa: E402,F401 — re-exported
    PRIORITY, CHAIN_HOP_PRIORITY, BARK_PRIORITY, DUTY_BASE, DUTY_WINDOW_S, DUTY_HUMAN_MULT, SILENCE_FLOOR_S,
    QUESTION_LINES, QUESTION_PREFIXES, PROPOSAL_LINES, PROPOSAL_PREFIXES, PROPOSAL_P, PROPOSAL_TARGET_P,
    PROPOSAL_REPLIES, PROPOSAL_TARGET_REPLIES, OPTIONAL_FLOOR, OPTIONAL_SOURCES, RARE_REPEATS, OWN_ACTION_LINES,
    LIFE_FOLLOWUP, STATE_ANSWERS, ADDRESS_SWAP, DEAL_TURNS, LONG_GAME_TURN, LETHAL_POWER, IDLE_S, IDLE_SLOWDOWN,
    MULL_LINE, MULL_P, MULL_SCREW_WORDS, MULL_DIG_WORDS, RECENT_S, PATTER_REPEAT_S, CHATTER_LEVELS,
    DEAL_KINDS, DEAL_ATTACK_KINDS, DEAL_TARGET_KINDS, DEAL_MAX_ROUNDS, DEALS_LEDGER, DEAL_CONTROL_DIR, DEAL_NOTE_KINDS, DEAL_LINES,
    DEAL_ANSWER_LINE, JOSHUA_DEAL_LINE, DEAL_OVER_P, I_BROKE_IT_P, CHAIN_P_OVERRIDE, normalize_deal, deal_terms, is_question,
    chatter_level, SchedulerMixin, classify)
from voice.events import (  # noqa: E402,F401 — re-exported
    FIRST_SENTENCE_MAX, ASK_MAX, LOOP_AT, THINK_S, NARRATIONS_PER_TURN, GRUDGE_EVERY, ELIM_SEAT_P, first_sentence,
    EVENTS_TAPE, OBSERVER_TAPE, EventsMixin)
from voice import events as _events        # the replay swaps its wall clock (events.py stamps time.time() on tapes and intents)
from voice.atoms import AtomsMixin
POLL_S = 0.5
CHAIN_POLL_S = 0.1          # while an exchange hop is pending: a retort's beat is ~0.5 s, so poll fast
# Restart memory (§4.1, A1/A2)
STATE_FILE = "voice-state.json"     # the checkpoint, in the logs directory beside voice-0.jsonl
STATE_SCHEMA = "arena.voice-state/1"
STATE_SAVE_S = 5.0                  # the recency maps are saved at most this often; a change of the durable set saves at once
STATE_RECENT_S = 300.0              # said_at / seat_said_at entries younger than this travel in the checkpoint
STATE_STALE_S = 900.0               # with no game id on either side, a checkpoint older than this is not trusted
STATE_SPOKEN_LOG_S = 60.0           # the duty window's samples: the last minute
LOG_MEMORY_S = 600.0                # no checkpoint: rebuild recency and eliminations from this much of voice-0.jsonl
RESTART_RING_MAX = 10               # ring events a restart catches up on at most; more = it was down too long: prime instead
REPLAY_TICK_S = 1.0                 # --replay: the clock steps between two tape snapshots, so the patter clock and the floor run as live


# ---- the daemon --------------------------------------------------------------------

class VoiceRunner(SchedulerMixin, EventsMixin, AtomsMixin):
    """The daemon: the state every mixin reads, the play step (speak), the loop (step/run).
    Queue policy lives in voice.scheduler.SchedulerMixin, the sources in voice.events.EventsMixin."""

    def __init__(self, logs_dir: Path, mailbox_dir: Path, dry_run: bool = False, fake_tts=None, player=None, clock=time.monotonic,
                 tuning: dict | None = None):
        self.logs = logs_dir
        self.mailbox = mailbox_dir
        self.dry_run = dry_run
        self.clock = clock
        self.wall = time.time                                  # wall time for records and the checkpoint; --replay swaps it
        self.human_seat = None if os.environ.get("ALL_SEATS") == "1" else 0   # all-AI (run_table.sh): seat 0 is a brain, notes and deals reach it
        self._log_path = logs_dir / "voice-0.log"
        self._jsonl = logs_dir / "voice-0.jsonl"
        self._control = logs_dir / "control" / "voice.json"
        self.rng = random.Random()
        self.renderer = Renderer(logs_dir / "cache" / "voice", log=self.say, fake_tts=fake_tts,
                                 record=self.record, clock=clock, rng=self.rng)
        self.player = player or Player(dry_run=dry_run, log=self.say)
        # The tuning (2026-09-16, hardening plan §2): every number below that is not an operator's
        # choice comes from voices/tuning.json — read once, overridable per runner (`tuning`, the tests).
        # The operator keeps the dial, the two on/some/off switches and the bleeps.
        self.tuning: dict = load_tuning()
        if tuning:
            unknown = set(tuning) - set(self.tuning)
            if unknown:
                raise ValueError(f"unknown tuning key(s): {sorted(unknown)} (voices/tuning.json holds {len(self.tuning)})")   # a typo tests nothing (critic)
            self.tuning.update(tuning)
        tune = self.tuning
        self.chatter = chatter_level(os.environ.get("ARENA_CHATTER", "normal"))
        self.min_gap = float(tune["min_gap_s"])
        self.sfx_on = os.environ.get("ARENA_VOICE_SFX", "on").lower() != "off"
        # "Your move" (Ben, 2026-09-10: "cool the first time, okay the second, lame
        # every time after"): on = every turn | some = about your_move_p of turns |
        # off; the wordings come from a shuffle bag either way.
        self.your_move_mode = os.environ.get("ARENA_VOICE_YOUR_MOVE", "some").lower()
        if self.your_move_mode not in ("on", "some", "off"):
            self.your_move_mode = "some"
        self.your_move_p = float(tune["your_move_p"])
        # Seat barks (2026-09-10): the advisor tags [bark:<seat>:<id>] on its
        # replies; the seat's static voice (voices/<lib>/) says its own wording.
        # Advisor off or muted => nothing (both already silence this runner).
        self.barks_mode = os.environ.get("ARENA_BARKS", "some").lower()
        if self.barks_mode not in ("off", "some", "all"):
            self.barks_mode = "some"
        self.barks_p = float(tune["barks_p"])
        self.barks_cooldown = float(tune["barks_cooldown_s"])
        self.barks_opener_p = float(tune["barks_opener_p"])
        self.barks_swing = int(tune["barks_swing"])
        self.barks_hit = int(tune["barks_hit"])
        # reactions to the HUMAN's plays (round 31: before this the seats ignored every card Ben cast)
        self.barks_human_p = float(tune["barks_human_p"])
        # the talk budget: a duty_target in the tuning overrides the dial's derived goal (null = derived)
        try:
            self.duty_target = float(tune["duty_target"] or 0) or min(0.45, DUTY_BASE * self.chatter)
        except (TypeError, ValueError):
            self.duty_target = min(0.45, DUTY_BASE * self.chatter)
        self.duty_human = float(tune["duty_human"])
        self._spoken_log: list[tuple[float, float]] = []       # (start, seconds) of every line played
        self.table_mult = float(tune["table_p"])
        self._turn_start: dict[int, dict] = {}                 # seat -> {"lands", "casts", "narrations"} for the turn it is playing
        self._prev_snapshot: dict = {}
        self._stack_seen: set[tuple] = set()
        self._thought: set[str] = set()                        # decision requests already muttered about
        self._cards: dict[int, dict[str, dict]] = {}           # seat -> name -> card record (lazy)
        # memory (phase D): who keeps hitting whom, how often a seat was countered, how many wipes, who promised whom
        self._hits_from: dict[int, dict[int, int]] = {}
        self._countered_n: dict[int, int] = {}
        self._sweeps = 0
        # table deals (plan 2026-09-16 §11): (a, b) -> {"kind", "until_turn", "struck", "offer_id"} both directions — the
        # live half of the ledger (logs/deals.jsonl); the counters a seat made and the player has not yet accepted; the
        # ledger's record counter. All three are in the checkpoint; an old checkpoint's int (the struck turn) upgrades.
        self._deals: dict[tuple[int, int], dict] = {}
        self._deal_counters: dict[str, dict] = {}              # offer_id -> {"between": [seat, other], "deal": terms, "turn": t}
        self._deal_seq = 0
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
        patter_switch = tune["patter"]
        if not isinstance(patter_switch, bool):
            raise ValueError(f"tuning.patter must be true/false, not {patter_switch!r}")             # "off" would read as on
        self.patter_on = patter_switch
        lo, hi = (list(tune["patter_gap_s"]) + [None])[:2]                                 # [lo, hi] seconds; [n] = fixed
        self.patter_gap = (float(lo), float(hi if hi is not None else lo))
        self.patter_human = float(tune["patter_human"])                                     # rate on the human's turn
        self.patter_after_advice = float(tune["patter_after_advice_s"])
        self.barks_slow = float(tune["barks_slow_s"])                                       # a seat thinking this long gets told
        self.barks_mana = int(tune["barks_mana"])                                           # floating this much is "big mana"
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
        self.chains = ChainTable.load(VOICES_DIR, tuning=tune)
        self._chain: dict | None = None      # {"origin": seat, "hop": n, "turn": t} while an exchange is running
        self._last_snapshot: dict = {}
        # the table: from the launcher at startup (ARENA_HUMAN_DECK + the roster), else
        # default seats until the game log names all three AI decks
        self._human_deck: str = os.environ.get("ARENA_HUMAN_DECK") or ""
        self._seat_decks: dict[int, str] = table_from_launcher(self._human_deck, os.environ.get("ARENA_SEAT_DECKS", ""),
                                                               all_ai=self.human_seat is None)
        self.seat_libraries = load_seat_libraries(seat_decks=self._seat_decks or None, human_seat=self.human_seat)
        self.game_changers: dict[int, set[str]] = self._table_game_changers()
        self.address = load_address()
        self._table_line = ", ".join(f"seat {k} {self._seat_decks.get(k, '?')} -> {v['voice']}" for k, v in sorted(self.seat_libraries.items())) or "no seat voices"
        self._who: dict[int, str] = self._table_who()
        self.table_ids, self.card_ids = self._load_sub_ids()
        self._combo_index = load_combo_index()
        self._combo_sets: dict[int, list[tuple[frozenset, str]]] = {}   # seat -> the deck's combos (lazy)
        self._combos_done: dict[int, set[frozenset]] = {}
        self._bark_spoken_at: dict[int, float] = {}
        # Colour commentary (Ben, 2026-09-07: "it could say a thing during
        # opponents' turns some of the time"): the advisor's per-turn recap
        # arrives after every turn, the opponents' included. off | some | all;
        # "some" voices each recap with probability color_p (0.5). Tuning, not a knob.
        self.color_mode = str(tune["color_mode"]).lower()
        if self.color_mode not in ("off", "some", "all"):
            self.color_mode = "some"
        self.color_p = float(tune["color_p"])
        # Ben, 2026-09-17 (game 58): Joshua gets a share of the colour on the AI seats' turns (the seat had all of it);
        # advice that lands within a few seconds of the player's own answer is still spoken, as a retrospective.
        self.color_joshua_share = float(tune["color_joshua_share"])
        self.advice_grace = float(tune["advice_grace_s"])
        self.apply_chatter()
        self.queue: list[dict] = []
        # A2: never -1e9 (the floor read a restart as an astronomical silence and forced a line in 3–6 s):
        # the clock starts at "a line just played", so the first line waits the normal gap. The log memory
        # and the checkpoint below may move it — to a real recent value, never to one past the floor.
        self.last_spoken_at = self.clock()
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
        self.answered_at: dict[int, float] = {}   # ...and when (the clock): advice within advice_grace_s of the answer still plays
        self.seen_turn = None
        self.seen_active = None
        self.eliminated: set[int] = set()
        self._seen_seats: set[int] = set()                    # every seat the snapshot has ever listed
        self.game_over_said = False
        self._state_published = None
        self._live_published = None
        self._step_enabled = True                              # step()'s one enabled() answer; react_atom reads it (B1)
        # Restart memory (§4.1). First the runner's own log: the opener never replays ("would you like to
        # play a game?" after the 2026-09-07 restart), and the last LOG_MEMORY_S of lines and deaths are
        # the fallback when no checkpoint exists (a crash before the first save). Then the checkpoint,
        # held until the first snapshot names the game (_adopt_state) — it overrides the log memory.
        mem = self._log_memory()
        self.started_said = mem["started_said"]              # a restart never replays "would you like to play a game?"
        self._said_at.update(mem["said_at"])
        self._seat_said_at.update(mem["seat_said_at"])
        self._bark_spoken_at.update(mem["bark_spoken_at"])
        self._spoken_log = mem["spoken_log"]
        if mem["last_spoken_at"] is not None:
            self.last_spoken_at = mem["last_spoken_at"]
        self._log_eliminated: set[int] | None = mem["eliminated"]     # applied at the first snapshot, when the game is past turn 1
        self._state_path = logs_dir / STATE_FILE
        self._state_sig: str | None = None
        self._state_saved_at = -1e9
        self._state_warned = False
        self._gid_cache: tuple[int, str | None] = (-1, None)
        self._pending_state: dict | None = self.load_state()

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

    # -- restart memory (§4.1, A1/A2)
    def _silence_floor(self) -> float:
        """The shorter (AI-turn) silence floor as the patter clock computes it — the yardstick for "was
        the last line long enough ago that the floor would fire the moment we start"."""
        return SILENCE_FLOOR_S["ai"] / max(0.25, self.chatter)

    def _settle_clock(self, d: dict) -> None:
        """A2 — at the first snapshot, whatever memory set last_spoken_at, a (re)start never reads as a
        long silence: a value older than the floor (or in the future: another clock base) is clamped to
        now - min_gap, so a real event may speak after the normal gap, but the floor re-arms from now and
        the patter clock is due one normal gap from now — the gap of the turn's owner, which is why this
        waits for the snapshot. A fresh start that reads its first snapshot within the floor keeps
        last_spoken_at at its construction time."""
        now = self.clock()
        if now - self.last_spoken_at > self._silence_floor() or self.last_spoken_at > now:
            self.last_spoken_at = now - self.min_gap
        self._floor_rearmed_at = now
        self._patter_anchor = self.last_spoken_at
        human_turn = d.get("activeSeat") == self.human_seat and not self.executive_on()
        self._patter_due = now + self._patter_gap_s(human_turn)

    def _log_memory(self) -> dict:
        """The runner's own voice-0.jsonl, read once at start (_startup_already_spoken generalised):
        whether the opener was ever spoken (any `spoke` of stock startup, however old) and, from the
        last LOG_MEMORY_S by wall time, the recency maps (`spoke` -> said_at / seat_said_at /
        bark_spoken_at / last_spoken_at / the duty samples) and the seats that left (`noted` "gone
        from the snapshot", a seat's `eliminated` line, the human's `human_out`). Every record carries
        `ts` (wall), so its clock value is now - age whatever the old process's monotonic base was.
        The fallback when no checkpoint exists (a crash before the first save)."""
        out: dict = {"started_said": False, "said_at": {}, "seat_said_at": {}, "bark_spoken_at": {}, "spoken_log": [],
                     "last_spoken_at": None, "eliminated": set()}
        try:
            raw = self._jsonl.read_bytes()
        except OSError:
            return out
        now_c, now_w = self.clock(), self.wall()
        for line in raw.splitlines():
            if b'"spoke"' not in line and b'"noted"' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ev = r.get("event")
            if ev == "spoke" and r.get("stock") == "startup":
                out["started_said"] = True
            try:
                age = now_w - float(r.get("ts"))
            except (TypeError, ValueError):
                continue
            if age > LOG_MEMORY_S:
                continue
            t = now_c - max(0.0, age)
            seat = r.get("seat")
            if ev == "noted":
                if seat is not None and "gone from the snapshot" in str(r.get("why") or ""):
                    out["eliminated"].add(int(seat))
                continue
            if ev != "spoke" or r.get("kind") == "atom":
                continue                                                   # an atom is presence, not a line
            stock = str(r.get("stock") or "")
            if r.get("kind") == "human_out":
                out["eliminated"].add(self.human_seat)
            elif stock == "eliminated" and seat is not None:
                out["eliminated"].add(int(seat))
            if out["last_spoken_at"] is None or t > out["last_spoken_at"]:
                out["last_spoken_at"] = t
            secs = float(r.get("seconds") or 0.0)
            if age <= STATE_SPOKEN_LOG_S:
                out["spoken_log"].append((t - secs, secs))
            if seat is not None and r.get("library"):
                out["bark_spoken_at"][int(seat)] = max(t, out["bark_spoken_at"].get(int(seat), -1e9))
                if stock:
                    out["said_at"][stock] = max(t, out["said_at"].get(stock, -1e9))
                    out["seat_said_at"][(int(seat), stock)] = max(t, out["seat_said_at"].get((int(seat), stock), -1e9))
        out["spoken_log"].sort()
        return out

    def _game_id(self, snap: dict | None = None):
        """The game's id: the snapshot's, else the seat runners' (the last game.jsonl record that
        carries one — the engine stamps gameId on every request; the observer does not)."""
        gid = (snap if snap is not None else self._last_snapshot).get("gameId")
        if gid:
            return str(gid)
        path = self.logs / "game.jsonl"
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if self._gid_cache[0] == size:
            return self._gid_cache[1]
        gid = None
        try:
            with path.open("rb") as f:
                f.seek(max(0, size - 16384))
                chunk = f.read()
            for line in reversed(chunk.splitlines()):
                try:
                    g = json.loads(line).get("gameId")
                except (ValueError, AttributeError):
                    continue
                if g:
                    gid = str(g)
                    break
        except OSError:
            pass
        self._gid_cache = (size, gid)
        return gid

    def load_state(self) -> dict | None:
        """The checkpoint, parsed, or None; adopted only at the first snapshot (_adopt_state)."""
        try:
            st = json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            return None
        return st if isinstance(st, dict) and st.get("schema") == STATE_SCHEMA else None

    def _durable_state(self) -> dict:
        """The part of the checkpoint whose change saves at once: what the table must never forget."""
        return {
            "eliminated": sorted(int(s) for s in self.eliminated),
            "seen_seats": sorted(int(s) for s in self._seen_seats),
            "combos_done": {str(s): sorted(sorted(str(p) for p in fs) for fs in sets) for s, sets in sorted(self._combos_done.items())},
            "gc_cast_seen": sorted([int(s), str(c)] for s, c in self._gc_cast_seen),
            "card_events_turn": sorted([int(s), str(c), int(n)] for (s, c), n in self._card_events_turn.items()),
            "heads_up_said": bool(self._heads_up_said),
            "sweeps": int(self._sweeps),
            "countered_n": {str(s): int(n) for s, n in sorted(self._countered_n.items())},
            "deals": sorted(([int(a), int(b), normalize_deal(v)] for (a, b), v in self._deals.items()), key=lambda x: (x[0], x[1])),
            "deal_counters": {str(k): v for k, v in sorted(self._deal_counters.items())},
            "deal_seq": int(self._deal_seq or 0),
            "hits_from": {str(v): {str(f): int(n) for f, n in sorted(m.items())} for v, m in sorted(self._hits_from.items())},
            "last_hit_by": {str(s): [[int(h) for h in hs], t] for s, (hs, t) in sorted(self._last_hit_by.items())},
            "mulls": {str(s): int(n) for s, n in sorted(self._mulls.items())},
            "kept_seven": [int(s) for s in self._kept_seven],
            "human_mull_done": bool(self._human_mull_done),
            "pool_high": sorted(int(s) for s in self._pool_high),
            "thought": sorted(self._thought),
            "said_turn": self._said_turn,
            "said_this_turn": sorted([int(s), str(p)] for s, p in self._said_this_turn),
            "chain": self._chain,
            "seen_turn": self.seen_turn, "seen_active": self.seen_active,
            "started_said": bool(self.started_said), "game_over_said": bool(self.game_over_said), "final_locked": bool(self.final_locked),
            "event_seq": self._event_seq,
            "loop_called": {str(s): t for s, t in sorted((self._loop_called or {}).items())},
            "heckled": int(getattr(self, "_heckled", 0) or 0),
            "last_spoken_at": self.last_spoken_at,                 # a spoken line is a checkpoint too
        }

    def _recency_state(self) -> dict:
        """The part saved at most every STATE_SAVE_S: what was said lately and the clocks."""
        now = self.clock()
        d = self.__dict__
        return {
            "said_at": {k: v for k, v in self._said_at.items() if now - v <= STATE_RECENT_S},
            "seat_said_at": {f"{s}|{pid}": v for (s, pid), v in self._seat_said_at.items() if now - v <= STATE_RECENT_S},
            "bark_spoken_at": {str(s): v for s, v in self._bark_spoken_at.items()},
            "seat_last_class": {str(s): c for s, c in self._seat_last_class().items()},
            "spoken_log": [[t, sec] for t, sec in self._spoken_log if t + sec > now - STATE_SPOKEN_LOG_S],
            "advisor_spoke_at": self._advisor_spoke_at,
            "patter_due": self._patter_due, "patter_anchor": self._patter_anchor,
            "floor_rearmed_at": getattr(self, "_floor_rearmed_at", -1e9), "floor_atom_run": int(getattr(self, "_floor_atom_run", 0) or 0),
            "tails": {k: list(v) for k, v in (self._tails or {}).items()},
            # the turn in progress (seam critic, 2026-09-16): the active seat's lands/casts/narrations, the cast
            # flurry clocks and the advisor requests already answered — a hot swap mid-turn kept none of them
            "turn_start": {str(s): dict(v) for s, v in self._turn_start.items()},
            "threat": {str(s): round(v, 3) for s, v in getattr(self, "_threat", {}).items()},
            "casts": {str(s): [x for x in v if now - x <= STATE_RECENT_S] for s, v in getattr(self, "_casts", {}).items()},
            "answered": sorted(int(x) for x in self.answered),
            "answered_at": {str(k): v for k, v in self.answered_at.items() if now - v <= STATE_RECENT_S},
            "ring_seq": self._ring_seq,
            "atom_seat_at": {str(s): t for s, t in d.get("_atom_seat_at", {}).items()},
            "atom_used": {f"{s}|{stem}": t for (s, stem), t in d.get("_atom_used", {}).items()},
        }

    def save_state(self, force: bool = False) -> bool:
        """logs/voice-state.json, atomically (tmp + os.replace): at once when the durable set changed
        (its JSON is the signature — a few hundred bytes a step), else at most every STATE_SAVE_S for
        the recency maps; `force` for game over. Clock values are stored raw beside `clock` and
        `saved_at` (wall), so adoption can rebase them onto a new monotonic base."""
        durable = self._durable_state()
        sig = json.dumps(durable, sort_keys=True, default=str)
        now = self.clock()
        if not force and sig == self._state_sig and 0.0 <= now - self._state_saved_at < STATE_SAVE_S:
            return False
        state = {"schema": STATE_SCHEMA, "gameId": self._game_id(), "saved_at": self.wall(), "clock": now, **durable, **self._recency_state()}
        try:
            tmp = self._state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, default=str))
            os.replace(tmp, self._state_path)
        except (OSError, TypeError, ValueError) as e:
            if not self._state_warned:
                self._state_warned = True
                self.say(f"[voice] checkpoint not written ({str(e)[:80]}) — a restart will forget")
            return False
        self._state_sig, self._state_saved_at = sig, now
        return True

    def _adopt_state(self, d: dict) -> None:
        """The first snapshot: adopt the checkpoint when it is this game's — same gameId (the
        snapshot's, else game.jsonl's), or neither side has one and the checkpoint is younger than
        STATE_STALE_S and its turn is not ahead of the board (turns never go backwards). Else it
        is ignored with a record, and the log memory's eliminations stand in on a game past turn 1."""
        state, self._pending_state = self._pending_state, None
        mem_dead, self._log_eliminated = self._log_eliminated, None
        gid = self._game_id(d)
        turn = d.get("turn")
        if state is not None:
            sgid = state.get("gameId")
            try:
                age = self.wall() - float(state.get("saved_at") or 0.0)
            except (TypeError, ValueError):
                age = float("inf")
            try:
                ahead = turn is not None and state.get("seen_turn") is not None and int(turn) < int(state["seen_turn"]) - 1
            except (TypeError, ValueError):
                ahead = False
            same = (sgid is not None and gid is not None and str(sgid) == str(gid)) or (sgid is None and gid is None and age <= STATE_STALE_S)
            if same and not ahead:
                self._restore_state(state, d, age)
                return
            self.record("noted", kind="state", why=f"checkpoint {'ahead of the board' if ahead else 'from another game'} ignored (saved for {sgid!r} at turn {state.get('seen_turn')}, "
                        f"{age:.0f}s ago; this is {gid!r} at turn {turn})")
        if mem_dead and (turn or 0) > 1:
            fresh = sorted(s for s in mem_dead if s not in self.eliminated)
            self.eliminated |= set(mem_dead)
            self._seen_seats |= set(mem_dead)
            self.record("noted", kind="state", why=f"no checkpoint: {len(fresh)} dead seat(s) rebuilt from voice-0.jsonl", seats=fresh)
        self._settle_clock(d)                                  # A2, for the fresh start and the log memory alike

    def _restore_state(self, state: dict, d: dict, age: float) -> None:
        """Every field back, tuples and sets decoded, clocks rebased by
        shift = now - saved clock - (wall now - wall saved) — the seconds that passed while down,
        seen from the new monotonic base — then _settle_clock, so nothing is forced at once (A2)."""
        now = self.clock()
        try:
            shift = now - float(state["clock"]) - (self.wall() - float(state["saved_at"]))
        except (KeyError, TypeError, ValueError):
            shift = 0.0

        def t(v, default=None):
            if v is None:
                return default
            try:
                v = float(v)
            except (TypeError, ValueError):
                return default
            return v + shift if v > -1e8 else -1e9

        def ints(xs):
            return {int(x) for x in (xs or [])}

        def get(key, kind):
            v = state.get(key)
            return v if isinstance(v, kind) else kind()
        # durable
        self.eliminated = ints(get("eliminated", list))
        self._seen_seats = ints(get("seen_seats", list)) | self.eliminated
        self._combos_done = {int(s): {frozenset(str(p) for p in fs) for fs in sets} for s, sets in get("combos_done", dict).items()}
        self._gc_cast_seen = {(int(s), str(c)) for s, c in get("gc_cast_seen", list)}
        self._card_events_turn = {(int(s), str(c)): int(n) for s, c, n in get("card_events_turn", list)}
        self._heads_up_said = bool(state.get("heads_up_said"))
        self._sweeps = int(state.get("sweeps") or 0)
        self._countered_n = {int(s): int(n) for s, n in get("countered_n", dict).items()}
        # the deals: the contract's dict, or an OLD checkpoint's int (the struck turn) upgraded to a truce until struck + DEAL_TURNS
        self._deals = {}
        for a, b, v in get("deals", list):
            deal = normalize_deal(v)
            if deal is not None:
                self._deals[(int(a), int(b))] = deal
        self._deal_counters = {str(k): v for k, v in get("deal_counters", dict).items()
                               if isinstance(v, dict) and isinstance(v.get("between"), list) and len(v["between"]) == 2}
        self._deal_seq = int(state.get("deal_seq") or 0)
        self._hits_from = {int(v): {int(f): int(n) for f, n in m.items()} for v, m in get("hits_from", dict).items()}
        self._last_hit_by = {int(s): ([int(h) for h in hs], tn) for s, (hs, tn) in get("last_hit_by", dict).items()}
        self._mulls = {int(s): int(n) for s, n in get("mulls", dict).items()}
        self._kept_seven = [int(s) for s in get("kept_seven", list)]
        self._human_mull_done = bool(state.get("human_mull_done"))
        self._pool_high = ints(get("pool_high", list))
        self._thought = set(str(x) for x in get("thought", list))
        self._said_turn = state.get("said_turn")
        self._said_this_turn = {(int(s), str(p)) for s, p in get("said_this_turn", list)}
        self._chain = state.get("chain") if isinstance(state.get("chain"), dict) else None
        self.seen_turn, self.seen_active = state.get("seen_turn"), state.get("seen_active")
        self.started_said = True
        self.game_over_said = bool(state.get("game_over_said"))
        self.final_locked = bool(state.get("final_locked"))
        self._loop_called = {int(s): tn for s, tn in get("loop_called", dict).items()}
        self._heckled = 0                                     # the wait restarts from this snapshot: no "there you are" for a move nobody made
        # the ring: catch up on what passed while down, unless too much of it rolled by
        saved_seq = state.get("event_seq")
        if saved_seq is not None:
            seqs = [int(e.get("seq", 0)) for e in (d.get("events") or []) if isinstance(e, dict)]
            top = max(seqs, default=int(saved_seq))
            if top - int(saved_seq) <= RESTART_RING_MAX:
                self._event_seq = int(saved_seq)
            else:
                self.record("noted", kind="state", why=f"{top - int(saved_seq)} ring events passed while down — not replayed")
        # recency, rebased
        self._said_at = {str(k): t(v) for k, v in get("said_at", dict).items() if t(v) is not None}
        self._seat_said_at = {}
        for key, v in get("seat_said_at", dict).items():
            seat, _, pid = str(key).partition("|")
            if pid and t(v) is not None:
                self._seat_said_at[(int(seat), pid)] = t(v)
        self._bark_spoken_at = {int(s): t(v) for s, v in get("bark_spoken_at", dict).items() if t(v) is not None}
        cls = self._seat_last_class()
        cls.clear()
        cls.update({int(s): str(c) for s, c in get("seat_last_class", dict).items()})
        self._spoken_log = [(t(a), float(b)) for a, b in get("spoken_log", list) if t(a) is not None]
        self._turn_start = {int(s): dict(v) for s, v in get("turn_start", dict).items()}
        self._threat = {int(s): float(v) for s, v in get("threat", dict).items()}
        self._casts = {int(s): [t(x) for x in v if t(x) is not None] for s, v in get("casts", dict).items()}
        self.answered = {int(x) for x in get("answered", list)}
        self.answered_at = {int(k): float(v) for k, v in get("answered_at", dict).items()}
        self.last_spoken_at = t(state.get("last_spoken_at"), now)
        self._advisor_spoke_at = t(state.get("advisor_spoke_at"), -1e9)
        self._patter_due = t(state.get("patter_due"), now)
        self._patter_anchor = t(state.get("patter_anchor"))
        self._floor_rearmed_at = t(state.get("floor_rearmed_at"), -1e9)
        self._floor_atom_run = int(state.get("floor_atom_run") or 0)
        tails = get("tails", dict)
        self._tails = {str(k): [v[0], int(v[1])] for k, v in tails.items() if isinstance(v, list) and len(v) == 2}
        atom_seat_at, atom_used = get("atom_seat_at", dict), get("atom_used", dict)
        if atom_seat_at or atom_used:
            self._atoms_init()
            self._atom_seat_at.update({int(s): t(v) for s, v in atom_seat_at.items() if t(v) is not None})
            for key, v in atom_used.items():
                seat, _, stem = str(key).partition("|")
                if stem and t(v) is not None:
                    self._atom_used[(int(seat), stem)] = t(v)
        self._settle_clock(d)
        recent = sum(1 for v in self._said_at.values() if now - v <= STATE_RECENT_S)
        self.record("noted", kind="state", why=f"checkpoint adopted: {len(self.eliminated)} dead, {sum(len(s) for s in self._combos_done.values())} combos, "
                    f"{recent} recent lines ({age:.0f}s old, clock shift {shift:+.1f}s)")

    def scan_observer(self, d: dict | None = None) -> None:
        """The mixin's, with the restart memory in front: the first snapshot that names the game
        adopts the checkpoint (or the log memory's dead) BEFORE the mixin reads it. The file is read
        here for that one snapshot (the mixin's stat signature is kept current); the mixin stays as it is."""
        if self._pending_state is None and self._log_eliminated is None:
            return super().scan_observer(d)
        if d is None:
            path = self.mailbox / "observer-state.json"
            try:
                st = path.stat()
                d = json.loads(path.read_text())
            except (OSError, ValueError):
                return
            self._snap_sig = (st.st_mtime_ns, st.st_size)
        if not isinstance(d, dict):
            return
        self._adopt_state(d)
        super().scan_observer(d)

    def react_atom(self, *args, **kw) -> bool:
        if not self._step_enabled:
            return False                                   # B1: a muted table gasps at nothing
        return super().react_atom(*args, **kw)

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
        """voice-0.jsonl: {"ts", "event": spoke|dropped|skipped|queued|noted|gap, "kind": <item kind>, …},
        every record stamped with the board it was written against (C1): `turn`, `phase`, `active`
        (None until a snapshot was read) and `clock`; a caller's own values stand."""
        snap = getattr(self, "_last_snapshot", None) or {}
        body.setdefault("turn", snap.get("turn"))
        body.setdefault("phase", snap.get("phase"))
        body.setdefault("active", snap.get("activeSeat"))
        if "clock" not in body:
            try:
                body["clock"] = round(self.clock(), 3)
            except Exception:  # noqa: BLE001 — a record never fails for its stamp
                body["clock"] = None
        tally = self.__dict__.setdefault("_tally", {})
        key = f"{event}:{body.get('kind')}:{body.get('source') or ''}"
        tally[key] = tally.get(key, 0) + 1
        try:
            with self._jsonl.open("a") as f:
                f.write(json.dumps({"ts": round(getattr(self, "wall", time.time)(), 3), "event": event, **body}, default=str) + "\n")
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
        # The match screen follows a seat only for a line worth looking at (Ben, game 51): a reaction, a
        # narration, a retort, the advisor's tag, a jab aimed at someone — never untargeted filler from the
        # patter clock, and never an atom (atoms do not pass through here). Afterwards it shows the active
        # player's field.
        meaningful = item.get("source") != "patter" or bool((item.get("ctx") or {}).get("targets"))
        self.publish_speaking(item if meaningful else None, secs)
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
        extra: dict = {"channel": "main"}                            # C1: the ring event that caused a bark, and the channel (atoms say "under")
        ctx_seq = (item.get("ctx") or {}).get("seq")
        if ctx_seq is not None:
            extra["seq"] = ctx_seq
        targets = (item.get("ctx") or {}).get("targets") or []
        if targets:
            extra["target"] = int(targets[0])                                # who the line was aimed at (hygiene's grounding score)
        self.record("spoke", kind=item["kind"], text=item["text"][:200], stock=item["stock"], seconds=round(secs, 2),
                    chars_used=self.renderer.chars_used, library=item.get("library") or "", seat=item.get("seat"),
                    file=path.name, duty=round(self.duty(), 2), goal=round(self.duty_goal(), 2), source=item.get("source", ""), **extra)
        who = f" seat {item['seat']} ({item['library']})" if item.get("library") else ""
        hop = f" (chain hop {item['chain']['hop']})" if item.get("chain") else ""
        self.say(f"[voice] {item['kind']}{who}{hop}: {item['stock'] or item['text'][:90]}" + (f" [{path.name}]" if item["stock"] and path.name != f"{item['stock']}.wav" else ""))
        self.after_spoken(item)
        return True

    # -- seat barks (the table is seated once, at startup, from the launcher's roster — 2026-09-17)

    def library_for_seat(self, seat: int) -> str:
        info = self.seat_libraries.get(int(seat))
        return info["library"] if info else ""

    # -- loop
    def step(self) -> None:
        self.publish_state()
        self._step_enabled = on = self.enabled()
        if not on:
            # B1: a muted runner still READS the snapshot — game over sets the lock and the teardown watcher
            # gets its final.json at once instead of after LINGER; every queued line is dropped with a
            # record; nothing plays (the queue is emptied here, react_atom is gated, the backchannel is armed
            # only by speak). The advisor stream and the game log wait for the unmute, as before.
            self.stop_atoms()                            # a pending murmur or an under-line dies with the mute
            self.scan_observer()
            if self.queue:
                for q in self.queue:
                    self.record("dropped", kind=q["kind"], why="voice disabled", stock=q.get("stock", ""), seat=q.get("seat"),
                                text=(q.get("text") or "")[:60])
                self.say(f"[voice] disabled — dropping {len(self.queue)} queued line(s)")
                self.queue = []
            if self.final_locked:
                self.publish_final()
            self.save_state()
            return
        self.scan_advisor()
        self.scan_observer()
        self.scan_game_log()
        self.scan_deal_control()                     # the player's acceptance of a seat's counter (logs/control/deal/, §11)
        self.mutter()
        self.heckle_human()                          # "we're waiting on you" (Ben: heckles are welcome; Joshua never answers)
        self.patter()
        item = self.next_item()
        if item is not None:
            self.save_state(force=True)               # the cursors past this line BEFORE it plays: a kill mid-line
            self.speak(item)                          # loses the line rather than repeating it (2026-09-07; critic 09-16)
        if self.final_locked and not self.queue:
            self.publish_final()                      # spoken or skipped, the sequence has drained
        self.save_state()                             # §4.1: at once when the durable set moved, else every STATE_SAVE_S

    def record_up(self) -> None:
        """One `up` record per (re)start (plan tune 11): the restart count is the number of earlier `up`
        records in this game's voice-0.jsonl, so hygiene reads restarts from the runner's own log."""
        earlier = 0
        try:
            for line in self._jsonl.read_text().splitlines():
                if '"event": "up"' in line:
                    earlier += 1
        except OSError:
            pass
        tune_sha = ""
        try:
            import hashlib
            tune_sha = hashlib.sha1((VOICES_DIR / "tuning.json").read_bytes()).hexdigest()[:10]
        except OSError:
            pass
        self.record("up", kind="runner", restart=earlier, chatter=self.chatter, tuning=tune_sha, live=bool(self.renderer.live),
                    libraries=sorted(v["library"] for v in self.seat_libraries.values()))

    def record_summary(self) -> None:
        """One `summary` record at the final marker (plan tune 11): what the table did, from the runner's own tally."""
        t = self.__dict__.get("_tally", {})
        spoke = {k.split(":")[2] or k.split(":")[1]: v for k, v in t.items() if k.startswith("spoke:")}
        self.record("summary", kind="runner",
                    spoke=sum(v for k, v in t.items() if k.startswith("spoke:") and ":atom:" not in k),
                    by_source=spoke, skipped=sum(v for k, v in t.items() if k.startswith("skipped:")),
                    dropped=sum(v for k, v in t.items() if k.startswith("dropped:")),
                    atoms=sum(v for k, v in t.items() if k.startswith("spoke:atom")),
                    duty=round(self.duty(), 2), ring_gaps=sum(v for k, v in t.items() if k.startswith("gap:")),
                    deals=len({tuple(sorted(k)) for k in self._deals}) if isinstance(self._deals, dict) else 0)

    def run(self) -> None:
        self.say(f"[voice] up — chatter={self.chatter:g}, stock {len(self.renderer.manifest.get('phrases', {}))} phrases, "
                 f"live={'on' if self.renderer.live else 'off (no ELEVENLABS_API_KEY)'}, min_gap={self.min_gap}s, "
                 f"fx={self.renderer.fx_mode}, format={self.renderer.format}, glitch={self.renderer.glitch}, sfx={'on' if self.sfx_on else 'off'}, color={self.color_mode}, "
                 f"your_move={self.your_move_mode}, barks={self.barks_mode}, patter={'off' if not self.patter_on else f'{self.patter_gap[0]:g}-{self.patter_gap[1]:g}s'}" + (f", chains p={self.chains.first_hop_p}/decay {self.chains.decay}/max {self.chains.max_hops}/gap {self.chains.gap_s}s" if self.chains else ", chains=off (no chains.json)")
                 + (f" (p={self.barks_p}, opener_p={self.barks_opener_p}, swing>={self.barks_swing}, hit>={self.barks_hit}, guard={self.barks_cooldown:.0f}s; " + self._table_line + ")"
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
        self.record_up()
        while True:
            try:
                self.step()
            except Exception as e:  # noqa: BLE001 — bookkeeping never ends the voice
                self.say(f"[voice] step error: {str(e)[:160]}")
            time.sleep(CHAIN_POLL_S if any(q.get("chain") for q in self.queue) else POLL_S)


# ---- replay (§4.3) ------------------------------------------------------------------

class _ReplayClock:
    """The fake monotonic clock a replay drives; set to each tape record's `clock`."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class _ReplayTime:
    """Stands in for the `time` module inside voice.events during a replay: time() is the tape's
    wall clock (intent staleness, the cast flurry, the tapes' ts), everything else the real module's."""

    def __init__(self, get):
        self._get = get

    def time(self) -> float:
        return self._get()

    def __getattr__(self, name):
        return getattr(time, name)


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
    except OSError:
        pass
    return out


def _read_stamped(path: Path) -> list[tuple[float, str]]:
    """(ts, raw line) for every record of an archived log that carries a wall `ts`, in file order."""
    out = []
    try:
        for line in path.read_text().splitlines():
            try:
                ts = float(json.loads(line).get("ts"))
            except (ValueError, TypeError, AttributeError):
                continue
            out.append((ts, line))
    except OSError:
        pass
    return out


def _snapshot_from_tape(rec: dict, events: list[dict], lo, hi) -> dict:
    """A live-shaped snapshot from a compacted observer-tape record: the seats with their
    battlefield entries as dicts, the ring = the archived events with lo < seq <= hi."""
    ring = [] if hi is None else [e for e in events if isinstance(e.get("seq"), int) and (lo is None or e["seq"] > lo) and e["seq"] <= hi]
    seats = [{"seat": s.get("seat"), "name": f"seat {s.get('seat')}", "life": s.get("life"), "handSize": s.get("handSize"),
              "pool": s.get("pool"), "eliminated": bool(s.get("eliminated")),
              "battlefield": [dict(c) for c in (s.get("battlefield") or []) if isinstance(c, dict)]}
             for s in (rec.get("seats") or []) if isinstance(s, dict)]
    return {"gameId": rec.get("gameId"), "turn": rec.get("turn"), "phase": rec.get("phase"), "activeSeat": rec.get("activeSeat"),
            "gameOver": bool(rec.get("gameOver")), "stack": rec.get("stack") or [], "stackDetail": rec.get("stackDetail") or [],
              "events": ring, "seats": seats}


def replay(archive: Path, seed: int = 1, out=print) -> list[str]:
    """Drive a VoiceRunner from an archive's observer-tape.jsonl (+ events.jsonl, game.jsonl,
    advisor-0.jsonl) with a fake clock and a dry player, logging into a temp directory that is
    removed afterwards — the live logs are never touched. Between two tape snapshots the clock
    steps REPLAY_TICK_S at a time so the patter clock and the floor run as they did live. Prints
    every line it would have said as `[t+MM:SS turn N] seat S <stock> (source)` and ends with
    lines/min, the share by source and the gap median / p90 / max; deterministic under `seed`
    (the backchannel timers are off — a real-time thread would race the dice). Returns the lines."""
    archive = Path(archive)
    tape = _read_jsonl(archive / _events.OBSERVER_TAPE)
    if not tape:
        raise SystemExit(f"[voice] no {_events.OBSERVER_TAPE} under {archive}")
    events = _read_jsonl(archive / _events.EVENTS_TAPE)
    game_lines, adv_lines = _read_stamped(archive / "game.jsonl"), _read_stamped(archive / "advisor-0.jsonl")
    tmp = Path(tempfile.mkdtemp(prefix="voice-replay-"))
    logs, mailbox = tmp / "logs", tmp / "mailbox"
    logs.mkdir()
    mailbox.mkdir()
    first = tape[0]
    wall = {"t": float(first.get("ts") or 0.0)}
    clock = _ReplayClock(float(first["clock"]) if first.get("clock") is not None else wall["t"])
    clock0 = clock.t
    saved_time = _events.time
    _events.time = _ReplayTime(lambda: wall["t"])
    report: list[str] = []
    try:
        vr = VoiceRunner(logs, mailbox, dry_run=True, clock=clock)
        vr.wall = lambda: wall["t"]
        vr.rng.seed(seed)
        vr.start_backchannel = lambda item, seconds=None: False        # no real-time timers in a replay
        seqs = [e["seq"] for e in events if isinstance(e.get("seq"), int)]
        prev_seq = first.get("seq") if first.get("seq") is not None else (min(seqs) - 1 if seqs else None)
        vr._event_seq = prev_seq                                       # the live runner primed here; the tape holds what followed
        cursors = {"game": 0, "advisor": 0}
        spoken: list[tuple[float, dict]] = []

        def feed(name: str, lines: list[tuple[float, str]]) -> None:
            i = cursors[name]
            due = []
            while i < len(lines) and lines[i][0] <= wall["t"]:
                due.append(lines[i][1])
                i += 1
            if due:
                with (logs / ("game.jsonl" if name == "game" else "advisor-0.jsonl")).open("a") as f:
                    f.write("\n".join(due) + "\n")
            cursors[name] = i

        def tick() -> None:
            feed("game", game_lines)
            feed("advisor", adv_lines)
            vr.scan_game_log()
            vr.scan_advisor()
            vr.mutter()
            vr.heckle_human()
            vr.patter()
            item = vr.next_item()
            if item is not None and vr.speak(item):
                spoken.append((clock.t, item))
                el = int(clock.t - clock0)
                line = (f"[t+{el // 60:02d}:{el % 60:02d} turn {vr._last_snapshot.get('turn')}] seat {item.get('seat') if item.get('seat') is not None else 'J'} "
                        f"<{item.get('stock') or (item.get('text') or '')[:60]}> ({item.get('source') or item.get('kind')})")
                report.append(line)
                out(line)
            if vr.final_locked and not vr.queue:
                vr.publish_final()

        for rec in tape:
            target_c = float(rec["clock"]) if rec.get("clock") is not None else (float(rec["ts"]) if rec.get("ts") is not None else clock.t)
            target_w = float(rec["ts"]) if rec.get("ts") is not None else wall["t"]
            while clock.t + REPLAY_TICK_S < target_c:
                clock.t += REPLAY_TICK_S
                wall["t"] += REPLAY_TICK_S
                tick()
            clock.t, wall["t"] = max(clock.t, target_c), max(wall["t"], target_w)
            hi = rec.get("seq") if isinstance(rec.get("seq"), int) else None
            vr.scan_observer(_snapshot_from_tape(rec, events, prev_seq, hi))
            if hi is not None:
                prev_seq = hi
            tick()
        span = max(1e-9, clock.t - clock0)
        report.append(f"-- {len(spoken)} lines in {span / 60:.1f} min = {len(spoken) / (span / 60):.2f} lines/min (seed {seed})")
        by_src: dict[str, int] = {}
        for _, item in spoken:
            src = str(item.get("source") or item.get("kind"))
            by_src[src] = by_src.get(src, 0) + 1
        for src, n in sorted(by_src.items(), key=lambda kv: (-kv[1], kv[0])):
            report.append(f"   {src}: {n} ({100 * n / len(spoken):.0f}%)")
        gaps = [b - a for (a, _), (b, _) in zip(spoken, spoken[1:])]
        if gaps:
            gaps_sorted = sorted(gaps)
            report.append(f"   gap median {statistics.median(gaps):.1f}s, p90 {gaps_sorted[int(0.9 * (len(gaps) - 1))]:.1f}s, max {gaps_sorted[-1]:.1f}s")
        for line in report[len(spoken):]:
            out(line)
    finally:
        _events.time = saved_time
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=str(HERE / "logs"))
    ap.add_argument("--mailbox", default=str(ARENA / "mailbox"))
    ap.add_argument("--play", metavar="ID", help="play a stock phrase and exit")
    ap.add_argument("--say", metavar="TEXT", help="render (cache/live) and play one line, then exit")
    ap.add_argument("--mute", action="store_true")
    ap.add_argument("--unmute", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replay", metavar="ARCHIVE_DIR", help="drive the runner from an archived observer tape (fake clock, dry player, temp logs)")
    ap.add_argument("--seed", type=int, default=1, help="the dice for --replay (1): the same seed gives the same run")
    a = ap.parse_args()
    if a.replay:
        replay(Path(a.replay), seed=a.seed)
        return
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
