# UPSTREAM-SYNC — taking Card-Forge updates without harm

*2026-08-17; re-audited 2026-08-24 against the full `git diff 0eec0a16d0a..HEAD`
delta. Companion to [INVENTORY.md](INVENTORY.md) §1 (the authoritative
divergence list). Read both before ANY merge from upstream.*

## The situation, plainly

- We are a fork of [Card-Forge/forge](https://github.com/Card-Forge/forge)
  (`origin`), working on branch `arena`, pushed to `private`
  (btsherry/forge-edh-arena). **Never push to `origin`.**
- Upstream base: **`a5f4f9e4796` (origin/master, 2026-09-10)** since the first sync
  (branch `sync-20260910`, merged into `arena` 2026-09-10; the original fork
  point was `0eec0a16d0a`, 2026-07-15). We are 523 commits ahead of the new
  base (`git rev-list --count a5f4f9e4796..HEAD`). `UpstreamMarkerTest` takes the
  live merge base with `origin/master` and falls back to this constant.
- The early rule "all new code lives in forge-arena, no parent-module
  patches" was **deliberately dropped**. The full delta outside
  `forge-arena/` (2026-09-04 recount, `git diff --name-status
  a5f4f9e4796..HEAD -- . ':(exclude)forge-arena'`) is **12 modified upstream files** plus our new parent-module files (2026-09-10 recount against the NEW base; INVENTORY §1 is the current table):
  - **12 modified**: 9 upstream Java files (301 insertions / 22 deletions —
    ComputerUtil, ComputerUtilMana, AiCostDecision, MyRandom, Combat,
    StaticAbilityTurnPhaseReversed, MagicStack, EDocID, CMatchUI), plus
    `forge-gui/res/defaults/match.xml`, root `pom.xml` (the
    `<module>forge-arena</module>` reactor line), and root `.gitignore`
    (arena transient-output block). pom.xml is a REAL conflict surface —
    upstream edits it routinely.
  - **20 new (ours, zero conflict)**: 9 parent-module code files (3
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
   *Defense: the 467-test arena suite (FULL gate) exercises the seams end-to-end through
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
  `[arena]`/`ARENA-PATCH` comment at the edit site. All 9 comply since 2026-09-09
  (`Combat.java`, `EDocID.java`, `CMatchUI.java` were the last), and
  `forge-arena/src/test/java/forge/arena/UpstreamMarkerTest.java` runs the
  check in the gate: every modified upstream `.java`/`pom.xml` must contain a
  marker or the build is red. Manual verification:
  `git grep -lE "\[arena\]|ARENA-PATCH" -- forge-ai/src forge-core/src forge-game/src forge-gui-desktop/src pom.xml`
  must enumerate every modified upstream file (a bare `grep -ln "arena"`
  false-positives on `GameFormat.java`'s "Arena" format name).
- **Build JDK rule (2026-09-10, W-17):** run gates and package builds with
  `JAVA_HOME` pinned to the JDK 17 install (`/usr/local/Cellar/openjdk@17/…/Contents/Home`
  on this machine) — Homebrew's OpenJDK 25.0.2 crashed twice in its G1 collector
  during the v4.1 gate; the launcher already runs games on the PATH JDK 17 and
  the classes are compiled for release 17 whichever JDK builds them.
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
mvn -o -pl forge-arena -am package -Darena.excluded.groups=headless-scenario   # FULL gate (extended on; HL-21 scenarios off)
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
| Additive hooks | `AiCostDecision.java` (+`TapCostPreference`, `SacCostPreference`, `PaymentPickPreference`) | Re-insert the hook blocks ahead of upstream's (possibly new) stock logic. `TapSymmetryBreakTest` / `SacrificeSeatChoiceTest` / `PaymentPickPreferenceTest` arbitrate. |
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
`SacrificeEffect`/`BalanceEffect`) / the wave-2 set — `chooseNewTargetsFor`
(caller `ChangeTargetsEffect`), `chooseCardsToDiscardToMaximumHandSize`,
`tuckCardsViaMulligan`, `arrangeForScry`/`Surveil`, `orderMoveToZoneList`,
`willPutCardOnTop`, `chooseNumber` x2, `announceRequirements`,
`chooseOptionalCosts`, `chooseProtectionType`, `vote`, `chooseCardsPile`
(check `TwoPilesEffect`'s FaceDown domain: False/One/True) —
against our `MailboxController`
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
mvn -pl forge-arena -am package         # FULL gate: no -DskipTests here — sync
                                        # imports must re-run upstream module
                                        # tests (BUILDING.md gate policy)
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

## The first sync, as it happened (2026-09-10) — the record for the next one

Stages, each on Ben's go: reconnaissance with `git merge-tree --write-tree`
(no checkout; it predicted the two conflicts and showed every marker surviving
the auto-merges) → tag `pre-sync-20260910`, branch, merge, stop at conflicts →
resolve by the playbook (`.gitignore` union; the AiCostDecision discard hook
re-inserted ahead of upstream's restructured fallback) → API drift in OUR code
(`handlePlayingSpellAbility` Runnable→Consumer at five call sites;
`setUseSimulation` moved to AiController with an enum; `AIOption.USE_SIMULATION`
→ `USE_FULL_SIMULATION`) → ONE online compile for two new upstream deps →
FULL gate: 6 red = the marker test's base (moved to the merge base) + five
seeded headless scenarios (fenced, HL-21) → re-ingest all ten decks
(`arena-add-deck.py <dck> --slug <slug> --manifest-only`; four decks needed
`--slug` because the file's deck NAME slugs differently) → three games (two
all-AI, one human) → 4.1 items → merge. Found only by the live games, never by
the gate: BL-47 — upstream's `<revision>` bump left a stale fat jar beside the
new one and the launcher's first-match glob loaded it (`NoSuchMethodError`
mid-game). Budget: about six hours wall-clock including games.

## Seeded scenario tests drift under engine upgrades (learned 2026-09-10)

The first sync (origin/master a5f4f9e4796, 605 commits) turned five headless
combo-scenario tests red with no patch reverted: scripted goldfish games whose
outcome depends on the engine's attack/block evaluation and on the fixture
cards' scripts, both of which upstream changed. Such tests are Project 1's
and are fenced in TestNG group `headless-scenario` (excluded by default and
from the FULL gate; HL-21). Rule: the sync gate is the interactive/protocol
suite plus the behavioural-patch arbiters; scenario games are re-baselined
as separate work, never patched to pass during a sync. A first-run compile
after a sync may need ONE online Maven build for new upstream dependencies
(2026-09-10: jupnp 3.0.5, gson 2.13.2); offline resolves again afterwards.

## Version bumps leave stale fat jars (learned 2026-09-10, BL-47)

Upstream bumps `<revision>` regularly. `mvn package` then writes a NEW
`forge-gui-desktop-<rev>-jar-with-dependencies.jar` beside the old one, and a
first-match glob loads the stale jar: new arena classes over old engine
classes, `NoSuchMethodError` in a live game. The launcher and the packager now
select by the pom's `<revision>` (newest-by-time fallback) and say so when
several are present. After any sync: `ls forge-gui-desktop/target/*.jar` and
remove the old revision (`mvn -o -pl forge-gui-desktop clean` before the gate
is simplest).

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
