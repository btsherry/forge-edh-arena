"""The mailbox decision contract as code.

Under the subscription transport there is NO grammar-enforced JSON, so this
module is the correctness gate: `validate()` accepts only responses the engine
will honor (anything else silently falls to stock — or worse, a
malformed-but-parseable answer burns the window), and `safe_default()` produces
a per-type answer that is ALWAYS engine-legal.

Traps encoded here (from the source-extracted contract, docs/INTERACTIVE-ARENA.md):
- MULLIGAN answers {"keep": bool} — its option ids are decorative.
- CHOOSE_MODE ids are 0-based INDICES into options; 0 is a REAL mode. Everywhere
  else id 0 is reserved for pass/none and only legal when actually offered.
- DECLARE_* are whole-assignment atomic: one bad pair discards ALL to stock;
  defenders must ALWAYS be explicit (multiplayer ambiguity poisons the block).
- Ids must be bare JSON integers ('1' or 1.0 -> stock). Bools are not ints.
- min/max/allowRepeat live in the request `state` and are strict.
"""
from __future__ import annotations

import json

# What the model must emit, per decisionType (fed into the prompt by brain.py).
ANSWER_CONTRACT = {
    "CAST_SPELL": 'Answer: {"chosenId": <option id>} — 0 = pass.',
    "REACT": 'Answer: {"chosenId": <option id>} — 0 = pass (do not respond).',
    "MULLIGAN": 'Answer: {"keep": true} or {"keep": false} — NOT chosenId.',
    "DECLARE_ATTACKERS": ('Answer: {"attackers": [{"attacker": <cardId>, "defender": '
                          '<entityId from state.defenders>}, ...]} — [] = no attack. '
                          'Every entry needs an explicit defender.'),
    "DECLARE_BLOCKERS": ('Answer: {"blocks": [{"blocker": <cardId>, "attacker": '
                         '<cardId from state.attackers>}, ...]} — [] = no blocks.'),
    "CHOOSE_ENTITY": ('Answer: {"chosenId": <option id>} — 0 (choose none) only if '
                      'offered in options.'),
    "CHOOSE_ENTITIES": ('Answer: {"chosen": [<option id>, ...]} — unique ids, count '
                        'within state.min..state.max.'),
    "CHOOSE_MODE": ('Answer: {"chosen": [<mode index>, ...]} — indices are 0-BASED '
                    'positions in options (0 is a real mode), count within '
                    'state.min..state.max; repeats only if state.allowRepeat.'),
    "CHOOSE_CARD": ('Answer: {"chosenId": <option id>} — 0 (choose none) only if '
                    'offered in options.'),
    "CHOOSE_NUMBER": ('Answer: {"chosen": <integer>} within state.min..state.max '
                      '— typically an X value; max is your affordable ceiling, '
                      'so bigger is usually (not always) better.'),
}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _option_ids(req) -> list[int]:
    return [o.get("id") for o in req.get("options", []) if _is_int(o.get("id"))]


def _bounds(req, default_min=1, default_max=1) -> tuple[int, int]:
    st = req.get("state", {}) or {}
    lo = st.get("min", req.get("min", default_min))
    hi = st.get("max", req.get("max", default_max))
    lo = lo if _is_int(lo) else default_min
    hi = hi if _is_int(hi) else default_max
    return lo, hi


def validate(req: dict, out) -> dict | None:
    """Return the CLEANED response dict the engine should receive, or None.

    Tolerates (and strips) extra keys like `reasoning`/`turn_plan` — the wire
    payload contains only the contract fields."""
    if not isinstance(out, dict):
        return None
    dtype = req.get("decisionType")
    ids = _option_ids(req)

    if dtype in ("CAST_SPELL", "REACT", "CHOOSE_ENTITY", "CHOOSE_CARD"):
        cid = out.get("chosenId")
        if not _is_int(cid) or cid not in ids:
            return None  # unknown id is NOT a pass — it falls to stock
        return {"chosenId": cid}

    if dtype == "MULLIGAN":
        keep = out.get("keep")
        if not isinstance(keep, bool):
            return None
        return {"keep": keep}

    if dtype == "DECLARE_ATTACKERS":
        arr = out.get("attackers")
        if not isinstance(arr, list):
            return None
        attacker_ids = [i for i in ids if i != 0]
        defender_ids = {d.get("id") for d in (req.get("state", {}) or {}).get(
            "defenders", []) if _is_int(d.get("id"))}
        seen, clean = set(), []
        for e in arr:
            if not isinstance(e, dict):
                continue  # tolerate stray non-object noise (e.g. a leaked "why")
            a, d = e.get("attacker"), e.get("defender")
            if not _is_int(a) or a not in attacker_ids:
                return None
            if a in seen:
                continue  # a creature attacks once; a repeat entry is noise, keep first
            if not _is_int(d) or (defender_ids and d not in defender_ids):
                return None  # defender ALWAYS explicit and known
            seen.add(a)
            clean.append({"attacker": a, "defender": d})
        return {"attackers": clean}

    if dtype == "DECLARE_BLOCKERS":
        arr = out.get("blocks")
        if not isinstance(arr, list):
            return None
        blocker_ids = [i for i in ids if i != 0]
        attacker_ids = {a.get("id") for a in (req.get("state", {}) or {}).get(
            "attackers", []) if _is_int(a.get("id"))}
        seen, clean = set(), []
        for e in arr:
            if not isinstance(e, dict):
                continue  # tolerate stray non-object noise (e.g. a leaked "why")
            b, a = e.get("blocker"), e.get("attacker")
            if not _is_int(b) or b not in blocker_ids:
                return None  # unknown blocker id
            if b in seen:
                continue  # a creature blocks once; a repeat entry is noise, keep first
            if not _is_int(a) or (attacker_ids and a not in attacker_ids):
                return None
            seen.add(b)
            clean.append({"blocker": b, "attacker": a})
        return {"blocks": clean}

    if dtype == "CHOOSE_ENTITIES":
        arr = out.get("chosen")
        if not isinstance(arr, list):
            return None
        lo, hi = _bounds(req, 0, len(ids))
        pool = [i for i in ids if i != 0]
        if len(arr) != len(set(arr)) or not (lo <= len(arr) <= hi):
            return None
        if any((not _is_int(i)) or i not in pool for i in arr):
            return None
        return {"chosen": list(arr)}

    if dtype == "CHOOSE_MODE":
        arr = out.get("chosen")
        if not isinstance(arr, list):
            return None
        lo, hi = _bounds(req, 1, 1)
        allow_repeat = bool((req.get("state", {}) or {}).get(
            "allowRepeat", req.get("allowRepeat", False)))
        if not (lo <= len(arr) <= hi):
            return None
        if not allow_repeat and len(arr) != len(set(arr)):
            return None
        if any((not _is_int(i)) or i not in ids for i in arr):
            return None  # mode ids ARE the option indices; 0 is a real mode
        return {"chosen": list(arr)}

    if dtype == "CHOOSE_NUMBER":
        n = out.get("chosen")
        lo, hi = _bounds(req, 0, 0)
        if not _is_int(n) or not (lo <= n <= hi):
            return None
        return {"chosen": n}

    return None  # unknown decisionType: never guess


def safe_default(req: dict) -> dict:
    """Always-legal per-type answer; the punt when the model fails us.
    Guaranteed to pass validate(req, safe_default(req))."""
    dtype = req.get("decisionType")
    ids = _option_ids(req)
    if dtype == "MULLIGAN":
        return {"keep": True}
    if dtype == "DECLARE_ATTACKERS":
        return {"attackers": []}
    if dtype == "DECLARE_BLOCKERS":
        return {"blocks": []}
    if dtype == "CHOOSE_MODE":
        lo, _ = _bounds(req, 1, 1)
        return {"chosen": list(range(lo))}       # first `min` indices
    if dtype == "CHOOSE_ENTITIES":
        lo, _ = _bounds(req, 0, len(ids))
        return {"chosen": [i for i in ids if i != 0][:lo]}
    if dtype in ("CHOOSE_ENTITY", "CHOOSE_CARD"):
        if 0 in ids:
            return {"chosenId": 0}               # optional: choose none
        pool = [i for i in ids if i != 0]
        return {"chosenId": pool[0] if pool else 0}  # mandatory: first legal
    if dtype == "CHOOSE_NUMBER":
        lo, hi = _bounds(req, 0, 0)
        return {"chosen": hi}  # punt HIGH: for X costs, min would re-create the
                               # Ballista-at-0 death; max is affordability-capped
    return {"chosenId": 0}                        # CAST_SPELL / REACT / unknown


def build_user_prompt(req: dict, plan: str | None = None,
                      observer: dict | None = None) -> str:
    """Per-decision prompt for the seat's model session (dossier already lives
    in the session's first message — this carries only the fresh decision)."""
    dtype = req.get("decisionType", "?")
    parts = [
        f"DECISION seq={req.get('seq')} | {dtype} | turn {req.get('turn')} "
        f"| {req.get('phase', '')}",
        ANSWER_CONTRACT.get(dtype, 'Answer: {"chosenId": 0}'),
    ]
    if observer:
        seats = observer.get("seats", [])
        lifeline = ", ".join(
            f"seat {s.get('seat')}: {s.get('life')} life, "
            f"{s.get('handSize')} cards"
            + (" [ELIMINATED]" if s.get("eliminated") else "")
            for s in seats)
        if lifeline:
            parts.append(f"PUBLIC TABLE: {lifeline} | stack: {observer.get('stack')}")
    if plan:
        parts.append(f"YOUR TURN PLAN (advisory — the request state below WINS "
                     f"if they disagree): {plan}")
    parts.append("REQUEST (ground truth — re-derive your decision from this):")
    parts.append(json.dumps(req, separators=(",", ":")))
    parts.append(
        "Reply with ONLY the JSON answer object on one line — no prose, no "
        "code fences. REQUIRED: include a \"why\" key — your decision logic in "
        "<=20 words (it is logged, never shown to opponents). You may add an "
        "optional \"turn_plan\" key (<=150 words) when this is the first "
        "main-phase decision of YOUR turn.")
    return "\n".join(parts)
