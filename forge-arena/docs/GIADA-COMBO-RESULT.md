# Giada's combo fires — the first end-to-end combo execution

30 games, same seeds as every prior baseline.

| metric | before | after |
|---|---|---|
| combo_ready (observations) | 17 | 15 |
| lines entered (decisions) | 3 | 3 |
| **combos FIRED** | **0** | **2** |
| **fired AND won that game** | **0** | **1** |
| wins | 10 | 10 |

**Wins unchanged is the correct result**, not a disappointing one. Execution
fidelity is the metric; win count is downstream of it. One of Giada's ten
wins is now a COMBO win rather than a combat win — the deck is playing its
own game plan for the first time.

## What fixed it

PR-69. Traced from a real game:

```
zone_change   Walking Ballista  Stack -> Battlefield
combo_ready   1274-3693  (Heliod + Ballista)
zone_change   Walking Ballista  Battlefield -> Graveyard
line_aborted  not_assemblable
```

Ballista is `ManaCost:X X, PT:0/0, K:etbCounter:P1P1:X`. Assembly cast it at
X=0, it entered as a 0/0 with no counters, and state-based actions buried it
on resolution — destroying the combo it had just completed. The abort said
"not_assemblable", which was true and utterly misleading: the piece WAS
assembled, and then it died.

Assembly now casts X-cost pieces at X=1. Deck-agnostic.

## Honest accounting of the remaining gap

15 ready against 3 entries looks like a large leak and mostly is not.
`combo_ready` is an OBSERVATION emitted whenever pieces are reachable; entry
is a DECISION taken only at MAIN1 with an empty stack. The pilot had roughly
7 real decision points, entered 3, fired 2. **Entry->fire went from 0% to
67%.**

The genuine remaining leak is decision-point scarcity, not decision quality.

## The pattern this confirms

Four bugs found this week, all one shape — **the model checks presence where
the game demands usability**:

| what we asked | what the game requires |
|---|---|
| does the deck own a haste card? | can these creatures ATTACK? (PR-54) |
| does the cost hint match? | does the SCRIPT's cost match? (PR-D1) |
| is the piece on the battlefield? | did it SURVIVE RESOLUTION? (PR-69) |
| is the piece in a reachable zone? | is it UNTAPPED and activatable? (open) |

None needed a smarter AI. Each needed the model to stop lying about the
board. That is a much narrower problem than "Magic is multivariant", and it
predicts where the next one lives.

## Next

1. **Readiness must mean usability** — a `{T}`-cost engine that is tapped is
   not ready, and PR-68's diagnostics caught exactly this on Selvala
   ("cost_unpayable: 'Sanctum Weaver' {T} ... card TAPPED").
2. **Resource protection** — the stock AI spends combo pieces for mana.
   `reservedCastNames` stops it CASTING reserved cards; nothing stops it
   TAPPING them.
3. **Execution-fidelity scorecard** as the standing per-deck metric.
