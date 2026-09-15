"""The atoms and the under channel (voicework2 hardening plan 4.5, 2026-09-14).

Shipped assets: three atoms sub-libraries (harry, bill, lily), 24 ids each, four-plus
wordings each, every wording a baked take of at most 3.6 s, resolved by the Renderer as
"<lib>/atoms". Behaviour: AtomsMixin on a minimal runner double over a synthetic tree
with known durations, a FakePlayer that records both channels, a fake clock; the real
Player's under channel (argv per backend, the dry path, the kill with the main line).
Run: python3 -m unittest discover -s tests
"""
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER))
from voice import atoms as A  # noqa: E402
from voice import renderer as vr_renderer  # noqa: E402
from voice.atoms import AtomsMixin, atom_class  # noqa: E402

VOICES = RUNNER / "voice" / "stock" / "voices"
LIBS = ("harry", "bill", "lily")
ATOM_IDS = ("sigh", "hmm", "chuckle", "laugh", "gasp", "cough", "throat", "tsk", "exhale", "groan", "oof", "ooh",
            "hah", "mm-hm", "yeah", "no-way", "nice", "wow", "ugh", "hmph", "come-on", "oh-no", "right", "yikes")


def silent_wav(seconds: float, rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


# ---- the shipped libraries --------------------------------------------------------

class ShippedAtoms(unittest.TestCase):
    def test_three_atoms_manifests_24_ids_four_plus_wordings_each(self):
        for lib in LIBS:
            m = json.loads((VOICES / lib / "atoms" / "manifest.json").read_text())
            self.assertEqual((m["schema"], m["library"], m["parent"]), ("arena.voice-stock/1", f"{lib}/atoms", lib))
            ph = m["phrases"]
            self.assertEqual(len(ph), 24, lib)
            self.assertEqual(set(ph), set(ATOM_IDS), f"{lib}: the 24 atom ids")
            for pid, rec in ph.items():
                self.assertEqual(rec.get("category"), "atom", f"{lib}/{pid}")
                self.assertTrue(rec.get("when"), f"{lib}/{pid}: a 'when' hint")
                self.assertIsInstance(rec["text"], list, f"{lib}/{pid}")
                self.assertGreaterEqual(len(rec["text"]), 4, f"{lib}/{pid}: Ben — four alternates each at least")
                self.assertEqual(len(set(rec["text"])), len(rec["text"]), f"{lib}/{pid}: wordings differ")

    def test_every_wording_is_a_baked_take_of_at_most_3_6_s(self):
        n = 0
        for lib in LIBS:
            m = json.loads((VOICES / lib / "atoms" / "manifest.json").read_text())
            for pid, rec in m["phrases"].items():
                for i in range(1, len(rec["text"]) + 1):
                    f = VOICES / lib / "atoms" / (f"{pid}.wav" if i == 1 else f"{pid}-{i}.wav")
                    self.assertTrue(f.exists(), f"{lib}/atoms/{f.name} missing for {rec['text'][i - 1]!r}")
                    with wave.open(str(f)) as w:
                        self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 22050), f.name)
                        secs = w.getnframes() / w.getframerate()
                    self.assertTrue(0.1 <= secs <= 3.6, f"{lib}/atoms/{f.name}: {secs:.2f}s")
                    n += 1
        self.assertGreaterEqual(n, 3 * 24 * 4)

    def test_renderer_resolves_the_atoms_sub_library_like_the_table(self):
        with tempfile.TemporaryDirectory() as td:
            r = vr_renderer.Renderer(Path(td), log=lambda m: None, rng=random.Random(1))
            files = r.variants("gasp", "harry/atoms")
            self.assertGreaterEqual(len(files), 4)
            self.assertTrue(all(f.parent == VOICES / "harry" / "atoms" for f in files))
            self.assertEqual(files[0].name, "gasp.wav")
            picks = [r.stock("gasp", "harry/atoms") for _ in files]
            self.assertEqual(sorted(p.name for p in picks), sorted(f.name for f in files), "the shuffle bag: every wording once")
            self.assertEqual(r.variants("gasp", "harry"), [], "the parent library has no gasp: the sub-library is separate")


# ---- the mixin on a double ------------------------------------------------------------

class FakePlayer:
    def __init__(self):
        self.played, self.under, self.stops = [], [], 0
        self.busy = False        # under_playing()
        self.accept = True       # play_under's answer when not busy

    def play(self, path, should_stop=None):
        self.played.append(Path(path).name)

    def play_under(self, path, volume=0.5):
        if self.busy or not self.accept:
            return False
        self.under.append((Path(path).name, volume))
        return True

    def stop_under(self):
        self.stops += 1
        self.busy = False

    def under_playing(self):
        return self.busy


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Double(AtomsMixin):
    """The runner attributes the mixin reads, nothing else."""
    def __init__(self, cache: Path, clock, rng):
        self.rng, self.clock = rng, clock
        self.player = FakePlayer()
        self.renderer = vr_renderer.Renderer(cache, log=lambda m: None, clock=clock, rng=rng)
        self.seat_libraries = {1: {"library": "harry", "voice": "Harry"}, 2: {"library": "bill", "voice": "Bill"},
                               3: {"library": "lily", "voice": "Lily"}}
        self.eliminated = set()
        self.human_seat = 0
        self.final_locked = False
        self._last_snapshot = {}
        self.records, self.said = [], []

    def record(self, event, **body):
        self.records.append({"event": event, **body})

    def say(self, msg):
        self.said.append(msg)

    def lib_for(self, seat, pid):
        return self.seat_libraries[int(seat)]["library"]


def build_tree(base: Path) -> Path:
    """voices/<lib>/atoms with the 24 ids x 4 wordings at 0.3 s; "sigh" has a fifth,
    long wording (2.5 s) so the length filter has something to reject."""
    voices = base / "stock" / "voices"
    for lib in LIBS:
        d = voices / lib / "atoms"
        d.mkdir(parents=True)
        phrases = {}
        for pid in ATOM_IDS:
            n = 5 if pid == "sigh" else 4
            phrases[pid] = {"category": "atom", "when": "test", "text": [f"[tag] {pid} {i}" for i in range(1, n + 1)]}
            for i in range(1, n + 1):
                secs = 2.5 if (pid == "sigh" and i == 5) else 0.3
                (d / (f"{pid}.wav" if i == 1 else f"{pid}-{i}.wav")).write_bytes(silent_wav(secs))
        (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": f"{lib}/atoms", "phrases": phrases}))
    return voices


def stem_id(name: str) -> str:
    stem = name[:-4] if name.endswith(".wav") else name
    head, _, tail = stem.rpartition("-")
    return head if tail.isdigit() and head else stem


class _Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._voices = vr_renderer.VOICES_DIR
        vr_renderer.VOICES_DIR = build_tree(base)
        self._key = os.environ.pop("ELEVENLABS_API_KEY", None)
        self.clock = Clock()
        self.r = Double(base / "cache", self.clock, random.Random(11))

    def tearDown(self):
        self.r.stop_atoms()
        vr_renderer.VOICES_DIR = self._voices
        if self._key is not None:
            os.environ["ELEVENLABS_API_KEY"] = self._key
        self.tmp.cleanup()

    def item(self, stock, seat=1, kind="bark", targets=(), **extra):
        d = {"kind": kind, "text": "", "stock": stock, "seat": seat, "library": "x",
             "ctx": {"targets": list(targets)}, "source": "event", "chain": None}
        d.update(extra)
        return d

    def atoms_records(self):
        return [x for x in self.r.records if x.get("kind") == "atom"]


class Gates(_Tree):
    def test_dead_seat_human_seat_and_the_final_lock(self):
        self.assertTrue(self.r._may_atom(1))
        self.r.eliminated.add(2)
        self.assertFalse(self.r._may_atom(2))
        self.r.human_seat = 1
        self.assertFalse(self.r._may_atom(1), "the human has no voice library to murmur with")
        self.assertTrue(self.r._may_atom(3))
        self.assertFalse(self.r._may_atom(4), "an unseated number")
        self.r.final_locked = True
        self.assertFalse(self.r._may_atom(3))
        self.assertFalse(self.r.floor_atom([3]))
        self.assertFalse(self.r.react_atom("swing", [3], p=1.0))
        self.assertEqual(self.r.player.played + self.r.player.under, [])

    def test_never_under_advice_or_an_ask(self):
        for kind in ("advice", "ask"):
            self.assertFalse(self.r._may_atom(1, self.item("landed-hit", kind=kind, targets=[2])))
            self.assertIsNone(self.r.backchannel_for(self.item("landed-hit", kind=kind, targets=[2]), p=1.0))
        self.assertTrue(self.r._may_atom(1, self.item("landed-hit", targets=[2])))

    def test_one_atom_per_seat_per_six_seconds(self):
        self.assertTrue(self.r.floor_atom([1]))
        self.assertFalse(self.r._may_atom(1))
        self.clock.t += 3.0
        self.assertFalse(self.r.floor_atom([1]))
        self.clock.t += 3.0
        self.assertTrue(self.r.floor_atom([1]))
        self.assertEqual(len(self.r.player.played), 2)
        self.assertEqual([x["channel"] for x in self.atoms_records()], ["main", "main"])

    def test_never_two_atoms_at_once(self):
        self.r.player.busy = True                                  # an under-line is playing
        self.assertFalse(self.r._may_atom(1))
        self.assertFalse(self.r.react_atom("swing", [2, 3], p=1.0))
        self.assertFalse(self.r.floor_atom([1, 2, 3]))
        self.r.player.busy = False
        self.assertTrue(self.r._may_atom(1))
        # a backchannel armed but not yet fired counts as "playing"
        old = A.BACKCHANNEL_DELAY_S
        A.BACKCHANNEL_DELAY_S = (30.0, 30.0)
        try:
            self.r.rng.random = lambda: 0.0
            self.assertTrue(self.r.start_backchannel(self.item("landed-hit", seat=1, targets=[2])))
            self.assertFalse(self.r._may_atom(3), "a murmur is pending: no second atom")
            self.assertFalse(self.r.react_atom("kill", [3], p=1.0))
            self.r.stop_atoms()
            self.assertTrue(self.r._may_atom(3))
            self.assertEqual(self.r.player.stops, 1, "stop_atoms kills the under channel too")
            self.assertEqual(self.r.player.under, [], "the cancelled timer never played")
        finally:
            A.BACKCHANNEL_DELAY_S = old

    def test_a_floor_atom_on_the_main_channel_blocks_the_under_channel_while_it_plays(self):
        seen = []

        class Probe(FakePlayer):
            def play(inner, path, should_stop=None):
                seen.append(self.r._may_atom(2))                   # inside the blocking play: the main channel is busy
                super().play(path, should_stop)
        self.r.player = Probe()
        self.assertTrue(self.r.floor_atom([1]))
        self.assertEqual(seen, [False])
        self.assertTrue(self.r._may_atom(2), "and free again once it returned")


class Recency(_Tree):
    def test_no_same_wording_within_120_s(self):
        stems = [self.r.pick_atom(1, ["gasp"]).stem for _ in range(4)]
        self.assertEqual(len(set(stems)), 4, "four wordings, four different stems")
        self.assertIsNone(self.r.pick_atom(1, ["gasp"]), "every gasp wording used within 120 s")
        self.assertIsNotNone(self.r.pick_atom(2, ["gasp"]), "recency is per seat")
        self.clock.t += 121.0
        self.assertIsNotNone(self.r.pick_atom(1, ["gasp"]))

    def test_max_s_filters_the_long_wording(self):
        stems = {self.r.pick_atom(1, ["sigh"], max_s=A.UNDER_MAX_S).stem for _ in range(4)}
        self.assertEqual(len(stems), 4)
        self.assertNotIn("sigh-5", stems)
        self.assertIsNone(self.r.pick_atom(1, ["sigh"], max_s=A.UNDER_MAX_S), "the 2.5 s wording is never an under-line")
        self.assertEqual(self.r.pick_atom(1, ["sigh"]).stem, "sigh-5", "on the main channel it may play")

    def test_unknown_ids_and_an_unseated_seat_yield_none(self):
        self.assertIsNone(self.r.pick_atom(1, ["no-such-atom"]))
        self.assertIsNone(self.r.pick_atom(9, ["gasp"]))
        self.assertEqual(self.r.atom_ids("harry/atoms"), set(ATOM_IDS))
        self.assertEqual(self.r.atom_ids(), set(ATOM_IDS))


class Backchannel(_Tree):
    def test_the_map(self):
        cases = {"landed-hit": "hit", "big-swing": "hit", "sweep": "hit", "kill": "hit", "removal": "hit", "counter": "hit",
                 "attack-you": "hit", "taunt": "jab", "clapback": "jab", "you-suck": "jab", "low-life-jab": "jab",
                 "kill-that": "proposal", "youre-the-threat": "proposal", "archenemy": "proposal", "hit-selvala": "proposal",
                 "threat-urza": "proposal", "deal": "proposal", "deal-giada": "proposal",
                 "cast-big": "cast", "commander-cast": "cast", "engine-online": "cast", "game-changer": "cast", "gc-react": "cast",
                 "combo-dualcaster-online": "cast", "combo-dualcaster-react": "cast", "cmd-urza-cast": "cast", "cmd-urza-react": "cast",
                 "eliminated": "death", "player-eliminated": "death", "lost-commander": "death", "cmd-urza-dead": "death",
                 "nothing-happening": None, "this-is-fine": None, "your-move": None, "pass": None, "my-turn": None, "": None}
        for stock, cls in cases.items():
            self.assertEqual(atom_class(stock), cls, stock)
        for cls, (_ids, _prefixes, atoms) in A.ATOM_CLASSES.items():
            for a in atoms + A.PROPOSAL_TARGET_ATOMS + A.FLOOR_ATOMS:
                self.assertIn(a, ATOM_IDS, f"{cls}: {a} is not an atom id")
        for kind, atoms in A.REACT_ATOMS.items():
            for a in atoms:
                self.assertIn(a, ATOM_IDS, f"{kind}: {a}")
        self.assertEqual((A.BACKCHANNEL_P, A.UNDER_MAX_S, A.BACKCHANNEL_DELAY_S), (0.35, 1.6, (0.4, 0.8)))

    def test_a_hit_draws_the_target(self):
        for _ in range(6):
            seat, path, delay = self.r.backchannel_for(self.item("landed-hit", seat=1, targets=[2]), p=1.0)
            self.assertEqual(seat, 2)
            self.assertIn(stem_id(path.name), A.ATOM_CLASSES["hit"][2])
            self.assertTrue(0.4 <= delay <= 0.8)
            self.assertLessEqual(self.r.atom_seconds(path), A.UNDER_MAX_S)
            self.clock.t += 7.0
        seat, path, _ = self.r.backchannel_for(self.item("big-swing", seat=1, targets=[0]), p=1.0)
        self.assertIn(seat, (2, 3), "the human was hit: a voiced bystander winces instead")

    def test_a_jab_draws_a_bystander_not_the_target(self):
        for _ in range(6):
            seat, path, _ = self.r.backchannel_for(self.item("taunt", seat=1, targets=[2]), p=1.0)
            self.assertEqual(seat, 3, "the target may retort through the chains; the third seat laughs")
            self.assertIn(stem_id(path.name), A.ATOM_CLASSES["jab"][2])
            self.clock.t += 7.0

    def test_a_proposal_draws_another_seat_the_target_huffs(self):
        seen = set()
        for _ in range(12):
            seat, path, _ = self.r.backchannel_for(self.item("kill-that", seat=1, targets=[2]), p=1.0)
            seen.add(seat)
            self.assertIn(seat, (2, 3))
            self.assertIn(stem_id(path.name), ("hmph",) if seat == 2 else ("hmm", "mm-hm"))
            self.clock.t += 31.0                                   # past the seat gap AND, over four draws, the 120 s wording repeat
        self.assertEqual(seen, {2, 3})

    def test_a_spicy_cast_draws_a_bystander(self):
        for stock in ("commander-cast", "cast-big", "combo-dualcaster-online", "game-changer"):
            seat, path, _ = self.r.backchannel_for(self.item(stock, seat=2), p=1.0)
            self.assertIn(seat, (1, 3))
            self.assertIn(stem_id(path.name), A.ATOM_CLASSES["cast"][2])
            self.clock.t += 7.0

    def test_a_death_draws_the_others(self):
        self.r.eliminated.add(3)
        seat, path, _ = self.r.backchannel_for(self.item("eliminated", seat=3, kind="event"), p=1.0)
        self.assertIn(seat, (1, 2))
        self.assertIn(stem_id(path.name), A.ATOM_CLASSES["death"][2])
        self.clock.t += 7.0
        seat, path, _ = self.r.backchannel_for(self.item("player-eliminated", seat=None, kind="event", library=""), p=1.0)
        self.assertIn(seat, (1, 2), "Joshua's line: any living voiced seat")

    def test_plain_patter_and_unmapped_lines_draw_nothing(self):
        for stock in ("nothing-happening", "what-turn", "pass", "your-move", "calculating"):
            self.assertIsNone(self.r.backchannel_for(self.item(stock, seat=1), p=1.0), stock)
        self.assertIsNone(self.r.backchannel_for(self.item("landed-hit", seat=1, targets=[2]), p=0.0), "p=0: never")

    def test_the_probability_is_backchannel_p(self):
        self.r.rng.random = lambda: 0.34
        self.assertIsNotNone(self.r.backchannel_for(self.item("landed-hit", seat=1, targets=[2])))
        self.clock.t += 7.0
        self.r.rng.random = lambda: 0.36
        self.assertIsNone(self.r.backchannel_for(self.item("landed-hit", seat=1, targets=[2])))

    def test_no_atoms_library_means_no_roll_and_no_murmur(self):
        self.r.seat_libraries = {1: {"library": "nobody", "voice": "x"}, 2: {"library": "nobody", "voice": "x"}}
        rolls = []
        self.r.rng.random = lambda: rolls.append(1) or 0.0
        self.assertIsNone(self.r.backchannel_for(self.item("landed-hit", seat=1, targets=[2])))
        self.assertEqual(rolls, [], "the dice are not thrown when no seat has atoms")

    def test_a_player_without_an_under_channel_gets_no_backchannel(self):
        class OldPlayer:
            def play(self, path, should_stop=None):
                pass
        self.r.player = OldPlayer()
        self.assertIsNone(self.r.backchannel_for(self.item("landed-hit", seat=1, targets=[2]), p=1.0))
        self.assertFalse(self.r.react_atom("swing", [2], p=1.0))
        self.assertFalse(self.r.start_backchannel(self.item("landed-hit", seat=1, targets=[2])))
        self.r.stop_atoms()                                        # no stop_under either: still fine

    def test_the_timer_fires_under_the_line_and_records(self):
        old = A.BACKCHANNEL_DELAY_S
        A.BACKCHANNEL_DELAY_S = (0.01, 0.02)
        try:
            self.r.rng.random = lambda: 0.0
            self.assertTrue(self.r.start_backchannel(self.item("landed-hit", seat=1, targets=[2]), 2.0))
            t = self.r._atom_timer
            self.assertTrue(t.daemon)
            t.join(2.0)
            self.assertFalse(t.is_alive())
        finally:
            A.BACKCHANNEL_DELAY_S = old
        self.assertEqual(len(self.r.player.under), 1)
        name, volume = self.r.player.under[0]
        self.assertEqual(volume, A.UNDER_VOLUME)
        self.assertIn(stem_id(name), A.ATOM_CLASSES["hit"][2])
        recs = self.atoms_records()
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual((rec["event"], rec["kind"], rec["channel"], rec["seat"], rec["under"], rec["library"]),
                         ("spoke", "atom", "under", 2, "landed-hit", "bill/atoms"))
        self.assertEqual(rec["stock"], name[:-4])
        self.assertAlmostEqual(rec["seconds"], 0.3, places=1)
        self.assertEqual(self.r.said, [f"[voice] atom seat 2 {rec['stock']} (under)"])
        self.assertEqual(self.r.player.played, [], "nothing on the main channel")

    def test_a_line_too_short_to_sit_under_gets_no_murmur(self):
        self.r.rng.random = lambda: 0.0
        self.assertFalse(self.r.start_backchannel(self.item("landed-hit", seat=1, targets=[2]), 0.3))
        self.assertIsNone(self.r._atom_timer)

    def test_the_timer_is_silent_after_the_lock_or_a_death(self):
        old = A.BACKCHANNEL_DELAY_S
        A.BACKCHANNEL_DELAY_S = (0.05, 0.05)
        try:
            self.r.rng.random = lambda: 0.0
            self.assertTrue(self.r.start_backchannel(self.item("landed-hit", seat=1, targets=[2])))
            self.r.final_locked = True                             # the game ended during the line
            self.r._atom_timer.join(2.0)
            self.assertEqual(self.r.player.under, [])
            self.assertEqual(self.atoms_records(), [])
        finally:
            A.BACKCHANNEL_DELAY_S = old


class Floor(_Tree):
    def test_a_living_seat_plays_a_presence_atom_on_main(self):
        self.assertTrue(self.r.floor_atom([1, 2, 3]))
        self.assertEqual(len(self.r.player.played), 1)
        self.assertIn(stem_id(self.r.player.played[0]), A.FLOOR_ATOMS)
        self.assertEqual(self.r.player.under, [])
        rec = self.atoms_records()[0]
        self.assertEqual((rec["event"], rec["kind"], rec["channel"]), ("spoke", "atom", "main"))
        self.assertIn(rec["seat"], (1, 2, 3))
        self.assertNotIn("under", rec)
        self.assertEqual(self.r.said, [f"[voice] atom seat {rec['seat']} {rec['stock']} (main)"])

    def test_false_when_nobody_may(self):
        self.assertFalse(self.r.floor_atom([]))
        self.r.eliminated |= {1, 2}
        self.r.human_seat = 3
        self.assertFalse(self.r.floor_atom([1, 2, 3]))
        self.assertEqual(self.r.player.played, [])

    def test_uses_the_daemons_stop_polling_play_when_present(self):
        calls = []
        self.r._play = lambda path: calls.append(Path(path).name)
        self.assertTrue(self.r.floor_atom([2]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.r.player.played, [], "went through _play, not the bare player")

    def test_floor_never_touches_duty(self):
        self.r.floor_atom([1])
        self.r.react_atom("swing", [2], p=1.0)
        self.assertNotIn("_spoken_log", vars(self.r))
        self.assertNotIn("last_spoken_at", vars(self.r))


class React(_Tree):
    def test_p_and_actor_exclusion(self):
        self.assertFalse(self.r.react_atom("swing", [1, 2, 3], actor=1, p=0.0))
        self.assertEqual(self.r.player.under, [])
        for _ in range(8):
            self.assertTrue(self.r.react_atom("swing", [1, 2, 3], actor=1, p=1.0))
            name, volume = self.r.player.under[-1]
            self.assertEqual(volume, A.UNDER_VOLUME)
            self.assertIn(stem_id(name), A.REACT_ATOMS["swing"])
            self.assertNotEqual(self.atoms_records()[-1]["seat"], 1, "never the actor")
            self.assertEqual(self.atoms_records()[-1]["under"], "swing")
            self.clock.t += 7.0
        self.assertFalse(self.r.react_atom("swing", [1], actor=1, p=1.0), "only the actor listed: nobody to gasp")

    def test_the_default_probability_is_react_p(self):
        self.assertEqual(A.REACT_P, 0.5)
        self.r.rng.random = lambda: 0.49
        self.assertTrue(self.r.react_atom("kill", [2, 3], actor=1))
        self.clock.t += 7.0
        self.r.rng.random = lambda: 0.51
        self.assertFalse(self.r.react_atom("kill", [2, 3], actor=1))

    def test_each_kind_maps_to_its_atoms_and_unknown_kinds_do_nothing(self):
        for kind in ("swing", "kill", "sweep", "combo"):
            self.assertTrue(self.r.react_atom(kind, [2, 3], actor=1, p=1.0), kind)
            self.assertIn(stem_id(self.r.player.under[-1][0]), A.REACT_ATOMS[kind], kind)
            self.clock.t += 7.0
        self.assertFalse(self.r.react_atom("mulligan", [2, 3], p=1.0))
        self.assertEqual(len(self.r.player.under), 4)

    def test_a_refused_under_channel_plays_nothing_and_records_nothing(self):
        self.r.player.accept = False                               # e.g. aplay: no volume flag
        self.assertFalse(self.r.react_atom("swing", [2, 3], actor=1, p=1.0))
        self.assertEqual(self.atoms_records(), [])


# ---- the real Player's under channel ------------------------------------------------

class UnderChannel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wav = Path(self.tmp.name) / "atom.wav"
        self.wav.write_bytes(silent_wav(0.4))
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_argv_per_backend(self):
        p = vr_renderer.Player(dry_run=True, log=self.logs.append)
        p.windows = False
        p.cmd = ["afplay"]
        self.assertEqual(p._under_argv(self.wav, 0.5), ["afplay", "-v", "0.50", str(self.wav)])
        p.cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]
        self.assertEqual(p._under_argv(self.wav, 0.5), p.cmd + ["-volume", "50", str(self.wav)])
        p.cmd = ["paplay"]
        self.assertEqual(p._under_argv(self.wav, 0.5), ["paplay", "--volume=32768", str(self.wav)])
        self.assertEqual(p._under_argv(self.wav, 2.0)[1], "--volume=65536", "clamped")
        p.cmd = ["aplay", "-q"]
        self.assertIsNone(p._under_argv(self.wav, 0.5), "aplay has no volume flag")
        p.cmd = ["powershell", "-NoProfile", "-Command"]; p.windows = True
        self.assertIsNone(p._under_argv(self.wav, 0.5))
        p.cmd = None; p.windows = False
        self.assertIsNone(p._under_argv(self.wav, 0.5))

    def test_dry_run_logs_and_holds_the_channel_for_the_take(self):
        p = vr_renderer.Player(dry_run=True, log=self.logs.append)
        self.assertFalse(p.under_playing())
        self.assertTrue(p.play_under(self.wav))
        self.assertEqual(self.logs, ["[voice] (dry) under atom.wav 0.4s"])
        self.assertTrue(p.under_playing())
        self.assertFalse(p.play_under(self.wav), "one under-line at a time")
        p.stop_under()
        self.assertFalse(p.under_playing())
        self.assertTrue(p.play_under(self.wav))

    def test_a_backend_without_overlap_says_so_once(self):
        p = vr_renderer.Player(dry_run=True, log=self.logs.append)
        p.dry_run = False
        p.cmd, p.windows, p.winsound = ["aplay", "-q"], False, None
        self.assertFalse(p.play_under(self.wav))
        self.assertFalse(p.play_under(self.wav))
        self.assertEqual(len(self.logs), 1)
        self.assertIn("under channel off: aplay", self.logs[0])
        self.assertFalse(p.under_playing())

    @unittest.skipIf(sys.platform == "win32", "posix sleep")
    def test_the_main_channels_kill_takes_the_under_line_with_it(self):
        p = vr_renderer.Player(dry_run=True, log=self.logs.append)
        p.dry_run = False
        p.cmd, p.windows, p.winsound = ["sh", "-c", "exec sleep 5 #"], False, None   # argv + [path]: $0 is the path
        p._under = subprocess.Popen(["sleep", "5"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertTrue(p.under_playing())
        t0 = time.time()
        p.play(self.wav, should_stop=lambda: True)
        self.assertLess(time.time() - t0, 3.0)
        self.assertFalse(p.under_playing())
        self.assertIn("[voice] playback cut: voice disabled", self.logs)

    def test_two_threads_cannot_start_two_under_lines(self):
        p = vr_renderer.Player(dry_run=True, log=lambda m: None)
        results = []
        barrier = threading.Barrier(2)

        def go():
            barrier.wait()
            results.append(p.play_under(self.wav))
        ts = [threading.Thread(target=go) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(results), [False, True])


if __name__ == "__main__":
    unittest.main()


class Wiring(unittest.TestCase):
    """The critic's first finding (2026-09-14): the mixin existed and nothing called it."""

    def test_the_daemon_carries_the_mixin_and_the_hooks(self):
        import inspect
        import voice_runner as vr
        self.assertIn(AtomsMixin, vr.VoiceRunner.__mro__)
        src = inspect.getsource(vr.VoiceRunner.speak)
        self.assertLess(src.index("start_backchannel"), src.index("self._play(path)"), "the murmur is armed before the line starts")
        self.assertIn("stop_atoms", inspect.getsource(vr.VoiceRunner.step), "the mute kills a pending murmur")

    def test_a_timer_armed_before_a_mute_never_plays(self):
        import random, tempfile
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        d = Double(Path(tmp.name) / "cache", Clock(), random.Random(3)); d.enabled = lambda: False
        d._backchannel_fire(1, Path("x.wav"), "taunt")
        self.assertEqual(d.player.under, [], "muted since the timer was armed: silence")
