# UPSTREAM-SYNC — taking Card-Forge updates without harm

*2026-08-17; re-audited 2026-08-24 against the full `git diff 0eec0a16d0a..HEAD`
delta. Companion to [INVENTORY.md](INVENTORY.md) §1 (the authoritative
divergence list). Read both before ANY merge from upstream.*

## The situation, plainly

- We are a fork of [Card-Forge/forge](https://github.com/Card-Forge/forge)
  (`origin`), working on branch `arena`, pushed to `private`
  (btsherry/forge-edh-arena). **Never push to `origin`.**
- Upstream base: `0eec0a16d0a` (2026-07-15). We are ~396 commits ahead
  (2026-08-24 count); upstream is very active (daily card-script updates,
  regular engine work).
- The early rule "all new code lives in forge-arena, no parent-module
  patches" was **deliberately dropped**. The full delta outside
  `forge-arena/` (2026-08-24 re-audit) is **31 files**:
  - **12 modified**: 9 upstream Java files (~263 changed lines —
    ComputerUtil, ComputerUtilMana, AiCostDecision, MyRandom, Combat,
    StaticAbilityTurnPhaseReversed, MagicStack, EDocID, CMatchUI), plus
    `forge-gui/res/defaults/match.xml`, root `pom.xml` (the
    `<module>forge-arena</module>` reactor line), and root `.gitignore`
    (arena transient-output block). pom.xml is a REAL conflict surface —
    upstream edits it routinely.
  - **19 new (ours, zero conflict)**: 8 parent-module code files (2
    forge-ai hook interfaces, 6 gui-desktop advisor/AI-panel files — see
    INVENTORY §1b), 10 `runs/*.json` batch templates, and the historical
    `UPSTREAM-PATCHES.md` deep-dive log at root.
  Three of the modifications are **behavioral** (ComputerUtil rollback,
  ComputerUtilMana effective-part payment vetting, MyRandom seeding) — an
  unmanaged merge could silently revert them and re-open closed bugs (a
  reverted rollback patch = vanishing commanders again). AiCostDecision
  carries two additive hooks (tap + sacrifice payment) that must survive
  any reshape of its visit methods.

## Why blind merging is dangerous — the three failure modes

1. **Silent revert.** Upstream rewrites a function we patched; the merge
   auto-resolves toward upstream; our behavior disappears with no conflict
   marker. *Defense: every behavioral divergence has a regression test that
   FAILS if the behavior reverts* (`UnaffordableCastRollbackTest`,
   `SeedDeterminismTest`) — the test suite, not the diff, is the contract.
2. **Semantic drift under our overrides.** `MailboxController` overrides ~20
   `PlayerControllerAi` methods and mirrors one stock method
   (`prepareTriggerViaSeat` mirrors `prepareSingleSa`;
   `orderAndPlaySimultaneousSa` is a modified copy). Upstream can change the
   *originals'* semantics (new parameters, new call sites, new decision
   surfaces) without touching our files — compiles clean, behaves wrong.
   *Defense: the 318-test arena suite exercises the seams end-to-end through
   real games; plus the mirror-audit step below.*
3. **Card-script behavior shifts.** `forge-gui/res/cardsfolder` changes daily
   upstream. Our brains read live oracle text (fine), but the
   symmetry-piece detector keys on script *metadata shape*
   (`IsPresent$ Card.Self+untapped`, `Affected$ Player`) and dossiers cache
   ingest-time data. *Defense: metadata-shape tests (TapSymmetryBreakTest
   uses real scripts) + treat res/ as upstream-owned (take theirs wholesale;
   our only res/ divergence is `defaults/match.xml`).*

## Standing discipline (do these NOW and always)

- **Marker rule:** every edit to an upstream file carries an
  `[arena]`/`ARENA-PATCH` comment at the edit site. 6/9 comply;
  `Combat.java`, `EDocID.java` and `CMatchUI.java` do not — add markers on
  the next touch (Combat's edit is logged in UPSTREAM-PATCHES.md §3 but
  unmarked in-file). Verification:
  `git grep -lE "\[arena\]|ARENA-PATCH" -- forge-ai/src forge-core/src forge-game/src forge-gui-desktop/src pom.xml`
  must enumerate every modified upstream file (a bare `grep -ln "arena"`
  false-positives on `GameFormat.java`'s "Arena" format name).
- **Test-per-divergence rule:** a behavioral upstream patch does not land
  without a test that fails when the patch is absent.
- **INVENTORY §1 is maintained:** any new parent-module edit updates that
  table in the same commit.
- **New parent-module code prefers NEW files** (like `TapCostPreference`,
  `AiControlFile`) over edits — new files can never conflict.

## The merge procedure

Run this when we choose to sync (see cadence below). Budget a focused
session; never mix a sync with feature work.

```sh
# 0) preconditions: clean tree, all tests green, tag the pre-sync point
git status --porcelain            # must be empty
mvn -o -pl forge-arena -am package   # 318 green, checkstyle on
git tag pre-sync-$(date +%Y%m%d)

# 1) fetch and branch — NEVER merge into arena directly
git fetch origin master
git checkout -b sync-$(date +%Y%m%d) arena

# 2) merge
git merge origin/master
```

**3) Conflict playbook, by file class (INVENTORY §1 is the checklist):**

| Class | Files | Resolution rule |
|---|---|---|
| Behavioral patches | `ComputerUtil.java`, `ComputerUtilMana.java`, `MyRandom.java` | Take upstream's new shape, **re-apply our behavior by hand** at the marker site; the guarding test is the arbiter. If upstream restructured the whole method, port the *intent* (rollback-to-origin-zone; seedable RNG), not the old lines. |
| Additive hooks | `AiCostDecision.java` (+`TapCostPreference`, `SacCostPreference`) | Re-insert the hook blocks ahead of upstream's (possibly new) stock logic. `TapSymmetryBreakTest` / `SacrificeSeatChoiceTest` arbitrate. |
| Diagnostics | `MagicStack.java` | Re-add the FIZZLE stderr block wherever the fizzle branch now lives. Cheap; skip only if the branch vanished. |
| Defensive fixes | `Combat.java`, `StaticAbilityTurnPhaseReversed.java` | Check if upstream fixed it themselves (both are upstream-worthy); if yes, drop ours — divergence shrinks. |
| GUI wiring | `EDocID.java`, `CMatchUI.java` | Re-add the 2+6 registration lines. Mechanical. |
| Root build/infra | `pom.xml`, `.gitignore` | Union-merge: keep upstream's changes AND our one `<module>forge-arena</module>` line (ARENA-PATCH-marked) / our arena transient-output ignore block. |
| New files (ours) | everything in 1b, plus `runs/*.json` + `UPSTREAM-PATCHES.md` at root | No conflicts possible; verify the code files still compile against changed APIs. |
| res/ | everything except `defaults/match.xml` | **Take upstream wholesale.** Keep our match.xml (re-apply if the schema moved). |

**4) Mirror-audit (the silent-drift defense):** diff upstream's new
`PlayerControllerAi.prepareSingleSa` / `orderAndPlaySimultaneousSa` /
`handlePlayingSpellAbility` / `chooseTargetsFor` /
`playSaFromPlayEffect` (and its callers in `PlayEffect`/`DiscoverEffect`/
`ChangeZoneEffect`) / `choosePermanentsToSacrifice`+`Destroy` (callers in
`SacrificeEffect`/`BalanceEffect`) against our `MailboxController`
mirrors and the assumptions in `INTERACTIVE-ARENA.md` field notes
14/15/21/49/50; port semantic changes. In `AiCostDecision`, re-verify the
two hook consults (`visit(CostTapType)` → `TapCostPreference`,
`visit(CostSacrifice)` → `SacCostPreference`) still run BEFORE stock
heuristics and that `visit(CostSacrifice)` is still reached only at
actual payment time (never affordability scans) — the live mailbox
exchange in `preferredSacCards` depends on that. Also re-check that no
NEW `PlayerController` decision methods appeared that should be
seat-owned (anything user-facing upstream added → candidate mailbox
surface).

**5) Gates, in order — all must pass before touching `arena`:**
```sh
mvn -pl forge-arena -am package         # full build + 318 tests + checkstyle, ONLINE first time
( cd forge-arena/runner && python3 -m unittest discover -s tests )   # 113 py tests
forge-arena/runner/run_table.sh --preflight
forge-arena/scripts/arena-play.sh --all-ai   # one live smoke game, watch for
                                             # FIZZLE/TARGETLOSS/SA-SWAP/REFUSED/vanish language
forge-arena/scripts/arena-stop.sh            # clean teardown + a rated result
```

**6) Land + record:**
```sh
git checkout arena && git merge --ff-only sync-$(date +%Y%m%d)
git push private arena
# update INVENTORY §1 (sizes/upstream-fixed rows), note the new upstream base here
```

## Cadence & triggers

- **Default: deliberate and infrequent** (quarterly-ish). We gain card-script
  freshness and engine fixes; we risk seam drift. The arena does not need
  daily card updates — brains play from oracle text the engine provides.
- **Sync early when:** upstream ships an engine fix we feel (a rules bug our
  games hit), a card set the decks need, or a security/build fix.
- **Never sync when:** mid-feature, mid-release, or without the full gate
  budget. A half-merged sync branch is fine to abandon; a poisoned `arena`
  is not — hence sync branches + the pre-sync tag, always.

## Shrinking the divergence (standing goal)

Candidates to offer upstream as PRs (each removes a conflict row forever):
`Combat.getAttackers` snapshot fix; `StaticAbilityTurnPhaseReversed` crash
guard; arguably the `ComputerUtil` rollback (it fixes their own FIXME).
`MyRandom` seeding could go upstream behind a system property. The
TapCostPreference/SacCostPreference hooks and the GUI tabs are
arena-specific; they stay ours.
