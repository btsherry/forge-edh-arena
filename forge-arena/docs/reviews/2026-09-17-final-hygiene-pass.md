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
