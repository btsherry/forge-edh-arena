"""Hardening pass (Ben, 2026-09-08): runner restart keeps the game record, the
voice backs off after repeated live failures, the launch banner's default
table cannot drift from the code, the hygiene block reads a session, and
`--stops restore` works standalone. Run: python3 -m unittest discover -s tests"""
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.runner import SeatRunner  # noqa: E402
import voice_runner as vr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent   # forge-arena/
WAV = vr.pcm_to_wav(b"\x00\x00" * 2400, 24000)


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _runner():
    tmp = Path(tempfile.mkdtemp(prefix="hard-"))
    return SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs")), tmp


def _rows(seat, gid, turns):
    return [{"seat": seat, "gameId": gid, "turn": t, "seq": 10 * t, "type": "CAST_SPELL", "source": "model",
             "answer": {"chosenId": 1}, "why": f"turn {t} reason",
             "board": {"lives": {"0": 40, "2": 40 - t}, "stack": []}} for t in turns]


class RestartKeepsTheRecord(unittest.TestCase):
    def test_init_prompt_shares_the_dossier_and_appends_the_record(self):
        r, _ = _runner()
        plain = r.brain._init_prompt(None)
        self.assertEqual(plain, r.brain._init_message)
        withrec = r.brain._init_prompt("THE RECORD")
        self.assertTrue(withrec.endswith("\nReply exactly: READY"))
        self.assertEqual(withrec.count("Reply exactly: READY"), 1, "READY is said once, after the record")
        self.assertLess(withrec.index("THE RECORD"), withrec.index("Reply exactly: READY"))
        self.assertTrue(withrec.startswith(plain[: len(plain) - len("\nReply exactly: READY")]))

    def test_restart_record_is_found_only_for_a_live_game(self):
        r, tmp = _runner()
        self.assertIsNone(r._restart_record(), "no game.jsonl: a launch, not a restart")
        r._game_log.parent.mkdir(parents=True, exist_ok=True)
        rows = _rows(0, "g1", [1, 2]) + _rows(2, "g1", [1, 2, 3])
        r._game_log.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
        got = r._restart_record()
        self.assertIsNotNone(got)
        gid, text, n = got
        self.assertEqual((gid, n), ("g1", 3))
        self.assertIn("Turn 3", text)
        self.assertIn("turn 3 reason", text, "own reasons are quoted")
        (tmp / "observer-state.json").write_text(json.dumps({"gameOver": True}))
        self.assertIsNone(r._restart_record(), "the game is over: nothing to carry")

    def test_ensure_session_sends_the_record_once(self):
        r, _ = _runner()
        sent = []
        r.brain._call = lambda prompt, timeout_s, resume, **k: (sent.append((prompt, resume)) or {"session_id": "abcdef1234", "usage": {"input_tokens": 5}})
        self.assertTrue(r.brain.ensure_session(record_text="THE RECORD"))
        self.assertEqual(len(sent), 1)
        self.assertIn("THE RECORD", sent[0][0]); self.assertFalse(sent[0][1])
        self.assertEqual(r.brain.session_id, "abcdef1234")
        self.assertTrue(r.brain.ensure_session(record_text="AGAIN"), "already up: no second init")
        self.assertEqual(len(sent), 1)

    def test_transport_name(self):
        r, _ = _runner()
        self.assertIn(r.brain.transport_name, ("spawn", "persistent"))


class ManaReachCeiling(unittest.TestCase):
    """BL-43: the affordability fastpath must not pass a window the payer could
    fund through a costed source (Selvala) — the engine's manaReach is the
    ceiling when published."""
    def _react(self, avail, reach=None):
        r = json.loads((ROOT / "runner" / "tests" / "fixtures" / "engine" / "react.json").read_text())
        st = r["state"]
        st["seat"] = 2; st["life"] = 18; st["manaPool"] = 0; st["untappedManaSourceCount"] = 3
        st["manaAvailableNow"] = avail
        st.pop("manaReach", None)   # the fixture carries the engine's reach; tests set the sum explicitly
        if reach is not None:
            st["manaReach"] = reach
        st["stack"] = []; st["stackKinds"] = []; st["stackOwners"] = []; st["stackTargets"] = []
        r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"},
                        {"id": 1, "label": "Rhonas the Indomitable  {2}{G} — Another target creature gets +2/+0 and gains trample", "cost": "{2}{G}", "type": "Ability"}]
        return r

    def test_reach_keeps_the_window_open(self):
        r, _ = _runner()
        self.assertEqual(r._fastpath(self._react(2))[1], "affordability", "2 mana, {2}{G} pump: dead without a reach")
        self.assertIsNone(r._fastpath(self._react(2, reach=9)), "Selvala can be tapped by the payer: the model decides")
        self.assertEqual(r._fastpath(self._react(2, reach=2))[1], "affordability", "reach equal to the sum changes nothing")
        self.assertEqual(r._fastpath(self._react(2, reach=True))[1], "affordability", "a malformed reach is ignored")


class VoiceBackoff(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("ARENA_VOICE_FX", "ARENA_VOICE_GLITCH")}
        os.environ["ARENA_VOICE_FX"] = "off"; os.environ["ARENA_VOICE_GLITCH"] = "off"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_three_failures_pause_live_lines_and_recovery_is_logged(self):
        tmp = Path(tempfile.mkdtemp(prefix="vb-"))
        now = [1000.0]; calls = [0]; ok = [False]; logs = []; events = []

        def tts(text):
            calls[0] += 1
            if not ok[0]:
                raise RuntimeError("HTTP 401 quota_exceeded")
            return WAV
        rd = vr.Renderer(tmp, log=logs.append, fake_tts=tts, record=lambda ev, **b: events.append((ev, b)), clock=lambda: now[0])
        for i in range(3):
            self.assertIsNone(rd.render(f"line {i}"))
        self.assertEqual(calls[0], 3)
        self.assertEqual(sum("live render failed:" in l for l in logs), 1, "the first failure logs in full")
        self.assertEqual(sum("paused 60s" in l for l in logs), 1)
        self.assertIsNone(rd.render("line 3")); self.assertEqual(calls[0], 3, "paused: no call")
        now[0] += 61
        self.assertIsNone(rd.render("line 4")); self.assertEqual(calls[0], 4, "pause over: one probe")
        self.assertTrue(any("paused 120s" in l for l in logs), "the pause doubles")
        self.assertEqual([e for e, _ in events].count("live-paused"), 2)
        self.assertEqual(rd.fails_total, 4)
        now[0] += 121; ok[0] = True
        self.assertIsNotNone(rd.render("line 5"))
        self.assertTrue(any("recovered after 4 failure(s)" in l for l in logs))
        self.assertEqual((rd.fail_streak, rd.renders, rd.pause_s), (0, 1, rd.PAUSE_FIRST_S))


class ConditionalQuips(unittest.TestCase):
    """Ben, 2026-09-08: stock quips are boosted ONLY while live lines are down."""
    def test_renderer_state_names_the_reason(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-"))
        now = [0.0]
        rd = vr.Renderer(tmp, log=lambda m: None, clock=lambda: now[0])
        rd.api_key = ""
        self.assertEqual(rd.state(), (False, "no ELEVENLABS_API_KEY"))
        rd.api_key = "k"
        self.assertEqual(rd.state(), (True, "ok"))
        rd.paused_until = 50.0
        self.assertEqual(rd.state(), (False, "paused after repeated failures"))
        now[0] = 60.0
        self.assertEqual(rd.state()[0], True)
        rd.chars_used = rd.max_chars
        self.assertFalse(rd.state()[0])

    def test_runner_publishes_state_once_per_change(self):
        tmp = Path(tempfile.mkdtemp(prefix="vs-"))
        (tmp / "logs").mkdir(); (tmp / "mailbox").mkdir()
        run = vr.VoiceRunner(tmp / "logs", tmp / "mailbox", dry_run=True)
        run.renderer.api_key = ""
        run.publish_state()
        st = tmp / "mailbox" / "seat-0-voice" / "state.json"
        d = json.loads(st.read_text())
        self.assertEqual((d["live"], d["enabled"]), (False, True)); self.assertIn("ELEVENLABS", d["reason"])
        m1 = st.stat().st_mtime_ns
        run.publish_state()
        self.assertEqual(st.stat().st_mtime_ns, m1, "unchanged state: no rewrite")
        run.renderer.api_key = "k"
        run.publish_state()
        self.assertTrue(json.loads(st.read_text())["live"])

    def test_mute_does_not_log_a_live_transition_and_your_move_waits_while_executive(self):
        tmp = Path(tempfile.mkdtemp(prefix="vs2-"))
        (tmp / "logs" / "control").mkdir(parents=True); (tmp / "mailbox").mkdir()
        run = vr.VoiceRunner(tmp / "logs", tmp / "mailbox", dry_run=True)
        run.renderer.api_key = "k"
        logs = []; run.say = logs.append
        run.publish_state()
        (tmp / "logs" / "control" / "voice.json").write_text(json.dumps({"enabled": False}))
        run.publish_state()
        self.assertFalse(json.loads((tmp / "mailbox" / "seat-0-voice" / "state.json").read_text())["enabled"])
        self.assertEqual([l for l in logs if "live lines" in l], [], "a mute is not a live transition")
        run.renderer.api_key = ""; run.publish_state()
        run.renderer.api_key = "k"; run.publish_state()
        self.assertEqual(sum("live lines off" in l for l in logs), 1); self.assertEqual(sum("back on" in l for l in logs), 1)
        # your move: seat 0 becomes active with the Executive on -> silence; off -> the line
        (tmp / "logs" / "control" / "voice.json").write_text(json.dumps({"enabled": True}))
        st = tmp / "mailbox" / "observer-state.json"
        st.write_text(json.dumps({"turn": 3, "activeSeat": 1, "seats": []})); run.scan_observer()
        (tmp / "logs" / "control" / "executive.json").write_text(json.dumps({"on": True}))
        st.write_text(json.dumps({"turn": 4, "activeSeat": 0, "seats": []})); run.scan_observer()
        self.assertEqual([q["kind"] for q in run.queue if q["kind"] == "your_move"], [])
        (tmp / "logs" / "control" / "executive.json").write_text(json.dumps({"on": False}))
        st.write_text(json.dumps({"turn": 5, "activeSeat": 1, "seats": []})); run.scan_observer()
        st.write_text(json.dumps({"turn": 6, "activeSeat": 0, "seats": []})); run.scan_observer()
        self.assertEqual([q["kind"] for q in run.queue if q["kind"] == "your_move"], ["your_move"])

    def test_advisor_switches_guidance_on_the_state_file(self):
        import advisor_runner as ar
        tmp = Path(tempfile.mkdtemp(prefix="qg-"))
        f = tmp / "state.json"; logs = []
        text, live = ar.quip_guide(f, log=logs.append, prev=None)
        self.assertEqual((text, live), (ar.QUIP_GUIDE_SPARSE, True), "no file: sparse")
        f.write_text(json.dumps({"live": False, "reason": "no ELEVENLABS_API_KEY", "enabled": True}))
        text, live = ar.quip_guide(f, log=logs.append, prev=True)
        self.assertEqual((text, live), (ar.QUIP_GUIDE_DENSE, False))
        self.assertIn("one line in two", text); self.assertIn("stock phrases", text)
        self.assertEqual(len(logs), 1); self.assertIn("no ELEVENLABS_API_KEY", logs[0])
        text, live = ar.quip_guide(f, log=logs.append, prev=False)
        self.assertEqual(len(logs), 1, "same state: no second log line")
        f.write_text(json.dumps({"live": True, "reason": "ok"}))
        text, live = ar.quip_guide(f, log=logs.append, prev=False)
        self.assertEqual((text, len(logs)), (ar.QUIP_GUIDE_SPARSE, 2))
        f.write_text("{not json")
        self.assertEqual(ar.quip_guide(f)[0], ar.QUIP_GUIDE_SPARSE, "unreadable: sparse")
        self.assertIn("at most every other turn", ar.QUIP_GUIDE_SPARSE)


class RoundTurnLabels(unittest.TestCase):
    """Ben, 2026-09-08 (game 32): panel lines read r<round>-t<turn>."""
    def test_rounds_follow_the_table_not_a_formula(self):
        import advisor_runner as ar
        tmp = Path(tempfile.mkdtemp(prefix="clk-"))
        st = tmp / "observer-state.json"
        clk = ar.TurnClock(st)
        self.assertEqual(clk.label(1), "r1-t1", "no snapshot: four turns a round")
        self.assertEqual(clk.label(5), "r2-t5"); self.assertEqual(clk.label(13), "r4-t13")
        # game 33's order: seat 1 started; the human is seat 0
        clk = ar.TurnClock(st)
        order = {1: 1, 2: 2, 3: 3, 4: 0, 5: 1, 6: 2, 7: 3, 8: 0, 9: 1}
        labels = {}
        for t, active in order.items():
            st.write_text(json.dumps({"turn": t, "activeSeat": active}))
            clk.observe()                      # the poll loop sees the snapshot first
            labels[t] = clk.label(t)
        self.assertEqual(labels[4], "r1-t4"); self.assertEqual(labels[5], "r2-t5", "seat 1 again: round 2 starts at t5")
        self.assertEqual(labels[8], "r2-t8"); self.assertEqual(labels[9], "r3-t9")
        # the snapshot lags a line: label() reads it on demand
        st.write_text(json.dumps({"turn": 10, "activeSeat": 2}))
        self.assertEqual(clk.label(10), "r3-t10")
        # seat 3 eliminated: round 3 is 9 (s1), 10 (s2), 11 (s0); seat 1 again at 12 opens round 4 — three turns a round now
        for t, active in {11: 0, 12: 1, 13: 2}.items():
            st.write_text(json.dumps({"turn": t, "activeSeat": active})); clk.observe()
        self.assertEqual(clk.label(11), "r3-t11", "earlier turns keep their round")
        self.assertEqual(clk.label(12), "r4-t12"); self.assertEqual(clk.label(13), "r4-t13")
        self.assertEqual(clk.label("?"), "t?")
        # a line for a turn the snapshot has not shown yet: same round as the latest known
        self.assertEqual(clk.label(14), "r4-t14")

    def test_stream_lines_carry_the_label(self):
        import advisor_runner as ar
        tmp = Path(tempfile.mkdtemp(prefix="lbl-"))

        class FakeBrain:
            deck = "selvala-heart-of-the-wilds"; model = "opus"; effort = "low"; session_id = "s1"
            last_prompt_tokens = 0; totals = {"calls": 0}; backend = None; wedges = 0; calls = 0
            def ensure_session(self, *a, **k): return True
            def reset(self): pass
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = (lambda *a, **k: FakeBrain()), (lambda *a, **k: [])
        try:
            adv = ar.AdvisorRunner("selvala-heart-of-the-wilds", tmp, "opus", "low", 30.0, log_dir=tmp / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        out = []
        adv._stream_write = out.append
        (tmp / "observer-state.json").write_text(json.dumps({"turn": 6, "activeSeat": 1}))
        env = os.environ.get("ARENA_AUTOPASS_RECEIPTS")
        os.environ.pop("ARENA_AUTOPASS_RECEIPTS", None)   # the default: summary
        try:
            adv._show_note({"turn": 6, "note": "(auto-passed — nothing available)"})
            self.assertEqual(out, [], "summary by default: held until the turn moves on")
            adv._show_note({"turn": 7, "note": "(prompt kept — castable: Khalni Ambush)"})
        finally:
            if env is not None:
                os.environ["ARENA_AUTOPASS_RECEIPTS"] = env
        self.assertTrue(out[0].startswith("[r2-t6] ⏭ auto-passed 1 stop"), out)
        self.assertTrue(out[1].startswith("[r2-t7] ⏭ (prompt kept"), out)


class LaunchBanner(unittest.TestCase):
    IGNORE = {"ARENA_RATE_VOIDED", "ARENA_OAI_API_KEY", "ARENA_HUMAN_DECK", "ARENA_MAILBOX_DIR", "ARENA_ADVISOR",
              "ARENA_AUTOSTOP_STATE", "ARENA_AUTOSTOP_STOP", "ARENA_AUTOSTOP_PID_FILE", "ARENA_AUTOSTOP_GUI_PID_FILE",
              "ARENA_STOPS", "ARENA_VOICE_ID"}

    def _observed(self):
        seen = {}
        py = re.compile(r'environ\.get\("((?:ARENA|SEAT)_[A-Z_]+)"(?:,\s*"([^"]*)")?\)')
        sh = re.compile(r'\$\{((?:ARENA|SEAT)_[A-Z_]+)(?::-([^}]*))?\}')
        files = list((ROOT / "runner").glob("*.py")) + list((ROOT / "runner" / "seatd").glob("*.py")) \
            + list((ROOT / "runner").glob("*.sh")) + list((ROOT / "scripts").glob("*.sh"))
        for f in files:
            text = f.read_text(errors="replace")
            for rx in (py, sh):
                for m in rx.finditer(text):
                    seen.setdefault(m.group(1), set()).add(m.group(2) or "")
        return seen

    def test_defaults_match_the_code_and_every_knob_is_listed(self):
        cfg = _load_script("arena-config")
        table = {name: default for rows in cfg.KNOBS.values() for name, default, _ in rows}
        seen = self._observed()
        for name, default in table.items():
            if name in seen and default:
                self.assertIn(default, seen[name], f"{name}: banner says {default!r}, code says {sorted(seen[name])}")
        missing = {n for n in seen if n not in table and n not in self.IGNORE and not n.startswith("ARENA_PF_")}
        self.assertEqual(missing, set(), "knobs read by the code but absent from the banner (add to KNOBS)")

    def test_readme_lists_every_knob(self):
        cfg = _load_script("arena-config")
        readme = (ROOT / "packaging" / "README.md").read_text()
        missing = [name for rows in cfg.KNOBS.values() for name, _, _ in rows if f"`{name}`" not in readme]
        self.assertEqual(missing, [], "knobs in the banner but not in the README's settings table")

    def test_banner_never_prints_a_secret(self):
        cfg = _load_script("arena-config")
        env = {"ELEVENLABS_API_KEY": "sk-very-secret", "ARENA_ROTATE_TOKENS": "1000"}

        class A:
            mode = "human"; deck = "selvala"; model = "opus"; effort = "low"; timeout = "90"; advisor = "1"
            voice = "on"; stops = "quick"; linger = "120"; autostop = "1"
        text = cfg.render(A(), env=env)
        self.assertNotIn("sk-very-secret", text)
        self.assertIn("ELEVENLABS_API_KEY=set", text)
        self.assertIn("ARENA_ROTATE_TOKENS=1000  [SET — default 250000]", text)
        self.assertIn("changed from defaults: ARENA_ROTATE_TOKENS", text)


class HygieneBlock(unittest.TestCase):
    def test_counts_and_the_loud_line(self):
        hy = _load_script("arena-hygiene")
        d = Path(tempfile.mkdtemp(prefix="hy-"))
        rows = [{"seat": 1, "gameId": "g", "source": "model", "latency_s": 2.0}, {"seat": 1, "gameId": "g", "source": "model", "latency_s": 4.0},
                {"seat": 2, "gameId": "g", "source": "memo"}, {"seat": 2, "gameId": "g", "source": "punt", "deviation": "x"}]
        (d / "game.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        (d / "seat-1.log").write_text("ok\n[seat 1] INTERNAL ERROR in handle()\nTraceback (most recent call last)\n[seat 1] session rotated #1 in 3s\n")
        (d / "run_table.out").write_text("[seat 1] INTERNAL ERROR in handle()\nTraceback (most recent call last)\n[seat 1] runner exited (1) — restarting in 2s\n")
        (d / "voice-0.jsonl").write_text(json.dumps({"event": "spoke"}) + "\n" + json.dumps({"event": "live-paused"}) + "\n")
        text, ok = hy.report(str(d))
        self.assertFalse(ok)
        self.assertIn("decisions 4 | model 2 (50%) | runner-answered 1 (memo 1) | punts 1 | deviations 1", text)
        self.assertIn("tracebacks 2", text, "seat log only — run_table.out echoes are not counted twice")
        self.assertIn("restarts 1", text); self.assertIn("rotations 1", text)
        self.assertIn("voice: spoke 1", text)
        self.assertIn("!! HYGIENE: punts (game log) 1, tracebacks 2, voice live paused 1", text)
        clean = Path(tempfile.mkdtemp(prefix="hy2-"))
        (clean / "game.jsonl").write_text(json.dumps({"seat": 1, "gameId": "g", "source": "model"}) + "\n")
        text, ok = hy.report(str(clean))
        self.assertTrue(ok); self.assertIn("OK: no punts", text)


class PackagerShipsWhatTheScriptsCall(unittest.TestCase):
    """The packager copies scripts by an explicit list; a script arena-play /
    arena-stop / arena-autostop / the advisor call that is missing from the
    list breaks the shipped package on first launch (2026-09-08 near-miss:
    arena-config.py, arena-hygiene.py and arena-public-state.py)."""
    def test_every_script_the_shipped_scripts_call_is_packaged(self):
        pk = (ROOT / "packaging" / "build-light-package.sh").read_text()
        m = re.search(r"for f in ((?:[^;]|\n)*?); do", pk[pk.index("[8/9] scripts"):])
        shipped = set(re.findall(r"[a-zA-Z_-]+\.(?:py|sh)", m.group(1)))
        needed = set()
        for name in ("arena-play.sh", "arena-stop.sh", "arena-autostop.sh"):
            text = (ROOT / "scripts" / name).read_text()
            needed |= set(re.findall(r"\$(?:DIR|ROOT/scripts)/([a-zA-Z_-]+\.(?:py|sh))", text))
        adv = (ROOT / "runner" / "advisor_runner.py").read_text()
        needed |= set(re.findall(r"forge-arena/scripts/([a-zA-Z_-]+\.py)", adv))
        self.assertEqual(needed - shipped, set(), "called by shipped code but not in the packager's script list")
        self.assertIn("--exclude '/voice/stock/raw/'", pk, "raw takes (4 MB) must not ship")
        self.assertIn("--exclude '/voice/build_stock.py'", pk, "the ElevenLabs render tool is dev-only")
        for name in ("packaging/build-light-package.sh", "scripts/run-pilot-match.sh"):
            text = (ROOT / name).read_text()
            self.assertIn("BL-47", text, f"{name}: fat jar must be chosen by the pom revision (BL-47), not the first glob match")
            self.assertIn("<versionCode>", text, f"{name}: the revision is composed from the pom's versionCode + snapshotName")
            self.assertNotIn('$(ls "$REPO_ROOT"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar 2>/dev/null | head -n1)', text)
            self.assertNotIn('$(ls "$REPO"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar 2>/dev/null | head -n1)', text)
        self.assertIn("--exclude '.DS_Store'", pk)


class StopsRestore(unittest.TestCase):
    def test_standalone_restore(self):
        home = Path(tempfile.mkdtemp(prefix="home-"))
        prefs = home / "Library" / "Application Support" / "Forge" / "preferences" / "forge.preferences"
        prefs.parent.mkdir(parents=True)
        prefs.write_text("PHASE_AI_EOT=false\n")
        env = dict(os.environ, HOME=str(home))
        r = subprocess.run(["sh", str(ROOT / "scripts" / "arena-play.sh"), "--stops", "restore"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1); self.assertIn("nothing to restore", r.stderr)
        (prefs.parent / "forge.preferences.bak-arena").write_text("PHASE_AI_EOT=true\n")
        r = subprocess.run(["sh", str(ROOT / "scripts" / "arena-play.sh"), "--stops", "restore"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("restored", r.stdout)
        self.assertEqual(prefs.read_text(), "PHASE_AI_EOT=true\n")
        r = subprocess.run(["sh", str(ROOT / "scripts" / "arena-play.sh"), "--stops", "sideways"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
