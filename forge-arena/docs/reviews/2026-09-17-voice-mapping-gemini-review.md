# Voice/seat mapping — the simplified rule and Gemini's double check (2026-09-17)

Ben, after game 58: "please harden and simplify the voice/seat mapping. Use Google Gemini as a double
check. Be sure to account for four new random decks, and tables where no voice association has been
specified." And: "The only seat that is generally voiceless now is the player's… The logic there is
tortureously complex."

## The rule (`runner/voice/table.py`, one function, three passes)

1. **The human's seat is silent.** `human_seat` is 0 on a human table and `None` on an all-AI table
   (`ALL_SEATS=1`); it is the only seat that never gets a library.
2. **Joshua sits only where there is no human.** A library whose manifest says `"role": "advisor"` is
   dropped from the pool whenever a human is seated; on an all-AI table he is a seat like the others.
3. **Associations first, lower seat wins.** `voices/assign.json` `by_deck` maps a deck slug to a
   library. Seats are walked in order; a seat whose deck is associated takes that library if it is
   still free.
4. **Then the fallback order.** Every seat still without a voice takes the next free library in
   `assign.json` `fallback` (then any library not listed, by its manifest `seat`, then name). Four new
   random decks therefore hear Harry, Bill, Lily (and Joshua on an all-AI table) in that order; a
   table with no associations at all is identical.
5. **The table is seated once, at startup, from the launcher's `ARENA_HUMAN_DECK` /
   `ARENA_SEAT_DECKS`, and never moves.** `table_from_launcher` is the single place the roster becomes
   seat → deck; seatd names deal parties from the same function. The old `learn_table` rebind from the
   game log and `seat_decks_from_roster`/`seat_decks_from_game_log` are gone.

Was there an existing knob? Yes — `assign.json` was already the association file; the fix was to
make it the whole story (one `by_deck` + one `fallback` list) rather than add another environment
variable. No new knob was added.

## What Gemini (gemini-pro-latest) was given

The rewritten `table.py`, the three call sites (`voice_runner.py`, `seatd/runner.py`, the tests),
`assign.json` and Joshua's manifest, and nine requirements (silent human seat; advisor never with a
human; associations then fallback; four unknown decks; no associations; all-AI seat 0; string and
missing manifests; roster shorter than four; the table never moves).

## Gemini's review, verbatim

**DEFECTS**

1. `load_libraries` crashes on non-dict JSON.
   Line: `seat = int(m.get("seat")) if m.get("seat") is not None else 99`
   Input: A `manifest.json` containing a list, e.g., `[]`.
   Observed: `AttributeError: 'list' object has no attribute 'get'`.
   Expected: Skips the file or defaults to seat 99 (requires an `isinstance(m, dict)` check or catching `AttributeError`).

2. `load_assignments` crashes on invalid `by_deck` types.
   Line: `return dict(_assign_file(voices_dir).get("by_deck") or {})`
   Input: `assign.json` containing a string instead of an object, e.g., `{"by_deck": "invalid"}`.
   Observed: `ValueError: dictionary update sequence element #0 has length 1; 2 is required`.
   Expected: Returns `{}`.

3. `load_libraries` stringifies `None` for explicit null voice names.
   Line: `"voice": str(m.get("voice_name", mp.parent.name)).split(" - ")[0]`
   Input: `manifest.json` containing `{"voice_name": null}`.
   Observed: `m.get` returns `None` (because the key exists), `str(None)` evaluates to `"None"`, and the voice is named `"None"`.
   Expected: Falls back to `mp.parent.name` (e.g., using `m.get("voice_name") or mp.parent.name`).

**EDGE CASES**

1. In `table_from_launcher`, if the `roster` contains duplicates of the `human_deck` (e.g., `"deckA deckA deckB deckC"` with `human_deck="deckA"`), the comprehension `[d for d in slugs if d != human_deck]` removes *all* instances. This leaves only `["deckB", "deckC"]`, seating fewer than 3 AI opponents at the table.
2. In `assign_voices`, if `seat_decks` is passed with string keys (e.g., `{"1": "urza"}` from a raw JSON payload bypassing the launcher), `seats` correctly parses the integers via `int(s)`, but Pass 2's `seat_decks.get(seat, "")` will look up the integer `1`, fail to find the string key `"1"`, and silently skip the deck's association.

**SIMPLIFICATIONS**

1. In `load_libraries`, the `seat` parsing can drop the `is not None` check by relying on the existing `TypeError` catch (since `int(None)` raises `TypeError`):
   ```python
   try:
       seat = int(m.get("seat", 99))
   except (TypeError, ValueError):
       seat = 99
   ```

2. In `load_fallback`, the `or []` is redundant because `isinstance(None, list)` safely handles the missing key case:
   ```python
   fb = _assign_file(voices_dir).get("fallback")
   return [str(x) for x in fb] if isinstance(fb, list) else []
   ```

3. In `assign_voices`, assuming the type hint `dict[int, str]` is respected by callers, the redundant `int()` casts can be removed:
   ```python
   seats = sorted(s for s in seat_decks if s != human_seat)
   ```

**VERDICT**
Fix first.

## Applied (all of it, same day)

- Defects 1–3: a manifest that is not a JSON object is skipped; a `by_deck` that is not an object is
  no associations; `"voice_name": null` falls back to the folder name.
- Edge case 1: a roster naming the human's deck twice removes ONE copy.
- Edge case 2: `seat_decks` keys are normalised to `int` once, so JSON string keys still honour the
  associations.
- Simplifications 1–2 taken; 3 (drop the int casts) declined — the normalisation above is the safer
  form of the same idea.
- Tests: `tests/test_barks_runtime.py` (string keys, malformed manifest, null voice name, malformed
  assign file, roster duplicate) and `tests/test_bark_libraries.py`.
