"""The seat loop: mailbox -> (fastpath | brain) -> validate -> respond.

Wiring rules (from docs/AGENT-SDK-SEATS.md):
- ZERO-API fastpaths run before any model call:
  (0) dead windows: every non-pass option costs more mana than
      state.manaAvailableNow (no free/alt/X/Phyrexian option), or every option
      is a plain mana ability, or the stack is empty and every option is a
      counterspell → pass
  (a) react_autopass: a REACT whose non-pass options are all on the no-op
      allowlist is passed instantly (the Giver-of-Runes cure);
  (b) memoized same-turn REACT: an identical (turn, stack, options) signature
      already passed this turn is re-passed without a call.
- Deadline discipline: the answer must land by req_mtime + 0.8 * engine
  timeout; the model gets what's left, and a late/failed call becomes
  rules.safe_default() — ALWAYS answer, never silence.
- In-band turn plan: a `turn_plan` emitted at the seat's own main phase is
  cached for the turn and quoted back as ADVISORY (request state wins).
- game_reset (seq regression) wipes plan, memos, and the brain session.
"""
from __future__ import annotations

import json
import re
import os
import time
from pathlib import Path

from . import backends, rules
from .brain import SeatBrain
from .protocol import SeatMailbox

DEFAULT_AUTOPASS = ("Giver of Runes", "Mother of Runes", "Academy Ruins")


class SeatRunner:
    # Defaults for a runner built without __init__ (offline tests use __new__):
    # rotation off, no game id, no repeat/yield memory yet.
    rotate_at = 0  # class default
    rotate_hard = 0
    _game_id = None
    _tap_pass = None
    _yielded = None   # dict once the first yield is noted (never a shared class dict)
    def __init__(self, seat: int, deck: str, base, model: str = "sonnet",
                 effort: str = "low", timeout_s: float = 90.0, log_dir=None,
                 autopass: tuple[str, ...] = DEFAULT_AUTOPASS,
                 speculative: bool = False, react_hold: bool = False,
                 brain=None):
        self.mb = SeatMailbox(seat, base, timeout_s=timeout_s)
        # Executive take-over (Ben, 2026-09-07): the ADVISOR's own brain — the
        # session that already holds all four dossiers — can be injected and
        # plays seat 0 through this runner's protocol loop. No second agent.
        self.brain = brain if brain is not None else SeatBrain(
            seat, deck, model=model, effort=effort, log=self._say)
        # Session rotation cap (tokens the model re-read on the last call).
        # 0 disables. Applied at a turn boundary, never inside a window.
        try:
            self.rotate_at = int(os.environ.get("ARENA_ROTATE_TOKENS", "250000"))
        except ValueError:
            self.rotate_at = 250000
        # Hard ceiling (game 28, 2026-09-08: Urza's 145-decision turn 17 grew
        # the chat to 851k before the turn boundary let it rotate). Past this
        # the seat rotates at the NEXT decision, mid-turn; the record carries
        # the turn's plays so far. 0 disables.
        try:
            self.rotate_hard = int(os.environ.get("ARENA_ROTATE_HARD", "600000"))
        except ValueError:
            self.rotate_hard = 600000
        self._game_id: str | None = None
        self.seat, self.deck = seat, deck
        self.timeout_s = timeout_s
        self.autopass = tuple(autopass)
        self.speculative = speculative
        self.react_hold = react_hold
        # Reactive hold posture (#2): brain-armed, same-turn REACT batching.
        #   {"turn": int, "seen": set(stack-object names already passed)}
        # Auto-passes later reacts whose stack objects are ALL already-seen and
        # non-empty; ANY new object or an empty-stack window escalates.
        self.hold: dict | None = None
        # Executable turn plan (SPEC-executable-turn-plans.md): dict or None.
        #   {"turn": int, "steps": [{"card","why"}], "idx": int}
        # Consumed locally under the four-part guard; discarded on any divergence.
        self.plan: dict | None = None
        self.react_seen: set[tuple] = set()
        # Repeat rule (2026-09-07, game 25 t23): the last MODEL pass of a
        # resourceless, tap-only REACT window this turn — (turn, option set,
        # own life). Cleared with the turn.
        self._tap_pass: tuple | None = None
        # Auto-yield (Forge's GUI notion, seat-side; Ben 2026-09-07): keys
        # (turn, top item name, owner, kind, option set) the MODEL passed on this
        # turn while the stack held no spell -> (own life, pool, untapped).
        self._yielded: dict[tuple, tuple] = {}
        # BL-02 follow-up: a trigger-order answer for the SAME set of trigger
        # groups is replayed for the rest of the TURN (Purphoros + Impact
        # Tremors would otherwise ask on every creature). Cleared with the other
        # per-turn memos at the turn boundary and on a new game: a stale order
        # across turns is wrong more often than it is cheap. Keyed by the sorted
        # option labels; the answer is stored as labels in resolution order and
        # rebound to the new window's indices. Fed only by real model answers.
        self.order_memo: dict[tuple, list[str]] = {}
        # Cycle replay (backlog item 3, 2026-08-17): the brain may declare
        # "repeat_cycle": N on a decision it has answered identically before
        # this turn; the runner replays the recorded cycle's answers for
        # signature-matching windows at zero model calls, breaking to the
        # model on ANY novelty. self._hist is this turn's decision tape.
        self.cycle = None          # {steps, ptr, rounds, total}
        self._hist = []            # [(sig, dtype, shape)] this turn
        self._last_turn: int | None = None
        # Stated intent for the current own turn (brain's `turn_plan`), kept in
        # NORMAL mode purely as an ADVISORY quote-back + deviation reference —
        # never executed (that is the separate, off-by-default speculative
        # plan). Cleared every turn.
        self.turn_intent: str | None = None
        log_dir = Path(log_dir) if log_dir else Path(__file__).parents[1] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / f"seat-{seat}.log"
        self._jsonl_path = log_dir / f"seat-{seat}.jsonl"
        # Shared table narrative: every seat APPENDS one line per decision
        # (never reads it) — an interleaved, board-stamped play-pattern record.
        self._game_log = log_dir / "game.jsonl"
        # Live control file: desired {model, effort} for this seat. The runner
        # is the reconciler — it publishes its launch values if the file is
        # absent, honors the file if present (UI/CLI writes win), and applies
        # changes at the next decision boundary (sessions survive: model and
        # effort are per-call flags on a transcript-based session).
        self._control_path = log_dir / "control" / f"seat-{seat}.json"
        self._control_mtime = 0.0
        # Crash-restart spend persistence (plan F-02): run_table.sh restarts a
        # crashed runner in 2s with a fresh brain — the backend cost/call rails
        # must resume, not reset. Backend seats only: the Claude path's totals
        # start at zero exactly as they always have.
        if self.brain.backend is not None:
            self._seed_spend()
        self._init_control()
        # Deck combos (CommanderSpellbook included-combos distillation) for the
        # per-decision COMBO STATUS line. Ship-pattern source: dossier/combos.json
        # only — no project-internal combo-program/advisory artifacts. Item 13b:
        # resolve() like the siblings (a relative __file__ found nothing and
        # every prompt silently lost its combo grounding), and SAY when absent.
        self.combos: list = []
        combos_p = (Path(__file__).resolve().parents[2] / "decks" / deck
                    / "dossier" / "combos.json")
        try:
            if combos_p.exists():
                self.combos = (json.loads(combos_p.read_text()).get("combos") or [])
            else:
                self._say(f"[seat {seat}] WARN combos.json missing at {combos_p} — "
                          f"COMBO STATUS lines will be absent from every prompt")
        except (OSError, json.JSONDecodeError) as e:
            self.combos = []
            self._say(f"[seat {seat}] WARN combos.json unreadable ({e}) — "
                      f"COMBO STATUS lines will be absent")

    def _seed_spend(self) -> None:
        p = self._jsonl_path.parent / f"seat-{self.seat}.usage.json"
        try:
            prev = json.loads(p.read_text())
        except (OSError, ValueError):
            if p.exists():
                self._say(f"[seat {self.seat}] usage snapshot unreadable — "
                          f"resetting cost counters (rails restart at zero)")
            return
        for k in ("calls", "input_tokens", "output_tokens",
                  "cache_read_input_tokens", "cache_creation_input_tokens",
                  "cost_usd", "backend_attempts", "unmetered_attempts",
                  "unmetered_est_tokens"):
            v = prev.get(k)
            if isinstance(v, (int, float)):
                self.brain.totals[k] = v
        if self.brain.totals.get("cost_usd") or self.brain.totals.get(
                "backend_attempts"):
            self._say(f"[seat {self.seat}] resumed spend rails from snapshot: "
                      f"${self.brain.totals.get('cost_usd', 0):.2f}, "
                      f"{self.brain.totals.get('backend_attempts', 0)} attempts")

    def _init_control(self) -> None:
        try:
            self._control_path.parent.mkdir(parents=True, exist_ok=True)
            if self._control_path.exists():
                self._apply_control(startup=True)
            else:
                self._control_path.write_text(json.dumps(
                    {"model": self.brain.model, "effort": self.brain.effort}))
                self._control_mtime = self._control_path.stat().st_mtime
        except OSError:
            pass

    def _apply_control(self, startup: bool = False) -> None:
        """Poll the control file; apply model/effort changes to the brain."""
        try:
            mtime = self._control_path.stat().st_mtime
        except OSError:
            return
        if mtime == self._control_mtime:
            return
        try:
            desired = json.loads(self._control_path.read_text())
        except (OSError, json.JSONDecodeError):
            # Torn/bad write: mtime is deliberately NOT recorded, so the next
            # poll retries instead of swallowing the change forever (plan F-34).
            return
        model = desired.get("model")
        effort = desired.get("effort")
        model_change = (isinstance(model, str) and model
                        and model != self.brain.model)
        # Debounce a dial-to-backend (plan F-38): a stepper traversing a
        # prefixed entry between clicks must not bill a cold-start init. Only
        # swaps TO a backend wait for a 2s-stable file; Claude re-dials keep
        # today's instant path.
        if (model_change and not startup
                and backends.parse_model(model)[0] != "claude"
                and time.time() - mtime < 2.0):
            return  # mtime not recorded — re-evaluated next poll
        self._control_mtime = mtime
        changes = []
        if model_change:
            changes.append(f"model {self.brain.model}->{model}")
            self.brain.set_model(model)
        if isinstance(effort, str) and effort and effort != self.brain.effort:
            changes.append(f"effort {self.brain.effort}->{effort}")
            self.brain.effort = effort
        if changes:
            self._say(f"[seat {self.seat}] CONTROL applied: " + ", ".join(changes)
                      + (" (startup)" if startup else ""))

    # ---- logging ---------------------------------------------------------

    def _say(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            with self._log_path.open("a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    @staticmethod
    def board_stamp(req: dict) -> dict:
        """Compact PUBLIC board digest computed script-side (zero tokens):
        life by seat, stack, own board size/power, combat picture if any."""
        st = req.get("state", {}) or {}
        lives = {str(st.get("seat")): st.get("life")}
        for o in st.get("opponents", []) or []:
            lives[str(o.get("seat"))] = o.get("life")
        stamp = {"lives": lives,
                 "stack": st.get("stack") or [],
                 "ownPow": st.get("ownBoardPower"),
                 "ownPerms": len(st.get("battlefield") or []),
                 # pool in the stamp: the 2026-08-10 "seven floating mana"
                 # forensics needed exactly this and it wasn't recorded
                 "pool": st.get("manaPool"),
                 "untappedSrc": st.get("untappedManaSourceCount",
                                       st.get("untappedManaSources"))}
        combat = st.get("combat")
        if combat:
            stamp["combat"] = [f"{a.get('name')} {a.get('power')}/"
                               f"{a.get('toughness')} -> {a.get('defender')}"
                               + (f" [blocked: {', '.join(a['blockedBy'])}]"
                                  if a.get("blockedBy") else "")
                               for a in combat][:6]
        return stamp

    def _transport_event(self, kind: str, game_id=None) -> None:
        """Append {ts, seat, kind, gameId} to logs/transport-events.jsonl — the
        ratings applier voids transport-contaminated games from this file
        (any wedge, or a punt pile-up on one seat). BL-09: the game id lets
        the sweep attribute an event to its game exactly; the time window is
        the fallback for events from an unstamped engine. The file is never
        rotated or moved during a session (one append, one file)."""
        try:
            p = self._jsonl_path.parent / "transport-events.jsonl"
            with p.open("a") as f:
                f.write(json.dumps({"ts": time.time(), "seat": self.seat,
                                    "kind": kind, "gameId": game_id}) + "\n")
        except OSError:
            pass  # never let bookkeeping hurt the game

    def _game_log_paths(self, gid) -> list:
        """The two append targets for one narrative record (BL-21, replacing
        item 13h's symlink swap): game.jsonl, a PLAIN append-only file that is
        the human `tail -f` target for the whole session and is archived at
        teardown; and game-<gid>.jsonl, the per-game machine record ratings
        and the dashboards read. Both are single-line appends to files that
        are never moved during a session — the one file operation with no
        partial-state window. A symlink left by a pre-BL-21 runner is removed
        once so the plain file can take its place (a sibling seat may have
        removed it first; that is fine)."""
        flat = self._game_log
        if not getattr(self, "_game_log_checked", False):
            self._game_log_checked = True
            try:
                if flat.is_symlink():
                    os.unlink(flat)
            except OSError:
                pass
        paths = [flat]
        if isinstance(gid, str) and gid:
            paths.append(flat.with_name(f"game-{gid}.jsonl"))
        return paths

    def _record(self, req: dict, answer: dict, source: str, meta=None,
                why: str | None = None, consumed: bool = True) -> None:
        stamp = self.board_stamp(req)
        rec = {"ts": time.time(), "seat": self.seat, "gameId": req.get("gameId"),
               "seq": req.get("seq"),
               "turn": req.get("turn"), "phase": req.get("phase"),
               "type": req.get("decisionType"), "source": source,
               "model": self.brain.model,
               "effort": (meta or {}).get("effort") or self.brain.effort,
               "answer": answer, "why": why, "consumed": consumed,
               "board": stamp}
        # Log the FULL option list for model/plan/hold decisions (the 08-10
        # forensics fought the old 9-entry truncation: seq85 chose id 13 with
        # only 9 recorded). ~80 chars/label keeps a 40-option board <4KB.
        if source in ("model", "plan", "hold"):
            rec["options"] = [str(o.get("label", ""))[:80]
                              for o in req.get("options", [])]
        if req.get("decisionType") == "MULLIGAN":
            st = req.get("state", {}) or {}
            rec["hand"] = st.get("hand")            # audit mulligan judgment
            rec["cardsToReturn"] = st.get("cardsToReturn")
        if meta:
            rec["latency_s"] = meta.get("latency_s")
            rec["usage"] = meta.get("usage")
        dev = getattr(self, "_deviation", None)
        if dev:
            rec["deviation"] = dev
        if self.turn_intent and source == "model":
            rec["turn_intent"] = self.turn_intent
        cum = dict(self.brain.totals)  # burn since instantiation
        for k in ("last_prompt_tokens", "rotations", "persistent_calls", "persistent_fallbacks"):
            v = getattr(self.brain, k, None)
            if isinstance(v, int):
                cum[k] = v
        if self.brain.backend is not None:
            cum["backend"] = self.brain.backend.kind      # additive (plan §8)
            if self.brain.backend.cap_unenforceable:
                cum["cap_enforceable"] = False
        rec["cum"] = cum
        try:
            with self._jsonl_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            # Always-current snapshot: THE final readout is whatever this
            # holds when the game closes (survives kill/crash). Atomic so a
            # crash-restart's spend seed can never read a torn file (F-02).
            usage_p = self._jsonl_path.parent / f"seat-{self.seat}.usage.json"
            tmp_p = usage_p.with_name(usage_p.name + ".tmp")
            tmp_p.write_text(json.dumps(cum, indent=1))
            os.replace(tmp_p, usage_p)
            # Shared narrative line (append-only; single-line writes are atomic
            # enough on a local fs; no seat ever reads this file). BL-21: the
            # same line goes to game.jsonl (human tail, archived at teardown)
            # and to game-<gameId>.jsonl (the per-game machine record).
            line = json.dumps({
                "ts": rec["ts"], "seat": self.seat, "deck": self.deck,
                "gameId": req.get("gameId"),
                "turn": rec["turn"], "phase": rec["phase"],
                "type": rec["type"], "seq": rec["seq"], "source": source,
                "model": self.brain.model, "effort": rec["effort"],
                "answer": answer, "why": why,
                "deviation": rec.get("deviation"),
                "latency_s": rec.get("latency_s"), "board": stamp}) + "\n"
            for gp in self._game_log_paths(req.get("gameId")):
                with gp.open("a") as f:
                    f.write(line)
        except OSError:
            pass

    def _usage_readout(self, label: str) -> None:
        t = self.brain.totals
        # Real backend dollars are never relabeled as subscription-covered
        # (plan F-35): the suffix tells the truth per transport.
        suffix = ("API-billed via backend" if self.brain.backend is not None
                  else "API-equivalent; subscription-covered")
        self._say(f"[seat {self.seat}] USAGE {label}: {t['calls']} calls, "
                  f"in={t['input_tokens']} out={t['output_tokens']} "
                  f"cache_read={t['cache_read_input_tokens']} "
                  f"cache_write={t['cache_creation_input_tokens']} "
                  f"ctx={getattr(self.brain, 'last_prompt_tokens', 0) // 1000}k "
                  f"rotations={getattr(self.brain, 'rotations', 0)} "
                  f"persistent={getattr(self.brain, 'persistent_calls', 0)}/"
                  f"{getattr(self.brain, 'persistent_fallbacks', 0)}fb "
                  f"(≈${t['cost_usd']:.2f} {suffix})")

    # ---- fastpaths --------------------------------------------------------

    def _react_signature(self, req: dict) -> tuple:
        # The memo auto-passes an identical same-turn REACT window without a
        # model call. It MUST include the state that could change the decision,
        # or it collapses two windows that look alike but aren't (a ping dropped
        # someone into counter-range, we floated mana, etc.) and eats a line the
        # brain would have taken. So: stack + options + every seat's life + our
        # own mana pool. Correctness over speed — a shifted life total re-opens
        # the window rather than fast-passing it.
        st = req.get("state", {}) or {}
        # Option A (2026-08-17): in a cascade of the seat's OWN triggers
        # (myriad tokens, Purphoros pings, Selvala's untap loop) each window
        # differs from the last only by one fewer identical trigger — the memo
        # missed all of them and the brain re-said "let my triggers resolve"
        # 10+ times per attack. When EVERY stack item is this seat's own
        # trigger, the signature keeps the SET of names (not the multiset), so
        # a shrinking cascade of the same triggers memoizes after the first
        # pass. Any opponent object or non-trigger on the stack restores the
        # exact multiset (an opponent's spell in the middle is a new decision).
        names = list(map(str, st.get("stack", [])))
        if self._all_own_triggers(req):
            stack = ("OWN-TRIGGERS", tuple(sorted(set(names))))
        else:
            stack = tuple(sorted(names))
        opts = tuple(sorted(str(o.get("label", "")).split("  ")[0]
                            for o in req.get("options", []) if o.get("id") != 0))
        # Game 25 (2026-09-07): Ben's Staff/Selvala loop changed HIS life on
        # every activation, so no two of the seats' windows matched and the
        # memo never fired (0 of 84 windows in one turn). Own life stays
        # exact; an opponent's life is exact at 10 or below (kill range) and
        # bucketed by 5 above it — replayed on games 24-25: +14 passes, 0 of
        # them a window the model had acted on.
        lives = (st.get("life"),) + tuple(self._life_bucket(o.get("life"))
                                          for o in st.get("opponents", []) or [])
        pool = st.get("manaPool")
        # Wave-2 (2026-08-28 audit finding 1): the signature was blind to
        # phase, combat and stack TARGETS — one correct pass at "beginning of
        # combat, nothing declared" fast-passed every later window that turn
        # (post-attackers, post-blocks, end step: the game-2 fog death one
        # layer up), and a same-named spell at a different target collided.
        # json digests are shape-agnostic and deterministic; memo fires
        # strictly less often, never more.
        combat = json.dumps(st.get("combat"), sort_keys=True, default=str)
        tgts = json.dumps(st.get("stackTargets"), sort_keys=True, default=str)
        return (req.get("turn"), req.get("phase"), stack, opts, lives, pool,
                combat, tgts)

    @staticmethod
    def _life_bucket(life):
        if not isinstance(life, int) or isinstance(life, bool) or life <= 10:
            return life
        return f"{life // 5 * 5}+"

    def _all_own_objects(self, req: dict) -> bool:
        """True iff the stack is non-empty and EVERY item belongs to this
        seat — any kind (triggers, spells, copies). Used ONLY by the cycle
        signature: a brain-declared loop's own engine may interleave its own
        copy-spells among its triggers (Spiritdancer/Aura Shards, game 12),
        and the count of own objects is expected loop movement. The REACT
        memo keeps the stricter trigger-only rule (_all_own_triggers) — it
        has no brain opt-in. Absent metadata -> False (fail-open)."""
        st = req.get("state") or {}
        owners = st.get("stackOwners")
        if not isinstance(owners, list) or not owners:
            return False
        return all(o == self.seat for o in owners)

    def _all_own_triggers(self, req: dict) -> bool:
        """True iff the stack is non-empty and EVERY item is a triggered
        ability controlled by this seat (needs the additive stackOwners /
        stackKinds fields; absent -> False, fail-open to full treatment)."""
        st = req.get("state") or {}
        owners = st.get("stackOwners")
        kinds = st.get("stackKinds")
        if not isinstance(owners, list) or not isinstance(kinds, list) or not owners:
            return False
        if len(owners) != len(kinds):
            return False
        return all(o == self.seat for o in owners) and all(k == "trigger" for k in kinds)

    # ---- cycle replay (brain-declared loop fast-forward) -------------------

    CYCLE_DTYPES = ("CAST_SPELL", "REACT", "CONFIRM", "PAY_UNLESS",
                    "CHOOSE_ENTITY", "CHOOSE_CARD", "CHOOSE_CARDS",
                    "CHOOSE_NUMBER")
    CYCLE_MAX_ROUNDS = 64
    CYCLE_MAX_HIST = 120

    def _cycle_signature(self, req: dict) -> tuple:
        """Decision-shape signature for loop replay. Deliberately EXCLUDES
        life totals and mana pool — a declared loop is expected to move both
        (Reservoir gain, ping drains, growing pool). Novelty still breaks
        replay through what IS included: any new/missing stack object, any
        change in the option list (a drawn card becomes castable, an
        affordability flip), a phase change, or a change in who is alive."""
        st = req.get("state", {}) or {}
        names = list(map(str, st.get("stack", [])))
        if self._all_own_objects(req):
            # own-engine collapse: a declared loop's own triggers AND its own
            # copy-spells shift in count, position, and even PRESENCE between
            # iterations (game 12 oscillated between {Shards,Spiritdancer} and
            # {Shards}-only windows) — for an OPT-IN cycle the stable identity
            # is simply "the stack is all mine". Steps are still gated by
            # decisionType + the option set, every replayed answer is
            # re-validated, and any opponent object restores the exact
            # multiset below (novelty always breaks out).
            stack = ("OWN-OBJECTS",)
        else:
            stack = tuple(sorted(names))
        opts = tuple(sorted(str(o.get("label", "")).split("  ")[0]
                            for o in req.get("options", []) if o.get("id") != 0))
        n_opp = len(st.get("opponents", []) or [])
        return (req.get("decisionType"), req.get("phase"), stack, opts, n_opp)

    @staticmethod
    def _opt_key(o: dict) -> tuple:
        """Replay identity of an option: (label, type, cost). BL-08: label
        alone let a card's costed ability rebind to its free sibling when the
        description drifted between windows."""
        return (str(o.get("label", "")), o.get("type"), o.get("cost"))

    @staticmethod
    def _cycle_shape(req: dict, answer: dict):
        """Answer -> replayable shape, or None (unsupported: never replayed).
        Shapes rebind by option identity (label, type, cost), never by id —
        ids are per-window."""
        opts = {o.get("id"): SeatRunner._opt_key(o)
                for o in req.get("options", []) or []}
        if not isinstance(answer, dict):
            return None
        if "chosenId" in answer:
            cid = answer.get("chosenId")
            if cid == 0:
                return ("id0",)
            lab = opts.get(cid)
            return ("label", lab) if lab else None
        ch = answer.get("chosen")
        if isinstance(ch, int):
            return ("number", ch)
        if isinstance(ch, list):
            labs = []
            for cid in ch:
                lab = opts.get(cid)
                if lab is None:
                    return None
                labs.append(lab)
            return ("labels", tuple(labs))
        return None

    @staticmethod
    def _cycle_rebind(shape, req: dict):
        """Shape -> concrete answer against THIS request, or None. An exact
        (label, type, cost) match wins; otherwise the label PREFIX (the card
        name) must match together with the same type and cost, and exactly
        one option may qualify — any ambiguity means no replay (BL-08)."""
        def find(key):
            lab, typ, cost = key
            opts = req.get("options", []) or []
            exact = [o for o in opts if SeatRunner._opt_key(o) == key]
            if len(exact) == 1:
                return exact[0].get("id")
            pre = lab.split("  ")[0]
            close = [o for o in opts
                     if str(o.get("label", "")).split("  ")[0] == pre
                     and o.get("type") == typ and o.get("cost") == cost]
            return close[0].get("id") if len(close) == 1 else None
        if shape == ("id0",):
            return {"chosenId": 0}
        kind = shape[0]
        if kind == "label":
            oid = find(shape[1])
            return {"chosenId": oid} if oid is not None else None
        if kind == "number":
            return {"chosen": shape[1]}
        if kind == "labels":
            ids = []
            for lab in shape[1]:
                oid = find(lab)
                if oid is None:
                    return None
                ids.append(oid)
            return {"chosen": ids}
        return None

    def _cycle_try_arm(self, req: dict, sig: tuple, out: dict) -> None:
        """Model declared repeat_cycle: N — extract the just-completed cycle
        from this turn's tape and arm the replay."""
        n = out.get("repeat_cycle")
        if not isinstance(n, int) or n < 1:
            return
        n = min(n, self.CYCLE_MAX_ROUNDS)
        if req.get("decisionType") not in self.CYCLE_DTYPES:
            self._say(f"[seat {self.seat}] repeat_cycle ignored: "
                      f"{req.get('decisionType')} is not replayable")
            return
        prev = None
        for i in range(len(self._hist) - 1, -1, -1):
            if self._hist[i][0] == sig:
                prev = i
                break
        if prev is None:
            self._say(f"[seat {self.seat}] repeat_cycle ignored: no earlier "
                      f"identical window this turn to bound the cycle")
            return
        steps = self._hist[prev:]
        if any(shape is None or dt not in self.CYCLE_DTYPES
               for (_, dt, shape) in steps):
            self._say(f"[seat {self.seat}] repeat_cycle ignored: cycle "
                      f"contains a non-replayable decision")
            return
        self.cycle = {"steps": steps, "ptr": 1 % len(steps),
                      "rounds": n - (1 if len(steps) == 1 else 0),
                      "total": n}
        self._say(f"[seat {self.seat}] CYCLE armed: {len(steps)} step(s) x {n} "
                  f"round(s) — replaying identical windows without model calls; "
                  f"ANY novelty breaks out")

    def _cycle_replay(self, req: dict, sig: tuple):
        """Return (answer, note) replayed from the armed cycle, or None
        (breaks the cycle on any mismatch)."""
        if not self.cycle:
            return None
        step_sig, dt, shape = self.cycle["steps"][self.cycle["ptr"]]
        if sig != step_sig or req.get("decisionType") != dt:
            self._say(f"[seat {self.seat}] CYCLE broken at step "
                      f"{self.cycle['ptr'] + 1}/{len(self.cycle['steps'])} "
                      f"(window changed) — model resumes")
            self.cycle = None
            return None
        answer = self._cycle_rebind(shape, req)
        if answer is None or rules.validate(req, answer) is None:
            self._say(f"[seat {self.seat}] CYCLE broken: recorded answer no "
                      f"longer binds/validates — model resumes")
            self.cycle = None
            return None
        self.cycle["ptr"] += 1
        note = (f"cycle {self.cycle['total'] - self.cycle['rounds'] + 1}"
                f"/{self.cycle['total']}")
        if self.cycle["ptr"] >= len(self.cycle["steps"]):
            self.cycle["ptr"] = 0
            self.cycle["rounds"] -= 1
            if self.cycle["rounds"] <= 0:
                self._say(f"[seat {self.seat}] CYCLE complete "
                          f"({self.cycle['total']} rounds) — model resumes")
                self.cycle = None
        return answer, note

    # ---- executable plan (four-part guard) --------------------------------

    def _plan_guard(self, req: dict, step: dict) -> int | None:
        """Guards #1-3 + the double-validate for one plan step vs the live req.
        (#1 TYPE and #4 NO-INTERACTION are checked by the caller.) Returns the
        bound option id if the step may execute locally, else None (divergence)."""
        if req.get("phase") not in ("MAIN1", "MAIN2"):          # #2a timing
            return None
        if (req.get("state") or {}).get("stack"):               # #2b empty stack
            return None
        oid = rules.bind_plan_step(step, req)                   # #3 option present
        if oid is None:
            return None
        if rules.validate(req, {"chosenId": oid}) is None:      # double guard: legal
            return None
        return oid

    @staticmethod
    def _mana_value(cost) -> int | None:
        """Total mana of an option's cost string ("{2}{U}{U}" -> 4). None when
        it cannot be known — no braces, {X}, a Phyrexian pip (payable with
        life), an unknown symbol — and the caller treats None as AFFORDABLE
        (fail open to the model). Hybrid takes its cheapest half; tap/untap/
        energy/snow symbols cost no mana."""
        if not cost:
            return None
        syms = re.findall(r"\{([^}]*)\}", str(cost))
        if not syms:
            return None
        total = 0
        for s in syms:
            s = s.strip().upper()
            if s.isdigit():
                total += int(s)
            elif s in ("W", "U", "B", "R", "G", "C"):
                total += 1
            elif "/" in s:
                parts = s.split("/")
                if "P" in parts:
                    return None
                nums = [int(p) for p in parts if p.isdigit()]
                total += min(nums) if nums else 1
            elif s in ("T", "Q", "E", "S", "CHAOS", "PW", "TK"):
                continue
            else:
                return None  # X, Y, or something new — fail open
        return total

    FREE_MARKERS = ("without paying", "convoke", "improvise", "delve", "affinity",
                    "emerge", "assist", "alternative cost", "alt cost", "pitch", "free")

    def _unaffordable_react(self, req: dict) -> str | None:
        """Affordability fastpath (2026-09-07, game 25: 99% of the seats' 338
        model-answered REACT windows were passes, ~4 s each). When EVERY
        non-pass option has a knowable mana cost strictly above
        state.manaAvailableNow (pool + one activation of each untapped source,
        the engine's own figure) and none is a free/alt-cost play, the window
        cannot be acted on — pass without a model call. The 2026-08-13 lesson
        (the 325th "dead" window was a real free/convoke/sac play) is honoured
        by construction: a zero or unknowable cost, a free-cast marker in the
        label, or a missing mana figure all fall through to the model."""
        if req.get("decisionType") != "REACT":
            return None
        st = req.get("state") or {}
        avail = st.get("manaAvailableNow")
        if not isinstance(avail, int) or isinstance(avail, bool):
            return None
        non_pass = [o for o in req.get("options", []) if o.get("id") != 0]
        if not non_pass:
            return None
        # Two more dead shapes, measured on game 25's 374 model-answered REACT
        # windows (0 false positives): every option is a plain mana ability
        # (mana with nothing to spend it on floats away), or the stack is empty
        # and every option is a counterspell (nothing to counter). Mana
        # abilities with a sacrifice/discard cost are NOT plain (Lion's Eye
        # Diamond class) and go to the model.
        stack_empty = not (st.get("stack") or [])
        # Gemini review 2026-09-07 (P1): a mana ability IS the response when our
        # source is targeted (Rishadan Port on a land, Beast Within on a Lotus:
        # float the mana first). Any opponent item aimed at us keeps the window.
        threatened = self._threatens_own(req)
        if not threatened and all(self._plain_mana_ability(o) for o in non_pass):
            return "only mana abilities offered, nothing to spend the mana on"
        if stack_empty and all(self._counterspell(o) for o in non_pass):
            return "only counterspells offered and the stack is empty"
        if stack_empty and all(self._plain_mana_ability(o) or self._counterspell(o) for o in non_pass):
            return "only mana abilities and counterspells offered with an empty stack"
        # Game 25: a non-empty stack of ABILITIES (Staff of Domination, Selvala)
        # is no target for a counterspell or a spell-copier either. Needs the
        # engine's stackKinds; absent or malformed -> fall through to the model.
        kinds = st.get("stackKinds")
        if (not stack_empty and not threatened and isinstance(kinds, list) and len(kinds) == len(st.get("stack") or [])
                and kinds and "spell" not in kinds
                and all(self._spell_reactor(o) or self._plain_mana_ability(o) for o in non_pass)):
            return "only counter/copy-spell options and no spell on the stack (abilities only)"
        cheapest = None
        for o in non_pass:
            label = str(o.get("label", "")).lower()
            if any(m in label for m in self.FREE_MARKERS):
                return None
            mv = self._mana_value(o.get("cost"))
            if mv is None or mv <= avail:
                return None
            cheapest = mv if cheapest is None else min(cheapest, mv)
        return (f"nothing affordable: cheapest option costs {cheapest}, "
                f"{avail} mana available now")

    @staticmethod
    def _plain_mana_ability(o: dict) -> bool:
        lab = str(o.get("label", ""))
        low = lab.lower()
        # the label is "<name>  <cost> — <text>": judge the COST part for
        # sacrifice/discard/exile (Chrome Mox's text says "exiled card" and is
        # still a plain mana ability)
        cost_part = low.split(" — ", 1)[0] if " — " in low else str(o.get("cost", "")).lower()
        if any(w in cost_part for w in ("sacrifice", "sac<", "discard", "exile")):
            return False
        adds = ("add {" in low or "add one mana" in low or "add x mana" in low or "add an amount of mana" in low
                or "mana of any" in low or re.search(r"\badd [a-z]* ?mana", low) is not None)
        taps = "{t}" in low or "tap an untapped" in low
        return bool(adds and taps)

    @staticmethod
    def _counterspell(o: dict) -> bool:
        low = str(o.get("label", "")).lower()
        return "counter target" in low

    @staticmethod
    def _spell_reactor(o: dict) -> bool:
        """An option that only does something to a SPELL on the stack: counter
        target spell, copy target instant/sorcery (Flare of Duplication class).
        Game 25: Purphoros was asked 103 times about Flare while Ben's Staff
        and Selvala ABILITIES cycled on the stack; 45 of those windows held
        nothing but abilities."""
        low = str(o.get("label", "")).lower()
        text = low.split(" — ", 1)[1] if " — " in low else low
        # Gemini review 2026-09-07 (P0): Stifle / Disallow / Tale's End counter
        # ABILITIES — an all-abilities stack is exactly their target. Not dead.
        if "ability" in text or "activated" in text or "triggered" in text:
            return False
        return ("counter target" in text
                or ("copy target" in text and ("instant" in text or "sorcery" in text or "spell" in text)))

    @staticmethod
    def _tap_only_utility(o: dict) -> bool:
        """A {T}/{Q}-only activated ability with no mana, no sacrifice/discard/
        exile/life in its cost and no target/counter/prevent in its text (The
        One Ring's draw, Sensei's Top's look). Nothing here can answer a
        stack item; it is a card-flow choice the model has already made
        once this turn when the repeat rule applies."""
        low = str(o.get("label", ""))
        low = low.lower()
        if " — " not in low:
            return False
        cost_part, text = low.split(" — ", 1)
        syms = re.findall(r"\{([^}]*)\}", cost_part)
        if not syms or any(s.strip().upper() not in ("T", "Q") for s in syms):
            return False
        if any(w in cost_part for w in ("sacrifice", "discard", "exile", "pay", "remove")):
            return False
        # "target" also covers "counter target"; a plain "counter" would reject
        # The One Ring's own "burden counter" text (the very card this is for)
        return not any(w in text for w in ("target", "prevent"))

    def _repeat_tap_pass(self, req: dict) -> str | None:
        """Repeat rule (Ben, 2026-09-07: cut the repeat offers, not the first
        one). A REACT window where the seat has NO mana (pool 0, untapped 0),
        the stack is non-empty, nothing on it threatens this seat, and every
        option is a tap-only utility, is passed without a model call when the
        MODEL already passed the same option set this turn and the seat's own
        life has not dropped since. The first such window always goes to the
        model; a life drop re-opens it (Giada's desperation One Ring draw at
        19 life vs 20 incoming, game 25 seq 202-class, stays live). Replayed on
        game 25: 62 fewer model calls for Giada, 0 of them a window the model
        had acted on."""
        if req.get("decisionType") != "REACT" or not self._tap_pass:
            return None
        st = req.get("state") or {}
        if not st.get("stack") or not self._resourceless_react(req) or self._threatens_own(req):
            return None
        # Gemini review 2026-09-07 (P1): a SPELL on the stack is a new question
        # (dig with the Ring in response to Peer into the Abyss) — abilities only.
        kinds = st.get("stackKinds")
        if not isinstance(kinds, list) or len(kinds) != len(st.get("stack") or []) or any(k == "spell" or k == "?" for k in kinds):
            return None
        non_pass = [o for o in req.get("options", []) if o.get("id") != 0]
        if not non_pass or not all(self._tap_only_utility(o) for o in non_pass):
            return None
        turn, optset, life = self._tap_pass
        if turn != req.get("turn") or optset != self._option_set(req):
            return None
        own = st.get("life")
        if not isinstance(own, int) or own < life:
            return None
        return "repeat: same tap-only options already passed this turn, no mana, life not down"

    @staticmethod
    def _option_set(req: dict) -> tuple:
        return tuple(sorted(str(o.get("label", "")).split("  ")[0]
                            for o in req.get("options", []) if o.get("id") != 0))

    def _unthreatened_ability_react(self, req: dict) -> bool:
        """REACT with a non-empty stack of OTHER players' abilities/triggers
        only (stackKinds/stackOwners present and aligned, no spell, none ours)
        and nothing aimed at this seat (state.stackTargets). Off with
        ARENA_REACT_LOW_EFFORT=off."""
        if os.environ.get("ARENA_REACT_LOW_EFFORT", "on").lower() == "off":
            return False
        st = req.get("state") or {}
        names = st.get("stack") or []
        kinds = st.get("stackKinds")
        owners = st.get("stackOwners")
        if (not names or not isinstance(kinds, list) or not isinstance(owners, list)
                or len(kinds) != len(names) or len(owners) != len(names)):
            return False
        if any(k not in ("ability", "trigger") for k in kinds):
            return False
        if any(o == self.seat for o in owners):
            return False
        # Gemini pass 2 (P1): a non-targeting ability can still end the game
        # (Thassa's Oracle, Felidar Sovereign, extra-turn loops). If any stack
        # item's oracle text says so, this is a full-effort question.
        for otext in st.get("stackOracle") or []:
            low = str(otext).lower()
            if any(w in low for w in self.GAME_DECIDING):
                return False
        return not self._threatens_own(req)

    GAME_DECIDING = ("win the game", "wins the game", "lose the game", "loses the game",
                     "extra turn", "each opponent loses", "you win", "you lose")

    def _yield_key(self, req: dict) -> tuple | None:
        """(turn, top name, top owner, top kind, option set) when the stack is
        non-empty, the kinds/owners metadata is present and aligned, and NO
        item on the stack is a spell (abilities and triggers loop; a spell is
        a one-off decision — game 25 seq 202: Purphoros copied a Genesis Wave
        with a Hydra trigger on top of it). None otherwise."""
        st = req.get("state") or {}
        names = st.get("stack") or []
        kinds = st.get("stackKinds")
        owners = st.get("stackOwners")
        if (not names or not isinstance(kinds, list) or not isinstance(owners, list)
                or len(kinds) != len(names) or len(owners) != len(names)):
            return None
        if any(k == "spell" or k == "?" for k in kinds):
            return None
        # the turn is part of the key (the dict is also cleared per turn; the
        # key makes a stale entry harmless if the clear ever moves)
        return (req.get("turn"), str(names[0]), owners[0], kinds[0], self._option_set(req))

    def _auto_yield(self, req: dict) -> str | None:
        """Auto-yield rule (Ben, 2026-09-07: cut the repeat offers). Forge's
        GUI lets a human yield to an ability for the turn; the seat gets the
        same: once the MODEL has passed with ability/trigger X on top of an
        all-abilities stack, later windows this turn with X on top of an
        all-abilities stack and the same options are passed without a call —
        unless the seat's life dropped, it has MORE mana than when it yielded
        (a new possibility), or an opponent item aims at it. The first offer
        of every X always reaches the model. Replayed on game 25 with the
        strictest approximation (Staff/Selvala only): 27 calls cut, 0 wrong."""
        if req.get("decisionType") != "REACT" or not self._yielded:
            return None
        key = self._yield_key(req)
        if key is None or key not in self._yielded:
            return None
        if self._threatens_own(req):
            return None
        st = req.get("state") or {}
        life, pool, untapped = self._yielded[key]
        own = st.get("life")
        if not isinstance(own, int) or own < life:
            return None
        if (st.get("manaPool") or 0) > pool or (st.get("untappedManaSourceCount") or 0) > untapped:
            return None
        return f"auto-yield: already passed with {key[1]} on top this turn (no spell on the stack, life not down, no new mana)"

    def _note_yield(self, req: dict, answer: dict) -> None:
        """Remember a MODEL pass on an all-abilities stack (never a punt)."""
        if req.get("decisionType") != "REACT" or answer != {"chosenId": 0}:
            return
        key = self._yield_key(req)
        st = req.get("state") or {}
        if key is not None and isinstance(st.get("life"), int):
            if self._yielded is None:
                self._yielded = {}
            self._yielded[key] = (st.get("life"), st.get("manaPool") or 0,
                                  st.get("untappedManaSourceCount") or 0)
            self._publish_yields()

    def _publish_yields(self) -> None:
        """Step 3 (engine-side mirror): write this turn's yields to
        mailbox/seat-N/yield.json so MailboxController can skip opening a
        window the runner would yield anyway (same key, same guards, one
        layer lower). Atomic; a failure only costs the mirror."""
        try:
            base = Path(getattr(self.mb, "dir", None) or (Path(self.mb.inbox).parent))
            base.mkdir(parents=True, exist_ok=True)
            items = []
            for (turn, name, owner, kind, optset), (life, pool, untapped) in (self._yielded or {}).items():
                items.append({"turn": turn, "name": name, "owner": owner, "kind": kind,
                              "options": list(optset), "life": life, "pool": pool, "untapped": untapped})
            tmp = base / "yield.json.tmp"
            tmp.write_text(json.dumps({"seat": self.seat, "items": items}))
            os.replace(tmp, base / "yield.json")
        except (OSError, TypeError, AttributeError):
            pass

    def _note_tap_pass(self, req: dict, answer: dict) -> None:
        """Remember a MODEL pass of a repeat-eligible window (never a punt)."""
        if req.get("decisionType") != "REACT" or answer != {"chosenId": 0}:
            return
        st = req.get("state") or {}
        non_pass = [o for o in req.get("options", []) if o.get("id") != 0]
        if (non_pass and st.get("stack") and self._resourceless_react(req)
                and all(self._tap_only_utility(o) for o in non_pass)
                and isinstance(st.get("life"), int)):
            self._tap_pass = (req.get("turn"), self._option_set(req), st.get("life"))

    @staticmethod
    def _resourceless_react(req: dict) -> bool:
        """Strictly-measured dead-window class (2026-08-13 study): REACT
        with pool AND untapped sources BOTH present and BOTH zero. The brain
        passed 324/325 of these historically — but the 325th was a real play
        (free/convoke/sac-cost class), so these windows are never SKIPPED,
        only routed to effort=low: full authority, faster verdicts. Absent
        fields disqualify (fail-open to normal effort)."""
        if req.get("decisionType") != "REACT":
            return False
        st = req.get("state") or {}
        untapped = st.get("untappedManaSourceCount",
                          st.get("untappedManaSources"))
        return st.get("manaPool") == 0 and untapped == 0

    @staticmethod
    def _stack_names(req: dict) -> list[str]:
        return [str(x) for x in (req.get("state", {}) or {}).get("stack", [])]

    def _threatens_own(self, req: dict) -> bool:
        """True iff any OPPONENT stack item's announced targets
        (state.stackTargets) point at this seat or its battlefield — the
        protect-window shape the autopass allowlist must never eat.
        Wave-3 (adversarial review F7/F9): divided-damage labels carry a
        trailing " [n]" that must be stripped before matching, and the
        seat's OWN items (pump on own attacker) are not threats."""
        st = req.get("state", {}) or {}
        groups = st.get("stackTargets") or []
        if not groups:
            return False
        owners = st.get("stackOwners") or []
        me = f"seat {self.seat}"
        own_ids = {f"({c.get('id')})" for c in (st.get("battlefield") or [])
                   if isinstance(c, dict) and c.get("id") is not None}
        for i, grp in enumerate(groups):
            if i < len(owners) and owners[i] == self.seat:
                continue  # own spell aiming own stuff is a plan, not a threat
            for raw in (grp or []):
                t = str(raw).split(" [")[0]  # strip divided-amount suffix
                if t == me or any(t.endswith(oid) for oid in own_ids):
                    return True
        return False

    @staticmethod
    def _order_key(req: dict) -> tuple | None:
        """Identity of a TRIGGER_ORDER window: the sorted group labels."""
        st = req.get("state", {}) or {}
        if req.get("decisionType") != "CHOOSE_MODE" or st.get("purpose") != "TRIGGER_ORDER":
            return None
        return tuple(sorted(str(o.get("label", "")) for o in req.get("options", []) or []))

    def _order_replay(self, req: dict) -> dict | None:
        """Rebind a remembered resolution order (labels) to this window's indices."""
        key = self._order_key(req)
        labels = self.order_memo.get(key) if key is not None else None
        if not labels:
            return None
        by_label = {str(o.get("label", "")): o.get("id") for o in req.get("options", []) or []}
        try:
            ids = [by_label[lab] for lab in labels]
        except KeyError:
            return None
        return {"chosen": ids}

    def _order_remember(self, req: dict, answer: dict) -> None:
        key = self._order_key(req)
        if key is None or not isinstance(answer, dict):
            return
        by_id = {o.get("id"): str(o.get("label", "")) for o in req.get("options", []) or []}
        try:
            self.order_memo[key] = [by_id[i] for i in answer.get("chosen", [])]
        except (KeyError, TypeError):
            pass

    def _fastpath(self, req: dict) -> tuple[dict, str] | None:
        if req.get("decisionType") == "CHOOSE_MODE":
            replay = self._order_replay(req)
            if replay is not None and rules.validate(req, replay) is not None:
                return replay, "memo"
            return None
        if req.get("decisionType") != "REACT":
            return None
        non_pass = [o for o in req.get("options", []) if o.get("id") != 0]
        if non_pass and all(any(str(o.get("label", "")).startswith(p)
                                for p in self.autopass) for o in non_pass):
            # Wave-2 (audit finding 5, restoring note 12's dropped clause): the
            # ONE window where a Mother-of-Runes-class option is the right play
            # is an opponent object aimed at OUR stuff — never autopass those.
            # state.stackTargets (note 51) names every stack item's targets.
            if not self._threatens_own(req):
                return {"chosenId": 0}, "autopass"
        why = self._unaffordable_react(req)
        if why is not None:
            self._fast_why = why
            return {"chosenId": 0}, "affordability"
        if self._react_signature(req) in self.react_seen:
            return {"chosenId": 0}, "memo"
        why = self._repeat_tap_pass(req)
        if why is not None:
            self._fast_why = why
            return {"chosenId": 0}, "repeat"
        why = self._auto_yield(req)
        if why is not None:
            self._fast_why = why
            return {"chosenId": 0}, "yield"
        # #2 reactive hold: brain armed a same-turn hold; auto-pass only when the
        # stack is non-empty AND every object was already shown-and-passed this
        # turn. A new object or an empty-stack (tactical) window escalates.
        if (self.react_hold and self.hold
                and self.hold.get("turn") == req.get("turn")):
            names = self._stack_names(req)
            if names and all(n in self.hold["seen"] for n in names):
                return {"chosenId": 0}, "hold"
        return None

    # ---- the loop ------------------------------------------------------------

    # poll_s 0.5->0.15 (2026-08-13 pace study: median non-model overhead was
    # 0.72s/decision across 4.4K decisions; inbox-poll quantization was its
    # largest slice. stat() at ~7Hz is free; the engine's own resp poll is 75ms.)
    def run(self, poll_s: float = 0.15) -> None:
        swept = self.mb.sweep_outbox()
        self._say(f"[seat {self.seat}] runner up — deck={self.deck} "
                  f"model={self.brain.model} timeout={self.timeout_s}s"
                  + (f" (swept {swept} stale)" if swept else ""))
        self.mb.start_heartbeat_thread()  # item 12: "somebody is home", every 5s,
                                          # beating through the pre-warm below too
        self.brain.ensure_session()  # pre-warm: dossier loads before turn 0
        while True:
            self._apply_control()
            req = self.mb.pending_request()
            if req is None:
                time.sleep(poll_s)
                continue
            self.handle(req)

    def _maybe_rotate(self, hard: bool = False) -> bool:
        """Layer two (Ben, 2026-09-07): when the last call re-read more than
        ARENA_ROTATE_TOKENS, start a fresh session with the same dossier plus
        the machine-built game record (seatd/record.py). Runs at a turn
        boundary, or mid-turn past ARENA_ROTATE_HARD (hard=True). A failed
        rotation keeps the old session."""
        size = getattr(self.brain, "last_prompt_tokens", 0)
        cap = self.rotate_hard if hard else self.rotate_at
        if (not cap or not isinstance(size, int) or size < cap
                or not getattr(self.brain, "session_id", None)):
            return False
        if hard:
            self._say(f"[seat {self.seat}] context {size // 1000}k past the hard ceiling "
                      f"{cap // 1000}k — rotating mid-turn")
        try:
            from . import record as _record
            text = _record.render(self._game_log, self._jsonl_path, self.seat, game_id=self._game_id)
        except Exception as e:  # noqa: BLE001 — a record failure must not stop the game
            self._say(f"[seat {self.seat}] game record failed ({e}) — rotation skipped")
            return False
        # bounded well inside one engine window (0.8 x timeout): a slow init
        # keeps the old session rather than costing the turn's first decision
        ok = self.brain.rotate(text, timeout_s=min(45.0, 0.5 * self.timeout_s))
        if ok:
            self._transport_event("rotate", self._game_id)
        return ok

    def handle(self, req: dict) -> None:
        """Item 13a: nothing raised inside a decision may kill the runner — a
        crash restarts it 2 s later with a fresh session and a full dossier
        re-send, and the game memory is gone. Log the traceback, answer the
        safe default on time, carry on."""
        try:
            self._handle_inner(req)
        except Exception:  # noqa: BLE001 — surviving anything is the point
            import traceback
            self._say(f"[seat {self.seat}] seq={req.get('seq')} INTERNAL ERROR in "
                      f"handle() — answering the safe default:\n{traceback.format_exc()}")
            # BL-20 hardening: an internal error leaves a hole in the cycle
            # tape; never let a loop arm across it.
            self.cycle = None
            self._hist.clear()
            try:
                answer = rules.safe_default(req)
                ok = self.mb.respond(req, answer)
                self._transport_event("punt", req.get("gameId"))
                self._record(req, answer, "punt", why="punt: runner exception", consumed=ok)
            except Exception:  # noqa: BLE001
                pass

    def _handle_inner(self, req: dict) -> None:
        if self.mb.game_reset:
            self._usage_readout("game close")  # final readout for the ended game
            self._say(f"[seat {self.seat}] NEW GAME detected "
                      f"({self.mb.prev_game_id or 'unstamped'} -> {self.mb.game_id or 'unstamped'}; "
                      f"swept {self.mb.swept_on_reset} stale resp) — session + memory reset")
            self.mb.game_reset = False
            self.brain.reset()
            self.plan = None
            self.hold = None
            self.react_seen.clear()
            self.order_memo.clear()
            self.cycle = None
            self._hist = []
            self._tap_pass = None
            self._yielded = {}
            self._publish_yields()
        if req.get("gameId"):
            self._game_id = req.get("gameId")
        new_turn = self._last_turn != req.get("turn")
        if not new_turn and self.rotate_hard \
                and isinstance(getattr(self.brain, "last_prompt_tokens", 0), int) \
                and getattr(self.brain, "last_prompt_tokens", 0) >= self.rotate_hard:
            self._maybe_rotate(hard=True)   # mid-turn, past the hard ceiling
        if new_turn:
            self._last_turn = req.get("turn")
            self._maybe_rotate()   # turn boundary: the preferred moment
            self.react_seen.clear()
            self.order_memo.clear()
            self._tap_pass = None
            self._yielded = {}
            self._publish_yields()
            self.hold = None  # hold posture is single-turn
            self.turn_intent = None
            self.cycle = None   # loops never survive a turn boundary
            self._hist = []

        seq, dtype = req.get("seq"), req.get("decisionType")
        # Item 12: the engine publishes its wait on every request. It is the
        # one timeout knob; budget from what the engine will actually do
        # rather than from a copy passed through the environment.
        eng_t = req.get("timeoutSec")
        if isinstance(eng_t, (int, float)) and eng_t > 0 and float(eng_t) != self.timeout_s:
            self._say(f"[seat {self.seat}] engine timeout is {eng_t:.0f}s "
                      f"(runner had {self.timeout_s:.0f}s) — budgeting from the engine's value")
            self.timeout_s = float(eng_t)
            self.mb.timeout_s = float(eng_t)
        if not req.get("gameId") and not getattr(self, "_unstamped_warned", False):
            self._unstamped_warned = True
            self._say(f"[seat {self.seat}] engine requests carry no gameId (pre-item-8 "
                      f"engine) — falling back to the seq heuristic for new-game detection")
        # Item 3: a deviation belongs to the model call that reported it. It
        # used to persist across fastpath/plan/cycle/punt records (no model
        # call) and get stamped onto every one of them.
        self._deviation = None

        # Guard #4: any opponent instant-speed action during our own turn shows
        # up as a REACT req — it invalidates the executable plan wholesale (the
        # remainder is strategically stale). Checked BEFORE fastpath so even an
        # autopassed react still kills the plan.
        if self.plan and dtype == "REACT" and self.plan.get("turn") == req.get("turn"):
            self._say(f"[seat {self.seat}] plan invalidated (opponent interaction)")
            self.plan = None

        # Cycle replay: an armed brain-declared loop answers matching
        # windows instantly; ANY mismatch falls through to the normal path.
        cyc_sig = (self._cycle_signature(req)
                   if (self.cycle or req.get("decisionType") in self.CYCLE_DTYPES)
                   else None)
        if self.cycle and cyc_sig is not None:
            replayed = self._cycle_replay(req, cyc_sig)
            if replayed is not None:
                answer, note = replayed
                ok = self.mb.respond(req, answer)
                self._say(f"[seat {self.seat}] seq={seq} {dtype} -> "
                          f"{json.dumps(answer)} [{note}]"
                          f"{'' if ok else ' WINDOW LOST'}")
                self._record(req, answer, "cycle", why=note, consumed=ok)
                self._hist.append((cyc_sig, dtype, self._cycle_shape(req, answer)))
                del self._hist[:-self.CYCLE_MAX_HIST]
                return

        fast = self._fastpath(req)
        if fast:
            answer, source = fast
            why = ("all options on the no-op allowlist" if source == "autopass"
                   else getattr(self, "_fast_why", "") if source in ("affordability", "repeat", "yield")
                   else "identical window already passed this turn")
            ok = self.mb.respond(req, answer)
            self._say(f"[seat {self.seat}] seq={seq} {dtype} -> {json.dumps(answer)} "
                      f"[{source}]{'' if ok else ' WINDOW LOST'}")
            self._record(req, answer, source, why=why, consumed=ok)
            if cyc_sig is not None:
                self._hist.append((cyc_sig, dtype, self._cycle_shape(req, answer)))
                del self._hist[:-self.CYCLE_MAX_HIST]
            return

        # Guards #1-3: consume an executable plan step for a CAST_SPELL window,
        # locally, no model call. Any failed consumption is a divergence -> drop
        # the whole plan and fall through to the model for this req.
        if (self.speculative and self.plan and dtype == "CAST_SPELL"
                and self.plan.get("turn") == req.get("turn")
                and self.plan["idx"] < len(self.plan["steps"])):
            step = self.plan["steps"][self.plan["idx"]]
            oid = self._plan_guard(req, step)
            if oid is not None:
                answer = {"chosenId": oid}
                self.plan["idx"] += 1
                ok = self.mb.respond(req, answer)
                self._say(f"[seat {self.seat}] seq={seq} {dtype} -> "
                          f"{json.dumps(answer)} [plan {self.plan['idx']}/"
                          f"{len(self.plan['steps'])}: {step.get('card')}]"
                          f"{'' if ok else ' WINDOW LOST'}")
                self._record(req, answer, "plan",
                             why=step.get("why"), consumed=ok)
                if cyc_sig is not None:
                    self._hist.append((cyc_sig, dtype, self._cycle_shape(req, answer)))
                    del self._hist[:-self.CYCLE_MAX_HIST]
                return
            self._say(f"[seat {self.seat}] plan invalidated (divergence at seq {seq})")
            self.plan = None

        # Deadline: answer must land before the engine gives up on us.
        vanished = False
        try:
            mtime = (self.mb.inbox / f"req-{seq}.json").stat().st_mtime
        except OSError:
            # BL-28: on a real mailbox a missing request file means the
            # engine already timed out or died — punt now, never invent a
            # fresh window. A fake mailbox with no inbox (tests) keeps one.
            vanished = self.mb.inbox.is_dir()
            mtime = time.time()
        deadline = mtime + 0.8 * self.timeout_s
        budget = 0.0 if vanished else deadline - time.time()
        answer, source, meta, why = None, "punt", None, None
        if budget > 5.0:
            # Advisory: remaining planned cards (if a plan survives) fed as text.
            plan_text = None
            if self.plan and self.plan.get("turn") == req.get("turn"):
                rem = [s.get("card") for s in self.plan["steps"][self.plan["idx"]:]]
                if rem:
                    plan_text = "remaining planned casts: " + ", ".join(rem)
            elif self.turn_intent:
                plan_text = self.turn_intent
            prompt = rules.build_user_prompt(
                req, plan=plan_text, observer=self.mb.read_observer(),
                speculative=self.speculative, react_hold=self.react_hold,
                combo_status=rules.combo_status_line(self.combos, req))
            # Item 2: the brain gets the DEADLINE, not a duration — init and
            # the decision call each spend only what remains of it (the old
            # min(budget, 240) handed the same budget to both, so a lazy
            # re-init could block the seat for 2x the window).
            # Option B (2026-08-17): a REACT where every stack item is the
            # seat's OWN trigger (measured 7+/game at 8-16s each, never once a
            # real play) thinks at effort low — full authority retained, never
            # skipped, so a trick in response to your own trigger stays live.
            fast_eff = None
            if self.brain.effort != "low":
                if self._resourceless_react(req):
                    fast_eff = "low"
                    self._say(f"[seat {self.seat}] resourceless REACT -> "
                              f"effort low for this window")
                elif dtype == "REACT" and self._all_own_triggers(req):
                    fast_eff = "low"
                    self._say(f"[seat {self.seat}] own-trigger REACT -> "
                              f"effort low for this window")
                elif dtype == "REACT" and self._unthreatened_ability_react(req):
                    # Step 2 (Ben, 2026-09-07): other players' ABILITIES on the
                    # stack, no spell, nothing aimed at us — a short question.
                    # Full authority, light thinking. ARENA_REACT_LOW_EFFORT=off
                    # disables.
                    fast_eff = "low"
                    self._say(f"[seat {self.seat}] unthreatened ability REACT -> "
                              f"effort low for this window")
                elif (dtype == "CONFIRM"
                        and (req.get("state") or {}).get("confirmMode") == "TRIGGER"
                        and str((req.get("state") or {}).get("yesCost", "none"))
                            .lower() in ("none", "", "0", "{0}")):
                    # your own free "you may" trigger (Scepter copy-cast class):
                    # full authority, light thinking
                    fast_eff = "low"
                    self._say(f"[seat {self.seat}] free own-trigger CONFIRM -> "
                              f"effort low for this window")
            out, meta = self.brain.decide(prompt, deadline=deadline,
                                          effort=fast_eff)
            if isinstance(meta, dict):
                meta["effort"] = fast_eff or self.brain.effort   # the effort actually used (game 26 visibility gap)
            clean = rules.validate(req, out) if out is not None else None
            if isinstance(out, dict) and isinstance(out.get("why"), str):
                why = out["why"][:200]
            # Capture stated intent (normal mode) and surface deviations
            # LOUDLY: a plan the brain wanted but could not execute is the
            # single most useful line in a play-quality review.
            if isinstance(out, dict):
                tp = out.get("turn_plan")
                if (isinstance(tp, str) and tp.strip()
                        and req.get("phase") in ("MAIN1", "MAIN2")):
                    self.turn_intent = tp.strip()[:600]
                dev = out.get("deviation")
                if isinstance(dev, dict) and (dev.get("wanted") or dev.get("blocked_by")):
                    self._deviation = {"wanted": str(dev.get("wanted", ""))[:200],
                                       "blocked_by": str(dev.get("blocked_by", ""))[:200]}
                    self._say(f"[seat {self.seat}] DEVIATION t{req.get('turn')} "
                              f"{req.get('phase','')}: wanted \"{self._deviation['wanted']}\" "
                              f"— blocked by: {self._deviation['blocked_by']}")
                else:
                    self._deviation = None
            else:
                self._deviation = None
            if clean is not None:
                answer, source = clean, "model"
                # Install an executable plan from the model's first own-turn main
                # decision (once per turn). Steps name cards; consumed under guard.
                if (self.speculative and self.plan is None
                        and isinstance(out, dict) and dtype == "CAST_SPELL"
                        and req.get("phase") in ("MAIN1", "MAIN2")):
                    steps = [s for s in (out.get("plan") or [])
                             if isinstance(s, dict) and s.get("card")]
                    if steps:
                        self.plan = {"turn": req.get("turn"),
                                     "steps": steps[:12], "idx": 0}
                        self._say(f"[seat {self.seat}] plan installed: "
                                  + ", ".join(s["card"] for s in self.plan["steps"]))
                # Cycle replay arming: the brain declared it just completed an
                # iteration of a loop it wants fast-forwarded.
                if isinstance(out, dict) and out.get("repeat_cycle") is not None \
                        and cyc_sig is not None:
                    self._cycle_try_arm(req, cyc_sig, out)
                # #2 hold posture: arm/refresh on a REACT-pass with hold_turn set;
                # any non-pass react (the seat is interacting) clears it.
                if self.react_hold and dtype == "REACT":
                    if answer == {"chosenId": 0} and isinstance(out, dict) \
                            and out.get("hold_turn") is True:
                        if not self.hold or self.hold.get("turn") != req.get("turn"):
                            self.hold = {"turn": req.get("turn"), "seen": set()}
                        self.hold["seen"].update(self._stack_names(req))
                    elif answer != {"chosenId": 0}:
                        self.hold = None
            elif out is not None:
                self._say(f"[seat {self.seat}] seq={seq} INVALID model answer "
                          f"{str(meta.get('raw'))[:120]!r} -> safe default")
                why = f"punt: invalid model answer ({(why or '-')[:80]})"
            else:
                why = "punt: model failure/timeout"
        elif vanished:
            self._say(f"[seat {self.seat}] seq={seq} request file vanished "
                      f"(engine moved on) -> safe default without model call")
            why = "punt: request file vanished"
        else:
            self._say(f"[seat {self.seat}] seq={seq} only {budget:.0f}s left "
                      f"-> safe default without model call")
            why = "punt: deadline nearly expired"
        if answer is None:
            answer = rules.safe_default(req)
        if source == "punt":
            self._transport_event("punt", req.get("gameId"))
        wedges = getattr(self.brain, "wedges", 0)
        if wedges > getattr(self, "_wedges_seen", 0):
            self._wedges_seen = wedges
            self._transport_event("wedge", req.get("gameId"))

        # Item 3: only a REAL model pass feeds the same-turn memo. A punt
        # (timeout / wedge / invalid / short budget) also answers {"chosenId":0}
        # but the brain never saw the window — memoizing it auto-passed every
        # identical window for the rest of the turn under a "why" that claimed
        # otherwise, and hid the punts from the ratings void counter.
        if source == "model" and dtype == "REACT" and answer == {"chosenId": 0}:
            self.react_seen.add(self._react_signature(req))
            self._note_tap_pass(req, answer)
            self._note_yield(req, answer)
        elif source == "model" and dtype == "REACT":
            self._tap_pass = None  # the seat acted: the next repeat is a fresh question
            self._yielded = {}
        if source == "model" and dtype == "CHOOSE_MODE":
            self._order_remember(req, answer)

        ok = self.mb.respond(req, answer)
        lat = f" {meta['latency_s']}s" if meta and meta.get("latency_s") else ""
        self._say(f"[seat {self.seat}] seq={seq} {dtype} turn={req.get('turn')} "
                  f"{req.get('phase', '')} -> {json.dumps(answer)} [{source}{lat}]"
                  f"{('  # ' + why) if why else ''}"
                  f"{'' if ok else ' WINDOW LOST'}")
        self._record(req, answer, source, meta, why=why, consumed=ok)
        if cyc_sig is not None:
            # BL-20: a punt is never a replayable step. Recording it with an
            # unreplayable shape makes repeat_cycle refuse to arm across it
            # (the existing "non-replayable decision" check), so a punted
            # decline can never be replayed 64 times as source "cycle".
            shape = None if source == "punt" else self._cycle_shape(req, answer)
            self._hist.append((cyc_sig, dtype, shape))
            del self._hist[:-self.CYCLE_MAX_HIST]
