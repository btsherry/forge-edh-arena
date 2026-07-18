# Combo Conversion Playbook

*Format-general design reference for the Forge EDH Arena combo pilot. Everything here describes structural mechanisms, not card whitelists. Card names appear only as examples of a class. (Opus deep-research output, 2026-07-18; commissioned after the long-200 batch showed 25% fire→win conversion.)*

## 0. Framing: why a "fire" is not a win

The central failure mode in the current batch (1000 mana floating, median win turn 31, Urza 0/3) is a category error the engine inherits from casual play: **producing a huge resource and treating that as the win.** In real Commander, a combo has two halves that must both be present and both be *executed in the same window*:

1. **An engine** — the loop that produces an unbounded resource (mana, untaps, tokens, storm count, ETB/death triggers, extra turns, cards).
2. **An outlet** — a card or ability that *consumes that resource and changes the win/loss state* (opponents' life to 0, opponents' libraries to empty, your own library-to-hand followed by an alt-win, or a lethal attack).

A pilot with an engine and no outlet has done nothing. Purphoros converts at 100% precisely because its payoff (token-ETB pinging each opponent) *is* a self-contained outlet requiring no combat and no priority window beyond the ETB triggers themselves. Selvala and Urza stall because green/artifact mana is inert until spent through an outlet, and the pilot is not finding/using one. **Therefore the single most important design change is: an engine fire must immediately branch to an outlet search, and if no outlet is in hand, the mana must be spent to DIG for one (see §3).**

The rest of this document enumerates the outlet classes (§1), when to fire (§2), how to sequence conversion (§3), whom to kill (§4), how to mulligan into this plan (§5), and the exact oracle-text predicates a parser can use to detect each class (§6).

---

## 1. Outlet Taxonomy

Each outlet class below is defined by: **(a) name → (b) resource consumed → (c) example cards → (d) structural detection pattern → (e) how the win executes.** The route names in brackets map to the project's existing `LethalityPlanner` routes.

### Summary table

| Class | Consumes | Examples | Kills all 3 opponents at once? | Needs combat? | Needs priority/timing window? |
|---|---|---|---|---|---|
| 1. X-damage burn | Mana | Fireball, Comet Storm, Blaze | No (single target unless divided) | No | No (instant/sorcery on your turn) |
| 2. X-drain / each-opponent loss | Mana | Exsanguinate, Torment of Hailfire, Debt to the Deathless, Crackle with Power | **Yes** | No | No |
| 3. Repeatable ping sink | Untaps/counters/mana | Walking Ballista, Triskelion, Goblin Cannon | One-at-a-time, but unbounded | No | No |
| 4. Lifegain→damage battery | Life / spells-cast | Aetherflux Reservoir | **Yes** (repeat activations) | No | No |
| 5. Aristocrat drain triggers | Death/ETB triggers | Blood Artist, Zulaport Cutthroat, Bastion of Remembrance, Syr Konrad | **Yes** (each opponent) | No | No |
| 6. Token-ETB/attack ping | ETB/attack triggers | Purphoros, Impact Tremors, Terror of the Peaks | **Yes** | No (ETB) / Yes (attack) | No |
| 7. Storm / copy payoff | Storm count / copies | Grapeshot, Tendrils of Agony, Brain Freeze | Depends (target or each opp) | No | No (but one big turn) |
| 8. Infinite tokens + haste | Tokens + haste | Krenko, token flood + Impact Tremors/Craterhoof | Only via combat unless paired w/ §6 | **Yes** | No |
| 9. Deck-out opponents (mill) | Mana / mill triggers | Blue Sun's Zenith (at opp), Stroke of Genius, Mindcrank+Duskmantle | Yes but **delayed to their draw step** | No | No |
| 10. Alt-win on empty library | Your own draw/library | Thassa's Oracle, Laboratory Maniac, Jace WoR | **Yes (you just win)** | No | ETB/trigger window only |
| 11. Draw-your-deck (the DIG) | Mana / untaps | Blue Sun's Zenith (self), Staff of Domination, Thrasios, Stroke of Genius | Not a win — finds one | No | No |
| 12. Commander damage + pump | Pump / combat steps | Infinite +1/+1, Ezuri trample, Aggravated Assault, Godo+Helm | One player per unblocked hit | **Yes** | No |
| 13. Infinite turns | Extra-turn spells | Time Warp loop, Nexus of Fate | Not a win — soft-lock; still needs an outlet | Usually | No |

### 1.1 X-cost damage spells [DIRECT_DAMAGE_LOOP]
- **Resource:** Mana (the value of X).
- **Examples:** Fireball, Comet Storm, Blaze, Bonfire of the Damned, Fireball-with-divide, Devil's Play.
- **Structural pattern:** Instant or sorcery with `{X}` in mana cost whose text contains `deals X damage` (optionally `divided as you choose among … target`). Distinguish **single-target** (needs 3 casts or a copy, or the `divided among any number of targets` clause to hit all opponents) from **divide** variants.
- **Execution:** Same turn, on your own turn, no combat. If single-target, needs `divided`/`each opponent` wording or 3 separate resolutions to clear a 4-player table. With infinite mana, always sufficient.

### 1.2 X-drain / "each opponent loses" spells [DIRECT_DAMAGE_LOOP — preferred]
- **Resource:** Mana.
- **Examples:** Exsanguinate, Torment of Hailfire, Debt to the Deathless, Crackle with Power (5-target), Fall of the Titans.
- **Structural pattern:** `{X}` cost + `each opponent loses X life` (or `X life` drain to *each*). This is the **gold-standard mana outlet** because one resolution ends all three opponents simultaneously and bypasses damage-prevention.
- **Execution:** Same turn, no combat, no target-splitting needed. **This class should be the pilot's top-priority outlet when it holds infinite mana.**

### 1.3 Repeatable-activation ping sinks (Walking Ballista class) [DIRECT_DAMAGE_LOOP]
- **Resource:** Whatever feeds the repeatable cost — +1/+1 counters (fed by infinite mana or an untap loop), untaps, or a mana-per-shot activated ability.
- **Examples:** Walking Ballista, Triskelion, Goblin Cannon, Hex Parasite; also "pinger + untap" (e.g. any `{T}: deal 1 damage` creature under an untapper).
- **Structural pattern:** A permanent with an **activated ability** whose effect includes `deals [N] damage to any target`, where the activation cost is *repeatable* under the assembled engine: `{T}` (needs an untap source), `remove a +1/+1 counter` (needs a counter source), or a mana cost (needs infinite mana). Ballista specifically: `{4}: put a +1/+1 counter` + `Remove a +1/+1 counter: deals 1 damage to any target`.
- **Execution:** Same turn, no combat. Fire N times, one target per activation — must **loop the activation 3× per opponent-life-total** (or until dead), so the pilot needs a repeat-until-dead loop, not a single shot.

### 1.4 Lifegain→damage battery (Aetherflux Reservoir class)
- **Resource:** Life total plus **spells cast this turn** (storm-adjacent).
- **Examples:** Aetherflux Reservoir (`gain 1 life for each spell cast this turn`; `pay 50 life: deal 50 damage to any target`).
- **Structural pattern:** Permanent with an activated ability `pay N life: [that permanent] deals N damage to any target`, paired with a self-lifegain source. Under infinite lifegain, activate repeatedly; life paid is refunded by the gain trigger.
- **Execution:** Same turn, no combat, one target per activation → loop 3×.

### 1.5 Aristocrat drain triggers [DIRECT_DAMAGE_LOOP via triggers]
- **Resource:** Death triggers or ETB triggers (fed by an infinite sac/token loop).
- **Examples:** Blood Artist, Zulaport Cutthroat, Bastion of Remembrance, Cruel Celebrant, Syr Konrad, Marionette Master.
- **Structural pattern:** Static permanent with a **triggered** ability: `Whenever [a creature / another creature you control] dies, each opponent loses 1 life` (Zulaport/Bastion = *each opponent*; Blood Artist = *each* + you gain). Detect the `dies →` / `enters →` trigger whose rider is `each opponent loses` or `deals damage to each opponent`.
- **Execution:** Same turn, no combat. Requires the sac/token half of the loop to be present; the drain is automatic per iteration → all opponents die together.

### 1.6 Token-ETB / attack-trigger ping (Purphoros class) [DIRECT_DAMAGE_LOOP]
- **Resource:** Creature ETB triggers (best) or attack triggers.
- **Examples:** Purphoros (`whenever another creature enters … deals 2 damage to each opponent`), Impact Tremors, Terror of the Peaks, Warstorm Surge, Witty Roastmaster.
- **Structural pattern:** Static permanent, `Whenever [a/another creature] you control enters, [it/this] deals N damage to each opponent` (or `to any target`). This is the **best passive outlet** because with an infinite-token loop it kills the whole table with zero combat and zero priority window beyond the ETB stack. This is why the Purphoros deck converts at 100% — its detection and use are already correct; replicate that pattern for the other decks.
- **Execution:** Same turn, no combat. Trigger fires per token entering → table dies.

### 1.7 Storm / spell-copy payoffs [DIRECT_DAMAGE_LOOP or token flood]
- **Resource:** Storm count (spells cast this turn) or number of copies.
- **Examples:** Grapeshot, Tendrils of Agony (drain), Brain Freeze (mill), Empty the Warrens (tokens), Mind's Desire.
- **Structural pattern:** Text containing the keyword `Storm` (copy for each spell cast this turn) or a copy-loop payoff. The base effect determines the win vector: `deals 1 damage to any target` (Grapeshot), `each … loses 2 life` (Tendrils), `mill` (Brain Freeze).
- **Execution:** One explosive turn. Needs the storm/copy count already high; in a bounded-loop sim, model the copies as N resolutions of the base effect.

### 1.8 Infinite tokens + haste + combat [SPREAD_COMBAT]
- **Resource:** Creature tokens plus a haste grant plus a combat step.
- **Examples:** Krenko + untap, token flood + Craterhoof/Overrun (mass pump = the project's `mass_pump` payoff class), Anointed Procession stacks.
- **Structural pattern:** A repeatable token maker + `haste` source (or the tokens already have haste). Win requires **an actual attack that connects**, so also needs evasion or a `mass_pump`/trample finisher, or pairing with §1.6 to skip combat entirely.
- **Execution:** Needs the combat phase; declare attackers, survive blockers. **Fragile in multiplayer** (blockers, fogs, instant-speed wipes) — prefer routing to §1.6/§1.5 if the same board can drain without swinging.

### 1.9 Deck-out opponents / infinite mill [BANK_AND_HOLD → delayed win]
- **Resource:** Mana or repeatable mill triggers.
- **Examples:** Blue Sun's Zenith / Stroke of Genius targeting an **opponent** (X = their library), Mindcrank + Duskmantle Guildmage, Bruvac + mill, Jace's Erasure loops.
- **Structural pattern:** `{X}: target player mills X / draws X` aimed at opponents, or a `mills → damages → mills` loop. Key trap: **milling to zero does not kill; the opponent loses only when they next try to draw from an empty library.** So the win *resolves on the opponent's upkeep/draw*, one turn later, unless you also force a draw (e.g. an X-draw at them). In a 4-player game you must empty **all three** libraries or they act on their turns.
- **Execution:** Delayed by one turn cycle unless combined with a forced-draw. Weakest solo outlet in multiplayer; use only when direct-damage/drain outlets are unavailable.

### 1.10 Alt-win on empty library (Lab-Man class) [instant win]
- **Resource:** Your own library, emptied by a draw-your-deck engine (§1.11).
- **Examples:** Thassa's Oracle, Laboratory Maniac, Jace, Wielder of Mysteries, Simic Ascendancy, plus other "you win the game" cards: Approach of the Second Sun, Felidar Sovereign, Test of Endurance, Revel in Riches, Mechanized Production, Helix Pinnacle, Coalition Victory, Maze's End.
- **Structural pattern:** Text containing `you win the game` (trigger/replacement), or the anti-deck-out replacement `If you would draw from an empty library, you win instead` (Lab Man / Jace WoR), or an ETB `look at the top X … if your library has fewer cards than devotion, you win` (Thassa's Oracle). The parser should flag every card whose oracle text literally contains **"win the game"** and classify by trigger condition (empty library, life ≥ 40, 10 poison you deal, etc.).
- **Execution:** Instant on resolution/ETB. Thassa's Oracle wins *on its ETB trigger*, so it can be protected by holding priority and pointing counters at the removal, not the Oracle. **This is the most resilient, combat-free win in the format** — pair it with §1.11.

### 1.11 Draw-your-deck engines (the DIG — not a win by itself) [precursor to any route]
- **Resource:** Mana or untaps.
- **Examples:** Blue Sun's Zenith / Stroke of Genius / Pull from Tomorrow at **yourself**, Staff of Domination (`{X}: draw a card`... plus untap), Thrasios/Kenrith/Selvala/Jace commander draw pumps, Recurring Insight loops.
- **Structural pattern:** Repeatable/`{X}` `draw` effect you can point at yourself, or a permanent activated `pay mana: draw a card`. **This is the bridge that fixes the current stall.** With 1000 mana and no outlet in hand, the pilot spends mana here to draw its whole deck, *then* finds and casts an outlet from §1.1–1.10 (typically ending on Lab-Man §1.10, since drawing your deck risks decking you — so you MUST have or draw into an anti-deck-out or an immediate kill).
- **Execution:** Same turn. Draw deck → cast outlet → win, all before passing turn.

### 1.12 Commander damage + infinite pump / infinite combat [COMMANDER_DMG_SEQUENCE]
- **Resource:** Pump (counters or +X/+X) or extra combat steps.
- **Examples:** Infinite +1/+1 counters on the commander, Ezuri Renegade Leader (`regenerate/+X/+X trample`), Aggravated Assault / Combat Celebrant / Aurelia (extra combats), Godo + Helm of the Host, Rooftop Storm shenanigans.
- **Structural pattern:** Either (a) a repeatable pump targeting a creature with **evasion or trample**, or (b) an `untap all creatures … additional combat phase` effect with a repeatable cost. Voltron win = **21 commander damage to one player**, so it kills **one opponent per unblocked connection** — three swings, or trample-over, or spread across extra combats.
- **Execution:** Needs combat and an unblocked path (evasion/trample/removing blockers). Less reliable than drain in a 3-opponent field; good when the deck's payoff coverage lacks `ping_each_opponent` but has `mass_pump`/evasion.

### 1.13 Infinite turns (soft-lock engine, not a terminal outlet)
- **Resource:** Extra-turn spells recast via a loop.
- **Examples:** Time Warp + recursion, Nexus of Fate loop, Ezuri Claw + Sage of Hours.
- **Structural pattern:** `Take an extra turn` text in a repeatable loop. Crucially this is **not a win** — it is a guarantee that you get unlimited draw steps and untaps to eventually deploy a real outlet. Model it as: acquire infinite turns → each turn dig one card / develop → assemble any §1 outlet → win. If the sim can't loop turns cheaply, treat "infinite turns" as "you will win, resolve to the deck's best available outlet."

---

## 2. Fire-vs-Hold Timing

cEDH consensus on **when a skilled pilot pulls the trigger**:

1. **Fire into open mana only when protected, otherwise develop.** The dominant heuristic: *"only commit to the combo turn when you can reasonably expect to resolve it through the table's open mana."* Count each opponent's untapped mana and, specifically, **open colored mana that could be a counterspell** (open blue/black in particular). Three opponents each with open interaction is the multiplayer tax on comboing.
2. **Protection-first sequencing ("mana dork turn 1, protect the combo turn").** Deploy acceleration early (turns 1–2) but **hold up interaction on the turn you go off** — a free counter (Force of Will / Pact of Negation class) or a "protect the win" spell. Pact-style free counters are ideal for linear combo decks because they push the win through *this* turn without holding mana up.
3. **Win-attempt math (EV of attempting vs waiting).** Attempt when `P(resolve through remaining interaction) × value(winning now)` exceeds the value of waiting a full turn cycle during which three opponents each draw a card, untap, and may themselves win or find an answer. Because each extra cycle hands all three opponents fresh resources, **the EV curve is steeply decaying** — waiting is far more expensive in multiplayer than in 1v1. A ~60–70% line now usually beats a "perfect" line two turns later.
4. **Bait and exhaust before the real attempt.** Skilled pilots throw a "fake" threat or a value engine first to draw out counters, tracking who has spent interaction, then combo when the table is tapped low. The cEDH scenario literature repeatedly shows the patient player winning by *forcing opponents to exhaust interaction* before the real attempt.
5. **The "time-threat gradient."** Any win that must be answered *within the same turn it resolves* is fully stoppable by open removal — so the pilot must know its **protection window** and only fire when that window is open (opponents tapped out or its own counter-backup up). This is exactly why Thassa's-Oracle-style ETB wins are strong: the pilot holds priority on the trigger and can protect the enabler.

**Design implication:** The pilot needs a cheap `table-open-interaction` estimate (sum of opponents' untapped lands/rocks, flagged if any produce blue/black) and a `have-protection-in-hand` flag. Fire when interaction is low OR protection is held OR the EV-of-waiting is negative (e.g. an opponent is visibly one turn from their own win). Otherwise spend the turn developing/digging.

---

## 3. Conversion Sequencing (the same-turn kill order)

Given an established engine (e.g. infinite mana already on the battlefield), the optimal same-turn conversion:

**A. If an all-opponent outlet is available (best case):**
1. Fire the single-resolution table-killer first: X-drain/each-opponent (§1.2) > Purphoros-style ETB ping (§1.6) > aristocrat drain loop (§1.5). One resolution, no combat, no split. Done.

**B. If only a single-target or repeatable outlet is available:**
1. **Loop the activation to lethal on each opponent in turn** (Ballista/Fireball ×3). Model as: repeat `deals N damage to any target` until each opponent ≤ 0. Never fire once and stop.

**C. If NO outlet is in hand — the critical fix for the current 1000-mana stall:**
1. **Spend mana to DIG (§1.11): draw your deck / big X-draw at yourself / activate a draw sink.**
2. As cards are drawn, **immediately re-scan hand for any §1 outlet.** The first drawn outlet ends the game the same turn.
3. Because drawing your whole deck risks decking, the terminal outlet is usually **Lab-Man (§1.10)** — but only fire the last draw once an anti-deck-out replacement or an immediate kill is secured. If the deck has neither, stop drawing one card short and pass with a full grip + the mana banked (BANK_AND_HOLD) rather than decking yourself.
4. **If the sim can't draw the deck this turn, convert mana into board/cards every turn thereafter** — this is what human pilots do with a stranded engine: each turn, dump mana into the biggest available `draw`/`tutor`/token/impulse effect, ratcheting toward an outlet, while holding up any interaction the mana affords. A stranded engine is a slow-motion win, not a stall — the bug is a pilot that *does nothing* with the mana.

**Pre-combat vs post-combat main:**
- Deploy and fire **non-combat outlets in the pre-combat main** (drain, ping, Lab-Man) so nothing depends on surviving to a second main.
- Only pass to combat first when the plan **is** combat (§1.8/§1.12: cast haste-enabler and pump pre-combat, attack, then have a post-combat main as backup).

**Holding priority:** When a win rides on a trigger (Thassa's Oracle ETB, a drain trigger), **hold priority and stack your protection on top** so a removal spell aimed at the enabler can be countered before the trigger resolves. The pilot's stack model must support "respond to my own trigger."

**Design implication:** Add a strict conversion state machine after any engine fire: `has_all_opp_outlet? → fire once-to-table`; else `has_single_outlet? → loop-to-lethal`; else `can_draw_deck? → dig then re-enter`; else `dump-mana-into-best-cantrip/tutor-this-turn, bank rest`. The current pilot appears to stop at "engine assembled" — it must never terminate a turn with an unused engine and an unsearched library.

---

## 4. Kill Order & Threat Assessment (multiplayer heuristics)

Simple, human-approximating heuristics for whom to hit first when the outlet is *not* a simultaneous table-kill:

1. **Kill the fastest/most-threatening opponent first, not the lowest life.** "Biggest and baddest" = whoever is closest to their own win or has the most open interaction. Removing the player who would otherwise stop *you* is often worth more than removing the player with least life.
2. **Prefer the opponent with the most open interaction / open mana** when you can only knock out one — it thins the counterspell field for your next attempt.
3. **Spread vs focus:**
   - **Spread** (SPREAD_COMBAT) when your outlet hits everyone anyway (drain/ping) or when no single opponent can be finished — apply pressure so several are in range next cycle.
   - **Focus** when combat/commander-damage is the plan and only one player is reachable (lowest effective life after blockers, fewest open blockers, no obvious fog/protection).
4. **Life-total + open-blocker + commander-threat triple** as a cheap scoring function: `threat_score = w1·(their proximity-to-win) + w2·(their open interaction) − w3·(their life) − w4·(their blockers)`. Attack/kill the highest `threat_score` when focusing; ignore it when your outlet is table-wide.
5. **Political reality (informs threat weighting even for a bot):** the visibly-winning or stax player draws the table's collective removal. A pilot that presents the *smaller* visible threat survives longer, so **don't over-telegraph** — develop the win behind an innocuous board when possible, and cash it in one turn (§2) rather than durdling on a scary board that invites a coordinated response.

**Design implication:** For non-table-wide outlets, the LethalityPlanner should target by descending `threat_score`, and it should never split a lethal single-target burst across two survivors when it could kill one outright (removing a whole set of blockers/interaction).

---

## 5. Mulligan Theory for Combo Decks

Combo decks gain the most from the London/free-mulligan rule because they hunt for specific cards. Framework (after Sperling and cEDH consensus):

1. **Default question flips to "do I have a valid reason to KEEP?"** — not "is this playable?" Ship anything without an affirmative reason.
2. **Keep-strength tiers (ranked):**
   - **Tier 1 — standalone broken:** a game-winning or game-defining turn-1–2 play (fast mana + engine piece, or a turn-1 card-advantage engine). Auto-keep.
   - **Tier 2 — development:** fast mana + a critical permanent. *"Mana is the most frequent bottleneck"* — a hand with land + fast rock + accel outranks a hand with tutors but no mana.
   - **Tier 3 — interaction only:** nice, insufficient alone (stopping wins is shared work; you can't win by only interacting).
   - **Tier 4 — card advantage only / Tier 5 — "does stuff before dying":** ship.
3. **Piece-count vs land-count thresholds:** you want **mana sources + a path to the engine.** Rough keepable shape: ≥2 mana sources *and* (an engine piece **or** a tutor/dig to one). Pure land (no action) and pure action (no mana) both ship. Below ~2 lands/rocks, most hands ship regardless of spells.
4. **Dig for the engine vs keep value:** at high power, **mulligan toward the combo or toward cheap interaction, not toward "value."** There is no time for card-quality hands that merely "do things." Going to 5 (or even 4) with the combo/tutors beats a 7 that wins slowly — *"4 cards that win beat 5 cards that lose slowly."*
5. **Seat-position adjustment:** going later (3rd/4th) makes marginal hands riskier (opponents have acted first) — tighten keeps. Going first, a develop-heavy hand is stronger.
6. **Commander-specific keep:** if the engine requires the commander or a namesake piece to function (e.g. a tap-for-mana commander, a Food-Chain-style enabler), a keep must include the mana to deploy it plus at least one payoff/dig.

**Design implication:** The mulligan evaluator should score a hand on `(mana_sources, engine_pieces_or_tutors, outlet_or_dig_present, interaction)` and keep only if `mana_sources ≥ 2 AND (engine_piece OR tutor) present`; otherwise mulligan (using the free first mull liberally, and the bottoming step to shed excess lands). Crucially, **weight "has an outlet or a dig-to-outlet" as a keep reason** — a hand that assembles the engine but can never find an outlet is the batch's exact failure, reproduced at the mulligan stage.

---

## 6. Structural Detection Notes (parser predicates + traps)

Predicates operate on **oracle text + type line + mana cost**. For each class, the positive predicate and the ambiguity traps:

| Class | Positive predicate (oracle/type/cost) | Ambiguity traps |
|---|---|---|
| 1. X-damage | `{X}` in mana cost AND `deal(s) X damage`; instant/sorcery | "damage divided as you choose **among any number of targets**" = table-clear-capable; plain single-target needs 3 casts/copies. Exclude `X damage to **you**`/symmetric. |
| 2. X-drain each-opp | `{X}` AND (`each opponent loses X life` OR `X damage to each opponent`) | Distinguish `each opponent` (table-wide, ideal) from `target opponent` (single). "loses life" ignores damage prevention/indestructible — flag as premium. |
| 3. Ballista ping sink | permanent with **activated** ability: cost is `{T}`/`remove a +1/+1 counter`/mana, effect `deals N damage to any target` | Requires the *feeder* to be present (untap/counter/mana). "any target" ≠ "each opponent" — needs a **loop 3×**, not one shot. `deals damage equal to its power` needs a power lookup (see below). |
| 4. Aetherflux battery | activated `pay N life: … deals N damage to any target` + a lifegain source | Life cost must be refundable by an infinite-lifegain engine; otherwise self-kill. |
| 5. Aristocrat drain | **triggered** `whenever [a creature] dies/enters, each opponent loses N` (or `deals N to each opponent`) | Trap: `each opponent` (wins) vs `target opponent`/`you gain` only (doesn't kill). Requires a sac/token loop as feeder. |
| 6. Token-ETB ping | static/triggered `whenever [a/another] creature you control enters, deals N damage to each opponent` (or `any target`) | `each opponent` = table-clear; `any target`/`target` = loop-per-opponent. Attack-trigger variants need combat. |
| 7. Storm/copy | keyword `Storm`, or `copy … for each spell cast this turn` | The *base* effect sets the vector (damage/drain/mill/tokens) — classify by that, not by "storm" alone. |
| 8. Tokens+haste combat | repeatable `create … creature token` + `haste` (granted or on token) | Needs combat + evasion/trample/`mass_pump`. Without a §6/§5 rider, blockers/fogs stop it — mark **combat-dependent**. |
| 9. Mill / deck-out | `target player mills X`/`draws X` aimed at opponents, or `mill → damage → mill` loop | **Milling to 0 ≠ win**; win triggers on their next draw. Must empty **all three** or force a draw. Delayed by a turn cycle. |
| 10. Alt-win / Lab-Man | literal `win the game` in text; OR replacement `if you would draw from an empty library, you win`; OR devotion/library-size ETB | Condition varies (empty library, life≥40, poison, seven lands, etc.) — parse the *condition*. Thassa's Oracle wins on ETB trigger (protectable). Coalition-Victory-style needs board state. |
| 11. Draw-your-deck (dig) | repeatable/`{X}` `draw` you can target at **yourself**, or `pay mana: draw a card` | Not a win — a precursor. Must be paired with an anti-deck-out or an in-hand kill or it self-decks. |
| 12. Commander dmg / pump | repeatable pump on a creature with `flying/menace/trample/unblockable`, OR `untap all creatures … extra combat` with repeatable cost | 21-commander-damage is per-player; trample/evasion required. `deals damage equal to its power` needs a **power value in context** (base + counters + pumps) to know if lethal. |
| 13. Infinite turns | `take an extra turn` in a repeatable loop | Not terminal — resolve to the deck's best §1 outlet; if none, it's a soft-lock, not a win. |

**Cross-cutting traps for the parser:**
- **"any target" vs "each opponent":** the former hits one thing and must be *looped* to clear a table; the latter clears the table in one resolution. Tag every damage/drain effect with a `hits_all_opponents` boolean — this alone predicts whether the route is one-shot or loop-3×.
- **"deals damage equal to its power/its toughness/X counters":** the number is not literal in text — the planner must supply the runtime value (power after pumps, counters present). Never treat these as fixed N.
- **"loses life" vs "deals damage":** life loss ignores prevention, indestructibility, redirection, and most fogs — rank life-loss outlets above damage outlets for reliability.
- **Symmetric / self-including effects:** `each player`, `damage to you`, `you lose life` can kill the pilot too — require a `hits_all_opponents AND NOT hits_self` (or a life-buffer check) before firing.
- **Delayed wins (mill, some alt-wins):** flag `resolves_on_opponent_turn` so the planner doesn't score them as same-turn lethal.
- **Outlet requires a feeder:** classes 3/4/5/8 are inert without their engine half — detection must pair "outlet found" with "feeder present" before the LethalityPlanner counts the route as live.

---

## Top 10 Actionable Recommendations

Ranked by expected conversion-rate impact for the pilot. Each is stated as a format-general mechanism (cards are examples only).

1. **Never end a turn with an unused engine and an unsearched library.** After any engine fire, run a mandatory conversion state machine: table-wide outlet → single-target loop → dig-to-outlet → dump-mana-into-best-cantrip-and-bank. This directly attacks the "1000 mana floating, turn 31" stall. *(Ex: infinite mana → Blue Sun's Zenith self → find Exsanguinate.)*

2. **Detect and prioritize single-resolution table-killers.** Add a `hits_all_opponents` structural flag; when infinite mana is up, prefer an `each opponent loses X life`-class outlet above everything — one resolution ends the game with no combat, no split, no prevention. *(Ex: Exsanguinate, Torment of Hailfire.)*

3. **Implement "dig with the mana."** When no outlet is in hand, spend the engine's output on a self-targeted draw-your-deck / X-draw / draw-sink, re-scanning the hand for an outlet after each draw. Terminate on an alt-win or in-hand kill; stop one card short of decking if neither exists. *(Ex: Stroke of Genius at self → Thassa's Oracle.)*

4. **Generalize the Purphoros pattern (token-ETB / trigger pinging) to all decks.** Its 100% conversion comes from a passive, combat-free, table-wide outlet keyed off ETB triggers. Detect the `creature enters → damage/loss to each opponent` predicate everywhere and route infinite-token/infinite-ETB engines straight into it. *(Ex: Impact Tremors, Terror of the Peaks, aristocrat dies-triggers.)*

5. **Add a loop-to-lethal executor for single-target outlets.** A ping/burn outlet must be activated repeatedly until each opponent is dead, targeting by threat score — not fired once. *(Ex: Walking Ballista, Fireball ×3.)*

6. **Gate the fire on a table-open-interaction estimate + protection flag.** Compute opponents' untapped mana (flag blue/black) and whether the hand holds protection; fire when interaction is low OR protection is held OR waiting has negative EV. This prevents both premature fires into counters and infinite durdling. *(Ex: hold a Pact-style free counter for the win turn.)*

7. **Weight outlet/dig presence in the mulligan.** Keep only hands with ≥2 mana sources AND (an engine piece OR a tutor) AND ideally an outlet-or-dig-to-outlet; otherwise ship using the free mull. Do not keep hands that assemble an engine they can never cash. *(Ex: keep fast-mana + tutor over value-only 7s.)*

8. **Sequence non-combat outlets in the pre-combat main and hold priority on win triggers.** Fire drain/ping/alt-win before combat so nothing rides on reaching a second main, and stack protection on your own game-winning trigger so removal on the enabler can be answered. *(Ex: hold priority on Thassa's Oracle ETB.)*

9. **Rank outlets by reliability: life-loss > damage > combat > delayed.** Prefer "each opponent loses life" (ignores prevention) over "deals damage" over combat/commander-damage (blockers, fogs) over mill/delayed alt-wins (resolve a turn later). Encode this as a route-preference order in the LethalityPlanner. *(Ex: choose Exsanguinate over a Craterhoof swing when both are available.)*

10. **For non-table-wide routes, target by threat score and kill outright.** Attack/burn the opponent with highest `(proximity-to-win + open interaction − life − blockers)`, and never split a lethal burst across two survivors when one can be removed cleanly — thinning the interaction field for the next attempt. *(Ex: commander-damage focus on the tapped-out, low-life, open-mana opponent.)*

---

*Sources consulted: Commander Spellbook syntax/result taxonomy; Draftsim cEDH win-conditions and infinite-mana rankings; EDHREC infinite-mana outlets and combo guides; Nerd Leagues "How cEDH decks win 2026"; cardsrealm cEDH Archetypes #11 (infinite mana) and cEDH Handbook game scenarios; TopDeck/Sperling "Can I Keep This?" mulligan framework; Commander's Herald politics/threat-assessment and extra-turns pieces; MTGGoldfish/StarCityGames Aetherflux storm; MTG Salvation "what to do with infinite mana" and infinite-turns threads.*
