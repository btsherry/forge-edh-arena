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

Usage:
  advisor_runner.py --deck <slug> [--model opus] [--effort low]
                    [--base <mailbox-dir>] [--timeout 60]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seatd.brain import SeatBrain  # noqa: E402

POLL_S = 0.5
# Table roster convention shared with run_table.sh / GuiPilotMatch: four deck
# slugs in seat order, overridable via ARENA_SEAT_DECKS.
DEFAULT_TABLE = ("selvala-heart-of-the-wilds purphoros-god-of-the-forge "
                 "giada-font-of-hope urza-lord-high-artificer")


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
    for slug in roster:
        if slug == own_deck:
            continue
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
    def __init__(self, deck: str, base: Path, model: str, effort: str, timeout: float):
        self.inbox = base / "seat-0-advisor" / "inbox"
        self.timeout = timeout
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._stream = log_dir / "advisor-0.log"
        self._jsonl = log_dir / "advisor-0.jsonl"
        self._usage = log_dir / "seat-0.usage.json"
        self._control = log_dir / "control" / "seat-0.json"
        self._control_mtime = 0.0
        arena_root = Path(__file__).resolve().parent.parent
        self.brain = SeatBrain(0, deck, model=model, effort=effort,
                               log=self._say, brief="advisor-brief.md",
                               extra_parts=opponent_deck_sections(deck, arena_root))
        self.last_seq = 0
        self.pending_context: list[str] = []  # chosen/digest lines awaiting a call
        self._init_control(model, effort)
        # ---- frequency governor state (the charm patch) ----------------------
        # Advice is deliberately sparse: 3-5 moments per turn — first main and
        # combat guaranteed, the rest admitted by seeded dice. Danger (an
        # opponent's spell on the stack) pierces the budget unconditionally.
        self.rng = random.Random()
        self.gov_turn = -1
        self.gov_budget = 0
        self.gov_main1_done = False
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
        self.gov_budget = self.rng.randint(3, 5)
        self.gov_main1_done = False
        self._record("governor", {"turn": turn, "budget": self.gov_budget,
                                  "seed": seed})

    def _admit(self, req: dict) -> tuple[bool, str]:
        """Governor verdict for one request: (advise?, reason)."""
        turn = int(req.get("turn") or 0)
        if turn > self.gov_turn:
            self._gov_new_turn(turn)
        dtype = req.get("decisionType") or ""
        if dtype != "PRIORITY":
            # Explicit questions (targets, X, mulligans, declares) are always
            # answered; combat declares are the guaranteed combat slots.
            if self.gov_budget > 0:
                self.gov_budget -= 1
            return True, "question"
        # Danger pierces the budget: an opponent's spell is on the stack.
        state = req.get("state") or {}
        stack = state.get("stack") or []
        if self.own_card_names and any(s not in self.own_card_names for s in stack):
            if self.gov_budget > 0:
                self.gov_budget -= 1
            return True, "danger"
        # Guaranteed slot: the first main-phase stop of the turn.
        phase = str(req.get("phase") or "")
        if not self.gov_main1_done and "MAIN1" in phase:
            self.gov_main1_done = True
            if self.gov_budget > 0:
                self.gov_budget -= 1
            return True, "main1"
        # The sprinkle: seeded dice while budget remains.
        if self.gov_budget > 0 and self.rng.random() < self.RANDOM_ADMIT_P:
            self.gov_budget -= 1
            return True, "sprinkle"
        return False, "budget"

    # ---- output --------------------------------------------------------------

    def _say(self, msg: str) -> None:
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    def _stream_write(self, text: str) -> None:
        with self._stream.open("a") as f:
            f.write(text)

    def _record(self, kind: str, body: dict) -> None:
        body = {"ts": round(time.time(), 3), "kind": kind, **body}
        with self._jsonl.open("a") as f:
            f.write(json.dumps(body) + "\n")
        try:
            self._usage.write_text(json.dumps(self.brain.totals))
        except OSError:
            pass

    # ---- control file (AI-tab steppers re-dial the advisor mid-game) ----------

    def _init_control(self, model: str, effort: str) -> None:
        try:
            self._control.parent.mkdir(parents=True, exist_ok=True)
            if not self._control.exists():
                self._control.write_text(json.dumps({"model": model, "effort": effort}))
            self._control_mtime = self._control.stat().st_mtime
        except OSError:
            pass

    def _apply_control(self) -> None:
        try:
            mtime = self._control.stat().st_mtime
            if mtime == self._control_mtime:
                return
            self._control_mtime = mtime
            desired = json.loads(self._control.read_text())
            model = desired.get("model")
            effort = desired.get("effort")
            if model and model != self.brain.model:
                self.brain.model = model
                self._say(f"[advisor] model -> {model}")
            if effort and effort != self.brain.effort:
                self.brain.effort = effort
                self._say(f"[advisor] effort -> {effort}")
        except (OSError, ValueError):
            pass

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
            ctx = "SINCE LAST TIME:\n" + "\n".join(self.pending_context) + "\n\n"
            self.pending_context = []
        prompt = (f"{ctx}DECISION NOW — {req.get('decisionType')} "
                  f"(turn {turn}, {phase}): {req.get('prompt')}\n"
                  f"{self._fmt_options(req)}"
                  f"STATE: {json.dumps(req.get('state'), separators=(',', ':'))}\n\n"
                  "Advise the human now (1-3 sentences, plain text).")
        answer, meta = self.brain.decide(prompt, self.timeout)
        text = (meta.get("raw") or "").strip()
        if text:
            self._stream_write(f"\n[t{turn} · {phase}] {text}\n")
        self._record("advice", {"seq": req.get("seq"), "turn": turn, "phase": phase,
                                "decisionType": req.get("decisionType"),
                                "text": text, "latency_s": meta.get("latency_s")})

    def _commentate(self, digest: dict) -> None:
        turn = digest.get("turn")
        lines = digest.get("digest") or []
        prompt = (f"TURN {turn} COMPLETE. Public log of the turn:\n"
                  + "\n".join(f"  {ln}" for ln in lines[-60:])
                  + "\n\nONE line of color commentary (plain text).")
        answer, meta = self.brain.decide(prompt, min(self.timeout, 45.0))
        text = (meta.get("raw") or "").strip()
        if text:
            self._stream_write(f"\n[t{turn} · color] {text}\n")
        self._record("color", {"seq": digest.get("seq"), "turn": turn,
                               "text": text, "latency_s": meta.get("latency_s")})

    # ---- main loop ---------------------------------------------------------------

    def run(self) -> None:
        self._say(f"[advisor] up — deck={self.brain.deck} model={self.brain.model} "
                  f"watching {self.inbox}")
        self.brain.ensure_session()  # pre-warm: dossier loads before turn 0
        self._stream_write("[advisor] session warm — watching your table.\n")
        while True:
            self._apply_control()
            items = self._scan()
            if not items:
                time.sleep(POLL_S)
                continue
            if items[0][0] < self.last_seq:
                # seq regression = new game: fresh session, fresh transcript
                self._say("[advisor] new game detected — resetting session")
                self.brain.reset()
                self.pending_context = []
                self.last_seq = 0
            reqs, digests = [], []
            for n, kind, path in items:
                body = self._load(path)
                if body is None:
                    continue  # partial write — leave for next poll
                self.last_seq = max(self.last_seq, n)
                if kind == "req":
                    reqs.append(body)
                elif kind == "digest":
                    digests.append(body)
                elif kind == "chosen":
                    self.pending_context.append(
                        f"- the human chose {json.dumps(body.get('chosen'))} "
                        f"for {body.get('decisionType')} (seq {body.get('seq')})")
                elif kind == "note":
                    self._stream_write(f"[t{body.get('turn')}] ⏭ {body.get('note')}\n")
                    self._record("note", body)
                try:
                    path.unlink()
                except OSError:
                    pass
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
                    self.pending_context.append(
                        f"- turn {d.get('turn')} public log: "
                        + " | ".join((d.get("digest") or [])[-25:]))
                self._advise(admitted[0])
            else:
                for d in digests:
                    self._commentate(d)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True, help="the HUMAN's deck slug")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--base", default=str(Path(__file__).resolve().parent.parent / "mailbox"))
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    AdvisorRunner(args.deck, Path(args.base), args.model, args.effort,
                  args.timeout).run()


if __name__ == "__main__":
    main()
