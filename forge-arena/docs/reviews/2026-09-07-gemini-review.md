# Gemini review of experimental/voicework — 2026-09-07 (late)

Ben: "run all recent code changes by gemini, review all code, docs, and scripts
written for the experimental branch. Fix anything that is not functionally
correct." Reviewer: Google Gemini CLI (`npx @google/gemini-cli`, model
gemini-3.5-flash), three diffs of `arena..experimental/voicework` (runner+scripts,
Java, docs+voice), prompt in the scratchpad `review-prompt.txt`. Every finding was
verified against the source before a change was made. Dispositions below; the
raw reports follow.

## Dispositions

| # | Finding | Verified? | Action |
|---|---|---|---|
| R1 (P0) | `_spell_reactor` treats Stifle/Disallow ("counter target … ability") as spell-only reactors → dead-rule pass on an all-abilities stack | yes | fixed: ability/activated/triggered text excludes the option |
| R2 (P1) | `record._label` stringifies dict options | no — our logs store label strings | hardened anyway (dict-safe) |
| R3 (P1) | advisor rotation can clobber the seat-0 runner's rotation while executive | yes | fixed: advisor skips rotation while executive |
| R4 (P1) | mana-only options auto-passed while our source is targeted (float in response) | yes | fixed: `_threatens_own` guards the mana-only and reactor rules |
| R5 (P1) | repeat rule ignores a new SPELL on the stack | yes | fixed: repeat needs an all-abilities stack (stackKinds) |
| R6 (P2) | executive heartbeat thread leaks per toggle | yes | fixed: `SeatMailbox.stop_heartbeat_thread`, called on OFF |
| R7 (P2) | game reset leaves `_tap_pass`/`_yielded` | yes | fixed |
| R8 (P2) | advisor `game_id` stale during executive | yes | fixed: synced from the seat runner each tick |
| R9 (P2) | record tail-truncation cuts the NEWEST turns | yes | fixed: oldest turns dropped with an omission line |
| R10 (P3) | unknown quip tags dropped silently | yes | fixed: logged |
| J1 (P0) | stale `executive.json` with no runner hands the seat to nobody | yes (arena-stop clears control/, but a GUI launched another way would not) | fixed: `wanted()` needs `-Darena.advisor=1` AND a fresh seat-0-advisor heartbeat; a dead advisor releases the seat at the next priority |
| J2 (P1) | release only at priority; other decisions could wait on a dead mailbox | yes | fixed: `exchange()` returns null at once when the executive should release (stock decides that one; next priority releases) |
| J3 (P1) | fresh-equipment keep fires on opponents' turns (equip is sorcery-speed) | yes | fixed: own turn only; test updated |
| J4 (P1) | `ZoneType.Flashback` is not a zone → NPE / miss | **no** — `Player.getCardsIn(Flashback)` returns `getCardsActivatableInExternalZones` | no change |
| J5 (P2) | Command zone not scanned → commander falls to the fail-open play | yes | fixed: Command added |
| J6 (P2) | `stackDetail` omits targeted SPELLS | yes | fixed: `getTargetSpells()` names added |
| J7 (P2) | file I/O on the Swing EDT | pre-existing pattern (advisor toggle does the same) | not changed; noted |
| D1 (P1) | `manaCeiling` skips any row with a `sick` key | **no** — `sick` is put only when true | no change |
| D2 (P1) | voice runner loses a line caught mid-write | yes | fixed: cursor advances to the last newline only |
| D3 (P1) | `glitch_wav` crashes on non-WAV bytes (ffmpeg absent) | yes | fixed: non-WAV returned untouched |
| D4 (P2) | `{0}` non-tap activated abilities treated as utility | yes | fixed: filed as free plays (keeps the prompt) |
| D5 (P2) | human controller does not delegate when the override is already installed | yes | fixed: delegate whenever wanted and installed |
| D6 (P2) | javadoc names `removeController(long)` | yes | fixed |

Tests: `runner/tests/test_review_fixes.py`; `AutopassPolicyTest` (equipment),
`ExecutiveSwitchTest` (file alone is not enough).

## Pass 2 — the three steps and the pass-1 fixes

| # | Finding | Verified? | Action |
|---|---|---|---|
| G1 (P0) | `mirrorYield` threat check ignores a SpellAbility target (our own stack item aimed at) | yes, though a spell on the stack already blocks the mirror | fixed: SpellAbility targets of ours count as threats |
| G2 (P0) | `arena-status.py` `_label` undefined | **no** — defined at module level; dry run on game 25 data passes | no change |
| G3 (P1) | persistent process stderr pipe never drained → CLI blocks when the buffer fills | yes | fixed: stderr to `runner/logs/claude-persistent-seat-N.err` (or DEVNULL) |
| G4 (P1) | a spawn-path turn (effort mismatch) is invisible to the live in-memory process → drift | yes | fixed: the process is stopped before a spawn turn; the next persistent call resumes from disk |
| G5 (P1) | low-effort downgrade could meet a game-deciding non-targeting ability | judgement; accepted | fixed: no downgrade when any stack item's oracle text names win/lose the game, extra turn |
| G6 (P2) | poll()-based abort could discard a final result still in the reader queue | yes | fixed: only the EOF marker ends the read |
| G7 (P2) | record may exceed `max_chars` when the newest FULL_TURNS blocks alone overflow | yes | fixed: tail-preserving hard cap |
| G8 (P3) | pipes not closed on kill | yes | fixed |

## Raw reports


### Runner + scripts

### Critical Severity (P0)

#### 1. Counterspell/Stifle Logic Error on All-Abilities Stack
*   **File/Context:** `forge-arena/runner/seatd/runner.py:657-668` (`_unaffordable_react` and `_spell_reactor` checks).
*   **Issue:** The `_spell_reactor(o)` helper matches any option label containing the substring `"counter target"`. This matches cards like Stifle, Disallow, Voidslime, and Tale's End (which can counter activated or triggered abilities). If the stack contains only abilities and triggers, `"spell" not in kinds` evaluates to `True`. The condition `all(self._spell_reactor(o) or self._plain_mana_ability(o) for o in non_pass)` is then satisfied, causing the runner to bypass the model and **automatically pass**. 
*   **Failure Scenario:** An opponent activates a game-winning or lethal ability (e.g., Thassa's Oracle trigger, Staff of Domination, or a lethal Purphoros trigger) while the seat has Stifle or Disallow in hand with mana available. The AI will incorrectly categorize Stifle/Disallow as a "spell-only" reactor, assume there is nothing to target on the stack, and automatically pass.
*   **Minimal Proposed Fix:** Refine `_spell_reactor` or `_unaffordable_react` to distinguish between pure spell-only counters (e.g., Counterspell, Negate) and ability/trigger counters. Ensure that if an option can target abilities or triggers (i.e., contains "activated", "triggered", "ability"), it is not classified as a pure spell reactor.
    ```python
    @staticmethod
    def _spell_reactor(o: dict) -> bool:
        low = str(o.get("label", "")).lower()
        text = low.split(" — ", 1)[1] if " — " in low else low
        # If it counters abilities/triggers, it is NOT a pure spell reactor
        if "ability" in text or "triggered" in text or "activated" in text:
            return False
        return ("counter target" in text
                or ("copy target" in text and ("instant" in text or "sorcery" in text or "spell" in text)))
    ```

---

### High Severity (P1)

#### 2. Raw Dictionary Representation in Rotated Game History
*   **File/Context:** `forge-arena/runner/seatd/record.py:53-59` (`_label` helper).
*   **Issue:** The `_label` helper attempts to stringify `opts[cid]` using `str(opts[cid])`. However, `opts` (retrieved from `rec.get("options")` in request entries) is a list of *dictionaries* parsed from JSON (e.g., `{"id": 1, "label": "Chrome Mox  {0}", ...}`). Converting a dictionary to a string yields `"{'id': 1, 'label': 'Chrome Mox  {0}'...}"`. Splitting this representation on double spaces (`split("  ")[0]`) produces a corrupted, raw-looking string starting with dict syntax (e.g., `"{'id': 1, 'label': 'Chrome Mox"`).
*   **Failure Scenario:** When a session is rotated, the history rendered via `record.render` populates the dossier with malformed Python stringified dictionaries instead of clean card/option names. This degrades the formatting and confuses the Claude model when parsing context.
*   **Minimal Proposed Fix:** Safely extract the `"label"` key from the dictionary before splitting:
    ```python
    if isinstance(cid, int) and opts and 0 <= cid < len(opts):
        opt = opts[cid]
        lab = opt.get("label") if isinstance(opt, dict) else str(opt)
        return lab.split("  ")[0] if lab else None
    ```

#### 3. Session Clash and History Deletion in Executive Mode
*   **File/Context:** `forge-arena/runner/advisor_runner.py:322-339` (`_executive_tick` and `_maybe_rotate`).
*   **Issue:** The advisor and the active executive-mode `SeatRunner` share the exact same `self.brain` instance. On a turn transition, if `SeatRunner` handles a priority window, it rotates `self.brain` using the rich history from the seat's private log (`seat-0.jsonl`). However, in the same tick or a subsequent tick, if no seat request is pending, `_executive_tick()` returns `False` and `AdvisorRunner._maybe_rotate()` is called. This triggers a second rotation on the *same* brain using `seat_log=None`, completely wiping the rich "why" reasoning and seat choices, and overwriting it with a public-facts-only transcript.
*   **Failure Scenario:** During Executive mode, the LLM's active memory is repeatedly stripped of its own reasoning from earlier turns because the advisor's bare-bones public rotator overrides the rich seat rotator on the shared `SeatBrain`.
*   **Minimal Proposed Fix:** In `AdvisorRunner._maybe_rotate()`, bypass the rotation completely if Executive mode is active (`self._exec is not None`), and let the active `SeatRunner` handle session rotations:
    ```python
    def _maybe_rotate(self) -> bool:
        if self._exec is not None:  # Let SeatRunner rotate using seat-0.jsonl
            return False
        ...
    ```

#### 4. Automatic Pass in Response to Targeted Tap/Destroy Effects
*   **File/Context:** `forge-arena/runner/seatd/runner.py:720-721` (`_unaffordable_react` plain mana ability check).
*   **Issue:** If the stack is non-empty and the only options are plain mana abilities (e.g., tapping a land or Giada), `_unaffordable_react` assumes "nothing to spend the mana on" and automatically passes the window. This ignores a core MTG strategic line: responding to a targeted tap (Rishadan Port, Deceiver Exarch, Cryptic Command) or destruction (Beast Within, Demolition Field) by tapping the permanent to float the mana before it is lost.
*   **Failure Scenario:** An opponent activates Rishadan Port targeting the AI's land on upkeep, or casts Beast Within on the AI's Gilded Lotus. The stack is non-empty, and the only available action is the targeted permanent's mana ability. The AI automatically passes, losing the land/Lotus and floating 0 mana.
*   **Minimal Proposed Fix:** Ensure that if any of the AI's permanents are targeted by an item on the stack, plain mana abilities are *not* automatically passed, allowing the model to decide whether to float the mana:
    ```python
    # Inside _unaffordable_react, do not autopass if our mana sources are targeted or threatened
    if all(self._plain_mana_ability(o) for o in non_pass) and not self._threatens_own(req):
        return "only mana abilities offered, nothing to spend the mana on"
    ```

#### 5. Stale Same-Turn Repeat Pass Blocks Reactive Card Draw
*   **File/Context:** `forge-arena/runner/seatd/runner.py:821-839` (`_repeat_tap_pass` logic).
*   **Issue:** `_repeat_tap_pass` automatically passes tap-only card flow abilities (Sensei's Divining Top, The One Ring) if the model already passed them once this turn, the life total has not dropped, and the options are identical. However, it completely ignores *changes to the stack*.
*   **Failure Scenario:** Early in a turn, an opponent triggers a minor ability; the AI chooses to pass on Sensei's Divining Top. Later in the same turn, the opponent casts a game-ending spell (e.g., Peer into the Abyss) that does not target the AI's permanents. The option set is identical, and life/mana have not changed, so `_repeat_tap_pass` automatically passes the window, preventing the AI from tapping Top to look for a counterspell in response to the Peer.
*   **Minimal Proposed Fix:** Store the top item of the stack as part of `self._tap_pass` cache. If the stack's top item changes (meaning a new spell/ability is on top), invalidate the repeat pass and let the model decide:
    ```python
    # In _note_tap_pass, store top stack item
    self._tap_pass = (req.get("turn"), self._option_set(req), st.get("life"), self._top_stack_item(req))
    
    # In _repeat_tap_pass, check if top item matches
    turn, optset, life, top_item = self._tap_pass
    if top_item != self._top_stack_item(req):
        return None
    ```

---

### Medium Severity (P2)

#### 6. Thread/Resource Leak on Executive Mode Handoff/Release
*   **File/Context:** `forge-arena/runner/advisor_runner.py:307-320` (`_executive_tick`).
*   **Issue:** Each time Executive mode is toggled on, `self._exec` is instantiated and `self._exec.mb.start_heartbeat_thread()` is called, launching an infinite background loop thread. When toggled off, `self._exec` is simply nullified (`self._exec = None`), but the heartbeat daemon thread continues running in the background because its target loop retains a reference to the mailbox `mb` object. This causes a thread leak that multiplies with each executive toggle.
*   **Failure Scenario:** A human player toggles the Executive mode button on and off 5 times during a match. Five orphan heartbeat threads continue running, writing redundant/stale heartbeat markers to the mailbox.
*   **Minimal Proposed Fix:** Introduce a `stop_heartbeat_thread` or `close` mechanism on `SeatMailbox`/`SeatRunner` and call it explicitly before clearing the executive runner reference. (If `stop_heartbeat_thread` depends on unexposed `seatd` code, the `SeatMailbox` should expose a boolean flag or stop signal).

#### 7. Leaked State and Landmines Across Game Resets
*   **File/Context:** `forge-arena/runner/seatd/runner.py:747-767` (`GAME_RESET` branch of `handle()`).
*   **Issue:** On a `GAME_RESET` event (such as starting a new match in the same GUI/process), the seat runner clears `self.order_memo`, `self.cycle`, and `self._hist`. However, the newly introduced repeat-pass caches, `self._tap_pass` and `self._yielded`, are **not** cleared. If a new game starts on Turn 1 and the previous game also ended on Turn 1 (common in testing or quick restarts), the turn boundaries align, preventing the turn-change clear from running and allowing stale choices to leak into the new game.
*   **Minimal Proposed Fix:** Explicitly clear both caches on game reset:
    ```python
    if dtype == "GAME_RESET":
        self._reset_game_memory()
        self.brain.reset()
        self.mb.respond(req, {"ready": True})
        self._say(f"[seat {self.seat}] GAME_RESET -> ready")
        self.order_memo.clear()
        self.cycle = None
        self._hist = []
        self._tap_pass = None
        self._yielded = {}
    ```

#### 8. Stale Game ID Tracking in AdvisorRunner
*   **File/Context:** `forge-arena/runner/advisor_runner.py:314` and `_maybe_rotate`.
*   **Issue:** `AdvisorRunner` tracks `self.game_id` which is parsed from advisor inbox files. However, during Executive mode, the `SeatRunner` handles requests directly and updates its own `_game_id`, while `AdvisorRunner.game_id` remains stale or `None`. Consequently, `AdvisorRunner._maybe_rotate()` renders records with a stale `game_id` which fails to load records in `_load()`, skipping history. Furthermore, when Executive mode is turned off, the first incoming advisor item with the correct `gameId` will trigger a false `_reset_for_new_game`.
*   **Minimal Proposed Fix:** Synchronize `self.game_id` with `self._exec._game_id` inside the executive tick:
    ```python
    if self._exec is not None:
        self.game_id = self._exec._game_id
        req = self._exec.mb.pending_request()
        ...
    ```

#### 9. Slicing/Truncation Strategy Contradiction in `record.py`
*   **File/Context:** `forge-arena/runner/seatd/record.py:148-154` (`render` truncation).
*   **Issue:** The file's documentation claims that oldest turns are folded while newest turns stay in full to preserve recent context. However, if the history is extremely long and the folded text still exceeds `max_chars`, the function performs a raw truncation of the end of the text: `text = text[:max_chars - 1] + "…"`. Because the turns are rendered chronologically (newest turns at the end of the string), this truncation silently cuts off the **most recent and important turns**, leaving only the old, folded history.
*   **Minimal Proposed Fix:** If a hard truncation is required, truncate the *beginning* of the history (oldest turns) rather than cutting off the latest state. Alternatively, raise a warning and drop older turns from the rendering loop.

---

### Low Severity (P3)

#### 10. Missing Warning/Observability for Dropped Voice Quips
*   **File/Context:** `forge-arena/runner/advisor_runner.py:270-279` (`_commentate` and `_advise`).
*   **Issue:** If the model outputs a quip ID that is misspelled or missing from the closed vocabulary `QUIPS` (e.g., `[quip:nice-swingg]`), the tag is silently dropped by `split_quip`. No warning or error is logged. This makes it difficult to detect when the LLM's prompt instructions or outputs diverge from the valid voice vocabulary.
*   **Minimal Proposed Fix:** Log a warning message in `split_quip` or the advisor's process loop when an invalid quip ID is parsed:
    ```python
    # Inside split_quip
    qid = m.group(1)
    if qid not in QUIPS:
        print(f"[warning] Advisor generated an invalid quip tag: {qid}")
    ```

### Java

### Code Review Report

This review covers the experimental branch versus the release branch of the Magic: the Gathering AI arena Forge fork, focusing on the newly introduced "Advisor Executive" toggle, autopass rules, mailbox protocol, and public state serialization.

---

### 1. [Severity: P0] Session-to-Session Persistence Leads to Non-Attached Advisor Lockout Hang
*   **File:** `ExecutiveSwitch.java` (lines 538–573), `AdvisorControllerHuman.java` (lines 77–83)
*   **Why it is wrong:** The state of Advisor Executive (`logs/control/executive.json`) is persisted across game sessions. If a user turns "Advisor Executive" ON in Game 1 and then starts Game 2 *without* the Advisor attached, `advisorAttached()` will be `false` in `VAdvisor.java`, which disables the toggle button so the user cannot turn it OFF from the GUI. However, `executive.json` remains `{"on": true}` on disk. 
    When the game starts, `AdvisorControllerHuman.chooseSpellAbilityToPlay()` sees `ExecutiveSwitch.wanted()` is `true` and installs the `MailboxController` override on Seat 0. Because no Advisor runner is running to answer the mailbox, `MailboxController` blocks indefinitely waiting for a response, permanently freezing the game on the very first priority step of Game 2.
*   **Failure Scenario:** A player tests Advisor Executive, leaves it ON, and closes the game. Later, they launch a standard match without the advisor daemon running. The game immediately freezes at the first priority check and cannot be resumed.
*   **Proposed Minimal Fix:** Write `{"on": false}` or delete `logs/control/executive.json` on game startup/initialization inside the game engine, or ensure `ExecutiveSwitch.wanted()` returns `false` if `MailboxController` detects that the Advisor runner is not active (e.g., via a heartbeat check).

---

### 2. [Severity: P1] Lockout from "Taking Back" Seat Control During Non-Priority Decisions
*   **File:** `MailboxController.java` (lines 306–313)
*   **Why it is wrong:** The override release check (`!ExecutiveSwitch.wanted()`) is placed *only* inside `MailboxController.chooseSpellAbilityToPlay()`. However, `MailboxController` overrides *all* decision methods of `PlayerController` (e.g., `chooseCards`, `choosePlayer`, `chooseCombatAndAttackers`, `chooseBlockers`, `chooseYesNo`, `payMana`). If the user toggles Advisor Executive OFF while the game is waiting for one of these other decisions, the release check is bypassed entirely. The game remains blocked waiting for a response from the advisor runner, and the human is locked out of regaining control.
*   **Failure Scenario:** The Advisor is executing the human's seat and casts a tutor. This triggers a `chooseCards` decision. The human clicks "take it back" (writing `{"on": false}`), but because `chooseCards` does not check `wanted()`, the human remains locked out. If the advisor brain has crashed or stopped responding, the game hangs permanently.
*   **Proposed Minimal Fix:** Add the `!ExecutiveSwitch.wanted()` release check and `ExecutiveSwitch.release(getPlayer())` logic to all major blocking decision methods inside `MailboxController.java`, or use a common helper method in `MailboxController` that wraps all mailbox decision waits and polls `ExecutiveSwitch.wanted()` to abort immediately if the toggle goes OFF.

---

### 3. [Severity: P1] Autopass Logic Error: Keeps Prompt Open for Fresh Equipment on Opponent's Turn
*   **File:** `AutopassPolicy.java` (lines 146–149, 175–178)
*   **Why it is wrong:** The `freshEquipment` rule in `AutopassPolicy.decide(Stop)` keeps the priority prompt open with `"equipment entered this turn"` without checking whether it is currently the player's own turn. By MTG rules, the Equip activated ability is sorcery-speed and can only be activated on your own turn. If an equipment enters the battlefield under your control during an opponent's turn (e.g., flashed in via Sigarda's Aid or put into play by an effect), `s.freshEquipment` will be `true`, causing the autopasser to keep the prompt open on the opponent's turn, forcing the human to click through dead windows where they cannot legally equip anything.
*   **Failure Scenario:** On an opponent's end step, an Equipment is put onto the battlefield. The autopasser keeps the prompt open on every subsequent priority window of that opponent's turn with the reason `"equipment entered this turn"`, wasting prompt space and time.
*   **Proposed Minimal Fix:** Restrict the fresh equipment keep rule to the player's own turn. In `AutopassPolicy.java`:
    ```java
    if (s.myTurn && s.freshEquipment) {
        return Decision.keep("equipment entered this turn");
    }
    ```

---

### 4. [Severity: P1] Incorrect Zone Scanned for Flashback and Graveyard Plays
*   **File:** `AdvisorControllerHuman.java` (`collectPlays`, lines 296–306)
*   **Why it is wrong:** In `collectPlays()`, the loop scans `ZoneType.Hand`, `ZoneType.Battlefield`, and `ZoneType.Flashback` to find actionable plays. However, Flashback is not a physical player zone in Forge; cards with Flashback reside physically in `ZoneType.Graveyard`. Calling `getPlayer().getCardsIn(ZoneType.Flashback)` will either throw a `NullPointerException` (causing the try-catch in `armCastsAutopassIfIdle` to fail-open every single priority stop) or return an empty list. 
    This means Graveyard-castable cards (such as those with Flashback, Escape, or playable via Crucible of Worlds) are never parsed and instead trigger the `matched < actionable.size()` fallback, making the autopasser fail open anonymously as `(actionable outside hand/battlefield/flashback)` with cost 0, rather than identifying the card's real cost and name.
*   **Failure Scenario:** A player has a castable Flashback card in their graveyard and no other plays. The autopasser fails open anonymously instead of noting the specific card name and cost. If `getCardsIn` throws an NPE, autopassing is completely disabled for the rest of the game.
*   **Proposed Minimal Fix:** Scan `ZoneType.Graveyard` instead of `ZoneType.Flashback`, and check for card playability in the graveyard zone.
    ```java
    for (ZoneType zone : new ZoneType[] { ZoneType.Hand, ZoneType.Battlefield, ZoneType.Graveyard }) {
    ```

---

### 5. [Severity: P2] Command Zone is Omitted from `collectPlays` Scan
*   **File:** `AdvisorControllerHuman.java` (`collectPlays`, lines 296–306)
*   **Why it is wrong:** `collectPlays()` does not include `ZoneType.Command` in its array of scanned zones. When the Commander is castable from the Command Zone, it is returned in `actionable` but missed by the zone loop. This triggers the fallback `matched < actionable.size()`, which adds a dummy play with cost `0` and name `(actionable outside...)`. This prevents the autopasser from analyzing the Commander's actual mana cost and name, causing it to fail-open (keep prompt) even when the player has 0 mana and cannot possibly afford the Commander.
*   **Proposed Minimal Fix:** Add `ZoneType.Command` to the zone scan array in `collectPlays()`.

---

### 6. [Severity: P2] public-state Observability Gap: Targeted Spells on the Stack Omitted from `stackDetail`
*   **File:** `ObserverSnapshot.java` (lines 204–249)
*   **Why it is wrong:** The new `stackDetail` block in `ObserverSnapshot` attempts to serialize targets using `tc.getTargetCards()` and `tc.getTargetPlayers()`. However, in MTG, counterspells and other redirection effects target `SpellAbility` objects on the stack. Because `getTargetCards()` only returns `Card` views of physical cards/permanents, targeted spells on the stack are omitted from the snapshot's target detail, causing the advisor brain to be blind to what is being countered or targeted on the stack.
*   **Proposed Minimal Fix:** Collect targeted spells/abilities from `TargetChoices` (e.g., checking `getTargetSpells()` or `getTargetAbilities()`) and include them in the serialized targets list.

---

### 7. [Severity: P2] Blocking Disk I/O Performed on Swing Event Dispatch Thread (EDT)
*   **File:** `VAdvisor.java` (lines 115–128, 190–203), `AiControlFile.java` (lines 193–228)
*   **Why it is wrong:** Every second, `VAdvisor.poll()` calls `AiControlFile.executiveOn()`, which performs a synchronous disk read (`Files.readAllBytes`) of `logs/control/executive.json` directly on the EDT. Clicking the toggle button also performs synchronous directory creation, write, and atomic move operations on the EDT. Performing synchronous I/O on the UI thread causes micro-stuttering and UI freezes if the filesystem or network drive has high latency.
*   **Proposed Minimal Fix:** Perform disk reads/writes in a background worker (e.g., `SwingWorker` or a thread pool) and update the UI components asynchronously on completion.

### Docs + voice

### Finding 1 (Critical Severity — P1): Summoning Sickness Check Bugs the Autopass Mana Ceiling
* **File & Context:** `AdvisorControllerHuman.java`, lines 125–130 (`manaCeiling()`):
```java
            int total = getPlayer().getManaPool().totalMana();
            for (java.util.Map<String, Object> row : MailboxController.manaSources(getPlayer())) {
                if (row.containsKey("sick")) {
                    continue;
                }
                ...
```
* **Description:** In Forge, a mana source's summoning-sick status is serialized into the `manaSources` map as `"sick": true` (summoning sick) or `"sick": false` (not summoning sick). Checking `row.containsKey("sick")` will match *any* creature-based mana source that has a serialized sickness property, regardless of its value.
* **Failure Scenario:** If the human controls an untapped, non-sick `Giada, Font of Hope` or `Llanowar Elves` (`"sick": false` is present in the map row), this check skips the row completely. The `manaCeiling()` method will return a total underreporting available mana (usually `0`), leading the policy table (`AutopassPolicy.decide`) to auto-pass priority windows where real plays could have been made.
* **Minimal Fix:** Change the check to only skip the source if the sickness boolean is actually `true`:
```java
                if (Boolean.TRUE.equals(row.get("sick"))) {
                    continue;
                }
```

---

### Finding 2 (Critical Severity — P1): Stream-splitting Race Condition in Log Reading Leads to Lost Advice Lines
* **File & Context:** `voice_runner.py`, lines 2465–2472 (`scan_advisor()`):
```python
        with path.open("rb") as f:
            f.seek(self._adv_pos)
            chunk = f.read()
            self._adv_pos = f.tell()
        for raw in chunk.decode("utf-8", "replace").splitlines():
            ...
```
* **Description:** Reading the streaming log file `advisor-0.jsonl` using a simple `f.read()` from a polling background thread is highly prone to racing with the process that appends to it. If the polling read occurs in the middle of a line write, `chunk` will end with a partial line. `json.loads()` will raise a `ValueError` and discard it. However, because `self._adv_pos` is still advanced to `f.tell()` (the physical end of the file), the next scan starts from the end of the partial line, permanently splitting and losing the second half of the line.
* **Failure Scenario:** When trigger-heavy boards are being processed, long advice rows are written to `advisor-0.jsonl`. If `VoiceRunner` reads the log mid-write, the advice fails to parse, is skipped, and because the file pointer has advanced, it is permanently lost and never spoken.
* **Minimal Fix:** Only advance the file pointer up to the end of the last *fully completed* line ending with a newline (`\n`), leaving any partial line at the end to be fully read in the next polling step:
```python
        with path.open("rb") as f:
            f.seek(self._adv_pos)
            chunk = f.read()
            if not chunk:
                return
            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                return  # Wait for a complete line to finish writing
            lines_chunk = chunk[:last_nl + 1]
            self._adv_pos += len(lines_chunk)
        for raw in lines_chunk.decode("utf-8", "replace").splitlines():
            ...
```

---

### Finding 3 (High Severity — P1): Uncaught `wave.Error` Crash When `ffmpeg` is Absent
* **File & Context:** `voice_runner.py`, lines 2240–2255 (`Renderer.render()` / `glitch_wav()`):
```python
            if self.glitch != "off":
                tmp_out.write_bytes(glitch_wav(tmp_out.read_bytes(), self.glitch, int(key[:8], 16)))
```
* **Description:** If `ffmpeg` is not installed on the system, `Renderer.render` writes the raw MP3 data returned from ElevenLabs directly to `tmp_out` as a fallback. When it then attempts to apply glitching via `glitch_wav()`, `glitch_wav` tries to open the file with `wave.open(io.BytesIO(data), "rb")`. Because `data` is MP3 instead of WAV, `wave.open` throws a `wave.Error`. Since this call is outside any try-except block inside `render()`, the error propagates, crashing the CLI `--say` mode and aborting the background thread's execution of `step()`.
* **Failure Scenario:** A user without `ffmpeg` runs `python3 voice_runner.py --say "hello"` to test their configuration. The script crashes immediately with a `wave.Error` trace.
* **Minimal Fix:** Add a try-except block in `glitch_wav` to return the original bytes untouched if wave opening or reading fails:
```python
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                return data
            sr = w.getframerate()
            pcm = array.array("h")
            pcm.frombytes(w.readframes(w.getnframes()))
    except (wave.Error, OSError, EOFError):
        return data
```

---

### Finding 4 (Medium Severity — P2): Free `{0}` Non-Tap Activated Abilities Auto-Passed
* **File & Context:** `AdvisorControllerHuman.java`, lines 324–332 (`collectPlays()`):
```java
                    if (sa.isActivatedAbility()) {
                        classified = true;
                        int abilityMana = manaCostOf(sa);
                        if (abilityMana > 0) {
                            playsOut.add(new AutopassPolicy.Play(card.getName() + " (ability)", abilityMana));
                        }
```
* **Description:** Activated abilities are only classified as "plays" (tracked in `playsOut`) if they cost mana (`abilityMana > 0`). If they cost `{0}` mana, they are added to `utilitiesOut`. However, `AutopassPolicy` only keeps the prompt open for utilities if they target, have a sacrifice cost, or target during the opponent's combat begin. A free, repeatable `{0}` non-tap activation (such as `{0}: Regenerate this creature` or `{0}: Prevent the next 1 damage to any target`) will be treated as plain utility and completely auto-passed by the policy table.
* **Failure Scenario:** An opponent casts a non-targeting board wipe (`Wrath of God`). The player has a creature with `{0}: Regenerate this creature` in play. Because the ability does not target and has no sacrifice cost, the policy table will auto-pass the priority window, and the creature dies without the player getting a window to protect it.
* **Minimal Fix:** Track `{0}` activated abilities that do not require tapping in `playsOut` as free plays:
```java
                        int abilityMana = manaCostOf(sa);
                        boolean requiresTap = sa.getPayCosts() != null && sa.getPayCosts().hasTapCost();
                        if (abilityMana > 0 || (abilityMana == 0 && !requiresTap)) {
                            playsOut.add(new AutopassPolicy.Play(card.getName() + " (ability)", abilityMana));
                        }
```

---

### Finding 5 (Medium Severity — P2): Already-Installed Override Ignored if Priority Method is Stored/Called Directly
* **File & Context:** `AdvisorControllerHuman.java`, lines 80–84 (`chooseSpellAbilityToPlay()`):
```java
        if (ExecutiveSwitch.wanted() && ExecutiveSwitch.install(getPlayer(), getLobbyPlayer())) {
            return getPlayer().getController().chooseSpellAbilityToPlay();
        }
```
* **Description:** If `wanted()` is true but the override controller is already installed, `install` returns `false`. This causes the condition to evaluate to `false`, proceeding to run `AdvisorControllerHuman`'s normal human priority execution. If the game engine holds or caches a direct reference to the `AdvisorControllerHuman` instance instead of accessing it via `player.getController()`, the already-installed override will be ignored, prompting the human directly.
* **Failure Scenario:** The player activates the Advisor Executive button. The override is successfully installed. On a subsequent decision within the same phase, the engine invokes `chooseSpellAbilityToPlay()` directly on the human controller reference. Because `wanted()` is true but the override is already installed, `install` returns `false` and the override is bypassed.
* **Minimal Fix:** Always delegate when `wanted()` is true, installing if not already installed:
```java
        if (ExecutiveSwitch.wanted()) {
            ExecutiveSwitch.install(getPlayer(), getLobbyPlayer());
            return getPlayer().getController().chooseSpellAbilityToPlay();
        }
```

---

### Finding 6 (Minor Severity — P2): JavaDoc Contradicts Implementation Signature on `removeController`
* **File & Context:** `ExecutiveSwitch.java`, line 105:
```java
            human.removeController(ts, true);
```
* **Description:** The JavaDoc comments state `{@link Player#removeController(long)}` which only accepts a single `long` parameter, while the implementation invokes `human.removeController(ts, true)` passing a boolean. 
* **Minimal Fix:** Update the JavaDoc comment or align the implementation signature with the parent Forge engine's actual definition of `removeController`.

### Pass 2

### P0 — Critical Severity

#### 1. Targeted Stack Spell/Ability Omission Leads to Premature Auto-Yields
* **File/Function:** `MailboxController.java: mirrorYield`
* **What's wrong:** When evaluating if the live stack contains a threat targeting our permanents or player (`threatened`), the code loops over the target list:
  ```java
  for (forge.game.GameObject tgt : part.getTargets()) {
      if (tgt == me || (tgt instanceof Card && ((Card) tgt).getController() == me)) {
          threatened = true;
      }
  }
  ```
  If an opponent plays a `Counterspell` or a `Stifle` targeting our spell or ability on the stack, the target `tgt` is a `SpellAbility` instance, which is a `GameObject` but not a `Card` or `Player`. Thus, the loop fails to detect that our spell/ability is targeted, evaluating `threatened` to `false`. This allows `mirrorYield` to match and auto-yield (pass) our reactive window, preventing the AI from responding (e.g., casting its own counterspell) and letting its play be countered.
* **Minimal Fix:** Extend the target type check to handle `SpellAbility` targets on the stack:
  ```java
  if (tgt == me 
      || (tgt instanceof Card && ((Card) tgt).getController() == me)
      || (tgt instanceof SpellAbility && ((SpellAbility) tgt).getActivatingPlayer() == me)) {
      threatened = true;
  }
  ```

#### 2. Guaranteed Runtime Exception on Status Monitoring
* **File/Function:** `forge-arena/scripts/arena-status.py: print_seat_efficiency`
* **What's wrong:** 
  1. The script tries to write: `line = (f"  seat {seat} [{_label(seat)}] ...")`. However, the helper `_label` is neither imported nor defined in `arena-status.py`, raising a `NameError` at runtime.
  2. Even if `_label` were imported from `seatd.record.py`, that function expects a `rec` dictionary (representing a game log entry), not an integer `seat` index. Passing `seat` directly would throw an `AttributeError` inside `_label` when calling `.get("answer")`.
* **Minimal Fix:** Remove the unresolvable `_label(seat)` call or resolve the seat index to a string using existing status mappings:
  ```python
  line = (f"  seat {seat}  decisions {len(mine)}  model {model}  " ...)
  ```

---

### P1 — High Severity

#### 3. Undrained Stderr Pipe in Persistent Claude Process Deadlocks Subprocess
* **File/Function:** `PersistentClaude._spawn` and drain logic
* **What's wrong:** The persistent Claude subprocess is spawned with `stderr=subprocess.PIPE` and the `--verbose` flag, but there is no background thread to read or drain the `stderr` stream:
  ```python
  def _spawn(self):
      return subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, cwd=self.cwd)
  ```
  Since `--verbose` logs heavily to `stderr`, the OS pipe buffer (typically 64KB on macOS) will fill up quickly. Once full, any further write to `stderr` by the `claude` subprocess will block indefinitely, causing the entire AI decision process to hang.
* **Minimal Fix:** Redirect `stderr` to `subprocess.DEVNULL` to discard unread logs and prevent the buffer from filling up:
  ```python
  def _spawn(self):
      return subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, cwd=self.cwd)
  ```

#### 4. Stale Persistent Session Memory Due to Spawn Path Fallback
* **File/Function:** `SeatBrain._persistent_call`
* **What's wrong:** If a decision requires a different model or effort (e.g. `eff = "low"`), `_persistent_call` falls back to the spawn path (returning `None`):
  ```python
  if p is not None and p.alive() and self._persistent_key != key:
      return None   # effort/model differs for this one call: spawn path
  ```
  The fallback spawn path resumes the session and appends a new turn to disk. However, the persistent process is left alive in memory. Because `claude` in persistent mode retains its session transcript in memory (rather than reloading it from disk for every call), a subsequent persistent call to this process will proceed without knowing about the turn(s) written by the fallback spawn process, leading to severe context drift and rule errors due to missing history.
* **Minimal Fix:** Explicitly terminate the persistent process when deviating to the spawn path, forcing the next persistent call to spin up a fresh process that resumes the updated session from disk:
  ```python
  if p is not None and p.alive() and self._persistent_key != key:
      self.stop_persistent()
      return None
  ```

#### 5. Threatless Reaction Downgrade Ignores Game-Ending Win Conditions
* **File/Function:** `SeatRunner._unthreatened_ability_react` (and its application in `SeatRunner.handle()`)
* **What's wrong:** Reaction windows involving only other players' abilities/triggers that do not target our seat are downgraded to `"low"` thinking effort. However, in competitive Commander, some of the most critical, game-ending win conditions are activated/triggered abilities that do not target any player or permanent (e.g., `Thassa's Oracle` ETB trigger, `Hermit Druid` activation, `Food Chain` loops, or `Felidar Sovereign` win triggers). Demoting these windows will cause the model to miss crucial counterplay (like casting `Stifle` or responding with instant-speed interaction).
* **Minimal Fix:** Disable the auto-downgrade of reaction windows, or limit `"low"` effort strictly to non-reactive windows, or change the default configuration `ARENA_REACT_LOW_EFFORT` to default to `"off"`.

---

### P2 — Medium Severity

#### 6. Race Condition in Persistent Queue Draining Discards Valid Decisions
* **File/Function:** `PersistentClaude.call`
* **What's wrong:** When polling the stdout queue inside `call()`, if `queue.Empty` is raised, the main thread checks `not self.alive()`:
  ```python
  except queue.Empty:
      if not self.alive():
          self.log("persistent claude exited mid-call")
          self.kill()
          return None
      continue
  ```
  If the `claude` subprocess writes its final response and immediately exits, `self.alive()` becomes `False`. If the main thread's poll times out before the background `drain` thread has finished transferring the final lines or the `None` EOF marker into `self._q`, `call()` aborts, kills the process, and discards a perfectly valid model response.
* **Minimal Fix:** Remove the `if not self.alive()` check on `queue.Empty`. If the process exits, the background thread will write the `None` (EOF) marker to the queue, which is handled cleanly on subsequent loop iterations:
  ```python
  except queue.Empty:
      continue
  ```

#### 7. Log Length Truncation Loop Permits Context Limit Violations
* **File/Function:** `record.py: render`
* **What's wrong:** The loop drops older turns while the text length exceeds `max_chars` but only as long as `len(body) > FULL_TURNS`:
  ```python
  while len(text) > max_chars and len(body) > FULL_TURNS:
      body.pop(0)
      dropped += 1
      text = ...
  ```
  If the text is still too long when `len(body)` reaches `FULL_TURNS`, the loop exits. Because the hard-limit truncation (`text = text[:max_chars - 1] + "…"`) was removed from the end of the function in this diff, `render` can return a string exceeding `max_chars`, causing context limit overflows or prompt parsing failures.
* **Minimal Fix:** Re-add a hard truncation fallback at the end of the function:
  ```python
  if len(text) > max_chars:
      text = text[:max_chars - 1] + "…"
  ```

---

### P3 — Low/Minor Severity

#### 8. Missing File Descriptor Teardown in PersistentClaude.kill
* **File/Function:** `PersistentClaude.kill`
* **What's wrong:** When killing the subprocess, `self.proc.stdin`, `self.proc.stdout`, and `self.proc.stderr` are not explicitly closed. 
* **Minimal Fix:** Explicitly close the standard I/O pipes inside the `kill()` method to prevent file descriptor leaks and potential runtime warnings:
  ```python
  try:
      p.stdin.close()
  except Exception:
      pass
  # Repeat for stdout/stderr
  ```
