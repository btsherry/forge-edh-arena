# MTG Comprehensive Rules Digest — Conversion Module

**Source:** *Magic: The Gathering Comprehensive Rules*, effective **June 19, 2026** (media.wizards.com/2026/downloads/MagicCompRules 20260619.txt). All rule numbers below were verified against that document.

**Scope:** This digest constrains the Forge EDH Arena **conversion module** — the logic that turns an assembled combo engine (e.g. a large/"infinite" floating mana pool, a repeatable damage sink, a draw loop) into an actual game win inside the Card-Forge rules engine. It does not restate rule text wholesale; each item explains the *operational* consequence for an AI acting through a rules engine.

> **Rule-number corrections vs. the module spec.** The June 2026 CR renumbered several sections. Where the design brief cited an old number, use the current one:
> - **Loops / shortcuts: `732`, not `727`.** In the current CR, `727` = "Restarting the Game" and `733` = "Handling Illegal Actions." "Taking Shortcuts" is **`732`**.
> - **Mana pool emptying: `500.5` (and `106.4`, `703.4q`), not `500.4`.** `500.4` is now "effects that last *until* a step/phase expire as it begins." The end-of-step/phase mana empty is **`500.5`**.
> - **Free first mulligan in multiplayer Commander: `103.5c` (Brawl: `903.12g`), not `903.9`.** `903.9` governs commanders returning to the command zone.
> - **Holding priority: `117.3c`** (reinforced by `601.2i` / `602.2b`). `405.6c` is actually "mana abilities resolve immediately," a related but distinct rule.

---

## 1. Priority and Timing (CR 117, 500s)

**What the rules say.**
- Priority is the system that decides who may act (`117.1`). The player with priority may cast spells, activate abilities, and take special actions.
- **Sorcery timing** is defined by `117.1a`: an *instant* may be cast any time you have priority; a *noninstant* (sorcery, creature, most X spells that are sorceries, planeswalkers, etc.) may be cast **only during your own main phase, while you have priority, and while the stack is empty**. `602.5d` extends this to activated abilities that read "Activate only as a sorcery."
- Activated abilities generally may be activated **any time you have priority** (`117.1b`); mana abilities are even freer (`117.1d` — see §3).
- The **active player receives priority** at the start of most steps/phases after turn-based actions and beginning-of-step triggers are handled (`117.3a`), and again after any spell/ability (other than a mana ability) resolves (`117.3b`).
- **No player ever receives priority during the untap step** (`502.4`) or, normally, during the cleanup step (`514.3`). During untap, nothing can be cast, activated, or resolved; triggers wait until upkeep. Cleanup gives priority only if an SBA fires or a trigger is waiting (`514.3a`), after which an extra cleanup step follows.
- A phase/step in which players get priority ends only when the stack is empty **and all players pass in succession** (`117.4`, `500.2`). Simply emptying the stack does not end it — every player gets a chance to add to the stack first.
- Turn-based and state-based actions are handled by the game, not by a player with priority; when steps/phases *end*, no player receives priority afterward (`117.2c`).
- Each time a player *would* receive priority, the game first performs all SBAs to a fixed point, then puts waiting triggers on the stack, then loops until stable, then hands out priority (`117.5`).

**What the conversion module must therefore do.**
- Model priority as the only legal action window. The state machine may only cast/activate when it holds priority; encode the two flavors: **instant-speed** (any priority window, incl. opponents' turns) vs. **sorcery-speed** (own main phase + empty stack, `117.1a`).
- **Do the conversion on the pilot's own main phase.** A main phase is a single phase with no sub-steps, so a floating pool survives across the whole main phase (see §3) and both sorcery- and instant-speed tools are legal there. Prefer the pre-combat or post-combat main phase; never attempt conversion during untap (impossible — `502.4`) or lean on cleanup.
- Never let the phase end mid-conversion: to keep acting, the pilot must **retain/regain priority** rather than pass with an empty stack (passing → `117.4` ends the phase and empties the pool). Concretely, keep the stack non-empty or reacquire priority via `117.3b`/`117.3c` before the "all pass" condition is met.
- On opponents' turns the pilot can still act at **instant speed** (`117.1b`, `117.1d`) — useful for holding up interaction or protecting a win, but any sorcery-speed payoff (most X spells) must wait for the pilot's own main phase.

---

## 2. The Stack and Resolution (CR 405, 608)

**What the rules say.**
- Spells and non-mana abilities go on the **stack** and resolve **last-in, first-out** (`405.2`, `405.5`, `608.1`). When all players pass in succession, only the top object resolves; then the game re-checks SBAs/triggers and re-offers priority.
- After you cast a spell or activate an ability, **you keep priority** (`117.3c`, reinforced by `601.2i` and `602.2b`). This is "holding priority" — you may add more to the stack before anyone can respond, or pass to let it resolve.
- A **triggered ability doesn't go on the stack the instant it triggers**; it is placed on the stack by its controller the next time a player *would* receive priority (`603.2`, `603.3`), on top of the stack. Only then can any player respond to it.
- When several abilities have triggered since the last priority, they go on the stack in **APNAP order** (active player's first, then each opponent in turn order), each controller choosing their own relative order (`405.3`, `603.3b`).
- At resolution, an ability with an intervening "if" re-checks its condition (`608.2a`, `603.4`); a spell/ability with targets re-checks legality and **is removed from the stack (countered by game rules) if *all* its targets are now illegal** (`608.2b`). Untargeted effects still resolve.
- Casting a spell "in response" means it resolves before the earlier object (`117.7`).

**What the conversion module must therefore do.**
- Sequence protection with LIFO in mind. To protect a payoff you are *casting* (e.g. a lethal X spell), remember you cannot respond to your own spell to shield it from a counter that hasn't been cast yet; instead hold up instant-speed answers and let opponents commit first, or make the payoff itself uncounterable/untargeted.
- To protect a **win trigger** ("you win the game" / lethal trigger): the trigger only reaches the stack at the next priority (`603.3`). Hold priority (`117.3c`) through the action that causes it, and when the trigger is on the stack and you receive priority, **cast protection in response** — it resolves first (LIFO), then the win trigger resolves. This is the natural home for a "respond to my own trigger" routine.
- Beware **intervening-if** wins (e.g. Felidar-Sovereign-style "if you have 40+ life, you win"): the condition is checked on the trigger *and again on resolution* (`603.4`). The module must protect the *condition* (life total, board state), not merely the trigger — an opponent flickering the condition in response removes the win with no counterspell.
- When injecting/queuing multiple triggers, honor APNAP + controller ordering (`603.3b`); don't assume a fixed global order.
- Treat "all targets illegal → fizzle" (`608.2b`) as a first-class failure mode: if the module distributes X damage across opponents and one opponent leaves in response (§4), re-validate targets before assuming the spell resolves.

---

## 3. Mana Abilities and the Mana Pool (CR 605, 106.4, 500.5)

**What the rules say.**
- **Mana abilities do not use the stack** and cannot be targeted, countered, or responded to; they **resolve immediately** upon activation (`605.3b`, `405.6c`; triggered mana abilities: `605.4a`). An ability is a mana ability only if it has no target and could add mana (`605.1a`/`605.1b`).
- A mana ability may be activated **whenever you have priority, and also mid-cast/mid-resolution whenever a cost or effect asks for a mana payment** (`117.1d`, `605.3a`, `601.2g`).
- Added mana goes to the player's **mana pool** and stays there as unspent mana until used (`106.4`).
- **The pool empties at the end of each step and each phase** (`106.4`; the actual emptying is a turn-based action, `500.5`, cross-referenced by `703.4q`). Passing priority does **not** empty the pool — only a step/phase boundary does.

**What the conversion module must therefore do.**
- **Treat the injected 1000-mana pool as phase-local.** Every pool-funded cast/activation must complete **within the same step or phase in which the pool was created** (`500.5`, `106.4`). If the pool is created during, say, the upkeep step, it vanishes at end of upkeep; create it and spend it in the **main phase** so it survives the entire phase.
- Within that phase, the pool **persists across multiple spells, resolutions, and priority passes** — as long as the phase itself does not end. So the module can: cast X spell → let it resolve (it regains priority, `117.3b`) → cast another → activate a sink repeatedly, all off one pool, provided it never lets "all players pass, stack empty" occur (which would end the phase and dump the pool, `500.2`/`500.5`).
- If the engine models mana as truly floating, prefer to **generate exactly what is needed and spend it immediately** (mana abilities resolve instantly, `605.3b`), rather than pre-floating a giant pool that a phase boundary could waste. If pre-floating, gate every subsequent action with a "still in the originating phase?" check.
- Mana abilities are safe from interaction (`605.3b`) — the module never needs to protect the mana step itself, only the payoff on the stack.

---

## 4. State-Based Actions and Winning / Losing (CR 704, 104, 800.4)

**What the rules say.**
- SBAs are checked **every time a player would get priority** (and once at the start of cleanup), performed simultaneously and repeatedly until none remain, *before* triggers go on the stack and before anyone actually gets priority (`704.3`, `117.5`). SBAs **do not use the stack** and ignore what happens mid-resolution (`704.1`, `704.4`).
- Loss/win SBAs (`704.5`): **0 or less life** → that player loses (`704.5a`); **attempted to draw from an empty library** since the last check → loses (`704.5b`); **10+ poison counters** → loses (`704.5c`). Tokens in the wrong zone cease to exist (`704.5d`); a copy of a spell off the stack ceases to exist (`704.5e`). Lethal marked damage destroys a creature as an SBA (`704.5g`, and damage never destroys directly — `120.5`).
- "Wins the game" effects: you win immediately if all opponents have left (`104.2a`, overrides effects that would stop you); an effect may state a player wins (`104.2b`); **if a player would both win and lose simultaneously, they lose** (`104.3f`). The life-0, empty-draw, poison, and Commander-damage losses are all delayed to "the next time a player would receive priority" (`104.3b–d`, `104.3j`).
- **Commander damage:** 21+ combat damage from a single commander → that player loses, as an SBA (`903.10a`, `104.3j`).
- **When a player leaves the game (`800.4a`):** all objects they own leave immediately; control effects they granted end; their non-card objects on the stack cease to exist; any objects still under their control are exiled. **This is NOT an SBA — it happens immediately** when they leave. Tokens created under the leaver revert/leave per ownership (`800.4a` examples), control reverts (`800.4b–c`), and their queued triggers/tokens aren't created (`800.4d`).

**What the conversion module must therefore do.**
- Understand that a kill only *registers* at the next SBA check (`704.3`), which is the next time a player would get priority — the loop's own priority passes are the checkpoints. Do not assume an opponent is "dead" until an SBA check has run.
- **Re-evaluate after every elimination.** When one opponent's death causes them to leave (`800.4a`), the board changes *immediately and mid-loop*: their permanents vanish/exile, control effects end, and a distributed-damage or "each opponent" payoff now has fewer legal targets/players. Re-derive the opponent set, re-target (`608.2b`), and recompute APNAP order (`101.4`) before the next iteration.
- **Check for the auto-win after each elimination:** the moment the *last* opponent has left, the pilot wins (`104.2a`) — the module should short-circuit and stop looping rather than continue and risk a self-loss.
- **Never self-destruct into a simultaneous win/loss** (`104.3f`): if a plan both wins and would deck/burn the pilot in the same SBA check, the pilot loses. Bound self-damage and self-mill so the pilot's own life stays ≥1 and its library stays ≥1 at every SBA checkpoint (see §10).
- Prefer robust wins (life to 0 via damage, poison to 10, "you win" effects) and know each resolves/loses only at the next priority — the module gets a window to protect the game state in between.

---

## 5. Loops and Shortcuts (CR 732)

**What the rules say.**
- Real Magic uses **shortcuts** to compress repeated actions (`732.1`). When a set of actions could repeat indefinitely, the shortcut rules decide how many times they repeat and how the loop breaks (`732.1b`).
- A player with priority may propose a sequence — "a loop that repeats a specified number of times" — that is legal from the current state with **predictable results**. It **may not contain conditional actions** (where a game event's outcome determines the next action) and must **end at a point where a player has priority** (`732.2a`). Other players may accept or shorten it (`732.2b–c`).
- A loop of **only mandatory actions is a draw** (`104.4b`, `732.4`); loops containing an optional action are not (the controller must eventually choose to stop). No player can be forced to take an out-of-loop action to end a loop (`732.5`), and "[A] unless [B]" loops don't force [B] (`732.6`).

**What the conversion module must therefore do.**
- Model conversion as an **engine-faithful bounded compression**, mirroring `732.2a`: compute a fixed iteration count up front (e.g. "activate this sink N times" where N is derived from the mana pool and lethal needed), then execute N deterministic iterations — never an unbounded `while(true)`.
- The loop body must be **non-conditional and predictable**: resolve each iteration to completion (SBA/trigger checks included) so the state is well-defined at each priority checkpoint, exactly as `732.2a` requires the sequence to be legal "based on the current game state and predictable results."
- Guarantee termination: the loop must include an **optional stopping action controlled by the pilot** (a "may," or the pilot's own choice to stop), so it is not a mandatory-loop draw (`104.4b`/`732.4`). The module's kill count is that stopping point.
- Insert a **re-evaluation / win-check between iterations** (per §4): compression must not blow past the point where the pilot has already won or would deck itself.

---

## 6. X Spells and Activated Abilities (CR 107.3, 601, 602)

**What the rules say.**
- **X in a cost is chosen and announced by the caster as part of casting/activating** (`107.3a`, during proposal `601.2b`). While the spell/ability is on the stack, X equals that announced value (`107.3a`). Outside the stack, X is treated as 0 (`107.3g`, `107.3h`).
- Casting sequence (`601.2`): move to stack (`601.2a`) → announce modes, alternative/additional costs, and **X** (`601.2b`) → choose targets/division (`601.2c–d`) → determine total cost, then **lock it in** (`601.2f`) → **activate mana abilities to pay** (`601.2g`) → **pay the total cost; partial payments are not allowed, unpayable costs can't be paid** (`601.2h`) → spell becomes cast, cast-triggers trigger, **caster keeps priority if they had it** (`601.2i`).
- Activating an ability follows the identical process (`602.2`, `602.2b`): put ability on the stack, announce X, pay activation cost from the pool.
- Default activation speed is **any time you have priority** (`117.1b`) unless the ability says otherwise. Restrictions persist across control changes (`602.5b`); "Activate only as a sorcery/instant" (`602.5d`/`602.5e`) impose casting-timing; a creature's `{T}`/`{Q}` ability needs summoning-sickness clearance unless it has haste (`602.5a`).
- Once-per-turn riders exist as "Activate only once each turn" (`602.5b`) and, on triggers, "Do this only once each turn" (`603.2h`).

**What the conversion module must therefore do.**
- **Price X against the floating pool:** at cast time, set X = min(available pool after other costs, X needed for lethal/effect), respecting that the cost is *locked in* at `601.2f` before payment and that **no partial payment** is allowed (`601.2h`) — the pool must actually cover the announced X or the cast is illegal and reversed (§ Handling Illegal Actions, `733.1`).
- Sequence repeated sink activations within one phase: each activation is a full `602.2` cycle drawing from the same phase-local pool (§3). Between activations the ability resolves and the pilot regains priority (`117.3b`), so the module can chain many activations off one pool as long as the phase doesn't end.
- **Enforce once-per-turn riders** (`602.5b`, `603.2h`): a sink capped at once per turn cannot be the loop engine — the module needs either a genuinely repeatable sink or enough distinct sinks. Also enforce sorcery-only activation timing (`602.5d`) and summoning sickness (`602.5a`).
- Announce X and every choice at the moment the rules demand (X at proposal, `601.2b`) so the engine's cost/target validation matches CR ordering.

---

## 7. Triggered Abilities and "May" (CR 603)

**What the rules say.**
- A trigger fires automatically when its event occurs but **does nothing at that moment**; it is put on the stack by its controller at the next priority (`603.2`, `603.3`). Triggers can fire even when it's illegal to cast/activate (`603.2a`).
- **Optional ("may") triggers still go on the stack; the choice is made on resolution, not when it triggers** (`603.5`). Same for "unless" clauses.
- **Intervening "if"** conditions are checked twice — when the trigger would fire, and again on resolution; failing either does nothing (`603.4`, `608.2a`).
- Modal/targeting choices for a trigger are made **as it's put on the stack** (`603.3c–d`); if no legal choice exists, it's removed.

**What the conversion module must therefore do.**
- Map the decision points to the engine's `pendingChoice` seam by *when* the CR asks for them:
  - **At resolution (pendingChoice):** whether to use a "may" (`603.5`), untargeted choices/divisions announced while applying the effect (`608.2d`), and any "unless" decision.
  - **When the trigger goes on the stack (not resolution):** its mode and targets (`603.3c–d`) — the module must supply these earlier, alongside the same seam used for casting choices (`601.2c–d`).
- For win payoffs built on intervening-if (`603.4`): verify the condition holds *both* at trigger time and at resolution; guard the condition against opponent interaction in the window between (see §2).
- Don't rely on a trigger acting "instantly" — it always waits for the next priority (`603.3`), giving opponents a response window the module must account for.

---

## 8. Copies and Tokens (CR 707, 111)

**What the rules say.**
- A copy takes the **copiable values** of the original — the printed characteristics (name, mana cost, color indicator, types, rules text, P/T/loyalty), plus, **for a spell on the stack, the choices made when casting it** (mode, targets, value of X, kicked, division) (`707.2`). Status, counters, stickers, and non-copy continuous effects are **not** copied.
- A **copy of a spell** exists only on the stack; off the stack it ceases to exist as an SBA (`707.10a`, `704.5e`). Effects that copy a spell may let the controller choose **new legal targets** (`707.10c`); a copied permanent spell becomes a **token** on resolution (`707.10f`).
- **Tokens:** their characteristics are exactly those defined by the creating effect (`111.3`); a token isn't created at all if a characteristic can't enter, or if it would copy an instant/sorcery (`111.5`). A token in any zone other than the battlefield **ceases to exist as an SBA** (`111.7`, `704.5d`), and once it has left the battlefield it can't return (`111.8`). Note relevant leaves-the-zone triggers fire *before* it ceases to exist (`111.7`).
- "Cast the copy" cards (Isochron-Scepter-class): the card *creates* a copy and grants permission to cast it; the copy on the stack carries the copiable values and its own new choices, and casting it follows the normal `601` process.

**What the conversion module must therefore do.**
- If the engine injects a copy of a spell for a payoff loop, the injected object must **mirror copiable-value rules** (`707.2`): same characteristics and the original's cast-time choices, *except* re-choose targets where the effect allows/requires (`707.10c`) — and it must live **only on the stack**, expiring via SBA if it ever leaves (`707.10a`).
- Validate injected **tokens** against `111.3`/`111.5`: don't fabricate characteristics the creating effect didn't grant, don't create a token that can't legally exist, and treat any token that leaves the battlefield as gone (`111.7`/`111.8`) — never reuse it.
- For "cast the copy" engines used as damage sinks, route the copy through the standard casting/priority/stack path (`601`, §2), including X announcement (`107.3a`) if the copied spell has X (X is copied from the original per `707.2`, but a freshly *created* copy that lets you choose X follows the card's wording).

---

## 9. Mulligans in Multiplayer Commander (CR 103.5, 903)

**What the rules say.**
- A Commander **pod of 3+ players** is a multiplayer game (`100.1b` — a game that *begins* with more than two players; 1v1 Commander is NOT multiplayer). Starting hand size is 7 (`103.5`/`903.7`) and starting life 40 (`103.4c`). The mulligan is the **London mulligan** (`103.5`): to mulligan, shuffle hand into library, draw a new 7, then **put on the bottom of the library a number of cards equal to the number of mulligans taken so far**. Declarations are made in turn order, then all mulligans happen simultaneously; you may mulligan down to a 0-card hand (`103.5`).
- **In a multiplayer game (including Commander), the *first* mulligan is free** — it doesn't count toward the number of cards bottomed or the number of mulligans taken; subsequent mulligans count normally (`103.5c`). (Brawl: same free-first rule, `903.12g`.)

**What the conversion module (pilot mulligan logic) must therefore do.**
- Use the exact bottoming arithmetic — **in a 3+ player pod**: after keeping following *m* total mulligans, **cards to bottom = max(0, m − 1)** because the first mulligan is free (`103.5c`). So: keep after 0 mulls → bottom 0; after 1 → bottom 0 (free); after 2 → bottom 1; etc. **In 1v1 Commander there is no free mulligan: cards to bottom = m.** Final hand size is always 7 minus cards bottomed.
- Draw 7 each iteration regardless (`103.5`); the free-first adjustment applies only to the *bottoming/count*, not the draw.
- The pilot may keep aggressively (it can mulligan to 0), but the free first mulligan means a single mulligan to find combo pieces is costless — factor that into keep/mull heuristics.

---

## 10. Replacement Effects Relevant to Wins (CR 614, 121, 104, 704)

**What the rules say.**
- A **replacement effect** watches for an event and replaces it before it happens (`614.1`); "instead" and "skip" wordings are the tells (`614.1a–b`). It must exist *before* the event (`614.4`) and applies **once per event** (`614.5`).
- **Empty-library draw** is a *loss* only because of the SBA: attempting to draw from an empty library makes you lose at the next priority (`121.4`, `704.5b`). But an effect that **replaces the draw** applies even when the library is empty (`121.6`, `121.6a`) — so a **Laboratory-Maniac / Jace-Wielder-of-Mysteries-class replacement** ("if you would draw from an empty library, you win instead") replaces the *would-draw* event, meaning the "attempt to draw from empty library" never occurs and `704.5b`/`121.4` never triggers. The win comes from `104.2b`.
- Moving cards to hand *without the word "draw"* is not a draw (`121.5`), and can't trigger draw-replacements.
- `104.3f`: simultaneous win-and-lose → the player **loses** (so an unprotected self-mill that both decks you and would win kills you).

**What the conversion module must therefore do.**
- When **digging with a huge pool** (repeated draw to find/assemble), treat the library count as a hard resource: each individual draw is separate (`121.2`), and **the draw that empties-then-draws-again loses the game** (`121.4`/`704.5b`). Bound draw loops so the library never hits the empty-draw condition **unless** a draw-replacement win is already in place.
- If a Lab-Man-class replacement is on the battlefield, the module may intentionally draw from an empty library to **win via the replacement** (`614.1a`, `121.6a`, `104.2b`) — but must confirm the replacement is active *before* the draw (`614.4`) and that the pilot isn't simultaneously losing by another SBA (`104.3f`).
- Distinguish "draw" from "put into hand"/"mill" (`121.5`) when deciding whether a dig tool risks the empty-library loss or interacts with draw-replacement wins.

---

## CONVERSION MODULE — LEGAL CONSTRAINTS CHECKLIST

1. **Pool is phase-local.** Every pool-funded cast/activation must complete within the same step/phase the pool was created in; the pool empties at each step/phase boundary. Create and spend it in a **main phase**. (`500.5`, `106.4`, `703.4q`)
2. **Passing priority does not empty the pool — ending the phase does.** To keep spending, retain/regain priority; never allow "all players pass with an empty stack," which ends the phase (and dumps the pool). (`117.4`, `500.2`, `500.5`)
3. **Sorcery-speed payoffs require own main phase + empty stack + priority.** Gate X-sorceries and "activate only as a sorcery" abilities accordingly; instant-speed tools may act in any priority window. (`117.1a`, `602.5d`)
4. **No action during untap; don't rely on cleanup.** No priority in the untap step; cleanup grants priority only via a pending SBA/trigger. (`502.4`, `514.3`/`514.3a`)
5. **Mana abilities can't be responded to and resolve immediately** — safe to generate mana mid-cast to pay costs. (`605.3b`, `117.1d`, `601.2g`)
6. **Announce X at cast/activation; cost locks in before payment; no partial payment.** Set X to what the pool can actually pay. (`107.3a`, `601.2b`, `601.2f`, `601.2h`)
7. **Enforce activation restrictions:** once-per-turn (`602.5b`), "do this only once each turn" (`603.2h`), summoning sickness for `{T}` abilities (`602.5a`) — a capped sink cannot be the loop engine.
8. **Triggers reach the stack only at the next priority; "may" is decided on resolution.** Route resolution-time choices to the `pendingChoice` seam; supply trigger targets/modes when it's put on the stack. (`603.3`, `603.5`, `603.3c–d`, `608.2d`)
9. **Protect win triggers in the response window; protect the *condition* for intervening-if wins.** Hold priority, then answer in response before the win resolves; guard the life/board condition rechecked at resolution. (`117.3c`, `603.4`, `608.2b`)
10. **Bound the loop to a fixed iteration count with a pilot-controlled stop.** No unbounded loops; a mandatory-only loop is a draw. Model conversion as an engine-faithful compression. (`732.2a`, `732.4`, `104.4b`)
11. **Re-evaluate the board after every opponent elimination — immediately, not as an SBA.** Their permanents leave/exile, control effects end, targets and APNAP order change. (`800.4a`, `608.2b`, `101.4`)
12. **Check for the auto-win after each elimination and stop.** Winning is automatic once all opponents have left; don't keep looping into a self-loss. (`104.2a`)
13. **Never win-and-lose simultaneously.** Keep the pilot's life ≥1 and library ≥1 at every SBA checkpoint unless a draw-replacement win is already active. (`104.3f`, `704.5a–b`)
14. **Empty-library draw loses at the next priority — unless a Lab-Man-class replacement is in play first.** Bound digging; the replacement must predate the draw. (`121.4`, `704.5b`, `614.4`, `121.6a`, `104.2b`)
15. **Injected copies/tokens must mirror copiable-value and existence rules.** Copies of spells live only on the stack (else cease to exist); tokens off the battlefield cease to exist and can't return; don't fabricate characteristics the creating effect didn't grant. (`707.2`, `707.10a`/`704.5e`, `111.3`/`111.5`, `111.7`/`111.8`/`704.5d`)
16. **Illegal actions are fully reversed by the engine — validate before committing.** An unpayable/illegal cast rewinds to before it began; design the module to pre-check legality (targets, cost payability) rather than rely on rollback. (`733.1`, `608.2b`)
17. **SBAs are the checkpoints:** checked each time a player would get priority (and once at cleanup start), to a fixed point, before triggers and before priority. Losses (life-0, empty-draw, poison, 21 commander damage) register there, delayed to the next priority. (`704.3`, `117.5`, `104.3b–d`, `104.3j`/`903.10a`)
18. **Commander mulligan arithmetic:** draw 7 each mulligan; in a 3+ player pod, cards bottomed = max(0, total mulligans − 1) (first multiplayer mulligan free); in 1v1, cards bottomed = total mulligans; may mulligan to 0. (`103.5`, `103.5c`)
