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
from seatd import backends  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402

POLL_S = 0.25  # advice feels snappier; cost is a stat() at 4Hz
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
    def __init__(self, deck: str, base: Path, model: str, effort: str, timeout: float,
                 log_dir: Path | None = None):
        self.inbox = base / "seat-0-advisor" / "inbox"
        self.timeout = timeout
        log_dir = Path(log_dir) if log_dir else Path(__file__).parent / "logs"
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
        self.game_id: str | None = None   # item 5/8: the game being advised
        self.pending_context: list[str] = []  # chosen/digest lines awaiting a call
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

    # ---- game identity (plan items 5 + 8) ----------------------------------------

    def _reset_for_new_game(self, why: str) -> None:
        """Fresh session, fresh transcript, fresh governor. The governor used
        to keep the previous game's turn counter, so a second game in one
        process never re-armed and got no advice past the mulligan."""
        self._say(f"[advisor] new game detected ({why}) — resetting session")
        self.brain.reset()
        self.pending_context = []
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
            if kind == "req":
                reqs.append(body)
            elif kind == "digest":
                digests.append(body)
            elif kind == "chosen":
                self.pending_context.append(
                    f"- the human chose {json.dumps(body.get('chosen'))} "
                    f"for {body.get('decisionType')} (seq {body.get('seq')})")
            elif kind == "note":
                if not quiet:
                    self._stream_write(f"[t{body.get('turn')}] ⏭ {body.get('note')}\n")
                self._record("note", body)
            try:
                path.unlink()
            except OSError:
                pass
        if quiet:
            for r in reqs:
                self._record("skipped_backlog", {"seq": r.get("seq"),
                                                 "decisionType": r.get("decisionType")})
            for d in digests:
                self.pending_context.append(
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
                self.pending_context.append(
                    f"- turn {d.get('turn')} public log: "
                    + " | ".join((d.get("digest") or [])[-25:]))
            self._advise(admitted[0])
        else:
            for d in digests:
                self._commentate(d)
        return consumed

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
