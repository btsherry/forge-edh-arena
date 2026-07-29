# Play observations — where wins were available sooner

Ben's directive (2026-07-29): observe play, note game states where we could
have converted to wins sooner given the board, and improve the turn-by-turn
logic. Tool: `scripts/observe-play.py <run-dir>` — conservative heuristics
over the per-game event streams (turn_state life/board_power tables, combo
timelines with ignore-reason attribution, drill churn, conversion tails).
Rules grounding re-checked against `research/mtg-rules-summary.md` (combat
only on own turns; sorcery-speed entry windows; LIFO stack; priority
retention after casting).

## chi30 baseline (30 games, the pre-PR-psi world)

Aggregate: 17 READY_NEVER_ENTERED, 11 ENTRY_LATENCY, 3 ALPHA_HELD_BACK,
plus one drill-churn case surviving the loop-iteration filter.

### Finding 1 — serial head-kills waste measured overkill (game 17, Urza's win)

The sharpest single miss. Turn 31: Urza, 50 power across 5+ Constructs;
table: Purphoros 27hp/0 creatures, Giada 9hp/1 creature, Selvala 20hp/1
creature. The LETHAL_ALPHA order sent ALL 50 power into the 9-life head —
41 damage of overkill — then killed one head per combat: t31 (9hp), t34
(35 dmg vs 18hp), t36 (37 vs 27). Three combats for a table that arithmetic
could clear in two: a worst-case partition at t31 (9+blocker for head one,
20+blocker for head two, remainder at Purphoros) kills two heads
immediately and wins on t34, two turns earlier. lethal_alpha events confirm
the engine SAW each kill (guaranteed 50 vs 9; 35 vs 18) — the miss is
`scriptAttack`'s deliberate all-at-one-head rule for LETHAL_ALPHA ("the
guarantee was computed all-in, spilling would dilute it").

**Improvement 1 (turn-by-turn logic): multi-head worst-case partition.**
Extend lethalAlphaOrder: after reserving head 1's worst-case-lethal
allocation (life + top-B attacker absorption), test whether the SURPLUS
alone is worst-case lethal for head 2, and so on. Only individually
guaranteed allocations split off — the conservative guarantee semantics
survive intact; pure overkill converts into extra eliminations. In a pod,
two turns earlier is the difference between winning and handing Selvala
the window (upsilon30's exact failure, inverted).

### Finding 2 — entry latency is an AFFORDABILITY-ESTIMATE wait, and it is long

Eleven ready-combos entered 2+ turns late, every one attributed
`mana_reserved` (the PR-19 gate: pool + untapped sources < first-cast
estimate). Worst cases: 513-3682 ready t1 entered t19 (+18); 527-2816
ready t2 entered t14 (+12); 527-2645 ready t1 entered t10 (+9); plus
ready-never-entered siblings held out all game by the same gate. These are
legacy-binding entries (the 513/542 programs replace several as of
PR-psi), but Selvala's Mantle/Staff latencies are the live cost of the
gate today: a {3} artifact whose line waits 8-12 turns is not a mana
problem, it is an estimate problem.

**Improvement 2: instrument, then fix.** The `combo_ignored/mana_reserved`
event should carry the estimate's numbers (needed, pool, untapped) — one
`.with()` each — so the next batch tells us whether the estimate
over-prices (color-blind estimate class, the kappa lesson) or readiness
genuinely precedes mana. Fix follows the measurement, not vice versa.

### Finding 3 — the drill stacks shots blind (CORRECTED)

CORRECTION (same session): the first observer draft reported "178
legacy-drill steps on Grim Monolith" in game 17 — those events carry
`kind: mana_pair` and are the 2585-5149 mana loop's legitimate, verified
iterations (life correctly frozen); the refined filter excludes them and
the Grim-as-drill-outlet claim is WITHDRAWN. The arm-time sim validation
(activateAtOpponent on a copy) has no measured failure.

The REAL, directly observed churn is the PR-chi diagnostic's Aetherflux
sequence: the legacy drill re-activates every priority window while its
own shot is still ON THE STACK — it queued four PayLife<50> shots against
a 40-life opponent (150 life of overkill) and then burned 196 refused
windows reaching its 200 bound before the stacked shots resolved.

**Improvement 3: stack-empty gate on drill re-activation.** One shot in
flight at a time — the drill waits for resolution before paying the next
cost. Opponent interaction landing mid-drill still works (the wait is the
interrupt window the step model already embraces).

### Finding 4 — no_viable_route is the build backlog, correctly named

The remaining READY_NEVER_ENTERED entries are combos with neither binding
nor program (4131-4235, 1110-6785, 2026-2404-2645, 2364-2495-3094 ...) —
expected, already tracked in program-backlog.json, no action beyond the
compile queue.

### Method notes

- ALPHA_HELD_BACK counts global turns while the seat can only attack on
  its own turns (CR 506; ~every 4th turn in a full pod) — read "held 8
  turns" as "2 own combats"; the finding stands because the FIRST own
  combat in the window overkilled a single head.
- Loop iterations (kind=mana_pair/copy_iteration/cast_bounce) are excluded
  from drill churn — their frozen life is by design; only legacy drill
  steps (no kind) count.
- Games ending without a game_end event are the known host-crash class and
  are skipped for conversion-timing claims.

## Improvements shipped (PR-omega, same day)

1. **Multi-head worst-case partition** — lethalAlphaOrder plans every head
   whose allocation is INDIVIDUALLY worst-case lethal; scriptAttack
   executes the exact partition; leftovers pile onto head[0] as
   trick-buffer, so the single-head case is byte-for-byte the old
   behavior. (Finding 1.)
2. **combo_ignored carries the gate's numbers** — mana_reserved events now
   name the cause (refire_lockout vs first_cast_unaffordable) with
   first_cast / estimate / pool / untapped, so the next batch adjudicates
   estimate-vs-reality. Measurement first; the gate itself is untouched.
   (Finding 2.)
3. **Drill stack-empty gate** — one shot in flight at a time; the stacked
   PayLife overkill class is gone by construction. (Finding 3, corrected
   form.)

## pr-omega100 — the first completed 100-game batch (2026-07-29)

100/100 records, 106.5 min wall, one worker JVM death mid-run absorbed by
the new supervisor respawn + resume (without it: short again). Results:
81 wins / 13 crash-records / 6 timeouts. Wins: **Purphoros 40** (25.8%
baseline), **Giada 27** (20.8%), **Selvala 8** (4.2%), **Urza 6** (0
baseline; 9 program entries, 1749 verified iterations, 4 engine wins).
The combat-deck surges (Purphoros +14, Giada +6, Selvala doubled) are the
expected fingerprint of the multi-head lethal partition — combat decks
cash overkill into extra eliminations — though psi-era changes and cap 48
share credit; chi30-paired per-seed comparison can attribute precisely.

Cast_bounce in the wild, the bottleneck MOVED as designed: the template
dispatch fix produced **105 family entries** (513-5034--46: 24, 513-3682:
28, 542-2364: 15, 542-5034: 15, 513-2364--47: 16, 542-2585: 1, plus
legacy-id entries) where chi30 had zero — but ~104 deferred quietly at
SETUP and one game ran 7 measured iterations (542-5034, ended by the game
before its lifegain target). The dominant defer causes are structural:
the Aetherflux outlet (a 1-of) in neither hand nor battlefield — the
deliberate no-durdle gate — and 7-8 mana engines reachable-in-hand but
unaffordable. Next-lever candidates for Ben: tutor weighting toward the
outlet when the family is otherwise assembled, and/or a peel-value close
(run the loop for mana + board removal with a combat finish) per his
dual-trigger strategy note.

Entry-gate telemetry (improvement 2) adjudicates: 109 first_cast_
unaffordable vs 21 refire_lockout. Top offenders are Selvala's Mantle/
Staff lines (71 ignores at estimate 3 — a seat showing <3 untapped
sources for dozens of turns points at the VIEW's untapped-source count,
not the estimate) and 35/109 were within 1 mana of the bar. The estimate
itself looks roughly honest; the source COUNT is the suspect. Follow-up:
audit SeatView.untappedManaSources against boards with dorks/tapped-rock
mixes before touching the gate.

Observer method note for next pass: ENTRY_LATENCY of +4 global turns in a
4-player pod is one own-turn — i.e. optimal — so the metric needs
own-turn normalization before the next reading; chi30's +8/+12/+18
mana_reserved cases remain real.
