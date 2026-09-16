"""The atoms — AtomsMixin, mixed into VoiceRunner (runner/voice_runner.py) beside the
scheduler and the events (voicework2 hardening plan 4.5, 2026-09-14; Ben: "one of the
best suggestions ... they need variety, four alternates each at least").

An atom is a sub-second non-verbal take — a sigh, a gasp, a chuckle, an "mm-hm" — from
voices/<lib>/atoms/ (24 ids x four-plus wordings per voice, baked 3 dB under the table).
It is presence, not talk: never queued, never counted toward the duty budget, never a
line anyone answers. Three triggers:

  backchannel   a listener murmurs UNDER the main line (Player.play_under, half volume),
                0.4-0.8 s in: the target of a hit oofs, a bystander laughs at a jab,
                another seat hmms at a proposal, oohs at a spicy cast, winces at a death
  floor         the patter clock's pool is empty or filler-only: a living seat sighs or
                clears its throat on the MAIN channel instead of a content line
  reaction      a gasp at a big swing, a kill, a sweep or a combo, from a seat that is
                not the actor, on the under channel, no queue

Rules, all behind one gate (_may_atom): never after the final lock, never from an
eliminated seat or the human, never under advice or an ask, at most one atom per seat
per ATOM_SEAT_GAP_S, never two atoms at once (a pending backchannel, an under-line
playing, a floor atom on the main channel), and a seat never repeats a WORDING within
ATOM_REPEAT_S. Every play is recorded as {"event": "spoke", "kind": "atom",
"channel": "main"|"under", ...} so hygiene can count atoms per minute without mistaking
them for lines; nothing here touches _spoken_log or last_spoken_at.

The daemon owns every attribute this reads (rng, clock, player, renderer, seat_libraries,
eliminated, human_seat, final_locked, record, say); the mixin's own state is created
lazily on first use, so VoiceRunner.__init__ needs no change. This module never imports
voice_runner."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from voice import renderer as _renderer          # VOICES_DIR read at call time: tests swap the tree
from voice.renderer import wav_seconds

ATOMS_LIB = "atoms"                    # voices/<lib>/atoms/
BACKCHANNEL_P = 0.35                   # a mapped main line draws a murmur about one time in three
BACKCHANNEL_DELAY_S = (0.4, 0.8)       # how far into the main line the murmur lands
UNDER_MAX_S = 1.6                      # an under-line must sit under the line, not trail it
UNDER_VOLUME = 0.5                     # Player.play_under volume (afplay -v 0.5)
ATOM_SEAT_GAP_S = 6.0                  # one atom per seat per six seconds
ATOM_REPEAT_S = 120.0                  # a seat never repeats a wording (stem) within two minutes
REACT_P = 0.5                          # an instant reaction on the under channel
FLOOR_ATOMS = ("sigh", "hmm", "cough", "throat", "right", "exhale")
REACT_ATOMS = {"swing": ("gasp", "wow", "no-way"), "kill": ("gasp", "oh-no", "no-way"),
               "sweep": ("gasp", "oh-no", "no-way"), "combo": ("oh-no", "no-way", "wow")}
NO_ATOM_UNDER = ("advice", "ask")     # Joshua's advice and his answers are never talked under

# The backchannel map: the main line's stock id -> the class of murmur it invites, who gives
# it, and from which atoms. Ids come from voices/<lib>/manifest.json (barks, reactions,
# replies, patter), the table sub-library (procedural/arc/loop; hit-/threat-/deal-<who>) and
# the cards sub-library (cmd-<who>-cast|dead|react, combo-<key>-online|react, gc-*).
#   hit       the speaker hurt someone: the TARGET (else a bystander) oofs
#   jab       a needle or name-calling: a BYSTANDER (not the target, who may retort) laughs
#   proposal  "kill that", "hit Selvala", a deal: ANOTHER seat hmms along, the target hmphs
#   cast      a spicy cast, an engine, a combo, a game changer: a bystander oohs
#   death     an elimination, a lost commander: the others wince
ATOM_CLASSES: dict[str, tuple[frozenset, tuple[str, ...], tuple[str, ...]]] = {
    "hit": (frozenset({"landed-hit", "big-swing", "kill", "sweep", "removal", "counter", "attack-you", "poke",
                       "pile-on", "not-sorry"}),
            (), ("oof", "groan", "gasp", "ugh")),
    "jab": (frozenset({"taunt", "clapback", "bite-me", "scoff", "nerd", "you-suck", "you-cheat", "you-wish", "shut-it",
                       "thats-mean", "board-envy", "pass-already", "play-faster", "play-slower", "slow-turn", "thinking-hard",
                       "last-word", "low-life-jab", "empty-hand", "grudge", "you-promised", "im-not-the-threat", "laugh",
                       "mull-gloat", "you-broke-it", "i-broke-it"}),
            (), ("hah", "tsk", "chuckle", "laugh")),
    "proposal": (frozenset({"kill-that", "youre-the-threat", "archenemy", "someone-wins", "attack-them", "deal",
                            "take-the-deal", "no-deal", "deal-with-you", "no-deal-with-you", "counter-offer"}),
                 ("hit-", "threat-", "deal-"), ("hmm", "mm-hm")),
    "cast": (frozenset({"cast-big", "commander-cast", "engine-online", "game-changer", "big-mana", "looping", "loop",
                        "gc-react", "gc-gone", "nice-play", "respect", "wow", "oh-no", "read-that"}),
             ("combo-", "gc-"), ("ooh", "wow", "no-way", "nice")),
    "death": (frozenset({"eliminated", "player-eliminated", "lost-commander"}),
              (), ("oh-no", "yikes", "gasp")),
}
PROPOSAL_TARGET_ATOMS = ("hmph",)     # the seat a proposal is aimed at huffs instead of humming along


def atom_class(stock: str) -> str | None:
    """Which murmur a main line invites, or None for a line nobody talks under (filler,
    Joshua's quips, questions, procedural passes)."""
    s = (stock or "").strip()
    if not s:
        return None
    for cls, (ids, _prefixes, _atoms) in ATOM_CLASSES.items():
        if s in ids:
            return cls
    if s.startswith("cmd-"):
        return "death" if s.endswith("-dead") else "cast"
    for cls, (_ids, prefixes, _atoms) in ATOM_CLASSES.items():
        if any(s.startswith(p) for p in prefixes):
            return cls
    return None


class AtomsMixin:
    """The three atom triggers and their one gate; VoiceRunner supplies the state."""

    # -- lazy state: VoiceRunner.__init__ does not know this mixin
    def _atoms_init(self) -> None:
        d = self.__dict__
        if "_atom_used" in d:
            return
        d["_atom_used"] = {}           # (seat, stem) -> when this seat last used this wording
        d["_atom_seat_at"] = {}        # seat -> when its last atom was scheduled or played
        d["_atom_ids_cache"] = {}      # "harry/atoms" -> the ids its manifest lists
        d["_atom_secs"] = {}           # path -> seconds
        d["_atom_timer"] = None        # the pending backchannel, if any
        d["_atom_main_until"] = 0.0    # a floor atom is on the main channel until then

    # -- the library
    def _atoms_lib(self, seat) -> str:
        info = self.seat_libraries.get(int(seat)) or self.seat_libraries.get(str(seat))
        return f"{info['library']}/{ATOMS_LIB}" if info and info.get("library") else ""

    def atom_ids(self, library: str | None = None) -> set[str]:
        """The atom ids one library (e.g. "harry/atoms") or every seated voice carries;
        read once per library from its manifest."""
        self._atoms_init()
        libs = [library] if library else [self._atoms_lib(s) for s in self.seat_libraries]
        out: set[str] = set()
        for lib in libs:
            if not lib:
                continue
            ids = self._atom_ids_cache.get(lib)
            if ids is None:
                try:
                    ids = set(json.loads((_renderer.VOICES_DIR / lib / "manifest.json").read_text()).get("phrases") or {})
                except (OSError, ValueError, TypeError):
                    ids = set()
                self._atom_ids_cache[lib] = ids
            out |= ids
        return out

    def atom_seconds(self, path: Path) -> float:
        self._atoms_init()
        secs = self._atom_secs.get(path)
        if secs is None:
            secs = self._atom_secs[path] = wav_seconds(path)
        return secs

    def pick_atom(self, seat: int, ids, max_s: float | None = None) -> Path | None:
        """A random wording of a random id from `ids` that this seat has not used in the
        last ATOM_REPEAT_S, no longer than `max_s` when given. The id is drawn first so a
        five-wording id is not favoured over a four-wording one. The pick is marked used."""
        self._atoms_init()
        seat = int(seat)
        lib = self._atoms_lib(seat)
        if not lib:
            return None
        known = self.atom_ids(lib)
        now = self.clock()
        by_id: dict[str, list[Path]] = {}
        for pid in ids:
            if pid not in known:
                continue
            files = [f for f in self.renderer.variants(pid, lib)
                     if now - self._atom_used.get((seat, f.stem), -1e9) >= ATOM_REPEAT_S
                     and (max_s is None or self.atom_seconds(f) <= max_s)]
            if files:
                by_id[pid] = files
        if not by_id:
            return None
        pid = self.rng.choice(sorted(by_id))
        path = self.rng.choice(by_id[pid])
        self._atom_used[(seat, path.stem)] = now
        return path

    # -- the gate
    def _voiced_living(self) -> list[int]:
        return [int(s) for s in self.seat_libraries if int(s) not in self.eliminated and int(s) != self.human_seat]

    def _under_ok(self) -> bool:
        return callable(getattr(self.player, "play_under", None))

    def _may_atom(self, seat, item: dict | None = None) -> bool:
        """Every rule in one place: the lock, the dead and the human, advice and asks,
        one per seat per ATOM_SEAT_GAP_S, never two at once."""
        self._atoms_init()
        seat = int(seat)
        if self.final_locked or seat in self.eliminated or seat == self.human_seat or not self._atoms_lib(seat):
            return False
        if item is not None and item.get("kind") in NO_ATOM_UNDER:
            return False
        now = self.clock()
        if now - self._atom_seat_at.get(seat, -1e9) < ATOM_SEAT_GAP_S:
            return False
        if now < self._atom_main_until:                       # a floor atom is on the main channel
            return False
        t = self._atom_timer
        if t is not None and t.is_alive():                    # a backchannel is pending or playing
            return False
        under = getattr(self.player, "under_playing", None)
        if under is not None and under():
            return False
        return True

    def _atom_played(self, seat: int, path: Path, channel: str, under: str = "") -> None:
        self._atoms_init()
        now = self.clock()
        stem = path.stem
        self._atom_used[(int(seat), stem)] = now
        self._atom_seat_at[int(seat)] = now
        body = {"kind": "atom", "channel": channel, "seat": int(seat), "stock": stem,
                "seconds": round(self.atom_seconds(path), 2), "library": self._atoms_lib(seat)}
        if under:
            body["under"] = under
        self.record("spoke", **body)
        self.say(f"[voice] atom seat {int(seat)} {stem} ({channel})")

    # -- trigger 1: the backchannel under a main line
    def backchannel_for(self, item: dict, p: float | None = None, max_s: float | None = None) -> tuple[int, Path, float] | None:
        """Given the main item about to play, (listener seat, atom path, delay) or None:
        the class from the map, the listener by role (target / bystander / another seat),
        an atom of at most UNDER_MAX_S, at BACKCHANNEL_P."""
        if self.final_locked or item.get("kind") in NO_ATOM_UNDER or not self._under_ok():
            return None
        cls = atom_class(item.get("stock") or "")
        if cls is None or not self.atom_ids():
            return None
        if self.rng.random() >= (BACKCHANNEL_P if p is None else p):
            return None
        speaker = item.get("seat")
        speaker = int(speaker) if speaker is not None else None
        ctx = item.get("ctx") or {}
        targets = {int(t) for t in (ctx.get("targets") or []) if t is not None}
        living = [s for s in self._voiced_living() if s != speaker]
        hit_targets = [s for s in living if s in targets]
        bystanders = [s for s in living if s not in targets]
        if cls == "hit":
            pool = hit_targets or bystanders
        elif cls in ("jab", "cast"):
            pool = bystanders
        else:                                                  # proposal, death: anyone else at the table
            pool = living
        pool = [s for s in pool if self._may_atom(s, item)]
        if not pool:
            return None
        seat = self.rng.choice(pool)
        atoms = ATOM_CLASSES[cls][2]
        if cls == "proposal" and seat in targets:
            atoms = PROPOSAL_TARGET_ATOMS
        delay = self.rng.uniform(*BACKCHANNEL_DELAY_S)
        room = UNDER_MAX_S if max_s is None else min(UNDER_MAX_S, max_s)
        path = self.pick_atom(seat, atoms, max_s=room)
        if path is None:
            return None
        return seat, path, delay

    def start_backchannel(self, item: dict, seconds: float | None = None) -> bool:
        """Called just before the main playback starts: arm a daemon Timer that puts the
        murmur under the line. `seconds` (the main line's length, when known) skips lines
        too short to sit under. True when a murmur was armed."""
        self._atoms_init()
        if seconds is not None and seconds < BACKCHANNEL_DELAY_S[0] + 0.2:
            return False
        # the murmur ends with the line (+0.3 s of grace), never in the clear after it
        room = None if seconds is None else seconds - BACKCHANNEL_DELAY_S[0] + 0.3
        pick = self.backchannel_for(item, max_s=room)
        if pick is None:
            return False
        seat, path, delay = pick
        if seconds is not None:
            delay = min(delay, max(0.1, seconds - 0.2))
        self._atom_seat_at[seat] = self.clock()                # booked now, so the next line cannot double up this seat
        t = threading.Timer(delay, self._backchannel_fire, args=(seat, path, str(item.get("stock") or item.get("kind") or "")))
        t.daemon = True
        self._atom_timer = t
        t.start()
        return True

    def _backchannel_fire(self, seat: int, path: Path, under: str) -> None:
        try:
            enabled = getattr(self, "enabled", None)
            if self.final_locked or int(seat) in self.eliminated or (enabled is not None and not enabled()):
                return                                             # muted since the timer was armed (critic, 2026-09-14)
            if not self.player.play_under(path, UNDER_VOLUME):
                return
            self._atom_played(seat, path, "under", under=under)
        except Exception as e:  # noqa: BLE001 — a timer thread never takes the daemon down
            try:
                self.say(f"[voice] atom failed: {str(e)[:120]}")
            except Exception:  # noqa: BLE001
                pass

    def stop_atoms(self) -> None:
        """Cancel a pending backchannel and kill the under channel (mute, the final lock)."""
        self._atoms_init()
        t, self._atom_timer = self._atom_timer, None
        if t is not None:
            t.cancel()
        stop = getattr(self.player, "stop_under", None)
        if stop is not None:
            stop()

    # -- trigger 2: presence at the patter floor
    def floor_atom(self, living: list[int]) -> bool:
        """The pool is empty or filler-only: a living voiced seat sighs, hmms, coughs or
        squares up on the MAIN channel (blocking, like a line). True when one played."""
        self._atoms_init()
        seats = [int(s) for s in living if self._may_atom(s)]
        if not seats:
            return False
        self.rng.shuffle(seats)
        for seat in seats:
            path = self.pick_atom(seat, FLOOR_ATOMS)
            if path is None:
                continue
            now = self.clock()
            self._atom_seat_at[seat] = now
            self._atom_main_until = now + self.atom_seconds(path)
            try:
                play = getattr(self, "_play", None)            # the daemon's stop-polling play, when mixed in
                if play is not None:
                    play(path)
                else:
                    self.player.play(path)
            finally:
                self._atom_main_until = 0.0
            self._atom_played(seat, path, "main")
            return True
        return False

    # -- trigger 3: an instant reaction, no queue
    def react_atom(self, kind: str, seats: list[int], actor: int | None = None, p: float | None = None) -> bool:
        """A gasp on the under channel at a big swing, a kill, a sweep or a combo, from one
        of `seats` that is not the actor, at REACT_P. True when it played."""
        self._atoms_init()
        atoms = REACT_ATOMS.get(kind)
        if atoms is None or not self._under_ok():
            return False
        pool = [int(s) for s in seats if (actor is None or int(s) != int(actor)) and self._may_atom(s)]
        if not pool:
            return False
        if self.rng.random() >= (REACT_P if p is None else p):
            return False
        seat = self.rng.choice(pool)
        path = self.pick_atom(seat, atoms, max_s=UNDER_MAX_S)
        if path is None or not self.player.play_under(path, UNDER_VOLUME):
            return False
        self._atom_played(seat, path, "under", under=kind)
        return True
