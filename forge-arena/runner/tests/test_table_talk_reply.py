"""Table talk answered by the seat itself (2026-10-16, Ben: "I do like the more direct
communication path"). The advisor runner still relays `@urza words` as a table-talk note; the
seat runner's idle-loop tick reads it, asks its OWN brain for one plain sentence on the same
session, appends `[<clock> · <Name> → you] <reply>` straight to logs/advisor-0.log (the panel's
stream) under the player's line, and records a `chat` row. No poll rate changed: the tick is
one stat of notes/ per idle pass and a listing only when the directory moved. Offline: fake
mailbox + scripted brain. Run: python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_deals_seat import make_runner, note, notes_left, cast  # noqa: E402


class TalkBrain:
    """decide() returns plain text in meta["raw"], the way the real brain does for a non-JSON answer."""
    effort, model = "medium", "opus"
    backend = None

    def __init__(self, *replies):
        self.replies, self.prompts, self.timeouts = list(replies), [], []
        self.totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0, "cost_usd": 0.0}

    def decide(self, prompt, timeout_s=None, effort=None, deadline=None):
        self.prompts.append(prompt)
        self.timeouts.append(timeout_s)
        raw = self.replies.pop(0) if self.replies else "Fine."
        return None, {"latency_s": 0.4, "usage": None, "raw": raw}

    def reset(self):
        pass


def talk_runner(*replies, panel=True, seat=1):
    r = make_runner(seat=seat)
    r.brain = TalkBrain(*replies)
    r.mb.game_id = "g1"
    if panel:
        (r._jsonl_path.parent / "advisor-0.log").write_text('\n[r2-t7 · you → Urza] "You really suck!"\n')
    return r


def panel(r) -> str:
    p = r._jsonl_path.parent / "advisor-0.log"
    return p.read_text() if p.exists() else ""


def said(r, ts=1700000000000, text="You really suck!", **extra):
    note(r, "table-talk", ts, **{"from": 0, "to": r.seat, "text": text, "turn": 7, "name": "Urza", "clock": "r2-t7", **extra})


class TheTick(unittest.TestCase):

    def test_talk_is_answered_in_the_panel_under_the_players_line(self):
        r = talk_runner("Bold words from a man at thirty-five life.")
        said(r)
        r._talk_tick()
        self.assertTrue(panel(r).endswith('\n[r2-t7 · you → Urza] "You really suck!"\n'
                                          '[r2-t7 · Urza → you] Bold words from a man at thirty-five life.\n'))
        self.assertEqual(notes_left(r), [], "consumed once")
        p = r.brain.prompts[-1]
        self.assertIn('Player One (seat 0) says to you: "You really suck!"', p)
        self.assertIn("TABLE TALK (turn 7)", p)
        self.assertIn("no JSON", p)
        self.assertIn("SILENT", p)
        self.assertEqual(r.brain.timeouts, [r.TALK_TIMEOUT_S], "a short budget: a stall must not eat an engine window")
        seq, answer, source, k = r.records[-1]
        self.assertEqual((source, answer), ("chat", {"text": "Bold words from a man at thirty-five life.", "silent": False}))
        self.assertEqual(k["why"], 'heard: "You really suck!"')
        self.assertIs(seq, None)
        self.assertTrue(any('table talk "You really suck!": "Bold words' in l and "after it was typed" in l for l in r.log_lines), r.log_lines)

    def test_silent_and_json_replies_show_nothing(self):
        r = talk_runner("SILENT.", '{"chosenId": 0}')
        before = panel(r)
        said(r, ts=1700000000000)
        r._talk_tick()
        r._talk_last = 0.0
        said(r, ts=1700000001000)
        r._talk_tick()
        self.assertEqual(panel(r), before, "nothing posted for SILENT or for a JSON answer")
        self.assertEqual([a for _, a, s, _ in r.records if s == "chat"], [{"text": None, "silent": True}] * 2)
        self.assertEqual(notes_left(r), [])
        self.assertTrue(any("stayed silent" in l for l in r.log_lines))

    def test_no_answer_posts_nothing_and_still_consumes_the_note(self):
        r = talk_runner(None)
        before = panel(r)
        said(r)
        r._talk_tick()
        self.assertEqual(panel(r), before)
        self.assertEqual(notes_left(r), [], "the brain saw it (or the call died): never sent twice")
        self.assertEqual(r.records[-1][1], {"text": None, "silent": False})
        self.assertTrue(any("no answer" in l for l in r.log_lines))

    def test_two_notes_share_one_turn_and_a_third_waits_for_the_gap(self):
        r = talk_runner("Both of you, settle down.", "Still here.")
        said(r, ts=1700000000000, text="You suck!")
        said(r, ts=1700000000500, text="Really.")
        r._talk_tick()
        self.assertEqual(len(r.brain.prompts), 1, "coalesced")
        self.assertIn('says to you: "You suck!"\nPlayer One (seat 0) says to you: "Really."', r.brain.prompts[0])
        self.assertEqual(panel(r).count("Urza → you"), 1)
        said(r, ts=1700000002000, text="Hello?")
        r._talk_tick()
        self.assertEqual(len(r.brain.prompts), 1, "inside TALK_GAP_S: it waits")
        self.assertEqual(notes_left(r), ["1700000002000-table-talk.json"])
        r._talk_tick()
        self.assertEqual(len(r.brain.prompts), 1, "still waiting (the dirty flag re-lists, the gap still holds)")
        r._talk_last = 0.0
        r._talk_tick()
        self.assertEqual(len(r.brain.prompts), 2)
        self.assertTrue(panel(r).endswith("[r2-t7 · Urza → you] Still here.\n"))

    def test_an_unchanged_directory_is_not_listed_again(self):
        r = talk_runner("Fine.")
        said(r)
        r._talk_tick()                                   # answers; the unlink moves the directory's mtime
        r._talk_tick()                                   # lists once more, finds nothing
        with mock.patch.object(Path, "iterdir", side_effect=AssertionError("listed an unchanged notes/")):
            r._talk_tick()                               # the signature matches: one stat, no listing
        self.assertEqual(len(r.brain.prompts), 1)

    def test_without_the_panel_stream_the_reply_is_only_logged(self):
        r = talk_runner("Fine.", panel=False)
        said(r)
        r._talk_tick()
        self.assertFalse((r._jsonl_path.parent / "advisor-0.log").exists(), "the seat never creates the stream")
        self.assertTrue(any("panel stream absent" in l for l in r.log_lines))
        self.assertEqual(r.records[-1][1]["text"], "Fine.")

    def test_the_reply_is_one_trimmed_row(self):
        r = talk_runner('  "Thirty-five life and\n   talking like that?"  ', "x" * 300)
        said(r, ts=1700000000000)
        r._talk_tick()
        self.assertTrue(panel(r).endswith("[r2-t7 · Urza → you] Thirty-five life and talking like that?\n"))
        r._talk_last = 0.0
        said(r, ts=1700000001000)
        r._talk_tick()
        last = panel(r).splitlines()[-1]
        self.assertEqual(len(last.split("] ", 1)[1]), r.TALK_MAX_CHARS)
        self.assertTrue(last.endswith("…"))

    def test_a_note_without_name_or_clock_still_gets_a_line(self):
        r = talk_runner("Fine.")
        d = r._notes_dir(); d.mkdir(parents=True, exist_ok=True)
        (d / "1700000000000-table-talk.json").write_text(json.dumps({"kind": "table-talk", "from": 0, "to": 1, "text": "oi", "turn": 7}))
        r._talk_tick()
        last = panel(r).splitlines()[-1]
        self.assertTrue(last.startswith("[t7 · ") and last.endswith(" → you] Fine."), last)

    def test_off_and_the_decision_path(self):
        # on: a talk note waits for the tick; a decision prompt never carries it, an invite is still consumed there
        r = talk_runner("Fine.")
        note(r, "deal-invite", 1700000000000, **{"from": 0, "to": 1, "text": "make me an offer", "turn": 7})
        said(r, ts=1700000000001)
        r.handle(cast(1, turn=7))
        self.assertNotIn("says to you", r.brain.prompts[-1])
        self.assertEqual(notes_left(r), ["1700000000001-table-talk.json"])
        r._talk_tick()
        self.assertEqual(notes_left(r), [])
        self.assertTrue(panel(r).endswith("[r2-t7 · Urza → you] Fine.\n"))
        # off: the old path, and the tick does nothing
        r2 = talk_runner("never asked")
        r2.talk_reply = False
        said(r2)
        r2._talk_tick()
        self.assertEqual(r2.brain.prompts, [])
        r2.handle(cast(1, turn=7))
        self.assertIn('RUNNER NOTE: Player One (seat 0) says to you: "You really suck!"', r2.brain.prompts[-1])
        self.assertEqual(notes_left(r2), [])

    def test_the_tick_never_raises(self):
        r = talk_runner("Fine.")
        said(r)
        r._record = mock.Mock(side_effect=RuntimeError("disk"))
        r._talk_tick()                                   # the answer path blew up after the brain call
        self.assertTrue(any("INTERNAL ERROR" in l for l in r.log_lines))
        self.assertEqual(notes_left(r), [])


class ARealRunner(unittest.TestCase):
    """The fixture stubs _record; the real one must take the pseudo-request (no seq, empty state)
    and write the chat row to seat-N.jsonl, game.jsonl and the usage snapshot."""

    def test_the_exchange_is_recorded_like_a_decision(self):
        import tempfile
        from seatd.runner import SeatRunner
        tmp = Path(tempfile.mkdtemp(prefix="talk-real-"))
        r = SeatRunner(1, "urza-lord-high-artificer", str(tmp), log_dir=str(tmp / "logs"))
        r.brain = TalkBrain("Thirty-five life and talking like that?")
        r.mb.game_id = "g77"
        (tmp / "logs" / "advisor-0.log").write_text('\n[r2-t7 · you → Urza] "You really suck!"\n')
        d = r._notes_dir(); d.mkdir(parents=True, exist_ok=True)
        (d / "1700000000000-table-talk.json").write_text(json.dumps(
            {"kind": "table-talk", "from": 0, "to": 1, "text": "You really suck!", "turn": 7, "name": "Urza", "clock": "r2-t7"}))
        r._talk_tick()
        self.assertTrue((tmp / "logs" / "advisor-0.log").read_text().endswith(
            "[r2-t7 · Urza → you] Thirty-five life and talking like that?\n"))
        rows = [json.loads(l) for l in (tmp / "logs" / "game.jsonl").read_text().splitlines()]
        self.assertEqual([(x["source"], x["type"], x["seat"], x["turn"], x["gameId"]) for x in rows], [("chat", "TABLE_TALK", 1, 7, "g77")])
        self.assertEqual(rows[0]["answer"], {"text": "Thirty-five life and talking like that?", "silent": False})
        self.assertEqual(rows[0]["why"], 'heard: "You really suck!"')
        self.assertEqual(rows[0]["latency_s"], 0.4)
        mine = [json.loads(l) for l in (tmp / "logs" / "seat-1.jsonl").read_text().splitlines()]
        self.assertEqual(mine[0]["source"], "chat")
        self.assertNotIn("options", mine[0])
        self.assertTrue((tmp / "logs" / "seat-1.usage.json").exists())
        self.assertTrue((tmp / "logs" / "game-g77.jsonl").exists(), "the per-game machine record gets the line too")
        self.assertTrue(r.talk_reply, "the default is on")
        self.assertEqual(sorted(p.name for p in d.iterdir()), [])


class TheText(unittest.TestCase):
    def test_talk_text(self):
        from seatd.runner import SeatRunner as S
        self.assertIsNone(S._talk_text(None))
        self.assertIsNone(S._talk_text("   "))
        self.assertEqual(S._talk_text("SILENT"), "")
        self.assertEqual(S._talk_text("silent."), "")
        self.assertEqual(S._talk_text('{"say": "taunt"}'), "")
        self.assertEqual(S._talk_text('“Nice try.”'), "Nice try.")
        self.assertEqual(S._talk_text("one\n\ntwo   three"), "one two three")


if __name__ == "__main__":
    unittest.main()
