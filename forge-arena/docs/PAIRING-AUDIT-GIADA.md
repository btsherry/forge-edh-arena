# Giada pairing audit — card-text reconfirmation (2026-07-23)

Two fully independent audits of all 36 `paired-plays.json` entries against
the actual card scripts/oracle text: one by Claude (Fable, in-session), one
by Gemini 3.1 Pro (API, self-contained package: pairs + oracle texts + CR
mechanism rules; advisory only per standing policy). **Verdicts agreed
36/36.** Both audits also independently proposed the same missed pairing
class and rejected the same non-candidates.

## Verdicts

**32 VALID / 4 INVALID.** The four invalid pairs are all Farewell +
indestructible-class protection:

| Pair | Verdict | Why |
|---|---|---|
| Farewell + Grand Crescendo | INVALID | exile ignores indestructible |
| Farewell + Flawless Maneuver | INVALID | exile ignores indestructible |
| Farewell + Akroma's Will | INVALID | exile ignores indestructible; protection-from-color never applies (exile-all doesn't target) |
| Farewell + Flare of Fortitude | INVALID | exile ignores indestructible; hexproof irrelevant (untargeted) |
| Farewell + Teferi's Protection / Clever Concealment | VALID | phasing — the permanent isn't there to exile |
| all other 30 pairs | VALID | destroy vs indestructible/phasing with correct coverage |

Coverage exclusions in the artifact were confirmed correct: no creature-only
shield is paired with a land wipe; Clever Concealment (nonland) is never
paired with Armageddon/Ravages.

## Caveats that must reach the compiled programs

1. **Final Showdown mode order (Gemini's catch, rules-verified):** its
   "+{1}: all creatures lose all abilities" mode STRIPS externally granted
   indestructible (later timestamp) before the destroy mode resolves. A
   compiled Final Showdown pairing must never select that mode alongside an
   indestructible shield. Phasing shields are immune to the trap.
2. **Farewell's graveyard mode** is outside any protection's scope —
   irrelevant to board survival, note only.
3. **Catastrophe's "can't be regenerated"** is irrelevant to indestructible
   and phasing — no effect on any verdict.

## Missed pairing class: Avacyn, Angel of Hope (both audits, independently)

"Other permanents you control have indestructible" — persistent, all
permanents, LANDS INCLUDED. With Avacyn resolved, every destroy-wipe in the
deck is one-sided with **no instant required**: Armageddon, Ravages of War,
Catastrophe (either mode), Doomskar, Vanquish the Horde, Final Showdown,
Hour of Revelation, Ondu Inversion — 8 standing pairs. This is a different
runner shape from respond-on-stack: a **standing-protection pairing**
(precondition: Avacyn on battlefield; no shield cast, no deferred measure —
plain stack_empty measurement). Not compiled yet; queued for the sweep.

## Rejected candidates (both audits, same reasons)

- Mother of Runes / Giver of Runes — single-target protection, not board.
- The One Ring — protects the PLAYER, not permanents.

## Implications for the compile sweep

- Compile 32 valid instant pairs (2 already done: Doomskar+Maneuver,
  Armageddon+Teferi's) with the mechanism-validity gate rejecting the 4
  Farewell pairs loudly (flagged, with reasons, in the pairing backlog).
- Phasing shields require `verify.measure_at: next_untap` (runner v2,
  PR-theta); indestructible shields use stack_empty.
- Final Showdown pairs carry a compiled mode constraint.
- Avacyn standing pairs need the standing-protection runner shape first.
