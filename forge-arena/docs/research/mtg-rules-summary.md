# MTG Rules Summary — General Game-Pilot Digest

**Primary source:** *Magic: The Gathering Comprehensive Rules* (CR), effective **June 19, 2026** (media.wizards.com/2026/downloads/MagicCompRules 20260619.txt). Every rule number below was verified directly against a downloaded copy of that document — the same edition the companion conversion digest was verified against. Secondary navigation aids: Yawgatog's hyperlinked CR (yawgatog.com/resources/magic-rules/) and RulesGuru's CR primer (rulesguru.org).

**Scope:** This is the *general* companion to `mtg-rules-digest-conversion.md`, which covers combo-conversion specifics (loops/shortcuts, X spells, floating-pool management, win/loss SBAs in depth, mulligans, Lab-Man-class replacements). This document covers the rest of the rules surface an AI pilot needs to sequence legal actions across an ordinary game of Commander: turn structure, priority, the stack, combat, replacement effects, Commander-format rules, and a keyword glossary. Where the two documents overlap, the conversion digest is the deeper treatment; rule numbers are consistent between them.

**Audience:** a program's decision logic, not a human learner. Each section leads with what the rule *permits or forbids* in action sequencing.

---

## 1. Turn Structure (CR 500–514)

A turn is exactly **five phases in fixed order**: beginning, precombat main, combat, postcombat main, ending (`500.1`). Three of them decompose into steps:

| Phase | Steps | Pilot gets priority? |
|---|---|---|
| Beginning | untap → upkeep → draw (`501.1`) | **Never during untap** (`502.4`); yes in upkeep and draw |
| Precombat main | (no steps) | Yes |
| Combat | beginning of combat → declare attackers → declare blockers → combat damage → end of combat (`506.1`) | Yes, in each step after its turn-based action |
| Postcombat main | (no steps) | Yes |
| Ending | end step → cleanup (`512.1`) | Yes in end step; **normally not in cleanup** (`514.3`) |

Sequencing constraints the pilot must encode:

- **Untap is a dead window.** No player receives priority during the untap step (`502.4`); nothing can be cast or activated there, and abilities that trigger during it wait until the upkeep.
- **Cleanup is almost dead.** During cleanup the active player discards to hand size, then damage is removed and "until end of turn" effects end. Players get priority in cleanup only if a state-based action is performed or a trigger is waiting (`514.3a`), and then an extra cleanup step follows.
- **Every phase/step that grants priority ends only when all players pass in succession on an empty stack** (`117.4`, `500.2`). The pilot passing does not end the phase by itself; every player must pass.
- The two main phases are the only windows for sorcery-speed action (see §3). They contain no sub-steps, so floating mana survives across the whole phase (see §5).
- **First-turn draw:** in a two-player game the starting player skips their first draw step (`103.8a`), but **in multiplayer games — including a normal Commander pod — no player skips their first draw** (`103.8c`).
- The declare blockers and combat damage steps are **skipped entirely** if no attackers were declared (`508.8`, via `506.1`), so "at end of combat"-gated plans must not assume those steps exist.

## 2. Priority and the Stack (CR 117, 405, 601–603, 608)

**Priority is the only legal action window.** A player may cast spells, activate abilities, and take special actions only when they have priority (`117.1`). The engine hands the active player priority at the start of most steps and phases after turn-based actions and any beginning-of-step triggers are dealt with (`117.3a`), and again after each spell or ability resolves (`117.3b`).

**The stack is strictly LIFO** (`405.2`): each new spell or non-mana ability goes on top, and when all players pass in succession, only the **top** object resolves (`608.1`, `117.4`). After it resolves, SBAs are checked, waiting triggers are stacked, and priority is offered again — objects lower on the stack do not resolve until everyone passes again. Practical consequences:

- "Casting in response" means resolving **first** (`117.7`). To beat an opponent's spell, the answer goes on the stack *after* it.
- After you cast a spell or activate an ability, **you retain priority** (`117.3c`, `601.2i`, `602.2b`). The pilot can stack multiple objects before any opponent may respond — the standard way to protect a combo piece or win trigger.
- A player who passes priority without acting can act again only after something else happens (another player acts, or an object resolves).

**Triggered abilities do not act instantly.** A trigger fires when its event occurs but is placed on the stack only the next time a player *would* receive priority (`603.2`, `603.3`) — so every trigger inherently offers opponents a response window before it resolves. Multiple simultaneous triggers stack in **APNAP order** — Active Player's first, then each Nonactive Player in turn order — with each controller ordering their own (`101.4`, `603.3b`). Because the stack is LIFO, the *last* player's triggers resolve *first*.

**Resolution checks:** a spell or ability with targets re-checks target legality when it starts resolving; if **all** its targets are illegal, it is removed from the stack and does nothing ("fizzles," `608.2b`). An intervening "if" trigger re-checks its condition at resolution (`603.4`, `608.2a`). The pilot must re-validate targets after any board change before assuming a queued object will resolve.

**State-based actions are checked every time any player would receive priority** (`704.3`), to a fixed point, *before* triggers are stacked and before priority is actually granted (`117.5`). SBAs use no stack and cannot be responded to (see §6).

## 3. Instants vs. Sorceries — Timing Classes (CR 117.1, 307, 304, 602.5)

The rules define exactly two speed classes, and every action falls into one:

- **Instant speed** (`117.1b`, `304.1`): instants — and by default all activated abilities — may be cast/activated **any time their controller has priority**, including during opponents' turns and in response to anything on the stack.
- **Sorcery speed** (`117.1a`, `307.1`): sorceries, creatures, artifacts, enchantments, planeswalkers, battles — any non-instant spell — may be cast only **(a)** during that player's **own main phase**, **(b)** while the **stack is empty**, and **(c)** while they hold priority. All three conditions are conjunctive.

Modifiers to encode:

- **Flash** (`702.8a`) promotes a card to instant timing: "you may play this card any time you could cast an instant."
- **"Activate only as a sorcery"** (`602.5d`) demotes an activated ability to sorcery timing; "activate only once each turn" (`602.5b`) caps repetition. Activation restrictions survive control changes (`602.5b`).
- **Summoning sickness** (`302.6`, `602.5a`): a creature can't attack, or use activated abilities with `{T}`/`{Q}` in their cost, unless its controller has controlled it continuously since their most recent turn began — or it has haste.
- **Playing a land** is a special action, not a spell: once per turn, own turn, stack empty, sorcery timing (`116.2a`, `305.1`–`305.2`); it uses no stack and cannot be responded to.

A legal-action generator should therefore compute, at each priority window: (is it my main phase? is the stack empty?) → sorcery-speed set available; (do I hold priority at all?) → instant-speed set available; then subtract per-object restrictions.

## 4. Split Second — the No-Response Flag (CR 702.61)

**Split second must be a first-class flag in the executor**, because it deletes almost the entire response space:

> `702.61a` — "Split second" means "As long as this spell is on the stack, players can't cast other spells or activate abilities that aren't mana abilities."

While a split second spell (e.g. *Krosan Grip*, *Sudden Spoiling*, *Angel's Grace* — but detect the keyword from card data, never from a memorized list) is on the stack:

- **Forbidden:** casting any spell; activating any non-mana ability. This applies to *every* player, including the split second spell's controller. Counterspells, sacrifice outlets, flicker effects — all illegal until it leaves the stack.
- **Still legal** (`702.61b`): activating **mana abilities**, and taking **special actions** (e.g. turning a face-down creature face up via its morph cost — the classic judge-exam response to split second).
- **Triggered abilities still trigger and are put on the stack as normal** (`702.61b`). Split second does not stop triggers — a permanent whose ability triggers off the split second spell being cast will still get its trigger, and that trigger can end up resolving before the split second spell only if it was put on the stack above it.

Executor rule: when the top-of-stack scan finds any object with split second anywhere on the stack, prune the action set to {mana abilities, special actions, pass priority}. Do not offer or expect responses; a plan whose protection line depends on responding to a split second removal spell is dead on arrival.

## 5. Mana Abilities and the Mana Pool (CR 605, 106.4, 500.5)

- **Mana abilities never use the stack.** An activated mana ability resolves immediately upon activation and can't be targeted, countered, or responded to (`605.3b`, `405.6c`). An ability is a mana ability only if it has no target and could add mana (`605.1a–b`).
- They may be activated whenever their controller has priority, **and also mid-cast or mid-resolution** whenever a cost or effect asks for a mana payment (`117.1d`, `605.3a`, `601.2g`) — mana generation can be interleaved inside the casting process itself.
- Added mana sits in the controller's **mana pool** as unspent mana (`106.4`).
- **"Mana empties as steps and phases end"**: each player's mana pool empties at the end of **each step and each phase** (`106.4`); the emptying is a turn-based action performed as the step/phase ends (`500.5`, `703.4q`). Passing priority does *not* empty the pool — only a step/phase boundary does. Corollary: mana floated in a main phase survives the entire phase (no sub-steps), while mana floated in the upkeep dies at end of upkeep. (Full floating-pool discipline: conversion digest §3.)

## 6. State-Based Actions (CR 704)

SBAs are the game's automatic bookkeeping: checked every time a player would receive priority (and at the start of cleanup), performed **simultaneously, repeatedly until stable**, before triggers stack and before priority is granted (`704.3`, `704.4`, `117.5`). No player controls them; nothing can respond to them. The pilot never "does" an SBA — it *predicts* them. The load-bearing list (`704.5`):

- **`704.5a`** Player at 0 or less life loses.
- **`704.5b`** Player who attempted to draw from an empty library since the last check loses.
- **`704.5c`** Player with 10+ poison counters loses.
- **`704.5d`** A token in any zone other than the battlefield ceases to exist.
- **`704.5e`** A copy of a spell anywhere but the stack ceases to exist.
- **`704.5f`** Creature with toughness ≤ 0 → owner's graveyard (regeneration cannot save it).
- **`704.5g`** Creature with marked damage ≥ toughness is destroyed (lethal damage). Damage never destroys directly — only this SBA does (`120.5`).
- **`704.5h`** Creature dealt any damage by a **deathtouch** source since the last check is destroyed.
- **`704.5i`** Planeswalker with 0 loyalty → graveyard.
- **`704.5j`** **The legend rule** — see §7.
- **`704.5m/n`** Illegally attached Auras go to the graveyard; illegally attached Equipment just unattaches.
- Commander addition: **`903.10a`** — 21+ combat damage from the same commander → that player loses (see §8).

Timing consequence: nothing "dies" mid-resolution. A creature at lethal damage stays on the battlefield until the resolving effect finishes and the next SBA check runs. Kill confirmation, legend-rule cleanup, and token evaporation all land at the next would-receive-priority checkpoint — the pilot's simulation must apply SBAs to a fixed point at exactly those checkpoints and nowhere else.

## 7. Replacement Effects and the Legend Rule (CR 614, 616, 704.5j)

**Replacement effects** (`614.1`) watch for an event and replace it with a different event before it happens — the tells are "instead" (`614.1a`), "skip" (`614.1b`), and "enters with / as [this] enters" (`614.1c–d`). They are not triggered abilities: they use no stack, offer no response window, and must exist **before** the event occurs. Each replacement effect gets **one** application per event (`614.5` — with a Commander-specific exception noted in §8).

**Ordering when multiple apply (`616.1`)** — the rule the pilot must get right because it is a *choice point*:

> If two or more replacement and/or prevention effects would modify how an event affects an object or player, **the affected object's controller (or its owner if it has no controller) or the affected player chooses one to apply** — not the effects' controllers, not APNAP.

Then the process repeats with the remaining still-applicable effects until none apply (`616.1f`). Mandatory picks come first in a fixed order: self-replacement effects must be chosen before others (`616.1a`), then control-changing enters-effects (`616.1b`), then copy-as-enters effects (`616.1c`), then back-face-up effects (`616.1d`); after those, free choice (`616.1e`). If several players must choose simultaneously, the choices are made in APNAP order (`616.1`). For the decision engine this is an owned decision node: when the pilot is the affected player, ordering replacements is a real lever (classic example: choosing whether a damage-doubler or a damage-preventer applies first).

**The legend rule (`704.5j`)** is an SBA: if a **single player** controls two or more **legendary** permanents **with the same name**, that player chooses one to keep and puts the rest into their owners' graveyards. Constraints worth encoding: it is per-player (two different players may each keep their own *Krenko*); it is name-based, not card-based; the controller chooses the survivor (keep the one with counters/auras/modifications); the death happens as an SBA, so "dies" triggers fire, but there is no response window between the second copy entering and the SBA check. Planeswalkers use this same rule — the old planeswalker uniqueness rule is gone (`306.4`).

## 8. Commander-Specific Rules (CR 903)

- **Deck construction** (`903.5`): exactly 100 cards including the commander (`903.5a`); singleton except basic lands (`903.5b`); no sideboards (`903.5e`).
- **Color identity** (`903.4`): the commander's color identity — all mana symbols in its cost **and rules text**, plus color indicators and characteristic-defining abilities — bounds the deck: every card's color identity must be a subset (`903.5c`). Even lands are constrained: a card with a basic land type is legal only if each color of mana it could produce is in the identity (`903.5d`). Back faces of double-faced cards count (`903.4d`); reminder text does not (`903.4c`).
- **Start of game** (`903.6`, `903.7`): commander begins face up in the **command zone**; each player starts at **40 life** with a 7-card hand. In a multiplayer pod the **first mulligan is free** (`103.5c`; details in the conversion digest §9).
- **Casting from the command zone & commander tax** (`903.8`): a player may cast their commander from the command zone; it costs an additional **{2} for each previous time they cast it from the command zone** this game. The tax keys off *casts from the command zone*, not deaths — track a per-commander cast counter, and note the tax is an additional cost (reducible by cost reducers, and it compounds: 3rd cast from the zone = +{4}).
- **Zone-return options** (`903.9`): if a commander was put into the graveyard or exile **since the last state-based-action check**, its owner **may** move it to the command zone as that check runs (`903.9a`) — a **one-shot choice at arrival**, not a standing option at later checks; declining it means the commander stays there (sometimes correct — reanimation). If a commander would go to its owner's **hand or library**, its owner may put it in the command zone **instead** — a replacement effect that, uniquely, can apply more than once to the same event (`903.9b`, explicit exception to `614.5`).
- **Commander damage** (`903.10a`): a player dealt **21 or more combat damage by the same commander** over the game loses, as an SBA. Per-commander, per-victim tracking; only **combat** damage counts; the count survives the commander changing zones or control. The pilot must maintain a matrix `damage[commander][player]` and treat 21 as a parallel lethal threshold alongside life and poison.

## 9. Combat Sequencing (CR 506–511)

Combat is five steps (`506.1`); each step's turn-based action happens first (no stack, no responses to the action itself), then players get priority.

1. **Beginning of combat** (`507`): in multiplayer, the active player chooses the defending player as a turn-based action (`507.1`, `506.2a`). Then priority — the last clean window to remove a would-be attacker before attacks are declared.
2. **Declare attackers** (`508.1`): the active player declares all attackers **at once** as a turn-based action: chosen creatures must be untapped and free of summoning sickness (`508.1a`); attacking **taps** them — tapping is not a cost (`508.1f`) — vigilance skips the tap; restrictions and requirements ("can't attack", "attacks each combat if able") are validated as a whole, and an illegal declaration rewinds entirely (`508.1c–d`, `733`). Then priority: this is where opponents respond *knowing the attack but before blocks*.
3. **Declare blockers** (`509.1`): the defending player declares all blocks at once; evasion (flying/menace/protection/etc.) and blocking restrictions are checked here. Once a creature is blocked, killing the blocker afterward does **not** make the attacker unblocked — it just assigns no damage unless it has trample (`510.1c`, `702.19d`). Then priority: the window for combat tricks with full information about blocks.
4. **Combat damage** (`510`): damage assignment is a turn-based action — the active player assigns each attacker's damage, then the defender assigns each blocker's (`510.1`); then **all combat damage is dealt simultaneously with no priority window between assignment and dealing** (`510.2`). Assignment rules: an attacker blocked by multiple creatures divides its damage **as its controller chooses** among them (`510.1c` — free division; the old "lethal-in-order" requirement no longer exists except for trample). Then **SBAs sweep the dead first** (checked before any player receives priority — `704.3`, `117.5`), then priority.
   - **First strike / double strike** (`702.7`, `702.4`, `510.4`): if any attacker or blocker has either as the step begins, there are **two** combat damage steps. Step one: only first/double strikers assign. Step two: creatures that had **neither** first nor double strike **as step one began**, plus creatures that **currently** have double strike (`702.7c` — gaining or losing first strike between the steps changes membership; "hasn't dealt damage yet" is NOT the criterion). Creatures killed in step one never deal their step-two damage — first strike math must be resolved before evaluating a block as "safe."
   - **Trample** (`702.19b`): the attacker must assign at least **lethal** damage to each blocking creature; the excess may then be divided among the blockers **and the defending player, planeswalker, or battle** as its controller chooses. Attacking a planeswalker: excess reaches the *player* only with "trample over planeswalkers" (`702.19f`) — plain trample assigns nothing to the player there. "Lethal" accounts for damage already marked and other damage being assigned this step, but ignores prevention/protection effects (assigning "wasted" lethal damage into a protected blocker to push the rest through is legal and correct).
   - **Deathtouch** (`702.2c`): any nonzero damage from a deathtouch source counts as lethal for assignment purposes — so a 4/4 trample-deathtouch attacker blocked by two creatures may assign 1 + 1 to the blockers and 2 to the player. Deathtouch kills via its own SBA (`704.5h`).
5. **End of combat** (`511`): "at end of combat" triggers; last priority window while creatures are still "attacking/blocking"; then combat ends.

If no attackers are declared, steps 3–4 are skipped (`508.8`).

## 10. Keyword Glossary

One line each; CR citations verified against the June 2026 text.

### Evergreen

| Keyword | CR | Operational meaning |
|---|---|---|
| Deathtouch | `702.2` | Any nonzero damage it deals to a creature destroys that creature (SBA `704.5h`); any nonzero assignment counts as lethal for combat math (`702.2c`). |
| Defender | `702.3` | This creature can't attack. |
| Double strike | `702.4` | Deals combat damage in both the first-strike step and the normal step (`510.4`). |
| First strike | `702.7` | Deals combat damage in an earlier, separate combat damage step; non-first-strikers that die there never deal theirs. |
| Flash | `702.8` | May be **played** any time you could cast an instant (`702.8a`) — covers casting spells AND playing lands (a flash land still consumes the land drop and uses no stack). |
| Flying | `702.9` | Can't be blocked except by creatures with flying and/or reach; may block anything. |
| Haste | `702.10` | Ignores summoning sickness: may attack and use `{T}`/`{Q}` abilities the turn it comes under your control (`302.6`). |
| Hexproof | `702.11` | Can't be targeted by spells or abilities **opponents** control (controller can still target it). |
| Indestructible | `702.12` | Can't be destroyed: immune to lethal-damage SBA and "destroy" effects; still dies to −X/−X toughness ≤ 0, sacrifice, or exile. |
| Lifelink | `702.15` | Damage it deals also causes its controller (owner, if uncontrolled — `702.15b`) to gain that much life, simultaneously with the damage (not a trigger — no response window). Multiple lifelink sources = **separate** life-gain events (`702.15e`) — matters for gain-life trigger counts. |
| Menace | `702.111` | Can't be blocked except by two or more creatures. |
| Protection from [quality] | `702.16` | Can't be **D**amaged, **E**nchanted/**E**quipped, **B**locked, or **T**argeted by anything with that quality (`702.16b–f`); damage from such sources is prevented. |
| Reach | `702.17` | Can block creatures with flying. |
| Trample | `702.19` | After assigning lethal to all blockers, excess may be divided among the blockers and the defending player/planeswalker/battle (`702.19b`); assigns everything through if blockers are gone (`702.19d`); vs a planeswalker, excess reaches the player only with trample-over-planeswalkers (`702.19f`). |
| Vigilance | `702.20` | Attacking doesn't cause it to tap. |
| Ward [cost] | `702.21` | Triggered ability: when it becomes the target of an opponent's spell/ability, counter that spell/ability unless the opponent pays the cost — a soft-hexproof tax the pilot must budget for when targeting. |

### Non-evergreen, common in Commander

| Keyword | CR | Operational meaning |
|---|---|---|
| Storm | `702.40` | Cast-trigger: copy the spell for each other spell cast before it this turn, with new targets allowed. The copies come from a trigger — countering the original doesn't stop the copies; countering/responding to the *storm trigger itself* is the standard answer. |
| Cascade | `702.85` | Cast-trigger: exile from the top until hitting a nonland card of lesser mana value; may cast it **without paying its mana cost** — only if the *resulting spell's* mana value is also less (a second check; matters for MDFC/split/adventure faces), and additional costs still apply (`702.85a`); rest to bottom in random order. Resolves *before* the cascading spell (LIFO). |
| Myriad | `702.116` | Attack-trigger: for each opponent other than the defending player, may create a tapped token copy attacking them; tokens exiled at end of combat. Turns one attack into pod-wide pressure. |
| Phasing | `702.26` | A permanent with phasing phases out/in as its controller's untap step begins (alternating — `702.26a`); while phased out it's treated as nonexistent (`702.26b`) but **no zone change occurs and no enter/leave triggers fire** (`702.26d`); counters/stickers stay on it (`702.26d`), attached Auras/Equipment phase with it (`702.26g`). A permanent phased out (by an outside effect) when a sweeper resolves survives it — but phasing itself offers no on-demand dodge; that takes an instant-speed phase-out effect. |
| Split second | `702.61` | While on the stack, no player may cast spells or activate non-mana abilities (§4). Triggers and special actions still work. |
| Buyback [cost] | `702.27` | Optional additional cost on an instant/sorcery; if paid, the spell returns to its owner's hand instead of the graveyard as it resolves — a repeatable-spell engine bounded only by mana. |
| Imprint | glossary | **Formerly a keyword, now an ability word — no rules meaning** (CR glossary: de-keyworded, all imprint cards errata'd). Marks abilities that exile a card and refer to "the exiled card" (e.g. Isochron Scepter); all behavior comes from the individual card text. |
| Monstrosity N | `701.37` | Keyword action: if this **permanent** isn't monstrous, put N +1/+1 counters on it and it becomes monstrous (`701.37a`); the flag lasts **until it leaves the battlefield** (`701.37b` — blink/bounce resets it; not a copiable value, so token copies aren't monstrous); X is locked at the time it became monstrous (`701.37c`). |
| Ferocious | `207.2c` | **Ability word — no rules meaning.** Labels abilities that improve if you control a creature with power ≥ 4; condition is checked per the card's own text. |
| Metalcraft | `207.2c` | **Ability word — no rules meaning.** Labels abilities that function/improve if you control three or more artifacts; condition per card text. |

Executor note on ability words: ferocious and metalcraft are ability words per `207.2c`, and imprint is an ability word per the CR glossary (de-keyworded); none carry rules meaning — never dispatch on the word, always parse the ability text it decorates.

---

## Sources

1. **Wizards of the Coast, *Magic: The Gathering Comprehensive Rules*, effective June 19, 2026** — media.wizards.com/2026/downloads/MagicCompRules 20260619.txt. Primary source; all rule numbers above verified against the downloaded text.
2. **Yawgatog, "Hyperlinked Magic: The Gathering Comprehensive Rules"** — yawgatog.com/resources/magic-rules/. Fan-maintained hyperlinked HTML mirror of the current CR (also June 19, 2026 edition); used for navigation/cross-checking.
3. **RulesGuru, "How to use the Comprehensive Rules"** — rulesguru.org/courses/intermediate/how-to-use-the-comprehensive-rules/. Judge-community primer consulted for source triage.
4. **Companion document:** `mtg-rules-digest-conversion.md` (this repo) — deeper treatment of priority-retention, floating mana, loops/shortcuts (CR 732), X spells (CR 107.3/601), win/loss SBAs, copies/tokens (CR 707/111), and Commander mulligans, all verified against the same CR edition.
