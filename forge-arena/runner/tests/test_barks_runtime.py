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
import time
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402

LINES = ("big-swing", "eliminated", "my-turn", "that-hurt", "landed-hit", "counter", "got-countered", "slow-turn", "respect",
         "commander-cast", "wow", "play-slower", "sweep", "got-swept", "lost-commander", "removal", "win", "kill", "big-mana",
         "play-faster", "thinking-hard", "youre-the-threat", "whats-your-life", "low-life-jab", "cards-in-hand", "empty-hand",
         "kill-that", "board-envy", "nothing-happening", "this-is-fine", "good-hand", "what-turn", "deal", "pass-already")


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
                     "ARENA_BARKS_OPENER_P": "0", "ARENA_VOICE_PATTER": "off"}.items():
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

    def test_the_launcher_hands_the_runner_the_table_at_startup(self):
        self.assertEqual(vr.seat_decks_from_roster("selvala-heart-of-the-wilds", ""),
                         {1: "urza-lord-high-artificer", 2: "giada-font-of-hope", 3: "purphoros-god-of-the-forge"})
        self.assertEqual(vr.seat_decks_from_roster("giada-font-of-hope", "a b c d"), {1: "a", 2: "b", 3: "c"})
        self.assertEqual(vr.seat_decks_from_roster(None, ""), {}, "all-AI or an old launcher: default seats")
        (Path(vr.VOICES_DIR) / "assign.json").write_text(json.dumps({"by_deck": {"purphoros-god-of-the-forge": "harry", "urza-lord-high-artificer": "bill", "giada-font-of-hope": "lily"}}))
        os.environ["ARENA_HUMAN_DECK"] = "selvala-heart-of-the-wilds"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual({k: v["library"] for k, v in r.seat_libraries.items()}, {1: "bill", 3: "harry"},
                         "before a single card is drawn: Urza is Bill, Purphoros is Harry (no Lily in this tree)")
        # the launcher's default roster is the arena's (arena-config ROSTER)
        cfg = (Path(__file__).resolve().parents[2] / "scripts" / "arena-config.py").read_text()
        self.assertIn('ROSTER = "' + vr.DEFAULT_TABLE + '"', cfg)

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

    def test_speaking_file_names_the_seat_while_its_line_plays_and_clears_after(self):
        seen = []
        real_play = self.player.play
        def spy(path, should_stop=None):
            seen.append(json.loads((self.logs / "voice-speaking.json").read_text()))
            real_play(path, should_stop)
        self.player.play = spy
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self._step()
        self.assertEqual((seen[0]["seat"], seen[0]["library"], seen[0]["stock"]), (1, "harry", "big-swing"))
        self.assertGreater(seen[0]["until"], 0)
        self.assertEqual(json.loads((self.logs / "voice-speaking.json").read_text()), {}, "cleared when the line ends")
        seen.clear()
        self._observer(5, 0); self.r.seen_turn, self.r.seen_active = 4, 3; self.r.scan_observer(); self._step()
        self.assertEqual(seen[-1], {}, "Joshua's 'your move' never moves the tabs")

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

    def test_cast_events_commander_big_spell_and_a_flurry(self):
        self._prime()
        ev = [{"seq": 2, "kind": "cast", "turn": 3, "seat": 1, "spell": "Urza, Lord High Artificer", "commander": True, "cmc": 4}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "commander-cast", "harry", 1)])
        self.r.queue.clear()
        ev.append({"seq": 3, "kind": "cast", "turn": 3, "seat": 1, "spell": "Big Thing", "commander": False, "cmc": 8})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "wow", "bill", 2)], "a seven-plus spell impresses a bystander")
        self.r.queue.clear()
        ev.append({"seq": 4, "kind": "cast", "turn": 3, "seat": 1, "spell": "Third", "commander": False, "cmc": 1})
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "play-slower", "bill", 2)], "three spells in thirty seconds: slow down")
        self.r.queue.clear(); self.r._roll_turn(4)
        ev.append({"seq": 5, "kind": "cast", "turn": 4, "seat": 1, "spell": "Mid", "commander": False, "cmc": 5})
        self._observer(4, 1, events=ev); self.r.scan_observer()
        called = [r["stock"] for r in self._records("queued", "bark") if r.get("source") == "event"]
        self.assertTrue(any(x in ("nice-play", "read-that", "oh-no") for x in called[-2:]), f"a five-mana spell draws a bystander's reaction: {called}")

    def test_left_events_removal_sweep_and_lost_commander_with_the_right_speaker(self):
        self._prime()
        ev = [{"seq": 2, "kind": "left", "turn": 3, "by": 2, "cards": ["Sol Ring"], "seats": [1], "commanders": [], "n": 1, "tokens": 0}]
        self._observer(3, 2, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "removal", "bill", 2)], "Bill removed Harry's thing")
        self.r.queue.clear()
        ev.append({"seq": 3, "kind": "left", "turn": 3, "by": 1, "cards": ["Token"], "seats": [1], "commanders": [], "n": 1, "tokens": 1})
        self._observer(3, 2, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "your own token dying to your own effect is not removal")
        ev.append({"seq": 4, "kind": "left", "turn": 3, "by": 0, "cards": ["Urza, Lord High Artificer"], "seats": [1], "commanders": ["Urza, Lord High Artificer"], "n": 1, "tokens": 0})
        self._observer(3, 2, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [("bark", "lost-commander", "harry", 1)], "the human killed Harry's commander: Harry mourns")
        self.assertTrue(self.r.queue[0]["ctx"]["human_cause"])
        self.r.queue.clear(); self.r._roll_turn(4)
        ev.append({"seq": 5, "kind": "left", "turn": 4, "by": 2, "cards": ["a", "b", "c", "d"], "seats": [0, 1], "commanders": [], "n": 4, "tokens": 0})
        self._observer(4, 2, events=ev); self.r.scan_observer()
        got = self._queued()
        self.assertEqual(got, [("bark", "got-swept", "harry", 1)], "one pending bark: the sweep line was queued, then Harry's reaction replaced it (newest wins)")
        self.assertEqual([r["stock"] for r in self._records("queued", "bark")][-2:], ["sweep", "got-swept"])

    def test_gameover_kill_and_big_mana(self):
        self._prime()
        ev = [{"seq": 2, "kind": "damage", "turn": 3, "seat": 2, "amount": 3, "combat": True, "from": [1]}]
        self._observer(3, 1, events=ev); self.r.scan_observer()
        self.assertEqual(self._queued(), [], "three damage is not a big hit, but the hitter is remembered")
        self.r.rng.random = lambda: 0.9                          # Joshua announces the elimination…
        self._observer(3, 1, events=ev, elim=(2,)); self.r.scan_observer()
        self.assertEqual([(q["kind"], q["stock"], q.get("seat")) for q in self.r.queue], [("event", "player-eliminated", None), ("bark", "kill", 1)],
                         "…and Harry, who hit Bill last this turn, takes the kill")
        self.r.queue.clear()
        ev.append({"seq": 3, "kind": "gameover", "turn": 3, "winner": 1})
        self._observer(3, 1, events=ev, elim=(2,)); self.r.scan_observer()
        self.assertIn(("bark", "win", "harry", 1), self._queued())
        self.r.queue.clear(); self.r.eliminated.clear()
        seats = [{"seat": i, "name": f"s{i}", "eliminated": False, "life": 40, "pool": 9 if i == 1 else 0} for i in range(4)]
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 4, "activeSeat": 1, "seats": seats, "events": ev}))
        self.r.scan_observer()
        self.assertIn(("bark", "big-mana", "harry", 1), self._queued())
        self.r.queue.clear(); self.r.scan_observer()
        self.assertEqual([q for q in self._queued() if q[1] == "big-mana"], [], "still floating: said once")

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
    def test_dead_players_do_not_talk(self):
        self._observer(3, 1); self.r.scan_observer(); self._step()
        self.r.rng.random = lambda: 0.1
        self._observer(4, 2, elim=(1,)); self.r.scan_observer()               # Harry's seat falls: its exit line plays…
        self.assertEqual([(q["kind"], q["stock"], q["library"]) for q in self.r.queue], [("event", "eliminated", "harry")])
        self._step()
        self.assertFalse(self.r.maybe_bark(1, "taunt", turn=5, source="recap"), "…and nothing after")
        self.assertEqual(self._records("skipped", "bark")[-1]["why"], "eliminated")
        self.assertTrue(self.r.maybe_bark(2, "taunt", turn=5, source="recap"), "the living still speak")

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

    def test_chatter_dial_scales_every_frequency_the_gap_and_the_thresholds(self):
        self.assertEqual([vr.chatter_level(x) for x in ("quiet", "normal", "lively", "rowdy", "1.25", "bogus", None)], [0.5, 1.0, 1.5, 2.0, 1.25, 1.0, 1.0])
        for k in ("ARENA_BARKS", "ARENA_BARKS_P", "ARENA_BARKS_OPENER_P", "ARENA_VOICE_YOUR_MOVE_P", "ARENA_VOICE_COLOR_P", "ARENA_VOICE_MIN_GAP"):
            os.environ.pop(k, None)
        os.environ["ARENA_CHATTER"] = "rowdy"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_p, r.barks_opener_p, r.color_p, r.your_move_p), (1.0, 0.7, 1.0, 1.0), "×2, capped at 1")
        self.assertEqual((r.min_gap, r.barks_swing, r.barks_hit), (4.0, 3, 4), "gap halved, thresholds halved (floors 3 / 4)")
        os.environ["ARENA_CHATTER"] = "quiet"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertAlmostEqual(r.barks_p, 0.425); self.assertEqual((r.min_gap, r.barks_swing, r.barks_hit), (16.0, 12, 16))
        os.environ["ARENA_CHATTER"] = "normal"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.barks_p, r.min_gap, r.barks_swing), (0.85, 8.0, 6), "normal = the knobs as written")

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
        self.assertEqual((self.r.chains.first_hop_p, self.r.chains.decay, self.r.chains.max_hops, self.r.chains.gap_s), (0.6, 0.5, 3, 0.25))
        # the BarkRuntime tree has no chains.json: chains off, nothing else changes
        self.assertIsNone(vr.ChainTable.load(Path(self.tmp.name) / "nowhere"))

    def test_attack_then_brace_then_laugh_then_clapback_then_silence(self):
        self._observer(3, 1); self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.random = lambda: 0.01                                    # every roll succeeds
        self.r.rng.shuffle = lambda x: None                                  # table order: target first
        self._spoken(1, "big-swing", ctx={"targets": [2], "aggressor": None})
        self.assertEqual(self._queued(), [("bark", "brace", "bill", 2)], "the defender braces")
        hop1 = self.r.queue[0]
        self.assertEqual((hop1["gap"], hop1["chain"]["hop"], hop1["chain"]["origin"]), (0.25, 1, 1))
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
        self.assertEqual([(q["kind"], q["stock"], q["gap"]) for q in self.r.queue], [("quip", "ouch", 0.25)], "Joshua's stock quip, at the chain's pace")
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

    def test_the_dead_never_join_an_exchange(self):
        self._observer(3, 1, elim=(2,)); self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.random = lambda: 0.01; self.r.rng.shuffle = lambda x: None
        self._spoken(1, "big-swing", ctx={"targets": [2]})                     # the target is dead: no brace, and no bystander is left
        self.assertEqual(self._queued(), [])

    def test_chatter_scales_the_first_hop_too(self):
        os.environ["ARENA_CHATTER"] = "rowdy"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual(r.chains.first_hop_p, 1.0)
        self.assertEqual(r.chains.decay, 0.5, "the decay is not chatter")

    def test_a_hop_finishes_the_exchange_before_joshua_speaks_and_advice_drops_it(self):
        """Game 44, 20:43: 'your move' cut between a jab and its retort, so the retort landed on Joshua."""
        self._observer(3, 1); self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.random = lambda: 0.01; self.r.rng.shuffle = lambda x: None
        self._spoken(1, "big-swing", ctx={"targets": [2]})              # Bill's brace is pending
        self.r.enqueue("your_move", stock="your-move", ttl=12.0)
        self.r.enqueue("quip", stock="calculating", ttl=20.0)
        order = [q["kind"] for q in sorted(self.r.queue, key=lambda q: (q["prio"], q["at"]))]
        self.assertEqual(order[0], "bark", "the retort plays before Joshua's incidental lines")
        self.clock.t += 9
        item = self.r.next_item()
        self.assertEqual((item["kind"], item["stock"]), ("bark", "brace"))
        # real advice interrupts: the pending hop is dropped, not played after Joshua
        self.r.queue.clear()
        self._spoken(1, "big-swing", ctx={"targets": [2]})
        self.r.enqueue("advice", text="Block with everything.", ttl=25.0)
        self.clock.t += 9
        item = self.r.next_item()
        self.assertEqual(item["kind"], "advice")
        self.assertEqual(self.r.queue, [], "the orphaned retort is gone")
        self.assertIn("exchange interrupted by the advisor", self._records("dropped", "bark")[-1]["why"])

    def test_recency_a_line_said_lately_is_a_weak_pick_and_a_seat_avoids_a_reply_it_just_used(self):
        self._observer(3, 1); self.r.scan_observer(); self.r.queue.clear()
        self.r._said_at["cards-in-hand"] = self.clock.t - 60
        seats = [{"seat": i, "name": f"s{i}", "eliminated": False, "life": 40, "handSize": 7 if i == 2 else 3, "battlefield": []} for i in range(4)]
        cands = self.r.patter_candidates({"turn": 3, "activeSeat": 1, "seats": seats}, [1, 2])
        w = {pid: wgt for _, pid, _, wgt in cands if pid == "cards-in-hand"}["cards-in-hand"]
        self.assertLess(w, 0.5, "said a minute ago: weak")
        self.r._said_at["cards-in-hand"] = self.clock.t - 600
        cands = self.r.patter_candidates({"turn": 3, "activeSeat": 1, "seats": seats}, [1, 2])
        self.assertEqual({pid: wgt for _, pid, _, wgt in cands if pid == "cards-in-hand"}["cards-in-hand"], 2.0, "ten minutes ago: full weight")
        # chain: Bill's brace was used lately -> the table order puts it behind fresher replies
        self.r.rng.random = lambda: 0.01; self.r.rng.shuffle = lambda x: None
        self.r._seat_said_at[(2, "brace")] = self.clock.t - 30
        self._spoken(1, "big-swing", ctx={"targets": [2]})
        self.assertEqual(self._queued()[0][1], "why-me", "brace is stale for Bill; the next target reply is used")

    def test_chains_off_with_barks_off(self):
        self.r.barks_mode = "off"
        self._spoken(1, "big-swing", ctx={"targets": [2]})
        self.assertEqual(self.r.queue, [])


class PatterClock(_TreeCase):
    """The table fills silences from what the board says; quieter on the human's turn; never over the advisor."""
    CHAINS = True

    def setUp(self):
        super().setUp()
        os.environ["ARENA_VOICE_PATTER"] = "on"; os.environ["ARENA_VOICE_PATTER_GAP"] = "5-5"
        self.r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.r.rng.random = lambda: 0.0                     # dice always pass; weighted pick takes the first candidate
        self.r.rng.uniform = lambda a, b: a

    def _board(self, lives=(40, 40, 40, 40), hands=(3, 3, 3, 3), active=1, boards=None, elim=(), turn=5):
        seats = []
        for i in range(4):
            bf = [{"name": f"c{i}{k}", "power": p} for k, p in enumerate((boards or {}).get(i, []))]
            seats.append({"seat": i, "name": f"s{i}", "eliminated": i in elim, "life": lives[i], "handSize": hands[i], "battlefield": bf})
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": turn, "activeSeat": active, "gameOver": False, "seats": seats, "events": []}))
        self.r.scan_observer(); self.r.queue.clear(); self.r.last_spoken_at = self.clock.t

    def _tick(self, dt):
        self.clock.t += dt; self.r.patter()

    def test_defaults_and_the_dial(self):
        for k in ("ARENA_VOICE_PATTER", "ARENA_VOICE_PATTER_GAP", "ARENA_VOICE_PATTER_HUMAN", "ARENA_VOICE_PATTER_AFTER_ADVICE", "ARENA_BARKS_SLOW"):
            os.environ.pop(k, None)
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.patter_on, r.patter_gap, r.patter_human, r.patter_after_advice, r.barks_slow), (True, (5.0, 7.0), 0.33, 6.0, 20.0))
        os.environ["ARENA_CHATTER"] = "rowdy"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual(r.patter_gap, (2.5, 3.5)); self.assertEqual(r.chains.max_hops, 4, "a livelier table talks back one more time")
        self.assertEqual(r.barks_cooldown, 5.0, "the seat guard follows the dial")

    def test_a_slow_seat_is_told_to_play_faster_by_someone_else(self):
        self._board(active=2)
        inbox = self.mailbox / "seat-2" / "inbox"; inbox.mkdir(parents=True)
        f = inbox / "req-7.json"; f.write_text("{}")
        os.utime(f, (time.time() - 30, time.time() - 30))
        self.assertEqual(self.r.slow_seats(), [2])
        self._tick(6)
        q = [x for x in self._queued() if x[0] == "bark"]
        self.assertEqual(q, [("bark", "play-faster", "harry", 1)], "seat 1 tells seat 2 to hurry — the top-weighted candidate")
        self.assertEqual(self.r.queue[0]["ctx"]["targets"], [2])
        self.assertEqual(self._records("queued", "bark")[-1]["source"], "patter")

    def test_board_lines_name_the_leader_the_low_seat_the_big_hand_and_the_big_board(self):
        self._board(lives=(40, 8, 40, 45), hands=(3, 7, 0, 3), boards={2: [7, 2, 2]}, active=3)
        cands = self.r.patter_candidates(self.r._last_snapshot, [1, 2])
        ids = {(pid, tgt) for _, pid, tgt, _ in cands}
        self.assertIn(("youre-the-threat", 3), ids, "the human-side seat 3 at 45 is the leader; the human can be a target")
        self.assertIn(("low-life-jab", 1), ids); self.assertIn(("cards-in-hand", 1), ids)
        self.assertIn(("empty-hand", 2), ids); self.assertIn(("kill-that", 2), ids); self.assertIn(("board-envy", 2), ids)
        self.assertTrue(all(sp != tgt for sp, _, tgt, _ in cands), "nobody addresses themselves")
        self.assertTrue(all(sp in (1, 2) for sp, *_ in cands), "only living voiced seats speak")

    def test_filler_when_the_board_says_nothing_and_silence_is_respected(self):
        self._board()
        self._tick(4)
        self.assertEqual(self.r.queue, [], "not yet: the gap is five seconds from the last line")
        self._tick(2)
        self.assertEqual(len([x for x in self._queued() if x[0] == "bark"]), 1)
        pid = self.r.queue[0]["stock"]
        self.assertIn(pid, ("nothing-happening", "this-is-fine", "good-hand", "what-turn", "deal", "pass-already", "youre-the-threat", "whats-your-life"))

    def test_quiet_on_the_humans_turn_and_never_over_the_advisor(self):
        self._board(active=0)
        self._tick(6)
        self.assertEqual(self.r.queue, [], "the human's turn: the gap is three times longer")
        self._tick(10)
        self.assertEqual(len(self.r.queue), 1)
        self.r.queue.clear(); self._board(active=1, turn=6)          # a new turn: the no-repeat set is fresh
        self.r._advisor_spoke_at = self.clock.t
        self._tick(5)
        self.assertEqual(self.r.queue, [], "silence after advice — six seconds")
        self._tick(2)
        self.assertEqual(len(self.r.queue), 1)
        self.r.queue.clear(); self._board(active=1, turn=7)
        self.r.enqueue("advice", text="Do the thing.")
        self._tick(6)
        self.assertEqual([q["kind"] for q in self.r.queue], ["advice"], "a pending line: no patter")

    def test_the_dead_do_not_patter_and_a_patter_line_can_start_an_exchange(self):
        self._board(elim=(1,), active=2); self.r.eliminated.add(1)
        self._tick(6)
        q = [x for x in self._queued() if x[0] == "bark"]
        self.assertTrue(all(x[3] == 2 for x in q), q)
        self.r.queue.clear()
        self.r.rng.shuffle = lambda x: None
        self.r.after_spoken({"kind": "bark", "stock": "youre-the-threat", "text": "", "seat": 2, "library": "bill", "ctx": {"targets": [1]}, "chain": None})
        self.assertEqual(self.r.queue, [], "the target is dead: no answer")


if __name__ == "__main__":
    unittest.main()
