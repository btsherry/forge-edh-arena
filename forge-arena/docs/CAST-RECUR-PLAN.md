# cast_recur runner — research + plan (Purphoros anchor) 2026-07-30

Research: full Purphoros reingest (deck + all 6 combos verbatim) + card scripts,
analyzed independently by Gemini 3.1 Pro and an Opus subagent (both advisory;
neither wrote code). They agree on every material point. Ben walked the Ignus
line by hand; the scripts confirm it to the pip.

## The headline: "cast_recur" is four sub-shapes, not one — and a NEW outlet

Purphoros's payoff is **on-board ETB damage**: `Creature.Other+YouCtrl enters →
2 to each opponent` (script-verified; the devotion clause gates only whether
Purphoros is *also* a creature, never the damage trigger). This is the
project's **first non-Aetherflux outlet** — the loop product (a creature
entering) is *directly lethal and directly measured* by opponent-life delta,
the cleanest verification signal we have. It also reuses machinery we already
built: per-ETB damage is amplified by Ojer Axonil / Torbran / Solphim /
Twinflame Tyrant, which is exactly the old PayoffRules DAMAGE_AMPLIFIER
`amplified()` (multipliers-first) code.

| combo | pop | sub-shape | per-iter mana | outlet | true loop |
|---|--:|---|---|---|---|
| 147-1235 Dualcaster + Twinflame | 71k | copy-loop | 0 (free copies) | Purphoros ETB (direct) | yes |
| 147-6785 Dualcaster + Onslaught | 5k | copy-loop | 0 | Purphoros ETB (direct) | yes |
| 411-3101 Grinning Ignus + Steam-Kin | 5k | self-recast | 0 net / 3-cast cycle | Purphoros ETB (direct) | yes |
| 1878-3368 Jeska's Will + Reiterate | 33k | ritual-buyback | net ≥+1 red | mana → SEPARATE sink | yes |
| 2091-3368 Mana Geyser + Reiterate | 28k | ritual-buyback | net ≥+1 red | mana → SEPARATE sink | yes |
| 1110-6785 Onslaught + Terror | 5k | one-shot-burst | 11 once | Terror + Purphoros | no (bounded 25) |

## The Ignus loop (411-3101), verified — Ben's walkthrough, script-checked

Grinning Ignus: `{R}, Return to hand: Add {C}{C}{R}` (sorcery speed).
Steam-Kin: red-spell cast → +1 counter if ≤2; `Remove 3 counters: Add {R}{R}{R}`.

Per 3-cast cycle (both researchers, same arithmetic):
- 3× cast Ignus {2}{R} = −9 mana, −3 red
- 3× Ignus return ability = +9 mana (+{C}{C}{R} each), +3 red
- 3× activation {R} = −3 mana, −3 red
- 1× Steam-Kin {R}{R}{R} = +3 mana, +3 red
- **Net = 0 total, 0 red.** Exactly break-even in mana AND color. Only need is
  a startup buffer (≤3 red) until Steam-Kin first fires. Then infinite.

Each Ignus cast = a creature ETB = Purphoros 2 to each opponent (× amplifiers).
No priority-hold, no separate sink — the recast IS the sink. Cleanest of the six.

## Runner architecture: ONE skeleton, THREE bodies (+ one degenerate case)

Skeleton: `cast enabler → produce a countable product → MEASURE it → check
engine-win / governor cap → stop`. Governor N = ceil(max opponent life ÷
amplified per-ETB damage), read live from the board. Self-consumption: none
(no library drain in any of these). But the bodies do not reduce to each other:

- **Body A — copy-loop** (147-1235, 147-6785): cast enabler; HOLD PRIORITY;
  flash Dualcaster targeting the enabler spell; on each Dualcaster ETB answer
  two prompts (copy the enabler; retarget the copy to the newest Dualcaster).
  Hardest engine seam (priority-hold + per-ETB targeting the stock AI won't do).
  Terminates trivially — governor just stops choosing to copy. The two combos
  differ only in which spell is copied + token cleanup (exile vs sac).
- **Body B — ritual-buyback** (1878-3368, 2091-3368): cast ritual; hold
  priority; Reiterate WITH BUYBACK targeting the ritual; bank mana; recast
  Reiterate each cycle; maintain a MANA LEDGER; then a mandatory SINK HANDOFF
  (Song of Totentanz X / Onslaught X / Ignus recasts) to turn mana into ETBs.
  Most machinery, and the win depends on a SECOND card (the sink). Mana alone
  never registers a win — Purphoros ignores mana.
- **Body C — self-recast** (411-3101): full-resolve recast (no priority-hold);
  activate the return ability each cast; track Steam-Kin counters, fire on
  exactly the 3rd cast; red-vs-generic color ledger. Standalone; shares nothing
  with A or B. But the DIRECT outlet + life-delta measure make it the cleanest.
- **Degenerate — one-shot** (1110-6785): Body A skeleton with governor cap = 1.
  Cast Onslaught X=5 → fixed 25-trigger fan-out; assign all 25 Terror triggers
  to opponent faces. Not a loop.

Measured observable per body: A → Δopp_life = −2×N_amplified AND tokens+1;
B → floating red pool rises (yield−6)/cycle, then the SINK's life delta;
C → Purphoros hit per cast AND Steam-Kin counter cycling 0→1→2→3; one-shot →
single large life delta.

## Recommended build order (staged, proven-discipline: anchor cleanest, clone)

1. **ANCHOR: Body C — Grinning Ignus + Steam-Kin (411-3101).** Cleanest
   verification (life delta), DIRECT outlet (no sink), NO priority-hold, reuses
   the amplifier machinery, Ben-vouched. Proves the shape + the new
   on-board-ETB-damage outlet class in one program.
2. **Body A — Dualcaster copy-loop (147-1235 first — the deck's 71k headline —
   then 147-6785).** Same outlet + same life-delta measure, adds the
   priority-hold + per-ETB target-choice seam. Highest-pop combo in the deck.
3. **One-shot (1110-6785)** — cheap add on Body A's skeleton (cap=1) + Terror
   target assignment. Or flag.
4. **DEFER: Body B — Reiterate ritual-buyback (1878-3368, 2091-3368).** Most
   machinery (mana ledger + two-phase sink handoff), win depends on a second
   combo, and Purphoros already wins 25%+ organically — coverage, not urgency.

## Open decisions for Ben (the check-in)

- Anchor on **Ignus (cleanest)** vs the higher-pop **Dualcaster**? (Recommend
  Ignus — proves outlet + shape with the least new engine surface.)
- Reiterate ritual-buyback **in scope now or deferred**? (Recommend deferred —
  it's a two-phase mana→sink machine, genuinely more than the others.)
- One-shot Onslaught+Terror: **build (cheap) or flag**? (Lean build — it's
  Body A cap=1 plus damage-assignment, and it's a real kill.)
