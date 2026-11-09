"""The scripts around the table: arena-autostop.sh (a table that has clearly concluded is torn down without a
hand stop; a hand stop always wins), arena-config.py's launch banner (every knob the code reads is listed with
the code's default, every row is in the README, no secret is printed, the first lines tell the truth about the
relay and the spectator table's voices), arena-hygiene.py's block and its grounding score, the packager (it
ships every script the shipped scripts call, refuses a voice tree with a promised take missing), arena-play.sh
`--stops restore`, and arena-add-deck.py's quantity rule. Run: python3 -m unittest discover -s tests"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path(__file__).resolve().parent.parent.parent


AUTOSTOP = Path(__file__).resolve().parents[2] / "scripts" / "arena-autostop.sh"


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_add_deck():
    p = Path(__file__).resolve().parents[2] / "scripts" / "arena-add-deck.py"
    spec = importlib.util.spec_from_file_location("arena_add_deck", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AutostopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.state = d / "observer-state.json"
        self.gui_pid = d / "gui.pid"
        self.own_pid = d / "autostop.pid"
        self.mark = d / "stopped.marker"
        self.stop = d / "stop.sh"
        self.stop.write_text("#!/bin/sh\necho stopped > \"$ARENA_AUTOSTOP_TEST_MARK\"\nexit 0\n")
        self.stop.chmod(0o755)
        self.own_pid.write_text("12345")
        self.env = dict(os.environ,
                        ARENA_AUTOSTOP_STATE=str(self.state),
                        ARENA_AUTOSTOP_GUI_PID_FILE=str(self.gui_pid),
                        ARENA_AUTOSTOP_PID_FILE=str(self.own_pid),
                        ARENA_AUTOSTOP_STOP=str(self.stop),
                        ARENA_AUTOSTOP_POLL="0.2",
                        ARENA_AUTOSTOP_GUI_GONE_LINGER="0",
                        ARENA_AUTOSTOP_TEST_MARK=str(self.mark))

    def tearDown(self):
        self.tmp.cleanup()

    def _snapshot(self, over):
        tmp = self.state.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kind": "observer-snapshot", "turn": 9, "gameOver": over}))
        os.replace(tmp, self.state)

    def _run(self, linger="0"):
        return subprocess.Popen(["sh", str(AUTOSTOP), linger], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def test_game_over_lingers_then_runs_the_stop_command(self):
        self._snapshot(False)
        self.gui_pid.write_text(str(os.getpid()))          # a live "JVM"
        p = self._run(linger="1")
        time.sleep(0.6)
        self.assertIsNone(p.poll(), "still waiting while the game is on")
        self.assertFalse(self.mark.exists())
        self._snapshot(True)
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertTrue(self.mark.exists(), out)
        self.assertIn("match over", out)
        self.assertIn("stopping in 1s", out)
        self.assertFalse(self.own_pid.exists(), "its own PID file goes before it becomes arena-stop")

    def test_gui_jvm_gone_before_game_over_stops_the_table(self):
        self._snapshot(False)
        self.gui_pid.write_text("2147483000")              # no such process
        p = self._run()
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertTrue(self.mark.exists(), out)
        self.assertIn("GUI JVM gone", out)

    def test_table_already_stopped_is_left_alone(self):
        # arena-stop cleared the snapshot and every PID file: nothing to do
        p = self._run()
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertFalse(self.mark.exists(), "a hand stop always wins — no second stop")
        self.assertIn("already stopped", out)
        self.assertFalse(self.own_pid.exists())

    def test_hand_stop_during_the_linger_means_no_second_stop(self):
        self._snapshot(True)
        self.gui_pid.write_text(str(os.getpid()))
        p = self._run(linger="2")
        time.sleep(0.8)
        self.state.unlink()                                 # what arena-stop does
        self.gui_pid.unlink()
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertFalse(self.mark.exists(), out)
        self.assertIn("stopped by someone else", out)

    def _voice(self, age_s=0):
        vd = Path(self.tmp.name) / "seat-0-voice"   # beside the snapshot, as the script derives it
        vd.mkdir(exist_ok=True)
        hb = vd / "heartbeat"
        hb.touch()
        if age_s:
            os.utime(hb, (time.time() - age_s, time.time() - age_s))
        return vd

    def test_a_live_voice_gets_its_sign_off_before_the_stop(self):
        # B5 (2026-09-14): the heartbeat's age is read portably (os.stat via python3), not BSD stat
        self._snapshot(True)
        self.gui_pid.write_text(str(os.getpid()))
        vd = self._voice()
        env = dict(self.env, ARENA_AUTOSTOP_VOICE_WAIT="6", ARENA_AUTOSTOP_AFTER_VOICE="0")
        p = subprocess.Popen(["sh", str(AUTOSTOP), "0"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(1.0)
        self.assertIsNone(p.poll(), "a fresh heartbeat: the watcher waits for the voice's final sequence")
        self.assertFalse(self.mark.exists())
        (vd / "final.json").write_text("{}")
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertTrue(self.mark.exists(), out)
        self.assertIn("voice finished its sign-off", out)

    def test_a_stale_voice_heartbeat_is_not_waited_for(self):
        self._snapshot(True)
        self.gui_pid.write_text(str(os.getpid()))
        self._voice(age_s=60)
        env = dict(self.env, ARENA_AUTOSTOP_VOICE_WAIT="6")
        t0 = time.time()
        p = subprocess.Popen(["sh", str(AUTOSTOP), "0"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertTrue(self.mark.exists(), out)
        self.assertNotIn("voice finished", out)
        self.assertLess(time.time() - t0, 5.0, "a dead voice is not waited for")

    def test_linger_must_be_a_whole_number(self):
        p = subprocess.run(["sh", str(AUTOSTOP), "soon"], env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10)
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIn("whole number", p.stdout)

    def test_before_the_match_is_live_the_watcher_keeps_waiting(self):
        # snapshot not yet written but the GUI PID is alive: launch in progress
        self.gui_pid.write_text(str(os.getpid()))
        p = self._run()
        time.sleep(0.7)
        try:
            self.assertIsNone(p.poll(), "no snapshot + live JVM is 'not started yet', not 'stopped'")
        finally:
            p.kill()
            p.communicate(timeout=5)


class LaunchBanner(unittest.TestCase):
    IGNORE = {"ARENA_RATE_VOIDED", "ARENA_OAI_API_KEY", "ARENA_HUMAN_DECK", "ARENA_MAILBOX_DIR", "ARENA_ADVISOR",
              "ARENA_AUTOSTOP_STATE", "ARENA_AUTOSTOP_STOP", "ARENA_AUTOSTOP_PID_FILE", "ARENA_AUTOSTOP_GUI_PID_FILE",
              "ARENA_STOPS", "ARENA_VOICE_ID",
              "ARENA_RELAY", "ARENA_VOICE_RUNNER"}          # launcher -> GUI plumbing (relay-only advisor, voice runner present), not knobs

    def _observed(self):
        seen = {}
        py = re.compile(r'environ\.get\("((?:ARENA|SEAT)_[A-Z_]+)"(?:,\s*"([^"]*)")?\)')
        sh = re.compile(r'\$\{((?:ARENA|SEAT)_[A-Z_]+)(?::-([^}]*))?\}')
        files = list((ROOT / "runner").glob("*.py")) + list((ROOT / "runner" / "seatd").glob("*.py")) \
            + list((ROOT / "runner" / "voice").glob("*.py")) \
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
        java_read = {"ARENA_AUTOPASS_RESOLVE_OWN", "ARENA_VOICE_FOCUS",
                     "ARENA_SELF_SPELL_WINDOW"}                                           # read by the Java side (AutopassPolicy, VAdvisor, MailboxController)
        stale = {n for n in table if n.startswith("ARENA_") and n not in seen and n not in self.IGNORE and n not in java_read}
        self.assertEqual(stale, set(), "banner rows for knobs nothing reads any more (retire the row; critic 2026-09-16)")

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


class LaunchBannerModeLines(unittest.TestCase):
    """2026-09-16: the banner's first lines tell the truth about the relay and the spectator table's voices."""

    def _args(self, **kw):
        import argparse
        base = dict(mode="", deck="", model="opus", effort="medium", timeout="90", advisor="", voice="", stops="", linger="60", autostop="1", out="")
        base.update(kw)
        return argparse.Namespace(**base)

    def test_human_line_names_the_relay_and_the_spectator_line_names_the_voices(self):
        cfg = _load_script("arena-config")
        env = {"ARENA_CHATTER": "rowdy", "ARENA_SEAT_DECKS": "urza-lord-high-artificer giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds"}
        human_off = cfg.render(self._args(mode="human", deck="selvala-heart-of-the-wilds", advisor="0", voice="on"), env)
        self.assertIn("advisor off (table relay on)", human_off)
        human_on = cfg.render(self._args(mode="human", deck="selvala-heart-of-the-wilds", advisor="1", voice="on"), env)
        self.assertIn("advisor on |", human_on)
        allai = cfg.render(self._args(mode="all-ai", voice="on"), env)
        self.assertIn("spectator: four brains, no advisor | voice on (chatter rowdy, barks some)", allai)
        self.assertIn("voices Urza=Bill, Giada=Lily, Purphoros=Harry, Selvala=Joshua", allai)
        self.assertNotIn("human game (advisor", allai, "the human section is skipped for four brains")
        allai_mute = cfg.render(self._args(mode="all-ai", voice="off"), env)
        self.assertIn("| voice off |", allai_mute)


class HygieneBlock(unittest.TestCase):
    def test_counts_and_the_loud_line(self):
        hy = _load_script("arena-hygiene")
        d = Path(tempfile.mkdtemp(prefix="hy-"))
        rows = [{"seat": 1, "gameId": "g", "source": "model", "latency_s": 2.0}, {"seat": 1, "gameId": "g", "source": "model", "latency_s": 4.0},
                {"seat": 2, "gameId": "g", "source": "memo"}, {"seat": 2, "gameId": "g", "source": "punt", "deviation": "x"}]
        (d / "game.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        (d / "seat-1.log").write_text("ok\n[seat 1] INTERNAL ERROR in handle()\nTraceback (most recent call last)\n[seat 1] session rotated #1 in 3s\n")
        (d / "run_table.out").write_text("[seat 1] INTERNAL ERROR in handle()\nTraceback (most recent call last)\n[seat 1] runner exited (1) — restarting in 2s\n")
        (d / "voice-0.jsonl").write_text(json.dumps({"event": "spoke"}) + "\n" + json.dumps({"event": "live-paused"}) + "\n"
                                         + json.dumps({"event": "spoke", "kind": "bark", "seat": 2}) + "\n"
                                         + json.dumps({"event": "skipped", "kind": "bark", "why": "dice"}) + "\n")
        text, ok = hy.report(str(d))
        self.assertFalse(ok)
        self.assertIn("decisions 4 | model 2 (50%) | runner-answered 1 (memo 1) | punts 1 | deviations 1", text)
        self.assertIn("tracebacks 2", text, "seat log only — run_table.out echoes are not counted twice")
        self.assertIn("restarts 1", text); self.assertIn("rotations 1", text)
        self.assertIn("voice: spoke 2", text)
        self.assertIn("barks spoke 1 / skipped 1 / dropped 0", text)
        self.assertIn("!! HYGIENE: punts (game log) 1, tracebacks 2, voice live paused 1", text)
        clean = Path(tempfile.mkdtemp(prefix="hy2-"))
        (clean / "game.jsonl").write_text(json.dumps({"seat": 1, "gameId": "g", "source": "model"}) + "\n")
        text, ok = hy.report(str(clean))
        self.assertTrue(ok); self.assertIn("OK: no punts", text)

    def test_voice_restarts_pace_gaps_and_ids(self):
        """C3 + observability (2026-09-14): restarts from every supervisor log; the gap
        distribution, pace and anchored share beside Ben's targets; ids spoken vs held."""
        hy = _load_script("arena-hygiene")
        d = Path(tempfile.mkdtemp(prefix="hy3-"))
        (d / "game.jsonl").write_text(json.dumps({"seat": 1, "gameId": "g", "source": "model"}) + "\n")
        (d / "run_table.out").write_text("[seat 1] runner exited (1) — restarting in 2s\n")
        (d / "voice_runner.out").write_text("[voice] runner exited (1) — restarting in 2s\n[voice] runner exited (0) — restarting in 2s\n")
        spoke = [dict(ts=100.0, seconds=2.0, kind="startup", stock="startup", library="", source="startup"),
                 dict(ts=110.0, seconds=3.0, kind="bark", stock="taunt", library="harry", seat=1, source="event"),
                 dict(ts=150.0, seconds=1.0, kind="bark", stock="pass", library="harry/table", seat=1, source="floor"),
                 dict(ts=155.0, seconds=2.0, kind="bark", stock="taunt", library="harry", seat=1, source="card")]
        (d / "voice-0.jsonl").write_text("".join(json.dumps(dict(event="spoke", **s)) + "\n" for s in spoke))
        text, _ = hy.report(str(d))
        self.assertIn("restarts 3", text, "run_table.out + voice_runner.out")
        # gaps: 110-102 = 8, 150-113 = 37, 155-151 = 4 -> sorted 4, 8, 37; span 57 s for 4 lines
        self.assertIn("voice pace: 3.2 seat lines/min (target 8) | anchored 67% (target 60%) | "
                      "gaps median 8.0s p90 8.0s max 37.0s | 37s inside 1 gap(s) over 24s", text)
        self.assertIn("voice ids: 3 distinct spoken", text)
        if (ROOT / "runner" / "voice" / "stock" / "voices" / "harry" / "table" / "manifest.json").exists():
            self.assertRegex(text, r"voice ids: 3 distinct spoken / \d+ available \(harry, harry/table\)")
        self.assertTrue(callable(hy.anchored), "one named rule, to be swapped for the shared classify() (plan C2)")
        self.assertTrue(hy.anchored({"source": "event"})); self.assertFalse(hy.anchored({"source": "floor"}))


class HygieneGrounding(unittest.TestCase):
    def test_the_grounding_score_from_a_synthetic_archive(self):
        import importlib.util, tempfile
        spec = importlib.util.spec_from_file_location("hy", Path(__file__).resolve().parents[2] / "scripts" / "arena-hygiene.py")
        hy = importlib.util.module_from_spec(spec); spec.loader.exec_module(hy)
        d = Path(tempfile.mkdtemp())
        (d / "game-1.json.rated").write_text(json.dumps({"placementGroups": [[3], [1], [0, 2]]}))
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
            {"kind": "cast", "turn": 5, "seat": 1}, {"kind": "cast", "turn": 5, "seat": 1}, {"kind": "cast", "turn": 6, "seat": 3}]))
        voice = [{"event": "spoke", "kind": "bark", "stock": "kill-that", "target": 3, "turn": 5, "ts": 1.0},     # the winner
                 {"event": "spoke", "kind": "bark", "stock": "youre-the-threat", "target": 1, "turn": 5, "ts": 2.0},  # the turn's busiest seat
                 {"event": "spoke", "kind": "bark", "stock": "hit-giada", "target": 2, "turn": 6, "ts": 3.0},          # neither
                 {"event": "spoke", "kind": "bark", "stock": "nothing-happening", "turn": 6, "ts": 4.0}]              # not addressed
        lines = hy.grounding(str(d), voice)
        self.assertEqual(len(lines), 1)
        self.assertIn("grounding: 67% of 3 addressed lines named the winner or the turn's busiest seat (winner seat 3)", lines[0])
        self.assertEqual(hy.grounding(str(d), [{"event": "spoke", "kind": "bark", "stock": "taunt"}]), [], "no addressed lines: silent")


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
        self.assertIn("--exclude '/voice/stock/voices/*/raw/'", pk, "the seat voices' dry takes (~30 MB) must not ship either")
        self.assertIn("--exclude '/voice/stock/voices/*/*/raw/'", pk, "nor the table/cards sub-libraries' dry takes (round 31)")
        self.assertIn("--exclude '/voice/table_lines.py'", pk, "the wording generator is a dev tool like build_stock.py")
        self.assertIn("--exclude '/voice/card_lines.py'", pk)
        self.assertIn("--exclude '/voice/build_stock.py'", pk, "the ElevenLabs render tool is dev-only")
        for name in ("packaging/build-light-package.sh", "scripts/run-pilot-match.sh"):
            text = (ROOT / name).read_text()
            self.assertIn("BL-47", text, f"{name}: fat jar must be chosen by the pom revision (BL-47), not the first glob match")
            self.assertIn("<versionCode>", text, f"{name}: the revision is composed from the pom's versionCode + snapshotName")
            self.assertNotIn('$(ls "$REPO_ROOT"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar 2>/dev/null | head -n1)', text)
            self.assertNotIn('$(ls "$REPO"/forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar 2>/dev/null | head -n1)', text)
        self.assertIn("--exclude '.DS_Store'", pk)


class VoicePackagePreflight(unittest.TestCase):
    """C5 (2026-09-14): the packager refuses a tree where a manifest promises a take
    that is not there — <id>.wav for wording 1, <id>-N.wav for wording N (build_stock)."""
    def _dest(self):
        dest = Path(tempfile.mkdtemp(prefix="pkg-"))
        voices = dest / "forge-arena" / "runner" / "voice" / "stock" / "voices"
        harry = voices / "harry"; table = harry / "table"
        table.mkdir(parents=True)
        (harry / "manifest.json").write_text(json.dumps({"phrases": {"taunt": {"text": "one"}, "gg": {"text": ["a", "b", "c"]}}}))
        (table / "manifest.json").write_text(json.dumps({"phrases": {"pass": {"text": ["x", "y"]}}}))
        for name in ("harry/taunt", "harry/gg", "harry/gg-2", "harry/gg-3", "harry/table/pass", "harry/table/pass-2"):
            (voices / f"{name}.wav").write_bytes(b"RIFF")
        (harry / "raw").mkdir(); (harry / "raw" / "taunt.wav").write_bytes(b"RIFF")   # a raw dir has no manifest: ignored
        return dest, voices

    def test_missing_takes_are_named_and_fail_the_script(self):
        chk = importlib.util.spec_from_file_location("check_voice_takes", ROOT / "packaging" / "check-voice-takes.py")
        mod = importlib.util.module_from_spec(chk); chk.loader.exec_module(mod)
        dest, voices = self._dest()
        self.assertEqual(mod.missing_takes(str(dest)), [])
        r = subprocess.run([sys.executable, str(ROOT / "packaging" / "check-voice-takes.py"), str(dest)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        (voices / "harry" / "gg-3.wav").unlink(); (voices / "harry" / "table" / "pass.wav").unlink()
        self.assertEqual(mod.missing_takes(str(dest)), ["harry: gg-3", "harry/table: pass"])
        r = subprocess.run([sys.executable, str(ROOT / "packaging" / "check-voice-takes.py"), str(dest)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1); self.assertIn("harry: gg-3", r.stderr); self.assertIn("harry/table: pass", r.stderr)
        (voices / "harry" / "manifest.json").write_text("{broken")
        self.assertTrue(any("unreadable" in m for m in mod.missing_takes(str(dest))))
        empty = Path(tempfile.mkdtemp(prefix="pkg0-"))
        r = subprocess.run([sys.executable, str(ROOT / "packaging" / "check-voice-takes.py"), str(empty)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1, "no voice tree at all is a broken package, not a pass")

    def test_the_packager_runs_the_preflight_after_the_voice_tree_is_copied(self):
        pk = (ROOT / "packaging" / "build-light-package.sh").read_text()
        i_copy, i_check, i_next = pk.index("[7/9] runner"), pk.index('check-voice-takes.py" "$DEST"'), pk.index("[8/9] scripts")
        self.assertTrue(i_copy < i_check < i_next, "the check runs once the runner tree (voices included) is in DEST")
        self.assertIn("|| { echo \"ERROR: voice takes missing", pk, "a failed check ends the build")


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


class ImporterQuantityRule(unittest.TestCase):
    def test_leading_numbers_that_cannot_be_counts_are_names(self):
        mod = _load_add_deck()
        d = Path(tempfile.mkdtemp()) / "t.dck"
        d.write_text("[metadata]\nName=T\n[Commander]\n1 Sheoldred, the Apocalypse\n"
                     "[Main]\n3x Forest\n2 Swamp\nForest\n1996 World Champion\n"
                     "1 Sol Ring|C21|1\n")
        parsed = mod.parse_dck(str(d))
        cmdrs, main = parsed["commanders"], parsed["main"]
        self.assertEqual(cmdrs, [("Sheoldred, the Apocalypse", 1)])
        self.assertIn(("Forest", 3), main)
        self.assertIn(("Swamp", 2), main)
        self.assertIn(("Forest", 1), main)
        self.assertIn(("1996 World Champion", 1), main)
        self.assertIn(("Sol Ring", 1), main)
