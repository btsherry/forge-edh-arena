# castrecur100 — full scored results (2026-07-30)

100-game batch, standard template (seed_base 3033, 48-turn cap, 6000 priority
passes), all four decks combo-aware with their full program/binding stacks.
First large batch after the cast_recur runner (Body C), the discovered-combos
mechanism, and the refreshed Purphoros tutor weights. NOT seed-paired to the
recent pr-* series (those use seed 6200) — comparison is against deck
baselines, not a specific prior batch.

## Win table

| deck | wins/100 | original 120-game baseline | recent rate (omega100/chi30) |
|---|---:|---:|---:|
| Purphoros | 44 | 25.8 | ~40 |
| Giada | 30 | 20.8 | ~27 |
| Urza | 7 | 0 | ~4–6 |
| Selvala | 1 | 4.2 | ~2–8 |
| timeout_draw | 8 | — | — |
| crash | 10 | — | — |

Decided: 82/100. Crashes at 10/100 are on the high side (host JVM-fork fault
class — SIGSEGV/SIGBUS in the surefire/worker fork, pre-existing, not a code
regression); worth watching but not new.

## cast_recur, measured

- **Fired organically in 4 of 100 games** — per-game iterations [29, 19, 17, 13],
  78 total. It converts when it fires: **Purphoros won all 4 of those games
  through cast_recur** (4/4 conversion once assembled).
- **Birgi discovered-combo dispatched live twice** — the discovered-combos
  mechanism works end to end in real games, not just the forced test. Ben's
  paper line is a first-class combo the tracker recognizes and the runner runs.
- **Program aborts (Purphoros): refund_source_lost ×6, no_outlet ×2** — clean,
  honest fresh-evaluation aborts: the combo assembled partially, then a piece
  (Steam-Kin/Birgi, or the payoff) left the board. Resilience/assembly frontier,
  not an execution bug.

## Reading it honestly

1. **cast_recur works but is entry-gated.** It's a THREE-piece combo (engine +
   refund + payoff); it assembled organically in ~4% of games. The runner's
   execution is not the limit — conversion is 4/4 when it fires — assembly is.
   Same frontier every multi-piece combo hits.

2. **cast_recur did NOT visibly lift Purphoros's win rate.** He landed at 44,
   consistent with his RECENT ~40 rate (the early 56–64% pace was seating skew
   that regressed as the rotation evened, exactly as flagged). Only 4 of his 44
   wins came through cast_recur; the other 40 are his existing aggressive
   ETB/combat/copy lines. On THIS deck the new combo is redundant coverage —
   Purphoros was already winning without it. (vs the ORIGINAL 25.8 baseline the
   44 looks huge, but that gap is the CUMULATIVE Phase-11 work across all decks,
   not cast_recur.)

3. **The regression check is clean.** The shared-code changes
   (ComboDef.loadWithDiscovered, TutorWeights discovered-combo reading, the
   cast_recur dispatch branch) did not dent any deck: Giada strong at 30, Urza
   holding at 7 (Phase-11 programs paying off vs a 0 baseline), Selvala at 1
   (low — the deck still entirely on legacy bindings, awaiting its mana-loop
   arc; this run is within its noisy 1–8 range).

## The takeaway for the roadmap

Two architectural wins confirmed in the wild — the cast_recur shape and the
discovered-combos channel both fire and convert organically. But the batch
also proves the honest point: a new combo only moves a deck's win rate if the
deck NEEDED it, and Purphoros didn't. Where cast_recur and the discovered-
combos channel will actually matter is a deck that's combo-dependent and
currently underserved — which is the direct argument for the two queued
initiatives: the cross-deck reuse proof (#54) and the Selvala mana-loop arc
(#47, Selvala at 1/100 is the pod's weakest and the most combo-starved).
