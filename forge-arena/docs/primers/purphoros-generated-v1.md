# Purphoros, God of the Forge — Strategy Primer (generated v1)

Mono-red, 4-player Commander. You already have every card's oracle text and both CR digests; this is the judgment layer. Imperative voice, decision-first.

## 1. Deck identity & win conditions (ranked)

You are a **noncombat-damage-to-the-face deck that wins off creature-ETB triggers**, not a creature deck. Ranked routes:

1. **ETB ping loop → all three opponents dead in one turn.** Purphoros deals 2 to *each opponent* per other-creature ETB; Agate Instigator adds 1 each; Terror of the Peaks adds that creature's power to any target. Pair with an infinite/large ETB engine (§3) and every opponent dies simultaneously at one SBA check.
2. **Multiplied burn.** Torbran (+2 per red damage event to an opponent/their permanents), Solphim (doubles noncombat damage to opponents), Twinflame Tyrant (doubles ALL damage), Ojer Axonil (floors red noncombat damage at its power) turn a 2-point Purphoros ping into 4–12+. Two multipliers plus a modest token wave is lethal without any loop. Chandra's Incinerator converts face damage into removal.
3. **Myriad combat.** Elturel Survivors, Genasi Enforcers, Gnoll War Band, Goldlust Triad, Tiamat's Fanatics, Warchief Giant hit all three opponents at once; Tannuk gives the team haste, Song of Totentanz makes a wide hasty board. Each myriad token is *created* on the battlefield, so it enters and triggers Purphoros/Agate/Terror — a myriad attack in a 4-player pod is 2 extra creature ETBs before damage, i.e. 4 to each opponent from Purphoros alone. Attacking is therefore a ping engine, not just a combat step.
4. **Commander damage: essentially never.** Purphoros is only a creature at devotion-to-red ≥ 5 and is a 6/5 with no evasion or haste. Track `damage[Purphoros][player]` per CR 903.10a but never build toward 21.

## 2. The commander — rules quirks that change play

- **Indestructible (702.12) + non-creature by default.** With devotion < 5 Purphoros is not a creature, so creature removal, board wipes hitting creatures (your own Blasphemous Act deals 13 to *each creature* — Purphoros survives either way), and "destroy target creature" all miss. He still dies to exile, sacrifice, and −X/−X. Treat him as near-unremovable: deploy him early and freely.
- **Devotion is a liability, not a goal.** Making him a creature exposes him to creature removal and combat. Count red pips before any effect that could turn him on; do not chase devotion for its own sake (Nykthos is the exception — devotion there is pure mana).
- **The ETB ability is a trigger, not a replacement.** Each qualifying creature entering makes a *separate* trigger that only reaches the stack at the next time a player would receive priority (603.2/603.3), stacking in APNAP order with everything else. Consequences: (a) opponents get a response window before *any* ping resolves; (b) in a loop, hundreds of triggers queue and resolve one at a time, each an SBA checkpoint — deaths register only at those checkpoints (704.3), and once the last opponent leaves you win immediately (104.2a), so stop.
- **"Another creature you control enters"** — tokens count, myriad tokens count, Dualcaster token copies count, Purphoros himself entering does not.
- **{2}{R} pump** is a mana sink for the combat route only; it is not part of any kill line. Do not spend combo mana on it.
- Commander tax: +{2} per prior cast from the command zone (903.8). He is indestructible, so recasts should be rare — if he is exiled or bounced, budget the tax before committing to a turn.

## 3. Combo lines

General execution rules that apply to **all** of these, from the conversion digest:
- **Do it in your own main phase.** Mana pools empty at the end of every step and phase (106.4 / 500.5), and sorcery-speed pieces (Twinflame, Jeska's Will, Mana Geyser, Devastating Onslaught, Grinning Ignus's ability) need main phase + empty stack + priority (117.1a). A ritual-fueled turn started in upkeep loses the mana at end of upkeep — never start there.
- **Never let all players pass on an empty stack** mid-line: that ends the phase and dumps your floating mana (117.4 / 500.2). Keep the stack occupied or reacquire priority via resolution (117.3b).
- **Hold priority (117.3c)** after each cast so you can stack the next piece before anyone responds. Protection goes on the stack *after* the thing it protects (LIFO, 117.7).
- Compress loops to a **fixed, pre-computed iteration count with your own stop** (732.2a; a mandatory-only loop is a draw, 104.4b). Compute iterations from lethal needed across all three opponents, not "infinite".

**A. Dualcaster Mage + Twinflame** (`{2}{R}{R}{R}`; need one creature on board). Cast Twinflame (sorcery) with one target; **holding priority**, flash in Dualcaster ({1}{R}{R}). Dualcaster's ETB copies Twinflame targeting Dualcaster; the copy makes a hasty token Dualcaster, whose ETB copies Twinflame again. Each iteration: one creature ETB → Purphoros 2 to each opponent (plus Agate/Terror/multipliers). This is the **primary kill**: cheapest, fastest, and it wins on its own with only Purphoros in play. Deploy the moment you have {2}{R}{R}{R}, Purphoros (or Terror/Agate) on board, and any creature to target. Dualcaster has flash, so you may hold it as pseudo-interaction (copy an opponent's spell) — but never keep it as interaction if the kill is available.

**B. Dualcaster Mage + Devastating Onslaught** (`{3}{R}{R}{R}`; X=1). Same shape: cast Onslaught for X=1 targeting a creature you control, hold priority, flash Dualcaster, ETB copies Onslaught targeting Dualcaster, copy makes a token Dualcaster, repeat. Identical payoff, one mana more — use it when Twinflame is missing. Tokens are sacrificed at the next end step; irrelevant, you win this turn.

**C. Devastating Onslaught (X=5) + Terror of the Peaks on battlefield** (`{10}{R}`). Not a loop — a one-shot. Five Terror tokens enter; the original triggers 5 times and each token 4 more, ~125 damage divided among up to 25 targets. **Point everything at faces**, and re-derive the target set after each elimination (800.4a happens immediately, not as an SBA; leftover triggers with only-illegal targets fizzle, 608.2b). Use this when mana is abundant but Dualcaster is unavailable.

**D. Jeska's Will + Reiterate** (`{6}{R}{R}{R}`; requires an opponent with 7+ cards in hand — check hand sizes first, and consider Wheel of Fortune / Reforge the Soul / Will of the Jeskai to *create* the condition). Cast Jeska's Will targeting that opponent; holding priority, cast Reiterate **with buyback** ({4}{R}{R}) copying it. The copy adds 7+ {R}; Reiterate returns to hand; repeat. Produces arbitrarily large red mana **inside this phase only** — spend it in the same main phase (106.4/500.5). Convert with Devastating Onslaught for large X, Song of Totentanz for X rats (all enter → Purphoros pings), or Shatterskull Smashing / Zenith Festival.

**E. Mana Geyser + Reiterate** (`{7}{R}{R}{R}{R}`; needs 7+ tapped opponent lands — best on the turn after opponents tap out, or in your postcombat main after they've spent on their turns). Same buyback loop, same phase-locality constraint, same converters. Prefer D when both are live: it is cheaper.

**F. Grinning Ignus + Runaway Steam-Kin** (`{2}{R}` plus {R} up to three counters). Steam-Kin gains a counter on each red spell cast; at three counters, remove them for {R}{R}{R}. Cast Ignus ({2}{R}) → Steam-Kin counter → activate Ignus ({R}, return to hand) for {C}{C}{R} → recast. Net-neutral mana with **infinite ETB/LTB and storm count**, which with Purphoros is directly lethal. Critical constraint: Ignus's ability is **"Activate only as a sorcery"** (602.5d) — main phase, empty stack, your turn only. Also mind summoning sickness is irrelevant (no {T} in the cost). Birgi, God of Storytelling makes this strictly better: her cast-trigger mana explicitly does *not* empty as steps and phases end.

**Deploy vs hold:** deploy the instant the line kills all three opponents through current interaction. Hold only if (a) an untapped blue opponent represents a real counterspell and you can add Boseiju / Cavern of Souls / Spider-Punk first, or (b) you are one multiplier short of lethal on the third opponent — a loop that kills two players and leaves one alive makes you the archenemy with an empty hand.

## 4. Sequencing & mulligan guidance

- **Keepable:** 3+ lands or 2 lands + a fast rock (Sol Ring, Mana Vault, Chrome Mox, Thran Dynamo, Ancient Tomb), plus either a combo piece, a tutor (Gamble, Imperial Recruiter, Reckless Handling), or a wheel. A hand with Purphoros castable by turn 3 and one damage multiplier is fine.
- **Mull:** 0–1 lands; all-expensive hands with no rock; four+ situational burn spells with no engine. **The first mulligan in a 3+ player pod is free** (103.5c) — bottom 0 cards after one mull. Take it readily to find pieces; only from the second mull on do you bottom (max(0, m−1)).
- **Turns 1–2:** land + rock. Ragavan or Norin are fine turn-1 plays; Ragavan generates Treasure and card access, Norin is a repeating "enters" trigger machine once Purphoros lands.
- **Turn 3–4:** Purphoros. He is indestructible and cheap; there is little reason to hold him. Once he resolves, every subsequent creature is 2 to each opponent — the pod's clock starts and you can play the rest of the game as a burn deck.
- **Then:** add exactly one multiplier (Torbran / Solphim / Twinflame Tyrant / Ojer Axonil) before going wide; the multiplier roughly halves the number of ETBs you need.
- **Wheels are engines, not draw:** Wheel of Fortune, Reforge the Soul, Will of the Jeskai refill you *and* set up Jeska's Will (opponents at 7 cards). Cast the wheel and the Will in the same main phase when going for line D. Razorkin Needlehead turns each wheel into 3–21 extra damage; play it before wheeling.
- Land notes: Urza's Saga sacrifices itself after III — plan around losing the land. Ruination destroys all nonbasics *including your own* (you run 3 basics); only cast it as targeted resource denial when you are ahead on board.

## 5. Threat assessment & politics

- **Pressure the player who can stop you**, not the one at lowest life: your kill hits everyone at once, so life totals barely matter until the turn you go off. The blue player holding up mana, and any player with a graveyard-hate or stax piece that blanks tokens, is the real threat.
- **Hold interaction for your own protection window, not for board policing.** Deflecting Swat is free with a commander on board — save it to redirect the counterspell or removal aimed at your combo piece, or to steal an opponent's targeted removal. Return the Favor and Flare of Duplication (free by sacrificing a nontoken red creature) do the same job. Chaos Warp and Wild Magic Surge are your only answers to a resolved problem permanent; spend them on things that hard-lock you (tax effects, damage prevention, token bans), not on value engines.
- **You are the visible threat once Purphoros resolves.** Speak softly: your damage is incidental and spread evenly, so let the pod's aggro deck draw fire. Do not tap low for marginal value — the turn you can't protect the kill is the turn it gets countered.
- **Blind spots:** (a) damage prevention and fog effects blank the entire deck — Spider-Punk's "Damage can't be prevented" and "spells and abilities can't be countered" is a near-silver-bullet, get it down before going off if a white/green opponent is representing prevention; (b) graveyard/stack interaction: you have almost no counterspell defense, so Boseiju (uncounterable instant/sorcery — covers Twinflame, Onslaught, Jeska's Will, Mana Geyser, Reiterate) and Cavern of Souls (naming Wizard covers Dualcaster) are the real protection; (c) you draw poorly outside The One Ring, Ignite the Future, Valakut Awakening and wheels — do not durdle into an empty hand; (d) mono-red cannot beat a resolved lifegain engine by attrition, so convert with a loop rather than grinding.
- **Self-damage discipline:** Ancient Tomb, Mana Vault, Treasonous Ogre (pay 3 life per {R}), The One Ring burden counters, and Boseiju all cost life. Bound the total: never win-and-lose simultaneously (104.3f) — keep life ≥1 at every SBA checkpoint inside a Treasonous-Ogre-fueled line.

## 6. Protection & tutor priorities

`protection-priorities.json` is empty — there is no card-specific protection mapping. Derive protection from the rules: **hold priority through the trigger, then answer in the window** (117.3c) — when your Dualcaster ETB or Purphoros ping is on the stack and you regain priority, cast Deflecting Swat / Return the Favor / Flare of Duplication in response; it resolves first (LIFO) and the payoff resolves after. Pre-emptive protection beats reactive: Lightning Greaves (haste + shroud, equip {0}) on a key creature, Boseiju mana into your uncounterable spell, Cavern of Souls for Dualcaster, Spider-Punk as a blanket. Note Greaves' shroud means *you* can't target it either — do not equip a creature you intend to copy with Twinflame.

Tutor targets, in weight order from `tutor-priorities.json` (Gamble — beware the random discard, so tutor when your hand is small or when you can win before the discard matters; Imperial Recruiter — creatures with power ≤ 2, which covers **Dualcaster Mage**, Grinning Ignus, Runaway Steam-Kin, Ragavan, Agate Instigator, Norin; Reckless Handling — artifacts only, plus 2 to each opponent):

1. **Dualcaster Mage / Twinflame (0.95)** — the best two-card kill. Recruiter fetches Dualcaster; Gamble fetches either.
2. **Jeska's Will / Reiterate (0.92), Mana Geyser (0.913)** — mana-explosion halves; only tutor a half if you already hold the other or can wheel into it.
3. **Birgi / Grinning Ignus (0.85)** — Birgi's non-emptying cast mana is the single best enabler for a long ritual turn; her mana survives phase boundaries where a normal pool would not.
4. **Devastating Onslaught / Terror of the Peaks / Runaway Steam-Kin (0.846)** — pick the one that completes a pair already in hand.
5. **Route payoffs (0.525)** — Chandra, Agate Instigator, Reckless Handling for the damage-loop route; Arena of Glory, Genasi Enforcers, Ragavan, Song of Totentanz, Tannuk for the spread-combat route. Tutor these only when no combo half is reachable.
6. **Purphoros himself (0.14)** — never tutor for him; the command zone always has him.
