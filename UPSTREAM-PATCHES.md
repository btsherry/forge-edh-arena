# UPSTREAM-PATCHES

Log of every modification to upstream Card-Forge files in this fork, per the
forge-arena plan (all are tagged `ARENA-PATCH` at the edit site). Keep this list
current — it is the rebase checklist.

| # | File | Change | Reason | Since |
|---|---|---|---|---|
| 1 | `pom.xml` (root) | add `<module>forge-arena</module>` to the reactor | build forge-arena as a sibling module against `${revision}` artifacts | 2026-07-15 |
| 2 | `forge-game/.../staticability/StaticAbilityTurnPhaseReversed.java` | thread-scoped reentrancy guard in `anyTurnPhaseReversed` | infinite mutual recursion crashed ~10% of headless 4-player games: `anyTurnPhaseReversed` → `matchesValidParam` → `Player.getOpponents` → `Game.getPlayersInTurnOrder` → `Player.isTurnOrderReversed` → back. Returns the identity value (`false`) on reentry — the outer call is already deciding that exact question, and no real card reverses turn order conditionally on turn order. Candidate upstream PR. | 2026-07-19 |
