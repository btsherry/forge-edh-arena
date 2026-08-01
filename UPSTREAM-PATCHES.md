# UPSTREAM-PATCHES

Log of every modification to upstream Card-Forge files in this fork, per the
forge-arena plan (all are tagged `ARENA-PATCH` at the edit site). Keep this list
current — it is the rebase checklist.

| # | File | Change | Reason | Since |
|---|---|---|---|---|
| 1 | `pom.xml` (root) | add `<module>forge-arena</module>` to the reactor | build forge-arena as a sibling module against `${revision}` artifacts | 2026-07-15 |
| 2 | `forge-game/.../staticability/StaticAbilityTurnPhaseReversed.java` | thread-scoped reentrancy guard in `anyTurnPhaseReversed` | infinite mutual recursion crashed ~10% of headless 4-player games: `anyTurnPhaseReversed` → `matchesValidParam` → `Player.getOpponents` → `Game.getPlayersInTurnOrder` → `Player.isTurnOrderReversed` → back. Returns the identity value (`false`) on reentry — the outer call is already deciding that exact question, and no real card reverses turn order conditionally on turn order. Candidate upstream PR. | 2026-07-19 |

## 2. `forge-core/src/main/java/forge/util/MyRandom.java` — per-thread RNG

**Why.** The random provider was one process-wide static, so any thread that
drew a number shifted the sequence every other thread saw. A headless batch
running work on a second thread silently perturbed the live game.

**Measured.** 15 of 30 games diverged on IDENTICAL seeds — different winner,
different length. Seeded reproduction was impossible and every seed-paired
A/B comparison we had run was paired in name only.

**Change.** `ThreadLocal<Random>` provider plus `setSeed(long)`, which gives
each thread its own generator from the same seed. `setRandom` now binds the
calling thread. Unseeded behaviour is unchanged — each thread lazily gets a
`SecureRandom` exactly as before, so interactive Forge is unaffected.

**Merge risk.** Low. One file, no signature removed; `setRandom` keeps its
name and arity.

## 3. `forge-game/src/main/java/forge/game/combat/Combat.java` — getAttackers defensive snapshot

**Why.** `getAttackers()` iterated the live `attackedByBands` multimap view,
throwing ConcurrentModificationException when AI speculative combat evaluation
(`AnimateAi.animateTgtAI` → `ComputerUtilCard.doesSpecifiedCreatureAttackAI` →
`AiAttackController.declareAttackers`) mutated the bands mid-iteration on large
boards.

**Measured.** Killed 2 of 3 Urza program games in the tau30 batch (previously a
1-in-30 background rate).

**Change.** Iterate a copied `ArrayList` of `attackedByBands` values instead of
the live multimap view. Not an AI-logic modification; Ben-approved as the third
logged infrastructure patch. Candidate for an upstream PR.

**Since.** 2026-07-28.
