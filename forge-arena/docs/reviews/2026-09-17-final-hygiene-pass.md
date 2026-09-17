# Final hygiene pass before the experimental cut (2026-09-17)

Ben: "We have written a ton of code and touched a lot of functionality in this branch. In a token
efficient way how can we look at all updates … for correctness, efficiency and elegance, while using
Gemini as a double check and perhaps 1 or 2 opus subagents, I want issues fixed and addressed only by
Fable 5.1 … This would be a final clean up pass before we fast forward main, after tagging it so we can
revert easily and then cutting an experimental release build." Then: "fix on the branch first, two opus
agents, go."

Scope: `experimental/voicework2` against `arena` (base 3e037fdc9a9) — 106 commits, 77 code files,
about 12,000 lines of new production code, 8,000 of tests, 2,000 of docs. Safety tag on `arena`:
`pre-voicework2-ff-20260917`.

## Method (layered, cheapest reader first)

1. **Mechanical** (no model tokens): pyflakes over `runner/` and `scripts/`, `git diff --check`, a grep
   for debug prints and TODOs, `compileall`.
2. **Gemini (gemini-pro-latest)** as the wide reader: the production files in four chunks (voice core;
   brains + advisor; the Java diff; scripts + docs diff) with a strict findings-only brief. Its first
   pass ran out of output budget mid-thought; re-sent with a 65k budget.
3. **Two Opus subagents**, findings only, no edits: (a) the voice pipeline read fresh with the live game
   notes; (b) the Java ↔ Python file contract (control files, deal questions, Swing threading).
4. **Fable** verified every finding against the source before touching anything, fixed the real ones,
   declined the rest with a reason below. One suite run per batch; the FULL Maven gate once at the end.

## Findings and decisions

### Mechanical
- pyflakes: one dead local (`events.py` `gid`), fifteen unused imports/locals in eleven test files —
  removed. The many "unused" imports in `voice_runner.py` are the documented re-export surface the
  tests use as `vr.X` (`# noqa: F401`); left as is. Two `ratings.py`/`replay.py` locals predate the
  branch — out of scope.
- Two trailing blank lines at EOF — fixed. `TapSymmetryBreakTest`'s `System.out.println("SYM-MINE…")`
  matches the three diagnostics already in that file — kept for consistency.

### Gemini, first (truncated) pass — 6 findings, 3 real
| # | Claim | Verdict |
|---|---|---|
| A-F1 | `chains.plan_reply` resolves each role twice; a bystander is a dice roll, so the stale-sort and the pick can disagree | **Fixed** — resolved once |
| A-F2/F3 | `int(e.get("seq", 0))` raises on `"seq": null` | Declined — the Java writer stamps `seq` as a `long`; the checkpoint is ours |
| B-F1 | a counter lapses at the end of its turn but a proposal at the end of the next | Declined — by design and pinned by `test_counter_accept_and_refuse_write_control_files_and_lapse_at_turn_end` |
| B-F2 | the seat writes a deal answer twice to game.jsonl (DEAL record + attached to the decision record) | **Fixed on the reader** — the advisor's deal tick consumes only `type == "DEAL"`; the Executive branch had no dedupe and showed the player's answer twice |
| B-F3 | `_talk_hinted` never resets on a new game | **Fixed** |

### Gemini, second pass
- **B (brains + advisor): no findings.** "Exceptionally clean… no correctness bugs, race conditions…"
- **C (Java): 3 findings, 1 real.** F1 `resolvingSeat()` peeks the wrong spell — declined: Forge
  resolves (`MagicStack.resolveStack` :660) before `finishResolving` removes the instance (:681), so the
  resolving spell IS the top of the stack. F2 `followVoice` yanks the tab back every 250 ms if the
  player clicks away mid-line — **fixed** (once per line; the player's click stands). F3
  `JOptionPane.getRootFrame()` is a hidden 0×0 frame — declined: `FView` sets it to the main window
  (`JOptionPane.setRootFrame(frmDocument)`), and Ben saw the pane bottom-right live.
- **D (scripts + docs): 2 findings, 0 real, 1 tidy.** F1 `ARENA_HUMAN_DECK` forced on an all-AI voice
  runner — the slug is empty in that mode, harmless; the duplicate variable was removed so the voice
  runner takes the table from `$ALL` exactly like the seats. F2 "`load_seat_libraries` was renamed" —
  false (the function exists; the banner test asserts the voices line).

### Opus reader A — the voice pipeline: 20 findings, 20 verified, 20 fixed (commit `b60facfb3b4`)
1 P1, 8 P2, 11 P3. The P1: on an all-AI table a leftover `human_out` record put `None` into
`eliminated`, every later `int()` raised inside `save_state()` (called before `speak()`), and the runner
fell silent for the run. The P2s: `answered_at` not rebased on restore (the game-58 grace window was
wrong after a hot swap); the cast-flurry stamps in wall time but filtered as monotonic; `enabled()`
parsing two control files every 200 ms during playback; the floor-atom guard unreachable so a
backchannel could talk over it; malformed ring events swallowed without a record; `final.json` from a
killed run satisfying the once-guard (autostop then tore the next table down at gameOver);
`variants()` globbing per call on every line; three inbox scans twice a second. The P3s: narrations
uncounted off-turn, `_stack_seen` not checkpointed, dead `ring_seq`/`heckled` fields, a quadratic
replay window, the log read twice at start, `sfx()` off the seeded rng, a redundant queue test, the
eviction audit aliasing the live list, the weighted pick's zero-total path. The verbatim report is
below as Appendix A.

### Opus reader B — the Java ↔ Python contract: 14 findings, 11 fixed, 2 declined, 1 "keep"
| # | Claim | Verdict |
|---|---|---|
| F1 P1 | with `--no-voice` nobody consumes the offer pane's accept/refuse files: the player is told a deal exists that no seat honours | **Fixed** — `--no-voice` now means *muted, never absent*: `arena-play.sh` always starts the runner (it owns the ledger) and writes the mute file first; the muted runner scans the game log and the deal control files; README, config banner, INTERACTIVE-ARENA updated |
| F2 P2 | the 16-bit patch's WAV header declares 2× the data (the converter writes the byte count as the frame count; invisible at 8-bit) | **Fixed** — `withTrueLength` rewrites the container from the decoded samples; `AudioDecodeFormatTest` now asserts header == data |
| F3 P2 | `DECODE_FORMAT` also forces mono/44.1 kHz, undocumented | Mono 44.1 kHz was the converter's own default — no behaviour change; comment states it; `button_press` (32 kHz) and `coins_drop` (48 kHz) added to the test |
| F4 P2 | the pane discards the offer_id: Accept answers the seat's *newest* offer | **Fixed** — the ask file carries `offer_id`; `_answer_counter` answers that offer; a typed answer still means the newest |
| F5 P2 | handles collide (`swords-plunder` and `-gc` are both `rev`) | **Fixed** — the later seat's handle carries its number (`rev2`), aliased |
| F6 P2 | an unanswerable answer left the question file, the pane stuck at "Sending…" | **Fixed** — a stale id drops the file ("no longer open") |
| F7 P2 | the pane not gated on `relayAttached()` like the chat row | **Fixed** |
| F8 P2 | both Swing timers never stopped; the focus timer runs with no voice runner | Focus timer starts only when `voiceAttached()`; the never-stopped 1 s timer is the house pattern (`VAiControl`) — left |
| F9 P3 | an unparseable ask file re-read every poll forever | **Fixed** — dropped once 2 s old, recorded |
| F10 P3 | `DealQuestion` recompiles ten regexes per file per second on the EDT | **Fixed** — cached |
| F11 P3 | six tiny file reads per second on the EDT | Declined — negligible at 1 Hz; not worth the mtime plumbing before a cut |
| F12 P3 | three hand-rolled flat-JSON readers | Declined for this cut — a refactor of working code; noted as a follow-up |
| F13 P3 | relay-only pane says "Joshua is weighing it…" forever | **Fixed** — "the advisor is off — your call" |
| F14 | `SYM-MINE` println | Keep — matches the file's three existing diagnostics |
Verified clean by the reader: temp+rename on every writer, `.tmp` filtered by every reader, the regex
parser vs `json.dumps` escapes, double-answer guards, stale-file clearing across games, EDT-only pane
access, no focus steal, the relay/voice flags match the scripts.

### Gemini — voice core (chunk A)
The first pass returned three truncated findings (above). The full re-send timed out twice at the API;
Opus reader A covered the same files line by line, so the chunk was not sent a third time.

## Result
- Commits: `b60facfb3b4` (pass 1: voice pipeline + mechanical + Gemini's early finds), pass 2 (this
  file, the contract batch, the launcher rule, the audio header).
- Python suite 713 OK; the FULL Maven gate on the final Java.
- Follow-ups (not blockers): share the three flat-JSON readers; stop the Swing timers at match end.

## Appendix A — Opus reader A, verbatim
# Voice pipeline review — runner/voice/{scheduler,events,renderer,table,atoms}.py, chains.py, voice_runner.py
Branch experimental/voicework2, read fresh 2026-09-17. Read-only; nothing edited, no tests run.

---

### F1 [P1] [correctness] runner/voice_runner.py:455 — the log-memory writes `None` into `eliminated` on an all-AI table, and every later `int(s)` over that set raises, so the runner stops speaking for the rest of the run

Evidence:
```python
# voice_runner.py:187
self.human_seat = None if os.environ.get("ALL_SEATS") == "1" else 0
# voice_runner.py:454-455  (_log_memory)
            if r.get("kind") == "human_out":
                out["eliminated"].add(self.human_seat)
```
With `ALL_SEATS=1` (`scripts/arena-play.sh:108`, `[ "$MODE" = "all-ai" ] && ALL="ALL_SEATS=1"`) `self.human_seat` is `None`, so a leftover `human_out` `spoke` record inside `LOG_MEMORY_S` puts `None` into `mem["eliminated"]`. `_adopt_state` then does `self.eliminated |= set(mem_dead)` (voice_runner.py:618) and `self._seen_seats |= set(mem_dead)` (:619). From then on:
```python
# voice_runner.py:513  (_durable_state, called at the TOP of save_state, outside its try)
            "eliminated": sorted(int(s) for s in self.eliminated),
```
`int(None)` -> `TypeError`, and `save_state()` is called at voice_runner.py:962 **before** `self.speak(item)` at :963 — the item has already been popped by `next_item()`, so every line is consumed and lost, one "step error" per tick from `run()`'s `except Exception` (:1021). `scan_observer` fails first for the same reason (`dying = [int(s["seat"]) ...]`, events.py:1165, over the synthetic `{"seat": None, "vanished": True}` row built at events.py:1164).
Reachability: needs an unarchived `runner/logs/voice-0.jsonl` from a human game (arena-stop.sh:86 moves it away, so it takes a kill/crash) followed by an all-ai launch inside 600 s. The failure mode once reached is total, permanent silence.

Fix: `if r.get("kind") == "human_out" and self.human_seat is not None:` at voice_runner.py:454.

---

### F2 [P2] [correctness] runner/voice_runner.py:707 — `answered_at` is the one clock map `_restore_state` does not rebase, so the advice grace window is wrong after a restart

Evidence: every neighbouring field goes through the rebasing helper `t()`; this one does not:
```python
705        self._casts = {int(s): [t(x) for x in v if t(x) is not None] for s, v in get("casts", dict).items()}
706        self.answered = {int(x) for x in get("answered", list)}
707        self.answered_at = {int(k): float(v) for k, v in get("answered_at", dict).items()}
708        self.last_spoken_at = t(state.get("last_spoken_at"), now)
```
The docstring two lines above promises "clocks rebased by shift = now - saved clock - (wall now - wall saved)". The consumer is the game-58 grace path:
```python
# voice/scheduler.py:434-437
                since = now - getattr(self, "answered_at", {}).get(q["seq"], -1e9)
                grace = float(getattr(self, "advice_grace", 0.0))
                if since > grace:
                    self.record("dropped", kind="advice", why=...)
```
With a non-zero shift (a replay clock, a test clock, any clock base that is not system uptime) `since` is meaningless: negative -> every answered advice line plays late; large -> the grace never applies. `self.answered` (:706) is also never pruned or aged — it grows for the whole game and is written out whole by `_recency_state` (:561), unlike `answered_at`, which *is* filtered by `STATE_RECENT_S` (:562). The two maps are keyed identically and should age together.

Fix: `self.answered_at = {int(k): t(v) for k, v in get("answered_at", dict).items() if t(v) is not None}` and drop from `self.answered` any seq that has no surviving `answered_at` entry.

---

### F3 [P2] [correctness] runner/voice_runner.py:560 — `_casts` holds wall-clock stamps but is filtered with the monotonic clock and rebased with the monotonic shift

Evidence: the writer stamps wall time —
```python
# voice/events.py:986-988
                    now_t = time.time()
                    recent = [t for t in self._casts.get(seat, []) if now_t - t < 30] + [now_t]
                    self._casts[seat] = recent
```
— and the checkpoint reads it as if it were `self.clock()`:
```python
# voice_runner.py:545, 560
        now = self.clock()
            "casts": {str(s): [x for x in v if now - x <= STATE_RECENT_S] for s, v in getattr(self, "_casts", {}).items()},
# voice_runner.py:705 — then adds the MONOTONIC shift to those wall stamps
        self._casts = {int(s): [t(x) for x in v if t(x) is not None] for s, v in get("casts", dict).items()}
```
`self.clock()` is `time.monotonic` (uptime, ~1e5) and `x` is ~1.7e9, so `now - x` is about -1.7e9 and the `<= STATE_RECENT_S` filter is a no-op — the checkpoint keeps entries it means to drop. Three clock domains for one map; the flurry detector ("play-slower" at three casts in thirty seconds) is the thing that misreads after a restore.

Fix: make `_casts` monotonic (`self.clock()` in events.py:986-987, matching `_said_at`/`_bark_spoken_at`), which makes the :560 filter and the :705 rebase both correct as written.

---

### F4 [P2] [efficiency] runner/voice_runner.py:868 — `enabled()` re-reads and re-parses two JSON control files on every 200 ms playback poll and twice per tick

Evidence:
```python
# voice_runner.py:838-854 (enabled)
            if not bool(json.loads(self._control.read_text()).get("enabled", True)):
            adv = self._control.parent / "advisor.json"
            if adv.exists() and not bool(json.loads(adv.read_text()).get("enabled", True)):
```
Call sites, all uncached:
```python
# voice_runner.py:868 — polled every 0.2 s for the whole length of every line
            self.player.play(path, should_stop=lambda: not self.enabled())
# voice_runner.py:934-935 — publish_state() calls enabled() too, one line before step() does
        self.publish_state()
        self._step_enabled = on = self.enabled()
# voice/events.py:1294
        cur = {"live": live, "reason": reason, "enabled": self.enabled()}
```
That is 2 reads + 1 `exists()` per call: 6 filesystem ops per tick at idle (2 ticks/s) plus 3 every 200 ms while any line plays (~60 for a four-second line). `executive_on()` next door already has exactly the right pattern (`EXEC_MEMO_S`, scheduler.py:141/347-352); `enabled()` has none.

Fix: give `enabled()` the same short memo as `executive_on()` (stat-signature or a 0.2 s TTL), and pass `self._step_enabled` into `speak()`'s `should_stop` instead of re-reading — `_step_enabled` already exists for exactly this (:349).

---

### F5 [P2] [correctness] runner/voice/atoms.py:191 — the `_atom_main_until` guard can never fire; a backchannel timer can talk over a floor atom

Evidence: the window is opened and closed around a *blocking* play on the same thread:
```python
313            self._atom_seat_at[seat] = now
314            self._atom_main_until = now + self.atom_seconds(path)
315            try:
...
321            finally:
322                self._atom_main_until = 0.0
```
Its only reader is `_may_atom`, which runs on the main thread — the thread that is blocked inside `play(path)` for the entire window:
```python
191        if now < self._atom_main_until:                       # a floor atom is on the main channel
192            return False
```
The thread that *could* collide, `_backchannel_fire` (atoms.py:275-287), never consults `_may_atom` at all — it checks only `final_locked`, `eliminated` and `enabled()`. So the "never two atoms at once" rule documented at atoms.py:18-22 does not hold for floor-atom + pending-backchannel, and the guard written for it is unreachable.

Fix: have `_backchannel_fire` bail when `self.clock() < self._atom_main_until` (cheap, no lock needed — the main thread only ever raises it), or drop the field.

---

### F6 [P2] [correctness] runner/voice/events.py:1060 — the ring dispatcher swallows every `TypeError`/`ValueError` with no record, so a malformed engine event disappears silently

Evidence:
```python
1060            except (TypeError, ValueError):
1061                continue
1062            finally:
1063                self._ring_seq = None
```
The `try` covers the whole 180-line dispatch (events.py:877-1059), which is full of unguarded coercions on engine-written fields: `seat = int(e.get("seat"))` (:878, :906, :933), `int(e.get("power", 0))` (:879), `[int(x) for x in (e.get("defenders") or [])]` (:880), `int(e.get("n", 0))` (:1002). A `damage` event with a null `seat`, or a `left` with a non-numeric `n`, is dropped whole — no `record()`, no `say()` — while `self._event_seq` has already advanced past it (:870), so it is never reconsidered. This is precisely the class of loss BL-50/BL-56 were chased through the tapes for; the tape at :871 is written before the dispatch, so only the tape shows it happened.

Fix: `except (TypeError, ValueError) as e: self.record("skipped", kind="event", why=f"malformed ring event: {str(e)[:80]}", seq=seq, event_kind=kind); continue`.

---

### F7 [P2] [correctness] runner/voice/events.py:1324 — `publish_final`'s once-guard is "the file exists", which a previous game's leftover satisfies

Evidence:
```python
1322            f = d / "final.json"
1323            ...
1324            if not f.exists():
1325                f.write_text(json.dumps({"done": round(time.time(), 3)}))
1326                self.say("[voice] final sequence done — the table may be torn down")
1327                summary = getattr(self, "record_summary", None)
1328                if summary is not None:
1329                    summary()
```
Nothing in `VoiceRunner.__init__` clears `mailbox/seat-0-voice/final.json`; only `scripts/arena-stop.sh:86` (`rm -rf "$ROOT"/mailbox/seat-*`) does, so a killed or crashed run leaves it. The next game then (a) never writes the `summary` record hygiene reads, and (b) hands `scripts/arena-autostop.sh:77` an already-present `$VOICE_FINAL` the moment gameOver appears, so the table is torn down after `ARENA_AUTOSTOP_AFTER_VOICE` (5 s) without waiting for the sign-off — the exact wait Ben asked for after game 44.

Fix: unlink `final.json` in `VoiceRunner.__init__` (beside the heartbeat directory creation in `run()`, voice_runner.py:1006-1007), and keep a `self._final_published` flag as the in-process guard.

---

### F8 [P2] [efficiency] runner/voice/renderer.py:450 — `variants()` globs the library directory on every call, and it is on the hot path of every line, every swap and every atom

Evidence:
```python
447    def variants(self, pid: str, library: str = "") -> list[Path]:
449        d = (VOICES_DIR / library) if library else STOCK
450        files = [d / f"{pid}.wav"] + sorted(d.glob(f"{pid}-[0-9]*.wav"))
451        return [f for f in files if f.exists()]
```
One `glob` + N `exists()` per call, against directories that are shipped read-only and never change during a run. Callers: `stock()` (:453, every spoken line), `card_swap` (scheduler.py:720, every candidate bark that names a card), `address_swap` (scheduler.py:743, every candidate bark in `ADDRESS_SWAP`), and `pick_atom` (atoms.py:160) — which calls it once **per candidate id**, so a floor atom is six globs and a backchannel three or four.

Fix: memoise on `(library, pid)` in `Renderer` (the manifests are already cached that way in `AtomsMixin.atom_ids`, atoms.py:128-134).

---

### F9 [P2] [efficiency] runner/voice/events.py:838 — `mutter()` rescans every seat's inbox directory on every 0.5 s tick

Evidence:
```python
833        now = time.time()
834        for seat in self.seat_libraries:
837            try:
838                files = list((self.mailbox / f"seat-{seat}" / "inbox").glob("req-*.json"))
```
`mutter()` is called unconditionally from `step()` (voice_runner.py:957), so that is three directory scans plus a `stat()` per file, twice a second, for a line (`thinking`) that fires at most once per request. `slow_seats()` (events.py:648-662) and `_ai_deciding()` (:129-141) walk the same directories with the same pattern — three near-identical scan loops — but they at least sit behind gates.

Fix: one `_inbox_ages()` helper memoised for the tick (the pattern `human_turn()` already uses at scheduler.py:347-352), shared by `mutter`, `slow_seats` and `_ai_deciding`.

---

### F10 [P3] [correctness] runner/voice/events.py:693 — `narrate_cast` increments a throwaway dict when the caster has no `_turn_start` entry, so `NARRATIONS_PER_TURN` is not enforced off-turn

Evidence:
```python
693        st = self._turn_start.get(int(seat)) or {"narrations": 0}
694        if st["narrations"] >= NARRATIONS_PER_TURN or not self.table_ids:
695            return False
...
707        if self._bark(int(seat), pid, turn=turn, source="procedural", p=p, ctx=ctx):
708            st["narrations"] += 1
```
`_turn_start` is populated only for the seat whose turn it is (`turn_boundary`, events.py:737-739). A seat casting on someone else's turn — the `in-response` branch at :700-702 is written for exactly that — gets the literal `{"narrations": 0}`, so the check at :694 always passes and the increment at :708 is discarded. Today only the strict per-turn no-repeat rule (`source="procedural"` classifies as anchored, so `optional=False`) keeps the count down, which means the cap silently depends on there being one id per branch.

Fix: `st = self._turn_start.setdefault(int(seat), {"lands": 0, "casts": 0, "narrations": 0})`.

---

### F11 [P3] [correctness] runner/voice_runner.py:238 — `_stack_seen` is not in the checkpoint, so a restart re-fires `hold-on` (and re-evaluates deal breaks) for stack items already dispatched

Evidence: the set is the only thing preventing a repeat, and it is cleared only when the stack empties:
```python
# voice/events.py:762-774
        if not detail:
            self._stack_seen.clear()
            return
...
            if key in self._stack_seen or not targets:
                continue
            self._stack_seen.add(key)
```
`_durable_state()` (voice_runner.py:512-540) lists eighteen per-game memories — `gc_cast_seen`, `combos_done`, `card_events_turn`, `thought` — but not `_stack_seen`. A runner hot-swapped while something sits on the stack re-announces "hold on, which one?" for it. (The deal-break path at events.py:776-785 is saved by `deal_forbids` returning False once the deal is popped, so only the `hold-on` line repeats.)

Fix: add `"stack_seen": sorted([...] for key in self._stack_seen)` to `_durable_state`, or accept it and say so in the comment at voice_runner.py:238.

---

### F12 [P3] [dead-code] runner/voice_runner.py:563 — `ring_seq` is written into every checkpoint and never read back, and is always `None` when it is written

Evidence:
```python
563            "ring_seq": self._ring_seq,
```
`_ring_seq` is set at events.py:875 (`self._ring_seq = seq`) and cleared in the `finally` at events.py:1063, so it is non-`None` only inside `scan_events`'s dispatch — never at a `save_state()` call site (voice_runner.py:951, :962, :966). `/usr/bin/grep -rn '"ring_seq"'` across `runner/` and `runner/tests/` returns this one line; `_restore_state` (voice_runner.py:623-727) never reads the key.

Fix: delete the entry from `_recency_state`.

---

### F13 [P3] [dead-code] runner/voice_runner.py:538 — `heckled` is written into the *durable* set (so it forces extra checkpoint writes) but `_restore_state` overwrites it with 0 regardless

Evidence:
```python
538            "heckled": int(getattr(self, "_heckled", 0) or 0),
```
versus
```python
681        self._heckled = 0                                     # the wait restarts from this snapshot: no "there you are" for a move nobody made
```
The decision at :681 is deliberate and right, but the value still rides in `_durable_state()`, whose JSON is the save signature (`sig = json.dumps(durable, sort_keys=True, ...)`, :574): each heckle stage change therefore forces an immediate atomic rewrite of the whole checkpoint for a field nobody will read.

Fix: drop the key, or move it to `_recency_state` if it is wanted for post-hoc log reading.

---

### F14 [P3] [efficiency] runner/voice_runner.py:1085 — `--replay` rescans the whole archived event list once per tape record (quadratic)

Evidence:
```python
1085    ring = [] if hi is None else [e for e in events if isinstance(e.get("seq"), int) and (lo is None or e["seq"] > lo) and e["seq"] <= hi]
```
called from the tape loop at :1170 (`vr.scan_observer(_snapshot_from_tape(rec, events, prev_seq, hi))`) for every record of `observer-tape.jsonl`. Both lists are the size of a whole game — a 90-minute archive is thousands of tape records against thousands of ring events, so this is O(tape x events) for a window that only ever moves forward.

Fix: sort `events` by `seq` once and walk it with a cursor alongside `prev_seq` (the `feed()` helper at :1131-1140 already does exactly this for the two stamped logs).

---

### F15 [P3] [efficiency] runner/voice_runner.py:973 — start-up reads `voice-0.jsonl` twice in full, once for the memory and once to count `up` records

Evidence:
```python
# voice_runner.py:425 (_log_memory, called from __init__:354)
            raw = self._jsonl.read_bytes()
# voice_runner.py:972-975 (record_up, called from run():1017)
            for line in self._jsonl.read_text().splitlines():
                if '"event": "up"' in line:
                    earlier += 1
```
`_log_memory` already iterates every line of that file with `json.loads` on the interesting ones. A game's `voice-0.jsonl` is one `record()` per decision — tens of thousands of lines by the endgame, and a restart pays for it twice.

Fix: count `"event": "up"` inside `_log_memory`'s existing loop and return it as `mem["restarts"]`.

---

### F16 [P3] [correctness] runner/voice/renderer.py:479 — `sfx()` draws from the module-global `random`, not the renderer's seeded `self.rng`

Evidence:
```python
478            return None
479        p = STOCK / "sfx" / random.choice(names)
```
`Renderer.__init__` takes and stores `rng` (`self.rng = rng or random.Random()`, :386) and every other draw uses it (`self.rng.shuffle(bag)`, :466; `self.rng.choice` throughout the mixins). `VoiceRunner` passes its own `self.rng` in at voice_runner.py:192-193 and `replay()` seeds it (`vr.rng.seed(seed)`, :1123) on the strength of the docstring promise "deterministic under `seed`". The bleep choice escapes that.

Fix: `self.rng.choice(names)`.

---

### F17 [P3] [elegance] runner/voice/scheduler.py:1043 — `not self.queue` in the silence-floor test is always true; the function returned on a non-empty queue eleven lines earlier

Evidence:
```python
1025        if not self.patter_on or self.barks_mode == "off" or self.queue or self.final_locked:
1026            return
...
1043        breaking = silent_for >= floor and not self.queue
```
`self.queue` cannot have gained an item between :1025 and :1043 — nothing in `human_turn()`, `_patter_gap_s()` or the idle bookkeeping enqueues. The redundant clause reads as if the floor were defending against a race that the early return already settled.

Fix: `breaking = silent_for >= floor`.

---

### F18 [P3] [elegance] runner/voice/scheduler.py:393 — `before = self.queue` aliases the live list instead of copying it, so the eviction audit silently does nothing on two of the five branches

Evidence:
```python
393        before = self.queue
394        if kind == "bark" and not evict:
395            pass                                                            # a follow-on: it queues behind what is already pending
...
415        for q in before:
416            if q not in self.queue and q["kind"] in ("bark", "event"):     # game 48: Urza's "kill" vanished without a trace
```
The audit at :415-417 works only because the eviction branches happen to rebind `self.queue` to a *new* list. On the `pass` branch (:394-395) and for every kind that matches no branch (`startup`, `ask`, `game_over`, `human_out`, `event` with `evict=False`), `before is self.queue` and the loop is a no-op walk of the live queue. It also compares dicts by `==`, so two items with identical content mask each other.

Fix: `before = list(self.queue)`, and match by identity (`any(q is x for x in self.queue)`).

---

### F19 [P3] [efficiency] runner/voice/renderer.py:486 — `_trim_cache` stats each cache file up to four times

Evidence:
```python
486            files = sorted(self.cache_dir.glob("*.wav"), key=lambda f: f.stat().st_mtime)
488            total = sum(f.stat().st_size for f in files)
489            for f in files:
490                if now - f.stat().st_mtime > CACHE_MAX_AGE_S or total > CACHE_MAX_BYTES:
491                    total -= f.stat().st_size
```
One `stat` for the sort key, one for the size sum, one for the age test, one for the size decrement. The comment above says the cache reaches 173 MB in a week; at ~40 KB a line that is thousands of files, stat-ed four times at every daemon start.

Fix: build `[(f, f.stat()) for f in ...]` once and read `st_mtime`/`st_size` off it.

---

### F20 [P3] [correctness] runner/voice/scheduler.py:1079 — the weighted patter pick leaks its loop variables and relies on the loop body always breaking

Evidence:
```python
1077        total = sum(w for *_, w in cands)
1078        pick = self.rng.random() * total
1079        for speaker, pid, target, w in cands:
1080            pick -= w
1081            if pick <= 0:
1082                break
1083        said = self.maybe_bark(speaker, pid, turn=snap.get("turn"), ...)
```
`speaker`/`pid`/`target` are used after the loop. `cands` is guaranteed non-empty here (both branches above return on an empty pool), so it does not crash today — but `total` can be 0 when every surviving weight is 0 (`add()` at :961-965 divides by the speaker count, and `patter_candidates` filters after the weights are assigned), in which case `pick` is 0.0, `pick -= w` leaves 0.0, `0.0 <= 0` breaks on the first candidate — the pick is no longer weighted, it is just "the first one". Silent, not fatal.

Fix: `idx = self.rng.choices(range(len(cands)), weights=[c[3] for c in cands])[0]`, or guard `if total <= 0: return`.

## Appendix B — Opus reader B, verbatim
# Java↔Python contract review — experimental/voicework2 vs 3e037fdc9a9

Read-only pass over the offer-pane / voice-focus / deal-relay contract. Line numbers are the
current on-disk state (VAdvisor.java and arena-play.sh were edited by another session while this
review ran; those uncommitted edits are unrelated to the findings below).

---

### F1 [P1] [correctness] forge-arena/scripts/arena-play.sh:210 — with `--no-voice` in a human game nobody consumes the accept/refuse control files, so the offer pane's Accept is a dead end
Evidence: the voice runner is the *only* consumer of `logs/control/deal/<ts>-accept|refuse.json` —
`forge-arena/runner/voice/events.py:441` `d = self.logs / "control" / DEAL_CONTROL_DIR`, reached
only from `forge-arena/runner/voice_runner.py:956` `self.scan_deal_control()`; nothing else in
`runner/` touches that directory (`grep -rn DEAL_CONTROL_DIR`). But it is started conditionally:
```
210: if [ "$VOICE" != "off" ]; then
211:   nohup … "$ROOT/runner/run_voice.sh" …
```
Meanwhile the seats keep proposing (the advisor tails `game.jsonl` directly,
`advisor_runner.py:1315-1318` → `_on_seat_offer`), so the pane still opens, and the click still
"succeeds": `_answer_counter` writes the file (`advisor_runner.py:1268`), drops the question file
(1274) and prints `accept the offer: …` (1278). With no voice runner the deal is never struck —
no ledger record, no `deal-struck` note to the seat, so the seat's brain never learns it has a
truce, and `seatd/runner.py` keeps the offer in `_pending_offers`. The player is told a deal exists
that no seat will honour.
Fix: gate the offer pane and `_answer_counter` on a live ledger owner — e.g. refuse with a panel
line ("no voice runner: deals cannot be struck this game") when
`mailbox/seat-0-voice/state.json` is missing/stale — or have `arena-play.sh` refuse `--no-voice`
in human mode.

### F2 [P2] [correctness] forge-gui-desktop/src/main/java/forge/sound/AudioClip.java:65 — the 16-bit patch makes every decoded WAV header declare twice the data it contains
Evidence: `Converter.to()` builds the output with
`new AudioInputStream(new ByteArrayInputStream(b), getTargetFormat(), (long) b.length)` — it
passes the **byte** count as the **frame** count (verified from `javap -c` of
`com/sipgate/mp3wav/Converter.class`, jar `com.sipgate:mp3-wav:1.0.4`). That was harmless only
because the default target format is 8-bit mono (frameSize 1). Measured on `draw.mp3` through
jshell with the real jar:
```
 8bit chunk data size=12672 (bytes actually present after the chunk header=12672)
16bit chunk data size=50688 (bytes actually present after the chunk header=25344)
       declared frames=25344  frameSize=2  totalBytes=25388
```
Consumers that trust the header now over-read/over-allocate by 2×:
`AudioClip.java:218` sizes the line with `((int) stream.getFrameLength() * format.getFrameSize())`
= 50688 for a 25344-byte clip, and `clip.open(stream)` at 220 allocates the same. The new arbiter
only asserts `in.getFrameLength() > 0` (`AudioDecodeFormatTest.java:39`), i.e. it asserts the wrong
number is non-zero.
Fix: after `toByteArray()`, patch the RIFF/`data` chunk sizes to the real payload length (or build
the WAV from `AudioSystem.getAudioInputStream(DECODE_FORMAT, decoded)` directly), and change the
test to assert `frameLength * frameSize == data-chunk bytes`.

### F3 [P2] [correctness] forge-gui-desktop/src/main/java/forge/sound/AudioClip.java:61 — `DECODE_FORMAT` also forces mono and 44.1 kHz; the comment only claims a bit-depth change
Evidence: `private static final AudioFormat DECODE_FORMAT = new AudioFormat(44100f, 16, 1, true, false);`
under a comment that speaks only of "decode to 16-bit PCM". All 39 files in `forge-gui/res/sound`
are **2-channel** (`afinfo`), and three are not 44.1 kHz: `button_press.mp3` 32000 Hz,
`coins_drop.mp3` and `take_shard.mp3` 48000 Hz. So the patch silently downmixes every effect to
mono and resamples those three. I confirmed the conversion succeeds and the durations come out
right (jshell, all five sampled files decode to 44100/16/mono with sane frame counts), so this is
not a break — but it is an undocumented change of every effect's channel layout, and the arbiter
covers only `draw/shuffle/tap/nighttime`, all of them 44.1 kHz.
Fix: derive channels and sample rate from the source format and change only the bit depth
(`new AudioFormat(src.getSampleRate(), 16, src.getChannels(), true, false)`), or state the
downmix in the comment and add `button_press`/`coins_drop` to the test list.

### F4 [P2] [correctness] forge-arena/runner/advisor_runner.py:1260 — the offer_id makes the whole round trip and is then thrown away: the pane's Accept answers the seat's *newest* offer, not the one on screen
Evidence: the question file carries `offer_id` (`_question_write`, 1390) and Java keeps it
(`DealQuestion.offerId`), but the answer is the chat string alone —
`VDealOffer`/`VAdvisor.answerOffer` send `"@" + handle + " accept"` and discard `q.offerId`
(`DealQuestion.java:99-105`, `VAdvisor.java:290-295`). The runner then re-derives everything from
the seat:
```python
open_ = [(oid, o) for oid, o in self._offers.items() if o["seat"] == seat and o["status"] in ("countered", "proposed")]
…
oid, off = open_[-1]
```
Two live offers from one seat (a counter plus a fresh proposal) and the click answers the last one
inserted, whatever the pane is showing.
Fix: let the pane's buttons carry the id (an ask body field, or `@handle accept <offer_id>`) and
have `_answer_counter` prefer an explicit id, falling back to `open_[-1]` for typed answers.

### F5 [P2] [correctness] forge-arena/runner/advisor_runner.py:415 — handles are not unique, and a duplicate silently routes the pane's answer to the wrong seat
Evidence: `deal_table` builds `handles[seat] = str(entry.get("who") or first).lower()` (410) but
registers aliases with `if k not in aliases: aliases[k] = seat` (415-416) — first seat wins. The
shipped `runner/voice/stock/voices/address.json` already contains a collision:
`swords-plunder -> who "rev"` and `swords-plunder-gc -> who "rev"` (also `say` "Rev" for both). Seat
those two decks together and both question files carry `"handle": "rev"`; every Accept/Refuse from
the pane resolves to the lower seat, so one seat's offer is answered on the other seat's behalf (or
gets "no counter or offer from Rev is pending").
Fix: de-duplicate in `deal_table` — append the seat when a handle is already taken (`rev`, `rev2`),
since the panel line and the question file both quote `handles[seat]`.

### F6 [P2] [correctness] forge-arena/runner/advisor_runner.py:1261 — an unanswerable answer leaves the question file on disk and the pane stuck at "Sending…" forever
Evidence:
```python
if not open_:
    self._panel("table", f"no counter or offer from {name} is pending", turn)
    return                      # <- no _question_drop(oid)
```
The pane is one-shot and never recovers: `VDealOffer.send()` sets `sent = true`, disables all three
buttons and writes "Sending…" (`VDealOffer.java:69-81`) with no reset and no timeout, while
`VAdvisor.syncOffers` keeps `refresh()`ing it because the file is still there (`VAdvisor.java:263`).
Contrast the typed path, which does have a deadline (`ASK_PICKUP_MS`, `VAdvisor.java:239-242`).
Fix: drop the question file on every exit path of `_answer_counter` (or give `VDealOffer` the same
20 s pickup deadline that re-enables the buttons).

### F7 [P2] [correctness] forge-gui-desktop/src/main/java/forge/screens/match/views/VAdvisor.java:464 — the offer pane is not gated on `relayAttached()`, unlike the chat row it answers through
Evidence: `poll()` hides the chat row when nothing can answer —
`askRow.setVisible(… relayAttached())` (455) — and `syncAsk()` disables the field and button (229-234),
but `syncOffers()` (464 → 248) scans `control/deal/questions` unconditionally and opens a pane with
live Accept/Refuse buttons whose only channel is exactly that chat relay. Any question file left
in `logs/control` (a crash between games; `arena-stop.sh:86` is what normally clears it) opens a
fully interactive pane in a game with no relay, and the click writes an ask nobody reads.
Fix: `if (!AiControlFile.relayAttached()) { dispose any pane; return; }` at the top of `syncOffers()`.

### F8 [P2] [correctness] forge-gui-desktop/src/main/java/forge/screens/match/views/VAdvisor.java:497 — both polling timers are started and never stopped
Evidence:
```java
161:  refresh = new Timer(1000, e -> poll());
163:  focusTimer = new Timer(250, e -> followVoice());
…
497:  refresh.start();
499:  if (FOCUS_ON) { focusTimer.start(); }
```
There is no `stop()` anywhere in the file; nothing ends them at game over or when the match screen
goes away, so the panel keeps listing `control/deal/questions`, reading five control files a second
and re-reading `voice-speaking.json` four times a second for the life of the JVM. (`VAiControl`
has the same never-stopped 2 s timer, so the 1 s one is a pre-existing house pattern; the 250 ms
one is new on this branch.) The focus timer also runs with no voice runner attached — it is gated
on `ARENA_VOICE_FOCUS` only, never on `AiControlFile.voiceAttached()`, which exists for exactly
this on the mute button (`AiControlFile.java:177`).
Fix: stop both timers on the match-ending path (or in an `ICDoc` teardown), and start `focusTimer`
only when `voiceAttached()`.

### F9 [P3] [correctness] forge-arena/runner/advisor_runner.py:1074 — an unparseable ask file is never deleted, contradicting the docstring and the panel's "nobody picked up" message
Evidence:
```python
body = self._load(p)
if body is None:
    continue  # partial write — next poll
```
`_load` (868-872) returns `None` for `ValueError` as well as `OSError`, so a permanently malformed
file is re-read every poll for the rest of the game, while the docstring one line above promises
"a torn write is retried next poll and a malformed one is dropped, never re-read". The GUI mean-
while gives up after 20 s and prints "nobody picked up your question" (`VAdvisor.java:241`) on a
file that is still sitting there.
Fix: keep the retry window (unlink once the file is older than a couple of seconds and still
unparseable), mirroring `scan_deal_control`'s two-second rule in `voice/events.py:451`.

### F10 [P3] [efficiency] forge-gui-desktop/src/main/java/forge/arena/interactive/DealQuestion.java:115 — every field of every question file recompiles its regex, once a second, on the EDT
Evidence: `str()` and `numLong()` both do
`Pattern.compile("\"" + Pattern.quote(key) + "\"\\s*:\\s*…").matcher(json)` per call, and `parse()`
calls them ten times per file (79-87), from `list()` (57-75), from `syncOffers()` on the Swing
timer. The two sibling parsers cache theirs — `AiControlFile.java:61-62` (`MODEL_RE`, `EFFORT_RE`)
and `VoiceFocus.java:25-31` (`SEAT`, `UNTIL`, `ACTIVE`, `TAB_SEAT`).
Fix: a small `static final Map<String, Pattern>` (or ten named constants) in `DealQuestion`.

### F11 [P3] [efficiency] forge-gui-desktop/src/main/java/forge/screens/match/views/VAdvisor.java:460 — one poll tick does six file reads plus a directory listing on the EDT, re-reading files that rarely change
Evidence: `syncToggle()` reads `control/advisor.json`, `syncExecutive()` reads
`control/executive.json`, `syncMute()` reads `control/voice.json`, `syncAsk()` stats the pending
ask, `syncOffers()` lists `control/deal/questions` and reads every file in it, then
`tail.readNew()` reads the log — all inside the 1 s Swing timer (460-465), with
`followVoice()`'s `Files.readString` (361) on top four times a second.
Fix: skip the toggle/mute/executive reads when `lastModified()` has not moved (the pattern
`AiControlFile._control_mtime` already uses on the Python side), and only re-parse a question file
whose mtime changed.

### F12 [P3] [elegance] forge-gui-desktop/src/main/java/forge/arena/interactive/DealQuestion.java:112 — a third hand-rolled flat-JSON reader, deliberately not shared with `AiControlFile`
Evidence: `DealQuestion` carries `str`/`num`/`numLong`/`unescape` (114-171) while `AiControlFile`
carries `find`/`usageLong`/`usageDouble`/`jsonString` (339-394) and `VoiceFocus` a third set — all
three with the same "this module carries no JSON dependency" rationale in their javadoc
(`DealQuestion.java:18-19`). `DealQuestion`'s is the only one that handles escapes and `null`,
which is the one the other two would benefit from.
Fix: move the reader trio into one package-private helper the three share; no behaviour change.

### F13 [P3] [correctness] forge-gui-desktop/src/main/java/forge/arena/interactive/VDealOffer.java:45 — in relay-only games the pane promises an assessment that can never arrive
Evidence: `assessment = new FTextArea(q.assessment == null ? "Joshua is weighing it…" : q.assessment);`
(and the same string in `refresh()`, 85). But `_assess_deal` returns immediately when the runner is
relay-only (`advisor_runner.py:1547-1548`, "no brain to ask: the offer pane shows the terms without
a read"), and relay-only is exactly the `--no-advisor` human game the pane was extended to serve
(`arena-play.sh:194-201`, `arena.relay=1`). The player watches "Joshua is weighing it…" for the
life of the offer.
Fix: have `_question_write` set a sentinel (e.g. `"assessment": ""` vs a `"no_advisor": true` flag)
in relay-only mode and render "the advisor is off — your call" instead.

### F14 [P3] [dead-code] forge-arena/src/test/java/forge/arena/interactive/TapSymmetryBreakTest.java:242 — the `SYM-MINE` println is *not* a leftover
Evidence: every test in the class prints the same diagnostic shape —
`SYM-URZA` (210), `SYM-CLOCK` (269), `SYM-NEG` (297) predate the branch, and `SYM-MINE` (242) is
the new test following the same convention, each printing the assertion inputs before asserting.
Verdict: keep it. (If they are to go, they should all go together.)

---

## Checked and clean (no finding)
- **Torn reads**: every writer on both sides uses temp+rename — `_write_atomic`
  (`advisor_runner.py:1177-1181`, `.json.tmp` in the same dir), `publish_speaking`/`publish_state`
  (`voice/events.py:1284-1286`, `1301-1303`), and the Java writers
  (`AiControlFile.write`/`writeFlag`/`setExecutive`/`askAdvisor`, all `ATOMIC_MOVE`). Every reader
  filters the temp name out: `n.endsWith(".json")` (`DealQuestion.java:59`),
  `glob("*-accept.json")` (`events.py:443`), `p.suffix == ".json"` (`seatd/runner.py:477`),
  `name.startswith("ask-") and endswith(".json")` (`advisor_runner.py:1053-1054`).
- **Java regex vs what Python writes**: `json.dumps` escapes quotes and emits `\uXXXX`, and
  `DealQuestion.str`'s `(?:[^"\\]|\\.)*` plus `unescape` handle both (the `\u` bound at line 156 is
  exactly right, surrogate pairs included). No key of the question body can be spoofed from inside a
  string value, because an embedded `\"assessment\"` leaves a backslash where the regex needs a quote.
  `"turn"` does not match inside `"lapses_after_turn"` for the same reason. `"assessment": null` and
  a `null` `lapses_after_turn` both fall to the defaults.
- **Double answers**: the pane is one-shot (`VDealOffer.sent`), a second typed answer finds no open
  offer (`_answer_counter`, 1260-1263), and if an accept *and* a refuse file both land,
  `scan_deal_control` pops the counter on the first and records "unknown or expired offer" for the
  second (`events.py:467-471`).
- **Stale replay across games**: `arena-stop.sh:86` deletes `$LOGS/control/*`, `AdvisorRunner.__init__`
  calls `_clear_questions()` (554), and `_deal_tick` clears again at game over (1321-1322).
- **Swing threading / focus**: everything that touches the panes runs from the two Swing timers, i.e.
  on the EDT; `VDealOffer` is non-modal with `setFocusableWindowState(false)` (42), and
  `FDialog.dispatchKeyEvent` returns false for a non-modal window that is not focused
  (`FDialog.java:142`), so ESC and the match hotkeys stay with the game. `FDialog.setVisible(false)`
  removes the global key dispatcher, and `dispose()` calls it (169-173).
- **Flags**: `-Darena.relay=1` / `-Darena.voice=1` in `run-pilot-match.sh:112-113` match
  `AiControlFile.relayAttached()/voiceAttached()` and what `arena-play.sh:188-218` exports
  (`RELAY=1` only for a human game without an advisor; `ARENA_VOICE_RUNNER` from `VOICE != off`).
  The comments match the code.

# Pass 2 (2026-09-17, later): new lenses, higher bar

Ben: "I will want another pass, to ensure there is nothing else to find. Refuting or skipping items is
totally desirable and fine if the finding is weak, at a certain point we need to stop touching the code."
Bar: fix only a correctness finding with a concrete, reproducible failure; efficiency and elegance are
recorded and left alone. Two Opus readers, no Gemini.

## Reader C — adversarial regression read of today's three commits: 5 findings, 5 fixed
| # | Claim | Verdict |
|---|---|---|
| F1 P2 | the new `stack_seen` checkpoint row sorts lists whose owner may be `null` next to an int → `TypeError` inside `save_state()` before the line plays | **Fixed** — sort key `json.dumps` |
| F2 P2 | the new `focusSeat == seat` guard latches after a seat speaks with its own board in front; its next lines are never followed | **Fixed** — `focusSeat` forgotten when there is nothing to restore |
| F3 P2 | pass 1's unconditional `final.json` unlink at start revokes a signal autostop is polling for; the leftover it targeted is already removed by arena-stop | **Fixed** — unlink removed; the per-process flag stays |
| F4 P3 | pass 1's Gemini-driven "remove one copy" in `table_from_launcher` contradicts run_table.sh and GuiPilotMatch, which strip every copy and refuse to launch | **Fixed** — reverted to every copy; test updated |
| F5 P3 | the muted runner now discards seat lines it used to replay under the 10 s gate | **Fixed** — muted branch reads the game log with `voice=False` (DEAL records only) |
Verified clean by the reader: no stale callers of the removed mapping functions, the `enabled()` and inbox
memos (APFS mtime at ns; mute writes differ in size), the `variants()` memo, `_TapeRing`, the clock
rebases, `withTrueLength`, the offer_id round trip, the DEAL-only narrowing, the mute-before-start order.

## Reader D — six cross-process scenarios: 20 findings, 8 fixed, 12 declined
| # | Claim | Verdict |
|---|---|---|
| F1 P1 | the seat's truce guard matches `(seat N)`, a label the engine never writes (`defenderList` → `ge.getName()` = "Player One" / "<commander>-S<n>"); the seat attacks a truce partner un-warned and is then called an oath-breaker | **Fixed** — `_seat_of_label` reads the engine's shapes (and the old one); the test fixture now writes the engine's labels |
| F13 P3 | the same for a player among target options | **Fixed** by the same change |
| F4 P1 | a seat-to-seat offer that lapses is recorded as `{"accept": null}` with no party; the voice runner reads it as a refusal of an offer from the PLAYER and the panel says "Urza refuses" | **Fixed** — the lapse carries `with`/`terms`/`lapsed`; the voice runner ledgers it `expired` |
| F5 P1 | all-AI: `library_for_seat(None)` in the opening-window check → every step dies for the opening stall; table mute, nothing checkpointed | **Fixed** — one line; test |
| F14 P3 | all-AI always ends with Joshua's loss line | **Fixed** — no verdict line on a spectator table |
| F8 P2 | on unmute the advisor backlog replays (a twenty-minute-old advice line), `answered_at` stamped at read time defeats the grace | **Fixed** — the muted runner consumes and drops the advisor stream (matches the game-log policy); recorded |
| F9 P2 | `_ingest_notes` caps at three sentences and reads in filename order, so a `deal-struck`/`deal-lapsed` behind table talk is never applied to the maps | **Fixed** — deals (offers + state) rank before invites before talk; the order test still holds |
| F11 P2 | seats write offer notes to seat 0 that nobody reads in a human game; toggling Executive later ingests the stale pile and can strike a turn-8 truce at turn 24 | **Fixed** — the Executive sweeps seat 0's notes when it takes the seat |
| F2 P1, F6 P2, F7 P2, F10 P2 | a second game in one session without teardown: the voice runner and the relay-only advisor have no new-game reset, the advised advisor under-resets, the seats leave note files | **Declined as a group** — autostop tears the table down at game over and arena-play tears down before every launch, so two games in one session is outside the release's flow; root cause is that `ObserverSnapshot` writes no `gameId` — one follow-up item (BL-57) |
| F3 P1 | a voice restart seeds the game-log cursor at EOF, losing a DEAL written in the 2 s gap | Declined — `_restore_state` restores the `tails` cursor before the first game-log read of the step, so a same-game restart resumes where it stopped; only an unadoptable checkpoint falls to EOF, and replaying then is wrong anyway |
| F12 P2 | the seat never expires a deal itself | Declined — the voice runner now always runs (muted at worst) and pushes the lapse; F9 makes the note land |
| F15 P3 | restart after sign-off revokes final.json | Superseded by C-F3 |
| F16 P3 | quip guidance prompted while muted | Declined — tokens, not correctness |
| F17 P3 | `@urza truce 2` is one turn | Declined — off-grammar, and the echo line shows the correction |
| F18 P3 | the accept file's `counter` field is unread | Declined — harmless; documented shape |
| F19 P3 | an advisor restart clears the question directory | Declined — rare, recoverable by typing |
| F20 P3 | Executive `continue` starves the deal lane for one iteration | Declined — the loop returns |
Walked and sound (per the reader): the human/advised deal path end to end; relay-only; the all-AI
handshake to autostop; `--no-voice`; the checkpoint round trip field by field.

## Result of pass 2
Python suite 715 OK; FULL gate green. Follow-up BL-57: a `gameId` in `ObserverSnapshot` and a
new-game reset in the voice runner and the relay-only advisor (only matters without autostop).

## Appendix C — Reader C, verbatim
# Regression review — the three commits of 2026-09-17 on experimental/voicework2

Read-only adversarial pass over `f28f26ffd8e`, `b60facfb3b4`, `a5a87dc3e58` and the code
around every hunk. Only findings verified by reading the source are listed.

---

### F1 [P2] forge-arena/runner/voice_runner.py:542 — the new `stack_seen` checkpoint line raises `TypeError` on a stack whose items share a name but not an owner, which kills the step *before* the line is spoken

Scenario: the observer's `stackDetail` is built by `ObserverSnapshot.java:818`, which writes
`"owner": null` whenever `si.getActivatingPlayer()` is null (a trigger with no activating
player), and `"name"` from the *host card*. Two entries from the same host card — one with
`owner: null`, one with an int owner — both carrying non-empty `targets` are both admitted to
`_stack_seen` (`events.py:785-787` only rejects a repeat or an untargeted item; the
`owner is not None` test comes *after* the `.add`). `_durable_state()` then sorts a list of
`[str, owner, list]` rows; list comparison falls through to element 1 and compares `None` with
an `int`.

Verified: `sorted([['Bolt', None, ['seat 1']], ['Bolt', 2, ['seat 3']]])` →
`TypeError: '<' not supported between instances of 'NoneType' and 'int'`.

Blast radius is bigger than a lost checkpoint. In `step()`:

```python
item = self.next_item()
if item is not None:
    self.save_state(force=True)   # <- raises here
    self.speak(item)
```

`run()` swallows it as `[voice] step error: ...`, so for as long as that stack configuration
stands the runner **speaks nothing at all** and stops checkpointing — the exact "the runner fell
silent for the run" class of failure this pass was meant to close. The old durable value here
(`"heckled": int(...)`) had no such risk.

Evidence:
```python
"stack_seen": sorted([str(n), o, list(t)] for n, o, t in self._stack_seen),   # hold-on already said for these (hygiene pass)
```
```java
d.put("owner", owner != null ? owner.getId() : null);
```

Fix: `sorted(..., key=str)` (or `key=lambda r: (r[0], str(r[1]), r[2])`) at voice_runner.py:542.

Note while here: the round trip at voice_runner.py:654 restores `n` as the saved *string*, so a
`stackDetail` entry with no `"name"` (live key `None`, saved `"None"`) never matches its restored
key and earns a second "hold on" — the one case the hunk set out to prevent.

---

### F2 [P2] forge-gui-desktop/src/main/java/forge/screens/match/views/VAdvisor.java:390 — the new `focusSeat == seat` guard latches and is never cleared, so voice-follow stops working for a seat after it speaks once with its own tab in front

Scenario (all from `followVoice()`):

1. The restore branch ends a burst with `SDisplayUtil.showTab(home)` — `home` is the **active
   player's** field — and sets `focusSeat = -1`, `focusRestore = null`.
2. The active seat X now speaks its opener. `current == target` (X's board is already the
   selected tab), so the first early return runs: `focusSeat = seat; return;` — **`focusRestore`
   stays `null`.**
3. The table goes quiet. The restore block is guarded by `if (focusRestore == null) { return; }`
   *before* any reset, so `focusSeat` stays X indefinitely.
4. The player clicks another seat's tab. X speaks again: `current != target`, and the new guard
   `if (focusSeat == seat) return;` fires — the tab is **not** brought forward, and `focusSeat`
   is still X, so no later line from X is followed either, until some other seat speaks.

So the intended "the player clicked away — theirs to keep" becomes "X's board is never brought
forward again", which is a common path because step 2 (the active seat speaking while its own
board is in front) is the normal shape of a turn.

Evidence:
```java
            if (current == target) {
                focusSeat = seat;
                return;                                    // already in front
            }
            if (focusSeat == seat) {
                return;                                    // brought forward once for this line; the player clicked away — theirs to keep (hygiene pass, 2026-09-17)
            }
...
        if (focusRestore == null) {
            return;
        }
```

Fix: make the guard about the tab actually shown, not the seat — remember the component passed to
`showTab` (`focusShown`) and return only when `focusShown == target && current != target`; or, at
minimum, reset `focusSeat = -1` in the `focusRestore == null` early return.

---

### F3 [P2] forge-arena/runner/voice_runner.py:1020 + voice/events.py:1328 — `final.json` is now revoked by a restart, and the leftover it claims to clear is already gone

Scenario: game over → `publish_final()` writes `mailbox/seat-0-voice/final.json`;
`arena-autostop.sh` is inside its `while [ ! -f "$VOICE_FINAL" ] ... waited < 60` loop. The voice
runner dies (run_voice.sh restarts it in 2 s). The new process's `run()` deletes `final.json`
unconditionally, so the signal the watcher is polling for disappears. Recovery depends on
`_adopt_state` restoring `final_locked` from the checkpoint at the next snapshot — and the
checkpoint is exactly what F1 (or any other `save_state` failure) stops writing. Where it does not
recover, the watcher burns the full `ARENA_AUTOSTOP_VOICE_WAIT` and falls back to the fixed linger.

The cost has no matching benefit: `arena-play.sh:163` already runs `arena-stop.sh`, whose line 86
is `rm -rf "$ROOT"/mailbox/seat-* ...` — `seat-0-voice/final.json` is removed on every launch
before the runner starts. The unlink only bites launches that reach this code twice.

Evidence:
```python
        (hb.parent / "final.json").unlink(missing_ok=True)     # a killed run's teardown signal is not this game's (hygiene pass)
```
```python
            if not getattr(self, "_final_published", False):   # once per process; run() removes a killed run's leftover
```

Fix: keep the file-existence guard (`if not f.exists() and not self._final_published:`) so a
restart re-asserts rather than revokes, and drop the unconditional unlink (or scope it to a
`final.json` whose `done` stamp predates this process's start).

---

### F4 [P3] forge-arena/runner/voice/table.py:170-172 — `table_from_launcher` now seats the human's own deck at an AI seat, contradicting both launchers

Scenario: `ARENA_SEAT_DECKS="a a b c"`, `ARENA_HUMAN_DECK=a`. The Gemini-driven change removes
only the *first* copy, so the voice runner seats `{1: "a", 2: "b", 3: "c"}` — seat 1 is given the
human's deck, which drives `seat_libraries`, `game_changers` and `_party_name`. Both launchers
remove **every** copy and then refuse to start:

* `runner/run_table.sh:107-114` — `[ "$d" = "$HUMAN" ] && continue` for each of the four, then
  `[ $# -eq 3 ] || { echo "... check ARENA_SEAT_DECKS for a repeated slug"; exit 1; }`
* `GuiPilotMatch.buildRoster` — `if (!slugOf(d).equals(human)) ordered.add(d);` then
  `if (ordered.size() != 4) throw new IllegalStateException(...)`

so the state the new branch handles can never reach a running table, and the handling it adds is
the wrong answer for it. The pre-change `[d for d in slugs if d != human_deck][:3]` matched both
launchers exactly. The new test at `tests/test_barks_runtime.py:203` now pins the divergent
contract.

Evidence:
```python
    rest = list(slugs)
    if human_deck in rest:
        rest.remove(human_deck)                                     # the human's ONE copy; a roster listing a deck twice keeps the other (Gemini review)
```

Fix: restore `rest = [d for d in slugs if d != human_deck]` and retire the duplicate-roster
assertion (or assert `{}` / a refusal instead).

---

### F5 [P3] forge-arena/runner/voice_runner.py:958 — a mid-game mute now *discards* the seat lines it used to defer

Scenario: the player hits the mute button, the table talks for ten seconds, the player unmutes.
Before this commit the muted branch scanned only the observer, so `game.jsonl` stayed behind its
cursor; on unmute `scan_game_log()` read the backlog and `brain_intent`'s gate
(`INTENT_MAX_AGE_S = 10.0`, `turn < snap_turn`) let the still-fresh declarations through. Now
`scan_game_log()` runs while muted with `voice = not (self.barks_mode == "off" or self.final_locked)`
still true, so every mulligan line, brain-intent line and loop call is enqueued and then dropped
seven lines later with `why="voice disabled"`. Nothing replays on unmute.

The commit message and `arena-play.sh`'s banner justify the change by the deal ledger only; the
line loss is silent. If it is wanted, it is wanted — but the muted branch could pass the same
`voice=False` that `barks_mode == "off"` already produces and take only the `type == "DEAL"` path,
which is all the stated rationale needs.

Evidence:
```python
            self.scan_observer()
            self.scan_game_log()
            self.scan_deal_control()
```
```python
        voice = not (self.barks_mode == "off" or self.final_locked)
```

Fix: give `scan_game_log(voice: bool | None = None)` an override and call it as
`self.scan_game_log(voice=False)` from the muted branch — deals are read, nothing else is built
and thrown away.

---

## Clean

Risky areas checked and found sound:

* **Removed symbols** — `/usr/bin/grep -rn` over `runner/`, `runner/tests/`, `scripts/`,
  `forge-gui-desktop/src`, `forge-arena/src` finds no caller of `seat_decks_from_roster`,
  `seat_decks_from_game_log`, `learn_table` or `exclude_seat=` outside the assertion that
  `learn_table` is gone. Every `assign_voices` / `load_seat_libraries` call site uses the new
  keyword.
* **`assign_voices` edge cases** — empty `libraries` → `{}`; missing `VOICES_DIR` → `Path.glob`
  yields nothing → `{}`; `human_seat=None` with two decks mapped to one library → pass 2's
  `lib not in used` gives it to the lower seat and drops the other into pass 3; a roster shorter
  than the library count → `break` leaves the tail silent, never two seats in one voice; the four
  shipped manifests all carry an int `seat`, so the relaxed `int(m.get("seat", 99))` adds no
  library that used to be skipped, and sub-libraries (`voices/<lib>/table|cards|atoms`) are at
  depth 2 and never matched by `*/manifest.json`.
* **`_party_name` via `table_from_launcher`** — the DEFAULT_TABLE substitution for an empty
  `ARENA_SEAT_DECKS` is not a mislabel: `run_table.sh:93` defaults to the identical roster string,
  so the names match the decks actually seated.
* **`enabled()` stat-signature memo** — the only writers are `AiControlFile.writeFlag`
  (`{"enabled": true}` = 17 B, `{"enabled": false}` = 18 B) and `arena-play.sh`'s
  `printf '{"enabled": false}\n'` (19 B), so mute and unmute always differ in size as well as
  mtime; `st_mtime_ns` on this machine's APFS is nanosecond-resolution (measured: five successive
  directory writes gave five distinct values), and a missing `advisor.json` memoises as `None` and
  re-stats when it appears.
* **`_inbox_files` directory-mtime cache** — `MailboxProtocol.writeAtomic` writes
  `req-N.json.tmp` *inside* the inbox and `Files.move`s it, and `deleteQuietly` removes it; every
  add and every remove moves the directory mtime, and `req-*.json` does not match the `.tmp`.
  Requests are never rewritten in place (`seq.incrementAndGet()` gives each a fresh name), so the
  cached per-file mtime that `slow_seats`/`mutter` now age against cannot go stale. A seat
  directory created after start stats as `OSError` → `cache.pop` → re-globbed on the poll after it
  appears.
* **`Renderer.variants()` memo** — the renderer only ever writes into `self.cache_dir`
  (`logs/cache/voice`); nothing in `runner/` or the tests writes a `.wav` into `VOICES_DIR/<lib>`
  during a run, the cache is per-`Renderer`-instance (tests that build a library mid-test then
  construct a fresh runner get a fresh cache), and `variants()` returns `list(cache[key])` so no
  caller can mutate it.
* **Checkpoint clocks** — `_casts` has exactly one reader (`events.py:991`) and it now uses
  `self.clock()`, matching the rebasing `t(x)` on restore; no `time.time()` reader of `_casts`
  remains. `answered` and `answered_at` are both keyed by advisor seq and pruned against the same
  `now = self.clock()`, and `STATE_RECENT_S = 300` is far past any advice TTL, so the tighter
  `answered` prune cannot resurrect an item the scheduler should drop.
* **`_TapeRing` in `--replay`** — `events` is rebound at voice_runner.py:1158 and used afterwards
  only at line 1203 (`_snapshot_from_tape(rec, events, prev_seq, hi)`), which branches on
  `isinstance(events, _TapeRing)`; `seqs` is computed before the rebind. `bisect_right(keys, lo)`
  reproduces the old strict `e["seq"] > lo`.
* **`AudioClip.withTrueLength`** — `AudioInputStream.readAllBytes()` stops at the underlying
  stream's EOF, so an over-declared `frameLength` yields the true PCM; `AudioSystem.write` to a
  non-seekable `ByteArrayOutputStream` needs a specified frame length and gets one, so
  `WaveFileWriter` stamps a correct RIFF header (the test's new
  `frameLength * frameSize == available()` assertion is the arbiter); a rejected source throws
  `UnsupportedAudioFileException` and falls back to the original bytes; the map caches one
  container per clip, same size as before — the extra `pcm`/`out` buffers are transient.
  (Theoretical only, not reachable with `DECODE_FORMAT`: `pcm.length / f.getFrameSize()` truncates
  a partial frame and would go negative if `getFrameSize()` were `NOT_SPECIFIED`.)
* **`arena-play.sh` mute-before-start** — the only `arena-stop.sh` that clears `$LOGS/control/*`
  runs at line 163, *before* the `mkdir -p "$LOGS/control"` + mute write at 212-213; the second
  call at 234 is on the launch-refused `exit 1` path. `run_voice.sh` only re-execs
  `voice_runner.py`, and `VoiceRunner.__init__` reads `logs/control/voice.json` without creating or
  truncating it. Dropping `ARENA_HUMAN_DECK="$HUMAN_SLUG"` from the `nohup env` line is safe:
  `$ALL` already carries it (line 108).
* **`ARENA_VOICE_RUNNER=1` unconditionally** — the only reader is
  `run-pilot-match.sh:113` → `-Darena.voice=1` → `AiControlFile.voiceAttached()`, used by
  `syncMute()` and the focus timer. With `--no-voice` the button is now *enabled* and correctly
  reads `control/voice.json` as muted (`voiceEnabled()` → `!s.contains("false")` → false → VOICE_OFF
  icon, "click to unmute"), which is the behaviour the change wants; nothing else keys on it.
* **`offer_id` in the ask body** — `AiControlFile.askAdvisor(raw, offerId)` emits the key only from
  `VAdvisor.answerOffer`, and `_handle_asks` passes `oid` to exactly one branch
  (`_handle_deal_message`), which forwards it only when `action in ("accept", "refuse")`. A typed
  ask carries no id, and `_answer_ask` never sees one — no foreign id can reach a non-deal path.
  A stale id is validated against seat *and* status before `_question_drop`.
* **`_deal_tick` narrowed to `type == "DEAL"`** — `seatd/runner.py` writes a dedicated
  `{"type": "DEAL", ...}` record at every deal site (`_record_deal` at lines 607, 616 and 695,
  covering answer, no-answer and the seat's own proposal), so nothing is lost by no longer reading
  the decision record's mirrored `deal` block.
* **`_earlier_ups`** — `_log_memory()` is called unconditionally from `__init__` (line 354) and
  sets the counter *before* its `try`, so the OSError path still yields 0; the byte pattern
  `b'"event": "up"'` is the same string the old `read_text()` loop matched, and nothing writes an
  `up` record between `__init__` and the single `record_up()` in `run()`.
* **`enqueue` eviction audit** — `before = list(self.queue)` is a shallow copy of the same dicts and
  every eviction branch *rebinds* `self.queue` rather than mutating it, so the identity test
  `all(q is not x for x in self.queue)` is exact.
* **Silence-floor `breaking`** — `patter()` returns at its first line when `self.queue` is
  non-empty and nothing between there and the `breaking` assignment enqueues, so dropping
  `and not self.queue` is a no-op.
* **Weighted patter pick** — `rng.choices(range(n), weights=w)` draws `random()` once, like the old
  manual walk, and the new `sum(weights) <= 0` guard removes the old unbound-`speaker` path when
  `cands` is empty.
* **`chains.plan_reply`** — each option's role is resolved once; the `fresh`/`stale` partition now
  carries `(opt, who)` pairs through to the loop, so the sorted seat is the picked seat.
* **`narrate_cast` `setdefault`** — the off-turn entry it creates is always overwritten by
  `turn_boundary`'s `self._turn_start[int(active)] = {...}` when that seat's turn begins, so the
  `land-go` / `pass` summary never reads the synthetic `lands: 0`.
* **Handle de-duplication** — `deal_table` keeps the plain `who` in the *later* seat's alias set
  too, but the alias map is first-wins, so `al["rev"] == 1` and `al["rev2"] == 2`; the pane quotes
  `_deal_handles[seat]`, which is the de-duplicated form.

## Appendix D — Reader D, verbatim
# Cross-process scenario walk — experimental/voicework2 vs base 3e037fdc9a9

Read-only trace of the six scenarios through seatd/runner.py + rules.py, advisor_runner.py,
voice_runner.py + voice/{events,scheduler,table}.py, and the Java mailbox/GUI side.
Findings are disagreements BETWEEN processes about a file's shape, lifetime, ownership or timing.

---

### F1 [P1] 1,2 forge-arena/runner/seatd/runner.py:338 vs forge-arena/src/main/java/forge/arena/interactive/MailboxController.java:4597 — the seat's truce guard keys on a `(seat N)` label the engine never writes, so an attack window under a struck truce is never held for the model

Scenario: seat 3 and Player One strike a truce (F-path 1 completes: accept file → ledger `struck` →
`deal-struck` note → `_deals_in_force[0]` set). Turn 7, seat 3 gets DECLARE_ATTACKERS with Player One
among `state.defenders`.

Evidence — seat side matches a parenthesised seat number:
```python
# runner.py:338
_SEAT_IN_LABEL = re.compile(r"\(seat (\d+)\)")
# runner.py:513-518  (_deal_partner_in, where == "defenders")
for e in (st.get(where) if where == "defenders" else req.get("options")) or []:
    m = self._SEAT_IN_LABEL.search(str(e.get("label", "")))
    if (m and int(m.group(1)) == other) or (where == "options" and e.get("id") in perms):
        return other, deal
```
Engine side writes the bare player name:
```java
// MailboxController.java:4592-4600  defenderList()
m.put("id", ge.getId());
m.put("label", ge.getName());          // "Player One" / "Urza, Lord High Artificer-S1"
m.put("type", ge instanceof Player ? "PLAYER" : "PERMANENT");
```
```java
// GuiPilotMatch.java:183, 206-207
static final String HUMAN_NAME = "Player One";
static String seatLabel(String commander, int seat) { return commander + "-S" + seat; }
```
`"(seat "` appears in exactly two places in the engine — `MailboxController.java:4040`
(`stackTargets`) and `ObserverSnapshot.java:826` (`stackDetail.targets`) — and both are **bare**
`seat N`, not `(seat N)`. So the regex never matches a defender label. Result:
`_deal_guard()` returns None on every DECLARE_ATTACKERS, the `RUNNER NOTE: your truce with X is in
force — attacking them breaks it` is never added, and `_deal_conflict()` (runner.py:553-556, same
regex) never breaks a replayed cycle out of an attack. Meanwhile the **voice runner does** see the
break, because it reads the ring's structured defender ids:
```python
# voice/events.py:884-891
defenders = [int(x) for x in (e.get("defenders") or [])]
betrayed = [x for x in defenders if x != seat and self.deal_forbids(seat, x, "attack")]
if betrayed: self._deal_broken(seat, betrayed, "attack", turn)
```
So the seat attacks the truce partner un-warned, and is then publicly called an oath-breaker
(`you-broke-it` / `you-promised`, ledger `broken`, a `deal-broken` note to the victim).
The unit test is green because its fixture invents a label shape the engine does not produce:
```python
# forge-arena/runner/tests/test_deals_seat.py:104
r["state"]["defenders"] = [{"id": d, "label": f"{names[d]} player (seat {d}), life 40", ...}]
```
(The target-window half of the guard survives — it matches on `e.get("id") in perms`, real card ids.)

Fix: seat side. `defenderList` already carries `id` and `type: "PLAYER"`; match on
`e.get("type") == "PLAYER" and e.get("id") == <partner's player id>`, or have the engine append
`" (seat N)"` to a PLAYER defender/option label. Then change the test fixture to the engine's shape.

---

### F2 [P1] 6 forge-arena/runner/voice_runner.py:946 (step) vs forge-arena/runner/seatd/runner.py:1968-1985 — the voice runner has no new-game reset at all; game 2 is silent and game 1's truces still forbid attacks

Scenario: a second match starts in the same JVM/session with no teardown. The seat runners see a new
`gameId` on the first request and wipe everything; the voice runner never looks.

Evidence — seat side resets:
```python
# runner.py:1968-1985
if self.mb.game_reset:
    ...
    self._pending_offers, self._deals_in_force, self._deal_notes = {}, {}, []   # deals die with the game
    self._my_offers, self._last_propose_turn, self._invited = {}, None, False
```
Voice side: `gameId` is referenced in exactly four places (`_game_id`, `save_state`, `_adopt_state`,
the observer tape) and **none of them is a reset**. `_adopt_state` runs once, at the first snapshot
(`voice_runner.py:737-750` guards on `_pending_state is None and _log_eliminated is None`), and
`scan_observer` (voice/events.py:1112-1271) has no game-identity branch. Consequences carried into
game 2:
- `self.final_locked = True` from game 1's game-over (events.py:1267) and every enqueue is refused:
  ```python
  # voice/scheduler.py:386-388
  if self.final_locked:
      self.record("dropped", kind=kind, why="game over — nothing after the sign-off", ...)
      return
  ```
  → the whole of game 2 is mute, and `publish_final()` is a no-op (`_final_published` is already True,
  events.py:1328), so autostop waits out the full 60 s voice window at the end of game 2.
- `self._deals` survives. `lapse_deals` only forgets a deal when `t > deal["until_turn"]`
  (scheduler.py:898); game 2 restarts at turn 1, so a game-1 truce with `until_turn 26` is in force
  for all of game 2 and `deal_forbids()` reports every attack between those seats as a broken deal —
  `_deal_broken` then writes `deal-broken` notes into the seats' mailboxes for a deal that never
  existed in this game.
- `eliminated`, `_seen_seats`, `_combos_done`, `_gc_cast_seen`, `_heads_up_said`,
  `_human_mull_done`, `started_said` all leak; seats dead in game 1 are skipped by `_inbox_files`
  (events.py:136-138), so `mutter`/`slow_seats`/heckles are blind to them in game 2.

Fix: voice side. In `scan_observer`, compare `self._game_id(d)` against the id the last snapshot
carried and, on a change, run the same reset the checkpoint schema already enumerates
(`_durable_state`, voice_runner.py:514-544) — i.e. re-init those fields and clear the queue.

---

### F3 [P1] 5 forge-arena/runner/voice_runner.py:257 vs forge-arena/runner/advisor_runner.py:558 — a voice restart seeds the game-log cursor at EOF, so a DEAL accept written during the 2 s gap is never struck while the Advisor panel says it was

Scenario: run_voice.sh's child dies (OOM, code reload) at 20:41:03; seat 1's brain answers the
player's offer with `{"deal": {"offer_id": "...", "accept": true}}` at 20:41:04; the supervisor
restarts the runner at 20:41:05.

Evidence — voice side skips everything appended while down:
```python
# voice_runner.py:257
self._game_log_pos = self._game_log_size()             # a (re)started runner never replays old decisions
# voice/events.py:239-242 (_tail seeds)
seeds = {"game": [None, self._game_log_pos], "advisor": [self._adv_inode, self._adv_pos]}
```
The checkpoint restores `_deals` and `_deal_counters` but **not** a log cursor — `_recency_state`
saves `"tails"` (voice_runner.py:559) and `_restore_state` reloads it (voice_runner.py:718-719), but
only after `_adopt_state`, which runs at the first snapshot — by which time `_tail("game")` may
already have been called in the same `step()`… and in any case the seed dict is only consulted when
`self._tails` has no entry, which is exactly the fresh-process case where `_game_log_pos` = EOF wins
for the very first read. Net effect: `scan_game_log` never sees the DEAL record, so `deal_answer`
→ `strike_deal` never runs: no `struck` in `logs/deals.jsonl`, no `deal-struck` note to either seat,
`_deals` unchanged.

The advisor's cursor is independent and continuous, so its panel lane fires:
```python
# advisor_runner.py:1386-1393  (_on_deal_record)
if deal.get("accept"):
    body = "accepts: " + deal_terms_text(src, name)
    off["status"] = "accepted"
```
State → event → wrong result: player reads `[r3-t9 · Urza] accepts: truce, 2 turns` in the panel;
seat 1's brain has no `deal-struck` note, so `_deals_in_force` is empty and nothing guards its
attack; the ledger the advisor later quotes as "ground truth" (`_deal_facts`) shows a deal the
ledger file never recorded.

Fix: voice side. Restore the `tails` cursor before the first `_tail` (or, simpler, seed
`_game_log_pos` from the checkpoint's `tails["game"]` in `__init__` when `load_state()` returned one
for the same game) instead of from the file size.

---

### F4 [P1] 1,3 forge-arena/runner/seatd/runner.py:610-616 vs forge-arena/runner/voice/events.py:416-420 — an offer that lapsed unanswered is written in the shape of a refusal, and both readers announce it as one, addressed to the player

Scenario: seat 2 proposes an alliance to seat 1 at turn 11. Seat 1's only window before the turn
rolls is a punt (deadline nearly expired), so the offer is never answered.

Evidence — seat side:
```python
# runner.py:610-616  _lapse_offers
for oid in list(self._pending()):
    self._pending().pop(oid, None)
    self._say(f"[seat {self.seat}] deal offer {oid} lapsed: no answer before the turn changed")
    self._record_deal(req, {"offer_id": oid, "accept": None, "why": "no answer"})
```
No `with`, no `terms`. Voice side:
```python
# voice/events.py:388-391, 403, 416-420
try:    other = int(deal.get("with", self.human_seat))     # "with" absent -> the PLAYER
...
counter = deal.get("counter") ...                          # None
else:
    self._ledger("refused", (seat, other), by=seat, deal=terms, offer_id=offer_id, turn=t)
    if offer_id:
        self._deal_note(other, {"kind": "deal-refused", ...})
```
`accept: None` is falsy, so the lapse lands in the refuse branch with `other = human_seat = 0`. The
ledger gets `refused between [1, 0]` for an offer seat 2 made to seat 1; the seat speaks
`no-deal-with-you` aimed at the player (events.py:431-439, fresh record so the staleness gate
passes); and the advisor's ledger lane prints it to the player:
```python
# advisor_runner.py:1523-1527
elif ev == "refused":
    if (oid, "answer") not in self._deal_seen and r.get("by") != 0:
        self._panel(name, "refuses", turn)
```
State → event → wrong result: the player is told "Urza refuses" about an offer they never made, and
the real proposer (seat 2) gets a `deal-refused` note only by accident of `offer_id` — actually it
gets none, because the note goes to `other` (= 0, the human, which `_deal_note_eligible` refuses
outside Executive). On an all-AI table the same record is dropped entirely
(`voice/events.py:392-394`, "a deal record naming no other party"), so the proposer never learns.

Fix: seat side. Carry the party and the terms on the lapse record and mark it distinctly —
`{"offer_id": oid, "accept": None, "lapsed": True, "with": <note['from']>, "terms": <note['deal']>}` —
and give `deal_answer` an explicit `lapsed` branch that emits `expired`, not `refused`.

---

### F5 [P1] 3 forge-arena/runner/voice/events.py:175 vs forge-arena/runner/voice_runner.py:187 — on an all-AI table `human_seat` is None and the opening-window check does `int(None)`, so every poll of the opening stall aborts mid-step

Scenario: `arena-play.sh --all-ai` (ALL_SEATS=1). The four brains mulligan; the board fingerprint
does not move for 30 s while a seat thinks.

Evidence:
```python
# voice_runner.py:187
self.human_seat = None if os.environ.get("ALL_SEATS") == "1" else 0
# voice_runner.py:941-943
def library_for_seat(self, seat: int) -> str:
    info = self.seat_libraries.get(int(seat))
```
```python
# voice/events.py:205  (heckle_human, after quiet >= HECKLE_S)
if not (self.human_turn() or ((self._human_window_open() or self._opening_window_open(snap)) and not self.executive_on())):
# voice/events.py:175  (_opening_window_open)
if (snap.get("turn") or 0) != 0 or self.library_for_seat(self.human_seat):
```
At turn 0 the left operand of the `or` is False, so `library_for_seat(None)` runs → `int(None)` →
`TypeError`. `human_turn()` returned False first (activeSeat is an int, `human_seat` is None), and
`_human_window_open()` returns False (no `seat-0-advisor` inbox on an all-AI table), so both
short-circuits are open. `run()` swallows it:
```python
# voice_runner.py:1032-1035
try:    self.step()
except Exception as e:  self.say(f"[voice] step error: {str(e)[:160]}")
```
State → event → wrong result: from the 30th second of the unchanged opening board until the first
board change, every `step()` dies at `heckle_human()` — after `scan_*` but **before** `patter()`,
`next_item()`, `speak()` and `save_state()`. The all-AI table is mute through its whole opening,
nothing is checkpointed, and `voice-0.log` fills with `[voice] step error: int() argument must be...`.

Fix: voice side, one line — `if self.human_seat is None or (snap.get("turn") or 0) != 0 or self.library_for_seat(self.human_seat): return False`
(or make `library_for_seat` tolerate None).

---

### F6 [P2] 2,6 forge-arena/runner/advisor_runner.py:1594-1617 vs forge-arena/runner/advisor_runner.py:955-974 — the relay-only advisor never calls `_process`, so `_maybe_new_game` can never fire and nothing it holds is ever reset

Scenario: `arena-play.sh --human --no-advisor`. The relay runs the whole session; a second game starts.

Evidence — the only caller of the game-identity check is the feed consumer:
```python
# advisor_runner.py:976-986  _process
for n, kind, path in items:
    body = self._load(path)
    ...
    self._maybe_new_game(body, n, kind)
```
and the relay loop never runs it:
```python
# advisor_runner.py:1612-1617
while True:
    self._apply_control()
    self._clock.observe()
    self._handle_asks()
    self._deal_tick()
    time.sleep(POLL_S)
```
State → event → wrong result: `self._offers`, `self._deal_seen`, the TurnClock's `round_of` /
`active_of` / `_last_turn` and `_talk_hinted` all carry game 1's content into game 2. Concretely, the
player types `@urza accept` in game 2; `_answer_counter` (advisor_runner.py:1272) finds game 1's
entry still at status `"proposed"`, writes `logs/control/deal/<ts>-accept.json` with that old
`offer_id`, and the voice runner — whose `_deal_counters` also survived (F2) — strikes it:
`strike_deal(..., until_turn = <a turn number from game 1>)`, i.e. a truce that `lapse_deals` can
never expire in game 2. Panel clocks are also wrong from the first line (`r5-t18` in a game that is
on turn 2).

Fix: advisor side. Call `_maybe_new_game` from the clock — `TurnClock.observe()` already parses the
snapshot each poll; have the relay loop compare the snapshot's turn going backwards (or add the
engine's `gameId` to `ObserverSnapshot.buildSnapshot`, which currently omits it entirely) and call
`_reset_for_new_game`.

---

### F7 [P2] 6 forge-arena/runner/advisor_runner.py:942-953 vs forge-arena/runner/advisor_runner.py:551-558 — `_reset_for_new_game` resets the brain and the governor but not the deal state it owns

Scenario: advised human game, game 2 starts, the feed's `gameId` changes so the reset *does* run.

Evidence:
```python
# advisor_runner.py:942-953
def _reset_for_new_game(self, why: str) -> None:
    self.brain.reset()
    self.pending_context = []
    self._context_dropped = 0
    self.last_seq = 0
    self.gov_turn = -1
    self.gov_budget = 0
    self._talk_hinted = False
```
against what the constructor declares as per-game state:
```python
# advisor_runner.py:551-557
self._offers: dict[str, dict] = {}
self._deal_seen: set = set()
...
self._clear_questions()                                  # a fresh runner: no pame from a past game
```
`_offers`, `_deal_seen`, `self._clock` and `self._last_turn` are untouched, and `_clear_questions()`
is not repeated. `_deal_tick` only clears the question directory on `gameOver`
(advisor_runner.py:1342-1343), so a question file for an offer that was still open when game 1 ended
without a clean `gameOver` snapshot survives — `VAdvisor.syncOffers()` re-opens the pane for it in
game 2 and `DealQuestion.acceptAsk()` sends `@urza accept` for a dead offer.

Fix: advisor side — add `self._offers.clear(); self._deal_seen.clear(); self._clear_questions();
self._clock = TurnClock(self._clock.path); self._last_turn = None` to `_reset_for_new_game`.

---

### F8 [P2] 4 forge-arena/runner/voice/events.py:1071-1098 vs forge-arena/runner/voice/events.py:344-348 — the two mute-backlog policies in one file disagree: the game log discards stale intents, the advisor stream replays them, and `answered_at` is stamped at read time so the "already answered" guard passes

Scenario: `--no-voice` (or the Advisor tab's mute) for twenty minutes, then the player unmutes.
`step()` deliberately withholds the advisor stream while muted:
```python
# voice_runner.py:951-957
# ... The advisor stream waits for the unmute. The game log and the deal control files do NOT
self.scan_observer(); self.scan_game_log(); self.scan_deal_control()
```

Evidence — the game-log scanner guards against exactly this:
```python
# voice/events.py:344-348  (brain_intent; same shape in deal_answer:421-426)
age = time.time() - float(r.get("ts") or time.time())
if (snap_turn is not None and turn and turn < snap_turn) or age > INTENT_MAX_AGE_S:
    # read late (a mute, a restart): a declaration from a past turn or older than a few seconds is history, not a line
    self.record("skipped", ...); return
```
The advisor scanner has no such check, although every advisor record carries `ts`
(`advisor_runner.py:653`):
```python
# voice/events.py:1074-1098
for raw in self._tail(self.logs / "advisor-0.jsonl", "advisor"):
    ...
    if k == "advice" and r.get("text"):
        self.enqueue("advice", text=first_sentence(r["text"]), seq=r.get("seq"), ttl=25.0)
    ...
    elif k == "chosen" and r.get("seq") is not None:
        self.answered.add(int(r["seq"]))
        getattr(self, "answered_at", {})[int(r["seq"])] = self.clock()      # <- NOW, not r["ts"]
```
The `answered` set exists to drop advice for a window the human already answered, but because
`answered_at` is stamped with the clock at *read* time, `next_item`'s grace test always passes:
```python
# voice/scheduler.py:431-439
since = now - getattr(self, "answered_at", {}).get(q["seq"], -1e9)
if since > grace:   ... drop ...
self.record("noted", kind="advice", why=f"spoken late: answered {since:.0f}s ago, inside the grace", ...)
```
State → event → wrong result: on unmute the table speaks a twenty-minute-old advice line ("hold the
Swords for their commander") for a decision resolved ten turns ago, logged as "spoken late: answered
0s ago, inside the grace"; the same pass replays whichever quip/bark survived eviction.

Fix: voice side — in `scan_advisor`, skip any record whose `r["ts"]` is older than `INTENT_MAX_AGE_S`
(or whose `turn` is behind `self._last_snapshot["turn"]`), and set
`answered_at[seq] = self.clock() - max(0.0, self.wall() - r["ts"])`.

---

### F9 [P2] 1,2 forge-arena/runner/seatd/runner.py:480-482 vs forge-arena/runner/voice/scheduler.py:811-828 — `_ingest_notes` stops reading once three sentences are buffered, so a `deal-struck` / `deal-lapsed` note queued behind table talk never reaches `_deals_in_force`

Scenario: the player relays two `table-talk` lines and an invite to seat 1 (advisor_runner.py:1245-1264
writes three notes). Seat 1 then answers a long run of REACT windows by fastpath/cycle — no model
call, so `_deal_notes` is never drained. The voice runner now writes a `deal-lapsed` note for the
truce seat 1 has with seat 2.

Evidence — the maps that gate the fastpath are mutated only as a side effect of *rendering prose*:
```python
# runner.py:480-502  _ingest_notes
for p in files:
    if len(self._deal_notes) >= self.NOTES_PER_PROMPT:      # NOTES_PER_PROMPT = 3
        break
    ...
    text = self._render_note(note, req)                      # <- the only place _deals()/_pending() are updated
```
```python
# runner.py:455-464  _render_note
was = self._deals().pop(int(other), None) or {}
...
if kind == "deal-lapsed":
    return f"your {word} with {who} has ended."
```
and the drain happens only on a model call:
```python
# runner.py:2135-2136
deal_notes = list(self._deal_notes or [])
self._deal_notes = []
```
The voice runner's contract assumes the opposite ("the seat runner renders it as one RUNNER NOTE and
deletes it", scheduler.py:812-813) and never re-sends.

State → event → wrong result: the `deal-lapsed` file sits on disk behind three table-talk sentences;
`_deals_in_force[2]` still holds the expired truce, so `_deal_guard` keeps forcing every attack and
target window to the model with "your truce with Giada is in force" for the rest of the game. The
symmetric case is worse: a `deal-struck` note stuck behind table talk means the seat has no record of
a deal it agreed to and attacks across it.

Fix: seat side — split application from rendering. Apply every readable note to the maps
(`_render_note`'s side effects) as the file is read, and only cap the number of *sentences* kept for
the prompt.

---

### F10 [P2] 6 forge-arena/runner/seatd/runner.py:1984-1985 vs forge-arena/runner/voice/scheduler.py:811-828 — the seat wipes its deal maps on a new game but leaves the note FILES on disk, and re-ingests them into game 2

Scenario: game 1 ends with a `deal-struck` note still unread in `mailbox/seat-2/notes/` (seat 2 got
no window after the strike). No teardown; game 2 begins.

Evidence:
```python
# runner.py:1984-1985
self._pending_offers, self._deals_in_force, self._deal_notes = {}, {}, []   # deals die with the game
self._my_offers, self._last_propose_turn, self._invited = {}, None, False
```
Nothing touches `self._notes_dir()`. `arena-stop.sh:86` is the only sweeper
(`rm -rf "$ROOT"/mailbox/seat-* ... "$LOGS"/control/*`) and by definition does not run between two
games in one session. At game 2's first window `_ingest_notes` reads the leftover file — the code
explicitly refuses any staleness rule:
```python
# runner.py:490-491
# no staleness rule on offers: a seat with nothing to do gets no window for turns on end ...
```
State → event → wrong result: seat 2 enters game 2 believing it has a truce with Player One
(`_deals_in_force[0]` set from a game-1 note), so every attack window is diverted to the model with a
false RUNNER NOTE, while the voice runner's `deal_forbids` (after F2, or on a fresh voice process,
correctly) says there is no such deal — the two processes hold opposite views of the same truce.

Fix: seat side — on `game_reset`, unlink every `*.json` in `self._notes_dir()` before the first
`_ingest_notes` of the new game. (Notes carry no `gameId`; adding one would be the sturdier fix.)

---

### F11 [P2] 1 forge-arena/runner/seatd/runner.py:678-684 vs forge-arena/runner/advisor_runner.py:753-768 — a seat's offer to seat 0 always writes a note into `mailbox/seat-0/notes/` that nobody reads in a human game; switching Executive on later ingests the whole backlog

Scenario: advised human game, Executive off. Seats 1-3 each propose to the player a few times over
twenty turns. At turn 24 the player clicks **Advisor Executive**.

Evidence — the seat writes the note unconditionally:
```python
# runner.py:678-684
note = {"kind": "deal-offer", "from": self.seat, "to": to, "deal": terms, "offer_id": oid, ...}
d = self._notes_dir().parent.parent / f"seat-{to}" / "notes"
d.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(note)); os.replace(tmp, d / f"{ts_ms}-deal-offer.json")
```
The docstring admits nobody reads it outside Executive ("seat 0's is read by the Executive when it
plays the seat; otherwise the advisor relays the DEAL record"), and the voice runner's own note
writer *does* gate on this (`_deal_note_eligible`, scheduler.py:803-809) while the seat runner does
not. Nothing deletes the files. When Executive starts:
```python
# advisor_runner.py:758-768
self._exec = SeatRunner(0, self.brain.deck, self._base, ..., brain=self.brain)
...
self._clear_questions()                    # the seat-0 runner answers the notes itself; no pane
```
State → event → wrong result: the seat-0 runner's first window ingests up to three of the oldest
stale offers, puts them in `_pending()`, and the `DEAL PENDING <oid>` grammar is appended to the
prompt; `unshown` / "an offer is waiting for your answer" (runner.py:2017-2018) forces every window
to the model until they are answered. An `accept` then produces a DEAL record for an `offer_id` the
voice runner either never had or already popped — `scan_deal_control`-style, `deal_answer` calls
`strike_deal` with `terms` copied from the *stale note* (runner.py:601), striking a turn-8 truce at
turn 24 with `until_turn = 24 + rounds*living`. The advisor panel shows
`you (Executive) accept Urza's truce` for an offer the player refused sixteen turns earlier.

Fix: seat side — mirror `_deal_note_eligible`: when `to == 0` and this is not an all-AI table, skip
the note file (the DEAL record already reaches the advisor panel). Or, at minimum, have the seat-0
runner sweep its notes directory when the Executive runner is constructed.

---

### F12 [P2] 1 forge-arena/runner/seatd/runner.py:446-447 vs forge-arena/runner/voice/scheduler.py:879-904 — the seat stores `until_turn` but never expires a deal itself; expiry is entirely the voice runner's to push

Scenario: the voice runner is killed and its supervisor loop is killed too (arena-stop's PID sweep
races, or the operator kills `voice-loop.pid`). A struck truce is in force.

Evidence — the seat records the expiry and then ignores it:
```python
# runner.py:446-447
self._deals()[int(other)] = {"kind": dk, "until_turn": deal.get("until_turn"), "rounds": deal.get("rounds"),
                             "offer_id": note.get("offer_id"), "struck": note.get("turn")}
```
`until_turn` is read back only by `rules.deal_duration()` for prose; `_deal_guard` /
`_deal_conflict` never compare it to `req["turn"]`. The only expiry path is the other process:
```python
# voice/scheduler.py:898-904
if t > deal["until_turn"]:
    self._deals.pop((a, b), None); self._deals.pop((b, a), None)
    self._ledger("lapsed", ...)
    for s in (a, b): self._deal_note(s, {"kind": "deal-lapsed", ...})
```
State → event → wrong result: with no voice runner, the seat honours a one-turn truce for the rest of
the game — every DECLARE_ATTACKERS/target window offering that partner is diverted to a model call
with a note that is false, and the advisor's `_deal_facts` ("the runner's ledger, ground truth") still
lists it as `accepted`. The same holds for the F9 case where the lapse note is simply never applied.

Fix: seat side — in `_deal_guard`, drop any entry whose `until_turn` is an int below `req["turn"]`
before matching. The note stays the authoritative announcement; this is only a backstop.

---

### F13 [P3] 1,2 forge-arena/runner/seatd/runner.py:511-518 vs forge-arena/src/main/java/forge/arena/interactive/MailboxController.java:4692-4694 — a no-target deal guards the partner's permanents but not the partner themselves

Scenario: seat 3 holds a `no-target` deal with Player One and gets a CHOOSE_ENTITY window whose
options include the player (a Lightning Bolt-class target list).

Evidence: the only option-side match that works is the permanent-id fallback (F1 kills the regex):
```python
# runner.py:511-518
perms = {c.get("id") for o in (st.get("opponents") or []) ... for c in (o.get("battlefield") or [])}
m = self._SEAT_IN_LABEL.search(str(e.get("label", "")))
if (m and int(m.group(1)) == other) or (where == "options" and e.get("id") in perms):
```
```java
// MailboxController.java:4692-4694
private static String entityLabel(GameEntity e) {
    return e instanceof Card ? cardChoiceLabel((Card) e) : e.getName();   // "Player One" — no seat number
}
```
A player option's id is a player id, never in `perms`. The voice runner *does* catch the break
(`_target_seats` parses the bare `"seat N"` the engine writes into `stackDetail.targets`,
voice/events.py:538-541), so the seat burns the deal un-warned and is publicly called on it.

Fix: same as F1 — match `type == "PLAYER"` + the partner's player id (the option list already carries
`entityType(e) == "PLAYER"`, MailboxController.java:4697-4702).

---

### F14 [P3] 3 forge-arena/runner/voice/events.py:1243-1263 vs forge-arena/runner/voice_runner.py:187 — an all-AI game always ends with Joshua's *loss* line

Scenario: `--all-ai`, seat 2 wins.

Evidence:
```python
# voice/events.py:1243-1244
human = next((s for s in seats if s.get("seat") == self.human_seat), None)
won = human is not None and not human.get("eliminated")
# voice/events.py:1261-1263
self.queue.append({... "stock": "you-win" if won else "strange-game", ...})
```
With `human_seat = None` no seat matches, so `won` is always False and the spectator table signs off
with the defeat line. Fix: voice side — when `self.human_seat is None`, queue a neutral sign-off
(the winner's own `win` line at events.py:1257-1260 already played) instead of the `you-win`/
`strange-game` pair.

---

### F15 [P3] 5 forge-arena/runner/voice_runner.py:1020 vs forge-arena/scripts/arena-autostop.sh:74-78 — a restart after the sign-off retracts the teardown signal the watcher is already polling for

Scenario: game over, the final sequence plays, `final.json` is written; the supervisor restarts the
runner a moment later (a step exception loop, or the operator reloading code).

Evidence:
```python
# voice_runner.py:1020
(hb.parent / "final.json").unlink(missing_ok=True)     # a killed run's teardown signal is not this game's
```
```sh
# arena-autostop.sh:74-78
if [ "$why" = "match over (engine reports gameOver)" ] && voice_alive; then
  waited=0; max="${ARENA_AUTOSTOP_VOICE_WAIT:-60}"
  while [ ! -f "$VOICE_FINAL" ] && [ "$waited" -lt "$max" ]; do sleep 1; waited=$((waited + 1)); done
```
The restarted process re-publishes it once `_adopt_state` restores `final_locked`
(voice_runner.py:683, then `step()`'s `if self.final_locked: self.publish_final()`), so this is at
most a few seconds — but if the restart also fails the adoption check (a checkpoint the gameId test
rejects, voice_runner.py:613) the file never comes back and the watcher falls through to the full
linger. Not a stuck game; only a delayed teardown. Fix: voice side — delete `final.json` only when
`load_state()` returned nothing for this game.

---

### F16 [P3] 4 forge-arena/runner/voice/events.py:1295-1309 vs forge-arena/runner/advisor_runner.py:310-323 — the voice publishes `enabled` in state.json and the advisor reads only `live`, so a muted table is still prompted for dense stock quips

Evidence:
```python
# voice/events.py:1298-1299
live, reason = self.renderer.state()
cur = {"live": live, "reason": reason, "enabled": self.enabled()}
```
```python
# advisor_runner.py:315-317
st = json.loads(Path(state_file).read_text())
live = bool(st.get("live", True))
```
With `--no-voice` and no ELEVENLABS key, `live` is False → `QUIP_GUIDE_DENSE` ("end about one line in
two with exactly one tag") is appended to every advice/colour prompt for a runner that drops
everything (`voice_runner.py:960-965`). Tokens and prompt weight spent on lines that are recorded as
`dropped: voice disabled`. Fix: advisor side — `if not st.get("enabled", True): return "", live` so a
muted voice suppresses the quip guidance entirely.

---

### F17 [P3] 2 forge-arena/runner/advisor_runner.py:363 vs forge-arena/runner/advisor_runner.py:375 — `@urza truce 2` is silently a one-turn truce although the panel's own help advertises `N turns`

Evidence:
```python
# advisor_runner.py:363
_DEAL_ROUNDS_RE = re.compile(r"\b(\d+|a|an|one|two|three)\s+(?:more\s+|full\s+)?(?:turns?|rounds?)\b", re.I)
# advisor_runner.py:375
"deals: @<seat> truce | no target | alliance [N turns | until turn N]",
```
A bare digit with no unit does not match, so `deal["rounds"] = 1` (advisor_runner.py:465). The echo
line `you → Urza: truce, 1 turn` does show the correction, so this is visible rather than silent —
but the prompt the seat sees, the ledger and the voice line all carry the wrong duration.
Fix: advisor side — allow a trailing bare integer when a kind word was matched.

---

### F18 [P3] 1 forge-arena/runner/advisor_runner.py:1285 vs forge-arena/runner/voice/events.py:489-505 — the accept file carries terms the voice runner ignores

Evidence:
```python
# advisor_runner.py:1285
body = {"offer_id": oid, "counter": off["counter"] or off["deal"]}
```
```python
# voice/events.py:489-496, 504
oid = str(body.get("offer_id") or "")
c = self._deal_counters_map().pop(oid, None)
...
terms = c.get("deal") or {}
self.strike_deal(a, b, terms.get("kind", "truce"), turn, by=self.human_seat, ...)
```
Only `offer_id` is read. Harmless today (the two maps are built from the same DEAL record) but it
means the file's documented shape and the reader's contract differ, and if `_deal_counters` is lost
(F2/F3) the terms sitting right there in the file are not used — the accept is simply dropped as
"an unknown or expired offer". Fix: voice side — fall back to `body["counter"]` when
`_deal_counters` has no entry, or drop the field from the writer.

---

### F19 [P3] 5 forge-arena/runner/advisor_runner.py:551-557 vs forge-gui-desktop/src/main/java/forge/screens/match/views/VAdvisor.java (syncOffers) — an advisor restart clears the question directory, so an open offer pane vanishes and a typed answer finds nothing

Evidence: `run_advisor.sh` restarts the child on any exit; the new process runs
`self._offers = {}` / `self._deal_seen = set()` / `self._clear_questions()` (advisor_runner.py:551-557)
and re-seeds `_game_pos` / `_ledger_pos` at EOF (advisor_runner.py:558-559). The GUI notices only that
the file is gone:
```java
// VAdvisor.syncOffers(): cur == null -> offerPane.dispose(); offerPane = null;
```
State → event → wrong result: the pane disappears mid-offer with no explanation, and `@urza accept`
now answers `no counter or offer from Urza is pending` (advisor_runner.py:1280-1282) even though the
voice runner still holds the offer in `_deal_counters` and would happily strike it.
Fix: advisor side — do not `_clear_questions()` on start; re-read the directory into `_offers` (the
files already carry seat, who, handle, terms, turn and `lapses_after_turn`).

---

### F20 [P3] 1 forge-arena/runner/advisor_runner.py:1645-1646 — under Executive, a busy seat-0 mailbox starves the ask/deal/clock lanes

Evidence:
```python
# advisor_runner.py:1644-1650
self._apply_control()
if self._executive_tick():
    continue          # a seat-0 decision was answered; look again at once
self._maybe_rotate()
self._clock.observe()
self._handle_asks()
self._deal_tick()
```
Every answered seat-0 request skips the clock, the chat/offer lane and the deal lane for that
iteration. On a turn where the engine hands seat 0 a long run of windows, the panel's turn labels
freeze and a typed `@urza accept` waits out the whole run. Not a stuck game (the loop always comes
back), but the ownership is wrong: `_deal_tick` is documented as running "every poll, pause or not".
Fix: advisor side — drop the `continue` and let the rest of the loop body run after the Executive
answers one request.

---

## Walked and sound

1. **Human game, advisor on.** Traced `_propose_deal` → `seat-0`/panel → `logs/control/ask/ask-*.json`
   (with `offer_id`, AiControlFile.askAdvisor) → `_handle_asks`/`_answer_counter` →
   `logs/control/deal/<ts>-accept.json` → `scan_deal_control` → `strike_deal` → `deals.jsonl` +
   `deal-struck` notes → `_render_note` → `_deals_in_force`. The offer-pane file lifecycle
   (`_question_write`/`_question_drop`/`_clear_questions` vs `DealQuestion.list` + `syncOffers`) is
   consistent, `_deal_note_eligible` correctly withholds seat 0's note outside Executive, and the
   ledger/panel/pane all agree on `lapses_after_turn` (advisor `counter_turn = t+1`, voice
   `_deal_counters[oid]["turn"] = t+1`, both expiring when the table turn passes it). The forbidden
   actions are what F1/F13 say they are; everything else in this lane matched.
2. **Human game, relay-only.** `--no-advisor` → `run_advisor.sh --relay-only`, `-Darena.relay=1` →
   `relayAttached()` keeps the chat row and the offer pane alive while `advisorAttached()` hides the
   Advisor/Executive toggles — consistent. `parse_deal` correctly routes accept/refuse → control file,
   invite → `deal-invite` note, anything without deal terms → `table-talk` note; the seat runner
   ingests both at its next window before any fastpath (runner.py:2015) and delivers them on the next
   model call (any window type, not just main-phase), with the invite lifting the propose cooldown
   exactly once. `_question_write`'s relay-only assessment stub matched the pane's expectations.
3. **All-AI table.** `ALL_SEATS=1` reaches run_table.sh (seat 0 gets a brain), the voice runner
   (`human_seat = None`) and each seat (`_all_ai()`, `rules.all_ai_table()`) from the one `$ALL`
   assignment in arena-play.sh; seat 0's `say` keys and propose windows are enabled in both
   `rules.say_offer` and `_can_propose`; `_deal_note_eligible(0)` correctly writes notes to seat 0;
   party naming agrees (seat runner via `table_from_launcher`, voice via `address.json`, no advisor to
   disagree). Game over → `final_locked` → queue drain → `publish_final()` → `arena-autostop.sh`'s
   `voice_alive`/`VOICE_FINAL` handshake is sound in both the speaking and muted paths.
4. **`--no-voice`.** Confirmed the muted `step()` still runs `scan_observer`/`scan_game_log`/
   `scan_deal_control` and `publish_final()`, so deals, the ledger, the notes and the teardown signal
   all work while nothing plays; queued lines are dropped with a record. `voiceAttached()` now keys on
   `-Darena.voice=1` rather than the advisor, so the mute button is live in every mode including
   all-AI. Unmute restores everything; only the advisor-stream backlog policy is wrong (F8).
5. **Voice restart.** Checkpoint round-trip verified field by field: `_deals` (with the old-int
   upgrade in `normalize_deal`), `_deal_counters` (shape-filtered on restore), `_deal_seq`,
   `eliminated`, `final_locked`, the ring cursor with its `RESTART_RING_MAX` guard, and the clock
   rebase + `_settle_clock` so a restart never reads as a long silence. Pending `*-accept.json` files
   survive on disk and are consumed on the next scan; the heartbeat thread restarts inside
   autostop's 15 s liveness window. The one real hole is the game-log cursor (F3).
6. **Two games, no teardown.** The seat runners are the only process that resets correctly
   (`mb.game_reset` from the engine's `gameId`, then a full wipe of plan/memos/cycle/deals) — and even
   they leave note files behind (F10). Verified that `ObserverSnapshot.buildSnapshot`
   (ObserverSnapshot.java:742-758) writes **no** `gameId` at all, which is why the voice runner falls
   back to `game.jsonl`'s last id and why neither it (F2) nor the relay-only advisor (F6) has any
   new-game signal to key on; the advised advisor gets one from `AdvisorFeed`'s stamped feed files but
   under-resets (F7).
