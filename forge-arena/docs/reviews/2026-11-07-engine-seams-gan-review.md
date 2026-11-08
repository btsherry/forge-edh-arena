# Engine seams from game `20261107-184934` — proposal, debate, GAN-style validation (2026-11-07)

Ben, after the 3-AI + human game on 2026-11-07: "check the logs for any agent behavior that may have been
blocked or not able to be carried out because of engine seams" → "propose fixes, dont execute" → "run all the
fixes and the other functions they touch, unit tests, functional interactions with gemini, and debate the
proposed fix, strengthen and simplify it, then validate it in a gan style fashion, before applying."

## The two seams

1. **BL-65 — Phyrexian shards.** Forge's AI payer pays `{C/P}` from sources before generic and considers life
   only once a shard has no source left: `{1}{R/P}{R/P}` with two Mountains and 37 life spent both Mountains on
   the `{R/P}`s and failed on `{1}` (`gui.out` 97–100, Solphim t26, twice).
2. **W-14 recurrence — no window over the seat's own spell.** Seat 3 cast Devastating Onslaught meaning to copy
   it with Flare of Duplication (turn intent: "hold priority"); the gate passed its priority and the loop died.

## What shipped (uncommitted on `arena` at the time of writing)

- `ComputerUtilMana`: the BL-01 reroute also fires for a Phyrexian shard, but only when `lifeBridgesTheGap`
  (life-payable shards to life; the sources must then cover every remaining shard, with per-colour producer
  counts). `LifeForManaPayerTest.phyrexianShardsGoToLifeOnlyWhenSourcesAreShort` (Dismember ×4 boards,
  Phyrexian Metamorph ×2, Tamiyo ×2, Solphim).
- `MailboxController`: fifth window kind `selfSpell` (own non-trigger object on the stack, no opponent object,
  an AFFORDABLE `CopySpellAbility` answer whose chain / Charm mode / host trigger can target it — the copy part
  itself, or `Defined$ Targeted` under an ancestor that does); counters and redirects do not qualify; a silent or
  malformed answer passes (never stock); a refused card cannot open it; `ARENA_SELF_SPELL_WINDOW=off|0|no`;
  the pre-cast affordability guard covers activated abilities. `SelfSpellWindowTest` (Flare, Dualcaster, Naru
  Meha, Wild Ricochet, Return the Favor, Lithoform over an own activation open it; Shock, Counterspell,
  Deflecting Swat, a tapped-out seat do not; an opponent object alongside makes it reactive).
- Runner logs `own-spell window:`; hygiene counts it; banner + README knob rows; `seat-brief.md` rule;
  `_talk_tick` checks the rate limit before listing notes/.
- Docs: BUG-LOG `Closed 2026-11-07` + W-14 bullet; INTERACTIVE-ARENA field note 21c.

## Process and the reviewers

Gemini was unavailable for the first debate (API key on a depleted prepay project → 402; the Gemini CLI's
free tier is discontinued → `IneligibleTierError`; Ben's AI Pro plan is not a CLI tier). Round one and two
therefore ran with an **Opus subagent** as the discriminator (no Fable subagent without express go). Ben then
supplied a fresh key; a **Gemini flash** pass ran on the free tier (answer truncated by its own thinking budget),
and after $20 prepaid credit **Gemini Pro** (`gemini-pro-latest`) ran the final round on the current diff.

| Round | Reviewer | Findings taken | Rejected / deferred |
|---|---|---|---|
| 1 | Opus | YouCtrl copy triggers need an activator (`ta.copy(who)`); copies in Charm modes / behind a redirect root; refused host must not open the window; brief contradicted the gate; silent brain → pass; kill switch + hygiene count | source-count heuristic limits (Signet overcount, Nykthos/doubler undercount) → documented; stock-AI baseline shift → documented |
| 2 | Opus | life bled before a doomed payment (rollback never refunds life) → `lifeBridgesTheGap`; affordability guard for activated abilities; malformed/unknown answer → pass; knob spellings; brief/prompt wording (own trigger, opponent responses) | Lithoform / Return the Favor "ability you control" flood → watch via hygiene; Spree `ModeCost`; Vote/d20 copies; Lutri without `TargetType`; human Auto button pays life; Compleated planeswalkers castable one land short |
| 2b | Gemini flash | copy part must bind to its own (or ancestor `Defined$ Targeted`) targeting, not any stack-targeting part in the chain | its payer walk-through pays correctly when traced (shards fall to life once no red source remains) |
| 3 | Gemini Pro | `lifeBridgesTheGap` must count colours, not mana; knob read once per process; `_talk_tick` listing during the rate-limit gap | ring cursor advanced before a punted window re-offers (pre-existing W-25 code; noted below) |

Open note from round three (not this diff): `_consume_ring` advances the observer-ring cursor when the menu is
built; if the same window is re-offered after a punt the `hit` situation is gone. Watch under W-25.

## Gemini flash, round two (verbatim, truncated by the model's output cap)

Here is the adversarial review of the diff-v2 revision.

---

### Finding 1: `chainCopiesOwn` conflates targeting and copy effects across separate sub-abilities, opening dead windows for counter/removal spells
* **Severity:** P1 (Flood / Seam violation)
* **Quote:**
  ```java
  private static boolean chainCopiesOwn(SpellAbility root, List<SpellAbility> own) {
      boolean copies = false;
      boolean targetsOwn = false;
      for (SpellAbility p = root; p != null; p = p.getSubAbility()) {
          ...
          if (p.getApi() == forge.game.ability.ApiType.CopySpellAbility) {
              copies = true;
          }
          forge.game.spellability.TargetRestrictions tgt = p.getTargetRestrictions();
          if (!targetsOwn && tgt != null && tgt.getZone() != null
                  && tgt.getZone().contains(ZoneType.Stack)) {
              for (SpellAbility o : own) {
                  if (p.canTargetSpellAbility(o)) {
                      targetsOwn = true;
                      break;
                  }
              }
          }
      }
      return copies && targetsOwn;
  }
  ```
* **Scenario:**
  Seat 3 casts *Devastating Onslaught* (its own sorcery is on the stack). Seat 3 holds *See Double* ("Choose one or both — Copy target spell an opponent controls; Create a token that's a copy of target creature") or any spell whose chain contains a `CopySpellAbility` mode/sub-ability that cannot legally target an own spell (e.g. opponent-only restriction), combined with a sub-ability or secondary effect that can target spells on the stack (e.g. an un-modal or chained counter/bounce/redirect). 
  More directly: consider a chained spell like *Expansion // Explosion* where one half has `CopySpellAbility` or a card with an ETB/trigger chain where sub-ability A targets a spell on the stack (e.g. an ETB counter or return to hand) and sub-ability B has `CopySpellAbility` (targeting an opponent's creature/permanent or opponent's spell). 
  Because `copies` and `targetsOwn` are decoupled booleans accumulated over the entire `for (SpellAbility p = root; ...)` traversal, if *any* ability in the chain has `ApiType.CopySpellAbility` and *any* ability in the chain can target an own spell on the stack, `chainCopiesOwn` returns `true`. The window opens and offers the spell even though the copy effect itself cannot copy the own spell on the stack, violating the gate's invariant that counters and redirects do not open the window.
* **Verification:**
  Traced `chainCopiesOwn`: `copies` is flipped to `true` whenever `p.getApi() == ApiType.CopySpellAbility`, irrespective of whether `p` has target restrictions or what it targets. `targetsOwn` is flipped to `true` whenever `p.canTargetSpellAbility(o)` succeeds on *any* sub-ability `p`. They are never bound to the same sub-ability or verified to share a target. While this was done to accommodate *Wild Ricochet* (where `ChangeTargets` is the root and `CopySpellAbility` is the sub-ability copying the root's target), it leaves `copies` and `targetsOwn` unlinked for any multi-part or chained ability.

---

### Finding 2: `sourcesShortOfShards` counts colorless sources toward colored pip sufficiency, stranding generic mana when non-Phyrexian colored pips exist
* **Severity:** P1 (Engine seam / AI mana payment failure)
* **Quote:**
  ```java
  if (chosenPayment != null
          && (lifeKeywordCovers(ai, toPay) || toPay.isPhyrexian())
          && sourcesShortOfShards(cost, sourcesForShards)
          && ai.canPayLife(phyLifeToPay, false, sa)
          && (ai.getLife() > phyLifeToPay || ai.cantLoseForZeroOrLessLife())) {
      chosenPayment = null; // route this shard into the life branch below
  }
  ```
  and `sourcesShortOfShards`:
  ```java
  mana += yield;
  ...
  return mana < cost.getUnpaidShards().size();
  ```
* **Scenario:**
  Player has 40 life, two Mountains, and one Wastes (or Sol Ring).
  The AI plays a cost with colored, generic, and Phyrexian shards: `{R}{1}{R/P}{R/P}` (4 shards total: one `{R}`, one `{1}`, two `{R/P}`).
  Legal play with mana + life: Mountain 1 pays `{R}`, Wastes pays `{1}`, Mountain 2 pays one `{R/P}`, and 2 life pays the other `{R/P}` (total: 3 mana from sources, 2 life).
  What Forge actually does:
  1. Initial state: 3 sources (2 Mountains, 1 Wastes). `mana = 3`. Unpaid shards = 4.
  2. `3 < 4` is true (`sourcesShortOfShards == true`). First shard to pay is `{R}` (mono-colored has highest priority under `getNextShardToPay`). Mountain 1 pays `{R}`.
  3. Remaining cost: `{1}{R/P}{R/P}` (3 shards). Remaining sources: 1 Mountain, 1 Wastes. `mana = 2`.
  4. `2 < 3` is true (`sourcesShortOfShards == true`). Next shard is `{R/P}` (Phyrexian priority over generic). Line 748 fires: Mountain 2 is NOT spent; `{R/P}` is paid with 2 life.
  5. Remaining cost: `{1}{R/P}` (2 shards). Remaining sources: 1 Mountain, 1 Wastes. `mana = 2`.
  6. Look at line 1203: `mana < cost.getUnpaidShards().size()` -> `2 < 2` is **FALSE**!
  7. Because `sourcesShortOfShards` returns **false**, line 748 does **not** fire!
  8. Next shard to pay is `{R/P}` (Phyrexian priority over generic). Forge looks for a source for `{R/P}`: Mountain 2 is available! Forge spends Mountain 2 on `{R/P}`!
  9. Remaining cost: `{1}` (1 generic shard). Remaining sources: Wastes (1 mana). Wastes pays `{1}`. (This case happens to pass).
  *Now consider the failing case:*
  Board: **Two Mountains, one Wastes, 40 life**. Cost: **`{R}{R}{R/P}{R/P}`** (4 shards, no generic).
  Sources: 2 Mountains, 1 Wastes (`mana = 3`).
  This is legally payable: Mountain 1 pays `{R}`, Mountain 2 pays `{R}`, and 4 life pays the two

## Gemini Pro, round three (verbatim)

Here are the findings from the current diff, ordered by severity.

### 1. `lifeBridgesTheGap` ignores mana colors, causing life bleed on unpayable costs
**Lines:** `ComputerUtilMana.java`
```java
    private static boolean lifeBridgesTheGap(final ManaCostBeingPaid cost,
            final Multimap<ManaCostShard, SpellAbility> sources, final Player ai) {
        // ...
        return countSourceMana(sources) >= unpaid - lifePayable;
    }
```
**Scenario:** The AI needs to pay `{2}{U}{R/P}` and controls an untapped Sol Ring and an untapped Mountain (40 life). `unpaid` is 4, `lifePayable` is 1. `sourcesForShards` contains Sol Ring (can pay `{2}`) and Mountain (can pay `{2}` or `{R/P}`). `countSourceMana` sums their yields to 3. Since `3 >= 4 - 1`, `lifeBridgesTheGap` returns `true`. The patch then routes the `{R/P}` shard to life, bleeding 2 life. However, the remaining `{2}{U}` cannot be paid because there is no blue source. The payment fails, and the rollback refunds the mana but **not** the 2 life. 
**Severity:** P1 (regression: life bleed on a payment that stock would have failed without spending life).
**Verification:** Read `countSourceMana` and `lifeBridgesTheGap`. `countSourceMana` simply sums the total mana yield of all unique sources that can pay for *at least one* unpaid shard. It does not verify if those sources can actually satisfy the specific color requirements (like `{U}`) of the remaining shards.

### 2. Observer ring events (hits and counters) are lost if the model punts or times out
**Lines:** `runner.py`
```python
        self._hit_since, self._countered_by = None, None
        for e in sorted((e for e in events if isinstance(e, dict)), key=lambda e: int(e.get("seq", 0))):
            seq = int(e.get("seq", 0))
            if seq <= self._ring_seq:
                continue
            self._ring_seq = seq
```
**Scenario:** An opponent hits the AI seat, adding a `damage` event to the observer ring. A priority window opens, and `handle` calls `_say_menu`, which calls `_situations`, which calls `_consume_ring`. `_consume_ring` reads the damage event, sets `self._hit_since`, and unconditionally advances `self._ring_seq`. The prompt is sent, but the model times out or punts (`source == "punt"`). The engine waits and retries the exact same window on the next tick. `_consume_ring` is called again, clears `self._hit_since`, and because `self._ring_seq` was already advanced, it skips the damage event. The menu offered on the retry lacks the `hit` situation, silently dropping the AI's ability to use grudge stances or hit-related table talk.
**Severity:** P1 (gap: state loss on retry leading to a degraded menu).
**Verification:** Read `_consume_ring` and `handle` in `runner.py`. `_consume_ring` advances the cursor and clears the flags regardless of whether the model successfully consumes the request, while `handle` aborts and retries the same request if the model punts.

### 3. Environment variable for self-spell knob is read on every priority window
**Lines:** `MailboxController.java`
```java
        // ARENA_SELF_SPELL_WINDOW=off restores the W-14 clean pass (kill switch
        // while the flood cost is measured; the banner and README list it).
        String selfSpellKnob = String.valueOf(System.getenv("ARENA_SELF_SPELL_WINDOW")).trim().toLowerCase();
```
**Scenario:** During a game, `chooseSpellAbilityToPlay` is evaluated hundreds or thousands of times. Reading directly from `System.getenv` on every single priority window adds unnecessary overhead (it accesses a synchronized map in Java) instead of caching the knob state during initialization or in a static variable.
**Severity:** P2 (nit / performance).
**Verification:** Read `chooseSpellAbilityToPlay` in `MailboxController.java`. The environment variable is fetched inline every time the method is called.

### 4. Table talk rate limiting causes continuous directory listing
**Lines:** `runner.py`
```python
        if time.time() - self._talk_last < self.TALK_GAP_S:
            self._notes_dirty = True                 # rate-limited: they keep until the next tick
            return
```
**Scenario:** A table talk note arrives and the seat answers it. Another note arrives 1 second later. `_talk_tick` sees the new note, but because `time.time() - self._talk_last < 5.0`, it sets `_notes_dirty = True` and returns. On the next idle pass (e.g., 0.1s later), it bypasses the `sig` check because `_notes_dirty` is true, lists the directory again, and hits the rate limit again. This repeats dozens of times until the 5-second gap elapses, causing unnecessary disk I/O on every tick.
**Severity:** P2 (nit / performance).
**Verification:** Read `_talk_tick` in `runner.py`. The `_notes_dirty` flag forces an `iterdir()` on every tick while the rate limit is active.

***

### What I could not verify
* **Whether `SAY_QUESTIONS` are allowed in stances:** I cannot see `say-menu.json` to verify if question IDs are permitted in the `stances` block. If they are, `_stance_key` lacks the check that prevents aiming questions at the human (unlike `_say_key`).
* **Whether `refusedHost` is properly filtered from the final AI prompt:** The diff ensures `refusedHost` cannot be the *reason* a `selfSpell` window opens, but it does not remove it from `playable`. I assume the existing runner/prompt logic (item 4) handles filtering or warning the AI not to pick it again.


---

# Commit review (Gemini Pro, 2026-11-07 late) — every uncommitted body of work, before the commits

Ben: "run all of the commits past gemini for bugs and issues, dont execute, just gather the review then discuss with
me" → "Clean everything up take all the fixes, check context around them as you opperate, go with care, and
precision. then push when confident." Three passes of `git diff -U20` plus the new files: A the seat side (talk-back,
say menu, stances; 144k chars), B the voice side (153k), C the engine seams (72k). Every finding was checked against
the code before a change.

| # | Finding | Verdict | Disposition |
|---|---|---|---|
| A1 | the quiet-window `say` line never shows the `{"id","to"}` form | confirmed | fixed: the quiet line names the object form for its aimed ids |
| A2 | `say_card` only on CAST_SPELL; `my_cast` only in main phases | half | fixed `say_card` for REACT casts; `my_cast` stays main-phase by design |
| A3 | unguarded `int()` on observer fields in `_situations` | hardening | fixed: malformed entries are skipped |
| A4 | the stack-threat loop keeps the last item, not the game changer | confirmed | fixed: a game changer outranks a later big spell |
| A5 | `cast-big` lit on a six-mana activation | confirmed | fixed: only a pure mana cost counts |
| A6 | plain-text talk replies may loop on JSON retries | refuted | live replies land in 2–3 s; the path reads the raw text on purpose |
| B1 | an expired stance wiped the seat's freshly armed ones | confirmed (the real bug) | fixed: only expired triggers die |
| B2 | shape-(b) stance replies skipped the named-address swap | confirmed | fixed: `address_swap` with certainty, as `maybe_bark` does |
| B3 | the shape-(b) test enforces the bug | refuted | the test read the generic id; it now also pins `hit-urza` |
| B4 | `_stance_fired` not checkpointed | confirmed | fixed: saved and restored |
| C1 | a dual land counts once per colour in `lifeBridgesTheGap` | confirmed, minor | documented under BL-65 (stock bleeds the same) |

## Part A — seat side (verbatim)

Here is a review of the uncommitted changes, focusing on bugs, protocol mismatches, and edge cases.

### 1. P1: Quiet window prompt lacks the `to` syntax explanation
**File:** `runner/seatd/rules.py`
**Lines:** 177-182 (`say_menu_block`)
**Scenario:** When `charged` is False (a quiet window), `say_menu_block` returns the short line: `OPTIONAL "say": one of [...] — a table line your seat speaks aloud...`. It completely omits the explanation of the `{"id": "<id>", "to": <seat number>}` syntax. However, the `core` ids offered on a quiet window include `youre-the-threat` and `kill-that`, which both have `"to": true`. Furthermore, uncharged situations like `leader` can offer ids like `whats-your-life` which also require a target. The brain will not know how to target these lines, resulting in dropped targets or malformed JSON.
**Verification:** The code explicitly branches on `if not charged:` and returns a string that only shows the `"<id>"` format, omitting the `to` dictionary syntax entirely.

### 2. P1: `say_card` and `my_cast` situations are missing on `REACT` windows
**File:** `runner/seatd/runner.py`
**Lines:** 405-409 (`_say_meta`), 467-477 (`_situations`)
**Scenario:** The AI casts an instant, a flash creature, or its commander during another player's turn or in response to a spell. The engine sends a `REACT` window, not a `CAST_SPELL` window. Because `_say_meta` explicitly checks `req.get("decisionType") == "CAST_SPELL"`, it fails to populate `say_card`, leaving the voice runner unable to speak the named card line. Similarly, `_situations` restricts `my_cast` to `CAST_SPELL` and `MAIN1`/`MAIN2`, meaning the AI will never be offered the `commander-cast`, `game-changer`, or `cast-big` lines when casting them at instant speed.
**Verification:** `_say_meta` checks `if req.get("decisionType") == "CAST_SPELL"`. `_situations` checks `if dtype == "CAST_SPELL" and phase in ("MAIN1", "MAIN2")`. Both ignore `REACT` windows, which are the engine's vehicle for instant-speed casts.

### 3. P1: Crash risk in `_situations` from unvalidated observer data
**File:** `runner/seatd/runner.py`
**Lines:** 453-454, 456-458 (`_situations`)
**Scenario:** The observer state contains a cast event where `seat` is explicitly `None`, or a `stackDetail` item where `owner` is a non-numeric string (e.g., `"Player 1"`). The dictionary comprehension `int(e.get("seat", -1))` will raise a `TypeError` if `seat` is `None`. Similarly, `int(item["owner"])` will raise a `ValueError`. Because `_say_menu` does not wrap `_situations` in a `try/except` block, this will crash the seat runner entirely.
**Verification:** While `_consume_ring` safely wraps its event parsing in `try/except (TypeError, ValueError):`, `_situations` does not protect its `casts` comprehension or its `stackDetail` loop.

### 4. P2: `_situations` overwrites `threat` in the `stackDetail` loop
**File:** `runner/seatd/runner.py`
**Lines:** 456-463 (`_situations`)
**Scenario:** Multiple spells are on the stack (e.g., a game changer, followed by a 5-CMC spell, followed by a counterspell). The `for item in obs.get("stackDetail")` loop evaluates each item and overwrites the `threat` variable. If the game changer is evaluated first, it will be overwritten by the 5-CMC spell. Consequently, `threat["gc"]` will be False, and the `gc-react` line will not be offered, even though a game changer is actively on the stack.
**Verification:** `threat = {"owner": owner, "name": name, "gc": ...}` blindly overwrites the previous `threat` without prioritizing game changers or breaking early.

### 5. P2: `label_cmc` triggers `cast-big` for activated abilities
**File:** `runner/seatd/rules.py`
**Lines:** 152-161 (`label_cmc`)
**Scenario:** The AI is offered an activated ability that costs `{6}` to activate. `label_cmc` counts the mana symbols and returns 6. `_situations` sees `big = True` and populates the `my_cast` situation. The AI is offered the `cast-big` line, whose gloss is "you are casting a six-plus mana spell", leading to the AI announcing a spell cast when it is merely activating an ability.
**Verification:** `label_cmc` is applied to all options in `req.get("options")` (except `id == 0`), which includes activated abilities, not just spells from hand.

### 6. P2: `brain.decide` may retry on plain text output for `TABLE_TALK`
**File:** `runner/seatd/runner.py`
**Lines:** 687-688 (`_answer_talk`)
**Scenario:** `_answer_talk` instructs the brain to output plain text (`"no JSON"`). If the underlying `brain.decide` implementation (which is not shown but typically enforces the JSON contract) automatically catches `json.decoder.JSONDecodeError` and retries the prompt under the hood, it will waste time and API calls looping until it hits its retry limit, before finally returning the raw text in `meta["raw"]`.
**Verification:** The prompt explicitly asks for plain text, but there is no flag passed to `brain.decide` (e.g., `expect_json=False`) to bypass its standard JSON validation loop.

## Part B — voice side (verbatim)

Here is the review of the VOICE side changes, focusing on bugs, protocol mismatches, and test weaknesses.

### 1. `st.clear()` in `take_stance` wipes out newly armed stances
**Severity:** P1 (Data loss / wrong play)
**File:** `runner/voice/events.py`
**Lines:** 445–449
```python
        if not self._stance_alive(seat, h):
            for trig, old in list(st.items()):
                self.record("noted", kind="stance", why="expired", stock=old["id"], seat=seat, source="brain", trigger=trig)
            st.clear()
            return None
```
**Scenario:** 
Because `_roll_turn` (which calls `expire_stances`) is evaluated lazily only when a bark is attempted, a seat's expired stances from a previous turn often survive into its new turn until the first event happens. 
If Seat 1 acts quickly on its new turn and arms a *new* stance (e.g., `on_counter`), and then gets hit, `take_stance(1, "on_hit")` is called. It sees that the old `on_hit` stance is expired (`_stance_alive` is False) and calls `st.clear()`. This wipes out the entire dictionary for that seat, deleting the newly armed `on_counter` reflex before it can ever be used.
**Fix:** Only delete the specific expired triggers, or rely on `expire_stances` to clean up the dictionary properly.

### 2. Stance replies (Shape b) skip `address_swap`
**Severity:** P1 (Protocol mismatch)
**File:** `runner/voice/scheduler.py`
**Lines:** 624–632
```python
            if parent_ctx.get("card"):
                named = self.card_swap(who, reply, parent_ctx)
                if named:
                    self._turn_said().add((who, named))
                    rctx["generic"] = reply
                    reply = named
            self.enqueue("bark", stock=reply, library=self.lib_for(who, reply), seat=who, ttl=15.0, gap=self.chains.gap_s, ctx=rctx, chain=link, source="stance")
```
**Scenario:** 
The plan (Step 3) requires that brain-aimed lines (like `"kill-that"`) are named every time (`"hit-urza"`). `maybe_bark` correctly implements this for Shape (a) stances by passing `certain=True` to `address_swap`. 
However, Shape (b) stances (where a stance fires as a hop-1 chain reply to another AI's line) are processed in `scan_chain`. `scan_chain` calls `card_swap` but completely omits `address_swap` before calling `enqueue` directly. If a brain arms `on_gc` with `"kill-that"` and `to=1`, the voice will speak the generic `"kill that"` instead of the intended `"hit Urza"`.

### 3. Test weakness enforcing the `address_swap` bug
**Severity:** P1 (Test weakness)
**File:** `runner/tests/test_events_hardening.py`
**Lines:** 407–411
```python
    def test_shape_b_another_seats_line_draws_the_holders_reflex_as_the_reply(self):
        self._prime()
        self._arm(2, on_gc="kill-that")
        self._spoken(1, "game-changer", ctx={"targets": [], "card": "mana-vault", "card_kind": "gc"})
        q = [(x["ctx"].get("generic", x["stock"]), x["seat"], x["source"], x.get("chain", {}).get("hop"), x["ctx"].get("targets")) for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual(q, [("kill-that", 2, "stance", 1, [1])], "the pre-chosen hop-1 reply, through the chain's link")
```
**Scenario:** 
This test asserts that the queued stock for the `on_gc` stance reply is exactly `"kill-that"`. Because `"kill-that"` is in `BRAIN_NAMED_CERTAIN`, it *should* be address-swapped to `"hit-urza"` (since `to=1` via the chain target). If the `address_swap` bug in `scan_chain` (Finding 2) is fixed, the queued stock will correctly become `"hit-urza"`, and this test will fail. The test is currently written against the buggy outcome and enforces it.

### 4. `_stance_fired` cap counters are lost on mid-turn restart
**Severity:** P2 (Unreset state / Data loss)
**File:** `runner/voice_runner.py`
**Lines:** 543–544
```python
            "stances": {str(s): {t: dict(h) for t, h in st.items()} for s, st in sorted((self.__dict__.get("_stances") or {}).items()) if st},
            "held_say": {str(s): dict(h) for s, h in sorted((self.__dict__.get("_held_say") or {}).items())},   # the brain's words (plan steps 2 + 4)
```
**Scenario:** 
The `_stance_fired` dictionary tracks how many reflexes a seat has fired this turn to enforce `stance_fires_per_turn`. If the voice runner restarts mid-turn (e.g., due to a crash or a token rotation), it restores `_stances` and `_held_say` from the checkpoint, but `_stance_fired` is omitted from both `_durable_state` and `_recency_state`. The fire counters reset to 0, allowing a seat to exceed its reflex cap for that turn.

## Part C — engine seams (verbatim)

Here is the review of the uncommitted work.

### `lifeBridgesTheGap` can return false positives when multiple colored shards share a single multi-color source
**Severity:** P2 (Minor — defaults safely to stock behaviour)
**File:** `forge-ai/src/main/java/forge/ai/ComputerUtilMana.java`
**Lines:** 1218–1234
```java
        if (countSourceMana(sources) < remainingCount) {
            return false;
        }
        for (java.util.Map.Entry<ManaCostShard, Integer> e : remaining.entrySet()) {
            // ...
            final Set<Card> able = new HashSet<>();
            for (SpellAbility ma : sources.get(shard)) {
                // ...
                    able.add(host);
            }
            if (able.size() < e.getValue()) {
                return false;
            }
        }
        return true;
```

**Concrete scenario:** 
The seat wants to cast a spell costing `{B/P}{B/P}{R/P}`. It has 3 life (enough to pay for exactly 1 Phyrexian shard) and controls 1 Badlands and 1 Sol Ring. 
1. `lifePayable` evaluates to 1, so the first `{B/P}` is routed to life.
2. `remaining` now needs 1 `{B/P}` and 1 `{R/P}`. 
3. `countSourceMana` is 3 (Badlands yields 1, Sol Ring yields 2). `remainingCount` is 2. `3 < 2` is false, so the total yield check passes.
4. The loop checks `{B/P}`: Badlands is added to `able`, size 1 >= 1.
5. The loop checks `{R/P}`: Badlands is added to `able`, size 1 >= 1.
6. `lifeBridgesTheGap` returns `true`, falsely believing the remaining shards can be paid. 

The first `{B/P}` is paid with life. The second `{B/P}` consumes the Badlands. The `{R/P}` then fails because there are no sources left and life cannot be paid. The payment fails, bleeding 2 life.

**How verified:** 
Traced the logic. The `able` check evaluates each color independently, allowing a single multi-color source (Badlands) to satisfy both the `{B/P}` and `{R/P}` checks simultaneously, while a colorless source (Sol Ring) inflates `countSourceMana` to pass the total yield check. 

*Note on severity:* This is ranked P2 because it does not introduce a *new* life bleed compared to stock. In the exact same scenario, stock would use Badlands for the first `{B/P}`, pay life for the second `{B/P}`, and fail on `{R/P}`, bleeding 2 life anyway. A true bipartite matching algorithm would be required to perfectly assign multi-color sources, but the current heuristic is lightweight and safe enough for the engine.

---

### Everything else is exceptionally solid
The rest of the patch is highly robust and elegantly handles the design constraints:
- **`sourcesShortOfShards`:** Perfectly identifies when the seat is short on total mana, preventing preemptive life payments when the seat has enough total mana (even colorless) to cover the cost.
- **`aimsAtOwnStack`:** Correctly traverses the ability chain (including Charm modes and redirect roots) and safely probes ETB triggers by copying them with the correct activating player.
- **`selfSpell` window:** The logic correctly isolates the seat's own spells/activations from opponent objects (which are correctly handled by the `reactive` window) and from triggers (handled by `selfTrigger`). The fallback to `null` on brain timeout safely resolves the spell instead of letting stock AI hijack the seat's own stack object.
- **Affordability guard (`playChosenSpellAbility`):** Catching activated abilities here correctly prevents unpayable Phyrexian activations (like Solphim) from bleeding life in the engine's rollback. The `refusedHost` logic perfectly prevents livelocks by omitting the unaffordable copy spell from the next window's options without breaking the `aims` check.
