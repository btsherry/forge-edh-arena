"""Seat barks at run time (experimental/voicework2, 2026-09-10) — the table-talk
design: every turn boundary has one owner (an AI seat's recap -> that seat's
retrospective line; the human's recap -> Joshua's colour line plus at most one
seat's reaction); instant reactions come from the snapshot's public event ring
(attack / damage / countered) with no LLM; openers at a seat's turn start are
rare; a (seat, line) is never said twice in one turn; every bark rolls one
dice (ARENA_BARKS_P) behind a short per-seat guard; mute or advisor pause
drops everything. Several wordings of a line play from a shuffle bag. An AI
seat's elimination is voiced once, by the seat itself 70 % of the time.

Everything here runs against a synthetic stock tree so it never depends on the
rendered libraries. Run: python3 -m unittest discover -s tests
"""
import io
import json
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402

LINES = ("big-swing", "eliminated", "my-turn", "that-hurt", "landed-hit", "counter", "got-countered", "slow-turn", "respect")


def silent_wav(seconds: float = 0.2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\x00\x00" * int(22050 * seconds))
    return buf.getvalue()


class FakePlayer:
    def __init__(self):
        self.played = []

    def play(self, path, should_stop=None):
        self.played.append(Path(path).name)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


REPLIES = ("agree", "disagree", "scoff", "clapback", "brace", "pile-on", "sympathy", "laugh", "last-word", "gg")
REAL_CHAINS = Path(__file__).resolve().parents[1] / "voice" / "stock" / "voices" / "chains.json"


def build_tree(base: Path, chains: bool = False):
    """A synthetic stock tree: Joshua with four "your move" wordings and the quips
    the chain table names, two seat libraries (seat 3 has none), optionally the
    REAL chains.json so the tests exercise the shipped table."""
    stock = base / "stock"; voices = stock / "voices"
    (stock / "sfx").mkdir(parents=True)
    (stock / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "phrases": {
        "your-move": {"text": ["Your move.", "b", "c", "d"]}, "player-eliminated": {"text": "x"}, "startup": {"text": "s"}}, "sfx": []}))
    for n in ("your-move", "your-move-2", "your-move-3", "your-move-4", "player-eliminated", "startup", "your-move-creep",
              "rough-counter", "ouch", "calm-before-engagement", "harsh-player"):
        (stock / f"{n}.wav").write_bytes(silent_wav())
    for lib, seat, name in (("harry", 1, "Harry - Fierce Warrior"), ("bill", 2, "Bill - Wise, Mature, Balanced")):
        d = voices / lib; d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": lib, "seat": seat,
                                                     "voice_name": name, "temperament": f"{lib} temper", "phrases": {}}))
        for n in LINES + REPLIES + ("big-swing-2", "big-swing-3", "big-swing-4"):
            (d / f"{n}.wav").write_bytes(silent_wav())
    if chains:
        (voices / "chains.json").write_text(REAL_CHAINS.read_text())
    return stock, voices


class _TreeCase(unittest.TestCase):
    CHAINS = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.logs, self.mailbox = base / "logs", base / "mailbox"
        self.logs.mkdir(); self.mailbox.mkdir()
        stock, voices = build_tree(base, chains=self.CHAINS)
        self._stock, self._voices = vr.STOCK, vr.VOICES_DIR
        vr.STOCK, vr.VOICES_DIR = stock, voices
        self._env = dict(os.environ)
        os.environ.pop("ELEVENLABS_API_KEY", None)
        for k, v in {"ARENA_VOICE_MIN_GAP": "8", "ARENA_VOICE_SFX": "off", "ARENA_VOICE_FX": "off",
                     "ARENA_BARKS": "all", "ARENA_BARKS_COOLDOWN": "10", "ARENA_VOICE_YOUR_MOVE": "on",
                     "ARENA_BARKS_OPENER_P": "0"}.items():
            os.environ[k] = v
        self.clock = Clock()
        self.player = FakePlayer()
        self.r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)

    def tearDown(self):
        vr.STOCK, vr.VOICES_DIR = self._stock, self._voices
        os.environ.clear(); os.environ.update(self._env)
        self.tmp.cleanup()

    # ---- helpers
    def _advisor(self, **rec):
        if "with_" in rec:
            rec["with"] = rec.pop("with_")
        with (self.logs / "advisor-0.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, **rec}) + "\n")

    def _observer(self, turn, active, game_over=False, elim=(), events=()):
        seats = [{"seat": i, "name": f"s{i}", "eliminated": i in elim, "life": 40} for i in range(4)]
        (self.mailbox / "observer-state.json").write_text(json.dumps(
            {"turn": turn, "activeSeat": active, "gameOver": game_over, "seats": seats, "events": list(events)}))

    def _records(self, event=None, kind=None):
        out = []
        f = self.logs / "voice-0.jsonl"
        for l in (f.read_text().splitlines() if f.exists() else []):
            r = json.loads(l)
            if (event is None or r.get("event") == event) and (kind is None or r.get("kind") == kind):
                out.append(r)
        return out

    def _step(self, n=1, dt=9.0):
        for _ in range(n):
            self.clock.t += dt
            self.r.step()

    def _queued(self):
        return [(q["kind"], q["stock"], q.get("library") or "", q.get("seat")) for q in self.r.queue]



class BarkRuntime(_TreeCase):
    # ---- libraries + shuffle bag
    def test_seat_libraries_are_read_from_the_manifests(self):
        self.assertEqual({k: v["library"] for k, v in self.r.seat_libraries.items()}, {1: "harry", 2: "bill"})
        self.assertEqual(self.r.seat_libraries[1]["voice"], "Harry")
        self.assertEqual(self.r.library_for_seat(3), "", "no library, no bark")
        self.assertEqual(vr.load_seat_libraries(Path(self.tmp.name) / "nowhere"), {})

    def test_voices_follow_the_decks_with_seat_order_as_fallback(self):
        libs = vr.load_libraries()
        self.assertEqual(sorted(libs), ["bill", "harry"])
        prefs = {"purphoros-god-of-the-forge": "harry", "urza-lord-high-artificer": "bill", "giada-font-of-hope": "lily"}
        # Purphoros in seat 2 takes Harry; Urza in seat 1 takes Bill — the seat numbers no longer decide
        got = vr.assign_voices(libs, {1: "urza-lord-high-artificer", 2: "purphoros-god-of-the-forge", 3: "selvala-heart-of-the-wilds"}, prefs)
        self.assertEqual({k: v["library"] for k, v in got.items()}, {1: "bill", 2: "harry"}, "Lily has no library here; Selvala gets nothing")
        # an unlisted deck takes a free library in seat order
        got = vr.assign_voices(libs, {1: "sheoldreds-sacrifice", 2: "purphoros-god-of-the-forge", 3: "sythis-harvests-hand"}, prefs)
        self.assertEqual({k: v["library"] for k, v in got.items()}, {2: "harry", 1: "bill"})
        # no table knowledge: default seats
        self.assertEqual({k: v["library"] for k, v in vr.assign_voices(libs, None, prefs).items()}, {1: "harry", 2: "bill"})
        # a clash: two decks wanting Harry — the lower seat keeps it, the other takes what is free
        got = vr.assign_voices(libs, {1: "purphoros-god-of-the-forge", 2: "purphoros-god-of-the-forge"}, prefs)
        self.assertEqual({k: v["library"] for k, v in got.items()}, {1: "harry", 2: "bill"})
        self.assertEqual(vr.assign_voices({}, {1: "x"}, prefs), {})

    def test_the_runner_learns_the_table_from_the_game_log_and_reseats_the_voices(self):
        (self.logs / "game.jsonl").write_text("\n".join(json.dumps(r) for r in (
            {"seat": 1, "deck": "giada-font-of-hope", "type": "MULLIGAN"},
            {"seat": 2, "deck": "purphoros-god-of-the-forge", "type": "MULLIGAN"},
            {"seat": 3, "deck": "urza-lord-high-artificer", "type": "MULLIGAN"},
            {"seat": 0, "deck": "selvala-heart-of-the-wilds", "type": "MULLIGAN"})) + "\n")
        (Path(vr.VOICES_DIR) / "assign.json").write_text(json.dumps({"by_deck": {"purphoros-god-of-the-forge": "harry", "urza-lord-high-artificer": "bill", "giada-font-of-hope": "lily"}}))
        self.assertEqual({k: v["library"] for k, v in self.r.seat_libraries.items()}, {1: "harry", 2: "bill"}, "before the log: default seats")
        (self.logs / "game-partial.jsonl").write_text(json.dumps({"seat": 2, "deck": "purphoros-god-of-the-forge"}) + "\n")
        partial = vr.seat_decks_from_game_log(self.logs / "game-partial.jsonl")
        self.assertEqual(len(partial), 1, "one deck known is not a table")
        self.r.learn_table()
        self.assertEqual(vr.seat_decks_from_game_log(self.logs / "game.jsonl")[2], "purphoros-god-of-the-forge")
        self.assertEqual({k: v["library"] for k, v in self.r.seat_libraries.items()}, {2: "harry", 3: "bill"},
                         "Purphoros (seat 2) is Harry, Urza (seat 3) is Bill; Giada would be Lily but this tree has no Lily")
        self.assertEqual(self.r.library_for_seat(1), "", "Giada's seat has no voice in this tree")

    def test_shuffle_bag_plays_every_wording_before_repeating_and_never_twice_running(self):
        picks = [self.r.renderer.stock("your-move").name for _ in range(12)]
        for i in range(0, 12, 4):
            self.assertEqual(sorted(picks[i:i + 4]), ["your-move-2.wav", "your-move-3.wav", "your-move-4.wav", "your-move.wav"], picks)
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])), picks)
        self.assertNotIn("your-move-creep.wav", picks, "a different phrase, never a wording of your-move")
        self.assertEqual(self.r.renderer.stock("player-eliminated").name, "player-eliminated.wav")
        seat_picks = {self.r.renderer.stock("big-swing", "harry").name for _ in range(4)}
        self.assertEqual(len(seat_picks), 4, seat_picks)

    # ---- the advisor's recap: owner by turn
    def test_recap_bark_plays_the_seats_own_library_and_records_who_spoke(self):
        self._advisor(kind="bark", seat=1, id="slow-turn", turn=4, with_="color")
        self._step()
        self.assertEqual(self.player.played, ["slow-turn.wav"])
        spoke = self._records("spoke")[0]
        self.assertEqual((spoke["kind"], spoke["library"], spoke["seat"], spoke["file"]), ("bark", "harry", 1, "slow-turn.wav"))
        self.assertEqual(self._records("queued", "bark")[0]["source"], "recap")

    def test_colour_belongs_to_joshua_only_after_the_humans_turn(self):
        self.r.color_mode = "all"
        self._advisor(kind="color", seq=1, turn=5, owner=1, text="Urza had a turn.")
        self._advisor(kind="color", seq=2, turn=6, owner=0, text="You had a turn.")
        self._advisor(kind="color", seq=3, turn=7, owner=3, text="Seat 3 has no voice library.")
        self._advisor(kind="color", seq=4, turn=8, text="An old record without an owner.")
        self.r.scan_advisor()
        texts = [q["text"] for q in self.r.queue]
        self.assertNotIn("Urza had a turn.", texts, "seat 1's turn is seat 1's line, not Joshua's")
        self.assertEqual(texts, ["An old record without an owner."], "one pending colour line: newest wins")
        skipped = [r["why"] for r in self._records("skipped", "color")]
        self.assertEqual(len(skipped), 1); self.assertIn("seat 1's turn", skipped[0])
        # a seat without a voice cannot speak for itself, so Joshua does; with barks off Joshua comments on every turn
        self.r.queue.clear()
        self._advisor(kind="color", seq=5, turn=9, owner=3, text="Seat 3 again.")
        self.r.scan_advisor()
        self.assertEqual([q["text"] for q in self.r.queue], ["Seat 3 again."])
        self.r.queue.clear(); self.r.barks_mode = "off"
        self._advisor(kind="color", seq=6, turn=10, owner=2, text="Barks off.")
        self.r.scan_advisor()
        self.assertEqual([q["text"] for q in self.r.queue], ["Barks off."])

    def test_one_dice_a_short_guard_and_never_the_same_line_twice_in_a_turn(self):
        self.r.barks_mode = "some"; self.r.barks_p = 0.85
        self.r.rng.random = lambda: 0.9
        self.assertFalse(self.r.maybe_bark(1, "big-swing", turn=3, source="recap"))
        self.assertIn("dice (recap, p=0.85)", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.1
        self.assertTrue(self.r.maybe_bark(1, "big-swing", turn=3, source="event"))
        self.assertFalse(self.r.maybe_bark(1, "big-swing", turn=3, source="recap"), "the same line twice in one turn is a repeat")
        self.assertIn("already said this turn", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(self.r.maybe_bark(1, "that-hurt", turn=3, source="event"), "a different line is fine")
        self._step()                                                            # spoken -> the 10 s guard
        self.assertFalse(self.r.maybe_bark(1, "counter", turn=3, source="event"))
        self.assertIn("seat guard", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(self.r.maybe_bark(2, "counter", turn=3, source="event"), "another seat is not guarded")
        self.clock.t += 11
        self.assertTrue(self.r.maybe_bark(1, "big-swing", turn=4, source="recap"), "a new turn forgets what was said")
        self.assertFalse(self.r.maybe_bark(3, "big-swing", turn=4))
        self.assertIn("no voice library", self._records("skipped", "bark")[-1]["why"])
        self.r.barks_mode = "off"
        self.assertFalse(self.r.maybe_bark(1, "big-swing", turn=5))
        self.assertIn("barks off", self._records("skipped", "bark")[-1]["why"])

    def test_barks_sort_last_behind_your_move_and_a_pending_bark_is_replaced_by_the_newest(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4, with_="color")
        self._advisor(kind="bark", seat=2, id="counter", turn=4, with_="advice")
        self.r.scan_advisor()
        self._observer(5, 0); self.r.seen_turn, self.r.seen_active = 4, 3
        self.r.scan_observer()                      # "your move" queued after the barks
        kinds = [q["kind"] for q in self.r.queue]
        self.assertEqual(kinds.count("bark"), 1, "newest bark replaces the pending one")
        self.assertEqual([q for q in self.r.queue if q["kind"] == "bark"][0]["seat"], 2)
        self._step()
        self.assertTrue(self.player.played[0].startswith("your-move"), "your move outranks a bark")
        self._step(dt=8.5)
        self.assertEqual(self.player.played[1], "counter.wav")

    def test_bleeps_precede_joshua_only_never_a_seat_voice(self):
        (Path(vr.STOCK) / "sfx" / "typing-01.wav").write_bytes(silent_wav())
        self.r.renderer.manifest["sfx"] = ["typing-01.wav"]
        self.r.sfx_on = True
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self._step()
        self.assertEqual(len(self.player.played), 1, self.player.played)
        self.assertTrue(self.player.played[0].startswith("big-swing"), "a bark plays bare — no typing bleep")
        self._observer(5, 0); self.r.seen_turn, self.r.seen_active = 4, 3; self.r.scan_observer()
        self._step()
        self.assertEqual(self.player.played[1], "typing-01.wav", "Joshua's lines keep their bleep")
        self.assertTrue(self.player.played[2].startswith("your-move"))

    def test_mute_or_advisor_pause_drops_a_queued_bark(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self.r.scan_advisor()
        self.assertEqual(len(self.r.queue), 1)
        (self.logs / "control").mkdir()
        (self.logs / "control" / "voice.json").write_text(json.dumps({"enabled": False}))
        self._step()
        self.assertEqual(self.r.queue, []); self.assertEqual(self.player.played, [])

    # ---- instant reactions from the snapshot's event ring
    def _prime(self):
        """First snapshot read: the runner learns the current event seq and never replays history."""
        self._observer(3, 1, events=[{"seq": 1, "kind": "attack", "turn": 2, "seat": 1, "attackers": 5, "power": 30, "defenders": [0]}])
        self.r.scan_observer(); self.r.queue.clear()
        self.assertEqual(self.r._event_seq, 1)
        self.assertEqual(self._records("queued", "bark"), [], "history is not replayed on a (re)start")

    def test_attack_event_fires_big_swing_above_the_thresholds(self):
        self._prime()
        ev = [{"seq": 2, "kind": "attack", "turn": 3, "seat": 1, "attackers": 1, "power": 3, "defenders": [0]},
              {"seq": 3, "kind": "attack", "turn": 3, "seat": 2, "attackers": 1, "power": 6, "defenders": [0]}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "big-swing", "bill", 2)], "3 power is a poke; 6 power is a swing")
        self.r.queue.clear()
        ev.append({"seq": 4, "kind": "attack", "turn": 3, "seat": 1, "attackers": 3, "power": 3, "defenders": [2]})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "big-swing", "harry", 1)], "three attackers count too")
        self.r.queue.clear()
        ev.append({"seq": 5, "kind": "attack", "turn": 4, "seat": 0, "attackers": 4, "power": 20, "defenders": [1]})
        self._observer(4, 0, events=ev); self.r.scan_observer()
        self.assertEqual([q for q in self._queued() if q[0] == "bark"], [], "the human's attack is not a bark")

    def test_damage_event_the_victim_speaks_or_the_hitter_when_the_victim_is_the_human(self):
        self._prime()
        ev = [{"seq": 2, "kind": "damage", "turn": 3, "seat": 2, "amount": 7, "combat": True, "from": [1]},
              {"seq": 3, "kind": "damage", "turn": 3, "seat": 2, "amount": 8, "combat": True, "from": [1]}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "that-hurt", "bill", 2)], "7 is not a big hit; 8 is, and the victim speaks")
        self.r.queue.clear()
        ev.append({"seq": 4, "kind": "damage", "turn": 3, "seat": 0, "amount": 12, "combat": True, "from": [1]})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "landed-hit", "harry", 1)], "the human took it: the hitter gloats")
        self.r.queue.clear()
        ev.append({"seq": 5, "kind": "damage", "turn": 3, "seat": 0, "amount": 12, "combat": False, "from": [3]})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "seat 3 has no voice; nobody speaks")

    def test_countered_event_the_counterer_speaks_else_the_victim(self):
        self._prime()
        ev = [{"seq": 2, "kind": "countered", "turn": 3, "seat": 0, "by": 2, "spell": "Beast Within"}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "counter", "bill", 2)])
        self.r.queue.clear()
        ev.append({"seq": 3, "kind": "countered", "turn": 3, "seat": 1, "by": 0, "spell": "Thopter Foundry"})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "got-countered", "harry", 1)], "the human countered: the victim grumbles")
        self.r.queue.clear()
        ev.append({"seq": 4, "kind": "countered", "turn": 3, "seat": 2, "by": None, "spell": "Sol Ring"})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "got-countered", "bill", 2)], "unknown counterer: still the victim")
        self.r.queue.clear()
        ev.append({"seq": 5, "kind": "countered", "turn": 3, "seat": 1, "by": 0, "spell": "Sol Ring"})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "seat 1 already grumbled this turn — no repeat")

    def test_opener_fires_at_a_seats_turn_start_at_its_own_probability(self):
        self.r.barks_opener_p = 0.35
        self._observer(3, 0); self.r.scan_observer(); self._step()          # startup, seen turn set
        self.r.rng.random = lambda: 0.9
        self._observer(4, 1); self.r.scan_observer()
        self.assertEqual(self._queued(), [])
        self.assertIn("dice (opener, p=0.35)", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.1
        self._observer(5, 2); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "my-turn", "bill", 2)])
        self.r.queue.clear(); self.r.barks_opener_p = 0
        self._observer(6, 1); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "opener_p 0 = never")

    # ---- elimination: the seat itself or Joshua, one line, at once
    def test_ai_elimination_is_voiced_once_by_the_seat_or_by_joshua(self):
        self._observer(3, 1); self.r.scan_observer()          # startup line
        self._step()
        self.r.rng.random = lambda: 0.1                        # < ELIM_SEAT_P -> the seat speaks
        self._observer(4, 2, elim=(1,)); self.r.scan_observer()
        self.assertEqual([(q["kind"], q["stock"], q["library"]) for q in self.r.queue], [("event", "eliminated", "harry")])
        self._step()
        self.assertEqual(self.player.played[-1], "eliminated.wav")
        self.r.rng.random = lambda: 0.9                        # >= ELIM_SEAT_P -> Joshua
        self._observer(5, 3, elim=(1, 2)); self.r.scan_observer()
        self.assertEqual([(q["kind"], q["stock"], q["library"]) for q in self.r.queue], [("event", "player-eliminated", "")])
        self.r.rng.random = lambda: 0.1
        self._observer(6, 0, elim=(1, 2, 3)); self.r.scan_observer()
        self.assertEqual([q["stock"] for q in self.r.queue if q["kind"] == "event"], ["player-eliminated"], "seat 3 has no voice")
        self.r.queue.clear(); self.r.barks_mode = "off"; self.r.eliminated.clear()
        self._observer(7, 0, elim=(1,)); self.r.scan_observer()
        self.assertEqual([q["stock"] for q in self.r.queue if q["kind"] == "event"], ["player-eliminated"])

    # ---- your move: on | some | off
    def test_your_move_modes(self):
        self._observer(3, 1); self.r.scan_observer(); self._step()
        self.r.your_move_mode = "some"; self.r.your_move_p = 0.6
        self.r.rng.random = lambda: 0.9
        self._observer(4, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue, [])
        self.assertIn("dice", self._records("skipped", "your_move")[-1]["why"])
        self.r.rng.random = lambda: 0.1
        self._observer(8, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue[-1]["kind"], "your_move")
        self.r.queue.clear(); self.r.your_move_mode = "off"
        self._observer(12, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue, [])
        self.r.your_move_mode = "on"; self.r.rng.random = lambda: 0.99
        self._observer(16, 0); self.r.scan_observer()
        self.assertEqual(self.r.queue[-1]["kind"], "your_move")

    def test_defaults_from_the_environment(self):
        for k in ("ARENA_BARKS", "ARENA_VOICE_YOUR_MOVE", "ARENA_BARKS_P", "ARENA_BARKS_COOLDOWN", "ARENA_VOICE_YOUR_MOVE_P",
                  "ARENA_BARKS_OPENER_P", "ARENA_BARKS_SWING", "ARENA_BARKS_HIT"):
            os.environ.pop(k, None)
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_mode, r.barks_p, r.barks_cooldown, r.barks_opener_p, r.barks_swing, r.barks_hit),
                         ("some", 0.85, 10.0, 0.35, 6, 8))
        self.assertEqual((r.your_move_mode, r.your_move_p), ("some", 0.6))
        os.environ["ARENA_BARKS"] = "bogus"; os.environ["ARENA_VOICE_YOUR_MOVE"] = "bogus"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_mode, r.your_move_mode), ("some", "some"))


class InteractionChains(_TreeCase):
    """chains.py + the shipped chains.json: a spoken line invites a reply from a
    role; hops decay and cap; the conversational gap is shorter; the turn ends
    an exchange; Joshua comments from outside and is never answered."""
    CHAINS = True

    def _spoken(self, seat, pid, ctx=None, chain=None):
        lib = self.r.library_for_seat(seat)
        item = {"kind": "bark", "stock": pid, "text": "", "seat": seat, "library": lib, "ctx": ctx or {}, "chain": chain}
        self.r._roll_turn(3)
        self.r.after_spoken(item)

    def test_table_loaded_and_the_banner_says_so(self):
        self.assertIsNotNone(self.r.chains)
        self.assertEqual((self.r.chains.first_hop_p, self.r.chains.decay, self.r.chains.max_hops, self.r.chains.gap_s), (0.6, 0.5, 3, 1.5))
        # the BarkRuntime tree has no chains.json: chains off, nothing else changes
        self.assertIsNone(vr.ChainTable.load(Path(self.tmp.name) / "nowhere"))

    def test_attack_then_brace_then_laugh_then_clapback_then_silence(self):
        self._observer(3, 1); self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.random = lambda: 0.01                                    # every roll succeeds
        self.r.rng.shuffle = lambda x: None                                  # table order: target first
        self._spoken(1, "big-swing", ctx={"targets": [2], "aggressor": None})
        self.assertEqual(self._queued(), [("bark", "brace", "bill", 2)], "the defender braces")
        hop1 = self.r.queue[0]
        self.assertEqual((hop1["gap"], hop1["chain"]["hop"], hop1["chain"]["origin"]), (1.5, 1, 1))
        self.r.queue.clear()
        self._spoken(2, "brace", ctx=hop1["ctx"], chain=hop1["chain"])
        self.assertEqual(self._queued(), [("bark", "laugh", "harry", 1)], "the attacker laughs it off")
        hop2 = self.r.queue[0]; self.assertEqual(hop2["chain"]["hop"], 2); self.r.queue.clear()
        self._spoken(1, "laugh", ctx=hop2["ctx"], chain=hop2["chain"])
        self.assertEqual(self._queued(), [("bark", "clapback", "bill", 2)], "the target claps back")
        hop3 = self.r.queue[0]; self.assertEqual(hop3["chain"]["hop"], 3); self.r.queue.clear()
        self._spoken(2, "clapback", ctx=hop3["ctx"], chain=hop3["chain"])
        self.assertEqual(self._queued(), [], "max_hops reached: the exchange is over")
        srcs = [r for r in self._records("queued", "bark") if r.get("source") == "chain"]
        self.assertEqual([r["hop"] for r in srcs], [1, 2, 3]); self.assertEqual(srcs[0]["parent"], "big-swing")

    def test_dice_and_decay_are_recorded_and_a_new_turn_ends_the_exchange(self):
        self._observer(3, 1); self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.shuffle = lambda x: None
        self.r.rng.random = lambda: 0.7                                     # >= 0.6: no reply
        self._spoken(1, "big-swing", ctx={"targets": [2]})
        self.assertEqual(self._queued(), [])
        self.assertIn("dice (chain hop 1, p=0.60)", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.4                                     # < 0.6 but >= 0.3 (hop 2)
        self._spoken(1, "big-swing", ctx={"targets": [2]})
        link = self.r.queue[0]["chain"]; self.r.queue.clear()
        self._spoken(2, "brace", ctx={"targets": [1]}, chain=link)
        self.assertEqual(self._queued(), []); self.assertIn("p=0.30", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.01
        self.r._roll_turn(4)                                                # new turn: 'brace' may be said again
        self.r.after_spoken({"kind": "bark", "stock": "big-swing", "text": "", "seat": 1, "library": "harry", "ctx": {"targets": [2]}, "chain": None})
        self.assertIsNotNone(self.r._chain)
        self.r._roll_turn(5)
        self.assertIsNone(self.r._chain, "a new turn ends any exchange")

    def test_joshua_comments_from_outside_and_is_never_answered(self):
        self._observer(3, 1); self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.random = lambda: 0.01; self.r.rng.shuffle = lambda x: None
        self._spoken(1, "landed-hit", ctx={"targets": [0], "aggressor": None})   # the seat hit the HUMAN
        self.assertEqual([(q["kind"], q["stock"], q["gap"]) for q in self.r.queue], [("quip", "ouch", 1.5)], "Joshua's stock quip, at the chain's pace")
        self.assertIsNone(self.r._chain, "nobody answers Joshua")
        self.r.queue.clear()
        self.r.after_spoken({"kind": "quip", "stock": "ouch", "text": "", "seat": None, "library": "", "ctx": {}, "chain": None})
        self.assertEqual(self.r.queue, [], "the seats ignore Joshua")
        self.r.rng.random = lambda: 0.01
        self._spoken(1, "counter", ctx={"targets": [0]})
        self.assertEqual([(q["kind"], q["stock"]) for q in self.r.queue], [("quip", "rough-counter")])

    def test_human_caused_openers_run_at_half_strength_and_nobody_repeats_or_answers_themselves(self):
        self._observer(3, 1); self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.shuffle = lambda x: None
        self.r.rng.random = lambda: 0.35                                    # < 0.6 but >= 0.3
        self._spoken(2, "got-countered", ctx={"targets": [], "aggressor": 0, "human_cause": True})
        self.assertEqual(self._queued(), [], "the human countered Bill: a pile-on is half as likely")
        self.assertIn("p=0.30", self._records("skipped", "bark")[-1]["why"])
        self.r.rng.random = lambda: 0.01
        self._spoken(2, "got-countered", ctx={"targets": [], "aggressor": 0, "human_cause": True})
        self.assertEqual(self._queued(), [("bark", "pile-on", "harry", 1)], "the aggressor is the human (no voice): the bystander piles on")
        self.r.queue.clear()
        # the reply is now 'said this turn' for Harry: the same exchange cannot recycle it
        self._spoken(2, "got-countered", ctx={"targets": [], "aggressor": 0})
        self.assertEqual(self._queued(), [("bark", "sympathy", "harry", 1)], "pile-on was said; the next option is used")

    def test_leader_role_answers_a_taunt(self):
        seats = [{"seat": i, "name": f"s{i}", "eliminated": False, "life": life} for i, life in enumerate((40, 12, 33, 20))]
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 3, "activeSeat": 1, "seats": seats, "events": []}))
        self.r.scan_observer(); self.r.queue.clear()
        self.assertEqual(self.r.leader_of(1), 2, "the highest-life seat other than the speaker and the human")
        self.assertEqual(self.r.leader_of(2), 3, "leader is factual even when that seat has no voice (then nobody claps back)")
        self.r.rng.random = lambda: 0.01; self.r.rng.shuffle = lambda x: None
        self._spoken(1, "taunt")
        self.assertEqual(self._queued(), [("bark", "clapback", "bill", 2)])

    def test_chains_off_with_barks_off(self):
        self.r.barks_mode = "off"
        self._spoken(1, "big-swing", ctx={"targets": [2]})
        self.assertEqual(self.r.queue, [])


if __name__ == "__main__":
    unittest.main()
