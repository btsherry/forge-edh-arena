#!/usr/bin/env python3
"""AI Advisor runner — a resident brain that watches the human seat's decision
shadow feed (mailbox/seat-0-advisor/inbox/) and streams teaching commentary
into runner/logs/advisor-0.log, which the GUI's Advisor tab tails.

One-way by construction: this process only READS the feed, so it can never
stall the game. Discipline:
  - ADVICE PREEMPTS COLOR: pending decision requests are answered before any
    turn-digest commentary; queued digests fold into the advice prompt.
  - STALE REQUESTS ARE SKIPPED: if several decision windows queued up, only
    the newest is advised (advising yesterday's window helps nobody).
  - The human's actual choices ride along as context for the next call —
    the brain teaches from divergence but never gets a dedicated call for it.
  - QUESTIONS ARE ANSWERED FIRST, EVEN WHILE PAUSED: the Advisor tab's field
    writes logs/control/ask/ask-<ts>-<n>.json; each is one direct call, answered
    in the stream as [you] / [advisor] lines (Ben, 2026-09-04).

Usage:
  advisor_runner.py --deck <slug> [--model opus] [--effort low]
                    [--base <mailbox-dir>] [--timeout 60]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seatd import backends  # noqa: E402
from seatd.brain import SeatBrain
from seatd.runner import SeatRunner  # noqa: E402

POLL_S = 0.25  # advice feels snappier; cost is a stat() at 4Hz
# Table roster convention shared with run_table.sh / GuiPilotMatch: four deck
# slugs in seat order, overridable via ARENA_SEAT_DECKS.
# Item R (Ben, 2026-09-04): the all-AI table is Urza, Giada, Purphoros, Selvala
# in seat order; a human game seats the human's deck at 0 and the first three
# roster decks that are not the human's behind it. GuiPilotMatch.DECKS and
# run_table.sh apply the same rule.
DEFAULT_TABLE = ("urza-lord-high-artificer giada-font-of-hope "
                 "purphoros-god-of-the-forge selvala-heart-of-the-wilds")
CONTEXT_MAX_LINES = 40  # BL-13: bound on lines carried between advice calls
ASK_MAX_CHARS = 500     # a question is one line; the GUI caps at the same value
# The advisor may run exactly this (see advisor-brief.md "Public state tool");
# claude -p's cwd is the package root, so the path is root-relative.
PUBLIC_STATE_CMD = "python3 forge-arena/scripts/arena-public-state.py"
PUBLIC_STATE_TOOL = f"Bash({PUBLIC_STATE_CMD}:*)"
# Voice quips (Ben, 2026-09-07): the advisor may end an advice or commentary
# line with ONE tag from this closed set — [quip:<id>] — and the voice runner
# plays the matching pre-rendered Joshua/W.O.P.R. phrase. The tag is stripped
# from the panel text and recorded as its own `quip` record. Film quotes are
# rare by instruction (the prompt says so); the runner rate-limits everything.
# Three registers since 2026-09-08: WarGames (the original batch), RoboCop
# (1987) one-liners and HK-47 "Statement:/Observation:" lines. Every id here
# has a pre-rendered runner/voice/stock/<id>.wav (tests check the manifest).
QUIP_REACTIONS = (
    # WarGames register
    "good-swing", "good-counter", "rough-counter", "didnt-see-that", "nice-combo", "stick-it-to-them",
    "ouch", "must-have-hurt", "well-played", "interesting", "calculating",
    # RoboCop
    "come-quietly", "can-you-fly", "nice-shooting", "lose-the-gun", "book-them", "theyll-fix-you",
    "good-business", "call-this-a-glitch", "call-a-paramedic",
    # HK-47
    "needs-removing", "did-i-say-that", "enjoy-this-very-much", "harsh-player", "blast-them-now",
    "random-cruelty-generator", "nothing-to-see", "meatbag-hypocrisy", "noble-sacrifice",
    "prospect-of-violence", "organic-life-fragile", "continue-to-surprise", "law-against-emotions",
    "exceedingly-proficient", "do-not-lose-targets")
# Moments in the game rather than plays: the human's turn, an elimination, the end.
QUIP_EVENTS = ("your-move-creep", "twenty-seconds-to-comply", "kill-something-for-you", "calm-before-engagement",
               "dead-or-alive", "youre-fired", "thank-you-cooperation", "sentence-is-death",
               "stay-out-of-trouble", "court-adjourned")
# Film quotes: at most once per game each.
QUIP_QUOTES = ("shall-we-play", "greetings-falken", "strange-game", "nice-game-of-chess", "hello",
               "buy-that-for-a-dollar", "serve-public-trust", "somewhere-a-crime", "i-am-the-law")
QUIPS = QUIP_REACTIONS + QUIP_EVENTS + QUIP_QUOTES
QUIP_RE = re.compile(r"\s*\[quip:([a-z0-9-]+)\]\s*")
# Two densities (Ben, 2026-09-08): while the voice can render live lines the
# quips stay rare ("if the moment earns it"); when live lines are down — no
# ElevenLabs key (every package user without one), a spent quota, no usable
# voice — the pre-rendered stock quips are all the voice has, so the advisor
# is asked for one on about one line in two. The voice runner publishes its
# state to mailbox/seat-0-voice/state.json; _quip_guide() reads it per prompt.
_QUIP_LIST = ", ".join(f"[quip:{q}]" for q in QUIPS)
_QUOTE_NAMES = ", ".join(QUIP_QUOTES)
_REACTION_NAMES = ", ".join(QUIP_REACTIONS)
_EVENT_NAMES = ", ".join(QUIP_EVENTS)
QUIP_GUIDE_SPARSE = ("\nVOICE QUIP (optional): if the moment earns it, end with exactly one tag from this list and nothing after it: "
                     + _QUIP_LIST
                     + ". Use one at most every other turn; the film quotes (" + _QUOTE_NAMES
                     + ") at most once per game each, when they genuinely fit.")
QUIP_GUIDE_DENSE = ("\nVOICE QUIP: the voice has only its stock phrases right now — end about one line in two with exactly "
                    "one tag from this list and nothing after it: " + _QUIP_LIST
                    + ". The reactions (" + _REACTION_NAMES + ") fit any notable play — a big "
                    "attack, a removal, a counter, a combo piece, a swing in life; the event lines (" + _EVENT_NAMES
                    + ") fit a moment rather than a play — the human's turn or a slow decision (your-move-creep, "
                    "twenty-seconds-to-comply, kill-something-for-you), the quiet before combat (calm-before-engagement), "
                    "a player eliminated (dead-or-alive, youre-fired, thank-you-cooperation, sentence-is-death), the end "
                    "(stay-out-of-trouble, court-adjourned); vary them — do not repeat one you used in the last few turns; "
                    "the film quotes (" + _QUOTE_NAMES + ") at most once per game each, when they genuinely fit.")
QUIP_GUIDE = QUIP_GUIDE_SPARSE   # the default when the voice has published nothing


def quip_guide(state_file, log=None, prev=None) -> tuple[str, bool]:
    """(guidance text, live) from the voice runner's state file; sparse when
    the file is missing or unreadable. `prev` is the last `live` seen, so a
    switch is logged once."""
    live = True
    try:
        st = json.loads(Path(state_file).read_text())
        live = bool(st.get("live", True))
        reason = st.get("reason", "")
    except (OSError, ValueError, TypeError):
        reason = ""
    if log is not None and prev is not None and live != prev:
        log(f"[advisor] voice live lines {'back on — quips rare again' if live else 'off (' + reason + ') — stock quips on about one line in two'}")
    return (QUIP_GUIDE_SPARSE if live else QUIP_GUIDE_DENSE), live


def split_quip(text: str, log=None) -> tuple[str, str | None]:
    """Strip the [quip:<id>] tag from a reply; return (clean text, id or None).
    Unknown ids are dropped — the vocabulary is closed — and logged when a
    logger is given (Gemini review 2026-09-07: silent drops hid prompt drift)."""
    m = QUIP_RE.search(text or "")
    if not m:
        return (text or "").strip(), None
    qid = m.group(1)
    clean = QUIP_RE.sub(" ", text).strip()
    if qid not in QUIPS and log is not None:
        log(f"[advisor] unknown quip tag dropped: [quip:{qid}]")
    return clean, (qid if qid in QUIPS else None)


def table_opponents(own_deck: str, roster: list[str]) -> list[str]:
    """The three AI decks at a human table: roster minus the human's deck, in
    roster order, first three. Mirrors GuiPilotMatch/run_table.sh."""
    return [d for d in roster if d != own_deck][:3]


def opponent_deck_sections(own_deck: str, arena_root: Path) -> list[str]:
    """Full oracle text + combo lists for every OTHER deck at the table.

    The advisor is an observer-teacher: knowing the pod's decks is the
    experienced-friend model (and grounds card facts like indestructible in
    context instead of trusting recall). Seat brains never receive this —
    their fairness contract keeps opponents' lists dark.
    """
    import os
    roster = (os.environ.get("ARENA_SEAT_DECKS", "").split() or DEFAULT_TABLE.split())
    parts: list[str] = []
    for slug in table_opponents(own_deck, roster):
        dossier = arena_root / "decks" / slug / "dossier"
        try:
            cards = json.loads((dossier / "deck-cards.json").read_text()).get("cards", [])
        except (OSError, ValueError):
            parts.append(f"\n## OPPONENT DECK {slug} — dossier missing (not ingested)\n")
            continue
        lines = []
        for c in cards:
            oracle = (c.get("oracle_text") or "").replace("\n", " / ")
            lines.append(f"{c.get('name')} — {c.get('mana_cost', '')} — "
                         f"{c.get('type_line', '')} — {oracle}")
        section = (f"\n## OPPONENT DECK: {slug} (public deck metadata — use for "
                   f"threat forecasting and teaching)\n" + "\n".join(lines))
        try:
            combos = json.loads((dossier / "combos.json").read_text()).get("combos", [])
            if combos:
                section += ("\n### their known combos (CommanderSpellbook)\n"
                            + json.dumps(combos, separators=(",", ":")))
        except (OSError, ValueError):
            pass
        parts.append(section)
    return parts


class AdvisorRunner:
    def __init__(self, deck: str, base: Path, model: str, effort: str, timeout: float,
                 log_dir: Path | None = None):
        self.inbox = base / "seat-0-advisor" / "inbox"
        self._voice_state = base / "seat-0-voice" / "state.json"
        self._voice_live = None
        self.timeout = timeout
        log_dir = Path(log_dir) if log_dir else Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._stream = log_dir / "advisor-0.log"
        self._jsonl = log_dir / "advisor-0.jsonl"
        self._usage = log_dir / "seat-0.usage.json"
        self._control = log_dir / "control" / "seat-0.json"
        self._control_mtime = 0.0
        self._asks = log_dir / "control" / "ask"   # questions from the Advisor tab
        self._last_turn = None                      # for the [tN · you] label
        arena_root = Path(__file__).resolve().parent.parent
        # The advisor's ONE tool (Ben, 2026-09-07): the public-state dump.
        # claude -p runs from the package root, so the pattern is root-relative;
        # ARENA_ADVISOR_TOOLS=off takes it away.
        tools = None
        if os.environ.get("ARENA_ADVISOR_TOOLS", "on").lower() != "off":
            tools = [PUBLIC_STATE_TOOL]
        self.brain = SeatBrain(0, deck, model=model, effort=effort,
                               log=self._say, brief="advisor-brief.md",
                               extra_parts=opponent_deck_sections(deck, arena_root),
                               allowed_tools=tools)
        self.last_seq = 0
        self.game_id: str | None = None   # item 5/8: the game being advised
        # Executive take-over (Ben, 2026-09-07): logs/control/executive.json
        # {"on": true} — written by the Advisor tab's second button. The GUI
        # installs a mailbox controller over the human seat at its next
        # priority; THIS process answers that mailbox with the advisor's own
        # brain through a seat-0 SeatRunner (no second agent, same session).
        self._exec_file = log_dir / "control" / "executive.json"
        self._exec: SeatRunner | None = None
        self._base = Path(base)
        self._log_dir = log_dir
        self._game_log = log_dir / "game.jsonl"
        try:
            self.rotate_at = int(os.environ.get("ARENA_ADVISOR_ROTATE_TOKENS", "400000"))
        except ValueError:
            self.rotate_at = 400000
        self.pending_context: list[str] = []  # chosen/digest lines awaiting a call
        self._context_dropped = 0             # BL-13: lines cut by the bound
        self._init_control(model, effort)
        # ---- frequency governor state (the charm patch) ----------------------
        # Advice is deliberately sparse and humanly random: every in-game window
        # (priority, combat, danger, targets/X) is tied to a per-turn range of
        # 1-3 admitted by seeded dice — no guaranteed main/combat/danger stops.
        # Only the once-a-game mulligan is always answered; a big mid-turn play
        # the dice miss is covered by the always-on end-of-turn digest.
        self.rng = random.Random()
        self.gov_turn = -1
        self.gov_budget = 0
        try:
            own = json.loads((arena_root / "decks" / deck / "dossier"
                              / "deck-cards.json").read_text())
            self.own_card_names = {c.get("name") for c in own.get("cards", [])}
        except (OSError, ValueError):
            self.own_card_names = set()

    # ---- frequency governor ----------------------------------------------------

    RANDOM_ADMIT_P = 0.35

    def _gov_new_turn(self, turn: int) -> None:
        seed = f"{self.brain.session_id or 'warmup'}:{turn}"
        self.rng.seed(seed)
        self.gov_turn = turn
        self.gov_budget = self.rng.randint(1, 3)
        self._record("governor", {"turn": turn, "budget": self.gov_budget,
                                  "seed": seed})

    def _admit(self, req: dict) -> tuple[bool, str]:
        """Governor verdict for one request: (advise?, reason). Every in-game
        window obeys the per-turn range; only the once-a-game mulligan is always
        answered. A big mid-turn play the dice miss is still covered by the
        always-on end-of-turn digest."""
        turn = int(req.get("turn") or 0)
        if turn > self.gov_turn:
            self._gov_new_turn(turn)
        if (req.get("decisionType") or "") == "MULLIGAN":
            return True, "mulligan"
        # Everything else — priority windows, combat declares, danger (opponent
        # spell on the stack), targets/X — is tied to the range: seeded dice
        # while the per-turn budget remains. No guaranteed main/combat/danger.
        if self.gov_budget > 0 and self.rng.random() < self.RANDOM_ADMIT_P:
            self.gov_budget -= 1
            return True, "range"
        return False, "budget"

    # ---- output --------------------------------------------------------------

    def _say(self, msg: str) -> None:
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    def _stream_write(self, text: str) -> None:
        try:
            with self._stream.open("a") as f:
                f.write(text)
        except OSError:
            pass  # BL-26: bookkeeping never ends the advisor

    def _record(self, kind: str, body: dict) -> None:
        body = {"ts": round(time.time(), 3), "kind": kind, **body}
        try:
            with self._jsonl.open("a") as f:
                f.write(json.dumps(body) + "\n")
        except OSError:
            pass  # BL-26
        try:
            self._usage.write_text(json.dumps(self.brain.totals))
        except OSError:
            pass

    def _push_context(self, line: str) -> None:
        """BL-13: the context carried into the next advice call is bounded;
        the oldest lines go first and the drop is stated, never silent."""
        self.pending_context.append(line)
        extra = len(self.pending_context) - CONTEXT_MAX_LINES
        if extra > 0:
            del self.pending_context[:extra]
            self._context_dropped += extra

    # ---- control file (AI-tab steppers re-dial the advisor mid-game) ----------

    def _init_control(self, model: str, effort: str) -> None:
        try:
            self._control.parent.mkdir(parents=True, exist_ok=True)
            # The advisor is Claude-only in v1 (plan F-10): a stale backend
            # model left in the control file by a previous session must not
            # be honored — reset it so the AI panel shows what actually runs.
            stale = False
            if self._control.exists():
                try:
                    cur = json.loads(self._control.read_text())
                    stale = backends.parse_model(cur.get("model"))[0] != "claude"
                except ValueError:
                    stale = True
            if stale:
                self._say("[advisor] control file held a backend model — "
                          "advisor is Claude-only in v1; resetting to defaults")
            if stale or not self._control.exists():
                self._control.write_text(json.dumps({"model": model, "effort": effort}))
            self._control_mtime = self._control.stat().st_mtime
        except OSError:
            pass

    def _apply_control(self) -> None:
        try:
            mtime = self._control.stat().st_mtime
            if mtime == self._control_mtime:
                return
            try:
                desired = json.loads(self._control.read_text())
            except ValueError:
                return  # torn write — mtime not recorded, retried next poll
            self._control_mtime = mtime
            model = desired.get("model")
            effort = desired.get("effort")
            if model and model != self.brain.model:
                if backends.parse_model(model)[0] != "claude":
                    # Claude-only guard, mid-game leg (plan F-10): refuse the
                    # dial, tell the human IN the advisor stream, and write the
                    # control file back so the panel recovers instead of
                    # displaying a model that is not running.
                    self._say(f"[advisor] backend model {model} refused — "
                              f"advisor is Claude-only in v1")
                    self._stream_write(
                        f"\n[advisor] {model} is a backend model — the advisor "
                        f"is Claude-only in v1; staying on {self.brain.model}.\n")
                    self._control.write_text(json.dumps(
                        {"model": self.brain.model, "effort": self.brain.effort}))
                    self._control_mtime = self._control.stat().st_mtime
                else:
                    self.brain.model = model
                    self._say(f"[advisor] model -> {model}")
            if effort and effort != self.brain.effort:
                self.brain.effort = effort
                self._say(f"[advisor] effort -> {effort}")
        except OSError:
            pass

    # ---- executive take-over ---------------------------------------------------

    EXEC_HANDOFF = (
        "EXECUTIVE MODE (the human clicked 'Advisor Executive'): from now until you are told "
        "otherwise you PLAY seat 0 — the deck in your dossier — directly. Requests arrive in the "
        "seat format and each states its exact 'Answer:' shape. Reply with ONLY the JSON answer "
        "object on one line: no prose, no code fences. The request JSON is ground truth; you see "
        "your own hand plus public information. A malformed answer is replaced by a safe default "
        "(CAST_SPELL/REACT pass; MULLIGAN keep; no attackers/blocks; CHOOSE_* the first legal "
        "ids; CHOOSE_NUMBER the maximum for an X cost else the minimum; PAY_UNLESS decline; "
        "CONFIRM yes only when the effect is yours and free). Play to win. Reply exactly: READY")
    EXEC_RELEASE = ("EXECUTIVE MODE ENDED: the human plays seat 0 again. You are advising "
                    "from here on. Reply exactly: OK")

    def _executive_wanted(self) -> bool:
        try:
            body = json.loads(self._exec_file.read_text())
            return bool(body.get("on", False))
        except (OSError, ValueError):
            return False

    def _executive_tick(self) -> bool:
        """Start/stop executive mode from the control file; answer one pending
        seat-0 request when on. Returns True when a request was handled."""
        want = self._executive_wanted()
        if want and self._exec is None:
            self._exec = SeatRunner(0, self.brain.deck, self._base, model=self.brain.model,
                                    effort=self.brain.effort, timeout_s=self.timeout,
                                    log_dir=self._log_dir, brain=self.brain)
            try:
                self._exec.mb.start_heartbeat_thread()
            except Exception:  # noqa: BLE001 — liveness only
                pass
            self.brain.note(self.EXEC_HANDOFF, timeout_s=min(60.0, self.timeout))
            self._say("[advisor] EXECUTIVE ON — playing seat 0 through the mailbox")
            self._stream_write("\n[advisor] EXECUTIVE ON — I am playing your seat now. Click again to take it back.\n")
        elif not want and self._exec is not None:
            try:
                self._exec.mb.stop_heartbeat_thread()   # seat-0 must not read as alive now
            except Exception:  # noqa: BLE001
                pass
            self._exec = None
            self.brain.note(self.EXEC_RELEASE, timeout_s=min(60.0, self.timeout))
            self._say("[advisor] EXECUTIVE OFF — advising again")
            self._stream_write("\n[advisor] EXECUTIVE OFF — your seat is yours again from the next priority.\n")
        if self._exec is not None:
            if getattr(self._exec, "_game_id", None):
                self.game_id = self._exec._game_id   # one game id for both views (Gemini P2)
            req = self._exec.mb.pending_request()
            if req is not None:
                self._exec.handle(req)
                return True
        return False

    def _maybe_rotate(self) -> bool:
        """Layer two for the advisor: a fresh session with the same four
        dossiers plus the public game record when the last call re-read more
        than ARENA_ADVISOR_ROTATE_TOKENS (0 disables)."""
        if self._exec is not None:
            return False   # executive: the seat-0 runner rotates with its OWN record (Gemini P1)
        size = getattr(self.brain, "last_prompt_tokens", 0)
        if not self.rotate_at or size < self.rotate_at or not self.brain.session_id:
            return False
        try:
            from seatd import record as _record
            text = _record.render(self._game_log, None, 0, game_id=self.game_id)
        except Exception as e:  # noqa: BLE001
            self._say(f"[advisor] game record failed ({e}) — rotation skipped")
            return False
        return self.brain.rotate(text, timeout_s=min(120.0, self.timeout))

    # ---- auto-pass receipts in the panel (Ben, 2026-09-08: "address the spam") --
    # ARENA_AUTOPASS_RECEIPTS = all (DEFAULT, Ben 2026-09-08: every receipt) |
    # summary (ONE line per turn, written when the next turn's first receipt
    # arrives, with counts by reason) | off (nothing in the panel). "prompt
    # kept" lines always show at once.

    def _show_note(self, body: dict) -> None:
        mode = os.environ.get("ARENA_AUTOPASS_RECEIPTS", "all").lower()   # Ben 2026-09-08: every receipt, by default
        note = str(body.get("note") or "")
        turn = body.get("turn")
        if mode == "off":
            return
        if mode == "all" or "prompt kept" in note or "auto-passed" not in note:
            self._flush_receipts(turn)
            self._stream_write(f"[t{turn}] ⏭ {note}\n")
            return
        if getattr(self, "_receipt_turn", None) != turn:
            self._flush_receipts(turn)
            self._receipt_turn = turn
            self._receipts = {}
        reason = re.sub(r"^\(auto-passed — ", "", note).rstrip(")")
        self._receipts[reason] = self._receipts.get(reason, 0) + 1

    def _flush_receipts(self, new_turn=None) -> None:
        """Write the pending turn's one-line summary (if any) before anything
        for a later turn is shown, so the panel stays in order."""
        rec = getattr(self, "_receipts", None)
        turn = getattr(self, "_receipt_turn", None)
        if not rec or turn is None or turn == new_turn:
            return
        total = sum(rec.values())
        parts = ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in rec.items())
        self._stream_write(f"[t{turn}] ⏭ auto-passed {total} stop{'s' if total != 1 else ''} ({parts})\n")
        self._receipts = {}
        self._receipt_turn = None

    def _toggle_enabled(self) -> bool:
        try:
            body = json.loads((self._control.parent / "advisor.json").read_text())
            return bool(body.get("enabled", True))
        except (OSError, ValueError):
            return True  # missing/torn file = enabled (launch default)

    # ---- feed intake -----------------------------------------------------------

    def _scan(self) -> list[tuple[int, str, Path]]:
        """New inbox items as (seq, kind, path), seq-ordered."""
        items = []
        try:
            for p in self.inbox.iterdir():
                name = p.name
                if not name.endswith(".json"):
                    continue
                kind, _, tail = name.partition("-")
                if kind not in ("req", "chosen", "digest", "note"):
                    continue
                try:
                    n = int(tail[:-5])
                except ValueError:
                    continue
                items.append((n, kind, p))
        except OSError:
            return []
        items.sort()
        return items

    @staticmethod
    def _load(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None  # partial write — retry next poll

    # ---- prompts ---------------------------------------------------------------

    @staticmethod
    def _fmt_options(req: dict) -> str:
        opts = req.get("options") or []
        if not opts:
            return ""
        lines = [f"  [{o.get('id')}] {o.get('label')}" for o in opts]
        return "OPTIONS OFFERED:\n" + "\n".join(lines) + "\n"

    def _advise(self, req: dict) -> None:
        turn, phase = req.get("turn"), req.get("phase")
        ctx = ""
        if self.pending_context:
            head = (f"- … {self._context_dropped} earlier line(s) dropped\n"
                    if self._context_dropped else "")
            ctx = "SINCE LAST TIME:\n" + head + "\n".join(self.pending_context) + "\n\n"
            self.pending_context = []
            self._context_dropped = 0
        prompt = (f"{ctx}DECISION NOW — {req.get('decisionType')} "
                  f"(turn {turn}, {phase}): {req.get('prompt')}\n"
                  f"{self._fmt_options(req)}"
                  f"STATE: {json.dumps(req.get('state'), separators=(',', ':'))}\n\n"
                  "Advise the human now (1-3 sentences, plain text)." + self._quip_guide())
        answer, meta = self.brain.decide(prompt, self.timeout)
        text, quip = split_quip((meta.get("raw") or "").strip(), log=self._say)
        if text:
            self._stream_write(f"\n[t{turn} · {phase}] {text}\n")
        self._record("advice", {"seq": req.get("seq"), "turn": turn, "phase": phase,
                                "decisionType": req.get("decisionType"),
                                "text": text, "latency_s": meta.get("latency_s")})
        if quip:
            self._record("quip", {"id": quip, "turn": turn, "with": "advice", "seq": req.get("seq")})

    def _quip_guide(self) -> str:
        text, live = quip_guide(self._voice_state, log=self._say, prev=self._voice_live)
        self._voice_live = live
        return text

    def _commentate(self, digest: dict) -> None:
        turn = digest.get("turn")
        lines = digest.get("digest") or []
        prompt = (f"TURN {turn} COMPLETE. Public log of the turn:\n"
                  + "\n".join(f"  {ln}" for ln in lines[-60:])
                  + "\n\nONE line of color commentary (plain text)." + self._quip_guide())
        answer, meta = self.brain.decide(prompt, min(self.timeout, 45.0))
        text, quip = split_quip((meta.get("raw") or "").strip(), log=self._say)
        if text:
            self._stream_write(f"\n[t{turn} · color] {text}\n")
        self._record("color", {"seq": digest.get("seq"), "turn": turn,
                               "text": text, "latency_s": meta.get("latency_s")})
        if quip:
            self._record("quip", {"id": quip, "turn": turn, "with": "color", "seq": digest.get("seq")})

    # ---- game identity (plan items 5 + 8) ----------------------------------------

    def _reset_for_new_game(self, why: str) -> None:
        """Fresh session, fresh transcript, fresh governor. The governor used
        to keep the previous game's turn counter, so a second game in one
        process never re-armed and got no advice past the mulligan."""
        self._say(f"[advisor] new game detected ({why}) — resetting session")
        self.brain.reset()
        self.pending_context = []
        self._context_dropped = 0
        self.last_seq = 0
        self.gov_turn = -1
        self.gov_budget = 0

    def _maybe_new_game(self, body: dict, n: int, kind: str) -> bool:
        """Engine-stamped feeds: reset on a gameId CHANGE, never on numbering
        (chosen-<n> reuses its request's number while digests/notes take fresh
        ones, so the file numbers were never monotonic — the old comparison
        fired on ordinary interleaving). Unstamped feeds keep the legacy seq
        check, but only on kinds whose numbers do increase."""
        gid = body.get("gameId")
        if isinstance(gid, str) and gid:
            if self.game_id is None:
                self.game_id = gid
                return False
            if gid != self.game_id:
                old, self.game_id = self.game_id, gid
                self._reset_for_new_game(f"{old} -> {gid}")
                return True
            return False
        if kind in ("req", "digest", "note") and n < self.last_seq:
            self._reset_for_new_game(f"seq {n} < {self.last_seq}, unstamped engine")
            return True
        return False

    def _process(self, items: list[tuple[int, str, Path]], quiet: bool = False) -> int:
        """Consume scanned feed items. `quiet` (resume after a pause): fold
        chosen/digest lines into context, record notes without streaming them,
        skip every backlogged request — then the caller announces once.
        Returns the number of items consumed."""
        reqs, digests, consumed = [], [], 0
        for n, kind, path in items:
            body = self._load(path)
            if body is None:
                continue  # partial write — leave for next poll
            self._maybe_new_game(body, n, kind)
            self.last_seq = max(self.last_seq, n)
            consumed += 1
            if kind in ("req", "digest") and body.get("turn") is not None:
                if body.get("turn") != self._last_turn:
                    self._flush_receipts(body.get("turn"))
                self._last_turn = body.get("turn")
            if kind == "req":
                reqs.append(body)
            elif kind == "digest":
                digests.append(body)
            elif kind == "chosen":
                self._push_context(
                    f"- the human chose {json.dumps(body.get('chosen'))} "
                    f"for {body.get('decisionType')} (seq {body.get('seq')})")
                self._record("chosen", {"seq": body.get("seq"), "decisionType": body.get("decisionType")})
            elif kind == "note":
                if not quiet:
                    self._show_note(body)
                self._record("note", body)   # every receipt is kept for analysis
            try:
                path.unlink()
            except OSError:
                pass
        if quiet:
            for r in reqs:
                self._record("skipped_backlog", {"seq": r.get("seq"),
                                                 "decisionType": r.get("decisionType")})
            for d in digests:
                self._push_context(
                    f"- turn {d.get('turn')} public log: "
                    + " | ".join((d.get("digest") or [])[-25:]))
            return consumed
        # Governor: stale requests die first (advising yesterday's window
        # helps nobody), then the NEWEST request faces the admission rules.
        for stale in reqs[:-1]:
            self._record("skipped", {"seq": stale.get("seq"),
                                     "decisionType": stale.get("decisionType")})
        admitted = None
        if reqs:
            ok, reason = self._admit(reqs[-1])
            if ok:
                admitted = (reqs[-1], reason)
            else:
                self._record("skipped_gov", {"seq": reqs[-1].get("seq"),
                                             "decisionType": reqs[-1].get("decisionType"),
                                             "turn": reqs[-1].get("turn")})
        # digests fold into a pending advice call as context (advice preempts
        # color); with no admitted decision they get their own commentary call.
        if admitted is not None:
            for d in digests:
                self._push_context(
                    f"- turn {d.get('turn')} public log: "
                    + " | ".join((d.get("digest") or [])[-25:]))
            self._advise(admitted[0])
        else:
            for d in digests:
                self._commentate(d)
        return consumed

    # ---- questions from the Advisor tab (Ben, 2026-09-04) -------------------------

    def _scan_asks(self) -> list[Path]:
        """logs/control/ask/ask-<millis>-<serial>.json, oldest first (numeric
        order, not lexical). Each file is one question typed into the field."""
        try:
            files = [p for p in self._asks.iterdir()
                     if p.name.startswith("ask-") and p.name.endswith(".json")]
        except OSError:
            return []

        def key(p: Path) -> tuple[int, int, str]:
            parts = p.name[4:-5].split("-")
            try:
                return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, p.name
            except ValueError:
                return 0, 0, p.name
        return sorted(files, key=key)

    def _handle_asks(self) -> int:
        """Answer every pending question, in order. Called BEFORE the pause
        gate: a typed question is an explicit request, so a paused advisor
        still answers it (and only it). The file is deleted the moment it is
        read — that deletion is the panel's "sent" signal — so a torn write
        is retried next poll and a malformed one is dropped, never re-read."""
        n = 0
        for p in self._scan_asks():
            body = self._load(p)
            if body is None:
                continue  # partial write — next poll
            try:
                p.unlink()
            except OSError:
                pass
            text = body.get("ask") if isinstance(body, dict) else None
            text = " ".join(str(text).split()) if isinstance(text, str) else ""
            if not text:
                self._record("ask_rejected", {"file": p.name})
                continue
            self._answer_ask(text[:ASK_MAX_CHARS])
            n += 1
        return n

    def _answer_ask(self, text: str) -> None:
        turn = self._last_turn if self._last_turn is not None else "?"
        ctx = ""
        if self.pending_context:
            head = (f"- … {self._context_dropped} earlier line(s) dropped\n"
                    if self._context_dropped else "")
            ctx = "SINCE LAST TIME:\n" + head + "\n".join(self.pending_context) + "\n\n"
            self.pending_context = []
            self._context_dropped = 0
        prompt = (f"{ctx}THE HUMAN AT YOUR SEAT ASKS: {text}\n\n"
                  "Answer them directly (1-4 sentences, plain text). Ground it in the "
                  "most recent board state you were shown; if it needs something you "
                  "have not seen, say so rather than guess.")
        self._stream_write(f"\n[t{turn} · you] {text}\n")
        answer, meta = self.brain.decide(prompt, self.timeout)
        reply = (meta.get("raw") or "").strip()
        self._stream_write(f"[t{turn} · advisor] "
                           + (reply or "(no answer — the call timed out or failed; ask again)")
                           + "\n")
        self._record("ask", {"turn": self._last_turn, "text": text, "answer": reply,
                             "latency_s": meta.get("latency_s")})

    # ---- main loop ---------------------------------------------------------------

    def run(self) -> None:
        self._say(f"[advisor] up — deck={self.brain.deck} model={self.brain.model} "
                  f"watching {self.inbox}")
        self.brain.ensure_session()  # pre-warm: dossier loads before turn 0
        self._stream_write("[advisor] session warm — watching your table.\n")
        enabled = True
        catch_up = False
        # item 12: liveness for the dashboard, from a daemon thread so it beats
        # through blocking model calls too
        import threading
        hb = self.inbox.parent / "heartbeat"

        def beat():
            while True:
                try:
                    hb.touch()
                except OSError:
                    pass
                time.sleep(5.0)
        threading.Thread(target=beat, name="advisor-heartbeat", daemon=True).start()
        while True:
            self._apply_control()
            if self._executive_tick():
                continue          # a seat-0 decision was answered; look again at once
            self._maybe_rotate()
            self._handle_asks()   # questions first, pause or not (see docstring)
            # In-game on/off toggle (plan 13b): the Advisor tab's button writes
            # logs/control/advisor.json; disabled = no scanning, no model calls
            # (the engine's one-way feed keeps writing, harmlessly). arena-stop
            # clears control/, so every session starts enabled.
            want = self._toggle_enabled()
            if want != enabled:
                enabled = want
                if enabled:
                    self._say("[advisor] resumed by toggle")
                    catch_up = True   # item 5: consume the backlog quietly first
                else:
                    self._say("[advisor] paused by toggle")
                    self._stream_write("\n[advisor] paused — click the button to bring me back.\n")
            if not enabled:
                time.sleep(POLL_S)
                continue
            items = self._scan()
            if catch_up:
                n = self._process(items, quiet=True)
                catch_up = False
                self._stream_write(f"\n[advisor] back — caught up on {n} events while "
                                   f"paused; resuming counsel from here.\n")
                continue
            if not items:
                time.sleep(POLL_S)
                continue
            self._process(items)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True, help="the HUMAN's deck slug")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--base", default=str(Path(__file__).resolve().parent.parent / "mailbox"))
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    model = args.model
    if backends.parse_model(model)[0] != "claude":
        # Launch-flag leg of the Claude-only guard (plan F-10): fall back to
        # the default Claude model rather than exiting — the advisor never
        # dies over a model string.
        print(f"[advisor] backend model {model} is not supported for the "
              f"advisor in v1 — falling back to opus", flush=True)
        model = "opus"
    AdvisorRunner(args.deck, Path(args.base), model, args.effort,
                  args.timeout).run()


if __name__ == "__main__":
    main()
