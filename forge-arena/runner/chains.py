"""chains.py — interaction chains for the seat voices (Ben, 2026-09-10).

"Playing with the AI should feel like sitting at the table with people": a
line invites replies. Every rendered line is an ATOM (a voice, an id, one of
its wordings); the chain table (voice/stock/voices/chains.json) says which
ROLES a spoken atom invites to answer and with which reply atom. The voice
runner — the one throat every line passes through — composes an exchange one
hop at a time: opener -> reply -> counter-reply, rolling
first_hop_p * decay^(hop-1) at each hop, capped at max_hops, paced by a short
conversational gap, and dropped when the turn changes. No LLM anywhere.

Roles, resolved from what the runner already knows:
  target     the seat(s) the opener addressed (from the event: defenders, the
             countered spell's owner, the player hit)
  aggressor  the seat that caused the opener's grief (the attacker, the counterer)
  bystander  another voiced AI seat, not the speaker, not a target
  leader     the highest-life other voiced seat (for taunt / archenemy)
  origin     the chain's first speaker (hops >= 2 only)
  open       a defender with no untapped creature (the runner reads the board) — "no blocks"
Joshua sits OUTSIDE the game (Ben): he may needle a seat over what it did to
the human (joshua_replies, a stock quip), and the seats never answer him.
Nobody replies to themselves; nobody says the same line twice in a turn.

Pure functions here; the runner supplies state and does the enqueueing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class ChainTable:
    def __init__(self, data: dict):
        self.invites: dict[str, list[dict]] = data.get("invites") or {}
        # families (round 31): "hit-" -> the invites of kill-that apply to hit-urza, hit-mono-red, ...
        self.families: dict[str, str] = {k: v for k, v in (data.get("families") or {}).items() if k != "note"}
        self.joshua: dict[str, str] = {k: v for k, v in (data.get("joshua_replies") or {}).items() if k != "note" and v}
        env = os.environ.get
        self.first_hop_p = float(env("ARENA_BARKS_CHAIN_P", data.get("first_hop_p", 0.6)))
        self.decay = float(env("ARENA_BARKS_CHAIN_DECAY", data.get("decay", 0.5)))
        self.max_hops = int(env("ARENA_BARKS_CHAIN_MAX", data.get("max_hops", 3)))
        self.gap_s = float(env("ARENA_BARKS_CHAIN_GAP", data.get("gap_s", 3.5)))
        self.human_mult = float(env("ARENA_BARKS_CHAIN_HUMAN_P", data.get("human_trigger_mult", 0.5)))

    @classmethod
    def load(cls, voices_dir: Path) -> "ChainTable | None":
        try:
            return cls(json.loads((voices_dir / "chains.json").read_text()))
        except (OSError, ValueError, TypeError):
            return None

    def invites_for(self, opener: str) -> list[dict]:
        if opener in self.invites:
            return list(self.invites[opener])
        for prefix, generic in self.families.items():
            if opener.startswith(prefix):
                return list(self.invites.get(generic, []))
        return []

    def hop_p(self, hop: int, human_cause: bool = False) -> float:
        """Chance of the reply that would become hop `hop` (1 = the first reply)."""
        p = self.first_hop_p * (self.decay ** max(0, hop - 1))
        return p * self.human_mult if human_cause else p


def resolve_role(role: str, speaker: int, ctx: dict, chain: dict | None, voiced: dict, human_seat: int,
                 leader_of, rng) -> int | None:
    """The seat a role points at, or None. `voiced` maps seat -> library for
    the AI seats that can speak; the human seat is returned only for the
    target role (the caller turns that into a Joshua reply)."""
    targets = [int(t) for t in (ctx.get("targets") or [])]
    if role == "target":
        cands = [t for t in targets if t != speaker and (t in voiced or t == human_seat)]
        return rng.choice(cands) if cands else None
    if role == "aggressor":
        a = ctx.get("aggressor")
        return int(a) if a is not None and int(a) != speaker and int(a) in voiced else None
    if role == "open":
        # a defender with nothing untapped to block (the runner reads the board): "no blocks"
        cands = [int(t) for t in (ctx.get("open") or []) if int(t) != speaker and int(t) in voiced]
        return rng.choice(cands) if cands else None
    if role == "bystander":
        cands = [s for s in voiced if s != speaker and s not in targets]
        return rng.choice(cands) if cands else None
    if role == "leader":
        lead = leader_of(speaker)
        return lead if lead is not None and lead in voiced and lead != speaker else None
    if role == "origin":
        if not chain:
            return None
        o = chain.get("origin")
        return int(o) if o is not None and int(o) != speaker and int(o) in voiced else None
    return None


def plan_reply(table: ChainTable, spoken: dict, chain: dict | None, voiced: dict, human_seat: int,
               leader_of, said_this_turn: set, rng, turn, recent: set | None = None) -> dict | None:
    """What (if anything) answers the line just spoken. Returns a reply plan:
    {"seat": int | "joshua", "id": str, "hop": int, "origin": int, "p": float} or None.
    The caller rolls `p` itself so the decision is recorded either way."""
    if spoken.get("seat") is None:
        return None                           # Joshua spoke: the seats ignore him
    speaker = int(spoken["seat"])
    opener = spoken.get("stock") or ""
    hop = int((chain or {}).get("hop", 0)) + 1
    if hop > table.max_hops:
        return None
    origin = int((chain or {}).get("origin", speaker))
    ctx = spoken.get("ctx") or {}
    options = table.invites_for(opener)
    rng.shuffle(options)
    # a reply the answering seat used recently goes to the back of the line (soft; the per-turn rule is hard)
    recent = recent or set()
    if recent:
        fresh, stale = [], []
        for opt in options:
            who = resolve_role(opt.get("role", ""), speaker, ctx, chain, voiced, human_seat, leader_of, rng)
            (stale if who is not None and who != human_seat and (who, opt.get("reply", "")) in recent else fresh).append(opt)
        options = fresh + stale
    for opt in options:
        who = resolve_role(opt.get("role", ""), speaker, ctx, chain, voiced, human_seat, leader_of, rng)
        if who is None:
            continue
        if who == human_seat:
            jid = table.joshua.get(opener)
            if jid and hop == 1:              # Joshua comments once, from outside the game; no chain follows
                return {"seat": "joshua", "id": jid, "hop": hop, "origin": origin, "p": table.hop_p(hop, ctx.get("human_cause", False))}
            continue
        reply = opt.get("reply", "")
        if not reply or (who, reply) in said_this_turn:
            continue
        return {"seat": who, "id": reply, "hop": hop, "origin": origin, "p": table.hop_p(hop, bool(ctx.get("human_cause")))}
    return None
