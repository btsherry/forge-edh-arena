# UPSTREAM-SYNC — taking Card-Forge updates without harm

*2026-08-17; re-audited 2026-08-24 against the full fork delta; rewritten
2026-10-02 after a dry run of the second sync, which was then executed the
same afternoon (the record is below). Companion to [INVENTORY.md](INVENTORY.md) §1 (the authoritative
divergence list). Read both before ANY merge from upstream.*

## The situation, plainly (as of 2026-10-02, after the second sync)

- We are a fork of [Card-Forge/forge](https://github.com/Card-Forge/forge)
  (`origin`), working on branch `arena`, pushed to `private`
  (btsherry/forge-edh-arena). **Never push to `origin`.** The local `master`
  branch is an upstream mirror; never commit to it.
- Upstream base: **`fb4d8091126` (origin/master, 2026-10-02)** since the
  second sync (branch `sync-20261002`, merged 2026-10-02 at `81d7cea3d0f`,
  tag `post-sync-20261002`; rollback tag `pre-sync-20261002` = `461735a2c48`).
  Earlier bases: `a5f4f9e4796` (first sync, 2026-09-10) and the fork point
  `0eec0a16d0a` (2026-07-15). `arena` is **663 commits ahead** of the base
  (`git rev-list --count fb4d8091126..arena`). That sync took 356 upstream
  commits, 3,579 files (2,957 card scripts), `<versionCode>` 2.0.15 → 2.0.16.
  `UpstreamMarkerTest` takes the live merge base with `origin/master` and
  falls back to the constant `fb4d8091126`; after a sync the merge base moves
  by itself.
- The divergence outside `forge-arena/` (INVENTORY §1, recounted 2026-10-02 —
  unchanged by the sync, every patch auto-merged:
  `git diff --name-status fb4d8091126..arena -- . ':(exclude)forge-arena'`):
  - **14 modified upstream files**: 10 upstream Java files — `ComputerUtil`,
    `ComputerUtilMana`, `AiCostDecision`, `MyRandom`, `Combat`,
    `StaticAbilityTurnPhaseReversed`, `MagicStack`, `EDocID`, `CMatchUI`,
    `forge-gui-desktop/.../sound/AudioClip.java` — plus
    `forge-gui/res/defaults/match.xml`, root `pom.xml` (the
    `<module>forge-arena</module>` reactor line), root `.gitignore` (the arena
    transient-output block) and root `.gitattributes` (`*.wav`/`*.mp3` binary).
    `pom.xml` is a REAL conflict surface — upstream edits it routinely.
  - **14 new parent-module code files (ours, zero conflict)**: 3 forge-ai hook
    interfaces, 11 gui-desktop files (the Advisor and AI-panel dock tabs, the
    offer pane, `AiControlFile`, `AdvisorLogTail`, `HotkeyGuard`, `DealQuestion`,
    `FlatJson`, `VoiceFocus`) — INVENTORY §1b — plus 10 `runs/*.json` batch
    templates and the historical `UPSTREAM-PATCHES.md` at root.
  - Three modifications are **behavioral** (ComputerUtil rollback,
    ComputerUtilMana effective-part payment vetting, MyRandom seeding) and one
    is **audible** (AudioClip 16-bit decode). An unmanaged merge could silently
    revert them and re-open closed bugs (a reverted rollback patch = vanishing
    commanders again). AiCostDecision carries additive hooks (tap, sacrifice,
    exile/discard/return payments) that must survive any reshape of its
    `visit` methods.
- **Everything else we own is under `forge-arena/`**, which upstream never
  touches: the whole mailbox seam (`MailboxController`, `AdvisorControllerHuman`,
  …), the runner, the voices, the decks, the docs. **There is nothing to
  re-apply there after a merge** — it merges clean by construction. What CAN
  break is the *meaning* of the upstream code it calls; that is the
  mirror-audit (step 4) and the semantics table (next-but-one section).

## Why blind merging is dangerous — the three failure modes

1. **Silent revert.** Upstream rewrites a function we patched; the merge
   auto-resolves toward upstream; our behavior disappears with no conflict
   marker. *Defense: every behavioral divergence has a regression test that
   FAILS if the behavior reverts* (`UnaffordableCastRollbackTest`,
   `SeedDeterminismTest`, `AudioDecodeFormatTest`, the hook tests) — the test
   suite, not the diff, is the contract. The marker-survival check in the
   reconnaissance (below) catches the textual half before any checkout.
2. **Semantic drift under our overrides.** `MailboxController` overrides ~20
   `PlayerControllerAi` methods and mirrors one stock method
   (`prepareTriggerViaSeat` mirrors `prepareSingleSa`;
   `orderAndPlaySimultaneousSa` is a modified copy). Upstream can change the
   *originals'* semantics (new parameters, new call sites, new decision
   surfaces, a reset that no longer happens) without touching our files —
   compiles clean, behaves wrong. *Defense: the 494-test Maven gate (49
   interactive test classes exercise the seams through real games on real
   cards) plus the mirror-audit step and the semantics table below.*
3. **Card-script behavior shifts.** `forge-gui/res/cardsfolder` changes daily
   upstream (2,957 scripts between our base and 2026-10-02). Our brains read
   live oracle text (fine), but several seam rules key on script *metadata
   shape* and several tests use real scripts as fixtures. *Defense:
   metadata-shape tests (`TapSymmetryBreakTest`, `ManaTableTest`,
   `OptionalAndMultiTargetTest`) + treat `res/` as upstream-owned (take theirs
   wholesale; our only `res/` divergence is `defaults/match.xml`).*

## Standing discipline (do these NOW and always)

- **Marker rule:** every edit to an upstream file carries an
  `[arena]`/`ARENA-PATCH` comment at the edit site. All 11 Java-or-pom
  files comply (`EDocID` 2 markers, `CMatchUI` 3, `AudioClip` 3, …), and
  `forge-arena/src/test/java/forge/arena/UpstreamMarkerTest.java` runs the
  check in the gate. Manual verification:
  `git grep -lE "\[arena\]|ARENA-PATCH" -- forge-ai/src forge-core/src forge-game/src forge-gui-desktop/src pom.xml`
  must enumerate every modified upstream file (a bare `grep -ln "arena"`
  false-positives on `GameFormat.java`'s "Arena" format name). The marker
  test resolves the repo root by looking for a `.git` DIRECTORY, so it reads
  "no modified upstream source" inside a `git worktree` (whose `.git` is a
  file) — run the gate in the main checkout, or know that this one red is the
  worktree, not the merge.
- **Build JDK rule (2026-09-10, W-17):** run gates and package builds with
  `JAVA_HOME` pinned to the JDK 17 install
  (`/usr/local/Cellar/openjdk@17/17.0.18/libexec/openjdk.jdk/Contents/Home`
  on this machine) — Homebrew's OpenJDK 25.0.2 crashed twice in its G1
  collector during the v4.1 gate; the launcher runs games on the PATH JDK 17.
- **Gate on exit status, never on a tail** (2026-09-03: a piped `tail` hid a
  SIGSEGV fork crash and a red gate got pushed). Capture `$?`, then read the
  surefire report's `testng-results` line AND its timestamp — a stale report
  from an earlier run looks green.
- **Test-per-divergence rule:** a behavioral upstream patch does not land
  without a test that fails when the patch is absent.
- **INVENTORY §1 is maintained:** any new parent-module edit updates that
  table in the same commit.
- **New parent-module code prefers NEW files** (like `TapCostPreference`,
  `VoiceFocus`) over edits — new files can never conflict.
- **Never patch upstream for convenience** (Ben, 2026-09-10): live with stock
  Forge limitations; fixes go in `forge-arena/` or in new files.
- **Scenario tests are never patched to pass during a sync** (HL-21).

## Reconnaissance before a sync — no checkout, no risk (run this first)

Everything here is read-only against the repository; it answers "what will
the merge do" before a branch exists. The 2026-10-02 run took forty minutes
including the probe compile and gate.

```sh
cd /Users/toor/Claude/personal/forge-edh-arena
git status --porcelain                          # must be empty
git fetch origin master                         # moves origin/master only
git log -1 --format='%h %cd %s' --date=short origin/master
git rev-list --count a5f4f9e4796..origin/master # upstream commits since our base
git merge-base arena origin/master              # must still print the base

# 1) trial merge into a tree object: exit 0 = no textual conflicts; the first
#    line is the merged tree id, conflicts are listed after it
git merge-tree --write-tree --name-only arena origin/master

# 2) which of OUR patched files did upstream also touch (the ones to re-check)
for f in $(git diff --name-only a5f4f9e4796..arena -- . ':(exclude)forge-arena'); do
  printf '%s: ' "$f"; git diff --numstat a5f4f9e4796..origin/master -- "$f" | awk '{print "+"$1" -"$2}'; echo
done

# 3) marker survival in the merged tree: every patched file must keep the same
#    number of markers and the same delta against the NEW upstream as it has
#    against the OLD base (T = the tree id from step 1)
T=<tree id>
for f in <each patched file>; do
  echo "$f: markers $(git show arena:$f | grep -cE '\[arena\]|ARENA-PATCH') -> $(git show $T:$f | grep -cE '\[arena\]|ARENA-PATCH')" \
       "delta $(git diff --numstat a5f4f9e4796..arena -- $f | awk '{print "+"$1"/-"$2}') -> $(git diff --numstat origin/master $T -- $f | awk '{print "+"$1"/-"$2}')"
done

# 4) upstream changes under our seams (the semantics table below names them)
git diff --numstat a5f4f9e4796..origin/master -- \
  forge-ai/src/main/java/forge/ai/PlayerControllerAi.java \
  forge-ai/src/main/java/forge/ai/AiController.java \
  forge-game/src/main/java/forge/game/player/PlayerController.java \
  forge-game/src/main/java/forge/game/spellability/SpellAbility.java \
  forge-game/src/main/java/forge/game/spellability/TargetRestrictions.java \
  forge-game/src/main/java/forge/game/spellability/TargetChoices.java \
  forge-game/src/main/java/forge/game/zone/MagicStack.java \
  forge-game/src/main/java/forge/game/ability/effects/DamageDealEffect.java \
  forge-gui/src/main/java/forge/player/PlayerControllerHuman.java
git log --oneline a5f4f9e4796..origin/master -- <those files>   # read the commits that touched them

# 5) the probe: compile AND gate the merged tree in a throwaway worktree.
#    Nothing here touches arena. One online Maven run is normal (new upstream
#    test dependencies); the 30 combo/prep reds are the worktree missing the
#    gitignored deck dossiers, and the marker test reads the worktree wrongly.
C=$(git commit-tree $T -p arena -p origin/master -m "PROBE ONLY")
git worktree add --detach /tmp/sync-probe $C
( cd /tmp/sync-probe && JAVA_HOME=<jdk17> mvn -q -pl forge-arena -am test-compile -DskipTests; echo "COMPILE $?" )
( cd /tmp/sync-probe && JAVA_HOME=<jdk17> mvn -o -q -pl forge-arena -am package -Darena.excluded.groups=headless-scenario; echo "GATE $?" )
grep -o 'testng-results[^>]*' /tmp/sync-probe/forge-arena/target/surefire-reports/testng-results.xml
git worktree remove --force /tmp/sync-probe && git worktree prune
```

**Result of the 2026-10-02 dry run (arena `3a10dafdf9b` × origin/master
`fb4d8091126`):** merge-tree exit 0, tree `4b860289b8a` — **no textual
conflicts**. Five of our fourteen patched files were also touched upstream —
`pom.xml` (+1 −1, the version bump), `ComputerUtil` (+73 −38), `MagicStack`
(+79 −77, the undo stack moved out), `EDocID` (+3 −1), `CMatchUI` (+121 −59)
— and **every patch survived** the auto-merge with its marker count and its
delta intact. The merged tree **compiled clean, main and tests**, after one
online Maven run for upstream's new test dependencies (`byte-buddy` 1.15.4,
`objenesis` 3.3). The gate on the merged tree: **every one of the 49
interactive test classes passed**, including the game-64 ones; the 31 reds
were the 30 combo/prep tests that read `decks/*/dossier/` (gitignored, absent
in a worktree) and the marker test's worktree blindness. So the next sync is
mechanically ready; what remains is the semantic audit below, the live games,
and the decision to spend the session.

## Arena Java that leans on upstream semantics — re-verify after EVERY merge

This is the answer to "do we have to re-apply our own Java changes after a
merge": **no file under `forge-arena/` is ever re-applied** — upstream never
edits it. But each row below is an assumption about upstream code that a
merge can invalidate without a conflict. The arbiter is the test; the column
"upstream 2026-10-02" is what the dry run found in the 356 incoming commits.

| Our code (all in `MailboxController` unless noted) | Upstream it relies on | The assumption | Arbiter | Upstream 2026-10-02 |
|---|---|---|---|---|
| `playChosenSpellAbility` root gate (BL-61): asks for targets when the root `usesTargeting()` and `getTargets()` is empty, or a required count is invalid | `SpellAbility.getTargets/resetTargets`, `TargetRestrictions.getMinTargets/getMaxTargets`, `isTargetNumberValid` → `isMinTargetsChosen` | an ability reaches the cast path with NO targets unless something aimed it on purpose; a DIVIDED part reads as "valid" until `clearTargets()` computes its amount (so the gate also keys on emptiness) | `OptionalAndMultiTargetTest` (Frost Breath, Tezzeret, Shatterskull, Electrolyze) | **`SpellAbility.resetOnceResolved()` no longer resets targets** (`789bda3c2a0`, "Some cleanup #12075"). For activated abilities the stack still clears the ORIGINAL's root targets on `add` (`original.clearTargets()`, `MagicStack`), and a resolved spell's card becomes a new object, so the gate still sees empty targets — verified by the probe gate. Sub-part targets of a re-activated ability were never cleared (W-22 h): the sub-part loop skips a part that already holds valid targets. |
| `multiTargetsViaSeat` + `targetCandidates` | `TargetRestrictions.getAllCandidates` (incremental `canTarget` against the picks so far: different controllers, same type, total CMC…), `canTargetSpellAbility`, `TargetChoices.add/contains`, `isRandomTarget` | candidates are legal one at a time; `add` refuses non-game objects; random targets are rolled by the engine | same test, `CounterspellReachesTargetTest`, `StackTargetsVisibleTest` | `TargetRestrictions`, `TargetChoices` unchanged; `SpellAbility.canTarget` unchanged |
| `divideViaSeat`, `allocateEvenly`, `stockAimChecked` | `SpellAbility.clearTargets` (recomputes `dividedValue` from `DividedAsYouChoose$`), `getDividedValue`, `addDividedAllocation`, `getTotalDividedValue`; `DamageDealEffect` reads `getDividedValue(target)` per target and unboxes it | X is announced before the aim (`mailboxManaX` runs first), every target holds an allocation ≥ 1, the sum equals the amount | Shatterskull + Hellkite + Electrolyze cases of the same test | `DamageDealEffect` unchanged; `clearTargets` unchanged |
| stock floor for a REQUIRED multi aim: `super.chooseTargetsFor` | `PlayerControllerAi.chooseTargetsFor` = `brains.doTrigger(sa, true)` (MANDATORY mode; `DamageDealAi` may add every candidate for a 0-minimum part and allocate nothing) | stock's answer is checked, never trusted: count legal, amount allocated | `aPuntOnARequiredAimGoesToStockAndStaysLegal` | `DamageDealAi`: `filterCreaturesThatWillDieThisTurn` lost its `sa` argument (we do not call it) |
| `prepareTriggerViaSeat` (mirror of `prepareSingleSa`) and the declined-trigger auto-aim | `WrappedAbility`, `AbilityUtils.getDefinedPlayers`, `CharmEffect.makeChoices`, `pendingTriggerDecline` ↔ `confirmTrigger` | an optional trigger declined at aim stacks LEGALLY with its full minimum of targets (stack objects, not host cards, for spell-targeting triggers) and is auto-declined at resolution | `TriggerAimContractTest`, `ModalTriggerAimTest`, `SiblingTriggerBatchTest`, the Hellkite case | `WrappedAbility`, `CharmEffect` unchanged |
| `orderAndPlaySimultaneousSa` (modified copy) — the COPY branch keeps stock's text | `PlayerControllerAi.orderAndPlaySimultaneousSa` | the copied-spell branch is upstream's verbatim | `ScepterCopyCastTest` | **upstream replaced the copy branch with `chooseNewTargetsForCopy` (`f12cd05dbe1`, "AI: give spell copies useful new targets #11977")** — re-port that branch into our copy at the sync, or call the new private method's logic by hand |
| `chooseNewTargetsFor` (single-target retargets only) | `ChangeTargetsEffect` → `PlayerController.chooseNewTargetsFor(ability, filter, optional)` | signature and the "return null = keep targets" contract | (reading) | unchanged |
| `playSaFromPlayEffect` (optional and required parts aimed before a free cast) | `PlayEffect`, `DiscoverEffect`, `ChangeZoneEffect` callers; `ComputerUtil.playStack` | the callers still hand the SA to the controller before casting | `ScepterCopyCastTest` | `PlayEffect` unchanged; `ComputerUtil` +73 −38 (our rollback hook survived; re-read `handlePlayingSpellAbility`) |
| `manaAbilityYield`, `producedColors`, `manaSources` (W-4) | `SpellAbility.metConditions()` (falls back to the host's controller when no activator is set — the "Did not have activator set" line), `AbilityManaPart`, `AbilityUtils.calculateAmount`; the two-part shape of `gemstone_caverns.txt` | a chained Mana part with an unmet condition adds nothing; the stock payer taps a luck-counter Caverns on its own | `ManaTableTest` (both Caverns tests) | `SpellAbilityCondition`, `AbilityManaPart` unchanged; `gemstone_caverns.txt` unchanged |
| `mailboxManaX` / `announceRequirements` | `SpellAbility.getPayCosts().hasXInAnyCostPart`, `ComputerUtilMana.determineLeftoverMana` | a loyalty X is not a mana X | `ManaTableTest.loyaltyXIsNotAManaX` | `ComputerUtilMana` unchanged upstream |
| the FIZZLE / TARGETLOSS diagnostics | our `MagicStack` patch, `SpellAbilityStackInstance` | the fizzle branch still exists where we re-add the print | (log) | `MagicStack` +79 −77: the undo stack moved to its own service; the patched hunk auto-merged |
| `chooseNewTargetsForCopy` (our verbatim port, since this sync) | `PlayerControllerAi.chooseNewTargetsForCopy` (private upstream) | the copy branch of `orderAndPlaySimultaneousSa` matches stock's | `ScepterCopyCastTest` (reading) | ported from `f12cd05dbe1`; re-diff at every sync |
| `AdvisorControllerHuman` (the human seat: auto-pick colour, off-colour guard, BL-60) | `PlayerControllerHuman` (overridden methods' signatures) | overrides still match | `OffColorControlTest`, `ColorChoiceWindowTest` | `PlayerControllerHuman` +139 −83 — compiled clean in the probe |
| every `PlayerController` subclass of ours (`MailboxController`, `AdvisorControllerHuman`, `ComboAwareLobbyPlayer`, `GoldfishLobbyPlayer`) | `PlayerController` abstract surface | no new abstract method is left unimplemented | (compile) | **three new abstract methods** (`chooseSticker`, `chooseStickerNamePosition`, `chooseCardToKeepStickers`, `5e3caa29a7d` Unfinity stickers) — implemented in `PlayerControllerAi`/`Human` upstream, so ours inherit them; compiled clean |
| Test fixtures on real cards | `res/cardsfolder`: Frost Breath, Tezzeret the Seeker, Shatterskull Smashing, Bogardan Hellkite, Electrolyze, Gemstone Caverns, Savannah Lions, Llanowar Elves, Grizzly Bears, Hill Giant, Gray Ogre, Mind Stone, Grim Monolith, Sol Ring, Mox Opal, Walking Ballista, Generous Gift, Winter Orb, Rhystic Study, Tidespout Tyrant, Counterspell | the scripts keep their target shape and costs | the tests themselves | all unchanged between the base and `fb4d8091126` |

Add a row whenever a new seam leans on an upstream method; delete the row
when the seam goes.

## The merge procedure

Run this when we choose to sync (see cadence below). Budget a focused
session; never mix a sync with feature work; reconnaissance first.

```sh
# 0) preconditions: clean tree, both gates green, tag the pre-sync point
cd /Users/toor/Claude/personal/forge-edh-arena
git status --porcelain                                  # must be empty
export JAVA_HOME=/usr/local/Cellar/openjdk@17/17.0.18/libexec/openjdk.jdk/Contents/Home
mvn -o -q -pl forge-arena -am package -Darena.excluded.groups=headless-scenario; echo "GATE $?"   # FULL gate: 494, exit 0
( cd forge-arena/runner && python3 -m unittest discover -s tests ); echo "PY $?"                   # 744, exit 0
git tag pre-sync-$(date +%Y%m%d)

# 1) fetch and branch — NEVER merge into arena directly
git fetch origin master
git checkout -b sync-$(date +%Y%m%d) arena

# 2) merge (the trial merge said whether this stops at conflicts)
git merge origin/master
```

**3) Conflict playbook, by file class (INVENTORY §1 is the checklist):**

| Class | Files | Resolution rule |
|---|---|---|
| Behavioral patches | `ComputerUtil.java`, `ComputerUtilMana.java`, `MyRandom.java` | Take upstream's new shape, **re-apply our behavior by hand** at the marker site; the guarding test is the arbiter. If upstream restructured the whole method, port the *intent* (rollback-to-origin-zone; refund-in-place for activated abilities; effective-part payment vetting; seedable RNG), not the old lines. |
| Additive hooks | `AiCostDecision.java` (+`TapCostPreference`, `SacCostPreference`, `PaymentPickPreference`) | Re-insert the hook blocks ahead of upstream's (possibly new) stock logic. `TapSymmetryBreakTest` / `SacrificeSeatChoiceTest` / `PaymentPickPreferenceTest` arbitrate. |
| Diagnostics | `MagicStack.java` | Re-add the FIZZLE / DECLINED-TRIGGER stderr block wherever the fizzle branch now lives. Cheap; skip only if the branch vanished. |
| Defensive fixes | `Combat.java`, `StaticAbilityTurnPhaseReversed.java` | Check if upstream fixed it themselves (both are upstream-worthy); if yes, drop ours — divergence shrinks. |
| Audio decode (BL-56) | `forge-gui-desktop/.../sound/AudioClip.java` | Keep `getAudioClips` decoding to **16-bit** (`Converter.convertFrom(...).withTargetFormat(DECODE_FORMAT)`). If upstream replaced the converter or the loader, port the intent: the effects must reach Java Sound as 16-bit signed PCM, never 8-bit. If upstream fixed it themselves, drop ours. **Arbiter: `AudioDecodeFormatTest`** (device-free, per Ben's rule that no lasting test may need the loopback). The loopback probe under `forge-arena/scripts/research/sound/` is optional manual research if the sound changes character after a sync. |
| GUI wiring | `EDocID.java`, `CMatchUI.java` | Re-add the 2 + 7 registration lines. Mechanical. Upstream reshaped `CMatchUI` heavily between the base and 2026-10-02 (+121 −59) and it still auto-merged. |
| Root build/infra | `pom.xml`, `.gitignore`, `.gitattributes` | Union-merge: keep upstream's changes AND our one `<module>forge-arena</module>` line (ARENA-PATCH-marked) / our arena transient-output ignore block / our `*.wav` `*.mp3` binary lines. |
| New files (ours) | everything in INVENTORY §1b, plus `runs/*.json` + `UPSTREAM-PATCHES.md` at root | No conflicts possible; verify the code files still compile against changed APIs (the probe compile does this before the branch exists). |
| `forge-arena/` | everything | Never conflicts. Nothing to re-apply. Run the semantics table. |
| res/ | everything except `defaults/match.xml` | **Take upstream wholesale.** Keep our match.xml (re-apply if the schema moved). |

**4) Mirror-audit (the silent-drift defense):** for every row of the
semantics table, read upstream's diff of the named class and port semantic
changes. In particular diff upstream's new `PlayerControllerAi.prepareSingleSa`
/ `orderAndPlaySimultaneousSa` (the copy branch — `chooseNewTargetsForCopy`
since `f12cd05dbe1`) / `handlePlayingSpellAbility` / `chooseTargetsFor` /
`playSaFromPlayEffect` (and its callers in `PlayEffect`/`DiscoverEffect`/
`ChangeZoneEffect`) / `choosePermanentsToSacrifice`+`Destroy` (callers in
`SacrificeEffect`/`BalanceEffect`) / the wave-2 set — `chooseNewTargetsFor`
(caller `ChangeTargetsEffect`), `chooseCardsToDiscardToMaximumHandSize`,
`tuckCardsViaMulligan`, `arrangeForScry`/`Surveil`, `orderMoveToZoneList`,
`willPutCardOnTop`, `chooseNumber` x2, `announceRequirements`,
`chooseOptionalCosts`, `chooseProtectionType`, `vote`, `chooseCardsPile`
(check `TwoPilesEffect`'s FaceDown domain: False/One/True) — against our
`MailboxController` mirrors and the assumptions in `INTERACTIVE-ARENA.md`
field notes 14/15/21/49/50/106; port semantic changes. Then the target
lifecycle: where upstream now clears an ability's targets between uses
(`MagicStack.add` → `original.clearTargets()` for activated abilities;
`resetOnceResolved` no longer does) — our aim gates key on "holds no target".
In `AiCostDecision`, re-verify the hook consults (`visit(CostTapType)` →
`TapCostPreference`, `visit(CostSacrifice)` → `SacCostPreference`, the
exile/discard/return visits → `PaymentPickPreference`) still run BEFORE stock
heuristics and that `visit(CostSacrifice)` is still reached only at actual
payment time (never affordability scans) — the live mailbox exchange in
`preferredSacCards` depends on that. Also re-check that no NEW
`PlayerController` decision methods appeared that should be seat-owned
(anything user-facing upstream added → candidate mailbox surface; the
2026-10-02 additions are the Unfinity sticker choices — stock is fine for
those, no shipped deck plays stickers).

**5) Gates, in order — all must pass before touching `arena`:**
```sh
export JAVA_HOME=/usr/local/Cellar/openjdk@17/17.0.18/libexec/openjdk.jdk/Contents/Home
rm forge-gui-desktop/target/forge-gui-desktop-<OLD rev>-SNAPSHOT*.jar forge-arena/target/forge-arena-<OLD rev>-SNAPSHOT.jar   # BL-47: the old revision's jars (mvn -o clean may fail offline)
mvn -pl forge-arena -am package -Darena.excluded.groups=headless-scenario; echo "GATE $?"
#   ONLINE the first time after a sync (new upstream dependencies), -o again afterwards;
#   no -DskipTests: the sync must re-run the upstream modules' tests too (BUILDING.md gate policy);
#   then: grep -o 'testng-results[^>]*' forge-arena/target/surefire-reports/testng-results.xml  and check the file's timestamp
( cd forge-arena/runner && python3 -m unittest discover -s tests ); echo "PY $?"      # 744 — our code, but the brief/help text pins it
ls forge-gui-desktop/target/*.jar                       # exactly one revision's jars
mvn -o -q -pl forge-arena -am -DskipTests prepare-package   # ONLY if the gate was red: it regenerates target/classpath.txt, which the ingest needs
for d in forge-arena/decks/*/; do echo $d; done         # re-ingest every shipped deck (card scripts moved):
#   forge-arena/scripts/arena-add-deck.py <dck> --slug <slug> --manifest-only   (four decks need --slug, 2026-09-10)
forge-arena/runner/run_table.sh --preflight
forge-arena/scripts/arena-play.sh --all-ai   # one live smoke game with Urza AND Purphoros seated: watch for
                                             # FIZZLE / TARGETLOSS / SA-SWAP / REFUSED / "targeting threw" / vanish language,
                                             # and that a multi-target window opens (Tezzeret's +1, Shatterskull Smashing)
forge-arena/scripts/arena-stop.sh            # clean teardown + a rated result; read hygiene.txt
```

**6) Land + record:**
```sh
git checkout arena && git merge --ff-only sync-$(date +%Y%m%d)
git tag post-sync-$(date +%Y%m%d)
git push private arena --tags
git branch -d sync-$(date +%Y%m%d)
# update INVENTORY §1 (sizes / upstream-fixed rows), the base and the counts at the top of this file,
# UpstreamMarkerTest.UPSTREAM_BASE (the fallback constant), BUG-LOG (a sync entry), and the memory note
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

## The second sync, as it happened (2026-10-02 15:25–16:10) — the record

Dry run in the morning (the reconnaissance section), executed on Ben's go
the same afternoon, by the lean plan: push + tag `pre-sync-20261002` →
branch, merge (clean; tree = the dry run's plus the docs commit, so no
textual review) → hand work: `chooseNewTargetsForCopy` ported verbatim into
our `orderAndPlaySimultaneousSa` copy, the rollback hook's new surroundings
read (intact, it clears targets itself), `UpstreamMarkerTest.UPSTREAM_BASE`
→ `fb4d8091126`, stale 2.0.15 jars deleted by hand → gate 493/494: the one
red was `UrzaManaLoopTest` (a seeded scenario, storm stage 0 casts after the
engine upgrade) → fenced `headless-scenario` as **HL-22**, never patched →
Python 744 → ten decks re-ingested `--manifest-only`, every card resolved →
certification gate 493/493, exit 0 → one all-AI smoke game (game 65: Urza won
at turn 15 with an Aetherflux Reservoir loop, 885 decisions, 0 punts / 0
deviations / 0 Java exceptions / 0 lost windows; voice 5.6 lines/min) →
fast-forward, tag, push. Budget: 45 minutes of work plus a 14-minute game.
Two lessons, both now in the procedure above:
- **`forge-arena/target/classpath.txt` is written at `prepare-package`.** A
  gate that fails at the test phase never reaches it, so the file stays
  stale — and `arena-add-deck.py` then starts Forge with the OLD jars
  (`ClassNotFoundException: forge.GuiDesktop` after the 2.0.15 jars were
  deleted). Regenerate with `mvn -o -pl forge-arena -am -DskipTests
  prepare-package` before any re-ingest that follows a red gate.
- **`mvn -o clean` can fail offline** (the clean plugin was never cached);
  deleting the old revision's jars by hand is equivalent and quicker.
- The smoke game never played an "up to N" card, so the new multi-target
  window was exercised on the upgraded engine by `OptionalAndMultiTargetTest`
  (7 cases, all green), not live; the first live Tezzeret +1 or Shatterskull
  Smashing on this base is still to be seen.

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
(2026-09-10: jupnp 3.0.5, gson 2.13.2; 2026-10-02 dry run: byte-buddy 1.15.4,
objenesis 3.3); offline resolves again afterwards.

## Version bumps leave stale fat jars (learned 2026-09-10, BL-47)

Upstream bumps `<versionCode>` regularly (2.0.15 → 2.0.16 between our base
and 2026-10-02). `mvn package` then writes a NEW
`forge-gui-desktop-<rev>-jar-with-dependencies.jar` beside the old one, and a
first-match glob loads the stale jar: new arena classes over old engine
classes, `NoSuchMethodError` in a live game. The launcher and the packager now
select by the pom's `<revision>` (newest-by-time fallback) and say so when
several are present. After any sync: `ls forge-gui-desktop/target/*.jar` and
remove the old revision (`mvn -o -pl forge-gui-desktop clean` before the gate
is simplest). The light package (`packaging/build-light-package.sh`) bundles
the jar it selects — check the manifest names the new revision.

## Cadence & triggers

- **Default: deliberate and infrequent** (quarterly-ish). We gain card-script
  freshness and engine fixes; we risk seam drift. The arena does not need
  daily card updates — brains play from oracle text the engine provides.
- **Sync early when:** upstream ships an engine fix we feel (a rules bug our
  games hit), a card set the decks need, or a security/build fix.
- **Never sync when:** mid-feature, mid-release, or without the full gate
  budget. A half-merged sync branch is fine to abandon; a poisoned `arena`
  is not — hence sync branches + the pre-sync tag, always.
- **Always reconnoitre first** (the section above): it costs forty minutes
  and no risk, and it turns the merge session into execution.

## Shrinking the divergence (standing goal)

Candidates to offer upstream as PRs (each removes a conflict row forever):
**`AudioClip.getAudioClips` 16-bit decode (BL-56) — the strongest candidate: a
one-line library call, no new dependency, and Card-Forge issue #8857
("crackling after the AI is thinking") is plausibly this very defect; take the
measurement numbers along.** `Combat.getAttackers` snapshot fix;
`StaticAbilityTurnPhaseReversed` crash guard; arguably the `ComputerUtil`
rollback (it fixes their own FIXME). `MyRandom` seeding could go upstream
behind a system property. The TapCostPreference/SacCostPreference hooks and
the GUI tabs are arena-specific; they stay ours.
