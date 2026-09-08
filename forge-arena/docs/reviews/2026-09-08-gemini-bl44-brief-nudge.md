# Gemini review — BL-44 (seat-side colour picks) and the seat-brief nudge (2026-09-08 16:25)

Reviewer: Gemini (gemini-cli, Ben's Pro account) with the ledger entries, the brief's mana section, the human-side
mono-colour rule (`AdvisorControllerHuman` 590–635), the engine's colour window (`MailboxController` chooseColor →
`CHOOSE_MODE`, `state.purpose = "COLOR"`), the runner's fastpath/memo code, the dossier's `color_identity` field and one
real window from game 32 as context. Verdicts: A build rule (1) only — mono-colour auto-pick keyed on
`purpose == "COLOR"` + label check, identity from the commander entries' `color_identity` union, `rules.validate` before
answering; do NOT build rule (2) (multi-colour replay — breaks deliberate splits, fragile activation boundary).
B: one sentence, drop the "cast every cheap engine" half (overextension into sweepers, bluffs, single-point risk).

Mainline verification (Claude): `state.put("purpose", "COLOR")` is at MailboxController 3386 and the options are typed
"COLOR" (3393); `TRIGGER_ORDER` is the other purpose (3538); `rules.validate` exists and CHOOSE_MODE answers are
`{"chosen": [index]}` (rules.py 11, 43). The design is buildable as written, Python + brief only. NOT BUILT at the time
of this record — awaiting Ben's call.

---

### A — BL-44: Seat-Side Colour Picks

* **Verdict:** Build with changes. Build **Rule (1) (mono-color auto-pick)** only. **Do NOT build Rule (2) (multi-color replay)**.

* **Concrete Risks of Rule (2):**
  1. **Disrupts Necessary Mana Splits:** In multi-color decks, "any combination of colors" is often used to produce a precise mix of colors to cast multiple distinct spells in hand (e.g., a green spell and a blue spell). Replaying the first pick forces all mana from that activation to be of a single color, leading to game-losing cast failures.
  2. **Boundary Fragility:** Correctly detecting the start and end of "the same activation" in Python is fragile, error-prone, and sensitive to nested spells/abilities, stack changes, and timing issues. Rejecting Rule (2) removes this entire class of bugs.

* **Answers to Specific Questions:**
  * **Recognition of mana-colour pick:** Robustly key on `req.get("decisionType") == "CHOOSE_MODE"` AND `req.get("state", {}).get("purpose") == "COLOR"` (mirroring line 3386 where the engine puts `"purpose", "COLOR"`). For defense-in-depth, verify that the option labels are standard Magic color names (`{"white", "blue", "black", "red", "green", "colorless"}`).
  * **Source of color identity:** Parse `/decks/<slug>/dossier/deck-cards.json` at runner startup. Collect all cards where `"zone" == "commander"`, and extract their `"color_identity"`. Union the characters to handle Partner commanders. If the union contains exactly one character from `"WUBRG"`, it is mono-colored.
  * **Colourless-identity decks:** The union of color characters is empty (size 0), so the fastpath is correctly skipped.
  * **Hybrid/Phyrexian costs / Stolen cards:** If the option set does not contain the commander's mono-color, the matching search fails and falls back to the model. This perfectly mirrors the human-side safety check `colors.hasAnyColor(mono)` in `AdvisorControllerHuman.java` line 603.
  * **Deliberate splits / Chromatic Lantern off-colour wants:** For mono-color decks, producing off-color mana has no benefit as they have no off-color cards in their main deck. Under standard rules, picking their own mono-color is always correct. This is why Forge human play already auto-picks the mono-color without human prompt (see `AdvisorControllerHuman.java` line 602).
  * **CHOOSE_MODE with "colorless":** The code searches for the mono-color label. If present, it picks it (producing colored mana is strictly better or equal to colorless); if absent, it falls back.

* **Minimal Design:**
  1. **Startup Initialization:** Inside `Runner.__init__`, parse `deck-cards.json` to cache the mono-color label if applicable:
     ```python
     self._mono_color_label = None
     COLOR_MAP = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
     # Parse deck-cards.json for commanders
     # Collect unique color characters. If len(colors) == 1, self._mono_color_label = COLOR_MAP[color]
     ```
  2. **Fastpath Implementation:** Inside `_fastpath()`:
     ```python
     st = req.get("state", {}) or {}
     if req.get("decisionType") == "CHOOSE_MODE" and st.get("purpose") == "COLOR" and self._mono_color_label:
         for idx, o in enumerate(req.get("options", []) or []):
             label = str(o.get("label", o) if isinstance(o, dict) else o).lower()
             if label == self._mono_color_label:
                 chosen_id = o.get("id", idx) if isinstance(o, dict) else idx
                 ans = {"chosen": [chosen_id]}
                 if rules.validate(req, ans) is not None:
                     return ans, "color_auto_pick"
     ```

* **Tests Needed:**
  1. **Color Identity Parser:** Test parsing of various `deck-cards.json` configurations: single commander (e.g. `"color_identity": "G"`), partner commanders (e.g. `"W"` and `"U"`), colorless commander (e.g. `""`), and malformed or missing JSON.
  2. **Fastpath matching:** Test that a mock `CHOOSE_MODE` with `purpose: "COLOR"` and options `["white", "blue", "black", "red", "green"]` is successfully auto-picked for a mono-green deck. Test that it falls back if the target color is absent or if the purpose is different (e.g., `"TRIGGER_ORDER"`).

---

### B — Seat-Brief "Nudge" Sentence

* **Verdict:** Build with changes. Reject proposal (b) entirely. Combine and rewrite (a) into a single, high-density, risk-aware sentence to conserve context and avoid cache invalidation.

* **Concrete Risks of (b) ("do not end a main phase with cheap mana engines uncast"):**
  1. **Overextension into Sweepers:** In 4-player Commander, board wipes are ubiquitous. Forcing the model to aggressively empty its hand of dorks/engines makes it highly vulnerable to sweepers, leaving it with no cards to rebuild.
  2. **Loss of Bluffs & Interaction:** Holding cards in hand is essential to bluffing interaction (e.g., instant-speed removal or protection).
  3. **Concentration Risk:** Forcing all resources to be cast or banked onto a single creature (Omnath) exposes the entire board state to single-point removal. If Omnath is destroyed, all banked mana is permanently lost. Keeping lands untapped or cards in hand is a safer, distributed-asset strategy.

* **Minimal Design:**
  Append a single highly-condensed sentence to the end of the **mana section** (after line 70 in `seat-brief.md`) that encourages banking unspent mana where mechanically persistent, while explicitly highlighting the risks of overextension and loss of interaction.

* **Exact Wording:**
  ```markdown
  - If unspent mana persists for you (Omnath, Kruphix), float unused mana before ending your main phase to bank it, but keep interactive mana up; avoid overextending dorks or banking everything on a fragile creature vulnerable to removal.
  ```
