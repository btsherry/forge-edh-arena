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
    "CAST_SPELL": ('Answer: {"chosenId": <option id>} — 0 = pass. If a cast '
                   'depends on a painful/conditional source (Ancient Tomb, '
                   'Gemstone Caverns class), FLOAT that mana first, then cast '
                   '— the auto-payer will not tap those for you.'),
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
                        'within state.min..state.max. SACRIFICE/DESTROY prompts '
                        '(edicts, sac-outlet payments) pick what YOU lose: feed '
                        'expendable bodies (tokens, spent pieces) unless your line '
                        'wants a death trigger to fire.'),
    "CHOOSE_MODE": ('Answer: {"chosen": [<mode index>, ...]} — indices are 0-BASED '
                    'positions in options (0 is a real mode), count within '
                    'state.min..state.max; repeats only if state.allowRepeat.'),
    "CHOOSE_CARD": ('Answer: {"chosenId": <option id>} — 0 (choose none) only if '
                    'offered in options.'),
    "CHOOSE_CARDS": ('Answer: {"chosen": [<option id>, ...]} — unique ids, count '
                     'within state.min..state.max (a multi-card search: e.g. '
                     'Cultivate\'s two basics, "up to two"). [] only if min is 0.'),
    "PAY_UNLESS": ('Answer: {"chosenId": 1} to PAY state.unlessCost now (uses '
                   'floating mana first, then untapped sources), or {"chosenId": 0} '
                   'to decline and let the effect happen. If state.effectIsMine is '
                   'true this is YOUR OWN spell (e.g. paying X to keep a tutored card '
                   'on the battlefield — usually pay if you can); if false an '
                   'opponent is taxing you (counter-unless, Rhystic Study, Propaganda) '
                   '— pay only when what you protect is worth the mana.'),
    "CONFIRM": ('Answer: {"chosenId": 1} = yes, {"chosenId": 0} = no. Read the '
                'question in the prompt; state.confirmMode names the situation. '
                'confirmMode TRIGGER = one of YOUR OWN optional ("you may") '
                'triggers is resolving: state.triggerText is the trigger, '
                'state.yesCost is what saying yes costs (paid from your pool/'
                'sources when it resolves), state.chosenTargets is what it will '
                'affect. Loops live here (Rings of Brighthearth copies, "may pay '
                'to copy/untap/draw"): if the yes-cost is part of a line you are '
                'executing, say yes. confirmMode PLAY_FROM_EFFECT = your own '
                '"may cast" from an effect (Scepter copy, cascade, impulse) — '
                'state.spell names it, state.free says it costs nothing.'),
    "CHOOSE_NUMBER": ('Answer: {"chosen": <integer>} within state.min..state.max '
                      '— typically an X value; max is your affordable ceiling '
                      'RIGHT NOW (it counts your floating pool), so bigger is '
                      'usually (not always) better. If state.cancelable is true '
                      'you may instead answer {"chosen": -1} to CANCEL the cast '
                      '— do that when max is far below what you intended: the '
                      'cast rewinds, and you can activate mana abilities '
                      '(commander, Cradle-class lands, untappers) to grow the '
                      'pool, then re-cast for a real X.'),
}

# Injected into CAST_SPELL / CHOOSE_NUMBER prompts: the anti-hallucination
# ground truth for mana. Written after the 2026-08-10 game where a brain
# announced "seven floating mana" off an untapped-source COUNT and wasted
# Genesis Wave at X=0.
MANA_GROUND_TRUTH = (
    'MANA GROUND TRUTH: state.manaPool is your ONLY floating mana — if it is '
    '0 you have floated NOTHING, no matter what you played earlier. '
    'state.untappedManaSourceCount counts untapped SOURCES, not mana (a '
    'Gaea\'s Cradle is 1 source even when it would add 4). The pool empties '
    'when the current step/phase ends — float only what you will spend this '
    'phase. Payment auto-taps simple lands and spends your pool first. To '
    'cast a big X spell: ACTIVATE mana-ability options FIRST (they resolve '
    'instantly, no stack, cannot be responded to), watch state.manaPool grow '
    'on the next request, THEN cast the X spell.')

# Optional key a REACT-pass may add to batch its own subsequent same-turn reacts.
REACT_HOLD_HINT = (
    'OPTIONAL on a REACT you are PASSING (chosenId 0): add "hold_turn": true if '
    'you intend to hold ALL your interaction for the rest of THIS turn. The '
    'runner will then auto-pass your later same-turn react windows to save time '
    '— but it ALWAYS hands control back to you the instant a genuinely NEW '
    'spell or ability appears on the stack, or at any empty-stack combat window. '
    'Set it only when you truly will not act again this turn barring a new '
    'threat; if you are holding a counter to fire when a specific object is on '
    'top of the stack, do NOT set it.')


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

    if dtype in ("CAST_SPELL", "REACT", "CHOOSE_ENTITY", "CHOOSE_CARD",
                 "PAY_UNLESS", "CONFIRM"):
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
                continue  # bare-string noise (e.g. a leaked "why") — skip
            a = e.get("attacker")
            if not _is_int(a):
                continue  # dict noise with no attacker id (e.g. {"why": "x"}) — skip
            if a not in attacker_ids:
                return None  # a real-but-illegal attacker id → hard reject
            if a in seen:
                continue  # a creature attacks once; a repeat entry is noise, keep first
            d = e.get("defender")
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
                continue  # bare-string noise (e.g. a leaked "why") — skip
            b = e.get("blocker")
            if not _is_int(b):
                continue  # dict noise with no blocker id (e.g. {"why": "x"}) — skip
            if b not in blocker_ids:
                return None  # a real-but-illegal blocker id → hard reject
            if b in seen:
                continue  # a creature blocks once; a repeat entry is noise, keep first
            a = e.get("attacker")
            if not _is_int(a) or (attacker_ids and a not in attacker_ids):
                return None
            seen.add(b)
            clean.append({"blocker": b, "attacker": a})
        return {"blocks": clean}

    if dtype in ("CHOOSE_ENTITIES", "CHOOSE_CARDS"):
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
        if _is_int(n) and n == -1 and (req.get("state", {}) or {}).get("cancelable"):
            return {"chosen": -1}  # explicit cancel sentinel (engine rewinds the cast)
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
    if dtype in ("CHOOSE_ENTITIES", "CHOOSE_CARDS"):
        lo, _ = _bounds(req, 0, len(ids))
        return {"chosen": [i for i in ids if i != 0][:lo]}
    if dtype == "CONFIRM":
        # Shape-aware (game 7, 2026-08-17): a punt answered NO to "cast your
        # free Dramatic Reversal copy?" and Urza's loop unwound at 72s a step.
        # Confirms about the seat's OWN free play/copy default to YES (they
        # spend nothing and are what the seat was doing); everything else —
        # trigger yes-costs, sacrifice/pay-life/exile confirms — stays NO,
        # the answer that spends nothing.
        st = req.get("state", {}) or {}
        mode = str(st.get("confirmMode", "") or "")
        prompt = str(req.get("prompt", "") or "").lower()
        if mode == "TRIGGER":
            free = str(st.get("yesCost", "none")).lower() in ("none", "", "0", "{0}")
            return {"chosenId": 1 if free else 0}
        if mode == "PLAY_FROM_EFFECT":
            # your own "may cast" (Scepter copy, cascade, impulse): free -> yes
            return {"chosenId": 1 if st.get("free") else 0}
        if mode in ("untyped", "OptionalChoose") and any(
                w in prompt for w in ("play", "cast", "copy")) and not any(
                w in prompt for w in ("sacrifice", "pay life", "exile", "discard")):
            return {"chosenId": 1}
        return {"chosenId": 0}
    if dtype == "PAY_UNLESS":
        return {"chosenId": 0}                   # decline: legal, spends nothing
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


def bind_plan_step(step: dict, req: dict) -> int | None:
    """Resolve an executable-plan step (references a card by NAME) to the current
    req's option id. Option ids are per-req, so plans can't carry ids across the
    sequential reqs a turn produces — they name the card and we re-resolve here.
    Returns the id of the first non-pass option whose label contains the card
    name (case-insensitive), or None (guard #3: intended play absent)."""
    if not isinstance(step, dict):
        return None
    card = str(step.get("card", "")).strip().lower()
    if not card:
        return None
    for o in req.get("options", []):
        if not _is_int(o.get("id")) or o.get("id") == 0:
            continue
        if card in str(o.get("label", "")).lower():
            return o.get("id")
    return None


PLAN_KEY_INSTRUCTION = (
    "OPTIONAL, only on the FIRST main-phase decision of YOUR own turn: a "
    "\"plan\" key — an ordered array of the REMAINING sorcery-speed CAST "
    "plays you intend THIS turn, each {\"card\": \"<exact card name>\", "
    "\"why\": \"<=12 words\"}, in cast order, EXCLUDING the play you are "
    "making right now and EXCLUDING lands and combat. The runner will "
    "execute these locally to save time, but re-checks each against the "
    "live board and hands control back to you the instant anything diverges "
    "(an opponent responds, a piece is gone, the board changed). Only list "
    "plays you are confident you'll want regardless of small changes.")


def build_user_prompt(req: dict, plan: str | None = None,
                      observer: dict | None = None,
                      speculative: bool = False, react_hold: bool = False,
                      combo_status: str | None = None) -> str:
    """Per-decision prompt for the seat's model session (dossier already lives
    in the session's first message — this carries only the fresh decision).

    Feature text is GATED on the feature actually being on (2026-08-10
    forensics: the always-on plan-key text primed plan-following abstraction
    over literal state reading even with the executor disabled)."""
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
    if combo_status:
        parts.append(combo_status)
    if dtype in ("CAST_SPELL", "CHOOSE_NUMBER"):
        parts.append(MANA_GROUND_TRUTH)
    parts.append("REQUEST (ground truth — re-derive your decision from this):")
    parts.append(json.dumps(req, separators=(",", ":")))
    if dtype == "REACT" and react_hold:
        parts.append(REACT_HOLD_HINT)
    tail = ("Reply with ONLY the JSON answer object on one line — no prose, no "
            "code fences. REQUIRED: include a \"why\" key — your decision logic "
            "in <=20 words (it is logged, never shown to opponents).")
    if (speculative and dtype == "CAST_SPELL"
            and req.get("phase") in ("MAIN1", "MAIN2")):
        tail += "\n" + PLAN_KEY_INSTRUCTION
    parts.append(tail)
    return "\n".join(parts)


def combo_status_line(combos: list, req: dict, limit: int = 3) -> str | None:
    """Compute the per-decision COMBO STATUS block from the deck's
    CommanderSpellbook included-combos list vs the request state's zones.
    Pure name matching — deck-agnostic; works for any deck with combos.json.
    Returns None when there is nothing useful to say."""
    if not combos or req.get("decisionType") != "CAST_SPELL":
        return None
    st = req.get("state", {}) or {}
    bf = {c.get("name") for c in st.get("battlefield") or [] if isinstance(c, dict)}
    hand = {c.get("name") for c in st.get("hand") or [] if isinstance(c, dict)}
    command = {str(n) for n in st.get("command") or []}
    grave = {str(n) for n in st.get("graveyard") or []}
    scored = []
    for combo in combos:
        cards = combo.get("cards") or []
        if not cards:
            continue
        locs, missing = [], 0
        for c in cards:
            name = c.get("name")
            if name in bf:
                locs.append(f"{name} ON BATTLEFIELD")
            elif name in hand:
                locs.append(f"{name} IN HAND")
                missing += 1
            elif name in command:
                locs.append(f"{name} IN COMMAND ZONE")
                missing += 1
            elif name in grave:
                locs.append(f"{name} in graveyard")
                missing += 1
            else:
                locs.append(f"{name} not visible (library?)")
                missing += 2  # further than a castable piece
        scored.append((missing, combo, locs))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0])
    if scored[0][0] >= 2 * len(scored[0][1].get("cards", [1])):
        return None  # nothing assembled or in reach — stay quiet, save tokens
    lines = ["COMBO STATUS (your deck's real combos; advance/protect/execute "
             "when favorable):"]
    for missing, combo, locs in scored[:limit]:
        need = combo.get("mana_needed")
        tag = ("ALL PIECES ON BATTLEFIELD — check prerequisites and EXECUTE "
               "THIS TURN" if missing == 0
               else f"{missing} step(s) from live")
        lines.append(f"- {' + '.join(c.get('name','?') for c in combo.get('cards', []))}: "
                     + "; ".join(locs) + f" — {tag}"
                     + (f"; needs {need}" if need else ""))
    return "\n".join(lines)
