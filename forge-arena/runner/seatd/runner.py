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
import time
from pathlib import Path

from . import rules
from .brain import SeatBrain
from .protocol import SeatMailbox

DEFAULT_AUTOPASS = ("Giver of Runes", "Academy Ruins")


class SeatRunner:
    def __init__(self, seat: int, deck: str, base, model: str = "sonnet",
                 timeout_s: float = 90.0, log_dir=None,
                 autopass: tuple[str, ...] = DEFAULT_AUTOPASS):
        self.mb = SeatMailbox(seat, base, timeout_s=timeout_s)
        self.brain = SeatBrain(seat, deck, model=model, log=self._say)
        self.seat, self.deck = seat, deck
        self.timeout_s = timeout_s
        self.autopass = tuple(autopass)
        self.plan: tuple[int, str] | None = None      # (turn, text)
        self.react_seen: set[tuple] = set()
        self._last_turn: int | None = None
        log_dir = Path(log_dir) if log_dir else Path(__file__).parents[1] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / f"seat-{seat}.log"
        self._jsonl_path = log_dir / f"seat-{seat}.jsonl"

    # ---- logging ---------------------------------------------------------

    def _say(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            with self._log_path.open("a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _record(self, req: dict, answer: dict, source: str, meta=None) -> None:
        rec = {"ts": time.time(), "seat": self.seat, "seq": req.get("seq"),
               "turn": req.get("turn"), "phase": req.get("phase"),
               "type": req.get("decisionType"), "source": source,
               "answer": answer}
        if meta:
            rec["latency_s"] = meta.get("latency_s")
            rec["usage"] = meta.get("usage")
        rec["cum"] = dict(self.brain.totals)  # burn since instantiation
        try:
            with self._jsonl_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            # Always-current snapshot: THE final readout is whatever this
            # holds when the game closes (survives kill/crash).
            (self._jsonl_path.parent / f"seat-{self.seat}.usage.json").write_text(
                json.dumps(rec["cum"], indent=1))
        except OSError:
            pass

    def _usage_readout(self, label: str) -> None:
        t = self.brain.totals
        self._say(f"[seat {self.seat}] USAGE {label}: {t['calls']} calls, "
                  f"in={t['input_tokens']} out={t['output_tokens']} "
                  f"cache_read={t['cache_read_input_tokens']} "
                  f"cache_write={t['cache_creation_input_tokens']} "
                  f"(≈${t['cost_usd']:.2f} API-equivalent; subscription-covered)")

    # ---- fastpaths --------------------------------------------------------

    def _react_signature(self, req: dict) -> tuple:
        stack = tuple(sorted(map(str, (req.get("state", {}) or {}).get("stack", []))))
        opts = tuple(sorted(str(o.get("label", "")).split("  ")[0]
                            for o in req.get("options", []) if o.get("id") != 0))
        return (req.get("turn"), stack, opts)

    def _fastpath(self, req: dict) -> tuple[dict, str] | None:
        if req.get("decisionType") != "REACT":
            return None
        non_pass = [o for o in req.get("options", []) if o.get("id") != 0]
        if non_pass and all(any(str(o.get("label", "")).startswith(p)
                                for p in self.autopass) for o in non_pass):
            return {"chosenId": 0}, "autopass"
        if self._react_signature(req) in self.react_seen:
            return {"chosenId": 0}, "memo"
        return None

    # ---- the loop ------------------------------------------------------------

    def run(self, poll_s: float = 0.5) -> None:
        swept = self.mb.sweep_outbox()
        self._say(f"[seat {self.seat}] runner up — deck={self.deck} "
                  f"model={self.brain.model} timeout={self.timeout_s}s"
                  + (f" (swept {swept} stale)" if swept else ""))
        self.brain.ensure_session()  # pre-warm: dossier loads before turn 0
        while True:
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
            self.react_seen.clear()
        if self._last_turn != req.get("turn"):
            self._last_turn = req.get("turn")
            self.react_seen.clear()

        seq, dtype = req.get("seq"), req.get("decisionType")

        fast = self._fastpath(req)
        if fast:
            answer, source = fast
            ok = self.mb.respond(req, answer)
            self._say(f"[seat {self.seat}] seq={seq} {dtype} -> {json.dumps(answer)} "
                      f"[{source}]{'' if ok else ' WINDOW LOST'}")
            self._record(req, answer, source)
            return

        # Deadline: answer must land before the engine gives up on us.
        try:
            mtime = (self.mb.inbox / f"req-{seq}.json").stat().st_mtime
        except OSError:
            mtime = time.time()
        deadline = mtime + 0.8 * self.timeout_s
        budget = deadline - time.time()
        answer, source, meta = None, "punt", None
        if budget > 5.0:
            plan_text = self.plan[1] if (self.plan and
                                         self.plan[0] == req.get("turn")) else None
            prompt = rules.build_user_prompt(req, plan=plan_text,
                                             observer=self.mb.read_observer())
            out, meta = self.brain.decide(prompt, timeout_s=min(budget, 120.0))
            clean = rules.validate(req, out) if out is not None else None
            if clean is not None:
                answer, source = clean, "model"
                if (isinstance(out, dict) and out.get("turn_plan")
                        and dtype == "CAST_SPELL"
                        and req.get("phase") in ("MAIN1", "MAIN2")):
                    self.plan = (req.get("turn"), str(out["turn_plan"])[:1200])
            elif out is not None:
                self._say(f"[seat {self.seat}] seq={seq} INVALID model answer "
                          f"{str(meta.get('raw'))[:120]!r} -> safe default")
        else:
            self._say(f"[seat {self.seat}] seq={seq} only {budget:.0f}s left "
                      f"-> safe default without model call")
        if answer is None:
            answer = rules.safe_default(req)

        if dtype == "REACT" and answer == {"chosenId": 0}:
            self.react_seen.add(self._react_signature(req))

        ok = self.mb.respond(req, answer)
        lat = f" {meta['latency_s']}s" if meta and meta.get("latency_s") else ""
        self._say(f"[seat {self.seat}] seq={seq} {dtype} turn={req.get('turn')} "
                  f"{req.get('phase', '')} -> {json.dumps(answer)} [{source}{lat}]"
                  f"{'' if ok else ' WINDOW LOST'}")
        self._record(req, answer, source, meta)
