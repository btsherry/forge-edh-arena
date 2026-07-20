# Combo-audit batch — flat, and what the telemetry taught

30 games, same seeds as rebaseline + phase10. 30 of 42 combos bound.

| deck | rebaseline | phase 10 | combo-audit |
|---|---|---|---|
| Selvala | 0 | 1 | 1 |
| Purphoros | 8 | 9 | 8 |
| Urza | 0 | 0 | 0 |
| Giada | 9 | 12 | 10 |

**Essentially flat, all within noise of the prior two runs.** The two new
Selvala bindings (Sanctum Weaver + Mantle/Staff) fired ZERO times and aborted
ZERO times across 30 games — they never assembled far enough to enter a line.

## The lesson, confirmed a third time

Coverage is not wins. A combo must (1) be bound correctly, (2) actually
ASSEMBLE in games, and (3) convert. This session fixed several (1)s — the
Power Artifact mechanic, two new Selvala bindings. None moved the needle,
because the bottleneck is (2): these multi-piece combos rarely come together
in 30 games without tutoring, and a correct binding for a combo that never
assembles changes nothing. PR-65 (Ignus), PR-D2 (Sanctum Weaver) and the
phase-10 bindings all confirm it.

The implication for where effort goes: binding MORE combos has diminishing
returns until assembly improves. The decks that win (Purphoros, Giada) win on
lines that need little assembly; the decks that do not (Selvala, Urza) hinge
on fragile multi-piece combos that seldom land.

## A crash-rate scare I talked myself into, then out of

The run showed 5/30 crashes (16%) vs 4/30 and 3/27 before, and 4 of the 5
crashed seeds had been wins or draws in the rebaseline. I initially read that
as a regression I had introduced via the amplifier combat hook.

Checked before acting: 2 of the 5 crashed games never fired lethal_alpha, so
amplified() was never called there — it is not the cause. And the crash rate
across all runs is 10 / 11 / 13 / 16% (300g / 30g / 30g / 30g), a drift of
1-2 games per 30, inside binomial noise against the 10% baseline. The
seed-level "wins became crashes" is that same jitter viewed per-seed, not a
systematic break. All crashes are turns=0 wall-clock timeout draws
reclassified as crash, the long-standing signature, not a new exception.

I jumped to "I broke it" as fast as I have jumped to "it worked" — the same
undisciplined move in the other direction. Checking the data corrected both.

## Honest status after this session's deck work

Real, committed, tested: RNG determinism, prediction-stack deletion, 341-card
ingestion, PR-A/B/C payoff classes, the Power Artifact binding fix, two new
Selvala bindings, full combo accounting. Every number now trustworthy.

Not achieved: Selvala barely breathing (1/30), Urza still 0. Both hinge on
combo ASSEMBLY, which no amount of binding correctness fixes. That is the next
real problem — tutoring toward combo pieces, and mulligan policy that keeps
assemblable hands — not more bindings.
