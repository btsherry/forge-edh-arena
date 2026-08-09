# Spec — Executable turn plans (speculative execution + four-part guard)

**Status: design spec (not yet built).** Reduces model round-trips on
uncontested own-turn CAST chains by executing a brain-authored plan locally,
guarded so that any divergence from the planning assumptions — especially an
opponent's instant-speed action — forces a live model call. Correctness is
never traded for round-trips; savings are only harvested where fidelity doesn't
need the call.

Builds on the existing seatd loop (`runner.py` `SeatRunner.handle`), the
per-turn `turn_plan` cache (today advisory text), `rules.validate/safe_default`,
and the mailbox contract (one decision per `req-<n>.json`; after a cast the seat
retains priority and gets the *next* CAST_SPELL req, so a 6-spell turn is 6
sequential reqs).

## Scope (v1)

- **In:** own-turn **CAST_SPELL** main-phase steps only (the 6–9-cast durdle
  chains — the biggest, safest win).
- **Out (always model):** DECLARE_ATTACKERS / DECLARE_BLOCKERS (depend on live
  attackers/tricks), all CHOOSE_* sub-choices (depend on info revealed at
  resolution — fetch targets, modes), MULLIGAN, REACT. These never come from a
  plan in v1.
- Plans are created at the seat's own turn, first MAIN1 empty-stack decision
  (same trigger as today's `turn_plan`), and **expire at turn change / game
  reset.**

## Plan representation

The brain, on its first own-turn main window, may return a `plan` array in its
answer (alongside the normal first-step answer + `why`):

```json
"plan": [
  {"card": "Sol Ring",              "why": "ramp first"},
  {"card": "Selvala, Heart of the Wilds", "why": "commander online"},
  {"card": "Umbral Mantle",         "why": "combo enabler"}
]
```

**Steps reference the action by card NAME/label, never by option id.** Option
ids are assigned per-req (1..N in *that* decision) and are not stable across the
sequential reqs a turn produces. At execution the runner re-resolves the named
card to the *current* req's option id. This also makes guard #3 fall out for
free (name absent from current options ⇒ escalate).

`bind_plan_step(step, req)` → returns the current option id whose label matches
`step.card` (prefix/normalized match on the card name), or `None`.

## The loop (runner.handle, v1 additions)

Plan state on the seat: `self.plan = {turn, steps:[...], idx, dirty:false}` or None.

Per incoming req `R`, in order:
1. **Housekeeping (existing):** game_reset ⇒ wipe plan; turn change ⇒ wipe plan
   (and reset the react-fired flag).
2. **Interaction flag (guard #4 source):** if `R.decisionType == "REACT"` during
   this seat's own turn, set `plan.dirty = true` *before* handling — an opponent
   put something on the stack during our turn, so the rest of any plan is
   strategically stale. (Optional enhancement: also set dirty on an
   observer-snapshot opponent board/life/stack delta not caused by our own step.)
3. **Fastpaths (existing):** react_autopass / memo — unchanged, run first.
4. **Plan consumption:** if a plan is active with steps remaining, evaluate the
   FOUR-PART GUARD against `R` for the next step `S`:
   - **(1) TYPE:** `R.decisionType == S` type (both CAST_SPELL in v1).
   - **(2) TIMING/STACK:** `R.state.stack` is empty **and** `R.phase ∈ {MAIN1,
     MAIN2}` — a genuine sorcery-speed window matching the plan's assumption. Any
     stack object ⇒ something happened ⇒ fail.
   - **(3) OPTION PRESENCE:** `bind_plan_step(S, R)` resolves to a present option
     id. Absent ⇒ the intended play was countered / sacrificed / no longer
     payable ⇒ fail. (The engine's CAST option list already reflects castability,
     so presence ≈ affordability, same parity as a live decision.)
   - **(4) NO INTERVENING INTERACTION:** `plan.dirty == false`.
   - **All four pass** ⇒ build the answer `{"chosenId": bound_id}`, run it
     through `rules.validate(R, answer)` (belt-and-suspenders), `respond()`,
     advance `idx`, log `source="plan"` with `S.why`. **No model call.**
   - **Any fail** ⇒ **discard the entire plan** (not just skip the step — once
     reality diverged the remainder is suspect) and fall through to §5.
5. **Model path (existing):** build prompt (with any surviving advisory context),
   `brain.decide`, `validate`, `safe_default` on failure, `respond`. If this is
   the first own-turn main window and the answer carries a fresh `plan`, install
   it.

### Turn end / plan exhaustion
When the plan's steps are exhausted, the **next** CAST/main req goes to the model
(one confirming call — the brain either passes to combat or finds a new play
given what resolved). So a 6-cast turn ≈ **1 planning call + 4 local + 1
confirming = 2 model calls instead of 7.** (A future opt: a terminal
`{"pass": true}` plan step to save the confirming call — deferred as riskier.)

## Why an opponent's instant-speed react can't be mishandled

When an opponent responds at instant speed, priority returns to our seat as a
**new REACT req with a non-empty stack** — interposed *before* the plan's next
main-phase step. That req:
- sets `plan.dirty` (step 2 above, guard #4), **and**
- fails guard #1 (REACT≠CAST_SPELL) **and** guard #2 (stack non-empty) if it
  were ever tested as a plan step.

So the opponent's action is surfaced to the brain as its own decision (the REACT
goes through fastpath-or-model like any react), and the plan is invalidated for
everything after it. The agent is *always asked*; the plan simply steps aside.
The residual "continues a legal-but-stale plan after a resolved interaction that
didn't block a remaining step" case is closed by guard #4 discarding the whole
plan on any REACT-fired-this-turn signal, forcing a re-plan on the next window.

## Self-regulating property

Guard #4 means plans only run through **uncontested** stretches. Quiet durdle
turns (where savings are safe and plentiful) harvest nearly all their round
trips; interactive turns (where fidelity matters most) collapse back to full
per-decision model calls automatically. Savings land where safe and evaporate
where they don't — by construction, not by tuning.

## Double correctness guard

Two independent gates protect every submitted action:
1. the four-part guard decides **whether** to use the plan at all, and
2. `rules.validate(R, answer)` confirms the bound answer is **legal for the
   actual req** before `respond()` writes it.
A malformed/stale/illegal plan step can therefore never be played — worst case
it's discarded and the req goes to the model (no worse than today).

## Telemetry (make the win measurable)

- New `source="plan"` in the per-decision + game.jsonl records (distinct from
  model / autopass / memo / punt) → `status.py` reports **plan-hit rate**.
- Log the **invalidation reason** (type / stack / option / interaction) per
  discard → a histogram to tune what's tripping plans.
- Carry `S.why` onto plan-sourced records so the narration/teacher-log keeps a
  per-action rationale even with no model call — no fidelity loss in the archive.

## Config & rollout

- `--speculative` flag on `seat_runner.py` (default **off** initially) so we A/B
  round-trip counts on identical fixtures and live games.
- **Tests** (`tests/test_plan.py`): plan of 3 CAST steps + 3 matching reqs ⇒ 3
  `plan`-source answers, 0 model calls; REACT interposed mid-sequence ⇒ plan
  invalidated + escalation; named card absent from options ⇒ escalate; non-empty
  stack on a CAST req ⇒ escalate; every plan-sourced answer passes
  `rules.validate`.
- **Acceptance metrics:** round-trips/turn down materially on uncontested turns;
  **zero** increase in punts or illegal answers; plan-hit rate + invalidation
  histogram sane over a full soak game.

## Failure modes (all degrade to "just call the model")

Malformed plan → ignored. Card never appears → guard #3. Opponent interaction →
guards #2/#4. Board wipe / own trigger changes options → guard #3. Engine
restart mid-turn → game_reset wipes plan. Planning-call timeout → safe_default
pass, no plan (today's behavior). In every case the fallback is the current
per-decision path — the feature can only *save* round trips, never *cost*
correctness.

## Companion (separate spec): reactive hold-posture (#2)

The same escalate-on-change principle applied to the REACT storms: the brain
attaches a conservative hold-predicate ("pass all my reacts this turn unless an
opponent casts a noncreature spell MV≥4 or a wincon"); the runner evaluates it
locally and escalates when it trips. Targets the larger raw REACT volume; specced
separately. #1 (this doc) covers the CAST chains.
