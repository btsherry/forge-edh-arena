# SEAM AUDIT — dual-model, 2026-08-28

Same brief (scratchpad seam-audit-brief.md, preserved below §3) to two
independent auditors: a Fable subagent with live repo access (55 tool
calls, real greps) and gemini-pro-latest with all ~449KB of materials
inlined. Neither saw the other's output. Comparison: §0. Verbatim
reports: §1 (Fable), §2 (Gemini).

## §0 Comparison (session author)

**Consensus findings (both models, independently — highest confidence):**
1. **Cleanup-step discard to max hand size** (`chooseCardsToDiscardToMaximumHandSize`)
   — Gemini #1, Fable #4. Stock bins the sculpted Necropotence/wheel/One Ring
   hand with zero mailbox records. Cheapest fix of the set (existing wire shape).
2. **Pitch-cost payments** (`AiCostDecision.visit(CostExile/CostReturn/CostDiscard)`)
   — Gemini #3, Fable #3. Stock picks WHICH card Force of Will eats
   (chooseExileFromList sorts by power ascending — meaningless for instants,
   Fable's detail). Fix = clone the shipped SacCostPreference pattern.
3. **Top-of-library class** (`orderMoveToZoneList`, `arrangeForScry/Surveil`,
   `willPutCardOnTop`) — Gemini #2+HM, Fable HM. Top/Scroll Rack/Sylvan
   Library play blind at stock quality AND the peeked cards are never
   serialized (Fable's info-loss angle). Needs a new ORDER shape.
4. **Number/announce choices beyond the two hooked paths** — Gemini #5 (generic
   chooseNumber, Wheel of Misfortune), Fable HM#1 (non-X Announce$ vars:
   Multikicker, Everflowing Chalice enters with 0 counters — note-15b's sibling).

**Fable-only (the code-depth class — required executing greps):**
- **#1 REACT memo is phase/combat-blind** — our own 21b fix's signature omits
  phase + state.combat + stackTargets, so a correct early-combat pass fast-
  passes every later window that turn: the fog/save death from game 2,
  resurrected one layer up. Runner-only fix, probe included. SHARPEST FINDING.
- **#2 `chooseNewTargetsFor` returns null for AI** — a whole new gap CLASS:
  the cast gate offers spells stock deliberately never casts (Deflecting
  Swat, Return the Favor — both in Purphoros), then RESOLUTION lands on a
  stock surface that cannot act: card resolves as a silent no-op.
- **#5 Mother-of-Runes autopass contradiction** — the shipped allowlist
  dropped note-12's "no threatened target" clause and ignores the new
  stackTargets data; plus un-overridden `chooseProtectionType` guesses the
  color. Contradicts note 24's "opponent-spell stops are never auto-passed".
- HMs: `allCards` gate silently bails on "creature or player" choices;
  TapCostPreference armed only by symmetry picks (Urza's routine artifact-tap
  payments can tap the Scepter the line needs); opponents' stack cards ship
  without oracle text (documented hallucination trigger).

**Gemini-only:**
- **#4 `chooseOptionalCosts`** — Buyback/Kicker/Cleave: stock declines the
  Buyback on Purphoros's Reiterate loop. Real, verified un-overridden.
- HMs: `chooseSingleReplacementEffect` ordering, `chooseCardsPile`
  (Fact or Fiction), `vote` (table politics).

**Verification:** every un-overridden surface named by either model was
grep-confirmed against MailboxController (zero hits each; the four
chooseNumber hits are all the hooked chooseNumberForCostReduction). Every
deck-grounding card named was confirmed present in the named list.

**Character of the two reports:** Gemini produced a clean, accurate
enumeration of the missing-override class — every claim checked out.
Fable additionally found bugs INSIDE shipped fixes (memo signature), a new
failure class (cast-gate/resolution-surface mismatch), and contradictions
with our own field notes — the kind of findings only live code inspection
reaches. Zero contradictions between the two reports; the union is the map.

**Suggested next-fix order (impact x cost):** (1) memo signature (runner-only,
known death pattern), (2) cleanup discard + mulligan bottoming (existing wire
shapes), (3) ExileCost/ReturnCost/DiscardCost preferences (shipped pattern),
(4) chooseNewTargetsFor + confirmAction gate widening, (5) autopass
threatened-target clause (stackTargets already serialized), then optional
costs / chooseNumber / top-of-library as the following wave.

## §1 Fable report (verbatim)

**1. Same-turn REACT memo is keyed blind to phase and combat — it re-eats the pre-damage fog window the tactical fix (#13) was built for.**
1. **Surface**: `SeatRunner._react_signature` / `_fastpath` in `forge-arena/runner/seatd/runner.py` (signature = `(turn, stack, opts, lives, pool)`), fed by every REACT pass (`react_seen.add` in `handle()`).
2. **Mechanism**: incompleteness in the 21b memo hardening. The signature includes stack names, option labels, lives, and pool — but **not the phase and not `state.combat`**. All tactical windows have an empty stack, and a held fog/save has identical option labels at COMBAT_BEGIN, DECLARE_ATTACKERS, DECLARE_BLOCKERS, pre-damage, and END_OF_TURN. So one pass at "beginning of combat, nothing declared yet" (a *correct* pass) memoizes, and every later window that turn — after attackers and blockers exist — is fast-passed at zero model calls. `stackTargets` is also absent, so a second same-named spell aimed at a different target collides too. Tests confirm the gap: `runner/tests/test_trigger_memo.py` never varies phase or combat.
3. **Predicted live symptom**: Giada dies to an alpha with Flare of Fortitude / Grand Crescendo / Flawless Maneuver in hand (the exact game-2 death, resurrected one layer up); Selvala never fires Heroic Intervention at blocks; end-step flash windows silently vanish after any earlier same-turn tactical pass. Log tell: `source:"memo"` records whose `board.combat` is non-null.
4. **Ten-minute probe**: `jq 'select(.source=="memo" and .board.combat != null)' runner/logs/archive/*/seat-*.jsonl` — any hit is the bug live. Unit: build two reqs differing only in `phase` + `state.combat`, assert `_react_signature` returns the same tuple (it does today).
5. **Fix shape**: runner-only, fail-safe (memo fires strictly less): add `req["phase"]` and a combat digest (`tuple((a["id"], a.get("defender"), tuple(a.get("blockedBy",[]))) for a in state.combat)`) plus `stackTargets` to the signature; or cheaper, clear `react_seen` whenever `state.combat` appears/changes.

**2. `chooseNewTargetsFor` is a hard null for AI — a seat-cast Deflecting Swat resolves as a silent no-op.**
1. **Surface**: `PlayerControllerAi.chooseNewTargetsFor` (`forge-ai/.../PlayerControllerAi.java:1364`, literally `// AI currently can't do this` → `return null`), reached from `ChangeTargetsEffect.resolve` (`forge-game/.../effects/ChangeTargetsEffect.java:145`); not overridden in MailboxController.
2. **Mechanism**: new seam-gap class — the mailbox *casting* gate uses `canPlay()`+affordability, so it happily offers spells stock AI deliberately never casts (`ChangeTargetsAi.checkApiLogic` returns `CantPlayAi` without `DefinedMagnet$ Self`), then resolution lands on a stock decision surface that cannot act. Chain: seat casts `[FREE]` Deflecting Swat, aims it via the seat-owned `chooseTargetsFor` → on resolve, the `Optional$ True` confirm falls to stock (MailboxController.confirmAction's `mode == null` branch only catches messages containing "play") → base `SpellAbilityAi.confirmAction` says yes → `chooseNewTargetsFor` returns null → `updateTarget` runs with an unchanged target block. Same for Return the Favor's `DBChangeTarget` mode (both in `purphoros-god-of-the-forge.dck`).
3. **Predicted live symptom**: Purphoros's seat "answers" removal on Terror of the Peaks (or joins a counter-war) with a free Swat, narrates the redirect, the Swat visibly resolves — and the original spell still hits its original target. Card + window burned, zero effect, no error anywhere.
4. **Ten-minute probe**: grep gui.out for the base-class warning `"default (ie. inherited from base class) implementation of confirmAction is used by Deflecting Swat"`; or a `ScepterCopyCastTest`-shaped test: opponent bolt on stack targeting seat creature, seat resolves Swat at it, assert the bolt's target changed (fails today).
5. **Fix shape**: override `chooseNewTargetsFor` in MailboxController — for each targeting part of the changing SA, run the existing single-target `CHOOSE_ENTITY` machinery against `getAllCandidates` on a cloned `TargetChoices`, return it (null → super = today's behavior); widen the `confirmAction` untyped gate to messages matching "change.*target". Zero parent-module edits.

**3. Pitch-cost payment is stock's pick — `visit(CostExile)` decides which card Force of Will eats, invisibly to the brain.**
1. **Surface**: `AiCostDecision.visit(CostExile)` (`forge-ai/.../AiCostDecision.java:187`) → `ComputerUtil.chooseExileFromList` (sorts by **power ascending** — meaningless for a hand of instants); siblings `visit(CostDiscard)` (:91, `aic.getCardsToDiscard`), `visit(CostReturn)`, `visit(CostPutCardToLib)`. Only 2 of ~40 visits are hooked (Tap, Sacrifice).
3. **Predicted live symptom**: Urza pitches Mana Drain (or the Dramatic Reversal its whole Scepter line needs) to a Force of Will it chose *because* it was "free"; next window the brain reports a hallucination-looking "where did my card go", and the planned line is dead. Same for Y'shtola's FoW/FoN in counter-wars.
4. **Ten-minute probe**: `SacrificeSeatChoiceTest` pattern — hand = FoW + two blue cards (one marked high-value), seat casts the alt-cost SA, assert which card got exiled and that zero mailbox windows fired during payment. Live: diff `state.hand` across a FoW cast in seat-N.jsonl.
5. **Fix shape**: clone the shipped `SacCostPreference` pattern — an `ExileCostPreference` interface in forge-ai consulted at the top of `visit(CostExile)` for the hand-zone/amount-N branch (no preference → stock byte-identical), implemented in MailboxController via the existing `cardChoiceViaSeat("EXILE PAYMENT …")`. Interim zero-Java-risk step: append the stock pick to the `[FREE]` label so the price is at least visible.

**4. The discard/mulligan fixes stop one method short: cleanup discard and London bottoming are still worst-card heuristics.**
1. **Surface**: `PlayerControllerAi.chooseCardsToDiscardToMaximumHandSize` (`PlayerControllerAi.java:879` → `brains.getCardsToDiscard(numDiscard, null, null)`) and `PlayerControllerAi.tuckCardsViaMulligan` (:777, "TODO … suboptimal" worst-land/max-CMC loop). Neither appears in MailboxController's 26 overrides; the fixed `chooseCardsToDiscardFrom` never sees the cleanup path.
2. **Mechanism**: silent stock decision on cards fully visible to the owner (hidden-info-safe to mailbox). The MULLIGAN request even ships `cardsToReturn`, so the brain judges keeps knowing N cards will be bottomed — then stock picks *which* N against the very plan that justified the keep.
3. **Predicted live symptom**: Purphoros wheels (Wheel of Fortune / Reforge the Soul) or any The One Ring seat (four of the five decks) ends a turn at 9+ cards and cleanup bins Jeska's Will / the held fog by CMC heuristic with **zero mailbox records** between end step and next upkeep; every mull-to-6 bottoms a stock-chosen card (max-CMC rule bottoms exactly the Craterhoof/Genesis Wave class the keep was built around).
4. **Ten-minute probe**: grep game.jsonl for a seat whose recorded `handSize` exceeds 7 across a turn boundary and confirm no CHOOSE_CARDS window in that span; harness: 9-card hand → `PhaseHandler.mainLoopStep` through cleanup → assert no `req-*.json` was written (proves the silent path).
5. **Fix shape**: two overrides reusing shipped wire shapes: `chooseCardsToDiscardToMaximumHandSize` → the existing `cardChoiceViaSeat("DISCARD to hand size", hand, n, n)`; `tuckCardsViaMulligan` → `CHOOSE_CARDS` with `destination:"LIBRARY_BOTTOM"`. Both fall to super on timeout/off-shape, per contract.

**5. The Mother-of-Runes line is broken at both ends: the autopass allowlist ignores threatened targets, and the protection color is stock's guess.**
1. **Surface**: (a) `DEFAULT_AUTOPASS = ("Giver of Runes", "Mother of Runes", "Academy Ruins")` + `SeatRunner._fastpath` in `runner/seatd/runner.py` (also the default in `runner/seat_runner.py:64`) — passes instantly whenever *all* non-pass options start with an allowlist name, with **no stack inspection at all**; (b) un-overridden `PlayerControllerAi.chooseProtectionType` (:1168) — inspects only the first foreign stack item (then `break`s), else falls back to "most prominent color of opponents' creatures".
2. **Mechanism**: note 12's durable-fix language was "suppress protect with **no valid or threatened target**"; the shipped fastpath dropped the threatened-target clause, so the one REACT where Mother is the *right* play — opponent removal on the stack aiming at the seat's creature — is answered `{"chosenId":0}` at ~0ms when Mother is the only affordable option. This also contradicts note 24's "opponent-spell stops are never auto-passed by any layer". And when the window *does* reach the brain and it taps Mother, the color choice on resolution is stock: vs Anguished Unmaking or a Swords with a green-heavy board, `ProtectAi.toProtectFrom`'s fallback picks the wrong color and the save whiffs anyway.
3. **Predicted live symptom**: in `--human` games, Giada or Serra Ascendant dies to targeted removal while Mother/Giver sits untapped — seat log shows `source:"autopass", why:"all options on the no-op allowlist"` at the exact seq the removal was on the stack; or the ability resolves granting protection from the wrong color.
4. **Ten-minute probe**: 5-line pytest — REACT req whose only non-pass option is `"Mother of Runes  {T} …"` and whose `state.stackTargets` names an own battlefield card; assert `_fastpath` returns `("autopass")` (it does today). For (b): grep gui.out for protection color granted vs the removal's color in any archived Giada game.
5. **Fix shape**: (a) runner-only — in `_fastpath`, skip the autopass when any `state.stackTargets` entry matches an own-battlefield id/name or "seat N"==self (data already serialized since note 51); route those to the model at effort low. (b) override `chooseProtectionType` in MailboxController as a bounded CHOOSE_CARD-style list of the ≤6 choices with the stack in state; super on fallback.

**Honorable mentions**
- `MailboxController.playChosenSpellAbility` announces only mana-X (`needsManaX` = `Count$xPaid`/empty): non-X `Announce$` vars (Multikicker) never fire on the AI cast path — a mailbox-cast Everflowing Chalice (Urza) enters with 0 counters, 15b's exact sibling; probe = zero CHOOSE_NUMBER wakes on a Chalice cast.
- `buildState` ships opponents' stack/battlefield cards as names+keywords with no oracle text — every REACT counter/removal valuation of a 2025-26 card runs on model recall (the documented hallucination trigger); serialize ≤300-char oracle for stack items first.
- The top-of-library class is both stock and information-losing: `arrangeForScry`/`arrangeForSurveil`/`orderMoveToZoneList`/`willPutCardOnTop` un-overridden and the peeked cards never serialized — Sensei's Top, Scroll Rack, Sylvan Library, Land Tax (Urza/Giada/Selvala) play blind at stock quality.
- `TapCostPreference` is only armed by symmetry-break picks (`pendingTapPreference`), so Urza's routine "Tap an untapped artifact you control: add {U}" payments are stock-chosen and can tap the Isochron Scepter / Grim Monolith the declared line needs next.
- `chooseSingleEntityForEffect`/`chooseEntitiesForEffect` bail to stock whenever any option is a non-Card (`allCards` gate) — "creature or player"/choose-a-player effects (Y'shtola lifedrain aiming, CopySpell's Zevlor branch) are silently stock even when that choice is the whole decision.


## §2 Gemini report (verbatim)

**1. Cleanup Step Discard (Maximum Hand Size)**
1. **Surface**: `forge-game/.../player/PlayerController.java` — `chooseCardsToDiscardToMaximumHandSize`.
2. **Mechanism**: Not overridden in `MailboxController`. Falls to `PlayerControllerAi`, which delegates to `brains.getCardsToDiscard()` heuristics.
3. **Predicted live symptom**: Y'shtola pays 15 life into `Necropotence` (or Urza casts `Recurring Insight`), ending the turn with a massive hand. Moving to the cleanup step, the engine requires discarding down to 7. Stock AI intercepts this and discards 8 cards using its "worst card" heuristic, binning combo pieces (like Thassa's Oracle or Dramatic Reversal) while keeping lands. The LLM's sculpted hand is destroyed.
4. **Ten-minute probe**: Give Y'shtola 15 cards in hand and pass the turn to the cleanup step. Observe the discard happening instantly without a `CHOOSE_CARDS` window, and check the graveyard for binned combo pieces.
5. **Fix shape**: Override `chooseCardsToDiscardToMaximumHandSize` in `MailboxController`. Send a `CHOOSE_CARDS` request to the brain with `min` and `max` equal to `hand.size() - maxHandSize`, reusing the existing discard wire shape.

**2. Top-of-Library Manipulation (Top / Sylvan Library / Scroll Rack)**
1. **Surface**: `forge-game/.../player/PlayerController.java` — `orderMoveToZoneList`.
2. **Mechanism**: Not overridden in `MailboxController`. When cards are moved to the library (e.g., rearranging the top), stock AI takes over and uses a hardcoded heuristic (putting lands on top if land-starved, else randomizing).
3. **Predicted live symptom**: Urza activates `Sensei's Divining Top` (or Selvala triggers `Sylvan Library`, Giada uses `Scroll Rack`). The LLM pilot never sees the cards. Stock AI instantly reorders them, effectively turning premium card selection engines into random shuffles.
4. **Ten-minute probe**: Launch Urza, cast and activate `Sensei's Divining Top`. Observe that no mailbox window opens and the top 3 cards are reordered instantly.
5. **Fix shape**: Override `orderMoveToZoneList` in `MailboxController`. Send a `CHOOSE_CARDS` (or new `ORDER_CARDS`) request presenting the cards to the brain, requiring it to return the array of IDs in the desired top-to-bottom order.

**3. Return and Exile Cost Payments**
1. **Surface**: `forge-ai/.../AiCostDecision.java` — `visit(CostReturn)` and `visit(CostExile)`.
2. **Mechanism**: The seam hooks Tap and Sacrifice costs via interfaces (`TapCostPreference`, `SacCostPreference`), but leaves Return and Exile costs to stock AI heuristics.
3. **Predicted live symptom**: Selvala activates `Temur Sabertooth` to bounce `Wirewood Symbiote` for an untap loop. Stock AI intercepts the `CostReturn` payment and bounces a random Elf token instead, breaking the loop. Similarly, Y'shtola casts `Force of Will` and stock AI exiles a combo piece instead of a redundant cantrip.
4. **Ten-minute probe**: Give Selvala `Temur Sabertooth` and multiple other creatures. Activate Sabertooth. Observe that the bounced creature is chosen instantly by stock AI, not the LLM.
5. **Fix shape**: Create `ReturnCostPreference` and `ExileCostPreference` interfaces (mirroring `SacCostPreference`). Implement them in `MailboxController` to open a `CHOOSE_ENTITIES` window for the payment.

**4. Optional Costs (Buyback / Kicker / Cleave)**
1. **Surface**: `forge-game/.../player/PlayerController.java` — `chooseOptionalCosts`.
2. **Mechanism**: Not overridden in `MailboxController`. Falls to `PlayerControllerAi.chooseOptionalCosts`, which delegates to AI heuristics.
3. **Predicted live symptom**: Purphoros casts `Reiterate` with infinite mana available, intending to pay the Buyback cost to loop it. The engine asks stock AI if it wants to pay optional costs. Stock AI evaluates it heuristically and declines Buyback. The spell goes to the graveyard, breaking the infinite loop.
4. **Ten-minute probe**: Give Purphoros `Reiterate` and 10 mana. Instruct the brain to cast it with Buyback. Observe that it casts without Buyback and goes to the graveyard.
5. **Fix shape**: Override `chooseOptionalCosts` in `MailboxController`. For each available optional cost, send a `CONFIRM` request (e.g., "Pay Buyback {3}?") and return the list of confirmed costs.

**5. Generic Number Choices (Wheel of Misfortune)**
1. **Surface**: `forge-game/.../player/PlayerController.java` — `chooseNumber` (both overloads).
2. **Mechanism**: Not overridden in `MailboxController`. Falls to `PlayerControllerAi.chooseNumber`, which uses hardcoded heuristics (the seam only hooked `chooseNumberForCostReduction` and `announceRequirements` for X-spells).
3. **Predicted live symptom**: Purphoros casts `Wheel of Misfortune`. The LLM pilot never gets a prompt to choose a number. Stock AI secretly chooses a number (often 0 or a random low number), causing Purphoros to lose the mini-game, take damage, and fail to draw 7 cards, completely wasting the spell.
4. **Ten-minute probe**: Launch a game with Purphoros. Cast `Wheel of Misfortune`. Observe that the number is chosen instantly without a `CHOOSE_NUMBER` mailbox request.
5. **Fix shape**: Override `chooseNumber` in `MailboxController`. Route it to the existing `CHOOSE_NUMBER` mailbox protocol, passing the prompt text and bounds.

**Honorable Mentions**
- **`PlayerController.chooseSingleReplacementEffect`**: Ordering multiple replacement effects (e.g., damage doublers vs. preventers) falls to stock AI, violating CR 616.1 player agency.
- **`PlayerController.arrangeForScry` / `arrangeForSurveil`**: Scry and Surveil decisions fall to stock AI heuristics, bypassing the pilot's card selection.
- **`AiCostDecision.visit(CostRemoveAnyCounter)`**: Removing counters as a cost (e.g., `Scholar of New Horizons` in Giada) falls to stock AI, which might remove a +1/+1 counter from the wrong creature.
- **`PlayerController.chooseCardsPile`**: `Fact or Fiction` / `Atris` pile splits are decided by stock AI, not the pilot.
- **`PlayerController.vote`**: Council's dilemma and voting mechanics fall to stock AI, bypassing table politics.
## §3 The brief both auditors received

# SEAM AUDIT BRIEF — find the next five breakages

## Mission
You are auditing an LLM-pilot layer bolted onto the Forge MTG rules engine
(4-player Commander). Your job: propose seams we have MISSED, or places where
our interface with Forge causes errors, misplays, or loss of critical
information — then rank THE FIVE most likely areas where we are currently
breaking. Not style review; find where a real game goes wrong.

## Object model (compact)
- Forge core: `Game` / `Player` / abstract `PlayerController` (~150 decision
  methods — THE full decision surface). Stock AI = `PlayerControllerAi`
  delegating to `AiController` heuristics ("brains").
- Our seam: `MailboxController extends PlayerControllerAi`, overrides ~28
  decision methods. Each override serializes a decision request (JSON: prompt,
  bounded options, public state + own hand) to a file mailbox; a Python seat
  daemon (`runner.py`/`rules.py`) forwards it to a resident LLM session and
  writes the answer back. FAIL-SAFE CONTRACT: invalid answer / timeout →
  `super` (stock AI decides); we must never be worse than stock.
- Anything NOT overridden falls to stock heuristics SILENTLY — that is the
  seam-gap class that keeps biting us.
- Cost payment is a parallel surface: `AiCostDecision.visit(Cost*)` picks
  HOW costs are paid (which card tapped/sacrificed/discarded/exiled...). We
  hook it via controller-interface checks (TapCostPreference,
  SacCostPreference). Every other CostPart type still pays via stock pick.
- State serialization (buildState): battlefield/stack/GY public info + own
  hand; effective keywords per card; stack now carries owners/kinds/targets.
  Anything the serializer OMITS, the pilot cannot know — omission = the
  second seam-gap class (the engine knows it, the brain doesn't).
- GUI game: `GuiPilotMatch` (human seat 0 + 3 mailbox seats), ObserverSnapshot
  publishes public state; seat-0 Advisor is a read-only shadow.

## Seam fixes to date (do not re-propose; DO inspect for incompleteness)
Targeting (chooseTargetsFor single-target incl. stack items; trigger aiming +
explicit decline; stackTargets announcement), modal modes, tutors/fetch,
discard, X + cost-reduction numbers, PAY_UNLESS taxes, CONFIRM (TRIGGER,
PLAY_FROM_EFFECT may-cast offers), sacrifice (both effect path
choosePermanentsToSacrifice/Destroy and cost path SacCostPreference),
symmetry-break tap payment, failed-payment rollback fixes (spell rollback to
origin zone; activated refund-in-place), condition-forked mana scripts
(ComputerUtilMana chain walk), attack/block declaration, mulligans,
choose-entity/entities/cards/card, number, cards-for-effect, zone-change
lists. Deliberately stock (rationale exists): multi-target spells (max>1),
trigger ORDERING, combat damage assignment/order, mana auto-tap source pick
(except the two hooks), whole-DB card naming.

## Where to look (read these)
1. `forge-game/.../player/PlayerController.java` — enumerate decision methods;
   which user-facing ones do we NOT override? (loss-of-agency class)
2. `forge-arena/.../interactive/MailboxController.java` — the seam itself:
   look for narrow assumptions (single-target-only gates, min/max handling,
   silent supers on odd shapes, serializer omissions).
3. `forge-ai/.../PlayerControllerAi.java` — what stock does on surfaces we
   never touched (the silent-decliner class: doTrigger/canPlayFromEffect-style
   combined decisions that veto lines the pilot chose).
4. `forge-ai/.../AiCostDecision.java` — every visit() we have NOT hooked:
   which cost picks can strand a pilot's line (discard-as-cost, exile-as-cost,
   return-to-hand, tap-creatures, remove counters, pay life...)?
5. `runner/seatd/rules.py` + `runner.py` — validator/safe-default/fastpath
   layers: where can a legal-but-unusual answer be rejected or a window
   wrongly memoized/collapsed?

## Rules + decks context (attached)
MTG rules digests (CR-cited) and the five decklists actually at our tables
(Selvala pilot + Purphoros, Giada, Urza, Y'shtola seats). Use them to ground
your five picks in plays these decks actually make (e.g. Urza: Scepter loops,
Power Artifact, Winter Orb; Purphoros: token storms; Giada: angels/lifegain;
Y'shtola: Esper control, edicts, lifedrain; Selvala: big-mana elf combat).

## Deliverable — EXACTLY this shape
Five findings, ranked by likelihood x impact. For each:
1. **Surface**: the exact method/interface point (file + method).
2. **Mechanism**: how it breaks (silent stock decision? serializer omission?
   validator rejection? rules edge?).
3. **Predicted live symptom**: what a game observer would see.
4. **Ten-minute probe**: how to confirm it is real (test shape or log grep).
5. **Fix shape**: minimal-footprint remedy consistent with our fail-safe
   contract and "minimize parent-project edits" policy.
Then a short "honorable mentions" list (max 5 one-liners). No preamble.

## §4 Wave-2 outcome (2026-08-28, same day)

All ten findings fixed in one rationalized change-set (field note 52):
one new hook interface (PaymentPickPreference) + three shared wire
mechanisms; two deferrals with rationale (replacement-effect ordering,
routine tap picks). Pre-finalize review: the full diffs went back to
Gemini side-by-side — 1 BLOCKER refuted by code inspection
(clearTargets() reassigns targetChosen; save/restore sound), 1 real FIX
applied (chooseCardsPile hid-pile visibility leak), 4 risk spots
confirmed, verdict SHIP. Gates: 338 Java + checkstyle, 120 Python.

### Reviewer output (verbatim)
```
Here is the review of the Wave-2 seam audit fixes, evaluated against the fail-safe contract, MTG rules, and Forge API constraints.

**1. [BLOCKER] `MailboxController.chooseNewTargetsFor` — Forge API Mutation Hole**
*Reason:* In Forge, `SpellAbility.clearTargets()` does not reassign the internal `TargetChoices` object; it calls `.clearTargets()` *on* it, emptying its internal lists. Because `old = sa.getTargets()` just holds a reference to that exact same object, calling `sa.clearTargets()` empties `old` as well. When the seat declines or fails the retarget, the restore path `sa.setTargets(old)` sets the spell's targets to the now-empty object, permanently breaking the spell on the stack and violating the fail-safe contract.
*Suggested Change:* Back up the actual target entities into a new list, and restore them by re-adding them to the cleared `TargetChoices` object.
```java
    TargetChoices old = sa.getTargets();
    if (old == null || old.size() != 1 || sa.isDividedAsYouChoose()) {
        return super.chooseNewTargetsFor(ability, filter, optional);
    }
    // Deep copy the actual target entities
    List<forge.game.GameObject> oldTargets = new java.util.ArrayList<>(old.getTargets());
    sa.clearTargets();
    if (chooseTargetsFor(sa)) {
        forge.game.spellability.TargetChoices next = sa.getTargets();
        boolean legal = next != null && next.size() == 1;
        if (legal && filter != null) {
            for (forge.game.GameObject t : next) {
                legal &= filter.test(t);
            }
        }
        if (legal) {
            return next;
        }
    }
    // Restore path
    sa.clearTargets();
    for (forge.game.GameObject t : oldTargets) {
        sa.getTargets().add(t);
    }
    return null;
```

**2. [OK-NOTE] `MailboxController.arrangeForScry` / `arrangeFor
--- continuation ---
2. [FIX] `MailboxController.java` / `chooseCardsPile`
The visibility logic `!"False".equals(faceUp)` and `"True".equals(faceUp)` mishandles asymmetric splits (e.g., Fortune's Favor, where `faceUp` is `"Pile1"` or `"Pile2"`). If `faceUp` is `"Pile2"`, Pile 1 incorrectly evaluates as visible to the LLM and Pile 2 as hidden. Change Pile 1 visibility to `"True".equals(faceUp) || "Pile1".equals(faceUp)` and Pile 2 to `"True".equals(faceUp) || "Pile2".equals(faceUp)`.

3. [OK-NOTE] `MailboxController.java` / `orderMoveToZoneList` & `arrangeForScry`
Risk spots [a] and [h] are correctly implemented. Forge's library insertion expects index 0 to be the top, matching the `FIRST=top` prompt convention, and iterating over `topN` to populate `toTop` inherently preserves the original relative order of kept cards. No change required.

4. [OK-NOTE] `MailboxController.java` / `announceRequirements` & `chooseOptionalCosts`
Risk spots [c] and [g] are safe. The `announceRequirements` branch correctly falls through to stock for unbounded ranges (`max - min > 1000`), and always opening a window for optional costs with a `min=0` bound correctly allows the LLM to decline all costs by returning an empty array. No change required.

5. [OK-NOTE] `runner.py` / `_runner` & `_threatens_own`
Risk spots [d] and [e] are robust. `json.dumps(..., sort_keys=True)` is deterministic and cheap for the memo signature, and the threat clause correctly identifies both direct seat targeting and permanent targeting via the `(id)` suffix in `stackTargets`. No change required.

6. [OK-NOTE] `AiCostDecision.java` & `MailboxController.java` / Entity IDs & CostDiscard
Risk spot [f] correctly uses `validD.removeAll(discarded)` to prevent duplicate payments. Furthermore, falling back to sequential IDs (`seq++`) when `opts` contains a mix of Cards and Players is a brilliant, collision-free way to round-trip mixed entities. No change required.

SHIP```
