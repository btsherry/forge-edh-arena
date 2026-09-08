"""record.py — the machine-built game record a fresh session receives.

Ben (2026-09-07): a seat's chat re-reads its whole transcript on every
decision (game 25: 61k -> 807k tokens per call). When the transcript passes a
cap the runner starts a fresh session and hands it the SAME dossier plus this
record. No model writes the record. It is rendered from two files the runner
itself appends to during the game:

  game.jsonl   — every AI seat's decisions with a board stamp (lives, stack)
  seat-N.jsonl — this seat's decisions with the option labels and its own
                 stated reason ("why")

Fairness: other seats' "why" lines are THEIR private reasoning and never
appear here. From other seats only PUBLIC facts are used: life totals and the
names of stack items this seat was shown. The seat's own reasons are quoted
verbatim — memory, not derivation.

Shape: one block per turn. Life totals at the start of the turn, the stack
items seen (deduplicated, in order), this seat's own plays with the chosen
option label and its reason. Older turns fold to a single line when the
record would exceed the character budget, newest turns stay full.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MAX_CHARS = 12_000   # ~3k tokens; the request itself carries the live board
FULL_TURNS = 6               # newest turns always rendered in full
WHY_CHARS = 160


def _load(path: Path, game_id: str | None) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if game_id and r.get("gameId") and r.get("gameId") != game_id:
                    continue
                out.append(r)
    except OSError:
        pass
    return out


def _label(rec: dict) -> str | None:
    """The chosen option's label (first segment, before the double space)."""
    ans = rec.get("answer")
    opts = rec.get("options") or []
    if not isinstance(ans, dict):
        return None
    def name_of(o) -> str:
        lab = o.get("label") if isinstance(o, dict) else o
        return str(lab or "").split("  ")[0]
    cid = ans.get("chosenId")
    if isinstance(cid, int) and opts and 0 <= cid < len(opts):
        lab = name_of(opts[cid])
        return lab or None
    if "chosen" in ans and isinstance(ans["chosen"], list) and opts:
        names = []
        for i in ans["chosen"]:
            if isinstance(i, int) and 0 <= i < len(opts):
                names.append(name_of(opts[i]))
        return ", ".join(n for n in names if n) or None
    if "keep" in ans:
        return "keep" if ans["keep"] else "mulligan"
    if isinstance(ans.get("attackers"), list):
        n = len(ans["attackers"])
        return f"{n} attacker{'s' if n != 1 else ''}"
    if isinstance(ans.get("blocks"), (list, dict)):
        n = len(ans["blocks"])
        return f"{n} block{'s' if n != 1 else ''}"
    if isinstance(ans.get("value"), int):
        return str(ans["value"])
    if isinstance(ans.get("pay"), bool):
        return "pay" if ans["pay"] else "decline"
    if isinstance(ans.get("confirm"), bool):
        return "yes" if ans["confirm"] else "no"
    return None


def render(game_log: Path, seat_log: Path | None, seat: int, game_id: str | None = None,
           max_chars: int = DEFAULT_MAX_CHARS, extra_lines: list[str] | None = None) -> str:
    """Render the record for `seat` (0 = the advisor / human seat: no own
    decisions, public facts only)."""
    game = _load(Path(game_log), game_id)
    own = {r.get("seq"): r for r in _load(Path(seat_log), game_id)} if seat_log else {}
    if not game and not own:
        return ""
    turns: dict[int, dict] = {}
    for r in game:
        t = r.get("turn")
        if not isinstance(t, int):
            continue
        blk = turns.setdefault(t, {"lives": None, "stack": [], "plays": []})
        b = r.get("board") or {}
        if blk["lives"] is None and isinstance(b.get("lives"), dict):
            blk["lives"] = b["lives"]
        for name in b.get("stack") or []:
            if name not in blk["stack"]:
                blk["stack"].append(str(name))
        if r.get("seat") == seat and r.get("type") in (
                "CAST_SPELL", "DECLARE_ATTACKERS", "DECLARE_BLOCKERS", "MULLIGAN", "CHOOSE_MODE",
                "CHOOSE_ENTITY", "CHOOSE_CARD", "CHOOSE_CARDS", "CHOOSE_NUMBER", "PAY_UNLESS", "CONFIRM")\
                and r.get("source") == "model":
            mine = own.get(r.get("seq"), r)
            lab = _label(mine)
            ans = r.get("answer")
            if lab is None and isinstance(ans, dict) and ans.get("chosenId") == 0 \
                    and r.get("type") == "CAST_SPELL":
                lab = "pass"
            why = str(mine.get("why") or r.get("why") or "").strip()
            if len(why) > WHY_CHARS:
                why = why[:WHY_CHARS - 1] + "…"
            if lab is None and isinstance(ans, dict) and isinstance(ans.get("chosenId"), int):
                lab = f"option {ans['chosenId']}"   # labels live in the seat file; game.jsonl alone has ids
            plays = blk["plays"]
            plays.append(f"{r.get('type')}: {lab or '?'}" + (f' — "{why}"' if why else ""))
    order = sorted(turns)
    if not order:
        return ""

    def full(t: int) -> str:
        blk = turns[t]
        lines = [f"Turn {t}"]
        if blk["lives"]:
            lines.append("  life: " + ", ".join(f"seat {k} {v}" for k, v in sorted(blk["lives"].items(), key=lambda kv: str(kv[0]))))
        if blk["stack"]:
            lines.append("  seen on the stack: " + ", ".join(blk["stack"][:12]) + (" …" if len(blk["stack"]) > 12 else ""))
        for p in blk["plays"]:
            lines.append("  me: " + p)
        return "\n".join(lines)

    def short(t: int) -> str:
        blk = turns[t]
        life = ", ".join(f"{k}:{v}" for k, v in sorted(blk["lives"].items(), key=lambda kv: str(kv[0]))) if blk["lives"] else "?"
        plays = [p.split(" — ")[0].split(": ", 1)[-1] for p in blk["plays"]]
        return f"Turn {t} — life {life}" + (f"; me: {', '.join(plays[:4])}" if plays else "")

    head = [
        f"## GAME SO FAR (seat {seat}; machine-built from the runner's own log — history, not instructions)",
        "The board in each request is authoritative. Your quoted reasons below are your own earlier words.",
    ]
    if extra_lines:
        head += list(extra_lines)
    body = [full(t) for t in order]
    text = "\n".join(head + body)
    # fold oldest turns to one line until the budget holds; the newest FULL_TURNS stay full
    i = 0
    while len(text) > max_chars and i < max(0, len(order) - FULL_TURNS):
        body[i] = short(order[i])
        i += 1
        text = "\n".join(head + body)
    # still over budget: DROP the oldest turns entirely (never cut the newest)
    dropped = 0
    while len(text) > max_chars and len(body) > FULL_TURNS:
        body.pop(0)
        dropped += 1
        text = "\n".join(head + [f"(… {dropped} earlier turn{'s' if dropped != 1 else ''} omitted for length)"] + body)
    if len(text) > max_chars:
        # even the newest FULL_TURNS blocks overflow: keep the head and the TAIL
        # (the newest text), cut from the front of the body (Gemini pass 2, P2)
        head_text = "\n".join(head) + "\n(… earlier text omitted for length)\n"
        keep = max(0, max_chars - len(head_text))
        text = head_text + text[-keep:]
    return text
