# T0 Verification — Forge internals vs. Implementation Plan v3.1 §1

**Status: COMPLETE — gate passed.**
Verified against fork commit `0eec0a16d0ad4352648b8b36e9569c4591082ad2` (upstream master, 2026-07-15), branch `arena`.
Build verified: `JAVA_HOME=<jdk17> mvn -pl forge-gui-desktop -am install -DskipTests -Dcheckstyle.skip=true` → BUILD SUCCESS (39s; modules forge-core, forge-game, forge-ai, forge-gui, forge-gui-desktop). Parent pom pins `maven.compiler.release=17`.

Method: full structural map built from a March-2026 checkout, then every claim re-verified against this tree with file:line evidence. **Verdict: all plan-§1 assumptions confirmed except 4 corrections (§2). Update the plan's code sketches accordingly.**

---

## 1. Confirmed assumptions (evidence)

| # | Plan assumption | Verdict | Evidence (path : line) |
|---|---|---|---|
| 1 | Headless CLI `SimulateMatch`, `sim -f commander`, `-n`, tournaments | ✅ | `forge-gui-desktop/src/main/java/forge/view/SimulateMatch.java:37` (`simulate(String[])`); dispatch `forge/view/Main.java:76` `case "sim"` |
| 2 | `PlayerControllerAi` subclassable decision seam | ✅ non-final | `forge-ai/.../PlayerControllerAi.java:56` extends `PlayerController`; ctor `(Game, Player, LobbyPlayer)` :61; `getAbilityToPlay(Card, List<SpellAbility>, ITriggerEvent)` :80 |
| 3 | `AiController` | ✅ | `forge-ai/.../AiController.java:103` ctor `(Player, Game)`; `chooseSpellAbilityToPlay()` :1348; `useSimulation` branch :1359 |
| 4 | `ChangeZoneAi` (tutor targeting) | ✅ | `forge-ai/src/main/java/forge/ai/ability/ChangeZoneAi.java` |
| 5 | Simulation AI: `GameCopier`, `GameStateEvaluator`, `SpellAbilityPicker` | ✅ | package `forge.ai.simulation`; `GameCopier(Game)` :53; enabled per-player via `forge.ai.AIOption.USE_SIMULATION` passed to `LobbyPlayerAi` (maps to per-seat `simulation_ai` manifest flag) |
| 6 | `ComputerUtilMana` | ✅ | `payManaCost(Cost, Player, SpellAbility, boolean)` `ComputerUtilMana.java:68`; `canPayManaCost` overloads :53–61 |
| 7 | `RegisteredPlayer.forCommander(Deck)` | ✅ | `forge-game/.../player/RegisteredPlayer.java:134` — sets `deck.getCommanders()` + starting life 40 |
| 8 | `GameRules(GameType.Commander)` | ✅ | `forge-game/.../GameRules.java:28`; variant flag via `setAppliedVariants(EnumSet.of(GameType.Commander))` :111; `hasCommander()` :124 |
| 9 | `Match.playGame()` | ✅ as `startGame` | `forge-game/.../Match.java:76/80` `startGame(Game[, Runnable])` → `game.getAction().startGame(lastOutcome, hook)` :92; `createGame()` :72 |
| 10 | Subscribable game event bus | ✅ | Guava `EventBus` — `Game.java:94`; `subscribeToEvents(Object)` :1024; `fireEvent(Event)` :1021; **63** event classes in `forge-game/.../game/event/` |
| 11 | Controller injection point | ✅ | `forge-ai/.../LobbyPlayerAi.java:37` private `createControllerFor(Player)`; `createIngamePlayer(Game,int)` :49 calls `ai.setFirstController(...)`. Seam: subclass `LobbyPlayerAi`, override the factory — no upstream patch needed |
| 12 | Card DSL at `forge-gui/res/cardsfolder/` | ✅ | unpacked letter dirs `a/…z/`; e.g. `g/grizzly_bears.txt` (`Name:/ManaCost:/Types:/PT:/Oracle:`) |
| 13 | `.dck` section headers | ✅ | `forge-core/.../deck/io/DeckSerializer.java:93` `fromFile(File)`; `[metadata]` block (keys `Name`, `Comment`, `Tags`, `Deck Type` — `DeckFileHeader.java:37-49`); sections from `forge.deck.DeckSection` enum: `Main, Sideboard, Commander, Avatar, Planes, Schemes, Conspiracy, Dungeon, Attractions, Contraptions` |
| 14 | AI personality profiles `res/ai/*.ai` | ✅ | `forge-gui/res/ai/`: `Default.ai`, `Cautious.ai`, `Experimental.ai`, `Reckless.ai`; loaded by `forge.ai.AiProfileUtil` → `forge.ai.AiProps` |
| 15 | Scripted game-state loader (golden tests) | ✅ (moved, §2) | `GameState.parse(...)` :485–494 + `applyGameOnThread(Game)` :586; subclass `forge.gamemodes.puzzle.Puzzle` |
| 16 | Headless bootstrap | ✅ | `GuiBase.setInterface(new GuiDesktop())` (`Main.java:57`) then `FModel.initialize(null, null)` (`SimulateMatch.java:38`, `FModel.java:146`); card DB from `ForgeConstants.CARD_DATA_DIR` (`ForgeConstants.java:93`). No image loading in sim path |
| 17 | Outcome data | ✅ | `forge-game/.../GameOutcome.java`: `getWinningPlayer()` :166, `getWinCondition()` → `GameEndReason {AllOpponentsLost, Draw, WinsGameSpellEffect, AllHumansLost, AllOpposingTeamsLost}` :180, `getLastTurnNumber()` :184, `isDraw()` :123; per-player `PlayerStatistics` (openingHandSize, timesMulliganed, turnsPlayed, outcome); cmdr damage `Player.java:188`, 21-dmg loss check :2061 (`GameLossReason.CommanderDamage`) |

## 2. Corrections — update the plan's code sketches

1. **`chooseCardsToDiscardFrom` signature drift.** Now 6-arg: `chooseCardsToDiscardFrom(Player p, SpellAbility sa, CardCollection validCards, int min, int max, CardCollectionView visibleToChooser)` (`PlayerControllerAi.java:666`). The `ComboAwareController` override sketch in plan §6 must use this form.
2. **`GamePlayerUtil` FQCN.** It is `forge.player.GamePlayerUtil` at `forge-gui/src/main/java/forge/player/GamePlayerUtil.java` (not `forge.gamemodes.match...`). Canonical AI factory: `createAiPlayer(String name, int avatarIndex, int sleeveIndex, Set<AIOption> options, String profileOverride)` :69 — this is where per-seat profile + `USE_SIMULATION` are set.
3. **`GameState` lives in forge-game.** `forge.game.GameState` (`forge-game/src/main/java/forge/game/GameState.java`), not `forge.ai.GameState`. Golden-scenario harness should subclass it (as `forge.gamemodes.puzzle.Puzzle` does).
4. **Test framework is TestNG, not JUnit 5.** Existing sim-test infra: `forge-gui-desktop/src/test/java/forge/ai/simulation/` (`SimulationTest → AITest`), TestNG `@Test`/`@BeforeMethod`; bootstrap in `AITest.initializeModel()` (static-flag-guarded `GuiBase.setInterface(new GuiDesktop())` + `FModel.initialize(null, prefs -> …)`). Decision: plan §8 test names stay, but **forge-arena tests use TestNG** to reuse `AITest`-style bootstrap and match repo convention (revisit if forge-arena becomes a standalone Maven module with its own test stack).

## 3. Load-bearing findings beyond §1

- **No turn cap exists anywhere in the engine.** `GameRules` has only `simTimeout` (wall-clock seconds, default 120, `GameRules.java:20`), enforced *externally* by `SimulateMatch` via `TimeLimitedCodeBlock.runWithTimeout` (`SimulateMatch.java:181`), with `game.setGameOver(GameEndReason.Draw)` on expiry :193. Plan's `limits.turns` and `limits.priority_passes_per_turn` are **new arena-side code** — implement in `EngineFacade.playWithLimits` as an event-bus subscriber (turn events) + the same setGameOver(Draw) mechanism, recording the limiting factor.
- **Stock loop guards (relevant to combo shortcut design):** priority-loop counter breaks at 999 with "AI looped too much" (`PhaseHandler.java:1109-1112`); stack > 999 forces a draw (`MagicStack.java:262`); `RepeatEffect` self-breaks (`RepeatEffect.java:46-51`). There is **no repeated-board-state detector** — grind-out draws only happen via these counters, the wall clock, or card effects. Our loop-shortcut must engage *before* the 999 guards distort results (they end games as draws / log spam).
- **Simulation AI is OFF in stock CLI sim runs** — `createAiPlayer(name, i-1)` doesn't pass `AIOption.USE_SIMULATION`. Per-seat enablement = construct our own `LobbyPlayerAi` with the option set (or the 5-arg `createAiPlayer`).
- **`Main` CLI subcommands:** `sim`, `parse` (card-script parse sweep — useful for Gate 2 implementability checks), `server` (stub). `sim` requires the desktop module's `GuiDesktop` interface registration even though no GUI opens.
- **Draw semantics for timeouts:** wall-clock expiry produces `GameEndReason.Draw` — indistinguishable from on-board draws in `GameOutcome`. Arena's `timeout_draw` result with limiting-factor must be recorded harness-side (we know *why* we ended it), not derived from the outcome object.
- `-c <seconds>` flag sets `simTimeout` from the CLI (`SimulateMatch.java:134`) — usable for Phase 0 baseline before `EngineFacade` exists.

## 4. Provisional-name substitution table (for the plan doc)

| Plan sketch says | Source says |
|---|---|
| `Match.playGame()` | `Match.startGame(Game)` after `Match.createGame()` |
| `chooseCardsToDiscardFrom(p, sa, valid, min, max)` | + trailing `CardCollectionView visibleToChooser` |
| `forge.gamemodes.match.GamePlayerUtil` | `forge.player.GamePlayerUtil` (forge-gui) |
| `forge.ai.GameState` (golden states) | `forge.game.GameState` |
| JUnit 5 (§8) | TestNG (repo convention; reuse `AITest` bootstrap) |
| `GameRules` turn/priority limits | do not exist — arena-side in `EngineFacade.playWithLimits` |

## 4.5 Addendum (PR-1, 2026-07-15): RNG seeding — VERIFIED clean

`forge.util.MyRandom` (forge-core) is the single RNG seam: `getRandom()` / `setRandom(Random)` (`MyRandom.java:55/63`, setter documented "Used for deterministic simulation"). Audit of forge-game + forge-ai main sources: every `Collections.shuffle` call passes `MyRandom.getRandom()` (10+ sites incl. `Zone.java:262` library shuffle, `GameAction.java:2282/2412`), and there are **zero** `new Random()`, `ThreadLocalRandom`, or `Math.random` call sites. Seeding = `MyRandom.setRandom(new Random(seed))` per game (`ArenaBootstrap.seedRng`). Constraint: the seam is a global static ⇒ determinism requires **one game per JVM process** — satisfied by the worker-pool design. Default (unseeded) is `SecureRandom`.

## 5. Reference: old-project (mtg-deck-test) hook points — NOT carried forward

The v1 project modified 7 tracked forge-ai files directly (`AiController`, `AiAttackController`, `AiBlockController`, `ComputerUtil`, `ChangeZoneAi`, `SpellAbilityPicker`, `GameStateEvaluator`) plus an untracked `forge.ai.combo` package. v3 replaces all of this with the `ComboAwareController extends PlayerControllerAi` + `LobbyPlayerAi.createControllerFor` seam behind `EngineFacade`; the old checkout remains at `personal/mtg-deck-test/forge` as a behavioral reference only.
