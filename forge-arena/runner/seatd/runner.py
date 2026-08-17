"""The seat loop: mailbox -> (fastpath | brain) -> validate -> respond.

Wiring rules (from docs/AGENT-SDK-SEATS.md):
- ZERO-API fastpaths run before any model call:
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
import os
import time
from pathlib import Path

from . import backends, rules
from .brain import SeatBrain
from .protocol import SeatMailbox

DEFAULT_AUTOPASS = ("Giver of Runes", "Mother of Runes", "Academy Ruins")


class SeatRunner:
    def __init__(self, seat: int, deck: str, base, model: str = "sonnet",
                 effort: str = "low", timeout_s: float = 90.0, log_dir=None,
                 autopass: tuple[str, ...] = DEFAULT_AUTOPASS,
                 speculative: bool = False, react_hold: bool = False):
        self.mb = SeatMailbox(seat, base, timeout_s=timeout_s)
        self.brain = SeatBrain(seat, deck, model=model, effort=effort,
                               log=self._say)
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
        # Deck combos (CommanderSpellbook included-combos distillation) for the
        # per-decision COMBO STATUS line. Ship-pattern source: dossier/combos.json
        # only — no project-internal combo-program/advisory artifacts.
        self.combos: list = []
        try:
            combos_p = (Path(__file__).parents[2] / "decks" / deck
                        / "dossier" / "combos.json")
            if combos_p.exists():
                self.combos = (json.loads(combos_p.read_text()).get("combos")
                               or [])
        except (OSError, json.JSONDecodeError):
            self.combos = []
        self.react_seen: set[tuple] = set()
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

    def _record(self, req: dict, answer: dict, source: str, meta=None,
                why: str | None = None, consumed: bool = True) -> None:
        stamp = self.board_stamp(req)
        rec = {"ts": time.time(), "seat": self.seat, "seq": req.get("seq"),
               "turn": req.get("turn"), "phase": req.get("phase"),
               "type": req.get("decisionType"), "source": source,
               "model": self.brain.model, "effort": self.brain.effort,
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
            # enough on a local fs; no seat ever reads this file).
            with self._game_log.open("a") as f:
                f.write(json.dumps({
                    "ts": rec["ts"], "seat": self.seat, "deck": self.deck,
                    "turn": rec["turn"], "phase": rec["phase"],
                    "type": rec["type"], "seq": rec["seq"], "source": source,
                    "model": self.brain.model, "effort": self.brain.effort,
                    "answer": answer, "why": why,
                    "deviation": rec.get("deviation"),
                    "latency_s": rec.get("latency_s"), "board": stamp}) + "\n")
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
        lives = (st.get("life"),) + tuple(o.get("life")
                                          for o in st.get("opponents", []) or [])
        pool = st.get("manaPool")
        return (req.get("turn"), stack, opts, lives, pool)

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

    def _fastpath(self, req: dict) -> tuple[dict, str] | None:
        if req.get("decisionType") != "REACT":
            return None
        non_pass = [o for o in req.get("options", []) if o.get("id") != 0]
        if non_pass and all(any(str(o.get("label", "")).startswith(p)
                                for p in self.autopass) for o in non_pass):
            return {"chosenId": 0}, "autopass"
        if self._react_signature(req) in self.react_seen:
            return {"chosenId": 0}, "memo"
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
        self.brain.ensure_session()  # pre-warm: dossier loads before turn 0
        while True:
            self._apply_control()
            req = self.mb.pending_request()
            if req is None:
                time.sleep(poll_s)
                continue
            self.handle(req)

    def handle(self, req: dict) -> None:
        if self.mb.game_reset:
            self._usage_readout("game close")  # final readout for the ended game
            self._say(f"[seat {self.seat}] NEW GAME detected — session + memory reset")
            self.mb.game_reset = False
            self.brain.reset()
            self.plan = None
            self.hold = None
            self.react_seen.clear()
        if self._last_turn != req.get("turn"):
            self._last_turn = req.get("turn")
            self.react_seen.clear()
            self.hold = None  # hold posture is single-turn
            self.turn_intent = None

        seq, dtype = req.get("seq"), req.get("decisionType")

        # Guard #4: any opponent instant-speed action during our own turn shows
        # up as a REACT req — it invalidates the executable plan wholesale (the
        # remainder is strategically stale). Checked BEFORE fastpath so even an
        # autopassed react still kills the plan.
        if self.plan and dtype == "REACT" and self.plan.get("turn") == req.get("turn"):
            self._say(f"[seat {self.seat}] plan invalidated (opponent interaction)")
            self.plan = None

        fast = self._fastpath(req)
        if fast:
            answer, source = fast
            why = ("all options on the no-op allowlist" if source == "autopass"
                   else "identical window already passed this turn")
            ok = self.mb.respond(req, answer)
            self._say(f"[seat {self.seat}] seq={seq} {dtype} -> {json.dumps(answer)} "
                      f"[{source}]{'' if ok else ' WINDOW LOST'}")
            self._record(req, answer, source, why=why, consumed=ok)
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
                return
            self._say(f"[seat {self.seat}] plan invalidated (divergence at seq {seq})")
            self.plan = None

        # Deadline: answer must land before the engine gives up on us.
        try:
            mtime = (self.mb.inbox / f"req-{seq}.json").stat().st_mtime
        except OSError:
            mtime = time.time()
        deadline = mtime + 0.8 * self.timeout_s
        budget = deadline - time.time()
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
            # Cap at the deadline (raised to 240 so fable/high effort isn't
            # truncated on long-timeout games; normal 90s games stay budget-bound).
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
            out, meta = self.brain.decide(prompt, timeout_s=min(budget, 240.0),
                                          effort=fast_eff)
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
        else:
            self._say(f"[seat {self.seat}] seq={seq} only {budget:.0f}s left "
                      f"-> safe default without model call")
            why = "punt: deadline nearly expired"
        if answer is None:
            answer = rules.safe_default(req)

        if dtype == "REACT" and answer == {"chosenId": 0}:
            self.react_seen.add(self._react_signature(req))

        ok = self.mb.respond(req, answer)
        lat = f" {meta['latency_s']}s" if meta and meta.get("latency_s") else ""
        self._say(f"[seat {self.seat}] seq={seq} {dtype} turn={req.get('turn')} "
                  f"{req.get('phase', '')} -> {json.dumps(answer)} [{source}{lat}]"
                  f"{('  # ' + why) if why else ''}"
                  f"{'' if ok else ' WINDOW LOST'}")
        self._record(req, answer, source, meta, why=why, consumed=ok)
